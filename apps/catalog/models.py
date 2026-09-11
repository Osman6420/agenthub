"""Project/scenario catalog (v3 plan §6.2, §9.1).

``AIProject`` is a business unit's product container; ``Scenario`` is the callable,
releasable behavior inside it. ``ScenarioAlias`` is the stable external name a
consumer targets; an alias is closed/redirected, never deleted, and is unique
within an organization.
"""

from __future__ import annotations

import uuid

from django.db import models

from apps.tenancy.models import (
    Organization,
    TimeStampedModel,
    ensure_immutable_public_id,
)


class RiskLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class Visibility(models.TextChoices):
    INTERNAL = "internal", "Internal"
    CUSTOMER_FACING = "customer_facing", "Customer facing"


class LifecycleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class AliasStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    REDIRECTED = "redirected", "Redirected"


class ScenarioAccessMode(models.TextChoices):
    LEGACY = "legacy", "Mevcut erişimi koru"
    INHERIT = "inherit", "Projeden devral"
    PRIVATE = "private", "Bu senaryoya özel erişim"


class ScenarioDataAccessMode(models.TextChoices):
    CONSUMER_SPECIFIC = "consumer_specific", "İstemciye özel veri"
    SCENARIO_SHARED = "scenario_shared", "Senaryonun ortak verisi"


class ScenarioExecutionContract(models.TextChoices):
    LEGACY = "legacy", "Mevcut sürüm çözümleme"
    SNAPSHOT = "scenario-revision/v1", "Tek senaryo sürümü"


class ScenarioDataSelection(models.TextChoices):
    LEGACY_PINNED = "legacy_pinned", "Yayında seçilen veri sürümleri"
    ACTIVE_GENERATION = "active_generation", "Kullanıma hazır güncel veri"


class AIProject(TimeStampedModel):
    """A product/business-unit container that owns scenarios."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="projects"
    )
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    access_revision = models.PositiveIntegerField(default=0, db_default=0)
    access_change_id = models.CharField(max_length=64, blank=True, default="", db_default="")
    # Informational GitOps metadata only. Authorization is expressed by scoped
    # responsibility assignments, never by this label.
    owner = models.CharField(max_length=200, blank=True)
    risk_level = models.CharField(
        max_length=16, choices=RiskLevel.choices, default=RiskLevel.MEDIUM
    )
    data_classification = models.CharField(max_length=64, blank=True)
    default_locale = models.CharField(max_length=16, default="tr-TR")
    status = models.CharField(
        max_length=16, choices=LifecycleStatus.choices, default=LifecycleStatus.ACTIVE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "slug"], name="uniq_project_org_slug")
        ]
        ordering = ["organization_id", "slug"]

    def __str__(self) -> str:
        return f"{self.organization_id}/{self.slug}"

    def save(self, *args: object, **kwargs: object) -> None:
        ensure_immutable_public_id(self)
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class Scenario(TimeStampedModel):
    """A callable, releasable single-purpose AI behavior within a project."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="scenarios"
    )
    project = models.ForeignKey(AIProject, on_delete=models.CASCADE, related_name="scenarios")
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    execution_contract = models.CharField(
        max_length=32,
        choices=ScenarioExecutionContract.choices,
        default=ScenarioExecutionContract.LEGACY,
        db_default=ScenarioExecutionContract.LEGACY,
    )
    data_access_mode = models.CharField(
        max_length=24,
        choices=ScenarioDataAccessMode.choices,
        default=ScenarioDataAccessMode.CONSUMER_SPECIFIC,
        db_default=ScenarioDataAccessMode.CONSUMER_SPECIFIC,
    )
    data_selection = models.CharField(
        max_length=24,
        choices=ScenarioDataSelection.choices,
        default=ScenarioDataSelection.LEGACY_PINNED,
        db_default=ScenarioDataSelection.LEGACY_PINNED,
    )
    access_mode = models.CharField(
        max_length=16,
        choices=ScenarioAccessMode.choices,
        default=ScenarioAccessMode.LEGACY,
        db_default=ScenarioAccessMode.LEGACY,
    )
    access_revision = models.PositiveIntegerField(default=0, db_default=0)
    access_change_id = models.CharField(max_length=64, blank=True, default="", db_default="")
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.INTERNAL
    )
    risk_level = models.CharField(
        max_length=16, choices=RiskLevel.choices, default=RiskLevel.MEDIUM
    )
    status = models.CharField(
        max_length=16, choices=LifecycleStatus.choices, default=LifecycleStatus.DRAFT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "slug"], name="uniq_scenario_project_slug"),
            models.CheckConstraint(
                condition=models.Q(execution_contract__in=ScenarioExecutionContract.values),
                name="scenario_execution_contract_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(data_selection=ScenarioDataSelection.LEGACY_PINNED)
                    | models.Q(
                        data_selection=ScenarioDataSelection.ACTIVE_GENERATION,
                        execution_contract=ScenarioExecutionContract.SNAPSHOT,
                    )
                ),
                name="scenario_data_selection_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(access_mode__in=ScenarioAccessMode.values),
                name="scenario_access_mode_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(data_access_mode__in=ScenarioDataAccessMode.values),
                name="scenario_data_access_mode_valid",
            ),
        ]
        ordering = ["project_id", "slug"]

    def __str__(self) -> str:
        return f"{self.project}/{self.slug}"

    def save(self, *args: object, **kwargs: object) -> None:
        ensure_immutable_public_id(self)
        if self.project_id:
            project_org_id = self.project.organization_id
            if self.organization_id and self.organization_id != project_org_id:
                raise ValueError("scenario organization must match project organization")
            self.organization_id = project_org_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class ScenarioAlias(TimeStampedModel):
    """Stable external name for a scenario; unique within an organization.

    ``organization`` is denormalized from ``scenario.project.organization`` so the
    uniqueness invariant can be enforced by a database constraint.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="scenario_aliases"
    )
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="aliases")
    alias = models.SlugField(max_length=128)
    status = models.CharField(
        max_length=16, choices=AliasStatus.choices, default=AliasStatus.ACTIVE
    )
    redirect_to = models.ForeignKey(
        Scenario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redirected_aliases",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "alias"], name="uniq_alias_org")
        ]
        ordering = ["organization_id", "alias"]

    def __str__(self) -> str:
        return self.alias

    def save(self, *args: object, **kwargs: object) -> None:
        # Keep the denormalized organization consistent with the scenario.
        if self.scenario_id and not self.organization_id:
            self.organization_id = self.scenario.project.organization_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]
