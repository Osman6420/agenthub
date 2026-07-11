"""Strict deterministic compiler for the non-executable AgentHub agent definition.

Compilation validates the artifact and emits an immutable, checksummed ``AgentConfig``:
the objective/output state keys, whether retrieval is enabled, the ordered allowlist of
tool binding roles the agent may propose, and the resolved (cap-clamped) limits. The
compiled config is the only thing the runtime trusts — it never re-reads the raw
artifact — so a run stays pinned to exactly these bounds and this tool allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.agents.agent_schema import AgentArtifactError, validate_agent_definition_body
from apps.agents.limits import resolve_limits
from apps.artifacts.types import ArtifactType
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


def validate_artifact_body(artifact_type: str, body: dict[str, Any]) -> None:
    if artifact_type == ArtifactType.AGENT_DEFINITION:
        compile_agent(body)


def compile_agent(body: dict[str, Any]) -> CompiledAgent:
    try:
        validate_agent_definition_body(body)
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
        "retrieval": {"enabled": bool(retrieval.get("enabled", False))},
        # Declared order is preserved: the deterministic planner proposes tools in this
        # order. The list is the agent's entire tool surface; the proxy still authorizes
        # each call against the release-pinned binding.
        "tools": list(spec.get("tools", [])),
        "limits": limits.as_dict(),
    }
    return CompiledAgent(config=config, checksum=compute_checksum(config))
