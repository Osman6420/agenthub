"""Mutable, tenant-scoped author working state for the visual builder.

A ``WorkflowDraft`` is *author working state* — it is neither a runtime graph nor an
immutable artifact. It holds a workflow DSL body that an operator edits in the console
builder. Publishing a draft routes the body through the same
:func:`apps.artifacts.services.create_artifact_version` path as GitOps, producing an
immutable ``workflow_definition`` ``ArtifactVersion``; the draft itself remains editable
so a later publish creates the next artifact version. The draft body carries no tenant
selector — every query is scoped by the authoritative ``organization`` column.

``ArtifactDraft`` is mutable author state for allowlisted non-workflow artifacts. Publishing
always routes through the canonical immutable artifact service.
"""

from __future__ import annotations

from django.db import models

from apps.artifacts.types import ArtifactType
from apps.tenancy.models import Organization, TimeStampedModel


class WorkflowDraft(TimeStampedModel):
    """An operator's editable workflow DSL, scoped to one organization."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_drafts"
    )
    project = models.ForeignKey(
        "catalog.AIProject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_drafts",
    )
    scenario = models.ForeignKey(
        "catalog.Scenario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_drafts",
    )
    name = models.CharField(max_length=200)
    # The target artifact ``logical_id`` used when the draft is published.
    logical_id = models.CharField(max_length=128)
    logical_description = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Stable purpose of the logical artifact across published versions.",
    )
    # The workflow DSL as author working state; may be incomplete/invalid while editing.
    body = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=200)
    updated_by = models.CharField(max_length=200)
    # Monotonic compare-and-swap token for editor updates and publish/delete actions.
    revision = models.PositiveBigIntegerField(default=1)
    # Records the most recent artifact version published from this draft (0 = never).
    last_published_version = models.PositiveIntegerField(default=0)
    last_published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "logical_id"],
                name="uniq_workflow_draft_org_logical",
            )
        ]
        indexes = [models.Index(fields=["organization", "-updated_at"])]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"workflow-draft:{self.organization_id}:{self.logical_id}"


class ArtifactDraft(TimeStampedModel):
    """Mutable author working state for allowlisted non-workflow artifacts.

    Published versions remain immutable; this row is only editable working state.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="artifact_drafts"
    )
    project = models.ForeignKey(
        "catalog.AIProject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artifact_drafts",
    )
    scenario = models.ForeignKey(
        "catalog.Scenario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artifact_drafts",
    )
    artifact_type = models.CharField(
        max_length=32,
        choices=[
            (ArtifactType.INPUT_CONTRACT, "Input contract"),
            (ArtifactType.OUTPUT_CONTRACT, "Output contract"),
            (ArtifactType.PROMPT_TEMPLATE, "Prompt template"),
            (ArtifactType.MODEL_PROFILE, "Model profile"),
            (ArtifactType.CHUNKING_PROFILE, "Chunking profile"),
            (ArtifactType.RETRIEVAL_PROFILE, "Retrieval profile"),
        ],
    )
    name = models.CharField(max_length=200)
    logical_id = models.CharField(max_length=128)
    logical_description = models.TextField(blank=True, max_length=1000)
    body = models.JSONField(default=dict)
    created_by = models.CharField(max_length=200)
    updated_by = models.CharField(max_length=200)
    revision = models.PositiveBigIntegerField(default=1)
    last_published_version = models.PositiveIntegerField(default=0)
    last_published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "artifact_type", "logical_id"],
                name="uniq_artifact_draft_org_type_logical",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "artifact_type", "-updated_at"],
                name="builder_art_org_type_upd_idx",
            )
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"artifact-draft:{self.organization_id}:{self.artifact_type}:{self.logical_id}"
