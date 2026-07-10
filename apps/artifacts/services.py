"""Artifact creation API.

All artifact writes go through :func:`create_artifact_version`, which validates the
body for its type, rejects inline secrets, computes the checksum, and auto-assigns
the next version for the (organization, type, logical_id) triple.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Max

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum, validate_body
from apps.tenancy.models import Organization


def next_version(organization: Organization, artifact_type: str, logical_id: str) -> int:
    current = ArtifactVersion.objects.filter(
        organization=organization, type=artifact_type, logical_id=logical_id
    ).aggregate(m=Max("version"))["m"]
    return (current or 0) + 1


@transaction.atomic
def create_artifact_version(
    *,
    organization: Organization,
    artifact_type: str,
    logical_id: str,
    body: dict,
    created_by: str,
    source_git_revision: str = "",
    version: int | None = None,
) -> ArtifactVersion:
    """Validate and persist a new immutable artifact version."""
    if artifact_type not in ArtifactType.values:
        raise ValueError(f"unknown artifact type: {artifact_type}")

    validate_body(artifact_type, body)

    resolved_version = (
        version if version is not None else next_version(organization, artifact_type, logical_id)
    )
    return ArtifactVersion.objects.create(
        organization=organization,
        type=artifact_type,
        logical_id=logical_id,
        version=resolved_version,
        body=body,
        checksum=compute_checksum(body),
        created_by=created_by,
        source_git_revision=source_git_revision,
    )
