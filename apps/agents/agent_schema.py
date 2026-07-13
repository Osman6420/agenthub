"""Structural validation for the ``agent_definition`` artifact type (Sprint 10).

An agent definition is *data, not code*: it declares an objective source, an optional
retrieval step, an optional authored **system prompt** (bounded, redaction-safe text — the
agent's persona/instructions, P6), a bounded allowlist of tool *binding roles* the agent may
propose, and optional limit overrides that may only lower the hard caps. It never declares an
endpoint, package, or executable, and the system prompt is **input, never authorization** — the
model's decisions at runtime are proposals that the governed tool proxy, retrieval, and
output-contract gates re-validate. Diagnostics are content-free (v3 plan §17). This module is
DB-free; the existence of declared tool bindings is checked at release-compile time, and every
tool call is still authorized by the release-pinned proxy.
"""

from __future__ import annotations

from typing import Any

from apps.agents.limits import LIMIT_FIELDS, field_bounds

MAX_IDENTIFIER_LENGTH = 128
MAX_TOOLS = 10
MAX_SYSTEM_PROMPT_LENGTH = 8000


class AgentArtifactError(ValueError):
    """Raised for safe, content-free agent-artifact validation diagnostics."""


def validate_agent_artifact_body(artifact_type: str, body: dict[str, Any]) -> None:
    if artifact_type == "agent_definition":
        validate_agent_definition_body(body)


def validate_agent_definition_body(body: dict[str, Any]) -> None:
    _require_exact_keys(body, {"api_version", "kind", "metadata", "spec"}, "agent definition")
    if body.get("api_version") != "agenthub/v1" or body.get("kind") != "Agent":
        raise AgentArtifactError("unsupported agent api_version or kind")
    metadata = _mapping(body.get("metadata"), "metadata")
    _require_exact_keys(metadata, {"id", "owner"}, "metadata")
    _identifier(metadata.get("id"), "agent id")
    _identifier(metadata.get("owner"), "agent owner")

    spec = _mapping(body.get("spec"), "spec")
    _require_exact_keys(
        spec,
        {"tools"},
        "agent spec",
        optional={"retrieval", "limits", "objective_key", "output_key", "system_prompt"},
    )

    _validate_tools(spec.get("tools"))
    if "retrieval" in spec:
        _validate_retrieval(spec.get("retrieval"))
    if "limits" in spec:
        _validate_limits(spec.get("limits"))
    if "objective_key" in spec:
        _identifier(spec.get("objective_key"), "objective_key")
    if "output_key" in spec:
        _identifier(spec.get("output_key"), "output_key")
    if "system_prompt" in spec:
        _validate_system_prompt(spec.get("system_prompt"))


def _validate_system_prompt(value: Any) -> None:
    """Authored persona/instructions: bounded text, no control chars (P6). Data, not code."""
    if not isinstance(value, str) or not value.strip():
        raise AgentArtifactError("system_prompt must be a non-empty string")
    if len(value) > MAX_SYSTEM_PROMPT_LENGTH:
        raise AgentArtifactError(
            f"system_prompt must be at most {MAX_SYSTEM_PROMPT_LENGTH} characters"
        )
    if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise AgentArtifactError("system_prompt contains control characters")


def _validate_tools(value: Any) -> None:
    if not isinstance(value, list) or len(value) > MAX_TOOLS:
        raise AgentArtifactError(f"tools must be a list of at most {MAX_TOOLS} binding roles")
    seen: set[str] = set()
    for role in value:
        _identifier(role, "tool binding role")
        if role in seen:
            raise AgentArtifactError("tools must be unique")
        seen.add(role)


def _validate_retrieval(value: Any) -> None:
    retrieval = _mapping(value, "retrieval")
    _require_exact_keys(retrieval, {"enabled"}, "retrieval")
    if not isinstance(retrieval.get("enabled"), bool):
        raise AgentArtifactError("retrieval.enabled must be a boolean")


def _validate_limits(value: Any) -> None:
    limits = _mapping(value, "limits")
    unknown = set(limits) - LIMIT_FIELDS
    if unknown:
        raise AgentArtifactError("limits contains unknown fields")
    for field, candidate in limits.items():
        low, cap = field_bounds(field)
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise AgentArtifactError(f"limit {field} must be an integer")
        if not low <= candidate <= cap:
            raise AgentArtifactError(f"limit {field} must be within [{low}, {cap}]")


def _identifier(value: Any, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or not all(character.isalnum() or character in "._-" for character in value)
    ):
        raise AgentArtifactError(f"{name} is invalid")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentArtifactError(f"{name} must be an object")
    return value


def _require_exact_keys(
    value: dict[str, Any], required: set[str], name: str, *, optional: set[str] | None = None
) -> None:
    optional = optional or set()
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise AgentArtifactError(f"{name} is missing required fields")
    if unknown:
        raise AgentArtifactError(f"{name} contains unknown fields")
