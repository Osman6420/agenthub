"""Closed configuration for the resource-only MCP ingestion adapter."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from apps.ingestion.mcp_resources import (
    PROTOCOL_VERSION,
    McpResourceClient,
    McpResourceError,
    McpResourceLimits,
    _uri,
)
from apps.tools.secrets_resolver import SecretResolutionError, _secret_name


def validate_resource_prefixes(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 50:
        raise McpResourceError("MCP_RESOURCE_SCOPE_REQUIRED")
    result = tuple(_uri(item) for item in value)
    if len(set(result)) != len(result) or any(not item.endswith("/") for item in result):
        raise McpResourceError("MCP_RESOURCE_PREFIX_INVALID")
    return result


def validate_mcp_profile(payload: dict[str, Any]) -> None:
    if set(payload) != {
        "logical_id",
        "revision",
        "protocol_version",
        "destination",
        "resource_prefixes",
        "mime_types",
        "limits",
        "secret_ref",
    }:
        raise McpResourceError("MCP_RESOURCE_PROFILE_FIELDS_INVALID")
    logical_id, revision = payload["logical_id"], payload["revision"]
    if (
        not isinstance(logical_id, str)
        or not 1 <= len(logical_id) <= 128
        or not logical_id.isascii()
        or any(not (c.isalnum() or c in "-_.") for c in logical_id)
        or type(revision) is not int
        or revision < 1
        or payload["protocol_version"] != PROTOCOL_VERSION
    ):
        raise McpResourceError("MCP_RESOURCE_PROFILE_IDENTITY_INVALID")
    destination = payload["destination"]
    if not isinstance(destination, dict):
        raise McpResourceError("MCP_RESOURCE_DESTINATION_INVALID")
    port = destination.get("port", 443)
    if type(port) is not int or not 1 <= port <= 65535:
        raise McpResourceError("MCP_RESOURCE_DESTINATION_INVALID")
    limits = payload["limits"]
    if not isinstance(limits, dict) or set(limits) - {f.name for f in fields(McpResourceLimits)}:
        raise McpResourceError("MCP_RESOURCE_LIMIT_INVALID")
    prefixes = validate_resource_prefixes(payload["resource_prefixes"])
    mime_types = payload["mime_types"]
    if not isinstance(mime_types, list) or any(not isinstance(v, str) for v in mime_types):
        raise McpResourceError("MCP_RESOURCE_MIME_UNSUPPORTED")
    if len(set(mime_types)) != len(mime_types):
        raise McpResourceError("MCP_RESOURCE_MIME_UNSUPPORTED")
    secret_ref = payload["secret_ref"]
    if not isinstance(secret_ref, str):
        raise McpResourceError("MCP_RESOURCE_SECRET_REF_INVALID")
    if secret_ref:
        try:
            _secret_name(secret_ref)
        except SecretResolutionError:
            raise McpResourceError("MCP_RESOURCE_SECRET_REF_INVALID") from None
    # Construction validates transport configuration without DNS, secrets or network I/O.
    McpResourceClient(
        destination=destination,
        resource_prefixes=prefixes,
        mime_types=tuple(mime_types),
        before_request=lambda: None,
        limits=McpResourceLimits(**limits),
    )


def validate_mcp_source_config(config: Any, allowed_prefixes: list[str]) -> tuple[str, ...]:
    if not isinstance(config, dict) or set(config) != {"resource_prefixes"}:
        raise McpResourceError("MCP_RESOURCE_SOURCE_CONFIG_INVALID")
    prefixes = validate_resource_prefixes(config["resource_prefixes"])
    allowed = validate_resource_prefixes(allowed_prefixes)
    if any(not any(prefix.startswith(scope) for scope in allowed) for prefix in prefixes):
        raise McpResourceError("MCP_RESOURCE_SCOPE_NOT_GRANTED")
    return prefixes
