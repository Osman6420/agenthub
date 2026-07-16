"""Canonical serialization, checksums, and per-type artifact validation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from apps.artifacts.eval_suite import validate_eval_suite_body
from apps.artifacts.secrets import assert_no_inline_secrets
from apps.artifacts.types import JSON_SCHEMA_TYPES, ArtifactType


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

    if artifact_type == ArtifactType.EVAL_SUITE:
        try:
            validate_eval_suite_body(body)
        except ValueError as exc:
            raise ArtifactValidationError(str(exc)) from exc

    if artifact_type in {
        ArtifactType.TRANSFORM_PROFILE,
        ArtifactType.CHUNKING_PROFILE,
        ArtifactType.RETRIEVAL_PROFILE,
    }:
        from apps.artifacts.governed_dsl import (
            GovernedDSLValidationError,
            validate_chunking_profile,
            validate_retrieval_profile,
            validate_transform_profile,
        )

        try:
            if artifact_type == ArtifactType.TRANSFORM_PROFILE:
                validate_transform_profile(body)
            elif artifact_type == ArtifactType.CHUNKING_PROFILE:
                validate_chunking_profile(body)
            else:
                validate_retrieval_profile(body)
        except GovernedDSLValidationError as exc:
            raise ArtifactValidationError(str(exc)) from exc

    if artifact_type == ArtifactType.MODEL_PROFILE:
        from apps.orchestration.profile_schema import (
            ModelProfileValidationError,
            validate_model_profile_artifact,
        )

        try:
            validate_model_profile_artifact(body)
        except ModelProfileValidationError as exc:
            raise ArtifactValidationError(str(exc)) from exc

    if artifact_type in {
        ArtifactType.WORKFLOW_DEFINITION,
        ArtifactType.CUSTOM_NODE_DEFINITION,
    }:
        from apps.workflows.compiler import WorkflowCompileError, validate_artifact_body

        try:
            validate_artifact_body(artifact_type, body)
        except WorkflowCompileError as exc:
            raise ArtifactValidationError(str(exc)) from exc

    if artifact_type in {ArtifactType.TOOL_DEFINITION, ArtifactType.TOOL_BINDING}:
        from apps.tools.tool_schema import ToolArtifactError, validate_tool_artifact_body

        try:
            validate_tool_artifact_body(artifact_type, body)
        except ToolArtifactError as exc:
            raise ArtifactValidationError(str(exc)) from exc

    if artifact_type == ArtifactType.AGENT_DEFINITION:
        from apps.agents.compiler import AgentCompileError, validate_artifact_body

        try:
            validate_artifact_body(artifact_type, body)
        except AgentCompileError as exc:
            raise ArtifactValidationError(str(exc)) from exc
