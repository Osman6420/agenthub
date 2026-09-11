"""Registration cross-references, risk/approval invariants, and release pinning."""

from __future__ import annotations

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.releases.compiler import ArtifactRef, CompileError, compile_release
from apps.tenancy.models import Organization
from apps.tools.models import ToolBinding, ToolDefinition, ToolStatus
from apps.tools.services import (
    ToolRegistryError,
    register_tool_binding,
    register_tool_definition,
)
from apps.workflows.presets import empty_workflow

ORG_SLUG = "tool-org"


def _definition_body(*, risk: str = "low", side_effecting: bool = False) -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolDefinition",
        "metadata": {"id": "search.v1", "owner": "platform"},
        "spec": {
            "protocol": "http",
            "destination": {"scheme": "https", "host": "api.example.com"},
            "method": "GET",
            "input_contract_ref": "tool_in:v1",
            "output_contract_ref": "tool_out:v1",
            "risk": risk,
            "side_effecting": side_effecting,
            "timeout_seconds": 10,
            "max_response_bytes": 65536,
            "rate_limit_per_minute": 60,
            "allowed_organizations": [ORG_SLUG],
        },
    }


def _binding_body(*, required: bool = False) -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolBinding",
        "metadata": {"id": "search-binding.v1", "owner": "editor"},
        "spec": {
            "tool_ref": "search:v1",
            "allowed_input_fields": ["query"],
            "allowed_output_fields": ["results"],
            "approval": {
                "required": required,
            },
        },
    }


def _org(slug: str = ORG_SLUG) -> Organization:
    return Organization.objects.create(slug=slug, name=slug.upper())


def _scenario(org: Organization) -> Scenario:
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    return Scenario.objects.create(project=project, slug="flow", name="Flow")


def _make_definition(org: Organization, body: dict) -> ToolDefinition:
    artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_DEFINITION,
        logical_id="search",
        body=body,
        created_by="platform",
    )
    return register_tool_definition(artifact=artifact)


def _make_binding_artifact(org: Organization, body: dict):
    return create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_BINDING,
        logical_id="search_binding",
        body=body,
        created_by="editor",
    )


def _workflow_ref(org: Organization) -> ArtifactRef:
    artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="tool_workflow",
        body=empty_workflow(logical_id="tool_workflow"),
        created_by="editor",
    )
    return ArtifactRef(
        "workflow_definition",
        artifact.type,
        artifact.logical_id,
        artifact.version,
    )


@pytest.mark.django_db
def test_register_definition_requires_org_allowlist() -> None:
    org = _org()
    body = _definition_body()
    body["spec"]["allowed_organizations"] = ["someone-else"]
    artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_DEFINITION,
        logical_id="search",
        body=body,
        created_by="platform",
    )
    with pytest.raises(ToolRegistryError, match="TOOL_NOT_ALLOWED_FOR_ORG"):
        register_tool_definition(artifact=artifact)


@pytest.mark.django_db
def test_register_binding_missing_definition_is_denied() -> None:
    org = _org()
    artifact = _make_binding_artifact(org, _binding_body())
    with pytest.raises(ToolRegistryError, match="TOOL_DEFINITION_NOT_FOUND"):
        register_tool_binding(artifact=artifact)


@pytest.mark.django_db
def test_high_risk_side_effecting_tool_requires_approval() -> None:
    org = _org()
    _make_definition(org, _definition_body(risk="high", side_effecting=True))
    # Approval not required -> denied.
    with pytest.raises(ToolRegistryError, match="HIGH_RISK_REQUIRES_APPROVAL"):
        register_tool_binding(artifact=_make_binding_artifact(org, _binding_body(required=False)))


@pytest.mark.django_db
def test_high_risk_binding_with_valid_approval_registers() -> None:
    org = _org()
    _make_definition(org, _definition_body(risk="high", side_effecting=True))
    binding = register_tool_binding(
        artifact=_make_binding_artifact(org, _binding_body(required=True))
    )
    assert binding.approval_required is True
    assert binding.status == ToolStatus.ACTIVE


@pytest.mark.django_db
def test_low_risk_binding_registers_without_approval() -> None:
    org = _org()
    _make_definition(org, _definition_body())
    binding = register_tool_binding(artifact=_make_binding_artifact(org, _binding_body()))
    assert binding.approval_required is False


@pytest.mark.django_db
def test_compile_release_pins_registered_binding() -> None:
    org = _org()
    scenario = _scenario(org)
    _make_definition(org, _definition_body(risk="high", side_effecting=True))
    artifact = _make_binding_artifact(org, _binding_body(required=True))
    register_tool_binding(artifact=artifact)

    release = compile_release(
        scenario=scenario,
        refs=[
            _workflow_ref(org),
            ArtifactRef("tool_binding.search", artifact.type, artifact.logical_id, 1),
        ],
        runtime_version="rt:9.0.0",
        created_by="editor",
    )
    pin = release.manifest["artifacts"]["tool_binding.search"]["tool"]
    assert pin["definition_ref"] == "search:v1"
    assert pin["risk"] == "high"
    assert pin["side_effecting"] is True
    assert pin["approval_required"] is True


@pytest.mark.django_db
def test_compile_release_fails_when_binding_not_registered() -> None:
    org = _org()
    scenario = _scenario(org)
    _make_definition(org, _definition_body())
    artifact = _make_binding_artifact(org, _binding_body())  # not registered
    with pytest.raises(CompileError, match="TOOL_BINDING_NOT_REGISTERED"):
        compile_release(
            scenario=scenario,
            refs=[
                _workflow_ref(org),
                ArtifactRef("tool_binding.search", artifact.type, artifact.logical_id, 1),
            ],
            runtime_version="rt:9.0.0",
            created_by="editor",
        )


@pytest.mark.django_db
def test_compile_release_fails_when_definition_disabled() -> None:
    org = _org()
    scenario = _scenario(org)
    definition = _make_definition(org, _definition_body())
    artifact = _make_binding_artifact(org, _binding_body())
    register_tool_binding(artifact=artifact)
    definition.status = ToolStatus.DISABLED
    definition.save(update_fields=["status", "updated_at"])
    with pytest.raises(CompileError, match="TOOL_DEFINITION_DISABLED"):
        compile_release(
            scenario=scenario,
            refs=[
                _workflow_ref(org),
                ArtifactRef("tool_binding.search", artifact.type, artifact.logical_id, 1),
            ],
            runtime_version="rt:9.0.0",
            created_by="editor",
        )


@pytest.mark.django_db
def test_definition_body_is_immutable_but_status_can_change() -> None:
    org = _org()
    definition = _make_definition(org, _definition_body())
    definition.status = ToolStatus.DISABLED
    definition.save(update_fields=["status", "updated_at"])  # allowed
    definition.risk = "high"
    with pytest.raises(ValueError, match="immutable"):
        definition.save()


@pytest.mark.django_db
def test_binding_cross_tenant_definition_is_denied() -> None:
    owner = _org()
    other = _org("other-org")
    _make_definition(owner, _definition_body())
    # A binding artifact created in a different org cannot resolve the definition.
    artifact = _make_binding_artifact(other, _binding_body())
    with pytest.raises(ToolRegistryError, match="TOOL_DEFINITION_NOT_FOUND"):
        register_tool_binding(artifact=artifact)
    assert ToolBinding.objects.count() == 0
