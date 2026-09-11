"""Governed scenario callability transitions.

Release promotion and scenario activation are deliberately separate commands. A release manager
must explicitly activate a ready scenario; gateway admission continues to enforce active status.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.audit.services import record_event
from apps.catalog.models import AliasStatus, LifecycleStatus, Scenario, ScenarioAlias
from apps.identity.authorization import Capability, authorize
from apps.releases.models import ReleaseStatus, ScenarioRelease


class ScenarioLifecycleError(ValueError):
    """A stable, content-free scenario lifecycle failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _actor_id(actor: Any) -> str:
    getter = getattr(actor, "get_username", None)
    return str(getter() if callable(getter) else getattr(actor, "pk", ""))[:255]


def _audit(
    *,
    scenario: Scenario,
    actor: Any,
    action: str,
    outcome: str,
    reason: str,
    request_id: str,
    before: str | None = None,
    after: str | None = None,
) -> None:
    record_event(
        actor_type="user",
        actor_id=_actor_id(actor),
        action=action,
        outcome=outcome,
        organization_id=scenario.organization_id,
        resource_type="scenario",
        resource_id=str(scenario.public_id),
        reason=reason,
        request_id=request_id,
        before={"status": before} if before is not None else None,
        after={"status": after} if after is not None else None,
    )


def _authorize_transition(*, scenario: Scenario, actor: Any, action: str, request_id: str) -> None:
    decision = authorize(
        user=actor,
        capability=Capability.SCENARIO_RELEASE,
        organization=scenario.organization,
        project=scenario.project,
        scenario=scenario,
    )
    if decision.allowed:
        return
    _audit(
        scenario=scenario,
        actor=actor,
        action=action,
        outcome="deny",
        reason=decision.reason,
        request_id=request_id,
    )
    raise ScenarioLifecycleError("SCENARIO_LIFECYCLE_FORBIDDEN")


def _transition(
    *, scenario: Scenario, actor: Any, target: str, action: str, request_id: str
) -> Scenario:
    _authorize_transition(scenario=scenario, actor=actor, action=action, request_id=request_id)
    try:
        with transaction.atomic():
            locked = (
                Scenario.objects.select_for_update()
                .select_related("organization", "project")
                .get(pk=scenario.pk)
            )
            before = locked.status
            if before == target:
                _audit(
                    scenario=locked,
                    actor=actor,
                    action=action,
                    outcome="success",
                    reason="ALREADY_IN_TARGET_STATE",
                    request_id=request_id,
                    before=before,
                    after=target,
                )
                return locked

            if target == LifecycleStatus.ACTIVE:
                # Lock readiness rows so the decision and status write share one snapshot.
                active_release = (
                    ScenarioRelease.objects.select_for_update()
                    .filter(scenario=locked, status=ReleaseStatus.ACTIVE)
                    .first()
                )
                has_active_alias = (
                    ScenarioAlias.objects.select_for_update()
                    .filter(scenario=locked, status=AliasStatus.ACTIVE)
                    .exists()
                )
                if active_release is None:
                    raise ScenarioLifecycleError("ACTIVE_RELEASE_REQUIRED")
                if not has_active_alias:
                    raise ScenarioLifecycleError("ACTIVE_ALIAS_REQUIRED")
                _assert_release_indexes_served(active_release)
                if before not in {LifecycleStatus.DRAFT, LifecycleStatus.DISABLED}:
                    raise ScenarioLifecycleError("SCENARIO_NOT_ACTIVATABLE")
            elif before != LifecycleStatus.ACTIVE:
                raise ScenarioLifecycleError("SCENARIO_NOT_DISABLEABLE")

            locked.status = target
            locked.save(update_fields=["status", "updated_at"])
            _audit(
                scenario=locked,
                actor=actor,
                action=action,
                outcome="success",
                reason="TRANSITIONED",
                request_id=request_id,
                before=before,
                after=target,
            )
            return locked
    except ScenarioLifecycleError as exc:
        _audit(
            scenario=scenario,
            actor=actor,
            action=action,
            outcome="failure",
            reason=exc.code,
            request_id=request_id,
        )
        raise


def activate_scenario(scenario: Scenario, *, actor: Any, request_id: str = "") -> Scenario:
    """Explicitly make a ready scenario callable; never called by release promotion."""
    return _transition(
        scenario=scenario,
        actor=actor,
        target=LifecycleStatus.ACTIVE,
        action="scenario.activate",
        request_id=request_id,
    )


def _assert_release_indexes_served(release: ScenarioRelease) -> None:
    manifest = release.manifest if isinstance(release.manifest, dict) else {}
    raw_pins = manifest.get("index_versions", [])
    if not isinstance(raw_pins, list) or any(
        not isinstance(value, int) or isinstance(value, bool) for value in raw_pins
    ):
        raise ScenarioLifecycleError("RELEASE_INDEX_PINS_INVALID")
    pins = set(raw_pins)
    if not pins:
        return

    from apps.documents.models import DocumentSetVersion, DocumentSetVersionStatus
    from apps.ingestion.models import IndexStatus, IndexVersion

    indexes = list(
        IndexVersion.objects.select_for_update().filter(
            pk__in=pins, organization_id=release.organization_id
        )
    )
    set_version_ids = {
        index.document_set_version_id
        for index in indexes
        if index.document_set_version_id is not None
    }
    served_versions = {
        version.pk: version
        for version in DocumentSetVersion.objects.select_for_update().filter(pk__in=set_version_ids)
    }
    if {index.pk for index in indexes} != pins or any(
        not index.store_ready
        or index.status != IndexStatus.ACTIVE
        or index.document_set_version_id not in served_versions
        or served_versions[index.document_set_version_id].organization_id != release.organization_id
        or served_versions[index.document_set_version_id].status != DocumentSetVersionStatus.ACTIVE
        or served_versions[index.document_set_version_id].built_index_version_id != index.pk
        for index in indexes
    ):
        raise ScenarioLifecycleError("RELEASE_INDEX_NOT_SERVED")


def disable_scenario(scenario: Scenario, *, actor: Any, request_id: str = "") -> Scenario:
    """Stop new consumer admission without mutating the active release."""
    return _transition(
        scenario=scenario,
        actor=actor,
        target=LifecycleStatus.DISABLED,
        action="scenario.disable",
        request_id=request_id,
    )
