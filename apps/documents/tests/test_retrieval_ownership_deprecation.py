"""Document sets no longer own query-time retrieval, but keep their historical provenance."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.documents import services as document_services
from apps.documents.profile_authoring import (
    AUTHORABLE_TYPES,
    DocumentProfileAuthoringError,
    publish_document_profile_artifact,
)
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
)
from apps.ingestion.models import (
    DocumentSetPreparationProfile,
    EmbeddingProfile,
    TenantEmbeddingProfileGrant,
)
from apps.ingestion.preparation import configure_preparation
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db

_RETRIEVAL_BODY = {
    "api_version": "agenthub/retrieval/v1",
    "kind": "RetrievalProfile",
    "mode": "hybrid",
    "top_k": 8,
    "score_threshold": 0,
    "vector_weight": 0.7,
    "keyword_weight": 0.3,
}
_CHUNKING_BODY = {
    "api_version": "agenthub/chunking/v1",
    "kind": "ChunkingProfile",
    "strategy": "tokens",
    "size": 800,
    "overlap": 80,
    "max_chunks": 500,
}


@pytest.fixture
def workspace() -> dict:
    org = Organization.objects.create(slug="retire-org", name="Retire")
    document_set = document_services.create_document_set(
        organization=org, logical_id="handbook", name="Handbook", actor="manager"
    )
    manager = User.objects.create_user("retire-manager", password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=manager)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        document_set=document_set,
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=manager,
    )
    embedding = EmbeddingProfile.objects.create(
        logical_id="embed",
        revision=1,
        host="embedding.example.com",
        model="embed-v1",
        secret_ref="secret://embedding",  # noqa: S106 -- opaque reference
        dimensions=64,
        created_by="platform",
    )
    TenantEmbeddingProfileGrant.objects.create(
        organization=org, embedding_profile=embedding, created_by="platform"
    )
    chunking = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.CHUNKING_PROFILE,
        logical_id="handbook.chunking",
        logical_description="Chunking",
        version_description="v1",
        body=_CHUNKING_BODY,
        created_by="manager",
    )
    return {
        "org": org,
        "set": document_set,
        "manager": manager,
        "embedding": embedding,
        "chunking": chunking,
    }


def test_retrieval_is_no_longer_authorable_from_the_document_set(workspace: dict) -> None:
    assert ArtifactType.RETRIEVAL_PROFILE not in AUTHORABLE_TYPES

    with pytest.raises(DocumentProfileAuthoringError) as exc:
        publish_document_profile_artifact(
            user=workspace["manager"],
            document_set=workspace["set"],
            artifact_type=ArtifactType.RETRIEVAL_PROFILE,
            logical_id="handbook.retrieval",
            logical_description="Should not be authored here",
            version_description="v1",
            body=_RETRIEVAL_BODY,
        )
    assert exc.value.code == "artifact_type_unsupported"
    assert not ArtifactVersion.objects.filter(type=ArtifactType.RETRIEVAL_PROFILE).exists()


def test_preparation_no_longer_requires_a_retrieval_profile(workspace: dict) -> None:
    policy = configure_preparation(
        document_set=workspace["set"],
        embedding_profile=workspace["embedding"],
        chunking_profile=workspace["chunking"],
        retrieval_profile=None,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=False,
        actor="manager",
    )

    assert policy.retrieval_profile_id is None
    policy.full_clean()


def test_an_existing_retrieval_pin_survives_as_historical_provenance(workspace: dict) -> None:
    legacy = create_artifact_version(
        organization=workspace["org"],
        artifact_type=ArtifactType.RETRIEVAL_PROFILE,
        logical_id="handbook.retrieval",
        logical_description="Authored before retrieval moved to the node",
        version_description="v1",
        body=_RETRIEVAL_BODY,
        created_by="manager",
    )
    configure_preparation(
        document_set=workspace["set"],
        embedding_profile=workspace["embedding"],
        chunking_profile=workspace["chunking"],
        retrieval_profile=legacy,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=False,
        actor="manager",
    )

    policy = DocumentSetPreparationProfile.objects.get(document_set=workspace["set"])
    assert policy.retrieval_profile_id == legacy.pk
    # The immutable artifact itself is never removed by the deprecation.
    assert ArtifactVersion.objects.filter(pk=legacy.pk).exists()
