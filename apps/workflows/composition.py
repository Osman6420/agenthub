"""Compile-time pinning for workflow-to-workflow composition."""

from __future__ import annotations

from typing import Any

from apps.artifacts.types import ArtifactType


class CompositionCompileError(ValueError):
    """Raised when a child workflow pin is missing, ambiguous or cyclic."""


def pin_composition_children(
    *,
    scenario: Any,
    graph: dict[str, Any],
    artifacts_manifest: dict[str, dict[str, Any]],
) -> None:
    """Pin each authored subworkflow node to one exact active child release."""

    organization_id = scenario.project.organization_id
    for node in graph.get("nodes", []):
        if not isinstance(node, dict) or node.get("type") != "subworkflow":
            continue
        config = node.get("config", {})
        role_name = config.get("workflow_role") if isinstance(config, dict) else None
        manifest_role = f"child_workflow.{role_name}"
        entry = artifacts_manifest.get(manifest_role)
        if not isinstance(entry, dict) or entry.get("type") != ArtifactType.WORKFLOW_DEFINITION:
            raise CompositionCompileError(
                f"composition node references an unpinned child role: {manifest_role}"
            )
        entry["child"] = _resolve_child_release_pin(
            organization_id=organization_id,
            entry=entry,
            parent_scenario_id=scenario.id,
        )


def _resolve_child_release_pin(
    *,
    organization_id: int,
    entry: dict[str, Any],
    parent_scenario_id: int,
) -> dict[str, Any]:
    from apps.artifacts.models import ArtifactVersion
    from apps.releases.models import ReleaseStatus, ScenarioRelease

    ref = str(entry.get("ref", ""))
    checksum = str(entry.get("checksum", ""))
    if ":v" not in ref:
        raise CompositionCompileError("child reference is invalid")
    logical_id, _, version_text = ref.rpartition(":v")
    if not version_text.isdigit():
        raise CompositionCompileError("child reference is invalid")
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id=logical_id,
        version=int(version_text),
        checksum=checksum,
    ).first()
    if artifact is None:
        raise CompositionCompileError("child artifact is unresolved in this organization")

    candidates = []
    for release in (
        ScenarioRelease.objects.filter(
            organization_id=organization_id,
            status=ReleaseStatus.ACTIVE,
        )
        .select_related("scenario")
        .iterator()
    ):
        pinned = release.manifest.get("artifacts", {}).get("workflow_definition")
        if (
            isinstance(pinned, dict)
            and pinned.get("ref") == ref
            and pinned.get("checksum") == checksum
        ):
            candidates.append(release)
    if not candidates:
        raise CompositionCompileError("child role has no active released scenario")
    if len(candidates) > 1:
        raise CompositionCompileError("child role resolves to multiple releases")
    release = candidates[0]
    if release.scenario_id == parent_scenario_id:
        raise CompositionCompileError("composition cycle: child resolves to the parent scenario")
    return {
        "kind": "workflow",
        "scenario_id": release.scenario_id,
        "release_id": release.id,
        "release_checksum": release.artifact_manifest_sha256,
        "artifact_checksum": checksum,
    }
