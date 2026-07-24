"""Immutable compiled workflows and durable tenant-scoped async runs."""

from __future__ import annotations

import uuid
from typing import Any

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
    # (``apps.workflows.compiler.COMPILER_VERSION``, currently ``workflow-compiler/v5``). This
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
    # Paused while a pinned child sub-workflow/agent-call executes as a separate run (P2.6.5).
    WAITING_CHILD = "waiting_child", "Waiting child"
    RECOVERY_REQUIRED = "recovery_required", "Recovery required"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    TIMED_OUT = "timed_out", "Timed out"
    CANCELLED = "cancelled", "Cancelled"


WORKFLOW_TERMINAL_STATUSES = frozenset(
    {
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.TIMED_OUT,
        WorkflowRunStatus.CANCELLED,
    }
)


class RunExecutionMode(models.TextChoices):
    SYNC = "sync", "Synchronous"
    BACKGROUND = "background", "Background"


class RunAwaitingKind(models.TextChoices):
    APPROVAL = "approval", "Approval"
    EVENT = "event", "Event"
    HUMAN = "human", "Human"
    TIMER = "timer", "Timer"
    CHILD = "child", "Child"
    RECOVERY = "recovery", "Recovery"


class RunCancellationState(models.TextChoices):
    NONE = "none", "None"
    REQUESTED = "requested", "Requested"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"


class RunEventType(models.TextChoices):
    REQUESTED = "run.requested", "Run requested"
    QUEUED = "run.queued", "Run queued"
    STARTED = "run.started", "Run started"
    CHECKPOINTED = "run.checkpointed", "Run checkpointed"
    WAITING = "run.waiting", "Run waiting"
    RESUMED = "run.resumed", "Run resumed"
    CANCELLATION_REQUESTED = "run.cancellation_requested", "Cancellation requested"
    RECOVERY_REQUIRED = "run.recovery_required", "Recovery required"
    COMPLETED = "run.completed", "Run completed"
    FAILED = "run.failed", "Run failed"
    TIMED_OUT = "run.timed_out", "Run timed out"
    CANCELLED = "run.cancelled", "Run cancelled"
    LATE_RESULT_DISCARDED = "run.late_result_discarded", "Late result discarded"


