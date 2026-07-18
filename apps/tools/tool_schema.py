"""Structural validation for ``tool_definition`` and ``tool_binding`` artifacts.

Tool artifacts are *data*, never code. A definition declares a single approved
outbound destination, its risk/side-effect posture, contracts, bounded limits, and
an optional ``secret:<name>`` credential reference; a binding attaches a definition
to a scenario release with a field allowlist and approval policy. This module is
deliberately DB-free and content-free in its diagnostics (v3 plan §17, §22.1); the
egress allowlist, DNS/redirect defenses, and credential resolution are enforced
later by the execution proxy, and cross-reference/risk invariants at registration.
"""

from __future__ import annotations

import ipaddress
from typing import Any

MAX_IDENTIFIER_LENGTH = 128
MAX_HOST_LENGTH = 253
MAX_LABEL_LENGTH = 63
MAX_PATH_PREFIX_LENGTH = 200
MAX_SECRET_REF_LENGTH = 200
MAX_FIELD_NAME_LENGTH = 128
MAX_FIELDS = 50
MAX_APPROVER_ROLES = 8

MAX_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1_048_576
MAX_RATE_LIMIT = 1000

ALLOWED_PROTOCOLS = frozenset({"http", "mcp"})
ALLOWED_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH"})
# ``critical`` is intentionally absent: critical tools are disabled in this release.
ALLOWED_RISKS = frozenset({"low", "medium", "high"})
ALLOWED_SCHEMES = frozenset({"https"})
ALLOWED_APPROVER_ROLES = frozenset(
    {"approver", "release_manager", "organization_admin", "platform_admin"}
)
DISALLOWED_HOST_SUFFIXES = frozenset({"local", "internal", "localhost", "localdomain"})
DISALLOWED_HOSTS = frozenset({"localhost", "metadata.google.internal", "metadata"})

SECRET_REFERENCE_PREFIX = "secret:"  # noqa: S105  # marker prefix, not a secret value


class ToolArtifactError(ValueError):
    """Raised for safe, content-free tool-artifact validation diagnostics."""


def validate_tool_artifact_body(artifact_type: str, body: dict[str, Any]) -> None:
    if artifact_type == "tool_definition":
        validate_tool_definition_body(body)
    elif artifact_type == "tool_binding":
        validate_tool_binding_body(body)


def validate_tool_definition_body(body: dict[str, Any]) -> None:
    _require_exact_keys(body, {"api_version", "kind", "metadata", "spec"}, "tool definition")
    if body.get("api_version") != "agenthub/v1" or body.get("kind") != "ToolDefinition":
        raise ToolArtifactError("unsupported tool definition api_version or kind")
    metadata = _mapping(body.get("metadata"), "metadata")
    _require_exact_keys(metadata, {"id", "owner"}, "metadata")
    _identifier(metadata.get("id"), "tool id")
    _identifier(metadata.get("owner"), "tool owner")

    spec = _mapping(body.get("spec"), "spec")
    _require_exact_keys(
        spec,
        {
            "protocol",
            "destination",
            "input_contract_ref",
            "output_contract_ref",
            "risk",
            "side_effecting",
            "timeout_seconds",
            "max_response_bytes",
            "rate_limit_per_minute",
            "allowed_organizations",
        },
        "tool spec",
        optional={"method", "secret_ref", "redaction"},
    )

    protocol = spec.get("protocol")
    if protocol not in ALLOWED_PROTOCOLS:
        raise ToolArtifactError("tool protocol must be 'http' or 'mcp'")
    _validate_destination(spec.get("destination"))

    method = spec.get("method")
    if protocol == "http":
        if method not in ALLOWED_HTTP_METHODS:
            raise ToolArtifactError("http tool requires an allowed method")
    elif method is not None:
        raise ToolArtifactError("mcp tool must not declare an http method")

    _artifact_ref(spec.get("input_contract_ref"), "input_contract_ref")
    _artifact_ref(spec.get("output_contract_ref"), "output_contract_ref")

    risk = spec.get("risk")
    if risk == "critical":
        raise ToolArtifactError("critical-risk tools are disabled")
    if risk not in ALLOWED_RISKS:
        raise ToolArtifactError("tool risk must be 'low', 'medium', or 'high'")
    _boolean(spec.get("side_effecting"), "side_effecting")

    _bounded_int(spec.get("timeout_seconds"), 1, MAX_TIMEOUT_SECONDS, "timeout_seconds")
    _bounded_int(spec.get("max_response_bytes"), 1, MAX_RESPONSE_BYTES, "max_response_bytes")
    _bounded_int(spec.get("rate_limit_per_minute"), 1, MAX_RATE_LIMIT, "rate_limit_per_minute")

    organizations = spec.get("allowed_organizations")
    if not isinstance(organizations, list) or not organizations:
        raise ToolArtifactError("tool requires a non-empty organization allowlist")
    if any(not isinstance(item, str) or not item for item in organizations):
        raise ToolArtifactError("tool organization allowlist is invalid")

    if "secret_ref" in spec:
        _secret_reference(spec.get("secret_ref"))
    if "redaction" in spec:
        _validate_redaction(spec.get("redaction"))


