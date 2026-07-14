"""Compiled scenario releases (v3 plan §8.5, §9.1).

A ``ScenarioRelease`` is an immutable composition of pinned artifact versions that
defines a full live behavior. Exactly one release per scenario may be ``active`` —
enforced by a database partial-unique constraint, not application logic alone.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.catalog.models import Scenario
from apps.tenancy.models import Organization


class ReleaseStatus(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    CANARY = "canary", "Canary"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"
    ROLLED_BACK = "rolled_back", "Rolled back"


class ScenarioRelease(models.Model):
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
            models.UniqueConstraint(
                fields=["scenario"],
                condition=Q(status="active"),
                name="uniq_active_release_per_scenario",
            )
        ]
        ordering = ["scenario_id", "-created_at"]

    def __str__(self) -> str:
        return f"release:{self.scenario_id}:{self.status}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.scenario_id:
            scenario_org_id = self.scenario.organization_id
            if self.organization_id and self.organization_id != scenario_org_id:
                raise ValueError("release organization must match scenario organization")
            self.organization_id = scenario_org_id
        super().save(*args, **kwargs)  # type: ignore[arg-type]


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