class Run(TimeStampedModel):
    """Canonical persistence root for synchronous and background workflow execution."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="runs"
    )
    scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.CASCADE, related_name="runs"
    )
    release = models.ForeignKey(
        "releases.ScenarioRelease", on_delete=models.PROTECT, related_name="runs"
    )
    workflow_version = models.ForeignKey(
        WorkflowVersion, on_delete=models.PROTECT, related_name="unified_runs"
    )
    consumer = models.ForeignKey(
        "identity.Consumer", on_delete=models.PROTECT, related_name="runs"
    )
    actor_id = models.CharField(max_length=200)
    response_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    idempotency_key = models.CharField(max_length=128)
    compiled_checksum = models.CharField(max_length=64)
    compiler_version = models.CharField(max_length=32)
    status = models.CharField(
        max_length=20, choices=WorkflowRunStatus.choices, default=WorkflowRunStatus.REQUESTED
    )
    execution_mode = models.CharField(max_length=16, choices=RunExecutionMode.choices)
    checkpoint = models.JSONField(default=dict)
    checkpoint_version = models.PositiveIntegerField(default=1)
    next_event_sequence = models.PositiveBigIntegerField(default=1)
    awaiting_kind = models.CharField(
        max_length=16, choices=RunAwaitingKind.choices, blank=True
    )
    awaiting_reference = models.CharField(max_length=200, blank=True)
    deadline_at = models.DateTimeField()
    sync_lease_token = models.UUIDField(null=True, blank=True)
    sync_lease_expires_at = models.DateTimeField(null=True, blank=True)
    cancellation_state = models.CharField(
        max_length=16,
        choices=RunCancellationState.choices,
        default=RunCancellationState.NONE,
    )
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason_code = models.CharField(max_length=64, blank=True)
    step_count = models.PositiveIntegerField(default=0)
    tool_call_count = models.PositiveIntegerField(default=0)
    input_token_count = models.PositiveIntegerField(default=0)
    output_token_count = models.PositiveIntegerField(default=0)
    input_checksum = models.CharField(max_length=64)
    execution_context = models.JSONField(default=dict)
    redacted_state = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "idempotency_key"],
                name="uniq_run_consumer_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(checkpoint_version__gte=1),
                name="run_checkpoint_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(next_event_sequence__gte=1),
                name="run_next_event_sequence_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "created_at"]),
            models.Index(fields=["organization", "execution_mode", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"run:{self.pk}:{self.status}"

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
        if bool(self.awaiting_kind) != bool(self.awaiting_reference):
            raise ValidationError("run awaiting kind and reference must be set together")
        if self.execution_mode != RunExecutionMode.SYNC and (
            self.sync_lease_token or self.sync_lease_expires_at
        ):
            raise ValidationError("only synchronous runs may hold a sync lease")
        if bool(self.sync_lease_token) != bool(self.sync_lease_expires_at):
            raise ValidationError("sync lease token and expiry must be set together")


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


class ChildLinkStatus(models.TextChoices):
    ADMITTED = "admitted", "Admitted"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


CHILD_LINK_TERMINAL_STATUSES = frozenset(
    {ChildLinkStatus.COMPLETED, ChildLinkStatus.FAILED, ChildLinkStatus.CANCELLED}
)


class WorkflowChildLink(TimeStampedModel):
    """Immutable tenant-scoped parent/child composition link (P2.6.5 / ADR-0009).

    Records the exact server-owned lineage of one ``subworkflow``/``agent_call`` call site: the
    parent run, the pinned child kind/scenario/release/checksums, the separate child run, the
    depth, the effective-capability *checksum* (never raw capabilities) and a safe status/reason.
    It carries direct organization lineage and is provisioned with FORCE RLS. The unique
    ``(parent_run, call_site)`` constraint makes child admission idempotent; the status guards
    prevent a late/duplicate child result from mutating a terminal parent.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_child_links"
    )
    parent_run = models.ForeignKey(
        WorkflowRun, on_delete=models.CASCADE, related_name="child_links"
    )
    call_site = models.CharField(max_length=64)
    child_kind = models.CharField(max_length=16)
    child_scenario = models.ForeignKey(
        "catalog.Scenario", on_delete=models.PROTECT, related_name="as_child_links"
    )
    child_release = models.ForeignKey(
        "releases.ScenarioRelease", on_delete=models.PROTECT, related_name="as_child_links"
    )
    child_release_checksum = models.CharField(max_length=64)
    child_artifact_checksum = models.CharField(max_length=64)
    child_workflow_run = models.ForeignKey(
        WorkflowRun,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="as_child_workflow_link",
    )
    child_agent_run = models.ForeignKey(
        "agents.AgentRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="child_link",
    )
    child_public_ref = models.CharField(max_length=64, blank=True)
    effective_capability_checksum = models.CharField(max_length=64)
    depth = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=16, choices=ChildLinkStatus.choices, default=ChildLinkStatus.ADMITTED
    )
    reason_code = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parent_run", "call_site"], name="uniq_child_link_parent_call_site"
            )
        ]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self) -> str:
        return f"child-link:{self.parent_run_id}:{self.call_site}:{self.status}"

    def clean(self) -> None:
        if self.parent_run_id and self.organization_id != self.parent_run.organization_id:
            raise ValidationError("child link organization must match parent run organization")
        if self.child_scenario_id and self.child_scenario.project.organization_id != (
            self.organization_id
        ):
            raise ValidationError("child scenario must belong to the parent organization")
        if self.child_release_id and self.child_release.organization_id != self.organization_id:
            raise ValidationError("child release must belong to the parent organization")
        wf_run = self.child_workflow_run if self.child_workflow_run_id else None
        if wf_run is not None and wf_run.organization_id != self.organization_id:
            raise ValidationError("child run must belong to the parent organization")
        agent_run = self.child_agent_run if self.child_agent_run_id else None
        if agent_run is not None and agent_run.organization_id != self.organization_id:
            raise ValidationError("child run must belong to the parent organization")


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


