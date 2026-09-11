from __future__ import annotations

from typing import Any

import pytest

from apps.artifacts.governed_dsl import (
    GovernedDocument,
    GovernedDSLValidationError,
    chunk_with_profile,
    execute_transform,
    normalize_retrieval_profile,
    validate_transform_profile,
)
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.retrieval.providers import StaticRetrievalProvider
from apps.retrieval.types import RetrievedChunk
from apps.tenancy.models import Organization

VALID_TRANSFORM = {
    "api_version": "agenthub/transform/v1",
    "kind": "DocumentTransform",
    "spec": {
        "limits": {"max_records": 100, "max_output_bytes": 100_000},
        "steps": [
            {"op": "records.select", "pointer": "/items"},
            {"op": "records.filter", "where": {"field": "/status", "eq": "active"}},
            {"op": "fields.rename", "from": "/description", "to": "/content"},
            {"op": "text.normalize", "pointer": "/content", "unicode": True},
            {
                "op": "documents.map",
                "id": "/id",
                "title": "/name",
                "content": "/content",
            },
        ],
    },
}


@pytest.mark.django_db
def test_governed_profiles_publish_as_validated_immutable_artifacts() -> None:
    organization = Organization.objects.create(slug="dsl", name="DSL")
    profiles: list[tuple[str, dict]] = [
        (ArtifactType.TRANSFORM_PROFILE, VALID_TRANSFORM),
        (
            ArtifactType.CHUNKING_PROFILE,
            {
                "api_version": "agenthub/chunking/v1",
                "kind": "ChunkingProfile",
                "strategy": "characters",
                "size": 800,
                "overlap": 100,
                "max_chunks": 500,
            },
        ),
        (
            ArtifactType.RETRIEVAL_PROFILE,
            {
                "api_version": "agenthub/retrieval/v1",
                "kind": "RetrievalProfile",
                "mode": "hybrid",
                "top_k": 10,
                "score_threshold": 0.25,
                "vector_weight": 0.7,
                "keyword_weight": 0.3,
                "metadata_filter": {"field": "/language", "eq": "tr"},
                "summary_document_top_k": 10,
                "max_chunks_per_document": 3,
            },
        ),
    ]
    for artifact_type, body in profiles:
        artifact = create_artifact_version(
            organization=organization,
            artifact_type=artifact_type,
            logical_id=f"valid_{artifact_type}",
            body=body,
            created_by="author",
        )
        assert artifact.version == 1


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda body: body.update({"python": "import os"}), "transform_unknown_field"),
        (
            lambda body: body["spec"]["steps"].append({"op": "code.eval", "code": "1+1"}),
            "transform_operation_unknown",
        ),
        (
            lambda body: body["spec"]["steps"].append(
                {"op": "fields.drop", "pointer": "/__proto__/admin"}
            ),
            "dsl_pointer_forbidden",
        ),
        (
            lambda body: body["spec"].update(
                {
                    "steps": [
                        {
                            "op": "records.filter",
                            "where": {
                                "and": [
                                    {
                                        "and": [
                                            {
                                                "and": [
                                                    {
                                                        "and": [
                                                            {
                                                                "and": [
                                                                    {
                                                                        "and": [
                                                                            {"field": "/x", "eq": 1}
                                                                        ]
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                        }
                    ]
                }
            ),
            "dsl_filter_too_complex",
        ),
    ],
)
def test_transform_rejects_unknown_code_pointer_and_excessive_depth(mutation, code: str) -> None:
    import copy

    body: dict[str, Any] = copy.deepcopy(VALID_TRANSFORM)
    mutation(body)
    with pytest.raises(GovernedDSLValidationError, match=code):
        validate_transform_profile(body)


@pytest.mark.parametrize(
    "body",
    [
        {
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "hybrid",
            "top_k": 10,
            "vector_weight": 0.8,
            "keyword_weight": 0.8,
        },
        {
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "vector",
            "top_k": 51,
            "organization_id": 99,
        },
        {
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "vector",
            "top_k": 5,
            "max_chunks_per_document": 2,
        },
    ],
)
def test_retrieval_profile_rejects_invalid_weights_bounds_and_authority_fields(body) -> None:
    from apps.artifacts.governed_dsl import validate_retrieval_profile

    with pytest.raises(GovernedDSLValidationError):
        validate_retrieval_profile(body)


def test_transform_executor_is_deterministic_preserves_identity_and_input() -> None:
    import copy

    source = {
        "items": [
            {"id": "2", "name": "Pasif", "description": "ignore", "status": "inactive"},
            {
                "id": "1",
                "name": "İade",
                "description": "  I\u0307ade   koşulları  ",
                "status": "active",
            },
        ]
    }
    original = copy.deepcopy(source)

    first = execute_transform(VALID_TRANSFORM, source)
    second = execute_transform(VALID_TRANSFORM, source)

    assert source == original
    assert (
        first
        == second
        == [GovernedDocument(source_id="1", title="İade", content="İade koşulları", metadata={})]
    )


def test_transform_executor_fails_closed_on_record_budget() -> None:
    import copy

    body: dict[str, Any] = copy.deepcopy(VALID_TRANSFORM)
    body["spec"]["limits"] = {"max_records": 1, "max_output_bytes": 100_000}
    with pytest.raises(GovernedDSLValidationError, match="dsl_record_limit_exceeded"):
        execute_transform(
            body,
            {
                "items": [
                    {"id": "1", "name": "a", "description": "a", "status": "active"},
                    {"id": "2", "name": "b", "description": "b", "status": "active"},
                ]
            },
        )


def test_chunking_and_retrieval_runtime_use_validated_contracts() -> None:
    chunks = chunk_with_profile(
        "abcdefghij",
        {
            "api_version": "agenthub/chunking/v1",
            "kind": "ChunkingProfile",
            "strategy": "characters",
            "size": 100,
            "overlap": 1,
            "max_chunks": 10,
        },
    )
    assert chunks == ["abcdefghij"]

    normalized = normalize_retrieval_profile(
        {
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "vector",
            "top_k": 5,
            "score_threshold": 0.4,
            "summary_document_top_k": 10,
            "max_chunks_per_document": 2,
        }
    )
    assert normalized == {
        "mode": "vector",
        "top_k": 5,
        "score_threshold": 0.4,
        "summary_document_top_k": 10,
        "max_chunks_per_document": 2,
    }

    provider = StaticRetrievalProvider(
        [
            RetrievedChunk("low", "1", "uri:1", score=0.3),
            RetrievedChunk("high", "2", "uri:2", score=0.8),
        ]
    )
    assert [
        chunk.text
        for chunk in provider.retrieve(
            query="q", profile=normalized, organization_id=1, index_versions=[]
        )
    ] == ["high"]


@pytest.mark.parametrize(
    ("strategy", "source"),
    [
        ("characters", "x" * 205),
        ("tokens", " ".join(f"token-{index}" for index in range(205))),
        ("headings", "\n".join(f"# Heading {index}" for index in range(205))),
        ("pages", "\f".join(f"Page {index}" for index in range(205))),
        ("tables", "\n\n".join(f"row-{index}|value-{index}" for index in range(205))),
    ],
)
def test_all_chunking_strategies_apply_bounds_and_overlap(strategy: str, source: str) -> None:
    chunks = chunk_with_profile(
        source,
        {
            "api_version": "agenthub/chunking/v1",
            "kind": "ChunkingProfile",
            "strategy": strategy,
            "size": 100,
            "overlap": 10,
            "max_chunks": 10,
        },
    )
    assert len(chunks) == 3
    assert all(chunks)


def test_chunking_fails_closed_when_profile_maximum_is_exceeded() -> None:
    with pytest.raises(GovernedDSLValidationError, match="chunking_max_exceeded"):
        chunk_with_profile(
            " ".join(f"token-{index}" for index in range(205)),
            {
                "api_version": "agenthub/chunking/v1",
                "kind": "ChunkingProfile",
                "strategy": "tokens",
                "size": 100,
                "overlap": 0,
                "max_chunks": 1,
            },
        )
