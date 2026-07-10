"""Gated release lifecycle: fail-closed promotion and audited rollback (Sprint 6).

Promotion is denied unless the candidate has a passing evaluation bound to the exact
eval suite pinned in its manifest, and every pinned retrieval index is ready and
tenant-owned. Rollback atomically restores a previously superseded release without
rebuilding. Every allow/deny is tenant-scoped and audited.

The low-level atomic active-pointer swap stays in :func:`apps.releases.compiler.promote_release`
(used by unrelated runtime/gateway test setup); this module adds the governance gate
that the operator console and management commands call.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.evaluations.models import EvalRun, EvalStatus
from apps.identity.models import Consumer
from apps.releases.compiler import promote_release as _activate
from apps.releases.models import CanaryStatus, ReleaseCanary, ReleaseStatus, ScenarioRelease
from apps.releases.services import get_manifest_role

PROMOTABLE_STATES = frozenset({ReleaseStatus.CANDIDATE, ReleaseStatus.CANARY})
CANARYABLE_STATES = frozenset({ReleaseStatus.CANDIDATE, ReleaseStatus.CANARY})
MAX_CANARY_TTL_SECONDS = 7 * 24 * 3600


class LifecycleError(RuntimeError):
    """Raised when a lifecycle transition is not permitted. ``code`` is stable."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _audit(action: str, *, release: ScenarioRelease, actor: str, outcome: str, reason: str) -> None:
    record_event(
        actor_type="user",
        actor_id=actor,
        action=action,
        outcome=outcome,
        organization_id=release.scenario.project.organization_id,
        resource_type="scenario_release",
        resource_id=str(release.pk),
        reason=reason,
    )


def _pinned_index_ids(release: ScenarioRelease) -> list[int]:
    manifest = release.manifest if isinstance(release.manifest, dict) else {}
    raw = manifest.get("index_versions", [])
    return [int(v) for v in raw if isinstance(v, int) and not isinstance(v, bool)]


def _assert_indexes_ready(release: ScenarioRelease) -> None:
    pins = _pinned_index_ids(release)
    if not pins:
        return
    from apps.ingestion.models import IndexStatus, IndexVersion

    organization_id = release.scenario.project.organization_id
    ready = set(
        IndexVersion.objects.filter(
            id__in=pins,
            organization_id=organization_id,
            status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
        ).values_list("id", flat=True)
    )
    if ready != set(pins):
        raise LifecycleError("INDEX_NOT_READY")


def _assert_release_gate(release: ScenarioRelease, *, actor: str, action: str) -> None:
    """Fail-closed gate shared by promotion and canary exposure.

    Requires an eval suite pinned in the manifest, a passing eval bound to that suite's
    checksum, and every pinned retrieval index ready and tenant-owned. Denials audit a
    stable reason before raising.
    """
    entry = get_manifest_role(release, "eval_suite")
    if entry is None:
        _audit(action, release=release, actor=actor, outcome="deny", reason="EVAL_SUITE_NOT_PINNED")
        raise LifecycleError("EVAL_SUITE_NOT_PINNED")
    checksum = str(entry.get("checksum", ""))
    if not EvalRun.objects.filter(
        release=release, suite_checksum=checksum, status=EvalStatus.PASSED
    ).exists():
        _audit(action, release=release, actor=actor, outcome="deny", reason="EVAL_REQUIRED")
        raise LifecycleError("EVAL_REQUIRED")
    try:
        _assert_indexes_ready(release)
    except LifecycleError as exc:
        _audit(action, release=release, actor=actor, outcome="deny", reason=exc.code)
        raise


def promote(*, release: ScenarioRelease, actor: str) -> ScenarioRelease:
    """Promote a candidate/canary to active, fail-closed on the evaluation gate."""
    if release.status not in PROMOTABLE_STATES:
        raise LifecycleError("RELEASE_NOT_PROMOTABLE")
    _assert_release_gate(release, actor=actor, action="release.promote")
    with transaction.atomic():
        promoted = _activate(release)
        _audit("release.promote", release=promoted, actor=actor, outcome="allow", reason="promoted")
    return promoted


