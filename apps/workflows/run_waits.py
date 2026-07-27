"""Replay-safe durable wait ownership for the unified Run aggregate."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import jsonschema
from django.db import transaction
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.tenancy.context import set_tenant_context
from apps.workflows.models import (
    WORKFLOW_TERMINAL_STATUSES,
    Run,
    RunAwaitingKind,
    RunWait,
    RunWaitStatus,
    WorkflowRunStatus,
)
from apps.workflows.services import _redact
from apps.workflows.state_mapping import MappingError, apply_output_mapping, compile_mappings
from apps.workflows.transitions import transition_run

MAX_RESUME_PAYLOAD_BYTES = 64 * 1024
MAX_WAIT_CONFIG_BYTES = 64 * 1024
_WAIT_STATUS_BY_KIND: dict[str, str] = {
    RunAwaitingKind.APPROVAL: WorkflowRunStatus.WAITING_APPROVAL,
    RunAwaitingKind.EVENT: WorkflowRunStatus.WAITING_EVENT,
    RunAwaitingKind.HUMAN: WorkflowRunStatus.WAITING_HUMAN,
    RunAwaitingKind.TIMER: WorkflowRunStatus.WAITING_TIMER,
    RunAwaitingKind.CHILD: WorkflowRunStatus.WAITING_CHILD,
}


class RunWaitError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RunWaitCreation:
    """`suspended` carries a resume authority; `converged` means the Run left `running`."""

    outcome: str
    status: str
    checkpoint_version: int
    wait_id: uuid.UUID | None = None
    resume_token: uuid.UUID | None = None


@dataclass(frozen=True)
class RunWaitResume:
    outcome: str
    status: str
    checkpoint_version: int


RUN_TOOL_KEY_PREFIX = "run"


def run_tool_idempotency_key(run_id: uuid.UUID, node_id: str) -> str:
    """The invocation key binding one governed tool call to one unified Run node."""
    return f"{RUN_TOOL_KEY_PREFIX}:{run_id}:{node_id}"


def run_id_from_tool_idempotency_key(key: str) -> uuid.UUID | None:
    parts = key.split(":", 2)
    if len(parts) != 3 or parts[0] != RUN_TOOL_KEY_PREFIX:
        return None
    try:
        return uuid.UUID(parts[1])
    except ValueError:
        return None


@transaction.atomic
def resume_run_for_approval(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    invocation_id: int,
) -> RunWaitResume:
    """Re-admit a Run parked on a tool approval once that approval has been decided.

    The authority is durable state rather than a token: only a Run parked on exactly this
    invocation, whose invocation has actually left ``pending_approval``, is re-queued. The
    decision itself stays with the Sprint 9 approval boundary.
    """

    from apps.tools.models import ToolInvocation, ToolInvocationStatus

    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(pk=run_id, organization_id=organization_id)
    if (
        run.status != WorkflowRunStatus.WAITING_APPROVAL
        or run.awaiting_kind != RunAwaitingKind.APPROVAL
        or run.awaiting_reference != str(invocation_id)
    ):
        raise RunWaitError("RUN_WAIT_NOT_FOUND")
    decided = (
        ToolInvocation.objects.filter(pk=invocation_id, organization_id=organization_id)
        .exclude(status=ToolInvocationStatus.PENDING_APPROVAL)
        .exists()
    )
    if not decided:
        raise RunWaitError("RUN_WAIT_NOT_FOUND")
    transitioned = transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=uuid.uuid5(run.id, f"approval-resume:{invocation_id}"),
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=WorkflowRunStatus.WAITING_APPROVAL,
        target_status=WorkflowRunStatus.QUEUED,
    )
    return RunWaitResume(
        transitioned.outcome,
        transitioned.status,
        transitioned.checkpoint_version,
    )


def _token_hash(token: uuid.UUID) -> str:
    return hashlib.sha256(str(token).encode("ascii")).hexdigest()


def _bounded_json(value: Any, *, error_code: str, maximum: int) -> Any:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise RunWaitError(error_code) from None
    if len(encoded) > maximum:
        raise RunWaitError(error_code)
    return value


def _safe_roles(roles: set[str] | None) -> set[str]:
    if roles is None:
        return set()
    if any(not isinstance(role, str) or not role or len(role) > 64 for role in roles):
        raise RunWaitError("RUN_WAIT_ACTOR_INVALID")
    return set(roles)


def _audit(
    *,
    organization_id: int,
    actor_id: str,
    resource_id: str,
    outcome: str,
    reason: str,
) -> None:
    record_event(
        actor_type="consumer" if actor_id.startswith("consumer:") else "user",
        actor_id=actor_id,
        action="workflow.run_wait_resume",
        outcome=outcome,
        organization_id=organization_id,
        resource_type="run_wait",
        resource_id=resource_id,
        reason=reason,
    )


@transaction.atomic
def suspend_run_for_wait(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    claim_token: uuid.UUID,
    expected_checkpoint_version: int,
    node_id: str,
    kind: str,
    checkpoint: dict[str, Any],
    deadline_at: datetime,
    payload_schema: dict[str, Any] | None = None,
    output_mapping: list[dict[str, Any]] | None = None,
    allowed_roles: list[str] | None = None,
    deny_self_decision: bool = True,
    step_delta: int = 0,
) -> RunWaitCreation:
    """Atomically checkpoint a claimed background Run and create one resume authority."""

    set_tenant_context(organization_id)
    if kind not in _WAIT_STATUS_BY_KIND:
        raise RunWaitError("RUN_WAIT_KIND_INVALID")
    if not node_id or len(node_id) > 64:
        raise RunWaitError("RUN_WAIT_NODE_INVALID")
    if deadline_at <= timezone.now():
        raise RunWaitError("RUN_WAIT_DEADLINE_INVALID")
    schema = _bounded_json(
        payload_schema or {},
        error_code="RUN_WAIT_CONFIG_INVALID",
        maximum=MAX_WAIT_CONFIG_BYTES,
    )
    mapping = _bounded_json(
        output_mapping or [],
        error_code="RUN_WAIT_CONFIG_INVALID",
        maximum=MAX_WAIT_CONFIG_BYTES,
    )
    roles = allowed_roles or []
    if any(not isinstance(role, str) or not role or len(role) > 64 for role in roles):
        raise RunWaitError("RUN_WAIT_CONFIG_INVALID")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError:
        raise RunWaitError("RUN_WAIT_CONFIG_INVALID") from None
    if mapping:
        # Reject a protected or malformed destination now, so a valid resume payload can never
        # fail (or write server-owned state) at consumption time.
        try:
            compiled = compile_mappings(mapping, restrict_destination=True)
        except MappingError:
            raise RunWaitError("RUN_WAIT_CONFIG_INVALID") from None
        mapping = [dict(entry) for entry in compiled]

    run = Run.objects.get(pk=run_id, organization_id=organization_id)
    wait_id = uuid.uuid4()
    resume_token = uuid.uuid4()
    wait_status = _WAIT_STATUS_BY_KIND[kind]
    effective_deadline = min(deadline_at, run.deadline_at)
    transitioned = transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=uuid.uuid5(wait_id, "suspend"),
        expected_checkpoint_version=expected_checkpoint_version,
        expected_status=WorkflowRunStatus.RUNNING,
        target_status=wait_status,
        checkpoint=checkpoint,
        awaiting_reference=str(wait_id),
        step_delta=step_delta,
        background_claim_token=claim_token,
    )
    if transitioned.outcome != "committed" or transitioned.status != wait_status:
        # Cancellation, deadline or a stale claim already resolved the Run. Keep that committed
        # evidence and report it instead of raising, which would roll the transition back.
        return RunWaitCreation(
            "converged",
            transitioned.status,
            transitioned.checkpoint_version,
        )
    wait = RunWait(
        id=wait_id,
        organization_id=organization_id,
        run_id=run.id,
        kind=kind,
        node_id=node_id,
        resume_token_hash=_token_hash(resume_token),
        pending_checksum=compute_checksum(
            {
                "allowed_roles": roles,
                "compiled_checksum": run.compiled_checksum,
                "compiler_version": run.compiler_version,
                "deadline_at": effective_deadline.isoformat(),
                "deny_self_decision": bool(deny_self_decision),
                "kind": kind,
                "node_id": node_id,
                "output_mapping": mapping,
                "payload_schema": schema,
                "release_id": run.release_id,
                "run_id": str(run.id),
                "wait_id": str(wait_id),
            }
        ),
        checkpoint_version_snapshot=transitioned.checkpoint_version,
        release_id_snapshot=run.release_id,
        compiled_checksum=run.compiled_checksum,
        compiler_version=run.compiler_version,
        payload_schema=schema,
        output_mapping=mapping,
        requester_actor_id=run.actor_id,
        allowed_roles=roles,
        deny_self_decision=bool(deny_self_decision),
        deadline_at=effective_deadline,
    )
    wait.full_clean()
    wait.save()
    return RunWaitCreation(
        "suspended",
        transitioned.status,
        transitioned.checkpoint_version,
        wait.id,
        resume_token,
    )


def _consume_wait(
    *,
    run: Run,
    wait: RunWait,
    actor_id: str,
    roles: set[str],
    data: dict[str, Any],
    resume_checksum: str,
) -> tuple[RunWaitResume | None, str | None]:
    """Decide and persist one locked resume attempt, returning either a result or a code."""

    organization_id = run.organization_id
    if wait.status == RunWaitStatus.RESUMED:
        if wait.resume_checksum != resume_checksum or wait.result_checkpoint_version is None:
            _audit(
                organization_id=organization_id,
                actor_id=actor_id,
                resource_id=str(wait.id),
                outcome="deny",
                reason="RUN_WAIT_REPLAY_CONFLICT",
            )
            return None, "RUN_WAIT_REPLAY_CONFLICT"
        return (
            RunWaitResume("replayed", str(run.status), wait.result_checkpoint_version),
            None,
        )
    expected_status = _WAIT_STATUS_BY_KIND.get(wait.kind)
    if wait.status != RunWaitStatus.PENDING or expected_status is None:
        _audit(
            organization_id=organization_id,
            actor_id=actor_id,
            resource_id=str(wait.id),
            outcome="deny",
            reason="RUN_WAIT_CONSUMED",
        )
        return None, "RUN_WAIT_NOT_FOUND"
    if (
        run.status != expected_status
        or run.awaiting_reference != str(wait.id)
        or run.awaiting_kind != wait.kind
        or run.checkpoint_version != wait.checkpoint_version_snapshot
        or run.release_id != wait.release_id_snapshot
        or run.compiled_checksum != wait.compiled_checksum
        or run.compiler_version != wait.compiler_version
    ):
        _audit(
            organization_id=organization_id,
            actor_id=actor_id,
            resource_id=str(wait.id),
            outcome="deny",
            reason="RUN_WAIT_LINEAGE_MISMATCH",
        )
        return None, "RUN_WAIT_NOT_FOUND"
    now = timezone.now()
    if now >= min(wait.deadline_at, run.deadline_at):
        # A durable pause always has a finite deadline: close the wait and the Run together so no
        # Run is left waiting on an authority that can never be consumed.
        _close_wait(wait, RunWaitStatus.EXPIRED, actor_id, now)
        transition_run(
            organization_id=organization_id,
            run_id=run.id,
            transition_token=uuid.uuid5(wait.id, "expire"),
            expected_checkpoint_version=wait.checkpoint_version_snapshot,
            expected_status=expected_status,
            target_status=WorkflowRunStatus.FAILED,
            error_code="RUN_WAIT_EXPIRED",
        )
        _audit(
            organization_id=organization_id,
            actor_id=actor_id,
            resource_id=str(wait.id),
            outcome="deny",
            reason="RUN_WAIT_EXPIRED",
        )
        return None, "RUN_WAIT_NOT_FOUND"
    if wait.kind in {RunAwaitingKind.APPROVAL, RunAwaitingKind.HUMAN}:
        allowed = set(wait.allowed_roles)
        if not allowed or not roles.intersection(allowed):
            _audit(
                organization_id=organization_id,
                actor_id=actor_id,
                resource_id=str(wait.id),
                outcome="deny",
                reason="RUN_WAIT_ACTOR_NOT_AUTHORIZED",
            )
            return None, "RUN_WAIT_NOT_FOUND"
        if wait.deny_self_decision and actor_id == wait.requester_actor_id:
            _audit(
                organization_id=organization_id,
                actor_id=actor_id,
                resource_id=str(wait.id),
                outcome="deny",
                reason="RUN_WAIT_SELF_DECISION_FORBIDDEN",
            )
            return None, "RUN_WAIT_NOT_FOUND"
    try:
        jsonschema.validate(data, wait.payload_schema)
        checkpoint = apply_output_mapping(run.checkpoint, {"payload": data}, wait.output_mapping)
    except (jsonschema.ValidationError, jsonschema.SchemaError, MappingError):
        # The one-shot authority stays pending: an invalid payload must not consume the wait.
        _audit(
            organization_id=organization_id,
            actor_id=actor_id,
            resource_id=str(wait.id),
            outcome="deny",
            reason="RUN_WAIT_PAYLOAD_INVALID",
        )
        return None, "RUN_WAIT_PAYLOAD_INVALID"

    transitioned = transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=uuid.uuid5(wait.id, f"resume:{resume_checksum}"),
        expected_checkpoint_version=wait.checkpoint_version_snapshot,
        expected_status=expected_status,
        target_status=WorkflowRunStatus.QUEUED,
        checkpoint=checkpoint,
    )
    if transitioned.outcome != "committed" or transitioned.status in WORKFLOW_TERMINAL_STATUSES:
        # Cancellation or the Run deadline won the race; the wait can never be consumed again.
        _close_wait(wait, RunWaitStatus.CANCELLED, actor_id, timezone.now())
        _audit(
            organization_id=organization_id,
            actor_id=actor_id,
            resource_id=str(wait.id),
            outcome="deny",
            reason="RUN_WAIT_RUN_CONVERGED",
        )
        return (
            RunWaitResume("converged", transitioned.status, transitioned.checkpoint_version),
            None,
        )
    wait.status = RunWaitStatus.RESUMED
    wait.consumed_at = timezone.now()
    wait.consumed_by = actor_id
    wait.resume_checksum = resume_checksum
    wait.result_checkpoint_version = transitioned.checkpoint_version
    wait.redacted_payload = _redact(data)
    wait.save(
        update_fields=[
            "status",
            "consumed_at",
            "consumed_by",
            "resume_checksum",
            "result_checkpoint_version",
            "redacted_payload",
            "updated_at",
        ]
    )
    _audit(
        organization_id=organization_id,
        actor_id=actor_id,
        resource_id=str(wait.id),
        outcome="success",
        reason="RUN_WAIT_RESUMED",
    )
    return (
        RunWaitResume("committed", transitioned.status, transitioned.checkpoint_version),
        None,
    )


def _close_wait(wait: RunWait, status: str, actor_id: str, now: datetime) -> None:
    wait.status = status
    wait.consumed_at = now
    wait.consumed_by = actor_id
    wait.save(update_fields=["status", "consumed_at", "consumed_by", "updated_at"])


def resume_run_wait(
    *,
    organization_id: int,
    resume_token: uuid.UUID,
    actor_id: str,
    payload: dict[str, Any],
    actor_roles: set[str] | None = None,
) -> RunWaitResume:
    """Consume an exact wait token once and atomically queue the owning Run."""

    if not actor_id or len(actor_id) > 200:
        raise RunWaitError("RUN_WAIT_ACTOR_INVALID")
    if not isinstance(resume_token, uuid.UUID):
        raise RunWaitError("RUN_WAIT_NOT_FOUND")
    roles = _safe_roles(actor_roles)
    data = _bounded_json(
        payload,
        error_code="RUN_WAIT_PAYLOAD_INVALID",
        maximum=MAX_RESUME_PAYLOAD_BYTES,
    )
    if not isinstance(data, dict):
        raise RunWaitError("RUN_WAIT_PAYLOAD_INVALID")
    resume_checksum = compute_checksum(data)
    token_hash = _token_hash(resume_token)

    result: RunWaitResume | None = None
    error: str | None = None
    # Denials are audited inside the transaction and reported afterwards, so raising never
    # discards the evidence or a committed Run transition.
    with transaction.atomic():
        set_tenant_context(organization_id)
        candidate = RunWait.objects.filter(
            organization_id=organization_id,
            resume_token_hash=token_hash,
        ).first()
        if candidate is None:
            _audit(
                organization_id=organization_id,
                actor_id=actor_id,
                resource_id="",
                outcome="deny",
                reason="RUN_WAIT_NOT_FOUND",
            )
            error = "RUN_WAIT_NOT_FOUND"
        else:
            run = Run.objects.select_for_update().get(
                pk=candidate.run_id,
                organization_id=organization_id,
            )
            wait = RunWait.objects.select_for_update().get(
                pk=candidate.pk,
                organization_id=organization_id,
                run_id=run.id,
            )
            result, error = _consume_wait(
                run=run,
                wait=wait,
                actor_id=actor_id,
                roles=roles,
                data=data,
                resume_checksum=resume_checksum,
            )
    if error is not None:
        raise RunWaitError(error)
    if result is None:
        raise RunWaitError("RUN_WAIT_NOT_FOUND")
    return result
