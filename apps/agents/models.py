"""Durable global and tenant runtime suspension controls."""

from __future__ import annotations

from django.db import models

from apps.tenancy.models import Organization, TimeStampedModel


class AgentRuntimeControl(TimeStampedModel):
    """Fail-closed kill switch shared by every workflow ``agent_loop`` node."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="agent_runtime_controls",
        null=True,
        blank=True,
    )
    suspended = models.BooleanField(default=False)
    reason = models.CharField(max_length=200, blank=True)
    updated_by = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(organization__isnull=False),
                name="uniq_agent_runtime_control_org",
            ),
        ]

    def __str__(self) -> str:
        scope = "global" if self.organization_id is None else f"org:{self.organization_id}"
        state = "suspended" if self.suspended else "active"
        return f"agent-runtime-control:{scope}:{state}"
