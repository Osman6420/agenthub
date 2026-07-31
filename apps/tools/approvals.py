"""Durable tool-invocation lifecycle: request, human approval, and idempotent resume.

This is the stateful layer above the stateless proxy. It records a redacted, durable
`ToolInvocation`, opens an `ApprovalRequest` for tools that require one, enforces
separation of duties and a request-checksum binding on the decision, and resumes
execution exactly once. A dispatched-but-unconfirmed call becomes ``outcome_unknown``
and is never retried. Every decision and outcome is audited without secrets or payloads.

Transaction discipline: terminal-state writes and audit events are committed inside an
atomic block and any resulting error is raised *after* the block, so a fail-closed
denial or terminal outcome is never rolled back by the raising path.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer
from apps.releases.models import ScenarioRelease
from apps.tools.models import (
    TERMINAL_INVOCATION_STATUSES,
    ApprovalRequest,
    ApprovalStatus,
    ToolInvocation,
    ToolInvocationStatus,
)
from apps.tools.proxy import (
    ToolApprovalRequired,
    ToolExecutionError,
    ToolOutcomeUnknown,
    invoke_tool,
    resolve_release_tool,
    validate_tool_input,
)

APPROVAL_TTL_SECONDS = 30 * 60
_MAX_KEY_LENGTH = 128


class ToolApprovalError(ValueError):
    """Raised for safe, content-free approval/lifecycle diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _request_checksum(*, role: str, release_id: int, tool_input: dict[str, Any]) -> str:
    from apps.artifacts.validation import compute_checksum

    return compute_checksum({"role": role, "release": release_id, "input": tool_input})


def request_tool_invocation(
    *,
    release: ScenarioRelease,
    consumer: Consumer,
    role: str,
    tool_input: dict[str, Any],
    idempotency_key: str,
    consumer_capabilities: list[str],
    initiated_by_user: Any | None = None,
) -> ToolInvocation:
    if not idempotency_key or len(idempotency_key) > _MAX_KEY_LENGTH:
        raise ToolApprovalError("IDEMPOTENCY_KEY_REQUIRED")
    tool = resolve_release_tool(release, role)

    required = Capability.TOOL_CALL_SIDE_EFFECT if tool.side_effecting else Capability.TOOL_CALL
    if required not in consumer_capabilities:
        with transaction.atomic():
            _audit(
                "tool.request",
                "deny",
                consumer,
                reason="CAPABILITY_DENIED",
                actor=consumer.subject,
            )
        raise ToolApprovalError("CAPABILITY_DENIED")

    # Validate the request up front so an approver never reviews an invalid request.
    try:
        validate_tool_input(tool, tool_input)
    except ToolExecutionError as exc:
        raise ToolApprovalError(exc.code) from exc

    checksum = _request_checksum(role=role, release_id=release.id, tool_input=tool_input)
    with transaction.atomic():
        existing = (
            ToolInvocation.objects.select_for_update()
            .filter(consumer=consumer, idempotency_key=idempotency_key)
            .first()
        )
        if existing is not None:
            if existing.request_checksum != checksum or existing.release_id != release.id:
                raise ToolApprovalError("IDEMPOTENCY_CONFLICT")
            return existing

        status = (
            ToolInvocationStatus.PENDING_APPROVAL
            if tool.approval_required
            else ToolInvocationStatus.APPROVED
        )
        invocation = ToolInvocation(
            organization_id=consumer.organization_id,
            scenario=release.scenario,
            release=release,
            consumer=consumer,
            binding_role=role,
            tool_ref=tool.definition_ref,
            binding_checksum=tool.binding_checksum,
            request_checksum=checksum,
            idempotency_key=idempotency_key,
            risk=tool.risk,
            side_effecting=tool.side_effecting,
            status=status,
            redacted_input=_redact(tool_input),
        )
        invocation.full_clean()
        try:
            with transaction.atomic():
                invocation.save()
        except IntegrityError:
            winner = ToolInvocation.objects.get(consumer=consumer, idempotency_key=idempotency_key)
            if winner.request_checksum != checksum or winner.release_id != release.id:
                raise ToolApprovalError("IDEMPOTENCY_CONFLICT") from None
            return winner

        if tool.approval_required:
            ApprovalRequest.objects.create(
                organization_id=consumer.organization_id,
                invocation=invocation,
                request_checksum=checksum,
                initiated_by_user=initiated_by_user,
                status=ApprovalStatus.PENDING,
                expires_at=timezone.now() + timedelta(seconds=APPROVAL_TTL_SECONDS),
            )
            _audit(
                "tool.approval_request",
                "allow",
                consumer,
                reason="APPROVAL_PENDING",
                actor=consumer.subject,
                resource_id=str(invocation.pk),
            )
        else:
            _audit(
                "tool.request",
                "allow",
                consumer,
                reason="AUTO_APPROVED",
                actor=consumer.subject,
                resource_id=str(invocation.pk),
            )
    return invocation


