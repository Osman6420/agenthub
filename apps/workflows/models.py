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


class RunStatus(models.TextChoices):
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


RUN_TERMINAL_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
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


class RunWaitStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RESUMED = "resumed", "Resumed"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class RunWaitKind(models.TextChoices):
    APPROVAL = "approval", "Approval"
    EVENT = "event", "Event"
    HUMAN = "human", "Human"
    TIMER = "timer", "Timer"
    CHILD = "child", "Child"


class RunEventType(models.TextChoices):
    REQUESTED = "run.requested", "Run requested"
    QUEUED = "run.queued", "Run queued"
    STARTED = "run.started", "Run started"
    CHECKPOINTED = "run.checkpointed", "Run checkpointed"
    WAITING = "run.waiting", "Run waiting"
    RESUMED = "run.resumed", "Run resumed"
    BRANCHES_OPENED = "run.branches_opened", "Run branches opened"
    JOIN_CLOSED = "run.join_closed", "Run join closed"
    CHILD_ADMITTED = "run.child_admitted", "Child run admitted"
    CHILD_COMPLETED = "run.child_completed", "Child run completed"
    NODE_RETRIED = "run.node_retried", "Node retried"
    COMPENSATION = "run.compensation", "Run compensation"
    CANCELLATION_REQUESTED = "run.cancellation_requested", "Cancellation requested"
    RECOVERY_REQUIRED = "run.recovery_required", "Recovery required"
    COMPLETED = "run.completed", "Run completed"
    FAILED = "run.failed", "Run failed"
    TIMED_OUT = "run.timed_out", "Run timed out"
    CANCELLED = "run.cancelled", "Run cancelled"
    LATE_RESULT_DISCARDED = "run.late_result_discarded", "Late result discarded"


class RunChildStatus(models.TextChoices):
    ADMITTED = "admitted", "Admitted"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class RunCompensationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Run(TimeStampedModel):
    """Canonical persistence root for synchronous and background workflow execution."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="runs")
    scenario = models.ForeignKey("catalog.Scenario", on_delete=models.CASCADE, related_name="runs")
    release = models.ForeignKey(
        "releases.ScenarioRelease", on_delete=models.PROTECT, related_name="runs"
    )
    workflow_version = models.ForeignKey(
        WorkflowVersion, on_delete=models.PROTECT, related_name="unified_runs"
    )
    consumer = models.ForeignKey("identity.Consumer", on_delete=models.PROTECT, related_name="runs")
    actor_id = models.CharField(max_length=200)
    response_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    idempotency_key = models.CharField(max_length=128)
    compiled_checksum = models.CharField(max_length=64)
    compiler_version = models.CharField(max_length=32)
    status = models.CharField(max_length=20, choices=RunStatus.choices, default=RunStatus.REQUESTED)
    execution_mode = models.CharField(max_length=16, choices=RunExecutionMode.choices)
    checkpoint = models.JSONField(default=dict)
    checkpoint_version = models.PositiveIntegerField(default=1)
    next_event_sequence = models.PositiveBigIntegerField(default=1)
    awaiting_kind = models.CharField(max_length=16, choices=RunAwaitingKind.choices, blank=True)
    awaiting_reference = models.CharField(max_length=200, blank=True)
    deadline_at = models.DateTimeField()
    sync_lease_token = models.UUIDField(null=True, blank=True)
    sync_lease_expires_at = models.DateTimeField(null=True, blank=True)
    background_claim_token = models.UUIDField(null=True, blank=True)
    background_claim_expires_at = models.DateTimeField(null=True, blank=True)
    background_claim_checkpoint_version = models.PositiveIntegerField(null=True, blank=True)
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
            models.CheckConstraint(
                condition=(
                    models.Q(
                        background_claim_token__isnull=True,
                        background_claim_expires_at__isnull=True,
                        background_claim_checkpoint_version__isnull=True,
                    )
                    | models.Q(
                        background_claim_token__isnull=False,
                        background_claim_expires_at__isnull=False,
                        background_claim_checkpoint_version__isnull=False,
                        execution_mode=RunExecutionMode.BACKGROUND,
                    )
                ),
                name="run_background_claim_complete",
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
        background_claim_parts = (
            self.background_claim_token,
            self.background_claim_expires_at,
            self.background_claim_checkpoint_version,
        )
        if any(value is not None for value in background_claim_parts) and (
            self.execution_mode != RunExecutionMode.BACKGROUND
            or not all(value is not None for value in background_claim_parts)
        ):
            raise ValidationError(
                "background claim token, expiry and checkpoint version must be set together"
            )


class RunWait(TimeStampedModel):
    """One-shot, direct-tenant durable resume authority for a unified Run."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="run_waits"
    )
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="waits")
    kind = models.CharField(max_length=16, choices=RunWaitKind.choices)
    node_id = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=RunWaitStatus.choices, default=RunWaitStatus.PENDING
    )
    resume_token_hash = models.CharField(max_length=64, unique=True)
    pending_checksum = models.CharField(max_length=64)
    checkpoint_version_snapshot = models.PositiveIntegerField()
    release_id_snapshot = models.PositiveBigIntegerField()
    compiled_checksum = models.CharField(max_length=64)
    compiler_version = models.CharField(max_length=32)
    payload_schema = models.JSONField(default=dict, blank=True)
    output_mapping = models.JSONField(default=list, blank=True)
    requester_actor_id = models.CharField(max_length=200)
    deadline_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by = models.CharField(max_length=200, blank=True)
    resume_checksum = models.CharField(max_length=64, blank=True)
    result_checkpoint_version = models.PositiveIntegerField(null=True, blank=True)
    redacted_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run"],
                condition=models.Q(status=RunWaitStatus.PENDING),
                name="uniq_pending_run_wait",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=RunWaitStatus.PENDING,
                        consumed_at__isnull=True,
                        consumed_by="",
                        resume_checksum="",
                        result_checkpoint_version__isnull=True,
                    )
                    | models.Q(
                        status=RunWaitStatus.RESUMED,
                        consumed_at__isnull=False,
                        resume_checksum__gt="",
                        result_checkpoint_version__isnull=False,
                    )
                    | models.Q(
                        status__in=[RunWaitStatus.EXPIRED, RunWaitStatus.CANCELLED],
                        consumed_at__isnull=False,
                        result_checkpoint_version__isnull=True,
                    )
                ),
                name="run_wait_consumption_complete",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "deadline_at"]),
            models.Index(fields=["run", "created_at"]),
        ]

    def clean(self) -> None:
        if self.kind not in {
            RunAwaitingKind.APPROVAL,
            RunAwaitingKind.EVENT,
            RunAwaitingKind.HUMAN,
            RunAwaitingKind.TIMER,
            RunAwaitingKind.CHILD,
        }:
            raise ValidationError("unsupported unified run wait kind")
        if self.run_id and self.organization_id != self.run.organization_id:
            raise ValidationError("run wait organization must match run organization")
        if self.run_id and self.release_id_snapshot != self.run.release_id:
            raise ValidationError("run wait release must match run release")


