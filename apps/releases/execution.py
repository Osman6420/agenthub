"""Resolve the release's explicit execution contract, never infer or fall back."""

from copy import deepcopy
from typing import Any

from apps.artifacts.validation import compute_checksum
from apps.catalog.models import ScenarioExecutionContract
from apps.releases.models import ScenarioRelease, ScenarioRevision
from apps.releases.revision_schema import RevisionError
from apps.releases.revisions import read_revision_snapshot
from apps.workflows.compiler import SNAPSHOT_COMPILER_VERSION


def release_revision(
    release: ScenarioRelease,
) -> tuple[ScenarioRevision | None, dict[str, Any] | None]:
    if release.execution_contract == ScenarioExecutionContract.LEGACY:
        return None, None
    if release.execution_contract != ScenarioExecutionContract.SNAPSHOT:
        raise RevisionError("REVISION_CONTRACT_UNSUPPORTED")
    revision = ScenarioRevision.objects.filter(
        source_release_id=release.pk,
        organization_id=release.organization_id,
        scenario_id=release.scenario_id,
    ).first()
    if revision is None:
        raise RevisionError("REVISION_REQUIRED")
    snapshot = read_revision_snapshot(revision)
    if (
        revision.source_manifest_checksum != release.artifact_manifest_sha256
        or compute_checksum(release.manifest) != revision.source_manifest_checksum
        or snapshot["workflow"]["compiler_version"] != SNAPSHOT_COMPILER_VERSION
    ):
        raise RevisionError("REVISION_RELEASE_CONFLICT")
    return revision, snapshot


def execution_manifest(release: ScenarioRelease) -> dict[str, Any]:
    _, snapshot = release_revision(release)
    return snapshot["manifest"] if snapshot is not None else deepcopy(release.manifest)


def run_workflow_graph(run: Any) -> dict[str, Any]:
    """Run/wait/branch/child must use the same revision captured at admission."""
    revision, snapshot = release_revision(run.release)
    if revision is None:
        if run.scenario_revision_id is not None:
            raise RevisionError("RUN_REVISION_CONFLICT")
        return run.workflow_version.compiled_graph
    if (
        snapshot is None
        or run.scenario_revision_id != revision.pk
        or run.organization_id != revision.organization_id
        or run.scenario_id != revision.scenario_id
        or run.workflow_version_id != revision.workflow_version_id
        or run.compiled_checksum != snapshot["workflow"]["checksum"]
        or run.compiler_version != snapshot["workflow"]["compiler_version"]
    ):
        raise RevisionError("RUN_REVISION_CONFLICT")
    return snapshot["workflow"]["graph"]
