"""Compiled scenario releases (v3 plan §8.5, §9.1).

A ``ScenarioRelease`` is an immutable composition of pinned artifact versions that
defines a full live behavior. Exactly one release per scenario may be ``active`` —
enforced by a database partial-unique constraint, not application logic alone.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.catalog.models import Scenario, ScenarioExecutionContract
from apps.tenancy.models import Organization


class ReleaseStatus(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    CANARY = "canary", "Canary"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"
    ROLLED_BACK = "rolled_back", "Rolled back"


class ScenarioRelease(models.Model):
    execution_contract = models.CharField(
        max_length=32,
        choices=ScenarioExecutionContract.choices,
        default=ScenarioExecutionContract.LEGACY,
        db_default=ScenarioExecutionContract.LEGACY,
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="scenario_releases"
    )
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="releases")
    status = models.CharField(
        max_length=16, choices=ReleaseStatus.choices, default=ReleaseStatus.CANDIDATE
    )
    runtime_version = models.CharField(max_length=64)
    manifest = models.JSONField()
    artifact_manifest_sha256 = models.CharField(max_length=64)
    created_by = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    promoted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(execution_contract__in=ScenarioExecutionContract.values),
                name="release_execution_contract_valid",
            ),
            models.UniqueConstraint(
                fields=["scenario"],
                condition=Q(status="active"),
                name="uniq_active_release_per_scenario",
            ),
        ]
        ordering = ["scenario_id", "-created_at"]

    def __str__(self) -> str:
        return f"release:{self.scenario_id}:{self.status}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is not None:
            previous = (
                ScenarioRelease.objects.filter(pk=self.pk)
                .values(
                    "execution_contract",
                    "manifest",
                    "artifact_manifest_sha256",
                    "runtime_version",
                    "scenario_id",
                    "organization_id",
                )
                .first()
            )
            if previous is not None and (
                previous["execution_contract"] != self.execution_contract
                or (
                    self.execution_contract == ScenarioExecutionContract.SNAPSHOT
                    and any(value != getattr(self, field) for field, value in previous.items())
                )
            ):
                raise ValidationError("release execution pins are immutable")
        if self.scenario_id:
            scenario_org_id = self.scenario.organization_id
            if self.organization_id and self.organization_id != scenario_org_id:
                raise ValueError("release organization must match scenario organization")
            self.organization_id = scenario_org_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class ScenarioRevision(models.Model):
    """Self-contained executable revision, with protected compatibility provenance."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    scenario = models.ForeignKey(Scenario, on_delete=models.PROTECT, related_name="revisions")
    source_release = models.OneToOneField(
        ScenarioRelease, on_delete=models.PROTECT, related_name="execution_revision"
    )
    workflow_version = models.ForeignKey("workflows.WorkflowVersion", on_delete=models.PROTECT)
    number = models.PositiveBigIntegerField()
    contract_version = models.CharField(max_length=32)
    snapshot = models.JSONField()
    checksum = models.CharField(max_length=64)
    source_manifest_checksum = models.CharField(max_length=64)
    created_by = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "number"], name="uniq_scenario_revision_number"
            ),
            models.CheckConstraint(
                condition=Q(number__gt=0), name="scenario_revision_number_positive"
            ),
        ]
        ordering = ["scenario_id", "-number"]

    def __str__(self) -> str:
        return f"scenario-revision:{self.scenario_id}:{self.number}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is not None:
            raise ValidationError("ScenarioRevision is immutable")
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        from apps.artifacts.validation import compute_checksum
        from apps.releases.revision_schema import REVISION_CONTRACT, validate_revision_snapshot

        validate_revision_snapshot(self.snapshot)
        if (
            self.contract_version != REVISION_CONTRACT
            or self.checksum != compute_checksum(self.snapshot)
            or self.source_manifest_checksum != compute_checksum(self.snapshot["manifest"])
            or self.snapshot["scope"]
            != {
                "organization_id": self.organization_id,
                "scenario_id": self.scenario_id,
                "source_release_id": self.source_release_id,
            }
            or self.snapshot["workflow"]["id"] != self.workflow_version_id
            or self.source_release.organization_id != self.organization_id
            or self.source_release.scenario_id != self.scenario_id
            or self.source_release.artifact_manifest_sha256 != self.source_manifest_checksum
            or self.source_release.manifest != self.snapshot["manifest"]
            or self.scenario.organization_id != self.organization_id
            or self.workflow_version.organization_id != self.organization_id
            or self.workflow_version.scenario_id != self.scenario_id
            or self.workflow_version.checksum != self.snapshot["workflow"]["checksum"]
            or self.workflow_version.compiler_version
            != self.snapshot["workflow"]["compiler_version"]
            or self.workflow_version.compiled_graph != self.snapshot["workflow"]["graph"]
            or self.workflow_version.source_artifact_id
            != self.snapshot["artifacts"]["workflow_definition"]["id"]
        ):
            raise ValidationError("REVISION_SCOPE_OR_CHECKSUM_INVALID")


