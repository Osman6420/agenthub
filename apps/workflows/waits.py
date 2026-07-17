"""Transactional, replay-safe workflow wait creation and resume services."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

import jsonschema
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.identity.models import Consumer
from apps.tools.authz import resolve_actor_roles
from apps.workflows.models import (
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStatus,
    WorkflowWait,
    WorkflowWaitKind,
    WorkflowWaitStatus,
)
from apps.workflows.services import MAX_STATE_BYTES, _next_sequence, _redact
from apps.workflows.state_mapping import MappingError, apply_output_mapping

MAX_RESUME_BYTES = 65_536
WAITING_STATUSES = frozenset(
    {
        WorkflowRunStatus.WAITING_EVENT,
        WorkflowRunStatus.WAITING_HUMAN,
        WorkflowRunStatus.WAITING_TIMER,
    }
)


class WorkflowWaitError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkflowWaitError("WAIT_PAYLOAD_INVALID")
    try:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError):
        raise WorkflowWaitError("WAIT_PAYLOAD_INVALID") from None
    if len(encoded) > MAX_RESUME_BYTES:
        raise WorkflowWaitError("WAIT_PAYLOAD_TOO_LARGE")
    return payload


@transaction.atomic
def create_wait(
    *, run: WorkflowRun, node: dict[str, Any], state: dict[str, Any]
) -> tuple[WorkflowWait, str]:
    locked = (
        WorkflowRun.objects.select_for_update().select_related("workflow_version").get(pk=run.pk)
    )
    existing = WorkflowWait.objects.filter(run=locked, node_id=node["id"]).first()
    if existing is not None:
        return existing, ""
    config = node["config"]
    kind = {
        "event_wait": WorkflowWaitKind.EVENT,
        "timer": WorkflowWaitKind.TIMER,
        "human_task": WorkflowWaitKind.HUMAN,
    }[node["type"]]
    seconds = int(config.get("timeout_seconds", config.get("delay_seconds", 1)))
    deadline = timezone.now() + timedelta(seconds=seconds)
    pending_checksum = compute_checksum(
        {
            "run_id": locked.id,
            "node_id": node["id"],
            "kind": kind,
            "release_id": locked.release_id,
            "workflow_checksum": locked.workflow_version.checksum,
            "config": config,
        }
    )
    wait = WorkflowWait(
        organization_id=locked.organization_id,
        run=locked,
        kind=kind,
        node_id=node["id"],
        correlation_hash="",
        pending_checksum=pending_checksum,
        workflow_checksum=locked.workflow_version.checksum,
        release_id_snapshot=locked.release_id,
        compiler_version=locked.workflow_version.compiler_version,
        payload_schema=config.get("payload_schema", config.get("decision_schema", {})),
        output_mapping=node.get("output_mapping", []),
        requester_subject=locked.consumer.subject,
        allowed_roles=config.get("allowed_decision_roles", []),
        deny_self_decision=bool(config.get("deny_self_decision", True)),
        escalation_role=str(config.get("escalation_role", "")),
        escalation_timeout_seconds=int(config.get("escalation_timeout_seconds", 0)),
        deadline_at=deadline,
    )
    wait.full_clean()
    correlation = str(wait.public_id) if kind == WorkflowWaitKind.EVENT else ""
    if correlation:
        wait.correlation_hash = _token_hash(correlation)
    wait.save()
    locked.status = {
        WorkflowWaitKind.EVENT: WorkflowRunStatus.WAITING_EVENT,
        WorkflowWaitKind.HUMAN: WorkflowRunStatus.WAITING_HUMAN,
        WorkflowWaitKind.TIMER: WorkflowRunStatus.WAITING_TIMER,
    }[kind]
    locked.awaiting_node = node["id"]
    locked.redacted_state = _redact(state)
    if deadline > locked.deadline_at:
        locked.deadline_at = deadline
    locked.save(
        update_fields=[
            "status",
            "awaiting_node",
            "redacted_state",
            "deadline_at",
            "updated_at",
        ]
    )
    WorkflowRunEvent.objects.create(
        run=locked,
        sequence=_next_sequence(locked),
        event_type="wait_created",
        node_id=node["id"],
        outcome=str(kind),
        state_checksum=compute_checksum(_redact(state)),
    )
    return wait, correlation


def _audit(
    wait: WorkflowWait | None, *, organization_id: int, actor: str, outcome: str, reason: str
) -> None:
    record_event(
        actor_type="consumer" if actor.startswith("consumer:") else "user",
        actor_id=actor,
        action="workflow.wait_resume",
        outcome=outcome,
        organization_id=organization_id,
        resource_type="workflow_wait",
        resource_id=str(wait.run_id) if wait else "",
        reason=reason,
    )


def resume_event(*, consumer: Consumer, correlation: str, payload: Any) -> WorkflowWait:
    if not isinstance(correlation, str) or len(correlation) != 36:
        _audit(
            None,
            organization_id=consumer.organization_id,
            actor=f"consumer:{consumer.subject}",
            outcome="deny",
            reason="WAIT_TOKEN_INVALID",
        )
        raise WorkflowWaitError("WAIT_TOKEN_INVALID")
    actor = f"consumer:{consumer.subject}"
    try:
        return _resume(
            wait_filter={
                "correlation_hash": _token_hash(correlation),
                "kind": WorkflowWaitKind.EVENT,
            },
            organization_id=consumer.organization_id,
            expected_consumer_id=consumer.id,
            actor=actor,
            payload=payload,
        )
    except WorkflowWaitError as exc:
        _audit(
            None,
            organization_id=consumer.organization_id,
            actor=actor,
            outcome="deny",
            reason=exc.code,
        )
        raise


def decide_human_task(
    *, user_id: int, organization_id: int, wait_id: str, decision: Any
) -> WorkflowWait:
    user = get_user_model().objects.get(pk=user_id)
    roles = set(
        resolve_actor_roles(username=user.get_username(), organization_id=organization_id) or []
    )
    actor = str(user.get_username())
    try:
        return _resume(
            wait_filter={"public_id": wait_id, "kind": WorkflowWaitKind.HUMAN},
            organization_id=organization_id,
            expected_consumer_id=None,
            actor=actor,
            payload=decision,
            actor_roles=roles,
        )
    except WorkflowWaitError as exc:
        _audit(
            None,
            organization_id=organization_id,
            actor=actor,
            outcome="deny",
            reason=exc.code,
        )
        raise


@transaction.atomic
def _resume(
    *,
    wait_filter: dict[str, Any],
    organization_id: int,
    expected_consumer_id: int | None,
    actor: str,
    payload: Any,
    actor_roles: set[str] | None = None,
) -> WorkflowWait:
    data = _safe_payload(payload)
    wait = (
        WorkflowWait.objects.select_for_update()
        .select_related("run", "run__workflow_version")
        .filter(organization_id=organization_id, **wait_filter)
        .first()
    )
    if wait is None:
        _audit(
            None,
            organization_id=organization_id,
            actor=actor,
            outcome="deny",
            reason="WAIT_NOT_FOUND",
        )
        raise WorkflowWaitError("WAIT_NOT_FOUND")
    run = WorkflowRun.objects.select_for_update().get(
        pk=wait.run_id, organization_id=organization_id
    )
    if expected_consumer_id is not None and run.consumer_id != expected_consumer_id:
        _audit(
            wait,
            organization_id=organization_id,
            actor=actor,
            outcome="deny",
            reason="WAIT_NOT_FOUND",
        )
        raise WorkflowWaitError("WAIT_NOT_FOUND")
    if wait.status != WorkflowWaitStatus.PENDING:
        _audit(
            wait,
            organization_id=organization_id,
            actor=actor,
            outcome="deny",
            reason="WAIT_REPLAYED",
        )
        raise WorkflowWaitError("WAIT_REPLAYED")
    if run.status not in WAITING_STATUSES or run.awaiting_node != wait.node_id:
        _audit(
            wait,
            organization_id=organization_id,
            actor=actor,
            outcome="deny",
            reason="WAIT_WRONG_STATE",
        )
        raise WorkflowWaitError("WAIT_WRONG_STATE")
    if (
        run.release_id != wait.release_id_snapshot
        or run.workflow_version.checksum != wait.workflow_checksum
    ):
        _audit(
            wait,
            organization_id=organization_id,
            actor=actor,
            outcome="deny",
            reason="WAIT_LINEAGE_MISMATCH",
        )
        raise WorkflowWaitError("WAIT_LINEAGE_MISMATCH")
    if timezone.now() >= wait.deadline_at:
        wait.status = WorkflowWaitStatus.EXPIRED
        wait.consumed_at = timezone.now()
        wait.save(update_fields=["status", "consumed_at", "updated_at"])
        _audit(
            wait,
            organization_id=organization_id,
            actor=actor,
            outcome="deny",
            reason="WAIT_EXPIRED",
        )
        raise WorkflowWaitError("WAIT_EXPIRED")
    if wait.kind == WorkflowWaitKind.HUMAN:
        if not actor_roles or not actor_roles.intersection(set(wait.allowed_roles)):
            _audit(
                wait,
                organization_id=organization_id,
                actor=actor,
                outcome="deny",
                reason="WAIT_ROLE_DENIED",
            )
            raise WorkflowWaitError("WAIT_ROLE_DENIED")
        if wait.deny_self_decision and actor == wait.requester_subject:
            _audit(
                wait,
                organization_id=organization_id,
                actor=actor,
                outcome="deny",
                reason="WAIT_SELF_DECISION_DENIED",
            )
            raise WorkflowWaitError("WAIT_SELF_DECISION_DENIED")
    try:
        jsonschema.validate(data, wait.payload_schema)
        new_state = apply_output_mapping(run.redacted_state, {"payload": data}, wait.output_mapping)
    except (jsonschema.ValidationError, jsonschema.SchemaError, MappingError):
        _audit(
            wait,
            organization_id=organization_id,
            actor=actor,
            outcome="deny",
            reason="WAIT_PAYLOAD_INVALID",
        )
        raise WorkflowWaitError("WAIT_PAYLOAD_INVALID") from None
    encoded = json.dumps(new_state, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise WorkflowWaitError("WAIT_PAYLOAD_TOO_LARGE")
    now = timezone.now()
    wait.status = WorkflowWaitStatus.RESUMED
    wait.consumed_at = now
    wait.consumed_by = actor[:255]
    wait.redacted_payload = _redact(data)
    wait.save(
        update_fields=["status", "consumed_at", "consumed_by", "redacted_payload", "updated_at"]
    )
    run.redacted_state = new_state
    run.status = WorkflowRunStatus.QUEUED
    run.save(update_fields=["redacted_state", "status", "updated_at"])
    WorkflowRunEvent.objects.create(
        run=run,
        sequence=_next_sequence(run),
        event_type="wait_resumed",
        node_id=wait.node_id,
        outcome="queued",
        state_checksum=compute_checksum(new_state),
    )
    _audit(
        wait, organization_id=organization_id, actor=actor, outcome="success", reason="WAIT_RESUMED"
    )
    return wait


@transaction.atomic
def reconcile_due_waits(*, limit: int = 100) -> list[int]:
    if limit < 1 or limit > 500:
        raise WorkflowWaitError("WAIT_RECONCILE_LIMIT_INVALID")
    due = list(
        WorkflowWait.objects.select_for_update(skip_locked=True)
        .filter(status=WorkflowWaitStatus.PENDING, deadline_at__lte=timezone.now())
        .order_by("deadline_at", "pk")[:limit]
    )
    resume_ids: list[int] = []
    for wait in due:
        run = WorkflowRun.objects.select_for_update().get(pk=wait.run_id)
        if run.status not in WAITING_STATUSES or run.awaiting_node != wait.node_id:
            wait.status = WorkflowWaitStatus.CANCELLED
        elif wait.kind == WorkflowWaitKind.TIMER:
            wait.status = WorkflowWaitStatus.RESUMED
            run.status = WorkflowRunStatus.QUEUED
            resume_ids.append(run.id)
        elif (
            wait.kind == WorkflowWaitKind.HUMAN
            and wait.escalation_role
            and wait.escalated_at is None
        ):
            wait.allowed_roles = [wait.escalation_role]
            wait.escalated_at = timezone.now()
            wait.deadline_at = timezone.now() + timedelta(seconds=wait.escalation_timeout_seconds)
            if wait.deadline_at > run.deadline_at:
                run.deadline_at = wait.deadline_at
                run.save(update_fields=["deadline_at", "updated_at"])
            wait.save(
                update_fields=[
                    "allowed_roles",
                    "escalated_at",
                    "deadline_at",
                    "updated_at",
                ]
            )
            WorkflowRunEvent.objects.create(
                run=run,
                sequence=_next_sequence(run),
                event_type="wait_escalated",
                node_id=wait.node_id,
                outcome="waiting_human",
                reason_code="WAIT_ESCALATED",
            )
            continue
        else:
            wait.status = WorkflowWaitStatus.EXPIRED
            run.status = WorkflowRunStatus.TIMED_OUT
            run.error_code = "WAIT_EXPIRED"
            run.finished_at = timezone.now()
        wait.consumed_at = timezone.now()
        wait.save(update_fields=["status", "consumed_at", "updated_at"])
        run.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
        WorkflowRunEvent.objects.create(
            run=run,
            sequence=_next_sequence(run),
            event_type="wait_deadline",
            node_id=wait.node_id,
            outcome=str(wait.status),
            reason_code="WAIT_DEADLINE",
        )
    return resume_ids
