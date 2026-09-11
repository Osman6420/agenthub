"""Tool execution proxy: default-deny policy, egress, secrets, and contracts."""

from __future__ import annotations

from typing import Any

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.identity.capabilities import Capability
from apps.releases.compiler import ArtifactRef, compile_release
from apps.tenancy.models import Organization
from apps.tools.adapters import ToolAdapterRequest, ToolAdapterResponse
from apps.tools.proxy import (
    ResolvedTool,
    ToolApprovalRequired,
    ToolCallResult,
    ToolExecutionError,
    invoke_tool,
    resolve_release_tool,
)
from apps.tools.secrets_resolver import EnvSecretResolver, SecretResolver
from apps.tools.services import register_tool_binding, register_tool_definition
from apps.workflows.presets import empty_workflow

PUBLIC_IP = "93.184.216.34"


def _public_resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    return [(2, 1, 6, "", (PUBLIC_IP, port))]


def _private_resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    return [(2, 1, 6, "", ("10.0.0.1", port))]


def _tool(**overrides: Any) -> ResolvedTool:
    base: dict[str, Any] = {
        "role": "tool_binding.search",
        "definition_ref": "search:v1",
        "binding_checksum": "deadbeef",
        "protocol": "http",
        "method": "GET",
        "destination": {"scheme": "https", "host": "api.example.com", "port": 443},
        "input_contract": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_contract": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": True,
        },
        "secret_ref": None,
        "risk": "low",
        "side_effecting": False,
        "approval_required": False,
        "timeout_seconds": 10,
        "max_response_bytes": 65536,
        "allowed_input_fields": ("query",),
        "allowed_output_fields": ("status", "echo"),
    }
    base.update(overrides)
    return ResolvedTool(**base)


class _RecordingAdapter:
    def __init__(self, response: ToolAdapterResponse | None = None) -> None:
        self.calls: list[ToolAdapterRequest] = []
        self._response = response

    def call(self, request: ToolAdapterRequest) -> ToolAdapterResponse:
        self.calls.append(request)
        if self._response is not None:
            return self._response
        return ToolAdapterResponse(status_code=200, body={"status": "ok"})


class _StaticSecretResolver(SecretResolver):
    def __init__(self, value: str) -> None:
        self.value = value

    def resolve(self, ref: str) -> str:
        return self.value


def test_completed_low_risk_call() -> None:
    result = invoke_tool(
        tool=_tool(),
        consumer_capabilities=[Capability.TOOL_CALL],
        tool_input={"query": "hi"},
        dns_resolver=_public_resolver,
    )
    assert isinstance(result, ToolCallResult)
    assert result.outcome == "completed"
    assert result.output == {"status": "ok", "echo": {"query": "hi"}}


def test_capability_denied() -> None:
    with pytest.raises(ToolExecutionError, match="CAPABILITY_DENIED"):
        invoke_tool(
            tool=_tool(),
            consumer_capabilities=[],
            tool_input={"query": "hi"},
            dns_resolver=_public_resolver,
        )


def test_side_effecting_requires_side_effect_capability() -> None:
    tool = _tool(side_effecting=True)
    with pytest.raises(ToolExecutionError, match="CAPABILITY_DENIED"):
        invoke_tool(
            tool=tool,
            consumer_capabilities=[Capability.TOOL_CALL],
            tool_input={"query": "hi"},
            dns_resolver=_public_resolver,
        )
    result = invoke_tool(
        tool=tool,
        consumer_capabilities=[Capability.TOOL_CALL_SIDE_EFFECT],
        tool_input={"query": "hi"},
        dns_resolver=_public_resolver,
    )
    assert result.outcome == "completed"


def test_approval_required_raises_and_never_executes() -> None:
    adapter = _RecordingAdapter()
    with pytest.raises(ToolApprovalRequired):
        invoke_tool(
            tool=_tool(side_effecting=True, approval_required=True, risk="high"),
            consumer_capabilities=[Capability.TOOL_CALL_SIDE_EFFECT],
            tool_input={"query": "hi"},
            adapter=adapter,
            dns_resolver=_public_resolver,
        )
    assert adapter.calls == []


def test_input_field_not_allowed() -> None:
    with pytest.raises(ToolExecutionError, match="INPUT_FIELD_NOT_ALLOWED"):
        invoke_tool(
            tool=_tool(),
            consumer_capabilities=[Capability.TOOL_CALL],
            tool_input={"query": "hi", "injected": "x"},
            dns_resolver=_public_resolver,
        )


def test_input_contract_violation() -> None:
    with pytest.raises(ToolExecutionError, match="INPUT_CONTRACT_VIOLATION"):
        invoke_tool(
            tool=_tool(),
            consumer_capabilities=[Capability.TOOL_CALL],
            tool_input={"query": 123},
            dns_resolver=_public_resolver,
        )


def test_egress_denied_for_private_target() -> None:
    with pytest.raises(ToolExecutionError, match="DESTINATION_NOT_PUBLIC"):
        invoke_tool(
            tool=_tool(),
            consumer_capabilities=[Capability.TOOL_CALL],
            tool_input={"query": "hi"},
            dns_resolver=_private_resolver,
        )