def decide_approval(
    *,
    approval_id: int,
    organization_id: int,
    actor: Any,
    approve: bool,
    reason: str = "",
) -> ApprovalRequest:
    error: str | None = None
    with transaction.atomic():
        approval = (
            ApprovalRequest.objects.select_for_update()
            .filter(pk=approval_id, organization_id=organization_id)
            .first()
        )
        if approval is None:
            raise ToolApprovalError("APPROVAL_NOT_FOUND")
        if approval.status != ApprovalStatus.PENDING:
            raise ToolApprovalError("APPROVAL_NOT_PENDING")

        invocation = ToolInvocation.objects.select_for_update().get(pk=approval.invocation_id)
        now = timezone.now()
        scenario = invocation.scenario
        from apps.identity.authorization import Capability as OperatorCapability
        from apps.identity.authorization import authorize as authorize_operator

        decision = authorize_operator(
            user=actor,
            capability=OperatorCapability.SCENARIO_APPROVAL_DECIDE,
            organization=approval.organization,
            project=scenario.project,
            scenario=scenario,
        )
        actor_name = actor.get_username()
        if now >= approval.expires_at:
            approval.status = ApprovalStatus.EXPIRED
            approval.decided_at = now
            approval.save(update_fields=["status", "decided_at", "updated_at"])
            _set_invocation_terminal(invocation, ToolInvocationStatus.EXPIRED, "APPROVAL_EXPIRED")
            _audit_actor("tool.approval_decide", "deny", approval, actor_name, "APPROVAL_EXPIRED")
            error = "APPROVAL_EXPIRED"
        elif not decision.allowed:
            _audit_actor(
                "tool.approval_decide",
                "deny",
                approval,
                actor_name,
                "APPROVER_NOT_AUTHORIZED",
            )
            error = "APPROVER_NOT_AUTHORIZED"
        elif approval.initiated_by_user_id == actor.pk:
            # Human separation of duties applies only when both identities are
            # verified users. Consumer and user identifiers are distinct types.
            _audit_actor(
                "tool.approval_decide",
                "deny",
                approval,
                actor_name,
                "SELF_APPROVAL_FORBIDDEN",
            )
            error = "SELF_APPROVAL_FORBIDDEN"
        else:
            approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
            approval.decided_by_user = actor
            approval.decision_reason = reason[:64]
            approval.decided_at = now
            approval.save(
                update_fields=[
                    "status",
                    "decided_by_user",
                    "decision_reason",
                    "decided_at",
                    "updated_at",
                ]
            )
            if approve:
                invocation.status = ToolInvocationStatus.APPROVED
                invocation.save(update_fields=["status", "updated_at"])
            else:
                _set_invocation_terminal(invocation, ToolInvocationStatus.REJECTED, "REJECTED")
            _audit_actor(
                "tool.approval_decide",
                "allow",
                approval,
                actor_name,
                "APPROVED" if approve else "REJECTED",
            )
    if error is not None:
        raise ToolApprovalError(error)
    return approval


