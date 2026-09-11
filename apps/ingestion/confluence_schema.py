"""Closed schemas for platform Confluence profiles and tenant source configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from apps.tools.egress import EgressDenied, validate_private_hostname

_LOGICAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_POLICY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SECRET_REF = re.compile(r"^secret:[A-Za-z0-9._-]{1,128}$")
_PAGE_ID = re.compile(r"^[1-9][0-9]{0,63}$")
_SOURCE_FIELDS = frozenset({"root_page_ids", "include_root", "excluded_page_ids"})


class ConfluenceValidationError(ValueError):
    """A stable, content-free Confluence validation failure."""


@dataclass(frozen=True)
class CanonicalConfluenceBaseUrl:
    scheme: str
    host: str
    port: int
    context_path: str


def canonicalize_confluence_base_url(value: Any) -> CanonicalConfluenceBaseUrl:
    if not isinstance(value, str) or not value or len(value) > 800:
        raise ConfluenceValidationError("CONFLUENCE_BASE_URL_INVALID")
    try:
        parsed = urlsplit(value)
        port = parsed.port or 443
    except ValueError as exc:
        raise ConfluenceValidationError("CONFLUENCE_BASE_URL_INVALID") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not 1 <= port <= 65535
    ):
        raise ConfluenceValidationError("CONFLUENCE_BASE_URL_INVALID")
    host = parsed.hostname.lower()
    try:
        validate_private_hostname(host)
    except EgressDenied as exc:
        raise ConfluenceValidationError("CONFLUENCE_HOST_INVALID") from exc
    path = parsed.path.rstrip("/")
    if path == "/":
        path = ""
    segments = path.split("/")
    if (
        len(path) > 512
        or "\\" in path
        or "%" in path
        or "//" in path
        or any(segment in {".", ".."} for segment in segments)
        or any(ord(character) < 32 for character in path)
        or (path and not path.startswith("/"))
    ):
        raise ConfluenceValidationError("CONFLUENCE_CONTEXT_PATH_INVALID")
    return CanonicalConfluenceBaseUrl(scheme="https", host=host, port=port, context_path=path)


def validate_confluence_profile_fields(**fields: Any) -> None:
    logical_id = fields.get("logical_id")
    if not isinstance(logical_id, str) or not _LOGICAL_ID.fullmatch(logical_id):
        raise ConfluenceValidationError("CONFLUENCE_PROFILE_LOGICAL_ID_INVALID")
    _bounded_int(fields, "revision", 1, 1_000_000)
    if fields.get("provider") != "confluence_dc" or fields.get("scheme") != "https":
        raise ConfluenceValidationError("CONFLUENCE_PROFILE_PROVIDER_INVALID")
    try:
        validate_private_hostname(fields.get("host"))
    except EgressDenied as exc:
        raise ConfluenceValidationError("CONFLUENCE_PROFILE_HOST_INVALID") from exc
    _bounded_int(fields, "port", 1, 65_535)
    context_path = fields.get("context_path")
    if not isinstance(context_path, str):
        raise ConfluenceValidationError("CONFLUENCE_PROFILE_PATH_INVALID")
    canonical = canonicalize_confluence_base_url(
        f"https://{fields['host']}:{fields['port']}{context_path}"
    )
    if canonical.context_path != context_path:
        raise ConfluenceValidationError("CONFLUENCE_PROFILE_PATH_INVALID")
    secret_ref = fields.get("secret_ref")
    if not isinstance(secret_ref, str) or not _SECRET_REF.fullmatch(secret_ref):
        raise ConfluenceValidationError("CONFLUENCE_PROFILE_SECRET_REF_INVALID")
    policy_id = fields.get("network_policy_id")
    if not isinstance(policy_id, str) or not _POLICY_ID.fullmatch(policy_id):
        raise ConfluenceValidationError("CONFLUENCE_NETWORK_POLICY_ID_INVALID")
    _bounded_int(fields, "timeout_seconds", 1, 120)
    _bounded_int(fields, "page_size", 1, 100)
    _bounded_int(fields, "max_pages", 1, 10_000)
    _bounded_int(fields, "max_depth", 0, 100)
    _bounded_int(fields, "max_requests", 1, 50_000)
    _bounded_int(fields, "max_retries", 0, 3)
    _bounded_int(fields, "max_response_bytes", 1_024, 10_000_000)
    _bounded_int(fields, "max_page_body_bytes", 1_024, 10_000_000)
    _bounded_int(fields, "max_total_bytes", 1_024, 250_000_000)
    if fields["max_page_body_bytes"] > fields["max_response_bytes"]:
        raise ConfluenceValidationError("CONFLUENCE_PROFILE_BODY_LIMIT_INVALID")
    if fields["max_response_bytes"] > fields["max_total_bytes"]:
        raise ConfluenceValidationError("CONFLUENCE_PROFILE_TOTAL_LIMIT_INVALID")


def normalize_confluence_source_config(value: Any) -> dict[str, Any]:
    validate_confluence_source_config(value)
    assert isinstance(value, dict)  # noqa: S101 - narrowed by validation
    return {
        "root_page_ids": list(value["root_page_ids"]),
        "include_root": value.get("include_root", True),
        "excluded_page_ids": list(value.get("excluded_page_ids", [])),
    }


def validate_confluence_source_config(value: Any) -> None:
    if not isinstance(value, dict) or set(value) - _SOURCE_FIELDS:
        raise ConfluenceValidationError("CONFLUENCE_SOURCE_CONFIG_INVALID")
    roots = value.get("root_page_ids")
    excluded = value.get("excluded_page_ids", [])
    if not isinstance(roots, list) or not 1 <= len(roots) <= 50:
        raise ConfluenceValidationError("CONFLUENCE_ROOT_PAGE_IDS_INVALID")
    if not isinstance(excluded, list) or len(excluded) > 500:
        raise ConfluenceValidationError("CONFLUENCE_EXCLUDED_PAGE_IDS_INVALID")
    if any(not isinstance(item, str) or not _PAGE_ID.fullmatch(item) for item in roots):
        raise ConfluenceValidationError("CONFLUENCE_ROOT_PAGE_IDS_INVALID")
    if any(not isinstance(item, str) or not _PAGE_ID.fullmatch(item) for item in excluded):
        raise ConfluenceValidationError("CONFLUENCE_EXCLUDED_PAGE_IDS_INVALID")
    if len(set(roots)) != len(roots) or len(set(excluded)) != len(excluded):
        raise ConfluenceValidationError("CONFLUENCE_PAGE_IDS_DUPLICATE")
    include_root = value.get("include_root", True)
    if not isinstance(include_root, bool):
        raise ConfluenceValidationError("CONFLUENCE_INCLUDE_ROOT_INVALID")


def _bounded_int(fields: dict[str, Any], name: str, minimum: int, maximum: int) -> None:
    value = fields.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfluenceValidationError(f"CONFLUENCE_PROFILE_{name.upper()}_INVALID")
