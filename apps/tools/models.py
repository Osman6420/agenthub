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