class WorkflowNodeAttemptStatus(models.TextChoices):
    RUNNING = "running", "Running"
    RETRY_WAIT = "retry_wait", "Retry waiting"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class WorkflowNodeAttempt(TimeStampedModel):
    """Durable tenant-owned record for one bounded workflow-node attempt."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_node_attempts"
    )
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="node_attempts")
    node_id = models.CharField(max_length=64)
    ordinal = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=16,
        choices=WorkflowNodeAttemptStatus.choices,
        default=WorkflowNodeAttemptStatus.RUNNING,
    )
    failure_class = models.CharField(max_length=24, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    state_checksum = models.CharField(max_length=64, blank=True)
    retry_not_before = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "node_id", "ordinal"], name="uniq_workflow_attempt_run_node_ordinal"
            )
        ]
        indexes = [models.Index(fields=["organization", "status", "retry_not_before"])]

    def clean(self) -> None:
        if self.run_id and self.organization_id != self.run.organization_id:
            raise ValidationError("attempt organization must match run organization")


class WorkflowCompensationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    BLOCKED = "blocked", "Blocked"
    CANCELLED = "cancelled", "Cancelled"


class WorkflowCompensationEntry(TimeStampedModel):
    """One release-pinned reverse-order compensation intent."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_compensation_entries"
    )
    run = models.ForeignKey(
        WorkflowRun, on_delete=models.CASCADE, related_name="compensation_entries"
    )
    sequence = models.PositiveSmallIntegerField()
    source_node_id = models.CharField(max_length=64)
    compensation_node_id = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=WorkflowCompensationStatus.choices,
        default=WorkflowCompensationStatus.PENDING,
    )
    input_checksum = models.CharField(max_length=64)
    reason_code = models.CharField(max_length=64, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"], name="uniq_workflow_compensation_run_sequence"
            )
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]

    def clean(self) -> None:
        if self.run_id and self.organization_id != self.run.organization_id:
            raise ValidationError("compensation organization must match run organization")


class WorkflowRecoveryStatus(models.TextChoices):
    OPEN = "open", "Open"
    AWAITING_SECOND_APPROVAL = "awaiting_second_approval", "Awaiting second approval"
    RESOLVED = "resolved", "Resolved"
    CANCELLED = "cancelled", "Cancelled"


class WorkflowRecoveryCase(TimeStampedModel):
    """A system-created ambiguity/blocked-compensation case; users cannot create one."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_recovery_cases"
    )
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="recovery_cases")
    node_id = models.CharField(max_length=64)
    failure_class = models.CharField(max_length=24)
    reason_code = models.CharField(max_length=64)
    status = models.CharField(
        max_length=32, choices=WorkflowRecoveryStatus.choices, default=WorkflowRecoveryStatus.OPEN
    )
    revision = models.PositiveIntegerField(default=1)
    state_checksum = models.CharField(max_length=64)
    high_risk = models.BooleanField(default=False)
    required_approvals = models.PositiveSmallIntegerField(default=1)
    resolved_action = models.CharField(max_length=40, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "node_id", "revision"], name="uniq_recovery_run_node_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(required_approvals__in=[1, 2]),
                name="workflow_recovery_required_approvals_valid",
            ),
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]

    def clean(self) -> None:
        if self.run_id and self.organization_id != self.run.organization_id:
            raise ValidationError("recovery organization must match run organization")


class WorkflowRecoveryApproval(TimeStampedModel):
    """One distinct admin's decision on an exact recovery-case revision."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_recovery_approvals"
    )
    recovery_case = models.ForeignKey(
        WorkflowRecoveryCase, on_delete=models.CASCADE, related_name="approvals"
    )
    actor_id = models.PositiveBigIntegerField()
    action = models.CharField(max_length=40)
    reason = models.CharField(max_length=200)
    revision = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recovery_case", "actor_id"], name="uniq_recovery_case_actor"
            )
        ]

    def clean(self) -> None:
        if self.recovery_case_id and self.organization_id != self.recovery_case.organization_id:
            raise ValidationError("approval organization must match recovery organization")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise ValueError("workflow recovery approvals are append-only")
        super().save(*args, **kwargs)


class RunEvent(models.Model):
    """Bounded, redacted event attached to the canonical Run aggregate."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="run_events"
    )
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=64, choices=RunEventType.choices)
    node_id = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=32, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    state_checksum = models.CharField(max_length=64, blank=True)
    transition_token = models.UUIDField(null=True, blank=True)
    transition_checksum = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"], name="uniq_unified_run_event_sequence"
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="run_event_sequence_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(event_type__in=RunEventType.values),
                name="run_event_type_valid",
            ),
            models.UniqueConstraint(
                fields=["run", "transition_token"],
                condition=models.Q(transition_token__isnull=False),
                name="uniq_run_event_transition_token",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(transition_token__isnull=True, transition_checksum="")
                    | (models.Q(transition_token__isnull=False) & ~models.Q(transition_checksum=""))
                ),
                name="run_event_transition_token_checksum_pair",
            ),
        ]
        ordering = ["run_id", "sequence"]

    def __str__(self) -> str:
        return f"run-event:{self.run_id}:{self.sequence}:{self.event_type}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.run_id:
            run_org_id = self.run.organization_id
            if self.organization_id and self.organization_id != run_org_id:
                raise ValueError("run event organization must match run organization")
            self.organization_id = run_org_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]
