"""PostgreSQL-authoritative ownership for unified background Run delivery."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.tenancy.context import set_tenant_context
from apps.workflows.compiler import COMPILER_VERSION
from apps.workflows.models import (
    WORKFLOW_TERMINAL_STATUSES,
    Run,
    RunCancellationState,
    RunExecutionMode,
    WorkflowRunStatus,
)

MAX_BACKGROUND_CLAIM_SECONDS = 60


class BackgroundClaimError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BackgroundClaimResult:
    outcome: str
    status: str
    checkpoint_version: int
    claim_expires_at: datetime | None


_DELIVERY_BODY_FIELDS = frozenset({"delivery_token", "run_id"})
_DELIVERY_HEADER_FIELDS = frozenset({"organization_id", "service_revision"})


@dataclass(frozen=True)
class BackgroundDelivery:
    organization_id: int
    run_id: uuid.UUID
    delivery_token: uuid.UUID
    service_revision: str


def parse_background_delivery(
    *,
    body: Mapping[str, object],
    headers: Mapping[str, object],
) -> BackgroundDelivery:
    """Validate and normalize an identifier-only broker delivery."""

    if not isinstance(body, Mapping) or set(body) != _DELIVERY_BODY_FIELDS:
        raise BackgroundClaimError("RUN_BACKGROUND_DELIVERY_BODY_INVALID")
    if not isinstance(headers, Mapping) or set(headers) != _DELIVERY_HEADER_FIELDS:
        raise BackgroundClaimError("RUN_BACKGROUND_DELIVERY_HEADERS_INVALID")
    raw_organization_id = headers["organization_id"]
    raw_service_revision = headers["service_revision"]
    if isinstance(raw_organization_id, bool) or not isinstance(raw_organization_id, (int, str)):
        raise BackgroundClaimError("RUN_BACKGROUND_DELIVERY_IDENTIFIER_INVALID")
    if (
        not isinstance(raw_service_revision, str)
        or not raw_service_revision
        or len(raw_service_revision) > 64
    ):
        raise BackgroundClaimError("RUN_BACKGROUND_DELIVERY_REVISION_INVALID")
    try:
        run_id = uuid.UUID(str(body["run_id"]))
        delivery_token = uuid.UUID(str(body["delivery_token"]))
        organization_id = int(raw_organization_id)
    except (TypeError, ValueError) as exc:
        raise BackgroundClaimError("RUN_BACKGROUND_DELIVERY_IDENTIFIER_INVALID") from exc
    if organization_id < 1:
        raise BackgroundClaimError("RUN_BACKGROUND_DELIVERY_IDENTIFIER_INVALID")
    return BackgroundDelivery(
        organization_id=organization_id,
        run_id=run_id,
        delivery_token=delivery_token,
        service_revision=raw_service_revision,
    )


def claim_background_delivery(
    *,
    body: Mapping[str, object],
    headers: Mapping[str, object],
    lease_seconds: int = 30,
) -> BackgroundClaimResult:
    """Validate an identifier-only broker delivery before claiming its Run."""

    delivery = parse_background_delivery(body=body, headers=headers)
    return claim_background_run(
        organization_id=delivery.organization_id,
        run_id=delivery.run_id,
        claim_token=delivery.delivery_token,
        lease_seconds=lease_seconds,
    )


def _validate_claim_request(*, claim_token: uuid.UUID, lease_seconds: int) -> None:
    if not isinstance(claim_token, uuid.UUID):
        raise BackgroundClaimError("RUN_BACKGROUND_CLAIM_TOKEN_INVALID")
    if (
        not isinstance(lease_seconds, int)
        or isinstance(lease_seconds, bool)
        or lease_seconds < 1
        or lease_seconds > MAX_BACKGROUND_CLAIM_SECONDS
    ):
        raise BackgroundClaimError("RUN_BACKGROUND_CLAIM_DURATION_INVALID")


def _validate_run_pins(run: Run) -> None:
    release_manifest = run.release.manifest if isinstance(run.release.manifest, dict) else {}
    if (
        run.compiler_version != COMPILER_VERSION
        or run.workflow_version.compiler_version != COMPILER_VERSION
    ):
        raise BackgroundClaimError("RUN_BACKGROUND_COMPILER_INCOMPATIBLE")
    if (
        run.compiled_checksum != run.workflow_version.checksum
        or release_manifest.get("workflow_checksum") != run.compiled_checksum
    ):
        raise BackgroundClaimError("RUN_BACKGROUND_CHECKSUM_MISMATCH")


@transaction.atomic
def claim_background_run(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    claim_token: uuid.UUID,
    lease_seconds: int,
    now: datetime | None = None,
) -> BackgroundClaimResult:
    """Claim a queued background Run without trusting broker-carried authority."""

    _validate_claim_request(claim_token=claim_token, lease_seconds=lease_seconds)
    claimed_at = now or timezone.now()
    set_tenant_context(organization_id)
    run = (
        Run.objects.select_for_update()
        .select_related("workflow_version", "release")
        .get(pk=run_id, organization_id=organization_id)
    )
    if run.execution_mode != RunExecutionMode.BACKGROUND:
        raise BackgroundClaimError("RUN_BACKGROUND_MODE_REQUIRED")
    _validate_run_pins(run)
    if run.status in WORKFLOW_TERMINAL_STATUSES:
        return BackgroundClaimResult("terminal", str(run.status), run.checkpoint_version, None)
    if run.cancellation_state == RunCancellationState.REQUESTED:
        return BackgroundClaimResult(
            "cancellation_requested", str(run.status), run.checkpoint_version, None
        )
    if claimed_at >= run.deadline_at:
        return BackgroundClaimResult(
            "deadline_exceeded", str(run.status), run.checkpoint_version, None
        )
    from apps.agents.services import runtime_suspended

    if runtime_suspended(organization_id):
        return BackgroundClaimResult("suspended", str(run.status), run.checkpoint_version, None)

    if run.background_claim_token == claim_token:
        if run.background_claim_checkpoint_version != run.checkpoint_version:
            raise BackgroundClaimError("RUN_BACKGROUND_CLAIM_STALE")
        if run.background_claim_expires_at is None or run.background_claim_expires_at <= claimed_at:
            return BackgroundClaimResult(
                ("expired" if run.status == WorkflowRunStatus.QUEUED else "recovery_required"),
                str(run.status),
                run.checkpoint_version,
                run.background_claim_expires_at,
            )
        return BackgroundClaimResult(
            "replayed",
            str(run.status),
            run.checkpoint_version,
            run.background_claim_expires_at,
        )

    if (
        run.background_claim_token is not None
        and run.background_claim_expires_at is not None
        and run.background_claim_expires_at > claimed_at
    ):
        return BackgroundClaimResult(
            "busy",
            str(run.status),
            run.checkpoint_version,
            run.background_claim_expires_at,
        )
    if run.background_claim_token is not None and run.status != WorkflowRunStatus.QUEUED:
        return BackgroundClaimResult(
            "recovery_required", str(run.status), run.checkpoint_version, None
        )
    if run.status != WorkflowRunStatus.QUEUED:
        raise BackgroundClaimError("RUN_BACKGROUND_NOT_CLAIMABLE")

    run.background_claim_token = claim_token
    run.background_claim_expires_at = min(
        claimed_at + timedelta(seconds=lease_seconds),
        run.deadline_at,
    )
    run.background_claim_checkpoint_version = run.checkpoint_version
    run.save(
        update_fields=[
            "background_claim_token",
            "background_claim_expires_at",
            "background_claim_checkpoint_version",
            "updated_at",
        ]
    )
    record_event(
        actor_type="system",
        actor_id="workflow-background-worker",
        action="workflow.run.background_claim",
        outcome="success",
        organization_id=organization_id,
        resource_type="run",
        resource_id=str(run.id),
        reason="RUN_BACKGROUND_CLAIM_ACQUIRED",
        after={
            "checkpoint_version": run.checkpoint_version,
            "status": str(run.status),
        },
    )
    return BackgroundClaimResult(
        "claimed",
        str(run.status),
        run.checkpoint_version,
        run.background_claim_expires_at,
    )


@transaction.atomic
def renew_background_claim(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    claim_token: uuid.UUID,
    expected_checkpoint_version: int,
    lease_seconds: int,
    now: datetime | None = None,
) -> datetime:
    """Renew only the exact live owner at the current checkpoint."""

    _validate_claim_request(claim_token=claim_token, lease_seconds=lease_seconds)
    renewed_at = now or timezone.now()
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(
        pk=run_id,
        organization_id=organization_id,
    )
    if run.execution_mode != RunExecutionMode.BACKGROUND:
        raise BackgroundClaimError("RUN_BACKGROUND_MODE_REQUIRED")
    if (
        run.background_claim_token != claim_token
        or run.background_claim_checkpoint_version != expected_checkpoint_version
        or run.checkpoint_version != expected_checkpoint_version
    ):
        raise BackgroundClaimError("RUN_BACKGROUND_CLAIM_STALE")
    if run.background_claim_expires_at is None or run.background_claim_expires_at <= renewed_at:
        raise BackgroundClaimError("RUN_BACKGROUND_CLAIM_EXPIRED")
    if run.status in WORKFLOW_TERMINAL_STATUSES:
        raise BackgroundClaimError("RUN_TERMINAL")
    if run.cancellation_state == RunCancellationState.REQUESTED:
        raise BackgroundClaimError("RUN_CANCELLATION_REQUESTED")
    if renewed_at >= run.deadline_at:
        raise BackgroundClaimError("RUN_DEADLINE_EXCEEDED")
    run.background_claim_expires_at = min(
        renewed_at + timedelta(seconds=lease_seconds),
        run.deadline_at,
    )
    run.save(update_fields=["background_claim_expires_at", "updated_at"])
    return run.background_claim_expires_at


@transaction.atomic
def resolve_expired_background_claim(
    *,
    organization_id: int,
    run_id: uuid.UUID,
    claim_token: uuid.UUID,
    transition_token: uuid.UUID,
    now: datetime | None = None,
) -> str:
    """Converge an expired running claim without assigning a replacement worker."""

    if not isinstance(claim_token, uuid.UUID) or not isinstance(transition_token, uuid.UUID):
        raise BackgroundClaimError("RUN_BACKGROUND_CLAIM_TOKEN_INVALID")
    resolved_at = now or timezone.now()
    set_tenant_context(organization_id)
    run = Run.objects.select_for_update().get(
        pk=run_id,
        organization_id=organization_id,
    )
    if run.execution_mode != RunExecutionMode.BACKGROUND:
        raise BackgroundClaimError("RUN_BACKGROUND_MODE_REQUIRED")
    if run.background_claim_token != claim_token:
        raise BackgroundClaimError("RUN_BACKGROUND_CLAIM_STALE")
    if run.background_claim_expires_at is None or run.background_claim_expires_at > resolved_at:
        raise BackgroundClaimError("RUN_BACKGROUND_CLAIM_NOT_EXPIRED")
    if run.status == WorkflowRunStatus.QUEUED:
        run.background_claim_token = None
        run.background_claim_expires_at = None
        run.background_claim_checkpoint_version = None
        run.save(
            update_fields=[
                "background_claim_token",
                "background_claim_expires_at",
                "background_claim_checkpoint_version",
                "updated_at",
            ]
        )
        record_event(
            actor_type="system",
            actor_id="workflow-background-worker",
            action="workflow.run.background_claim_released",
            outcome="success",
            organization_id=organization_id,
            resource_type="run",
            resource_id=str(run.id),
            reason="RUN_BACKGROUND_QUEUED_CLAIM_EXPIRED",
            after={
                "checkpoint_version": run.checkpoint_version,
                "status": str(run.status),
            },
        )
        return "released"
    if run.status in WORKFLOW_TERMINAL_STATUSES:
        return "terminal"

    from apps.workflows.transitions import transition_run

    if run.cancellation_state == RunCancellationState.REQUESTED:
        target_status = WorkflowRunStatus.CANCELLED
        awaiting_reference = ""
        reason_code = "RUN_CANCELLATION_REQUESTED"
    elif resolved_at >= run.deadline_at:
        target_status = WorkflowRunStatus.TIMED_OUT
        awaiting_reference = ""
        reason_code = "RUN_DEADLINE_EXCEEDED"
    else:
        target_status = WorkflowRunStatus.RECOVERY_REQUIRED
        awaiting_reference = "background-claim-expired"
        reason_code = "RUN_BACKGROUND_CLAIM_EXPIRED"
    result = transition_run(
        organization_id=organization_id,
        run_id=run.id,
        transition_token=transition_token,
        expected_checkpoint_version=run.checkpoint_version,
        expected_status=str(run.status),
        target_status=target_status,
        awaiting_reference=awaiting_reference,
        reason_code=reason_code,
        background_claim_token=claim_token,
    )
    return result.outcome
