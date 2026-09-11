"""Closed, bounded executable snapshot contract; no mutable catalog lookup here."""

import json
from typing import Any

from apps.artifacts.secrets import assert_no_inline_secrets
from apps.artifacts.validation import compute_checksum, validate_body

REVISION_CONTRACT = "scenario-revision/v1"
MAX_REVISION_BYTES = 4 * 1024 * 1024
MAX_REVISION_ROLES = 50
MAX_REVISION_DATA_PINS = 1000


class RevisionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RevisionError("REVISION_CONTRACT_INVALID")
    return value


def _positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _pins(value: Any) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_REVISION_DATA_PINS
        or any(not _positive(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise RevisionError("REVISION_DATA_PINS_INVALID")
    return value


def validate_revision_snapshot(snapshot: Any) -> None:
    """Verify integrity and provenance, never return artifact content in an error."""
    try:
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise RevisionError("REVISION_CONTRACT_INVALID") from None
    if len(encoded) > MAX_REVISION_BYTES:
        raise RevisionError("REVISION_TOO_LARGE")
    body = _object(
        snapshot,
        {"contract", "scope", "runtime_version", "manifest", "artifacts", "workflow", "data"},
    )
    if body["contract"] != REVISION_CONTRACT:
        raise RevisionError("REVISION_CONTRACT_UNSUPPORTED")
    scope = _object(body["scope"], {"organization_id", "scenario_id", "source_release_id"})
    if not all(_positive(value) for value in scope.values()):
        raise RevisionError("REVISION_SCOPE_INVALID")
    manifest = body["manifest"]
    if (
        not isinstance(manifest, dict)
        or not _positive(manifest.get("scenario_id"))
        or manifest.get("scenario_id") != scope["scenario_id"]
    ):
        raise RevisionError("REVISION_SCOPE_INVALID")
    if (
        not isinstance(body["runtime_version"], str)
        or not 1 <= len(body["runtime_version"]) <= 64
        or manifest.get("runtime_version") != body["runtime_version"]
    ):
        raise RevisionError("REVISION_RUNTIME_INVALID")
    artifacts, pins = body["artifacts"], manifest.get("artifacts")
    if (
        not isinstance(artifacts, dict)
        or not 1 <= len(artifacts) <= MAX_REVISION_ROLES
        or not isinstance(pins, dict)
        or set(pins) != set(artifacts)
    ):
        raise RevisionError("REVISION_ARTIFACTS_INVALID")
    for role, raw in artifacts.items():
        if not isinstance(role, str) or not 1 <= len(role) <= 200:
            raise RevisionError("REVISION_ARTIFACTS_INVALID")
        artifact = _object(raw, {"id", "type", "ref", "checksum", "body"})
        pin = pins[role]
        if (
            not _positive(artifact["id"])
            or not isinstance(artifact["type"], str)
            or not isinstance(artifact["ref"], str)
            or not 1 <= len(artifact["ref"]) <= 1000
            or not isinstance(pin, dict)
            or any(artifact[key] != pin.get(key) for key in ("type", "ref", "checksum"))
            or compute_checksum(artifact["body"]) != artifact["checksum"]
        ):
            raise RevisionError("REVISION_ARTIFACT_INTEGRITY")
        try:
            validate_body(artifact["type"], artifact["body"])
        except (ValueError, TypeError, RecursionError):
            raise RevisionError("REVISION_ARTIFACT_INVALID") from None
    workflow = _object(body["workflow"], {"id", "checksum", "compiler_version", "graph"})
    if (
        not _positive(workflow["id"])
        or not isinstance(workflow["graph"], dict)
        or not isinstance(workflow["compiler_version"], str)
        or not 1 <= len(workflow["compiler_version"]) <= 32
        or compute_checksum(workflow["graph"]) != workflow["checksum"]
        or manifest.get("workflow_checksum") != workflow["checksum"]
        or artifacts.get("workflow_definition", {}).get("type") != "workflow_definition"
    ):
        raise RevisionError("REVISION_WORKFLOW_INTEGRITY")
    data = _object(
        body["data"],
        {"selection", "document_set_ids", "document_set_version_ids", "index_version_ids"},
    )
    if not isinstance(data["selection"], str) or data["selection"] not in {
        "legacy_pinned",
        "active_generation",
    }:
        raise RevisionError("REVISION_DATA_MODE_UNSUPPORTED")
    if (
        data["selection"] != manifest.get("data_selection", "legacy_pinned")
        or _pins(data["document_set_ids"]) != _pins(manifest.get("document_set_ids", []))
        or len(data["document_set_ids"]) > 200
        or (data["selection"] == "legacy_pinned" and data["document_set_ids"])
        or (
            data["selection"] == "active_generation"
            and (data["document_set_version_ids"] or data["index_version_ids"])
        )
    ):
        raise RevisionError("REVISION_DATA_PINS_INVALID")
    for key, manifest_key in (
        ("document_set_version_ids", "document_set_versions"),
        ("index_version_ids", "index_versions"),
    ):
        if _pins(data[key]) != _pins(manifest.get(manifest_key, [])):
            raise RevisionError("REVISION_DATA_PINS_INVALID")
    try:
        assert_no_inline_secrets(body)
    except (ValueError, RecursionError):
        raise RevisionError("REVISION_INLINE_SECRET") from None
