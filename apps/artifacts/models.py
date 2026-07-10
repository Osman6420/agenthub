"""Immutable, versioned artifact registry (v3 plan §6.3, §9).

An ``ArtifactVersion`` is a canonical, checksummed definition (prompt, policy,
contract, profile, ...). Once created it is never modified; a change is a new
version. Releases pin exact versions so runtime behavior is reproducible.
"""

from __future__ import annotations

from django.db import models

from apps.artifacts.types import ArtifactType
from apps.tenancy.models import Organization


class ArtifactVersion(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="artifacts"
    )
    type = models.CharField(max_length=32, choices=ArtifactType.choices)
    logical_id = models.CharField(
        max_length=128, help_text="Stable identity across versions, e.g. 'customer_answer'."
    )
    version = models.PositiveIntegerField()
    body = models.JSONField()
    checksum = models.CharField(max_length=64, editable=False)
    created_by = models.CharField(max_length=200)
    source_git_revision = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "type", "logical_id", "version"],
                name="uniq_artifact_org_type_logical_version",
            )
        ]
        ordering = ["organization_id", "type", "logical_id", "-version"]

    def __str__(self) -> str:
        return self.ref

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            raise ValueError("ArtifactVersion is immutable; create a new version instead")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        # Retained for audit/reproducibility; retention cleanup is a separate,
        # controlled workflow (v3 plan §22.3), not an ad-hoc delete.
        raise ValueError("ArtifactVersion cannot be deleted directly")

    @property
    def ref(self) -> str:
        """Human/GitOps reference, e.g. ``customer_answer:v3``."""
        return f"{self.logical_id}:v{self.version}"
