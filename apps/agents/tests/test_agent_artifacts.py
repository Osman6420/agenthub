"""Author-time validation of the ``agent_definition`` artifact (data, not code)."""

from __future__ import annotations

import pytest

from apps.agents.agent_schema import AgentArtifactError, validate_agent_definition_body
from apps.artifacts.validation import ArtifactValidationError, validate_body


def _body(**spec_overrides: object) -> dict:
    spec: dict = {"tools": []}
    spec.update(spec_overrides)
    return {
        "api_version": "agenthub/v1",
        "kind": "Agent",
        "metadata": {"id": "assistant.v1", "owner": "editor"},
        "spec": spec,
    }


def test_minimal_agent_is_valid() -> None:
    validate_agent_definition_body(_body())


def test_full_agent_is_valid() -> None:
    validate_agent_definition_body(
        _body(
            tools=["search", "lookup"],
            retrieval={"enabled": True},
            limits={"max_steps": 5, "max_tool_calls": 2},
            objective_key="question",
            output_key="result",
        )
    )


def test_unknown_top_level_key_rejected() -> None:
    body = _body()
    body["extra"] = 1
    with pytest.raises(AgentArtifactError):
        validate_agent_definition_body(body)


def test_wrong_kind_rejected() -> None:
    body = _body()
    body["kind"] = "Workflow"
    with pytest.raises(AgentArtifactError):
        validate_agent_definition_body(body)


def test_too_many_tools_rejected() -> None:
    with pytest.raises(AgentArtifactError):
        validate_agent_definition_body(_body(tools=[f"t{i}" for i in range(11)]))


def test_duplicate_tools_rejected() -> None:
    with pytest.raises(AgentArtifactError):
        validate_agent_definition_body(_body(tools=["search", "search"]))


def test_limit_above_cap_rejected() -> None:
    with pytest.raises(AgentArtifactError):
        validate_agent_definition_body(_body(limits={"max_steps": 9999}))


def test_unknown_limit_field_rejected() -> None:
    with pytest.raises(AgentArtifactError):
        validate_agent_definition_body(_body(limits={"max_widgets": 1}))


def test_retrieval_enabled_must_be_bool() -> None:
    with pytest.raises(AgentArtifactError):
        validate_agent_definition_body(_body(retrieval={"enabled": "yes"}))


def test_validate_body_dispatch_wraps_error() -> None:
    # The generic artifact entrypoint re-wraps agent errors as ArtifactValidationError.
    with pytest.raises(ArtifactValidationError):
        validate_body("agent_definition", _body(tools=["a", "a"]))


def test_inline_secret_rejected_by_generic_validation() -> None:
    body = _body()
    body["metadata"]["password"] = "hunter2"  # noqa: S105
    with pytest.raises(ArtifactValidationError):
        validate_body("agent_definition", body)
