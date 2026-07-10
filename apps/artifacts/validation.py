"""Canonical serialization, checksums, and per-type artifact validation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from apps.artifacts.secrets import assert_no_inline_secrets
from apps.artifacts.types import JSON_SCHEMA_TYPES


class ArtifactValidationError(ValueError):
    """Raised when an artifact body fails validation for its type."""


def canonical_json(body: Any) -> str:
    """Deterministic JSON used for checksums (sorted keys, compact separators)."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_checksum(body: Any) -> str:
    """SHA-256 over the canonical JSON of the body."""
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def validate_body(artifact_type: str, body: Any) -> None:
    """Validate an artifact body for its type. Raises ``ArtifactValidationError``.

    - Every body must be a JSON object and free of inline secrets.
    - Contract types (input/output) must themselves be valid JSON Schema documents.
    """
    if not isinstance(body, dict):
        raise ArtifactValidationError("artifact body must be a JSON object")

    try:
        assert_no_inline_secrets(body)
    except ValueError as exc:
        raise ArtifactValidationError(str(exc)) from exc

    if artifact_type in JSON_SCHEMA_TYPES:
        try:
            Draft202012Validator.check_schema(body)
        except SchemaError as exc:
            raise ArtifactValidationError(f"invalid JSON Schema: {exc.message}") from exc
