"""Scenario Studio release-manifest authoring services.

The browser supplies only exact artifact-version identifiers and manifest roles.
This module re-resolves those identifiers within the trusted scenario tenant and
reuses the canonical release compiler for both no-write preflight and candidate
creation. It intentionally contains no alternate manifest validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.catalog.models import Scenario
from apps.releases.compiler import (
    MAX_MANIFEST_ROLE_LENGTH,
    ArtifactRef,
    CompileError,
    compile_release,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.workflows.compiler import WorkflowCompileError, compile_workflow
from apps.workflows.models import CustomNodeDefinition, CustomNodeStatus

MAX_MANIFEST_ARTIFACTS = 50
MAX_MANIFEST_REQUEST_BYTES = 64 * 1024

_REQUEST_ERROR_MESSAGES = {
    "manifest_items_invalid": "Manifest 1–50 exact artifact seçimi içermelidir.",
    "manifest_item_invalid": "Manifest satırı exact artifact ID ve rol içermelidir.",
    "manifest_role_invalid": "Manifest rolü geçersizdir.",
    "duplicate_artifact_version": "Aynı exact artifact manifestte bir kez seçilebilir.",
    "artifact_not_found": "Seçilen exact artifact bu senaryo kapsamında bulunamadı.",
    "workflow_artifact_required": "Dependency analizi için exact workflow artifact seçilmelidir.",
}


class ManifestRequestError(ValueError):
    """Stable, content-free request failure before canonical compilation."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _REQUEST_ERROR_MESSAGES else "manifest_item_invalid"
        super().__init__(_REQUEST_ERROR_MESSAGES[self.code])

    def as_diagnostic(self) -> dict[str, str]:
        return {"code": self.code, "message": _REQUEST_ERROR_MESSAGES[self.code]}


@dataclass(frozen=True)
class ManifestPreflightResult:
    ok: bool
    diagnostics: list[dict[str, Any]]
    artifact_manifest_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "diagnostics": self.diagnostics,
        }
        if self.artifact_manifest_sha256 is not None:
            result["artifact_manifest_sha256"] = self.artifact_manifest_sha256
        return result


def resolve_manifest_refs(*, scenario: Scenario, items: Any) -> list[ArtifactRef]:
    """Resolve a bounded browser manifest within ``scenario``'s organization."""

    if not isinstance(items, list) or not 1 <= len(items) <= MAX_MANIFEST_ARTIFACTS:
        raise ManifestRequestError("manifest_items_invalid")

    parsed: list[tuple[int, str]] = []
    artifact_ids: list[int] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"artifact_version_id", "role"}:
            raise ManifestRequestError("manifest_item_invalid")
        artifact_id = item.get("artifact_version_id")
        role = item.get("role")
        if isinstance(artifact_id, bool) or not isinstance(artifact_id, int) or artifact_id <= 0:
            raise ManifestRequestError("manifest_item_invalid")
        if (
            not isinstance(role, str)
            or not role
            or len(role) > MAX_MANIFEST_ROLE_LENGTH
            or not all(character.isalnum() or character in "._-" for character in role)
        ):
            raise ManifestRequestError("manifest_role_invalid")
        parsed.append((artifact_id, role))
        artifact_ids.append(artifact_id)

    if len(set(artifact_ids)) != len(artifact_ids):
        raise ManifestRequestError("duplicate_artifact_version")

    artifacts = {
        artifact.pk: artifact
        for artifact in ArtifactVersion.objects.filter(
            organization_id=scenario.organization_id,
            pk__in=artifact_ids,
        )
    }
    if len(artifacts) != len(artifact_ids):
        # Foreign and nonexistent IDs deliberately share one non-disclosing result.
        raise ManifestRequestError("artifact_not_found")

    return [
        ArtifactRef(
            role=role,
            type=artifacts[artifact_id].type,
            logical_id=artifacts[artifact_id].logical_id,
            version=artifacts[artifact_id].version,
        )
        for artifact_id, role in parsed
    ]


def candidate_runtime_version(scenario: Scenario) -> str:
    active = ScenarioRelease.objects.filter(
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
    ).first()
    return active.runtime_version if active is not None else "runtime:v1"


