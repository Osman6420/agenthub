"""Release read helpers used by the runtime/gateway.

Resolution stays within the scenario's organization and reads only pinned versions
from a release manifest.
"""

from __future__ import annotations

from apps.artifacts.models import ArtifactVersion
from apps.catalog.models import Scenario
from apps.releases.execution import execution_manifest, release_revision
from apps.releases.models import ReleaseStatus, ScenarioRelease


def get_active_release(scenario: Scenario) -> ScenarioRelease | None:
    return ScenarioRelease.objects.filter(scenario=scenario, status=ReleaseStatus.ACTIVE).first()


def get_manifest_role(release: ScenarioRelease, role: str) -> dict | None:
    artifacts = execution_manifest(release).get("artifacts", {})
    entry = artifacts.get(role)
    return entry if isinstance(entry, dict) else None


def get_artifact_body_for_role(release: ScenarioRelease, role: str) -> dict | None:
    """Return the pinned artifact body for a manifest role, or None if absent.

    The manifest stores a portable ``ref`` (``logical_id:vN``); the body is resolved
    from the artifact registry within the scenario's organization.
    """
    _, snapshot = release_revision(release)
    if snapshot is not None:
        artifact = snapshot["artifacts"].get(role)
        return artifact["body"] if artifact is not None else None
    entry = get_manifest_role(release, role)
    if entry is None:
        return None
    ref = str(entry.get("ref", ""))
    artifact_type = str(entry.get("type", ""))
    if ":v" not in ref:
        return None
    logical_id, _, version_str = ref.rpartition(":v")
    if not version_str.isdigit():
        return None
    organization_id = release.scenario.project.organization_id
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type=artifact_type,
        logical_id=logical_id,
        version=int(version_str),
    ).first()
    return artifact.body if artifact is not None else None
