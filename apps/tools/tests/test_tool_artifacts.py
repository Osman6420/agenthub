"""Structural validation of tool_definition and tool_binding artifact bodies."""

from __future__ import annotations

import copy

import pytest

from apps.tools.tool_schema import (
    ToolArtifactError,
    validate_tool_binding_body,
    validate_tool_definition_body,
)


def _definition() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolDefinition",
        "metadata": {"id": "search.v1", "owner": "platform"},
        "spec": {
            "protocol": "http",
            "destination": {
                "scheme": "https",
                "host": "api.example.com",
                "port": 443,
                "path_prefix": "/v1",
            },
            "method": "GET",
            "input_contract_ref": "tool_in:v1",
            "output_contract_ref": "tool_out:v1",
            "risk": "low",
            "side_effecting": False,
            "timeout_seconds": 10,
            "max_response_bytes": 65536,
            "rate_limit_per_minute": 60,
            "allowed_organizations": ["tool-org"],
            "secret_ref": "secret:search-api-key",
        },
    }


def _binding() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "ToolBinding",
        "metadata": {"id": "search-binding.v1", "owner": "editor"},
        "spec": {
            "tool_ref": "search:v1",
            "allowed_input_fields": ["query"],
            "allowed_output_fields": ["results"],
            "approval": {
                "required": False,
                "approver_roles": ["approver"],
                "self_approval_allowed": False,
            },
        },
    }


def test_valid_definition_and_binding_pass() -> None:
    validate_tool_definition_body(_definition())
    validate_tool_binding_body(_binding())
    # An mcp tool omits the http method.
    mcp = _definition()
    mcp["spec"]["protocol"] = "mcp"
    del mcp["spec"]["method"]
    validate_tool_definition_body(mcp)


def test_mcp_destination_session_flag_is_optional_and_must_be_boolean() -> None:
    mcp = _definition()
    mcp["spec"]["protocol"] = "mcp"
    del mcp["spec"]["method"]
    mcp["spec"]["destination"]["session"] = True
    validate_tool_definition_body(mcp)  # accepted
    mcp["spec"]["destination"]["session"] = "yes"
    with pytest.raises(ToolArtifactError):
        validate_tool_definition_body(mcp)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["spec"]["destination"].__setitem__("host", "169.254.169.254"),
        lambda d: d["spec"]["destination"].__setitem__("host", "internalhost"),
        lambda d: d["spec"]["destination"].__setitem__("host", "svc.internal"),
        lambda d: d["spec"]["destination"].__setitem__("host", "localhost"),
        lambda d: d["spec"]["destination"].__setitem__("scheme", "http"),
        lambda d: d["spec"].__setitem__("protocol", "ftp"),
        lambda d: d["spec"].__setitem__("risk", "critical"),
        lambda d: d["spec"].__setitem__("risk", "extreme"),
        lambda d: d["spec"].__setitem__("side_effecting", "yes"),
        lambda d: d["spec"].__setitem__("timeout_seconds", 0),
        lambda d: d["spec"].__setitem__("timeout_seconds", 31),
        lambda d: d["spec"].__setitem__("max_response_bytes", 2_000_000),
        lambda d: d["spec"].__setitem__("rate_limit_per_minute", 0),
        lambda d: d["spec"].__setitem__("allowed_organizations", []),
        lambda d: d["spec"].__setitem__("secret_ref", "literal-key"),
        lambda d: d["spec"].__setitem__("input_contract_ref", "no-version"),
        lambda d: d["spec"].__setitem__("unexpected", True),
        lambda d: d.__setitem__("extra_top_level", 1),
        lambda d: d["spec"].__delitem__("method"),  # http requires a method
        lambda d: d["spec"]["destination"].__setitem__("path_prefix", "no-leading-slash"),
    ],
)
def test_invalid_definition_is_rejected(mutate) -> None:
    body = _definition()
    mutate(body)
    with pytest.raises(ToolArtifactError):
        validate_tool_definition_body(body)


def test_mcp_tool_rejects_http_method() -> None:
    body = _definition()
    body["spec"]["protocol"] = "mcp"
    with pytest.raises(ToolArtifactError):
        validate_tool_definition_body(body)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.__setitem__("kind", "Nope"),
        lambda b: b["spec"].__setitem__("tool_ref", "no-version"),
        lambda b: b["spec"]["approval"].__setitem__("approver_roles", []),
        lambda b: b["spec"]["approval"].__setitem__("approver_roles", ["intern"]),
        lambda b: b["spec"]["approval"].__setitem__("required", "true"),
        lambda b: b["spec"]["approval"].__setitem__("self_approval_allowed", 1),
        lambda b: b["spec"].__setitem__("allowed_input_fields", "query"),
        lambda b: b["spec"].__setitem__("allowed_output_fields", ["x"] * 51),
        lambda b: b["spec"].__setitem__("surprise", True),
    ],
)
def test_invalid_binding_is_rejected(mutate) -> None:
    body = copy.deepcopy(_binding())
    mutate(body)
    with pytest.raises(ToolArtifactError):
        validate_tool_binding_body(body)
