"""Evaluation runs and per-case results (Sprint 6).

An :class:`EvalRun` records the deterministic evaluation of a *candidate* release
against the eval-suite artifact pinned in that release's manifest. Reports store the
assertion type, a boolean outcome, and a stable, content-free reason code only — never
raw prompts, model output, or retrieved passages (observability/data-minimization
rules). Every run is bound to the release's organization and enforces that boundary.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization, TimeStampedModel


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
