"""Deterministic agent compilation and release-level tool-allowlist closure."""

from __future__ import annotations

import pytest

from apps.agents.compiler import AgentCompileError, compile_agent
from apps.agents.limits import MAX_STEPS, MAX_TOKENS
from apps.agents.tests.conftest import agent_body, build_agent
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.releases.compiler import ArtifactRef, CompileError, compile_release


def test_compile_emits_immutable_config_and_checksum() -> None:
    compiled = compile_agent(agent_body(tools=["search"], retrieval=True))
    assert compiled.config["api_version"] == "agenthub/compiled-agent/v1"
    assert compiled.config["agent_id"] == "assistant.v1"
    assert compiled.config["retrieval"] == {"enabled": True}
    assert compiled.config["tools"] == ["search"]
    assert compiled.config["limits"]["max_steps"] == MAX_STEPS
    assert compiled.config["limits"]["max_tokens"] == MAX_TOKENS
    assert len(compiled.checksum) == 64


def test_compile_is_deterministic() -> None:
    a = compile_agent(agent_body(tools=["a", "b"]))
    b = compile_agent(agent_body(tools=["a", "b"]))
    assert a.checksum == b.checksum


def test_tool_order_is_preserved() -> None:
    compiled = compile_agent(agent_body(tools=["b", "a", "c"]))
    assert compiled.tools == ("b", "a", "c")


def test_limits_lowered_but_never_raised() -> None:
    compiled = compile_agent(agent_body(limits={"max_steps": 3}))
    assert compiled.config["limits"]["max_steps"] == 3
    # Untouched fields keep the hard cap.
    assert compiled.config["limits"]["max_tokens"] == MAX_TOKENS


def test_compile_rejects_invalid_body() -> None:
    with pytest.raises(AgentCompileError):
        compile_agent(agent_body(tools=["dup", "dup"]))


@pytest.mark.django_db
def test_release_compile_pins_agent_checksum() -> None:
    fixture = build_agent(promote=False)
    assert "agent_checksum" in fixture.release.manifest
    assert "agent_definition" in fixture.release.manifest["artifacts"]


@pytest.mark.django_db
def test_release_rejects_tool_not_pinned() -> None:
    # An agent declaring a tool with no matching tool_binding role fails closed.
    from apps.catalog.models import AIProject, Scenario, ScenarioType
    from apps.tenancy.models import Organization

    org = Organization.objects.create(slug="closure-org", name="Closure")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(project=project, slug="a", name="A", type=ScenarioType.AGENT)
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.AGENT_DEFINITION,
        logical_id="assistant",
        body=agent_body(tools=["ghost_tool"]),
        created_by="editor",
    )
    with pytest.raises(CompileError):
        compile_release(
            scenario=scenario,
            refs=[ArtifactRef("agent_definition", ArtifactType.AGENT_DEFINITION, "assistant", 1)],
            runtime_version="agent:1",
            created_by="editor",
        )
