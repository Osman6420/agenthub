"""Release compiler and promotion.

``compile_release`` resolves artifact references to exact versions within the
scenario's organization, re-validates each body, computes a manifest checksum, and
creates a ``candidate`` release. It fails closed: a missing reference, a validation
failure, or an inline secret raises ``CompileError`` and no candidate is created.

``promote_release`` performs the atomic active-pointer swap; the database
single-active constraint guarantees only one active release per scenario.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.validation import canonical_json, compute_checksum, validate_body
from apps.catalog.models import Scenario
from apps.releases.models import ReleaseStatus, ScenarioRelease


class CompileError(ValueError):
    """Raised when a release cannot be compiled from its references."""


@dataclass(frozen=True)
class ArtifactRef:
    """A reference to a specific artifact version, bound to a manifest role."""

    role: str
    type: str
    logical_id: str
    version: int


def _resolve(scenario: Scenario, ref: ArtifactRef) -> ArtifactVersion:
    organization_id = scenario.project.organization_id
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type=ref.type,
        logical_id=ref.logical_id,
        version=ref.version,
    ).first()
    if artifact is None:
        raise CompileError(
            f"unresolved reference for role '{ref.role}': "
            f"{ref.type} {ref.logical_id}:v{ref.version} not found in organization"
        )
    return artifact


@transaction.atomic
def compile_release(
    *,
    scenario: Scenario,
    refs: list[ArtifactRef],
    runtime_version: str,
    created_by: str,
    index_versions: list[int] | None = None,
) -> ScenarioRelease:
    if not refs:
        raise CompileError("a release must reference at least one artifact")

    # Optional pinned retrieval indexes. Readiness/tenant checks happen at the
    # promotion gate (Sprint 6); the retriever additionally filters by the release's
    # organization, so a stray pin can never surface another tenant's chunks.
    pinned_indexes = sorted({int(v) for v in (index_versions or [])})
    if any(v <= 0 for v in pinned_indexes):
        raise CompileError("index version ids must be positive integers")

    artifacts_manifest: dict[str, dict[str, object]] = {}
    for ref in refs:
        if ref.role in artifacts_manifest:
            raise CompileError(f"duplicate role in release: {ref.role}")
        artifact = _resolve(scenario, ref)
        # Defense in depth: re-validate the pinned body at compile time.
        try:
            validate_body(artifact.type, artifact.body)
        except ValueError as exc:
            raise CompileError(f"role '{ref.role}' failed validation: {exc}") from exc
        # Detect drift between stored checksum and current body.
        if compute_checksum(artifact.body) != artifact.checksum:
            raise CompileError(f"checksum mismatch for role '{ref.role}'")
        artifacts_manifest[ref.role] = {
            "type": artifact.type,
            "ref": artifact.ref,
            "checksum": artifact.checksum,
        }

    manifest: dict[str, object] = {
        "scenario_id": scenario.id,
        "runtime_version": runtime_version,
        "artifacts": artifacts_manifest,
    }
    if pinned_indexes:
        manifest["index_versions"] = pinned_indexes
    manifest_sha = compute_checksum(manifest)

    return ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.CANDIDATE,
        runtime_version=runtime_version,
        manifest=manifest,
        artifact_manifest_sha256=manifest_sha,
        created_by=created_by,
    )


@transaction.atomic
def promote_release(release: ScenarioRelease) -> ScenarioRelease:
    """Make ``release`` the single active release for its scenario (atomic swap).

    Minimal Sprint 2 promotion — the full gated promotion/canary/rollback path is
    Sprint 6. The DB constraint guarantees the single-active invariant.
    """
    previous = (
        ScenarioRelease.objects.select_for_update()
        .filter(scenario_id=release.scenario_id, status=ReleaseStatus.ACTIVE)
        .exclude(pk=release.pk)
        .first()
    )
    if previous is not None:
        previous.status = ReleaseStatus.SUPERSEDED
        previous.save(update_fields=["status"])

    release.status = ReleaseStatus.ACTIVE
    release.promoted_at = timezone.now()
    release.save(update_fields=["status", "promoted_at"])
    return release


def canonical_manifest(release: ScenarioRelease) -> str:
    """Canonical serialization of a release manifest (for diffing/snapshotting)."""
    return canonical_json(release.manifest)
