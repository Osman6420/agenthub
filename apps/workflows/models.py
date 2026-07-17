"""Immutable compiled workflows and durable tenant-scoped async runs."""

from __future__ import annotations

import uuid

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
    # The active compiled-contract version is set explicitly by ``compile_workflow_version``
    # (``apps.workflows.compiler.COMPILER_VERSION``, currently ``workflow-compiler/v3``). This
    # column default is only a legacy fallback and is never used by the service path.
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
    WAITING_APPROVAL = "waiting_approval", "Waiting approval"
    WAITING_EVENT = "waiting_event", "Waiting event"
    WAITING_HUMAN = "waiting_human", "Waiting human"
    WAITING_TIMER = "waiting_timer", "Waiting timer"
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
        max_length=20, choices=WorkflowRunStatus.choices, default=WorkflowRunStatus.REQUESTED
    )
    error_code = models.CharField(max_length=64, blank=True)
    # Set to the node id while a run is paused; the typed child record owns wait semantics.
    awaiting_node = models.CharField(max_length=64, blank=True)
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
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_run_events"
    )
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

    def save(self, *args: object, **kwargs: object) -> None:
        if self.run_id:
            run_org_id = self.run.organization_id
            if self.organization_id and self.organization_id != run_org_id:
                raise ValueError("workflow event organization must match run organization")
            self.organization_id = run_org_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class WorkflowBranchStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class WorkflowBranch(TimeStampedModel):
    """Tenant-owned durable branch/item and PostgreSQL dispatch intent."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="branches")
    region_node_id = models.CharField(max_length=64)
    branch_name = models.CharField(max_length=64)
    item_ordinal = models.PositiveIntegerField(default=0)
    workflow_checksum = models.CharField(max_length=64)
    transition_version = models.CharField(max_length=32)
    status = models.CharField(
        max_length=16, choices=WorkflowBranchStatus.choices, default=WorkflowBranchStatus.PENDING
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    input_state = models.JSONField(default=dict)
    result_state = models.JSONField(default=dict)
    result_checksum = models.CharField(max_length=64, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "region_node_id", "branch_name", "item_ordinal"],
                name="uniq_workflow_branch_identity",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__lte=3), name="workflow_branch_attempt_lte_3"
            ),
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]


class WorkflowJoinStatus(models.TextChoices):
    OPEN = "open", "Open"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class WorkflowJoin(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="joins")
    region_node_id = models.CharField(max_length=64)
    join_node_id = models.CharField(max_length=64)
    workflow_checksum = models.CharField(max_length=64)
    transition_version = models.CharField(max_length=32)
    mode = models.CharField(max_length=16)
    required_count = models.PositiveIntegerField()
    branch_count = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16, choices=WorkflowJoinStatus.choices, default=WorkflowJoinStatus.OPEN
    )
    merged_state = models.JSONField(default=dict)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "region_node_id"], name="uniq_workflow_join_region"
            ),
            models.CheckConstraint(
                condition=models.Q(required_count__gte=1), name="workflow_join_required_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(branch_count__gte=1), name="workflow_join_branch_count_gte_1"
            ),
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]


class WorkflowWaitKind(models.TextChoices):
    EVENT = "event", "Event"
    TIMER = "timer", "Timer"
    HUMAN = "human", "Human"


class WorkflowWaitStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RESUMED = "resumed", "Resumed"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class WorkflowWait(TimeStampedModel):
    """Tenant-owned one-shot checkpoint; correlation is public but never authorization."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_waits"
    )
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="waits")
    kind = models.CharField(max_length=16, choices=WorkflowWaitKind.choices)
    node_id = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=WorkflowWaitStatus.choices, default=WorkflowWaitStatus.PENDING
    )
    correlation_hash = models.CharField(max_length=64, blank=True, db_index=True)
    pending_checksum = models.CharField(max_length=64)
    workflow_checksum = models.CharField(max_length=64)
    release_id_snapshot = models.PositiveBigIntegerField()
    compiler_version = models.CharField(max_length=32)
    payload_schema = models.JSONField(default=dict, blank=True)
    output_mapping = models.JSONField(default=list, blank=True)
    requester_subject = models.CharField(max_length=255, blank=True)
    allowed_roles = models.JSONField(default=list, blank=True)
    deny_self_decision = models.BooleanField(default=True)
    escalation_role = models.CharField(max_length=64, blank=True)
    escalation_timeout_seconds = models.PositiveIntegerField(default=0)
    deadline_at = models.DateTimeField()
    escalated_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = models.CharField(max_length=255, blank=True)
    redacted_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "node_id"], name="uniq_workflow_wait_run_node")
        ]
        indexes = [models.Index(fields=["organization", "status", "deadline_at"])]

    def clean(self) -> None:
        if self.run_id and self.organization_id != self.run.organization_id:
            raise ValidationError("wait organization must match run organization")
        if self.run_id and self.release_id_snapshot != self.run.release_id:
            raise ValidationError("wait release must match run release")
