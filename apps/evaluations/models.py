"""Evaluation runs and per-case results (Sprint 6).

An :class:`EvalRun` records the deterministic evaluation of a *candidate* release
against the eval-suite artifact pinned in that release's manifest. Reports store the
assertion type, a boolean outcome, and a stable, content-free reason code only — never
raw prompts, model output, or retrieved passages (observability/data-minimization
rules). Every run is bound to the release's organization and enforces that boundary.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.artifacts.models import ArtifactVersion
from apps.documents.models import DocumentSetVersion
from apps.ingestion.models import IndexVersion
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import (
    Organization,
    TimeStampedModel,
    ensure_immutable_public_id,
)


class EvalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"
    ERROR = "error", "Error"


class EvalRun(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="eval_runs"
    )
    release = models.ForeignKey(ScenarioRelease, on_delete=models.CASCADE, related_name="eval_runs")
    # The eval suite is pinned in the release manifest; both ref and checksum are
    # recorded so a promotion gate can require a pass bound to the exact suite version.
    suite_ref = models.CharField(max_length=256)
    suite_checksum = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=EvalStatus.choices, default=EvalStatus.PENDING)
    total_cases = models.PositiveIntegerField(default=0)
    passed_cases = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    created_by = models.CharField(max_length=200)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["release", "suite_checksum", "status"],
                name="evalrun_gate_lookup",
            )
        ]

    def clean(self) -> None:
        if (
            self.release_id
            and self.organization_id != self.release.scenario.project.organization_id
        ):
            raise ValidationError("eval run organization must match the release organization")

    @property
    def is_passed(self) -> bool:
        return self.status == EvalStatus.PASSED


class EvalCaseResult(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="eval_case_results"
    )
    run = models.ForeignKey(EvalRun, on_delete=models.CASCADE, related_name="case_results")
    case_id = models.CharField(max_length=128)
    passed = models.BooleanField()
    fallback_used = models.BooleanField(default=False)
    # List of {"type": str, "passed": bool, "reason_code": str}. No raw content.
    assertions = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "case_id"], name="uniq_case_result_run_case")
        ]

    def save(self, *args: object, **kwargs: object) -> None:
        if self.run_id:
            run_org_id = self.run.organization_id
            if self.organization_id and self.organization_id != run_org_id:
                raise ValueError("eval result organization must match run organization")
            self.organization_id = run_org_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class QuestionSetStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class QuestionSet(TimeStampedModel):
    """Tenant-owned mutable question-set draft identity."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="question_sets"
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # A scenario owns the question set edited from its "Test soruları" step. Organization-wide
    # sets created before this (and any deliberately shared set) keep ``scenario=NULL``.
    scenario = models.ForeignKey(
        "catalog.Scenario",
        on_delete=models.CASCADE,
        related_name="question_sets",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=16, choices=QuestionSetStatus.choices, default=QuestionSetStatus.ACTIVE
    )
    draft_revision = models.PositiveIntegerField(default=1)
    draft_cases = models.JSONField(default=list)
    created_by = models.CharField(max_length=200)
    updated_by = models.CharField(max_length=200)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_question_set_org_name"
            )
        ]
        ordering = ["organization_id", "name", "id"]

    def save(self, *args: object, **kwargs: object) -> None:
        ensure_immutable_public_id(self)
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class QuestionSetVersion(TimeStampedModel):
    """Immutable published snapshot of a question-set draft."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="question_set_versions"
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    question_set = models.ForeignKey(QuestionSet, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    checksum = models.CharField(max_length=64)
    case_count = models.PositiveIntegerField(default=0)
    published_by = models.CharField(max_length=200)
    published_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question_set", "version"], name="uniq_question_set_version"
            ),
            models.UniqueConstraint(
                fields=["question_set", "checksum"], name="uniq_question_set_checksum"
            ),
        ]
        ordering = ["question_set_id", "-version"]

    def clean(self) -> None:
        if self.question_set_id and self.question_set.organization_id != self.organization_id:
            raise ValidationError("question-set version organization must match its question set")

    def save(self, *args: object, **kwargs: object) -> None:
        ensure_immutable_public_id(self)
        if self.pk and QuestionSetVersion.objects.filter(pk=self.pk).exists():
            raise ValidationError("published question-set versions are immutable")
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class QuestionCase(TimeStampedModel):
    """One immutable, bounded case in a published question-set version."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="question_cases"
    )
    question_set_version = models.ForeignKey(
        QuestionSetVersion, on_delete=models.CASCADE, related_name="cases"
    )
    case_id = models.CharField(max_length=128)
    ordinal = models.PositiveIntegerField()
    question = models.CharField(max_length=4000)
    input_payload = models.JSONField(default=dict)
    assertions = models.JSONField(default=list)
    # The answer an author expects, in their own words. It is judge input, never an
    # assertion: deterministic scoring uses ``assertions``, and this only reaches the
    # referee so it can decide whether the produced answer matches the intent.
    expected_answer = models.CharField(max_length=4000, blank=True)
    expected_anchors = models.JSONField(default=list)
    judge_policy = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question_set_version", "case_id"],
                name="uniq_question_case_version_id",
            ),
            models.UniqueConstraint(
                fields=["question_set_version", "ordinal"],
                name="uniq_question_case_version_ordinal",
            ),
        ]
        ordering = ["question_set_version_id", "ordinal"]

    def clean(self) -> None:
        if (
            self.question_set_version_id
            and self.question_set_version.organization_id != self.organization_id
        ):
            raise ValidationError("question case organization must match its version")

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk and QuestionCase.objects.filter(pk=self.pk).exists():
            raise ValidationError("published question cases are immutable")
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class QuestionEvaluationKind(models.TextChoices):
    RETRIEVAL = "retrieval", "Retrieval"
    ANSWER = "answer", "Answer"


class QuestionEvaluationStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class QuestionEvaluationRun(TimeStampedModel):
    """Bounded batch evaluation pinned to exact immutable inputs."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="question_evaluation_runs"
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    question_set_version = models.ForeignKey(
        QuestionSetVersion,
        on_delete=models.PROTECT,
        related_name="evaluation_runs",
    )
    kind = models.CharField(max_length=16, choices=QuestionEvaluationKind.choices)
    document_set_version = models.ForeignKey(
        DocumentSetVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="question_evaluation_runs",
    )
    index_version = models.ForeignKey(
        IndexVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="question_evaluation_runs",
    )
    retrieval_profile = models.ForeignKey(
        ArtifactVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="question_evaluation_runs_as_retrieval_profile",
    )
    release = models.ForeignKey(
        ScenarioRelease,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="question_evaluation_runs",
    )
    judge_model_profile = models.ForeignKey(
        ArtifactVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="question_evaluation_runs_as_judge_model",
    )
    judge_prompt_contract = models.ForeignKey(
        ArtifactVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="question_evaluation_runs_as_judge_prompt",
    )
    status = models.CharField(
        max_length=16,
        choices=QuestionEvaluationStatus.choices,
        default=QuestionEvaluationStatus.QUEUED,
    )
    idempotency_key = models.CharField(max_length=128)
    total_cases = models.PositiveIntegerField(default=0)
    completed_cases = models.PositiveIntegerField(default=0)
    passed_cases = models.PositiveIntegerField(default=0)
    unscored_cases = models.PositiveIntegerField(default=0)
    error_cases = models.PositiveIntegerField(default=0)
    metrics = models.JSONField(default=dict, blank=True)
    provenance = models.JSONField(default=dict)
    created_by = models.CharField(max_length=200)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateTimeField(null=True, blank=True)
    legal_hold = models.BooleanField(default=False)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="uniq_question_eval_org_idempotency",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "kind", "status", "-created_at"],
                name="question_eval_status_idx",
            )
        ]
        ordering = ["-created_at", "-id"]

    def clean(self) -> None:
        targets = [
            self.question_set_version,
            self.document_set_version,
            self.index_version,
            self.retrieval_profile,
            self.release,
            self.judge_model_profile,
            self.judge_prompt_contract,
        ]
        for target in targets:
            if target is not None and target.organization_id != self.organization_id:
                raise ValidationError("evaluation target organization mismatch")
        if self.kind == QuestionEvaluationKind.RETRIEVAL:
            if (
                not all(
                    [self.document_set_version_id, self.index_version_id, self.retrieval_profile_id]
                )
                or self.release_id
            ):
                raise ValidationError("retrieval evaluation requires exact document/index/profile")
            if (
                self.index_version is not None
                and self.index_version.document_set_version_id != self.document_set_version_id
            ):
                raise ValidationError(
                    "index version must belong to the selected document-set version"
                )
        elif self.kind == QuestionEvaluationKind.ANSWER:
            if not self.release_id or self.document_set_version_id or self.index_version_id:
                raise ValidationError("answer evaluation requires one exact release")
        if bool(self.judge_model_profile_id) != bool(self.judge_prompt_contract_id):
            raise ValidationError("judge model and prompt must be pinned together")

    def save(self, *args: object, **kwargs: object) -> None:
        ensure_immutable_public_id(self)
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class QuestionEvaluationEvidenceStatus(models.TextChoices):
    PASSED = "passed", "Passed"
    FAILED = "failed", "Failed"
    UNSCORED = "unscored", "Unscored"
    ERROR = "error", "Error"


class QuestionEvaluationEvidence(TimeStampedModel):
    """Per-case evidence; telemetry must never copy these confidential fields."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="question_evaluation_evidence"
    )
    run = models.ForeignKey(
        QuestionEvaluationRun, on_delete=models.CASCADE, related_name="case_evidence"
    )
    question_case = models.ForeignKey(
        QuestionCase,
        on_delete=models.PROTECT,
        related_name="evaluation_evidence",
    )
    ordinal = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=QuestionEvaluationEvidenceStatus.choices)
    passed = models.BooleanField(null=True)
    generated_answer = models.TextField(blank=True)
    retrieval_evidence = models.JSONField(default=list)
    assertions = models.JSONField(default=list)
    judge = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "ordinal"], name="uniq_question_evidence_run_ordinal"
            ),
            models.UniqueConstraint(
                fields=["run", "question_case"],
                name="uniq_question_evidence_run_case",
            ),
        ]
        ordering = ["run_id", "ordinal"]

    def clean(self) -> None:
        if self.run_id and self.run.organization_id != self.organization_id:
            raise ValidationError("evidence organization must match run")
        if self.question_case_id and self.question_case.organization_id != self.organization_id:
            raise ValidationError("evidence case organization must match run")
