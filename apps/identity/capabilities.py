"""Consumer capability vocabulary (v3 plan §10.2).

Capabilities are the fine-grained actions a consumer binding may grant. They are an
explicit allowlist: a binding may only reference values defined here, and the
gateway (Sprint 3) enforces them on the request path.
"""

from __future__ import annotations

from django.db import models


class Capability(models.TextChoices):
    QUERY = "query", "Synchronous RAG/prompt query"
    QUERY_STREAM = "query_stream", "Streaming (SSE) answer"
    WORKFLOW_RUN = "workflow_run", "Start a defined workflow"
    AGENT_INVOKE = "agent_invoke", "Start a defined agent run"
    AGENT_RESUME = "agent_resume", "Resume an owned/permitted run"
    TOOL_CALL = "tool_call", "Read-only tool call"
    TOOL_CALL_SIDE_EFFECT = "tool_call_side_effect", "Side-effecting tool call"
    TOOL_APPROVE = "tool_approve", "Decide tool approvals"
    MEMORY_READ = "memory_read", "Read memory (if policy allows)"
    MEMORY_WRITE = "memory_write", "Write memory (if policy allows)"
    RETRIEVE_DEBUG = "retrieve_debug", "View redacted retrieved chunks"
    INGESTION_READ = "ingestion_read", "View ingestion status"
    INGESTION_TRIGGER = "ingestion_trigger", "Trigger ingestion manually"
    RELEASE_PROMOTE = "release_promote", "Promote a release"


ALL_CAPABILITIES: frozenset[str] = frozenset(Capability.values)


def validate_capabilities(values: list[str]) -> None:
    """Raise ``ValidationError`` if any capability is unknown or the list is malformed."""
    from django.core.exceptions import ValidationError

    if not isinstance(values, list):
        raise ValidationError("capabilities must be a list of strings")
    unknown = [v for v in values if v not in ALL_CAPABILITIES]
    if unknown:
        raise ValidationError(f"unknown capabilities: {sorted(unknown)}")
