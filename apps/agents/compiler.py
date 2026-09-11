"""Strict deterministic compiler for an embedded workflow agent policy.

Compilation validates the artifact and emits an immutable, checksummed ``AgentConfig``:
the objective/output state keys, whether retrieval is enabled, the ordered allowlist of
tool binding roles the agent may propose, and the resolved (cap-clamped) limits. The
compiled config is the only thing the runtime trusts — it never re-reads the raw
artifact — so a run stays pinned to exactly these bounds and this tool allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.agents.agent_schema import AgentArtifactError, validate_agent_loop_policy
from apps.agents.limits import resolve_limits
from apps.agents.planner import AGENT_DECISION_SCHEMA_VERSION
from apps.artifacts.validation import compute_checksum

COMPILER_VERSION = "agent-compiler/v1"
DEFAULT_OBJECTIVE_KEY = "query"
DEFAULT_OUTPUT_KEY = "output"


class AgentCompileError(ValueError):
    """Raised for safe, content-free agent compilation diagnostics."""


@dataclass(frozen=True)
class CompiledAgent:
    config: dict[str, Any]
    checksum: str

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(self.config["tools"])


def compile_agent(body: dict[str, Any]) -> CompiledAgent:
    try:
        validate_agent_loop_policy(body)
    except AgentArtifactError as exc:
        raise AgentCompileError(str(exc)) from exc

    spec = body["spec"]
    retrieval = spec.get("retrieval", {})
    limits = resolve_limits(spec.get("limits"))
    config = {
        "api_version": "agenthub/compiled-agent/v1",
        "agent_id": body["metadata"]["id"],
        "objective_key": spec.get("objective_key", DEFAULT_OBJECTIVE_KEY),
        "output_key": spec.get("output_key", DEFAULT_OUTPUT_KEY),
        # Authored persona/instructions (P6). Empty when unset; pinned into the checksum so a run
        # stays bound to exactly this system prompt. It is input to the model, never authorization.
        "system_prompt": spec.get("system_prompt", ""),
        "retrieval": {"enabled": bool(retrieval.get("enabled", False))},
        # Declared order is preserved: the deterministic planner proposes tools in this
        # order. The list is the agent's entire tool surface; the proxy still authorizes
        # each call against the release-pinned binding.
        "tools": list(spec.get("tools", [])),
        "limits": limits.as_dict(),
    }
    # Governed action policy (P2.6.6). Emitted *only when authored* so agents that do not
    # opt in keep a byte-identical compiled config and a stable checksum. The decision
    # schema version is a runtime constant carried on each proposal, not written here.
    if "actions" in spec:
        config["decision_schema_version"] = AGENT_DECISION_SCHEMA_VERSION
        config["actions"] = _compile_actions(spec["actions"])
    return CompiledAgent(config=config, checksum=compute_checksum(config))


def _compile_actions(actions: dict[str, Any]) -> dict[str, Any]:
    """Normalize the validated action policy into a deterministic compiled block.

    Keys and ``verify_roles`` order are canonicalized so the compiled output — and thus
    the release checksum — is stable regardless of authored key/element ordering.
    """
    return {
        "verify_roles": sorted(actions.get("verify_roles", [])),
        "repeat_retrieval": bool(actions.get("repeat_retrieval", False)),
        "escalation_enabled": bool(actions.get("escalation_enabled", False)),
        "role_call_caps": {
            str(role): int(cap) for role, cap in sorted(actions.get("role_call_caps", {}).items())
        },
    }
