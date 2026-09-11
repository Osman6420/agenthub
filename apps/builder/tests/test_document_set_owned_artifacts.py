"""Studio must not offer a second authoring path for document-set-owned artifacts."""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.builder import services
from apps.builder.models import ArtifactDraft
from apps.builder.tests.conftest import BuilderFixture

pytestmark = pytest.mark.django_db

_CHUNKING_BODY = {
    "api_version": "agenthub/chunking/v1",
    "kind": "ChunkingProfile",
    "strategy": "tokens",
    "size": 800,
    "overlap": 80,
    "max_chunks": 500,
}


def _chunking_draft(bf: BuilderFixture) -> ArtifactDraft:
    """Create a legacy chunking draft directly, bypassing the retired Studio path."""

    return ArtifactDraft.objects.create(
        organization=bf.org,
        project=bf.project,
        scenario=bf.scenario,
        artifact_type=ArtifactType.CHUNKING_PROFILE,
        name="Legacy chunking",
        logical_id="legacy.chunking",
        logical_description="Authored before chunking moved to the document set",
        body=_CHUNKING_BODY,
        created_by="author",
        updated_by="author",
    )


def test_chunking_is_not_a_studio_authorable_type(bf: BuilderFixture) -> None:
    assert ArtifactType.CHUNKING_PROFILE not in services.AUTHORABLE_ARTIFACT_TYPES
    assert ArtifactType.CHUNKING_PROFILE in services.DOCUMENT_SET_OWNED_ARTIFACT_TYPES

    with pytest.raises(services.BuilderError) as exc:
        services.create_artifact_draft(
            organization=bf.org,
            project=bf.project,
            scenario=bf.scenario,
            artifact_type=ArtifactType.CHUNKING_PROFILE,
            name="Chunking",
            logical_id="studio.chunking",
            logical_description="Should never be authored here",
            body=_CHUNKING_BODY,
            actor="author",
        )
    assert exc.value.code == "unsupported_artifact_type"
    assert not ArtifactDraft.objects.filter(logical_id="studio.chunking").exists()


def test_chunking_draft_api_create_is_rejected(client: Client, bf: BuilderFixture) -> None:
    client.force_login(bf.author)
    response = client.post(
        reverse("builder_api:artifact_drafts"),
        data=json.dumps(
            {
                "organization": bf.org.slug,
                "project_id": bf.project.pk,
                "scenario_id": bf.scenario.pk,
                "artifact_type": ArtifactType.CHUNKING_PROFILE,
                "name": "Chunking",
                "logical_id": "studio.chunking",
                "logical_description": "Should never be authored here",
                "body": _CHUNKING_BODY,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_artifact_type"
    assert not ArtifactDraft.objects.exists()


def test_published_chunking_artifact_cannot_seed_a_studio_draft(
    client: Client, bf: BuilderFixture
) -> None:
    artifact = create_artifact_version(
        organization=bf.org,
        artifact_type=ArtifactType.CHUNKING_PROFILE,
        logical_id="published.chunking",
        logical_description="Published by the document set",
        version_description="v1",
        body=_CHUNKING_BODY,
        created_by="document-set-manager",
    )
    client.force_login(bf.author)
    response = client.post(
        reverse("builder_api:artifact_drafts"),
        data=json.dumps(
            {
                "organization": bf.org.slug,
                "project_id": bf.project.pk,
                "scenario_id": bf.scenario.pk,
                "source_artifact_version_id": artifact.pk,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 404
    assert not ArtifactDraft.objects.exists()


def test_existing_chunking_drafts_are_hidden_from_every_studio_route(
    client: Client, bf: BuilderFixture
) -> None:
    draft = _chunking_draft(bf)
    client.force_login(bf.author)

    listed = client.get(reverse("builder_api:artifact_drafts"))
    assert listed.status_code == 200
    assert listed.json()["drafts"] == []

    # Direct URL access must not reach it either, for read or for write.
    detail_url = reverse("builder_api:artifact_draft_detail", args=[draft.pk])
    assert client.get(detail_url).status_code == 404
    assert (
        client.put(
            detail_url,
            data=json.dumps({"revision": 1, "name": "Renamed"}),
            content_type="application/json",
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("builder_api:artifact_draft_publish", args=[draft.pk]),
            data=json.dumps({"revision": 1, "version_description": "Nope"}),
            content_type="application/json",
        ).status_code
        == 404
    )
    draft.refresh_from_db()
    assert draft.name == "Legacy chunking"
    assert draft.revision == 1
