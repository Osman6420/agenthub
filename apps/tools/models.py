"""Tenant-scoped registry of approved tool definitions and scenario bindings.

A ``ToolDefinition`` records one platform-reviewed outbound destination and its
risk posture; a ``ToolBinding`` attaches a definition to a tenant's release with an
approval policy. Bodies are immutable once registered (a change is a new artifact
version and a new row); only ``status`` may flip so a platform admin can disable a
tool without deleting the auditable record. Execution/egress is enforced later by
the proxy — these models are the default-deny registry it consults.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from apps.tenancy.models import Organization, TimeStampedModel

# Fields that may change on an already-registered row; the immutable body cannot.
_MUTABLE_FIELDS = frozenset({"status", "updated_at"})


class ToolStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class ToolRisk(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class _ImmutableBodyModel(TimeStampedModel):
    """Base enforcing write-once body with a status-only mutation path."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            update_fields = set(kwargs.get("update_fields") or [])
            if not update_fields or not update_fields <= _MUTABLE_FIELDS:
                raise ValueError(f"{type(self).__name__} body is immutable; only status may change")
        super().save(*args, **kwargs)


class ToolDefinition(_ImmutableBodyModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="tool_definitions"
    )
    logical_id = models.CharField(max_length=128)
    version = models.PositiveIntegerField()
    manifest = models.JSONField()
    checksum = models.CharField(max_length=64)
    protocol = models.CharField(max_length=16)
    risk = models.CharField(max_length=16, choices=ToolRisk.choices)
    side_effecting = models.BooleanField()
    status = models.CharField(max_length=16, choices=ToolStatus.choices, default=ToolStatus.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "logical_id", "version"],
                name="uniq_tool_definition_org_logical_version",
            )
        ]

    def __str__(self) -> str:
        return f"tool:{self.organization_id}:{self.logical_id}:v{self.version}"

    @property
    def requires_approval(self) -> bool:
        """High-risk side-effecting tools always require human approval."""
        return self.side_effecting and self.risk == ToolRisk.HIGH


class ToolBinding(_ImmutableBodyModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="tool_bindings"
    )
    tool_definition = models.ForeignKey(
        ToolDefinition, on_delete=models.PROTECT, related_name="bindings"
    )
    logical_id = models.CharField(max_length=128)
    version = models.PositiveIntegerField()
    manifest = models.JSONField()
    checksum = models.CharField(max_length=64)
    approval_required = models.BooleanField()
    status = models.CharField(max_length=16, choices=ToolStatus.choices, default=ToolStatus.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "logical_id", "version"],
                name="uniq_tool_binding_org_logical_version",
            )
        ]

    def __str__(self) -> str:
        return f"tool-binding:{self.organization_id}:{self.logical_id}:v{self.version}"

    def clean(self) -> None:
        if self.tool_definition_id and self.organization_id != self.tool_definition.organization_id:
            raise ValidationError("tool binding organization must match its definition")


class ToolInvocationStatus(models.TextChoices):
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    APPROVED = "approved", "Approved"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected"
    FAILED = "failed", "Failed"
    OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


# Statuses from which no further execution or decision may occur.
TERMINAL_INVOCATION_STATUSES = frozenset(
    {
        ToolInvocationStatus.COMPLETED,
        ToolInvocationStatus.REJECTED,
        ToolInvocationStatus.FAILED,
        ToolInvocationStatus.OUTCOME_UNKNOWN,
        ToolInvocationStatus.CANCELLED,
        ToolInvocationStatus.EXPIRED,
    }
)


class ToolInvocation(TimeStampedModel):
    """A durable, redacted, idempotent record of one tool-call attempt."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="tool_invocations"
    )
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.PROTECT, related_name="tool_invocations"
    )
    release = models.ForeignKey(
        "releases.ScenarioRelease", on_delete=models.PROTECT, related_name="tool_invocations"
    )
    consumer = models.ForeignKey(
        "identity.Consumer", on_delete=models.PROTECT, related_name="tool_invocations"
    )
    binding_role = models.CharField(max_length=128)
    tool_ref = models.CharField(max_length=160)
    binding_checksum = models.CharField(max_length=64)
    request_checksum = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    risk = models.CharField(max_length=16)
    side_effecting = models.BooleanField()
    status = models.CharField(
        max_length=20,
        choices=ToolInvocationStatus.choices,
        default=ToolInvocationStatus.PENDING_APPROVAL,
    )
    outcome_reason = models.CharField(max_length=64, blank=True)
    redacted_input = models.JSONField(default=dict, blank=True)
    redacted_output = models.JSONField(default=dict, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "idempotency_key"],
                name="uniq_tool_invocation_consumer_idempotency",
            )
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]

    def __str__(self) -> str:
        return f"tool-invocation:{self.pk}:{self.status}"

    def clean(self) -> None:
        organization_id = self.organization_id
        if self.scenario_id and organization_id != self.scenario.project.organization_id:
            raise ValidationError("invocation scenario must match invocation organization")
        if self.release_id and self.release.scenario_id != self.scenario_id:
            raise ValidationError("invocation release must match invocation scenario")
        if self.consumer_id and self.consumer.organization_id != organization_id:
            raise ValidationError("invocation consumer must match invocation organization")


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class ApprovalRequest(TimeStampedModel):
    """Human approval bound to one invocation's exact request checksum."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="tool_approval_requests"
    )
    invocation = models.OneToOneField(
        ToolInvocation, on_delete=models.PROTECT, related_name="approval"
    )
    request_checksum = models.CharField(max_length=64)
    approver_roles = models.JSONField(default=list)
    requested_by = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )
    decided_by = models.CharField(max_length=200, blank=True)
    decision_reason = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status", "expires_at"])]

    def __str__(self) -> str:
        return f"tool-approval:{self.pk}:{self.status}"

    def clean(self) -> None:
        if self.invocation_id and self.organization_id != self.invocation.organization_id:
            raise ValidationError("approval organization must match its invocation")
