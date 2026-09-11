"""Bounded, actor-bound preview and atomic scenario access transitions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.services import record_event
from apps.catalog.models import AIProject, Scenario, ScenarioAccessMode
from apps.identity.assignment_services import AssignmentError
from apps.identity.authorization import (
    _BASIC_SCENARIO_ROLES,
    _GLOBAL_ADMIN_CAPABILITIES,
    _ORGANIZATION_ADMIN_CAPABILITIES,
    _ORGANIZATION_AUDITOR_CAPABILITIES,
    Capability,
    _active_assignments,
    _project_capabilities,
    _scenario_capabilities,
    authorize,
)
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    PlatformResponsibility,
    PlatformResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization, OrganizationMembership

_SALT = "agenthub.scenario-access.v1"
_MAX_MEMBERS = 500


@dataclass(frozen=True)
class AccessGrant:
    membership_id: int
    role: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class AccessDelta:
    membership_id: int
    username: str
    gained: tuple[str, ...]
    lost: tuple[str, ...]


@dataclass(frozen=True)
class AccessPreview:
    token: str
    previous_mode: str
    target_mode: str
    changes: tuple[AccessDelta, ...]
    grants: tuple[AccessGrant, ...]


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require_manager(actor: Any, scenario: Scenario) -> None:
    if (
        scenario.organization.status != "active"
        or not authorize(
            user=actor, capability=Capability.SCENARIO_ACCESS_MANAGE, scenario=scenario
        ).allowed
    ):
        raise AssignmentError("SCENARIO_ACCESS_MANAGEMENT_REQUIRED")


def _audit_denial(
    scenario: Scenario, actor: Any, code: str, request_id: str, trace_id: str
) -> None:
    record_event(
        actor_type="user",
        actor_id=actor.get_username(),
        organization_id=scenario.organization_id,
        action="responsibility.scenario.access_changed",
        outcome="deny",
        resource_type="scenario",
        resource_id=str(scenario.public_id),
        reason=code,
        request_id=request_id,
        trace_id=trace_id,
    )


def _grants(mode: str, grants: tuple[AccessGrant, ...]) -> list[dict[str, Any]]:
    if mode not in {ScenarioAccessMode.INHERIT, ScenarioAccessMode.PRIVATE}:
        raise AssignmentError("INVALID_ACCESS_MODE")
    if len(grants) > _MAX_MEMBERS or (mode == ScenarioAccessMode.INHERIT and grants):
        raise AssignmentError("INVALID_ACCESS_ASSIGNMENTS")
    return _serialize_grants(grants, _BASIC_SCENARIO_ROLES)


def _serialize_grants(
    grants: tuple[AccessGrant, ...], roles: frozenset[str]
) -> list[dict[str, Any]]:
    if len(grants) > _MAX_MEMBERS:
        raise AssignmentError("INVALID_ACCESS_ASSIGNMENTS")
    seen = set()
    result = []
    for grant in grants:
        if (
            not isinstance(grant.membership_id, int)
            or isinstance(grant.membership_id, bool)
            or grant.membership_id <= 0
            or grant.membership_id in seen
            or grant.role not in roles
        ):
            raise AssignmentError("INVALID_ACCESS_ASSIGNMENTS")
        if grant.expires_at is not None and (
            not isinstance(grant.expires_at, datetime)
            or timezone.is_naive(grant.expires_at)
            or grant.expires_at <= timezone.now()
        ):
            raise AssignmentError("INVALID_ACCESS_EXPIRY")
        seen.add(grant.membership_id)
        result.append(
            {
                "membership_id": grant.membership_id,
                "role": grant.role,
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            }
        )
    return sorted(result, key=lambda row: row["membership_id"])


def _snapshot(scenario: Scenario) -> tuple[list[OrganizationMembership], dict[str, Any], str]:
    return _scope_snapshot(scenario.project, scenario)


def _scope_snapshot(
    project: AIProject, scenario: Scenario | None = None
) -> tuple[list[OrganizationMembership], dict[str, Any], str]:
    members = list(
        OrganizationMembership.objects.filter(
            organization_id=project.organization_id,
            status="active",
            user__is_active=True,
            user__is_superuser=False,
        )
        .select_related("user")
        .order_by("pk")[: _MAX_MEMBERS + 1]
    )
    if len(members) > _MAX_MEMBERS:
        raise AssignmentError("ACCESS_PREVIEW_TOO_LARGE")
    ids = [member.pk for member in members]
    common = {"organization_id": project.organization_id, "membership_id__in": ids}
    scenario_scope: dict[str, Any] = (
        {"scenario": scenario} if scenario else {"scenario__project": project}
    )
    scopes = {
        "organization": OrganizationResponsibilityAssignment.objects.filter(**common),
        "project": ProjectResponsibilityAssignment.objects.filter(**common, project_id=project.pk),
        "scenario": ScenarioResponsibilityAssignment.objects.filter(**common, **scenario_scope),
    }
    state: dict[str, Any] = {
        "mode": scenario.access_mode if scenario else "project",
        "revision": scenario.access_revision if scenario else project.access_revision,
        "project_id": project.pk,
        "organization_id": project.organization_id,
        "members": [(member.pk, member.user_id) for member in members],
    }
    for scope, queryset in scopes.items():
        fields = ["pk", "membership_id", "responsibility", "expires_at"]
        if scope == "scenario":
            fields.append("scenario_id")
        rows = list(_active_assignments(queryset).order_by("pk").values(*fields)[:5001])
        if len(rows) > 5000:
            raise AssignmentError("ACCESS_PREVIEW_TOO_LARGE")
        for row in rows:
            row["expires_at"] = row["expires_at"].isoformat() if row["expires_at"] else None
        state[scope] = rows
    if scenario is None:
        state["scenarios"] = list(
            Scenario.objects.filter(project=project, organization_id=project.organization_id)
            .order_by("pk")
            .values("pk", "name", "access_mode", "access_revision")[:201]
        )
        if len(state["scenarios"]) > 200:
            raise AssignmentError("ACCESS_PREVIEW_TOO_LARGE")
    state["platform_users"] = list(
        PlatformResponsibilityAssignment.objects.filter(
            user_id__in=[member.user_id for member in members],
            status="active",
            responsibility=PlatformResponsibility.GLOBAL_ADMINISTRATOR,
        )
        .order_by("user_id")
        .values_list("user_id", flat=True)
    )
    return members, state, _hash(state)


def _validate_continuity(
    members: list[OrganizationMembership],
    state: dict[str, Any],
    mode: str,
    grants: list[dict[str, Any]],
) -> None:
    member_ids = {member.pk for member in members}
    if any(row["membership_id"] not in member_ids for row in grants):
        raise AssignmentError("ELIGIBLE_ORGANIZATION_MEMBER_REQUIRED")
    if mode == "private":
        if not any(
            row["role"] == ScenarioResponsibility.MANAGER and row["expires_at"] is None
            for row in grants
        ):
            raise AssignmentError("LAST_SCENARIO_MANAGER")
    elif not any(
        row["responsibility"] == ProjectResponsibility.MANAGER and row["expires_at"] is None
        for row in state["project"]
    ):
        raise AssignmentError("LAST_PROJECT_MANAGER")


def _capabilities(
    member: OrganizationMembership,
    state: dict[str, Any],
    mode: str,
    grants: list[dict[str, Any]] | None,
) -> set[Capability]:
    result = {Capability.ORGANIZATION_VIEW}
    if member.user_id in state["platform_users"]:
        result.update(_GLOBAL_ADMIN_CAPABILITIES)
    for row in state["organization"]:
        if row["membership_id"] == member.pk:
            if row["responsibility"] == OrganizationResponsibility.ADMINISTRATOR:
                result.update(_ORGANIZATION_ADMIN_CAPABILITIES)
            elif row["responsibility"] == OrganizationResponsibility.AUDITOR:
                result.update(_ORGANIZATION_AUDITOR_CAPABILITIES)
    for row in state["project"]:
        if row["membership_id"] == member.pk:
            result.update(_project_capabilities(row["responsibility"], mode))
    for row in state["scenario"]:
        if row["membership_id"] == member.pk and not (
            grants is not None and row["responsibility"] in _BASIC_SCENARIO_ROLES
        ):
            result.update(_scenario_capabilities(row["responsibility"], mode))
    for row in grants or []:
        if row["membership_id"] == member.pk:
            result.update(_scenario_capabilities(row["role"], mode))
    return result


@transaction.atomic
def preview_scenario_access(
    *, scenario: Scenario, actor: Any, mode: str, grants: tuple[AccessGrant, ...] = ()
) -> AccessPreview:
    set_tenant_context(scenario.organization_id)
    scenario = Scenario.objects.select_related("organization", "project").get(
        pk=scenario.pk, organization_id=scenario.organization_id
    )
    _require_manager(actor, scenario)
    requested = _grants(mode, grants)
    members, state, baseline = _snapshot(scenario)
    _validate_continuity(members, state, mode, requested)
    changes = []
    for member in members:
        before = _capabilities(member, state, scenario.access_mode, None)
        after = _capabilities(member, state, mode, requested if mode == "private" else None)
        if before != after:
            changes.append(
                AccessDelta(
                    member.pk,
                    member.user.get_username(),
                    tuple(sorted(after - before)),
                    tuple(sorted(before - after)),
                )
            )
    payload = {
        "actor": actor.pk,
        "scenario": scenario.pk,
        "organization": scenario.organization_id,
        "baseline": baseline,
        "mode": mode,
        "grants": requested,
    }
    return AccessPreview(
        signing.dumps(payload, salt=_SALT), scenario.access_mode, mode, tuple(changes), grants
    )


def apply_scenario_access(
    *, scenario: Scenario, actor: Any, token: str, request_id: str = "", trace_id: str = ""
) -> Scenario:
    try:
        if not isinstance(token, str) or len(token) > 150_000:
            raise signing.BadSignature()
        payload = signing.loads(token, salt=_SALT, max_age=600)
        if (
            payload["actor"] != actor.pk
            or payload["scenario"] != scenario.pk
            or payload["organization"] != scenario.organization_id
        ):
            raise signing.BadSignature()
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        _audit_denial(scenario, actor, "ACCESS_PREVIEW_INVALID_OR_EXPIRED", request_id, trace_id)
        raise AssignmentError("ACCESS_PREVIEW_INVALID_OR_EXPIRED") from exc
    try:
        with transaction.atomic():
            set_tenant_context(scenario.organization_id)
            Organization.objects.select_for_update().get(pk=scenario.organization_id)
            current = (
                Scenario.objects.select_for_update()
                .select_related("organization", "project")
                .get(pk=scenario.pk, organization_id=scenario.organization_id)
            )
            _require_manager(actor, current)
            change_id = hashlib.sha256(token.encode()).hexdigest()
            if current.access_change_id == change_id:
                return current
            members, state, baseline = _snapshot(current)
            if baseline != payload["baseline"]:
                raise AssignmentError("ACCESS_PREVIEW_STALE")
            grants = tuple(
                AccessGrant(
                    row["membership_id"],
                    row["role"],
                    parse_datetime(row["expires_at"]) if row["expires_at"] else None,
                )
                for row in payload["grants"]
            )
            requested = _grants(payload["mode"], grants)
            _validate_continuity(members, state, payload["mode"], requested)
            if payload["mode"] == "private":
                chosen = {(grant.membership_id, grant.role): grant for grant in grants}
                for (
                    assignment
                ) in ScenarioResponsibilityAssignment.objects.select_for_update().filter(
                    scenario=current, responsibility__in=_BASIC_SCENARIO_ROLES
                ):
                    grant = chosen.pop((assignment.membership_id, assignment.responsibility), None)
                    if grant is not None:
                        assignment.status = "active"
                        assignment.assigned_by = actor
                        assignment.expires_at = grant.expires_at
                        assignment.revoked_at = assignment.revoked_by = None
                        assignment.save()
                    elif assignment.status == "active":
                        # Revocation must also work for an already inactive member; it
                        # cannot require eligibility to receive a new assignment.
                        ScenarioResponsibilityAssignment.objects.filter(pk=assignment.pk).update(
                            status="revoked",
                            revoked_by=actor,
                            revoked_at=timezone.now(),
                            updated_at=timezone.now(),
                        )
                for grant in chosen.values():
                    ScenarioResponsibilityAssignment.objects.create(
                        scenario=current,
                        organization_id=current.organization_id,
                        membership_id=grant.membership_id,
                        responsibility=grant.role,
                        expires_at=grant.expires_at,
                        assigned_by=actor,
                    )
            previous_mode = current.access_mode
            current.access_mode = payload["mode"]
            current.access_revision += 1
            current.access_change_id = change_id
            current.save(
                update_fields=["access_mode", "access_revision", "access_change_id", "updated_at"]
            )
            record_event(
                actor_type="user",
                actor_id=actor.get_username(),
                organization_id=current.organization_id,
                action="responsibility.scenario.access_changed",
                outcome="success",
                resource_type="scenario",
                resource_id=str(current.public_id),
                reason="ACCESS_PREVIEW_APPLIED",
                request_id=request_id,
                trace_id=trace_id,
                before={"mode": previous_mode, "revision": current.access_revision - 1},
                after={
                    "mode": current.access_mode,
                    "revision": current.access_revision,
                    "change_id": change_id,
                    "grants": requested,
                },
            )
            return current
    except AssignmentError as exc:
        _audit_denial(scenario, actor, exc.code, request_id, trace_id)
        raise
