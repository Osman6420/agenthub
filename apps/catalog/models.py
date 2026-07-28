"""Project/scenario catalog (v3 plan §6.2, §9.1).

``AIProject`` is a business unit's product container; ``Scenario`` is the callable,
releasable behavior inside it. ``ScenarioAlias`` is the stable external name a
consumer targets; an alias is closed/redirected, never deleted, and is unique
within an organization.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import cast

from django.db import models

from apps.tenancy.models import (
    Organization,
    OrganizationMembership,
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


class AIProject(TimeStampedModel):
    """A product/business-unit container that owns scenarios."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="projects"
    )
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    owner_membership = models.ForeignKey(
        OrganizationMembership,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="owned_projects",
    )
    # Compatibility label for existing rows and the current GitOps contract. It is not authority.
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
        if self.owner_membership_id:
            membership = OrganizationMembership.objects.select_related("user").get(
                pk=self.owner_membership_id
            )
            if membership.organization_id != self.organization_id:
                raise ValueError("project owner membership must belong to project organization")
            self.owner = membership.user.get_username()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                fields = set(cast(Iterable[str], update_fields))
                if "owner_membership" in fields:
                    kwargs["update_fields"] = fields | {"owner"}
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
            models.UniqueConstraint(fields=["project", "slug"], name="uniq_scenario_project_slug")
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