def validate_tool_binding_body(body: dict[str, Any]) -> None:
    _require_exact_keys(body, {"api_version", "kind", "metadata", "spec"}, "tool binding")
    if body.get("api_version") != "agenthub/v1" or body.get("kind") != "ToolBinding":
        raise ToolArtifactError("unsupported tool binding api_version or kind")
    metadata = _mapping(body.get("metadata"), "metadata")
    _require_exact_keys(metadata, {"id", "owner"}, "metadata")
    _identifier(metadata.get("id"), "tool binding id")
    _identifier(metadata.get("owner"), "tool binding owner")

    spec = _mapping(body.get("spec"), "spec")
    _require_exact_keys(
        spec,
        {"tool_ref", "allowed_input_fields", "allowed_output_fields", "approval"},
        "tool binding spec",
        optional={"rate_limit_per_minute"},
    )
    _artifact_ref(spec.get("tool_ref"), "tool_ref")
    _field_list(spec.get("allowed_input_fields"), "allowed_input_fields")
    _field_list(spec.get("allowed_output_fields"), "allowed_output_fields")

    approval = _mapping(spec.get("approval"), "approval")
    _require_exact_keys(
        approval, {"required", "approver_roles", "self_approval_allowed"}, "approval"
    )
    _boolean(approval.get("required"), "approval.required")
    _boolean(approval.get("self_approval_allowed"), "approval.self_approval_allowed")
    roles = approval.get("approver_roles")
    if not isinstance(roles, list) or not roles or len(roles) > MAX_APPROVER_ROLES:
        raise ToolArtifactError("approver_roles must be a bounded non-empty list")
    if any(role not in ALLOWED_APPROVER_ROLES for role in roles):
        raise ToolArtifactError("approver_roles contains an unknown role")

    if "rate_limit_per_minute" in spec:
        _bounded_int(spec.get("rate_limit_per_minute"), 1, MAX_RATE_LIMIT, "rate_limit_per_minute")


def _validate_destination(value: Any) -> None:
    destination = _mapping(value, "destination")
    _require_exact_keys(
        destination,
        {"scheme", "host"},
        "destination",
        optional={"port", "path_prefix", "session"},
    )
    if destination.get("scheme") not in ALLOWED_SCHEMES:
        raise ToolArtifactError("destination scheme must be https")
    _validate_public_hostname(destination.get("host"))
    if "port" in destination:
        _bounded_int(destination.get("port"), 1, 65535, "destination port")
    if "session" in destination and not isinstance(destination.get("session"), bool):
        raise ToolArtifactError("destination session must be a boolean")
    if "path_prefix" in destination:
        prefix = destination.get("path_prefix")
        if (
            not isinstance(prefix, str)
            or not prefix.startswith("/")
            or len(prefix) > MAX_PATH_PREFIX_LENGTH
            or ".." in prefix
        ):
            raise ToolArtifactError("destination path_prefix is invalid")


def _validate_public_hostname(value: Any) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_HOST_LENGTH:
        raise ToolArtifactError("destination host is invalid")
    lowered = value.lower()
    is_ip = True
    try:
        ipaddress.ip_address(lowered)
    except ValueError:
        is_ip = False
    if is_ip:
        raise ToolArtifactError("destination host must be a domain name, not an IP address")
    if lowered in DISALLOWED_HOSTS:
        raise ToolArtifactError("destination host is disallowed")
    labels = lowered.split(".")
    if len(labels) < 2:
        raise ToolArtifactError("destination host must be a fully qualified domain")
    for label in labels:
        if (
            not label
            or len(label) > MAX_LABEL_LENGTH
            or label.startswith("-")
            or label.endswith("-")
            or not all(character.isalnum() or character == "-" for character in label)
        ):
            raise ToolArtifactError("destination host label is invalid")
    if labels[-1] in DISALLOWED_HOST_SUFFIXES:
        raise ToolArtifactError("destination host uses a disallowed suffix")


def _validate_redaction(value: Any) -> None:
    redaction = _mapping(value, "redaction")
    _require_exact_keys(redaction, {"request_fields", "response_fields"}, "redaction")
    _field_list(redaction.get("request_fields"), "redaction.request_fields")
    _field_list(redaction.get("response_fields"), "redaction.response_fields")


def _field_list(value: Any, name: str) -> None:
    if not isinstance(value, list) or len(value) > MAX_FIELDS:
        raise ToolArtifactError(f"{name} must be a bounded list")
    for item in value:
        if not isinstance(item, str) or not item or len(item) > MAX_FIELD_NAME_LENGTH:
            raise ToolArtifactError(f"{name} contains an invalid field name")


def _secret_reference(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith(SECRET_REFERENCE_PREFIX)
        or len(value) <= len(SECRET_REFERENCE_PREFIX)
        or len(value) > MAX_SECRET_REF_LENGTH
    ):
        raise ToolArtifactError("secret_ref must be a bounded 'secret:<name>' reference")


def _artifact_ref(value: Any, name: str) -> None:
    if not isinstance(value, str) or ":v" not in value:
        raise ToolArtifactError(f"{name} must be a '<logical>:v<N>' reference")
    logical, _, version = value.rpartition(":v")
    _identifier(logical, name)
    if not version.isdigit() or int(version) < 1:
        raise ToolArtifactError(f"{name} version is invalid")


def _identifier(value: Any, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or not all(character.isalnum() or character in "._-" for character in value)
    ):
        raise ToolArtifactError(f"{name} is invalid")


def _boolean(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise ToolArtifactError(f"{name} must be a boolean")


def _bounded_int(value: Any, low: int, high: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ToolArtifactError(f"{name} must be an integer in [{low}, {high}]")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ToolArtifactError(f"{name} must be an object")
    return value


def _require_exact_keys(
    value: dict[str, Any], required: set[str], name: str, *, optional: set[str] | None = None
) -> None:
    optional = optional or set()
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise ToolArtifactError(f"{name} is missing required fields")
    if unknown:
        raise ToolArtifactError(f"{name} contains unknown fields")
