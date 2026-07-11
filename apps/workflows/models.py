"""Immutable compiled workflows and durable tenant-scoped async runs."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.tenancy.models import Organization, TimeStampedModel


class CustomNodeStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class CustomNodeDefinition(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="custom_node_definitions"
    )
    logical_id = models.CharField(max_length=128)
    version = models.PositiveIntegerField()
    manifest = models.JSONField()
    checksum = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=CustomNodeStatus.choices, default=CustomNodeStatus.ACTIVE
    )
    installed_package_version = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "logical_id", "version"],
                name="uniq_custom_node_org_logical_version",
            )
        ]

    def __str__(self) -> str:
        return f"custom-node:{self.organization_id}:{self.logical_id}:v{self.version}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is not None:
            raise ValueError("CustomNodeDefinition is immutable")
        super().save(*args, **kwargs)


class WorkflowVersion(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_versions"
    )
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.CASCADE, related_name="workflow_versions"
    )
    source_artifact = models.ForeignKey(
        "artifacts.ArtifactVersion", on_delete=models.PROTECT, related_name="compiled_workflows"
    )
    compiled_graph = models.JSONField()
    checksum = models.CharField(max_length=64)
    compiler_version = models.CharField(max_length=32, default="workflow-compiler/v1")
    created_by = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "source_artifact", "compiler_version"],
                name="uniq_compiled_workflow_source",
            )
        ]

    def __str__(self) -> str:
        return f"workflow:{self.scenario_id}:{self.checksum[:12]}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is not None:
            raise ValueError("WorkflowVersion is immutable")
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        if self.scenario_id and self.organization_id != self.scenario.project.organization_id:
            raise ValidationError("workflow organization must match scenario organization")
        if self.source_artifact_id and self.organization_id != self.source_artifact.organization_id:
            raise ValidationError("workflow artifact must match workflow organization")


class WorkflowRunStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    TIMED_OUT = "timed_out", "Timed out"
    CANCELLED = "cancelled", "Cancelled"


class WorkflowRun(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_runs"
    )
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.CASCADE, related_name="workflow_runs"
    )
    release = models.ForeignKey(
        "releases.ScenarioRelease", on_delete=models.PROTECT, related_name="workflow_runs"
    )
    workflow_version = models.ForeignKey(
        WorkflowVersion, on_delete=models.PROTECT, related_name="runs"
    )
    consumer = models.ForeignKey(
        "identity.Consumer", on_delete=models.PROTECT, related_name="workflow_runs"
    )
    idempotency_key = models.CharField(max_length=128)
    input_checksum = models.CharField(max_length=64)
    execution_context = models.JSONField()
    redacted_state = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=WorkflowRunStatus.choices, default=WorkflowRunStatus.REQUESTED
    )
    error_code = models.CharField(max_length=64, blank=True)
    deadline_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "idempotency_key"],
                name="uniq_workflow_run_consumer_idempotency",
            )
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]

    def __str__(self) -> str:
        return f"workflow-run:{self.pk}:{self.status}"

    def clean(self) -> None:
        organization_id = self.organization_id
        if self.scenario_id and organization_id != self.scenario.project.organization_id:
            raise ValidationError("run scenario must match run organization")
        if self.release_id and self.release.scenario_id != self.scenario_id:
            raise ValidationError("run release must match run scenario")
        if self.workflow_version_id and self.workflow_version.scenario_id != self.scenario_id:
            raise ValidationError("run workflow must match run scenario")
        if self.consumer_id and self.consumer.organization_id != organization_id:
            raise ValidationError("run consumer must match run organization")


class WorkflowRunEvent(models.Model):
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=64)
    node_id = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=32, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    state_checksum = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "sequence"], name="uniq_run_event_sequence")
        ]
        ordering = ["run_id", "sequence"]

    def __str__(self) -> str:
        return f"workflow-event:{self.run_id}:{self.sequence}:{self.event_type}"