class RunChildLink(TimeStampedModel):
    """Immutable, tenant-owned lineage between a parent Run and one pinned child Run."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="run_child_links"
    )
    parent_run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="child_links")
    child_run = models.OneToOneField(Run, on_delete=models.PROTECT, related_name="parent_link")
    call_site = models.CharField(max_length=64)
    child_release_checksum = models.CharField(max_length=64)
    child_artifact_checksum = models.CharField(max_length=64)
    effective_capability_checksum = models.CharField(max_length=64)
    depth = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=16, choices=RunChildStatus.choices, default=RunChildStatus.ADMITTED
    )
    reason_code = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parent_run", "call_site"], name="uniq_run_child_parent_call_site"
            )
        ]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self) -> str:
        return f"run-child:{self.parent_run_id}:{self.call_site}:{self.status}"

    def clean(self) -> None:
        if self.parent_run_id and self.parent_run.organization_id != self.organization_id:
            raise ValidationError("child link parent must match organization")
        if self.child_run_id and self.child_run.organization_id != self.organization_id:
            raise ValidationError("child link child must match organization")
        if self.parent_run_id and self.child_run_id and self.parent_run_id == self.child_run_id:
            raise ValidationError("a run cannot be its own child")


class RunCompensationEntry(TimeStampedModel):
    """Durable compensation intent recorded after one side effect succeeds."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="run_compensations"
    )
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="compensations")
    sequence = models.PositiveSmallIntegerField()
    source_node_id = models.CharField(max_length=64)
    compensation_node_id = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=RunCompensationStatus.choices,
        default=RunCompensationStatus.PENDING,
    )
    reason_code = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"], name="uniq_run_compensation_sequence"
            ),
            models.UniqueConstraint(
                fields=["run", "source_node_id"], name="uniq_run_compensation_source"
            ),
        ]
        indexes = [models.Index(fields=["organization", "status"])]

    def clean(self) -> None:
        if self.run_id and self.run.organization_id != self.organization_id:
            raise ValidationError("run compensation must match organization")


