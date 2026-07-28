"""Structural validation for the embedded ``agent_loop`` workflow policy.

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

from apps.agents.limits import LIMIT_FIELDS, MAX_ROLE_CALLS, field_bounds

MAX_IDENTIFIER_LENGTH = 128
MAX_TOOLS = 10
MAX_SYSTEM_PROMPT_LENGTH = 8000
# Literal verification target meaning "re-run the pinned release retrieval" (no side effect).
VERIFY_RETRIEVAL = "retrieval"


class AgentArtifactError(ValueError):
    """Raised for safe, content-free agent-artifact validation diagnostics."""


def validate_agent_loop_policy(body: dict[str, Any]) -> None:
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
        optional={
            "retrieval",
            "limits",
            "objective_key",
            "output_key",
            "system_prompt",
            "actions",
        },
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
    if "actions" in spec:
        _validate_actions(spec.get("actions"), spec)


def _validate_actions(value: Any, spec: dict[str, Any]) -> None:
    """Governed action policy (P2.6.6). Data, not code — all fields optional; defaults
    reproduce single-use, no-verify, no-escalate behavior.

    ``verify_roles`` members must each be a declared tool role or the literal
    ``"retrieval"`` (permitted only when retrieval is enabled). ``role_call_caps`` keys
    must be declared tool roles and each cap is a bounded integer that may only lower the
    global tool-call budget. Side-effect/approval rejection for a verification role is
    enforced at release-compile time, where the pinned tool definition is known.
    """
    actions = _mapping(value, "actions")
    _require_exact_keys(
        actions,
        set(),
        "actions",
        optional={"verify_roles", "repeat_retrieval", "escalation_enabled", "role_call_caps"},
    )
    tool_roles = set(spec.get("tools") or [])
    retrieval_enabled = bool((spec.get("retrieval") or {}).get("enabled"))

    verify_roles = actions.get("verify_roles", [])
    if not isinstance(verify_roles, list) or len(verify_roles) > MAX_TOOLS + 1:
        raise AgentArtifactError("actions.verify_roles must be a bounded list")
    seen: set[str] = set()
    for role in verify_roles:
        _identifier(role, "verify role")
        if role in seen:
            raise AgentArtifactError("actions.verify_roles must be unique")
        seen.add(role)
        if role == VERIFY_RETRIEVAL:
            if not retrieval_enabled:
                raise AgentArtifactError("actions.verify_roles uses retrieval but it is disabled")
        elif role not in tool_roles:
            raise AgentArtifactError("actions.verify_roles must reference declared tools")

    for flag in ("repeat_retrieval", "escalation_enabled"):
        if flag in actions and not isinstance(actions.get(flag), bool):
            raise AgentArtifactError(f"actions.{flag} must be a boolean")
    if actions.get("repeat_retrieval") and not retrieval_enabled:
        raise AgentArtifactError("actions.repeat_retrieval requires retrieval to be enabled")

    caps = actions.get("role_call_caps", {})
    caps = _mapping(caps, "actions.role_call_caps")
    for role, cap in caps.items():
        _identifier(role, "role_call_caps role")
        if role not in tool_roles:
            raise AgentArtifactError("actions.role_call_caps must reference declared tools")
        if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= MAX_ROLE_CALLS:
            raise AgentArtifactError(
                f"actions.role_call_caps values must be within [1, {MAX_ROLE_CALLS}]"
            )


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