def start_canary(
    *, release: ScenarioRelease, consumer: Consumer, ttl_seconds: int, actor: str
) -> ReleaseCanary:
    """Route one consumer to an evaluated candidate for a bounded window.

    Same fail-closed gate as promotion (an unevaluated candidate is never exposed to
    real traffic). The candidate moves to ``canary`` status; the routing itself is
    consumer-scoped via the returned :class:`ReleaseCanary`.
    """
    if release.status not in CANARYABLE_STATES:
        raise LifecycleError("RELEASE_NOT_CANARYABLE")
    if ttl_seconds <= 0 or ttl_seconds > MAX_CANARY_TTL_SECONDS:
        raise LifecycleError("CANARY_TTL_INVALID")
    scenario = release.scenario
    if consumer.organization_id != scenario.project.organization_id:
        _audit(
            "release.canary_start",
            release=release,
            actor=actor,
            outcome="deny",
            reason="CANARY_CROSS_TENANT",
        )
        raise LifecycleError("CANARY_CROSS_TENANT")
    _assert_release_gate(release, actor=actor, action="release.canary_start")

    with transaction.atomic():
        if ReleaseCanary.objects.filter(
            scenario=scenario, consumer=consumer, status=CanaryStatus.ACTIVE
        ).exists():
            raise LifecycleError("CANARY_EXISTS")
        if release.status == ReleaseStatus.CANDIDATE:
            locked = ScenarioRelease.objects.select_for_update().get(pk=release.pk)
            locked.status = ReleaseStatus.CANARY
            locked.save(update_fields=["status"])
            release = locked
        canary = ReleaseCanary(
            scenario=scenario,
            consumer=consumer,
            release=release,
            expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
            created_by=actor,
        )
        canary.full_clean()
        canary.save()
        _audit(
            "release.canary_start",
            release=release,
            actor=actor,
            outcome="allow",
            reason="canary_started",
        )
    return canary


def stop_canary(*, canary: ReleaseCanary, actor: str) -> ReleaseCanary:
    """Stop an active canary; revert its release to candidate if unused elsewhere."""
    with transaction.atomic():
        locked = (
            ReleaseCanary.objects.select_for_update()
            .select_related("release", "release__scenario__project")
            .get(pk=canary.pk)
        )
        if locked.status != CanaryStatus.ACTIVE:
            raise LifecycleError("CANARY_NOT_ACTIVE")
        locked.status = CanaryStatus.STOPPED
        locked.save(update_fields=["status"])
        release = locked.release
        still_used = ReleaseCanary.objects.filter(
            release=release, status=CanaryStatus.ACTIVE
        ).exists()
        if not still_used and release.status == ReleaseStatus.CANARY:
            release.status = ReleaseStatus.CANDIDATE
            release.save(update_fields=["status"])
        _audit(
            "release.canary_stop",
            release=release,
            actor=actor,
            outcome="allow",
            reason="canary_stopped",
        )
    return locked


def rollback(*, scenario: Scenario, target: ScenarioRelease, actor: str) -> ScenarioRelease:
    """Atomically restore a previously superseded release as the active one."""
    if target.scenario_id != scenario.id:
        raise LifecycleError("TARGET_SCENARIO_MISMATCH")

    with transaction.atomic():
        # Re-read the target under lock; never trust the caller's in-memory status.
        locked_target = ScenarioRelease.objects.select_for_update().get(pk=target.pk)
        if locked_target.scenario_id != scenario.id:
            raise LifecycleError("TARGET_SCENARIO_MISMATCH")
        if locked_target.status != ReleaseStatus.SUPERSEDED:
            raise LifecycleError("TARGET_NOT_ROLLBACKABLE")

        # Free the single-active slot before activating the target.
        current = (
            ScenarioRelease.objects.select_for_update()
            .filter(scenario_id=scenario.id, status=ReleaseStatus.ACTIVE)
            .first()
        )
        if current is not None:
            current.status = ReleaseStatus.ROLLED_BACK
            current.save(update_fields=["status"])
        locked_target.status = ReleaseStatus.ACTIVE
        locked_target.promoted_at = timezone.now()
        locked_target.save(update_fields=["status", "promoted_at"])
        _audit(
            "release.rollback",
            release=locked_target,
            actor=actor,
            outcome="allow",
            reason="rolled_back",
        )
    return locked_target