def test_missing_secret_fails_closed() -> None:
    with pytest.raises(ToolExecutionError, match="SECRET_UNAVAILABLE"):
        invoke_tool(
            tool=_tool(secret_ref="secret:absent"),  # noqa: S106
            consumer_capabilities=[Capability.TOOL_CALL],
            tool_input={"query": "hi"},
            secret_resolver=EnvSecretResolver(),
            dns_resolver=_public_resolver,
        )


def test_secret_is_passed_to_adapter_but_not_returned() -> None:
    adapter = _RecordingAdapter(ToolAdapterResponse(200, {"status": "ok"}))
    result = invoke_tool(
        tool=_tool(secret_ref="secret:key"),  # noqa: S106
        consumer_capabilities=[Capability.TOOL_CALL],
        tool_input={"query": "hi"},
        adapter=adapter,
        secret_resolver=_StaticSecretResolver("s3cr3t"),
        dns_resolver=_public_resolver,
    )
    assert adapter.calls[0].credential == "s3cr3t"
    assert "s3cr3t" not in repr(result)


def test_output_field_not_allowed() -> None:
    adapter = _RecordingAdapter(ToolAdapterResponse(200, {"status": "ok", "exfil": "secret"}))
    with pytest.raises(ToolExecutionError, match="OUTPUT_FIELD_NOT_ALLOWED"):
        invoke_tool(
            tool=_tool(allowed_output_fields=("status",)),
            consumer_capabilities=[Capability.TOOL_CALL],
            tool_input={"query": "hi"},
            adapter=adapter,
            dns_resolver=_public_resolver,
        )


def test_output_contract_violation() -> None:
    adapter = _RecordingAdapter(ToolAdapterResponse(200, {"status": 500}))
    with pytest.raises(ToolExecutionError, match="OUTPUT_CONTRACT_VIOLATION"):
        invoke_tool(
            tool=_tool(),
            consumer_capabilities=[Capability.TOOL_CALL],
            tool_input={"query": "hi"},
            adapter=adapter,
            dns_resolver=_public_resolver,
        )


def test_oversized_response_is_denied() -> None:
    adapter = _RecordingAdapter(ToolAdapterResponse(200, {"status": "x" * 100}))
    with pytest.raises(ToolExecutionError, match="RESPONSE_TOO_LARGE"):
        invoke_tool(
            tool=_tool(max_response_bytes=10),
            consumer_capabilities=[Capability.TOOL_CALL],
            tool_input={"query": "hi"},
            adapter=adapter,
            dns_resolver=_public_resolver,
        )


# --- resolve_release_tool integration (reads the release-pinned binding) ---

ORG_SLUG = "tool-org"


def _definition_body() -> dict:
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
            "risk": "low",
            "side_effecting": False,
            "timeout_seconds": 10,
            "max_response_bytes": 65536,
            "rate_limit_per_minute": 60,
            "allowed_organizations": [ORG_SLUG],
        },
    }


def _binding_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolBinding",
        "metadata": {"id": "search-binding.v1", "owner": "editor"},
        "spec": {
            "tool_ref": "search:v1",
            "allowed_input_fields": ["query"],
            "allowed_output_fields": ["status", "echo"],
            "approval": {
                "required": False,
            },
        },
    }


def _make_pinned_release():
    org = Organization.objects.create(slug=ORG_SLUG, name="Tool Org")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(project=project, slug="flow", name="Flow")
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="tool_in",
        body={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        created_by="editor",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="tool_out",
        body={
            "type": "object",
            "properties": {"status": {"type": "string"}, "echo": {"type": "object"}},
            "required": ["status"],
            "additionalProperties": True,
        },
        created_by="editor",
    )
    definition_artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_DEFINITION,
        logical_id="search",
        body=_definition_body(),
        created_by="platform",
    )
    register_tool_definition(artifact=definition_artifact)
    binding_artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.TOOL_BINDING,
        logical_id="search_binding",
        body=_binding_body(),
        created_by="editor",
    )
    register_tool_binding(artifact=binding_artifact)
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="tool_workflow",
        body=empty_workflow(logical_id="tool_workflow"),
        created_by="editor",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                "workflow_definition", workflow.type, workflow.logical_id, workflow.version
            ),
            ArtifactRef(
                "tool_binding.search", binding_artifact.type, binding_artifact.logical_id, 1
            ),
        ],
        runtime_version="rt:9.0.0",
        created_by="editor",
    )
    return release


@pytest.mark.django_db
def test_resolve_release_tool_then_invoke() -> None:
    release = _make_pinned_release()
    tool = resolve_release_tool(release, "tool_binding.search")
    assert tool.protocol == "http"
    assert tool.destination["host"] == "api.example.com"
    assert tool.allowed_output_fields == ("status", "echo")
    result = invoke_tool(
        tool=tool,
        consumer_capabilities=[Capability.TOOL_CALL],
        tool_input={"query": "hi"},
        dns_resolver=_public_resolver,
    )
    assert result.outcome == "completed"


@pytest.mark.django_db
def test_resolve_release_tool_missing_role_fails_closed() -> None:
    release = _make_pinned_release()
    with pytest.raises(ToolExecutionError, match="TOOL_NOT_PINNED"):
        resolve_release_tool(release, "tool_binding.absent")
