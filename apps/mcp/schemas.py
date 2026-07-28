"""Stable MCP tool catalog and JSON Schema contracts."""

from __future__ import annotations

from typing import Any

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "agenthub__responses",
        "description": "Run an authorized AgentHub workflow through the canonical Responses API.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["model", "input", "idempotency_key"],
            "properties": {
                "model": {"type": "string", "minLength": 1, "maxLength": 200},
                "input": {
                    "oneOf": [
                        {"type": "string", "minLength": 1, "maxLength": 100000},
                        {"type": "array", "minItems": 1, "maxItems": 128},
                    ]
                },
                "background": {"type": "boolean"},
                "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
            },
        },
    },
    {
        "name": "agenthub__run_status",
        "description": "Read an authorized durable run status when available.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["run_id"],
            "properties": {"run_id": {"type": "string", "minLength": 1, "maxLength": 128}},
        },
    },
    {
        "name": "agenthub__ingestion_status",
        "description": "Read tenant-scoped ingestion status.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"run_id": {"type": "integer", "minimum": 1}},
        },
    },
    {
        "name": "agenthub__retrieve_debug",
        "description": "Return redacted retrieval diagnostics for an internal consumer.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["scenario_alias", "query"],
            "properties": {
                "scenario_alias": {"type": "string", "minLength": 1, "maxLength": 200},
                "query": {"type": "string", "minLength": 1, "maxLength": 100000},
            },
        },
    },
)

TOOL_BY_NAME = {tool["name"]: tool for tool in TOOLS}
