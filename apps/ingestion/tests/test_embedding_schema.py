"""EmbeddingProfile field validation, incl. the no-silent-truncation dimension rule."""

from __future__ import annotations

import uuid

import pytest

from apps.ingestion.embedding_schema import (
    EmbeddingProfileValidationError,
    validate_embedding_profile_artifact,
    validate_embedding_profile_fields,
)


def _fields(**overrides: object) -> dict:
    base = {
        "logical_id": "default-embed",
        "revision": 1,
        "provider": "openai_compatible",
        "scheme": "https",
        "host": "embeddings.example.com",
        "port": 443,
        "path": "/v1/embeddings",
        "model": "text-embed-3",
        "secret_ref": "secret:embed-token",
        "dimensions": 1536,
        "index_type": "vector",
        "normalize": True,
        "distance_metric": "cosine",
        "timeout_seconds": 30,
        "max_response_bytes": 5_000_000,
        "max_batch_size": 64,
    }
    base.update(overrides)
    return base


def test_valid_fields_pass() -> None:
    validate_embedding_profile_fields(**_fields())


def test_vector_dimension_over_limit_is_rejected() -> None:
    with pytest.raises(EmbeddingProfileValidationError, match="DIMENSIONS_UNSUPPORTED"):
        validate_embedding_profile_fields(**_fields(index_type="vector", dimensions=2001))


def test_halfvec_allows_up_to_4000_and_rejects_above() -> None:
    validate_embedding_profile_fields(**_fields(index_type="halfvec", dimensions=4000))
    with pytest.raises(EmbeddingProfileValidationError, match="DIMENSIONS_UNSUPPORTED"):
        validate_embedding_profile_fields(**_fields(index_type="halfvec", dimensions=4001))


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"scheme": "http"}, "PROVIDER_INVALID"),
        ({"host": "localhost"}, "HOST_INVALID"),
        ({"host": "10.0.0.5"}, "HOST_INVALID"),
        ({"secret_ref": "inline-token"}, "SECRET_REF_INVALID"),
        ({"path": "/v1/embeddings?x=1"}, "PATH_INVALID"),
        ({"dimensions": 0}, "DIMENSIONS_INVALID"),
        ({"index_type": "sparse"}, "INDEX_TYPE_INVALID"),
        ({"distance_metric": "euclidean"}, "METRIC_INVALID"),
        ({"max_batch_size": 0}, "BATCH_LIMIT_INVALID"),
    ],
)
def test_field_rejections(overrides: dict, match: str) -> None:
    with pytest.raises(EmbeddingProfileValidationError, match=match):
        validate_embedding_profile_fields(**_fields(**overrides))


def test_artifact_reference_is_profile_id_only() -> None:
    validate_embedding_profile_artifact({"profile_id": str(uuid.uuid4())})
    with pytest.raises(EmbeddingProfileValidationError):
        validate_embedding_profile_artifact({"profile_id": str(uuid.uuid4()), "host": "x"})
    with pytest.raises(EmbeddingProfileValidationError):
        validate_embedding_profile_artifact({"profile_id": "not-a-uuid"})
