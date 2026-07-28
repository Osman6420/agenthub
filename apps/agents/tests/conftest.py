"""Pure builders for embedded agent-loop policy tests."""

from __future__ import annotations


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