# Server-owned resume cursor key inside a Run checkpoint. It is defined here so the executor
# that writes it and the parallel aggregate that must strip it agree on a single name.
RUN_CURSOR_KEY = "__resume_node"
MAX_RUN_PARALLEL_CONCURRENCY = 16
MAX_RUN_PARALLEL_DURATION_SECONDS = 300
MAX_RUN_PARALLEL_STATE_BYTES = 1_048_576


class RunBranchStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


RUN_BRANCH_TERMINAL_STATUSES = frozenset(
    {RunBranchStatus.SUCCEEDED, RunBranchStatus.FAILED, RunBranchStatus.CANCELLED}
)
MAX_RUN_BRANCH_ATTEMPTS = 3


class RunBranch(TimeStampedModel):
    """Direct-tenant durable branch or item of one unified Run parallel region."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="run_branches"
    )
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="branches")
    region_node_id = models.CharField(max_length=64)
    branch_name = models.CharField(max_length=64)
    item_ordinal = models.PositiveIntegerField(default=0)
    compiled_checksum = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=RunBranchStatus.choices, default=RunBranchStatus.PENDING
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    input_state = models.JSONField(default=dict)
    result_state = models.JSONField(default=dict)
    result_checksum = models.CharField(max_length=64, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True)
    delivery_token = models.UUIDField(null=True, blank=True)
    delivery_expires_at = models.DateTimeField(null=True, blank=True)
    claim_expires_at = models.DateTimeField(null=True, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "region_node_id", "branch_name", "item_ordinal"],
                name="uniq_run_branch_identity",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__lte=MAX_RUN_BRANCH_ATTEMPTS),
                name="run_branch_attempt_bounded",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=[RunBranchStatus.PENDING, RunBranchStatus.RUNNING])
                    | models.Q(finished_at__isnull=False)
                ),
                name="run_branch_terminal_finished",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "created_at"]),
            models.Index(fields=["run", "region_node_id"]),
            models.Index(
                fields=["organization", "status", "delivery_expires_at"],
                name="run_branch_dispatch_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"run-branch:{self.pk}:{self.status}"

    def clean(self) -> None:
        if self.run_id and self.organization_id != self.run.organization_id:
            raise ValidationError("run branch organization must match run organization")


class RunJoinStatus(models.TextChoices):
    OPEN = "open", "Open"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class RunJoin(TimeStampedModel):
    """Direct-tenant durable close condition for one unified Run parallel region."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="run_joins"
    )
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="joins")
    region_node_id = models.CharField(max_length=64)
    join_node_id = models.CharField(max_length=64)
    compiled_checksum = models.CharField(max_length=64)
    mode = models.CharField(max_length=16)
    required_count = models.PositiveIntegerField()
    branch_count = models.PositiveIntegerField()
    max_concurrency = models.PositiveSmallIntegerField()
    max_duration_seconds = models.PositiveIntegerField()
    max_state_bytes = models.PositiveIntegerField()
    deadline_at = models.DateTimeField()
    status = models.CharField(
        max_length=16, choices=RunJoinStatus.choices, default=RunJoinStatus.OPEN
    )
    merged_state = models.JSONField(default=dict)
    reason_code = models.CharField(max_length=64, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "region_node_id"], name="uniq_run_join_region"),
            models.UniqueConstraint(fields=["run", "join_node_id"], name="uniq_run_join_node"),
            models.CheckConstraint(
                condition=models.Q(required_count__gte=1), name="run_join_required_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(branch_count__gte=1), name="run_join_branch_count_gte_1"
            ),
            models.CheckConstraint(
                condition=models.Q(required_count__lte=models.F("branch_count")),
                name="run_join_required_lte_branches",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    max_concurrency__gte=1,
                    max_concurrency__lte=MAX_RUN_PARALLEL_CONCURRENCY,
                ),
                name="run_join_concurrency_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    max_duration_seconds__gte=1,
                    max_duration_seconds__lte=MAX_RUN_PARALLEL_DURATION_SECONDS,
                ),
                name="run_join_duration_bounded",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    max_state_bytes__gte=1,
                    max_state_bytes__lte=MAX_RUN_PARALLEL_STATE_BYTES,
                ),
                name="run_join_state_bounded",
            ),
            models.CheckConstraint(
                condition=(models.Q(status=RunJoinStatus.OPEN) | models.Q(closed_at__isnull=False)),
                name="run_join_closed_at_set",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "created_at"]),
            models.Index(
                fields=["organization", "status", "deadline_at"],
                name="run_join_deadline_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"run-join:{self.pk}:{self.status}"

    def clean(self) -> None:
        if self.run_id and self.organization_id != self.run.organization_id:
            raise ValidationError("run join organization must match run organization")


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
