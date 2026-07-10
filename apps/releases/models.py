"""Compiled scenario releases (v3 plan §8.5, §9.1).

A ``ScenarioRelease`` is an immutable composition of pinned artifact versions that
defines a full live behavior. Exactly one release per scenario may be ``active`` —
enforced by a database partial-unique constraint, not application logic alone.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.catalog.models import Scenario


class ReleaseStatus(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    CANARY = "canary", "Canary"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"
    ROLLED_BACK = "rolled_back", "Rolled back"


class ScenarioRelease(models.Model):
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
