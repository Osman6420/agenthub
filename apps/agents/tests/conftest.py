"""Shared builders for agent-runtime tests.

The default fixture builds a promoted AGENT-type scenario with an input/output contract
and a compiled agent; ``with_tool`` additionally pins a high-risk, approval-required tool
binding so the pause/resume path can be exercised end to end.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.agents.models import AgentRun
from apps.agents.services import request_agent_run, resolve_release_agent
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias, ScenarioType
from apps.gateway.execution_context import issue_execution_context
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.tokens import create_token
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization

ALIAS = "agent-alias"

INPUT_CONTRACT = {
    "type": "object",
    "required": ["query"],
    "properties": {"query": {"type": "string"}},
    "additionalProperties": True,
}
OUTPUT_CONTRACT = {
    "type": "object",
    "required": ["answer", "sources"],
    "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
    "additionalProperties": True,
}


@dataclass
class AgentFixture:
    organization: Organization
    scenario: Scenario
    consumer: Consumer
    token: str
    alias: str
    release: ScenarioRelease


def agent_body(
    *,
    tools: list[str] | None = None,
    retrieval: bool = False,
    limits: dict | None = None,
    actions: dict | None = None,
) -> dict:
    spec: dict = {"tools": tools or []}
    if retrieval:
        spec["retrieval"] = {"enabled": True}
    if limits is not None:
        spec["limits"] = limits
    if actions is not None:
        spec["actions"] = actions
    return {
        "api_version": "agenthub/v1",
        "kind": "Agent",
        "metadata": {"id": "assistant.v1", "owner": "editor"},
        "spec": spec,
    }


def _verify_tool_definition_body(org_slug: str) -> dict:
    """A no-side-effect, low-risk tool usable as a P2.6.6 verification role."""
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolDefinition",
        "metadata": {"id": "check.v1", "owner": "platform"},
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
            "allowed_organizations": [org_slug],
        },
    }


def _verify_tool_binding_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolBinding",
        "metadata": {"id": "check-binding.v1", "owner": "editor"},
        "spec": {
            "tool_ref": "check:v1",
            "allowed_input_fields": ["query"],
            "allowed_output_fields": ["status", "echo"],
            "approval": {
                "required": False,
                "approver_roles": ["approver"],
                "self_approval_allowed": False,
            },
        },
    }


def _tool_definition_body(org_slug: str) -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolDefinition",
        "metadata": {"id": "search.v1", "owner": "platform"},
        "spec": {
            "protocol": "http",
            "destination": {"scheme": "https", "host": "api.example.com"},
            "method": "POST",
            "input_contract_ref": "tool_in:v1",
            "output_contract_ref": "tool_out:v1",
            "risk": "high",
            "side_effecting": True,
            "timeout_seconds": 10,
            "max_response_bytes": 65536,
            "rate_limit_per_minute": 60,
            "allowed_organizations": [org_slug],
        },
    }


def _tool_binding_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolBinding",
        "metadata": {"id": "search-binding.v1", "owner": "editor"},
        "spec": {
            "tool_ref": "search:v1",
            "allowed_input_fields": ["query"],
            "allowed_output_fields": ["status", "echo"],
            "approval": {
                "required": True,
                "approver_roles": ["approver"],
                "self_approval_allowed": False,
            },
        },
    }


def build_agent(
    *,
    org_slug: str = "agent-org",
    tools: list[str] | None = None,
    retrieval: bool = False,
    limits: dict | None = None,
    capabilities: list[str] | None = None,
    with_tool: bool = False,
    with_verify_tool: bool = False,
    actions: dict | None = None,
    policy_citations_required: bool = False,
    eval_suite: dict | None = None,
    promote: bool = True,
) -> AgentFixture:
    org = Organization.objects.create(slug=org_slug, name=org_slug)
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(
        project=project,
        slug="assistant",
        name="Assistant",
        type=ScenarioType.AGENT,
        status=LifecycleStatus.ACTIVE,
    )
    ScenarioAlias.objects.create(organization=org, scenario=scenario, alias=ALIAS)

    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="agent_input",
        body=INPUT_CONTRACT,
        created_by="editor",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="agent_output",
        body=OUTPUT_CONTRACT,
        created_by="editor",
    )
    refs = [
        ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "agent_input", 1),
        ArtifactRef("output_contract", ArtifactType.OUTPUT_CONTRACT, "agent_output", 1),
    ]

    if with_tool or with_verify_tool:
        from apps.tools.services import register_tool_binding, register_tool_definition

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
        declared: list[str] = []

    if with_tool:
        register_tool_definition(
            artifact=create_artifact_version(
                organization=org,
                artifact_type=ArtifactType.TOOL_DEFINITION,
                logical_id="search",
                body=_tool_definition_body(org_slug),
                created_by="platform",
            )
        )
        binding = create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.TOOL_BINDING,
            logical_id="search_binding",
            body=_tool_binding_body(),
            created_by="editor",
        )
        register_tool_binding(artifact=binding)
        refs.append(ArtifactRef("search", ArtifactType.TOOL_BINDING, "search_binding", 1))
        declared.append("search")

    if with_verify_tool:
        register_tool_definition(
            artifact=create_artifact_version(
                organization=org,
                artifact_type=ArtifactType.TOOL_DEFINITION,
                logical_id="check",
                body=_verify_tool_definition_body(org_slug),
                created_by="platform",
            )
        )
        vbinding = create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.TOOL_BINDING,
            logical_id="check_binding",
            body=_verify_tool_binding_body(),
            created_by="editor",
        )
        register_tool_binding(artifact=vbinding)
        refs.append(ArtifactRef("check", ArtifactType.TOOL_BINDING, "check_binding", 1))
        declared.append("check")

    if with_tool or with_verify_tool:
        tools = tools if tools is not None else declared

    if policy_citations_required:
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.POLICY_PROFILE,
            logical_id="policy",
            body={"output": {"citations": "required"}},
            created_by="editor",
        )
        refs.append(ArtifactRef("policy_profile", ArtifactType.POLICY_PROFILE, "policy", 1))

    if eval_suite is not None:
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.EVAL_SUITE,
            logical_id="suite",
            body=eval_suite,
            created_by="editor",
        )
        refs.append(ArtifactRef("eval_suite", ArtifactType.EVAL_SUITE, "suite", 1))

    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.AGENT_DEFINITION,
        logical_id="assistant",
        body=agent_body(tools=tools, retrieval=retrieval, limits=limits, actions=actions),
        created_by="editor",
    )
    refs.append(ArtifactRef("agent_definition", ArtifactType.AGENT_DEFINITION, "assistant", 1))

    release = compile_release(
        scenario=scenario, refs=refs, runtime_version="agent:1", created_by="editor"
    )
    if promote:
        promote_release(release)

    consumer = Consumer.objects.create(
        organization=org, subject="agent-client", name="Client", protocol=ConsumerProtocol.REST
    )
    ConsumerBinding.objects.create(
        consumer=consumer,
        scenario=scenario,
        capabilities=capabilities if capabilities is not None else [Capability.AGENT_INVOKE],
    )
    _, raw_token = create_token(consumer, "test")
    return AgentFixture(org, scenario, consumer, raw_token, ALIAS, release)


def make_run(fixture: AgentFixture, *, capabilities: list[str] | None = None) -> AgentRun:
    """Create a queued AgentRun for the fixture's release through the real service."""
    caps: list[str] = capabilities if capabilities is not None else [Capability.AGENT_INVOKE]
    context = issue_execution_context(
        organization_id=fixture.organization.id,
        project_id=fixture.scenario.project_id,
        scenario_id=fixture.scenario.id,
        scenario_alias=fixture.alias,
        consumer_id=fixture.consumer.id,
        capabilities=caps,
        release_id=fixture.release.id,
        request_id="req-agent-1",
    )
    run, _created = request_agent_run(
        release=fixture.release,
        consumer=fixture.consumer,
        agent_version=resolve_release_agent(fixture.release),
        execution_context=context,
        input_payload={"query": "hello"},
        idempotency_key="agent-key-1",
    )
    return run


@pytest.fixture
def agent_fixture(db: object) -> AgentFixture:
    return build_agent()
