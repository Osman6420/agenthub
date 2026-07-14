"""Immutable compiled agents and durable, tenant-scoped agent runs (Sprint 10).

Mirrors the Sprint 8 workflow run model: an ``AgentVersion`` is an immutable compiled
definition a release pins; an ``AgentRun`` is a durable run with an immutable start
snapshot, a versioned redacted checkpoint, bounded resource counters, an explicit state
machine, and an append-only ``AgentRunEvent`` trail. A run is addressed externally by an
opaque ``public_id`` (UUID) so agent and workflow run ids never collide on the shared
``/v1/runs/{id}`` surface. Serialized state carries no tenant selector — every query is
scoped by the authoritative ``organization``/``consumer`` columns.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.agents.limits import CHECKPOINT_SCHEMA_VERSION
from apps.tenancy.models import Organization, TimeStampedModel


class AgentVersion(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="agent_versions"
    )
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.CASCADE, related_name="agent_versions"
    )
    source_artifact = models.ForeignKey(
        "artifacts.ArtifactVersion", on_delete=models.PROTECT, related_name="compiled_agents"
    )
    compiled_config = models.JSONField()
    checksum = models.CharField(max_length=64)
    compiler_version = models.CharField(max_length=32, default="agent-compiler/v1")
    created_by = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "source_artifact", "compiler_version"],
                name="uniq_compiled_agent_source",
            )
        ]

    def __str__(self) -> str:
        return f"agent:{self.scenario_id}:{self.checksum[:12]}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is not None:
            raise ValueError("AgentVersion is immutable")
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        if self.scenario_id and self.organization_id != self.scenario.project.organization_id:
            raise ValidationError("agent organization must match scenario organization")
        if self.source_artifact_id and self.organization_id != self.source_artifact.organization_id:
            raise ValidationError("agent artifact must match agent organization")


class AgentRunStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    WAITING_APPROVAL = "waiting_approval", "Waiting approval"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    TIMED_OUT = "timed_out", "Timed out"
    CANCELLED = "cancelled", "Cancelled"


TERMINAL_RUN_STATUSES = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.TIMED_OUT,
        AgentRunStatus.CANCELLED,
    }
)


class AgentRun(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="agent_runs"
    )
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.CASCADE, related_name="agent_runs"
    )
    release = models.ForeignKey(
        "releases.ScenarioRelease", on_delete=models.PROTECT, related_name="agent_runs"
    )
    agent_version = models.ForeignKey(AgentVersion, on_delete=models.PROTECT, related_name="runs")
    consumer = models.ForeignKey(
        "identity.Consumer", on_delete=models.PROTECT, related_name="agent_runs"
    )
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    idempotency_key = models.CharField(max_length=128)
    input_checksum = models.CharField(max_length=64)
    execution_context = models.JSONField()
    # Immutable redacted snapshot captured at request time (input + resolved limits).
    start_snapshot = models.JSONField(default=dict)
    # Durable redacted working state; overwritten at each committed step.
    checkpoint = models.JSONField(default=dict)
    checkpoint_version = models.PositiveIntegerField(default=CHECKPOINT_SCHEMA_VERSION)
    status = models.CharField(
        max_length=20, choices=AgentRunStatus.choices, default=AgentRunStatus.REQUESTED
    )
    error_code = models.CharField(max_length=64, blank=True)
    # Bounded resource accounting; guards terminate a run that exceeds a pinned cap.
    step_count = models.PositiveIntegerField(default=0)
    tool_call_count = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    # While paused for a tool approval: the step index and binding role to resume.
    awaiting_step = models.IntegerField(null=True, blank=True)
    awaiting_role = models.CharField(max_length=128, blank=True)
    deadline_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "idempotency_key"],
                name="uniq_agent_run_consumer_idempotency",
            )
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]

    def __str__(self) -> str:
        return f"agent-run:{self.pk}:{self.status}"

    def clean(self) -> None:
        organization_id = self.organization_id
        if self.scenario_id and organization_id != self.scenario.project.organization_id:
            raise ValidationError("run scenario must match run organization")
        if self.release_id and self.release.scenario_id != self.scenario_id:
            raise ValidationError("run release must match run scenario")
        if self.agent_version_id and self.agent_version.scenario_id != self.scenario_id:
            raise ValidationError("run agent must match run scenario")
        if self.consumer_id and self.consumer.organization_id != organization_id:
            raise ValidationError("run consumer must match run organization")


class AgentRunEvent(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="agent_run_events"
    )
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=64)
    step_index = models.IntegerField(null=True, blank=True)
    # A bounded, allowlisted decision label (never raw chain-of-thought).
    decision = models.CharField(max_length=32, blank=True)
    outcome = models.CharField(max_length=32, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    state_checksum = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"], name="uniq_agent_run_event_sequence"
            )
        ]
        ordering = ["run_id", "sequence"]

    def __str__(self) -> str:
        return f"agent-event:{self.run_id}:{self.sequence}:{self.event_type}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.run_id:
            run_org_id = self.run.organization_id
            if self.organization_id and self.organization_id != run_org_id:
                raise ValueError("agent event organization must match run organization")
            self.organization_id = run_org_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]
