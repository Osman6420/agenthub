"""Validation for platform ``EmbeddingProfile`` fields and profile-id references.

Mirrors ``apps.orchestration.profile_schema`` (the P1 ``ModelProfile`` validator) and adds the
embedding-specific dimension/index-type rule from ADR-0003: an unsupported declared store dimension
is **rejected — never silently truncated** (`vector` ≤ 2000, `halfvec` ≤ 4000). ADR-0017 separately
allows bounded provider-response truncation for an explicit `halfvec(4000)` profile.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from apps.ingestion.models import (
    HALFVEC_MAX_DIMENSIONS,
    VECTOR_MAX_DIMENSIONS,
    EmbeddingIndexType,
)
from apps.tools.tool_schema import ToolArtifactError, _validate_public_hostname

_LOGICAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SECRET_REF = re.compile(r"^secret:[A-Za-z0-9._-]{1,128}$")
_ALLOWED_ARTIFACT_FIELDS = frozenset({"profile_id"})


class EmbeddingProfileValidationError(ValueError):
    pass


def validate_embedding_profile_artifact(body: dict[str, Any]) -> None:
    """An ``embedding_profile`` artifact reference carries only a catalog UUID (ADR-0002)."""
    if set(body) != _ALLOWED_ARTIFACT_FIELDS:
        raise EmbeddingProfileValidationError("embedding_profile must contain only profile_id")
    try:
        uuid.UUID(str(body["profile_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise EmbeddingProfileValidationError(
            "embedding_profile.profile_id must be a UUID"
        ) from exc


def validate_embedding_profile_fields(
    *,
    logical_id: str,
    revision: int,
    provider: str,
    scheme: str,
    host: str,
    port: int,
    path: str,
    model: str,
    secret_ref: str,
    dimensions: int,
    index_type: str,
    normalize: bool,
    distance_metric: str,
    timeout_seconds: int,
    max_response_bytes: int,
    max_batch_size: int,
) -> None:
    if not _LOGICAL_ID.fullmatch(logical_id):
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_LOGICAL_ID_INVALID")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or not 1 <= revision <= 1_000_000
    ):
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_REVISION_INVALID")
    if provider != "openai_compatible" or scheme != "https":
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_PROVIDER_INVALID")
    try:
        _validate_public_hostname(host)
    except ToolArtifactError as exc:
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_HOST_INVALID") from exc
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_PORT_INVALID")
    if not path.startswith("/") or len(path) > 512 or "?" in path or "#" in path:
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_PATH_INVALID")
    if not model or len(model) > 200 or any(c in model for c in "\r\n"):
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_MODEL_INVALID")
    if not _SECRET_REF.fullmatch(secret_ref):
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_SECRET_REF_INVALID")
    if index_type not in EmbeddingIndexType.values:
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_INDEX_TYPE_INVALID")
    if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions < 1:
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_DIMENSIONS_INVALID")
    # Never truncate declared store geometry: reject a dimension HNSW cannot cover.
    limit = (
        HALFVEC_MAX_DIMENSIONS
        if index_type == EmbeddingIndexType.HALFVEC
        else VECTOR_MAX_DIMENSIONS
    )
    if dimensions > limit:
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_DIMENSIONS_UNSUPPORTED")
    if not isinstance(normalize, bool):
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_NORMALIZE_INVALID")
    if distance_metric != "cosine":
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_METRIC_INVALID")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= 120
    ):
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_TIMEOUT_INVALID")
    if (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or not 1_024 <= max_response_bytes <= 50_000_000
    ):
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_RESPONSE_LIMIT_INVALID")
    if (
        isinstance(max_batch_size, bool)
        or not isinstance(max_batch_size, int)
        or not 1 <= max_batch_size <= 2048
    ):
        raise EmbeddingProfileValidationError("EMBEDDING_PROFILE_BATCH_LIMIT_INVALID")