def analyze_workflow_requirements(
    *,
    scenario: Scenario,
    workflow_artifact_id: Any,
) -> dict[str, Any]:
    """Extract exact manifest-role requirements from the canonical compiled graph."""

    if (
        isinstance(workflow_artifact_id, bool)
        or not isinstance(workflow_artifact_id, int)
        or workflow_artifact_id <= 0
    ):
        raise ManifestRequestError("workflow_artifact_required")
    artifact = ArtifactVersion.objects.filter(
        pk=workflow_artifact_id,
        organization_id=scenario.organization_id,
        type=ArtifactType.WORKFLOW_DEFINITION,
    ).first()
    if artifact is None:
        raise ManifestRequestError("artifact_not_found")
    if compute_checksum(artifact.body) != artifact.checksum:
        raise CompileError(
            "workflow artifact checksum mismatch",
            code="artifact_checksum_mismatch",
            role="workflow_definition",
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        )

    allowed_custom_nodes = frozenset(
        f"{item.logical_id}.v{item.version}"
        for item in CustomNodeDefinition.objects.filter(
            organization_id=scenario.organization_id,
            status=CustomNodeStatus.ACTIVE,
        )
    )
    try:
        compiled = compile_workflow(
            artifact.body,
            allowed_custom_nodes=allowed_custom_nodes,
        )
    except WorkflowCompileError as exc:
        raise CompileError(
            f"workflow compilation failed: {exc}",
            code="workflow_compile_failed",
            role="workflow_definition",
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        ) from exc

    requirements: dict[str, dict[str, Any]] = {}

    def require(role: object, artifact_type: str, node_id: object = None) -> None:
        if not isinstance(role, str) or not role:
            return
        current = requirements.get(role)
        if current is not None and current["artifact_type"] != artifact_type:
            raise CompileError(
                f"manifest role '{role}' requires incompatible artifact types",
                code="role_type_mismatch",
                role=role,
                artifact_type=artifact_type,
            )
        if current is None:
            current = {
                "role": role,
                "artifact_type": artifact_type,
                "node_ids": [],
            }
            requirements[role] = current
        if isinstance(node_id, str) and node_id and node_id not in current["node_ids"]:
            current["node_ids"].append(node_id)

    require("workflow_definition", ArtifactType.WORKFLOW_DEFINITION)
    nodes = compiled.graph.get("nodes", [])
    if not isinstance(nodes, list):
        raise CompileError(
            "compiled workflow nodes are invalid",
            code="compiled_workflow_invalid",
        )
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        node_type = node.get("type")
        config = node.get("config")
        if not isinstance(config, dict):
            config = {}
        if node_type == "transform":
            require(
                config.get("transform_profile_ref"),
                ArtifactType.TRANSFORM_PROFILE,
                node_id,
            )
        elif node_type == "tool":
            require(config.get("binding_role"), ArtifactType.TOOL_BINDING, node_id)
        elif node_type == "generate":
            require(config.get("prompt_ref"), ArtifactType.PROMPT_TEMPLATE, node_id)
            require(config.get("model_profile_ref"), ArtifactType.MODEL_PROFILE, node_id)
        elif node_type == "retrieve":
            require(
                config.get("retrieval_profile_ref"),
                ArtifactType.RETRIEVAL_PROFILE,
                node_id,
            )
        elif node_type == "subworkflow":
            child_role = config.get("workflow_role")
            if isinstance(child_role, str):
                require(
                    f"child_workflow.{child_role}",
                    ArtifactType.WORKFLOW_DEFINITION,
                    node_id,
                )
        elif node_type == "agent_loop":
            policy = config.get("policy")
            if not isinstance(policy, dict):
                continue
            tools = policy.get("tools", [])
            if isinstance(tools, list):
                for role in tools:
                    require(role, ArtifactType.TOOL_BINDING, node_id)
            actions = policy.get("actions")
            verify_roles = actions.get("verify_roles", []) if isinstance(actions, dict) else []
            if isinstance(verify_roles, list):
                for role in verify_roles:
                    if role != "retrieval":
                        require(role, ArtifactType.TOOL_BINDING, node_id)

    ordered = sorted(
        requirements.values(),
        key=lambda item: (item["role"] != "workflow_definition", item["role"]),
    )
    for item in ordered:
        item["node_ids"].sort()
    return {
        "workflow": {
            "artifact_version_id": artifact.pk,
            "logical_id": artifact.logical_id,
            "version": artifact.version,
            "checksum": artifact.checksum,
        },
        "requirements": ordered,
    }


def preflight_release(
    *,
    scenario: Scenario,
    refs: list[ArtifactRef],
    runtime_version: str,
    created_by: str,
) -> ManifestPreflightResult:
    """Run the canonical compiler and roll back every database write.

    ``compile_release`` may create a canonical ``WorkflowVersion`` and candidate
    ``ScenarioRelease``. The outer transaction is always marked for rollback, so a
    successful preflight has the same durable no-write property as a rejected one.
    """

    with transaction.atomic():
        try:
            release = compile_release(
                scenario=scenario,
                refs=refs,
                runtime_version=runtime_version,
                created_by=created_by,
            )
        except CompileError as exc:
            result = ManifestPreflightResult(
                ok=False,
                diagnostics=[exc.as_diagnostic()],
            )
        else:
            result = ManifestPreflightResult(
                ok=True,
                diagnostics=[],
                artifact_manifest_sha256=release.artifact_manifest_sha256,
            )
        finally:
            transaction.set_rollback(True)
    return result
