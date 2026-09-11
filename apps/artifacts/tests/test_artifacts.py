"""Artifact validation, immutability, checksum, and secret-safety."""

from __future__ import annotations

import pytest

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import ArtifactValidationError, compute_checksum
from apps.tenancy.models import Organization

VALID_INPUT_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {"query": {"type": "string", "maxLength": 8000}},
    "additionalProperties": False,
}


@pytest.fixture
def org(db) -> Organization:
    return Organization.objects.create(slug="mcm", name="MCM")


@pytest.mark.django_db
def test_create_assigns_version_and_checksum(org: Organization) -> None:
    a1 = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="customer_query",
        body=VALID_INPUT_SCHEMA,
        created_by="alice",
    )
    assert a1.version == 1
    assert a1.checksum == compute_checksum(VALID_INPUT_SCHEMA)
    assert a1.ref == "customer_query:v1"

    a2 = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="customer_query",
        body=VALID_INPUT_SCHEMA,
        created_by="alice",
    )
    assert a2.version == 2  # auto-incremented


@pytest.mark.django_db
def test_logical_description_is_stable_while_exact_version_description_changes(
    org: Organization,
) -> None:
    first = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        logical_id="support_prompt",
        logical_description="Stable support answer purpose",
        version_description="Initial reviewed wording",
        body={"template": "Hello"},
        created_by="author",
    )
    second = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        logical_id="support_prompt",
        version_description="Adds Turkish wording",
        body={"template": "Merhaba"},
        created_by="author",
    )
    assert second.logical_description == first.logical_description
    assert second.version_description == "Adds Turkish wording"

    with pytest.raises(ValueError, match="must remain stable"):
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.PROMPT_TEMPLATE,
            logical_id="support_prompt",
            logical_description="Different purpose",
            version_description="Invalid metadata change",
            body={"template": "Nope"},
            created_by="author",
        )


@pytest.mark.django_db
def test_artifact_is_immutable(org: Organization) -> None:
    artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.POLICY_PROFILE,
        logical_id="grounded",
        body={"grounding": {"required": True}},
        created_by="alice",
    )
    artifact.body = {"grounding": {"required": False}}
    with pytest.raises(ValueError, match="immutable"):
        artifact.save()
    with pytest.raises(ValueError):
        artifact.delete()


@pytest.mark.django_db
def test_invalid_json_schema_contract_rejected(org: Organization) -> None:
    with pytest.raises(ArtifactValidationError, match="JSON Schema"):
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.OUTPUT_CONTRACT,
            logical_id="bad",
            body={"type": "not-a-real-type"},
            created_by="alice",
        )


@pytest.mark.django_db
def test_inline_secret_rejected(org: Organization) -> None:
    with pytest.raises(ArtifactValidationError, match="inline secret"):
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.MODEL_PROFILE,
            logical_id="default_chat",
            body={"endpoint": "https://llm.example", "api_key": "sk-live-123"},
            created_by="alice",
        )


@pytest.mark.django_db
def test_prompt_template_requires_nonempty_bounded_template(org: Organization) -> None:
    for body in ({}, {"template": " "}, {"template": 42}):
        with pytest.raises(ArtifactValidationError, match="non-empty template"):
            create_artifact_version(
                organization=org,
                artifact_type=ArtifactType.PROMPT_TEMPLATE,
                logical_id="bad_prompt",
                body=body,
                created_by="alice",
            )


@pytest.mark.django_db
def test_model_profile_reference_allowed(org: Organization) -> None:
    artifact = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.MODEL_PROFILE,
        logical_id="default_chat",
        body={"profile_id": "00000000-0000-0000-0000-000000000001"},
        created_by="alice",
    )
    assert ArtifactVersion.objects.filter(pk=artifact.pk).exists()


@pytest.mark.django_db
def test_model_profile_rejects_inline_endpoint_even_with_secret_ref(org: Organization) -> None:
    with pytest.raises(ArtifactValidationError, match="only profile_id"):
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.MODEL_PROFILE,
            logical_id="unsafe",
            body={
                "profile_id": "00000000-0000-0000-0000-000000000001",
                "endpoint": "https://llm.example",
            },
            created_by="alice",
        )