def execute_invocation(
    *,
    invocation_id: int,
    tool_input: dict[str, Any],
    consumer_capabilities: list[str],
    adapter: Any = None,
    secret_resolver: Any = None,
    dns_resolver: Any = None,
) -> ToolInvocation:
    error: str | None = None
    with transaction.atomic():
        invocation = ToolInvocation.objects.select_for_update().get(pk=invocation_id)
        # Idempotent: a terminal invocation (including outcome_unknown) is never re-run.
        if invocation.status in TERMINAL_INVOCATION_STATUSES:
            return invocation
        if invocation.status != ToolInvocationStatus.APPROVED:
            raise ToolApprovalError("NOT_APPROVED")

        # Input-swap-after-approval defense: executed input must match the approved one.
        checksum = _request_checksum(
            role=invocation.binding_role,
            release_id=invocation.release_id,
            tool_input=tool_input,
        )
        if checksum != invocation.request_checksum:
            _set_invocation_terminal(
                invocation, ToolInvocationStatus.FAILED, "REQUEST_CHECKSUM_MISMATCH"
            )
            _audit_outcome(invocation, "failure", "REQUEST_CHECKSUM_MISMATCH")
            error = "REQUEST_CHECKSUM_MISMATCH"
        else:
            tool = resolve_release_tool(invocation.release, invocation.binding_role)
            try:
                result = invoke_tool(
                    tool=tool,
                    consumer_capabilities=consumer_capabilities,
                    tool_input=tool_input,
                    adapter=adapter,
                    secret_resolver=secret_resolver,
                    dns_resolver=dns_resolver,
                    approval_granted=True,
                )
            except ToolOutcomeUnknown as exc:
                _set_invocation_terminal(invocation, ToolInvocationStatus.OUTCOME_UNKNOWN, exc.code)
                _audit_outcome(invocation, "failure", exc.code)
            except ToolApprovalRequired:
                _set_invocation_terminal(
                    invocation, ToolInvocationStatus.FAILED, "APPROVAL_REQUIRED"
                )
                _audit_outcome(invocation, "failure", "APPROVAL_REQUIRED")
                error = "APPROVAL_REQUIRED"
            except ToolExecutionError as exc:
                _set_invocation_terminal(invocation, ToolInvocationStatus.FAILED, exc.code)
                _audit_outcome(invocation, "failure", exc.code)
            else:
                invocation.status = ToolInvocationStatus.COMPLETED
                invocation.outcome_reason = "OK"
                invocation.redacted_output = _redact(result.output or {})
                invocation.finished_at = timezone.now()
                invocation.save(
                    update_fields=[
                        "status",
                        "outcome_reason",
                        "redacted_output",
                        "finished_at",
                        "updated_at",
                    ]
                )
                _audit_outcome(invocation, "success", "OK")
    if error is not None:
        raise ToolApprovalError(error)
    return invocation


@transaction.atomic
def cancel_invocation(*, invocation_id: int, organization_id: int, actor: Any) -> ToolInvocation:
    invocation = (
        ToolInvocation.objects.select_for_update()
        .filter(pk=invocation_id, organization_id=organization_id)
        .first()
    )
    if invocation is None:
        raise ToolApprovalError("INVOCATION_NOT_FOUND")
    if invocation.status in TERMINAL_INVOCATION_STATUSES:
        return invocation
    _set_invocation_terminal(invocation, ToolInvocationStatus.CANCELLED, "CANCELLED")
    approval = (
        ApprovalRequest.objects.select_for_update()
        .filter(invocation=invocation, status=ApprovalStatus.PENDING)
        .first()
    )
    if approval is not None:
        approval.status = ApprovalStatus.CANCELLED
        approval.decided_by_user = actor
        approval.decided_at = timezone.now()
        approval.save(update_fields=["status", "decided_by_user", "decided_at", "updated_at"])
    _audit_outcome(
        invocation,
        "success",
        "CANCELLED",
        actor_type="user",
        actor=actor.get_username(),
    )
    return invocation


def _set_invocation_terminal(invocation: ToolInvocation, status: str, reason: str) -> None:
    invocation.status = status
    invocation.outcome_reason = reason
    invocation.finished_at = timezone.now()
    invocation.save(update_fields=["status", "outcome_reason", "finished_at", "updated_at"])


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    return "[redacted]"


def _audit(
    action: str,
    outcome: str,
    consumer: Consumer,
    *,
    reason: str,
    actor: str,
    resource_id: str = "",
) -> None:
    record_event(
        actor_type="consumer",
        actor_id=actor,
        action=action,
        outcome=outcome,
        organization_id=consumer.organization_id,
        resource_type="tool_invocation",
        resource_id=resource_id,
        reason=reason,
    )


def _audit_actor(
    action: str, outcome: str, approval: ApprovalRequest, actor: str, reason: str
) -> None:
    record_event(
        actor_type="user",
        actor_id=actor,
        action=action,
        outcome=outcome,
        organization_id=approval.organization_id,
        resource_type="tool_approval",
        resource_id=str(approval.pk),
        reason=reason,
    )


def _audit_outcome(
    invocation: ToolInvocation,
    outcome: str,
    reason: str,
    *,
    actor_type: str = "system",
    actor: str = "runtime",
) -> None:
    record_event(
        actor_type=actor_type,
        actor_id=actor,
        action="tool.invocation_outcome",
        outcome=outcome,
        organization_id=invocation.organization_id,
        resource_type="tool_invocation",
        resource_id=str(invocation.pk),
        reason=reason,
    )
