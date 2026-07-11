"""Pre-installed custom-node registry with restricted schema-checked execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import jsonschema

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.workflows.models import CustomNodeDefinition, CustomNodeStatus


class CustomNodeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NodeExecutionContext:
    organization_id: int
    scenario_id: int
    release_id: int
    run_id: int


class CustomNodeExecutor(Protocol):
    def __call__(
        self, config: dict[str, Any], state: dict[str, Any], context: NodeExecutionContext
    ) -> dict[str, Any]: ...


_EXECUTORS: dict[str, tuple[str, CustomNodeExecutor]] = {}


def register_executor(node_ref: str, package_version: str, executor: CustomNodeExecutor) -> None:
    """Register code already installed in the reviewed platform image."""
    _EXECUTORS[node_ref] = (package_version, executor)


def unregister_executor(node_ref: str) -> None:
    _EXECUTORS.pop(node_ref, None)


def execute_custom_node(
    *, node_ref: str, config: dict[str, Any], state: dict[str, Any], run: Any
) -> dict[str, Any]:
    if ".v" not in node_ref:
        raise CustomNodeError("CUSTOM_NODE_REF_INVALID")
    logical_id, _, version_text = node_ref.rpartition(".v")
    if not version_text.isdigit():
        raise CustomNodeError("CUSTOM_NODE_REF_INVALID")
    definition = CustomNodeDefinition.objects.filter(
        organization_id=run.organization_id,
        logical_id=logical_id,
        version=int(version_text),
        status=CustomNodeStatus.ACTIVE,
    ).first()
    if definition is None:
        raise CustomNodeError("CUSTOM_NODE_NOT_ALLOWED")
    manifest = definition.manifest["spec"]
    allowed_organizations = manifest.get("allowed_organizations", [])
    if run.organization.slug not in allowed_organizations:
        raise CustomNodeError("CUSTOM_NODE_NOT_ALLOWED")
    registered = _EXECUTORS.get(node_ref)
    if registered is None or registered[0] != definition.installed_package_version:
        raise CustomNodeError("CUSTOM_NODE_PACKAGE_UNAVAILABLE")
    expected_version = str(manifest.get("package_version", ""))
    if registered[0] != expected_version:
        raise CustomNodeError("CUSTOM_NODE_PACKAGE_MISMATCH")

    config_schema = _resolve_schema(run.organization_id, manifest["config_schema_ref"])
    input_schema = _resolve_schema(run.organization_id, manifest["input_state_schema_ref"])
    output_schema = _resolve_schema(run.organization_id, manifest["output_state_schema_ref"])
    try:
        jsonschema.validate(config, config_schema)
        jsonschema.validate(state, input_schema)
    except jsonschema.ValidationError:
        raise CustomNodeError("CUSTOM_NODE_INPUT_INVALID") from None
    _, executor = registered
    patch = executor(
        dict(config),
        dict(state),
        NodeExecutionContext(
            organization_id=run.organization_id,
            scenario_id=run.scenario_id,
            release_id=run.release_id,
            run_id=run.id,
        ),
    )
    if not isinstance(patch, dict):
        raise CustomNodeError("CUSTOM_NODE_OUTPUT_INVALID")
    try:
        jsonschema.validate(patch, output_schema)
    except jsonschema.ValidationError:
        raise CustomNodeError("CUSTOM_NODE_OUTPUT_INVALID") from None
    return patch


def _resolve_schema(organization_id: int, ref: str) -> dict[str, Any]:
    if ":v" not in ref:
        raise CustomNodeError("CUSTOM_NODE_SCHEMA_UNRESOLVED")
    logical_id, _, version_text = ref.rpartition(":v")
    if not version_text.isdigit():
        raise CustomNodeError("CUSTOM_NODE_SCHEMA_UNRESOLVED")
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type__in=[ArtifactType.INPUT_CONTRACT, ArtifactType.OUTPUT_CONTRACT],
        logical_id=logical_id,
        version=int(version_text),
    ).first()
    if artifact is None:
        raise CustomNodeError("CUSTOM_NODE_SCHEMA_UNRESOLVED")
    return artifact.body
