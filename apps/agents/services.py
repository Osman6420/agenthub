"""Agent compilation and durable run request/cancel services.

Mirrors the Sprint 8 workflow services: compilation stays inside the scenario's
organization and reads only pinned artifact versions; run requests are idempotent on
``(consumer, idempotency_key)`` with a request-checksum conflict check; state is redacted
before it is ever persisted. The runtime and Celery task consume the durable rows these
services create — they never trust request payloads directly.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.agents.compiler import COMPILER_VERSION, AgentCompileError, compile_agent
from apps.agents.limits import MAX_CHECKPOINT_BYTES, resolve_limits
from apps.agents.models import (
    AgentRun,
    AgentRunEvent,
    AgentRunStatus,
    AgentRuntimeControl,
    AgentVersion,
)
from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.gateway.execution_context import verify_execution_context
from apps.identity.models import Consumer
from apps.releases.models import ScenarioRelease
from apps.releases.services import get_artifact_body_for_role, get_manifest_role


class AgentRequestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@transaction.atomic
def compile_agent_version(
    *, scenario: Scenario, source_artifact: ArtifactVersion, created_by: str
) -> AgentVersion:
    organization_id = scenario.project.organization_id
    if source_artifact.organization_id != organization_id:
        raise AgentCompileError("agent artifact belongs to another organization")
    if source_artifact.type != ArtifactType.AGENT_DEFINITION:
        raise AgentCompileError("source artifact is not an agent definition")

    compiled = compile_agent(source_artifact.body)
    existing = AgentVersion.objects.filter(
        scenario=scenario,
        source_artifact=source_artifact,
        compiler_version=COMPILER_VERSION,
    ).first()
    if existing is not None:
        if existing.checksum != compiled.checksum:
            raise AgentCompileError("compiled agent checksum conflict")
        return existing
    return AgentVersion.objects.create(
        organization_id=organization_id,
        scenario=scenario,
        source_artifact=source_artifact,
        compiled_config=compiled.config,
        checksum=compiled.checksum,
        compiler_version=COMPILER_VERSION,
        created_by=created_by,
    )


def resolve_release_agent(release: ScenarioRelease) -> AgentVersion:
    entry = get_manifest_role(release, "agent_definition")
    body = get_artifact_body_for_role(release, "agent_definition")
    if entry is None or body is None:
        raise AgentCompileError("release does not pin an agent definition")
    ref = str(entry.get("ref", ""))
    if ":v" not in ref:
        raise AgentCompileError("release agent reference is invalid")
    logical_id, _, version_text = ref.rpartition(":v")
    if not version_text.isdigit():
        raise AgentCompileError("release agent reference is invalid")
    artifact = ArtifactVersion.objects.filter(
        organization_id=release.scenario.project.organization_id,
        type=ArtifactType.AGENT_DEFINITION,
        logical_id=logical_id,
        version=int(version_text),
        checksum=str(entry.get("checksum", "")),
    ).first()
    if artifact is None:
        raise AgentCompileError("release agent artifact is unresolved")
    return compile_agent_version(
        scenario=release.scenario,
        source_artifact=artifact,
        created_by="release-runtime",
    )


@transaction.atomic
def request_agent_run(
    *,
    release: ScenarioRelease,
    consumer: Consumer,
    agent_version: AgentVersion,
    execution_context: dict[str, Any],
    input_payload: dict[str, Any],
    idempotency_key: str,
) -> tuple[AgentRun, bool]:
    if not idempotency_key or len(idempotency_key) > 128:
        raise AgentRequestError("IDEMPOTENCY_KEY_REQUIRED")
    verify_execution_context(execution_context)
    input_checksum = compute_checksum(input_payload)
    existing = (
        AgentRun.objects.select_for_update()
        .filter(consumer=consumer, idempotency_key=idempotency_key)
        .first()
    )
    if existing is not None:
        if existing.input_checksum != input_checksum or existing.release_id != release.id:
            raise AgentRequestError("IDEMPOTENCY_CONFLICT")
        return existing, False

    limits = resolve_limits(agent_version.compiled_config.get("limits"))
    snapshot = {"input": _redact(input_payload), "limits": limits.as_dict()}
    _assert_checkpoint_size(snapshot)
    run = AgentRun(
        organization_id=consumer.organization_id,
        scenario=release.scenario,
        release=release,
        agent_version=agent_version,
        consumer=consumer,
        idempotency_key=idempotency_key,
        input_checksum=input_checksum,
        execution_context=execution_context,
        start_snapshot=snapshot,
        checkpoint=dict(snapshot),
        status=AgentRunStatus.QUEUED,
        deadline_at=timezone.now() + timedelta(seconds=limits.deadline_seconds),
    )
    run.full_clean(exclude=["public_id"])
    try:
        with transaction.atomic():
            run.save()
    except IntegrityError:
        winner = AgentRun.objects.get(consumer=consumer, idempotency_key=idempotency_key)
        if winner.input_checksum != input_checksum or winner.release_id != release.id:
            raise AgentRequestError("IDEMPOTENCY_CONFLICT") from None
        return winner, False
    AgentRunEvent.objects.create(
        run=run,
        sequence=1,
        event_type="run_queued",
        outcome="queued",
        state_checksum=compute_checksum(snapshot),
    )
    return run, True


@transaction.atomic
def cancel_agent_run(*, run: AgentRun, consumer: Consumer) -> AgentRun:
    locked = AgentRun.objects.select_for_update().get(pk=run.pk)
    if locked.consumer_id != consumer.id or locked.organization_id != consumer.organization_id:
        raise AgentRequestError("RUN_NOT_FOUND")
    return _cancel_locked(locked)


@transaction.atomic
def operator_cancel_agent_run(*, run: AgentRun, organization_id: int, actor: str) -> AgentRun:
    """Tenant-scoped operator cancellation (console/management command).

    Unlike the consumer path this is an administrative action, so it is audited with the
    operator identity. Cancellation is idempotent and never resurrects a terminal run.
    """
    locked = AgentRun.objects.select_for_update().get(pk=run.pk)
    if locked.organization_id != organization_id:
        raise AgentRequestError("RUN_NOT_FOUND")
    cancelled = _cancel_locked(locked)
    record_event(
        actor_type="user",
        actor_id=actor,
        action="agent.cancel",
        outcome="success",
        organization_id=organization_id,
        resource_type="agent_run",
        resource_id=str(cancelled.public_id),
        reason=str(cancelled.status),
    )
    return cancelled


def _cancel_locked(locked: AgentRun) -> AgentRun:
    if locked.status in {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.TIMED_OUT,
    }:
        return locked
    if locked.status != AgentRunStatus.CANCELLED:
        locked.status = AgentRunStatus.CANCELLED
        locked.finished_at = timezone.now()
        locked.save(update_fields=["status", "finished_at", "updated_at"])
        AgentRunEvent.objects.create(
            run=locked,
            sequence=_next_sequence(locked),
            event_type="run_cancelled",
            outcome="cancelled",
        )
    return locked


def runtime_suspended(organization_id: int) -> bool:
    """True when the global or this organization's agent-runtime kill switch is set.

    Filters organization explicitly (global ``NULL`` row OR this org's row) so the check is
    correct under both the RLS-bypassing owner role (CI/local) and a non-owner production
    role where the manual RLS policy also exposes the global row.
    """
    return AgentRuntimeControl.objects.filter(
        Q(organization__isnull=True) | Q(organization_id=organization_id),
        suspended=True,
    ).exists()


@transaction.atomic
def set_runtime_suspension(
    *, organization_id: int | None, suspended: bool, actor: str, reason: str = ""
) -> AgentRuntimeControl:
    """Flip the global (``organization_id=None``) or per-organization kill switch.

    A role-gated audited platform-operator action (invoked by the management commands),
    never a consumer action. Idempotent and upsert-safe on the scope singleton.
    """
    lookup: dict[str, Any] = {"organization_id": organization_id}
    control, _ = AgentRuntimeControl.objects.select_for_update().get_or_create(
        defaults={"suspended": suspended, "updated_by": actor, "reason": reason[:200]},
        **lookup,
    )
    control.suspended = suspended
    control.updated_by = actor
    control.reason = reason[:200]
    control.save(update_fields=["suspended", "updated_by", "reason", "updated_at"])
    record_event(
        actor_type="user",
        actor_id=actor,
        action="agent.runtime_suspend" if suspended else "agent.runtime_resume",
        outcome="success",
        organization_id=organization_id,
        resource_type="agent_runtime_control",
        resource_id="global" if organization_id is None else str(organization_id),
        reason=reason[:64] or ("suspended" if suspended else "resumed"),
    )
    return control


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    return "[redacted]"


def _assert_checkpoint_size(state: dict[str, Any]) -> None:
    size = len(json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > MAX_CHECKPOINT_BYTES:
        raise AgentRequestError("AGENT_STATE_TOO_LARGE")


def _next_sequence(run: AgentRun) -> int:
    latest = run.events.order_by("-sequence").values_list("sequence", flat=True).first()
    return int(latest or 0) + 1
