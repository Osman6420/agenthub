"""Durable global and tenant runtime suspension controls."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from apps.tenancy.models import Organization, TimeStampedModel


class RuntimeControlScope(models.TextChoices):
    PLATFORM = "platform", "Platform"
    ORGANIZATION = "organization", "Organization"
    PROJECT = "project", "Project"
    SCENARIO = "scenario", "Scenario"


class RuntimeControlSource(models.TextChoices):
    HUMAN = "human", "Human"
    AUTOMATIC = "automatic", "Automatic"
    POLICY = "policy", "Policy"


class AgentRuntimeControl(TimeStampedModel):
    """Fail-closed hierarchical control for the unified workflow runtime."""

    scope_type = models.CharField(
        max_length=16,
        choices=RuntimeControlScope.choices,
        default=RuntimeControlScope.ORGANIZATION,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="agent_runtime_controls",
        null=True,
        blank=True,
    )
    project = models.ForeignKey(
        "catalog.AIProject",
        on_delete=models.CASCADE,
        related_name="runtime_controls",
        null=True,
        blank=True,
    )
    scenario = models.ForeignKey(
        "catalog.Scenario",
        on_delete=models.CASCADE,
        related_name="runtime_controls",
        null=True,
        blank=True,
    )
    suspended = models.BooleanField(default=False)
    reason_code = models.CharField(max_length=64, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    source = models.CharField(
        max_length=16,
        choices=RuntimeControlSource.choices,
        default=RuntimeControlSource.HUMAN,
    )
    requires_privileged_resume = models.BooleanField(default=False)
    updated_by = models.CharField(max_length=200, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scope_type=RuntimeControlScope.PLATFORM,
                        organization__isnull=True,
                        project__isnull=True,
                        scenario__isnull=True,
                    )
                    | models.Q(
                        scope_type=RuntimeControlScope.ORGANIZATION,
                        organization__isnull=False,
                        project__isnull=True,
                        scenario__isnull=True,
                    )
                    | models.Q(
                        scope_type=RuntimeControlScope.PROJECT,
                        organization__isnull=False,
                        project__isnull=False,
                        scenario__isnull=True,
                    )
                    | models.Q(
                        scope_type=RuntimeControlScope.SCENARIO,
                        organization__isnull=False,
                        project__isnull=True,
                        scenario__isnull=False,
                    )
                ),
                name="runtime_control_exact_scope",
            ),
            models.UniqueConstraint(
                fields=["scope_type"],
                condition=models.Q(scope_type=RuntimeControlScope.PLATFORM),
                name="uniq_runtime_control_platform",
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(scope_type=RuntimeControlScope.ORGANIZATION),
                name="uniq_runtime_control_org",
            ),
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(scope_type=RuntimeControlScope.PROJECT),
                name="uniq_runtime_control_project",
            ),
            models.UniqueConstraint(
                fields=["scenario"],
                condition=models.Q(scope_type=RuntimeControlScope.SCENARIO),
                name="uniq_runtime_control_scenario",
            ),
        ]

    def clean(self) -> None:
        project = self.project
        scenario = self.scenario
        if project is not None and project.organization_id != self.organization_id:
            raise ValidationError("runtime-control project organization mismatch")
        if scenario is not None and scenario.organization_id != self.organization_id:
            raise ValidationError("runtime-control scenario organization mismatch")

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Compatibility for pre-Part-7 callers that represented platform scope only as
        # ``organization=None`` and did not know about ``scope_type``.
        if (
            self._state.adding
            and self.scope_type == RuntimeControlScope.ORGANIZATION
            and self.organization_id is None
            and self.project_id is None
            and self.scenario_id is None
        ):
            self.scope_type = RuntimeControlScope.PLATFORM
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        if self.scope_type == RuntimeControlScope.PLATFORM:
            scope = "platform"
        elif self.scope_type == RuntimeControlScope.ORGANIZATION:
            scope = f"org:{self.organization_id}"
        elif self.scope_type == RuntimeControlScope.PROJECT:
            scope = f"project:{self.project_id}"
        else:
            scope = f"scenario:{self.scenario_id}"
        state = "suspended" if self.suspended else "active"
        return f"runtime-control:{scope}:{state}"