class ScenarioPublication(models.Model):
    """An idempotent operator intent; release and evaluation remain state authorities."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    scenario = models.ForeignKey(Scenario, on_delete=models.PROTECT, related_name="publications")
    draft = models.ForeignKey(
        "builder.WorkflowDraft", on_delete=models.PROTECT, null=True, blank=True
    )
    source_job = models.ForeignKey(
        "ingestion.StagedIndexBuildJob",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="publications",
    )
    release = models.OneToOneField(
        ScenarioRelease, on_delete=models.PROTECT, related_name="publication"
    )
    evaluation = models.OneToOneField("evaluations.EvalRun", on_delete=models.PROTECT)
    baseline_release = models.ForeignKey(
        ScenarioRelease, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    request_checksum = models.CharField(max_length=64)
    prepared_checksum = models.CharField(max_length=64)
    created_by = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(draft__isnull=False, source_job__isnull=True)
                    | models.Q(draft__isnull=True, source_job__isnull=False)
                ),
                name="publication_single_origin",
            ),
            models.UniqueConstraint(
                fields=["source_job", "scenario"],
                condition=models.Q(source_job__isnull=False),
                name="uniq_source_job_scenario_publication",
            ),
        ]

    def __str__(self) -> str:
        return str(self.public_id)

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is not None:
            previous = type(self).objects.values().get(pk=self.pk)
            if any(
                value != getattr(self, field)
                for field, value in previous.items()
                if field != "completed_at"
            ) or (
                previous["completed_at"] is not None
                and previous["completed_at"] != self.completed_at
            ):
                raise ValidationError("PUBLICATION_INTENT_IMMUTABLE")
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def clean(self) -> None:
        import re

        if (
            not re.fullmatch(r"[0-9a-f]{64}", self.request_checksum)
            or not re.fullmatch(r"[0-9a-f]{64}", self.prepared_checksum)
            or self.scenario.organization_id != self.organization_id
            or (self.draft_id is None) == (self.source_job_id is None)
            or (
                self.draft is not None
                and (
                    self.draft.organization_id != self.organization_id
                    or self.draft.scenario_id != self.scenario_id
                    or self.draft.project_id != self.scenario.project_id
                )
            )
            or (
                self.source_job is not None
                and (
                    self.source_job.organization_id != self.organization_id
                    or self.evaluation.prepared_source_job_id != self.source_job_id
                    or self.baseline_release_id is None
                )
            )
            or self.release.organization_id != self.organization_id
            or self.release.scenario_id != self.scenario_id
            or self.evaluation.organization_id != self.organization_id
            or self.evaluation.release_id != self.release_id
            or (
                self.baseline_release is not None
                and (
                    self.baseline_release.organization_id != self.organization_id
                    or self.baseline_release.scenario_id != self.scenario_id
                )
            )
        ):
            raise ValidationError("PUBLICATION_SCOPE_INVALID")

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError("PUBLICATION_INTENT_IMMUTABLE")


class CanaryStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    STOPPED = "stopped", "Stopped"
    EXPIRED = "expired", "Expired"


class ReleaseCanary(models.Model):
    """A time-bounded assignment routing one consumer to a candidate release.

    Canary routing is consumer-scoped (never a percentage) and only takes effect
    after the gateway has authenticated the consumer and authorized its scenario
    binding. Exactly one *active* canary may exist per (scenario, consumer).
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="release_canaries"
    )
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="canaries")
    consumer = models.ForeignKey(
        "identity.Consumer", on_delete=models.CASCADE, related_name="canaries"
    )
    release = models.ForeignKey(ScenarioRelease, on_delete=models.CASCADE, related_name="canaries")
    status = models.CharField(
        max_length=16, choices=CanaryStatus.choices, default=CanaryStatus.ACTIVE
    )
    expires_at = models.DateTimeField()
    created_by = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "consumer"],
                condition=Q(status="active"),
                name="uniq_active_canary_per_consumer_scenario",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"canary:{self.scenario_id}->{self.release_id}@{self.consumer_id}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.scenario_id:
            scenario_org_id = self.scenario.organization_id
            if self.organization_id and self.organization_id != scenario_org_id:
                raise ValidationError("canary organization must match scenario organization")
            self.organization_id = scenario_org_id
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def clean(self) -> None:
        # Same-tenant, same-scenario invariants (defense in depth around the gate).
        if self.release_id and self.release.scenario_id != self.scenario_id:
            raise ValidationError("canary release must belong to the target scenario")
        if self.consumer_id and self.scenario_id:
            if self.consumer.organization_id != self.scenario.project.organization_id:
                raise ValidationError("consumer and scenario must belong to the same organization")
