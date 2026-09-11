"""Phase 2.9 Part 4 governed setup and immutable release-input console coverage."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet
from apps.documents.services import create_document_set
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.ingestion.confluence_services import (
    ConfluenceServiceError,
    disable_confluence_profile,
    grant_confluence_profile,
)
from apps.ingestion.models import (
    ConfluenceProfile,
    EmbeddingProfile,
    EmbeddingProfileStatus,
    RestPullProfile,
    TenantConfluenceProfileGrant,
    TenantEmbeddingProfileGrant,
)
from apps.ingestion.rest_services import (
    RestServiceError,
    disable_rest_profile,
    grant_rest_profile,
)
from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _scenario(organization: Organization, slug: str) -> Scenario:
    project = AIProject.objects.create(organization=organization, slug=f"p-{slug}", name=slug)
    return Scenario.objects.create(project=project, slug=slug, name=slug)


def _scenario_actor(username: str, scenario: Scenario, responsibility: str):
    user = User.objects.create_user(username, password="unused")  # noqa: S106
    membership = OrganizationMembership.objects.create(
        organization=scenario.organization,
        user=user,
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=scenario.organization,
        membership=membership,
        scenario=scenario,
        responsibility=responsibility,
        assigned_by=user,
    )
    return user


def _document_manager(username: str, document_set: DocumentSet):
    user = User.objects.create_user(username, password="unused")  # noqa: S106
    membership = OrganizationMembership.objects.create(
        organization=document_set.organization,
        user=user,
    )
    DocumentSetResponsibilityAssignment.objects.create(
        organization=document_set.organization,
        membership=membership,
        document_set=document_set,
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=user,
    )
    return user


def _artifact_payload(artifact_type: str, body: dict[str, object]) -> dict[str, str]:
    return {
        "artifact_type": artifact_type,
        "logical_description": "Stable scenario contract purpose",
        "version_description": "Guided revision",
        "body": json.dumps(body),
    }


def test_exact_editor_creates_validated_immutable_contract_versions(client: Client) -> None:
    organization = Organization.objects.create(slug="artifact-ui", name="Artifact UI")
    scenario = _scenario(organization, "assigned")
    editor = _scenario_actor("artifact-editor", scenario, ScenarioResponsibility.EDITOR)
    client.force_login(editor)
    url = reverse("console:scenario_artifact_create", args=[scenario.public_id])
    schema = {"type": "object", "properties": {}, "additionalProperties": False}

    first = client.post(url, _artifact_payload(ArtifactType.INPUT_CONTRACT, schema))
    second = client.post(url, _artifact_payload(ArtifactType.INPUT_CONTRACT, schema))

    assert first.status_code == 302
    assert second.status_code == 302
    assert first.headers["Location"] == reverse(
        "console:scenario_detail_public", args=[scenario.public_id]
    )
    assert second.headers["Location"] == first.headers["Location"]
    versions = ArtifactVersion.objects.filter(
        organization=organization,
        type=ArtifactType.INPUT_CONTRACT,
        logical_id=f"scenario-{scenario.public_id.hex}-input_contract",
    ).order_by("version")
    assert list(versions.values_list("version", flat=True)) == [1, 2]
    assert versions[0].checksum == versions[1].checksum
    event = AuditEvent.objects.filter(
        action="artifact_version.create",
        outcome="success",
    ).latest("occurred_at")
    assert event.after is not None
    assert event.after["artifact_type"] == ArtifactType.INPUT_CONTRACT
    assert "properties" not in json.dumps(event.after)
    assert "Guided revision" in client.get(first.headers["Location"]).content.decode()


def test_artifact_authoring_rejects_secret_and_other_exact_scope(client: Client) -> None:
    organization = Organization.objects.create(slug="artifact-deny", name="Artifact Deny")
    assigned = _scenario(organization, "assigned")
    hidden = _scenario(organization, "hidden")
    editor = _scenario_actor("artifact-exact", assigned, ScenarioResponsibility.EDITOR)
    client.force_login(editor)

    denied = client.post(
        reverse("console:scenario_artifact_create", args=[assigned.public_id]),
        _artifact_payload(ArtifactType.OUTPUT_CONTRACT, {"api_key": "inline-secret"}),
    )

    assert denied.status_code == 200
    assert "Artifact doğrulanamadı" in denied.content.decode()
    assert not ArtifactVersion.objects.exists()
    assert AuditEvent.objects.filter(
        action="artifact_version.create",
        outcome="failure",
        reason="ARTIFACT_VALIDATION_FAILED",
    ).exists()
    assert (
        client.get(reverse("console:scenario_artifact_create", args=[hidden.public_id])).status_code
        == 404
    )


def test_neighboring_release_role_cannot_author_artifact(client: Client) -> None:
    organization = Organization.objects.create(slug="artifact-role", name="Artifact Role")
    scenario = _scenario(organization, "assigned")
    manager = _scenario_actor(
        "artifact-release-manager",
        scenario,
        ScenarioResponsibility.RELEASE_MANAGER,
    )
    client.force_login(manager)

    response = client.post(
        reverse("console:scenario_artifact_create", args=[scenario.public_id]),
        _artifact_payload(ArtifactType.EVAL_SUITE, {"cases": []}),
    )

    assert response.status_code == 403
    assert not ArtifactVersion.objects.exists()


def _model_payload() -> dict[str, object]:
    return {
        "logical_id": "console-chat",
        "revision": 1,
        "provider": "openai_compatible",
        "scheme": "https",
        "host": "models.example.com",
        "port": 443,
        "path": "/v1/chat/completions",
        "model": "chat-1",
        "secret_ref": "secret:model-token",  # noqa: S106
        "timeout_seconds": 30,
        "max_response_bytes": 1_000_000,
        "max_output_tokens": 2_048,
    }


def _embedding_payload() -> dict[str, object]:
    return {
        "logical_id": "console-embed",
        "revision": 1,
        "provider": "openai_compatible",
        "scheme": "https",
        "host": "embeddings.example.com",
        "port": 443,
        "path": "/v1/embeddings",
        "model": "embed-1",
        "secret_ref": "secret:embed-token",  # noqa: S106
        "dimensions": 64,
        "index_type": "vector",
        "normalize": True,
        "distance_metric": "cosine",
        "timeout_seconds": 30,
        "max_response_bytes": 5_000_000,
        "max_batch_size": 64,
    }


@pytest.mark.parametrize(
    ("kind", "payload"),
    [("model", _model_payload()), ("embedding", _embedding_payload())],
)
def test_profile_form_groups_fields_without_dropping_any(
    client: Client, kind: str, payload: dict[str, object]
) -> None:
    """BUG-009: the form was regrouped into fieldsets for readability -- every field the form
    actually has (and the registration flow actually accepts, per the payload fixtures above)
    must still render, none silently dropped by the new grouping."""
    admin = User.objects.create_superuser(f"profile-admin-{kind}", password=None)
    client.force_login(admin)

    body = client.get(reverse("console:platform_profile_create", args=[kind])).content.decode()

    for field_name in payload:
        assert f'name="{field_name}"' in body, f"{field_name} missing from {kind} profile form"


def test_platform_setup_is_platform_only_and_redacts_registered_profile(client: Client) -> None:
    organization = Organization.objects.create(slug="platform-ui", name="Platform UI")
    member = User.objects.create_user("tenant-member")
    OrganizationMembership.objects.create(organization=organization, user=member)
    client.force_login(member)
    assert client.get(reverse("console:platform_setup")).status_code == 403
    assert (
        client.post(
            reverse("console:platform_profile_create", args=["model"]),
            _model_payload(),
        ).status_code
        == 403
    )

    admin = User.objects.create_superuser("platform-admin", password=None)
    client.force_login(admin)
    response = client.post(
        reverse("console:platform_profile_create", args=["model"]),
        _model_payload(),
        follow=True,
    )

    assert response.status_code == 200
    profile = ModelProfile.objects.get(logical_id="console-chat")
    body = response.content.decode()
    assert "console-chat" in body
    assert "models.example.com" not in body
    assert "model-token" not in body
    event = AuditEvent.objects.get(action="model_profile.create", outcome="success")
    assert "model-token" not in json.dumps(event.after)

    disabled = client.post(
        reverse(
            "console:platform_profile_disable",
            args=["model", profile.public_id],
        )
    )
    assert disabled.status_code == 302
    profile.refresh_from_db()
    assert profile.status == ModelProfileStatus.DISABLED


def test_embedding_profile_grant_is_explicit_idempotent_and_disabled_safe(
    client: Client,
) -> None:
    organization = Organization.objects.create(slug="embedding-grant", name="Embedding Grant")
    admin = User.objects.create_superuser("embedding-platform", password=None)
    client.force_login(admin)
    created = client.post(
        reverse("console:platform_profile_create", args=["embedding"]),
        _embedding_payload(),
    )
    assert created.status_code == 302
    profile = EmbeddingProfile.objects.get(logical_id="console-embed")
    grant_url = reverse(
        "console:platform_profile_grant",
        args=["embedding", profile.public_id],
    )

    assert client.post(grant_url, {"organization": organization.pk}).status_code == 302
    assert client.post(grant_url, {"organization": organization.pk}).status_code == 302
    assert (
        TenantEmbeddingProfileGrant.objects.filter(
            organization=organization,
            embedding_profile=profile,
        ).count()
        == 1
    )

    client.post(
        reverse(
            "console:platform_profile_disable",
            args=["embedding", profile.public_id],
        )
    )
    profile.refresh_from_db()
    assert profile.status == EmbeddingProfileStatus.DISABLED
    other = Organization.objects.create(slug="embedding-other", name="Embedding Other")
    rejected = client.post(grant_url, {"organization": other.pk})
    assert rejected.status_code == 200
    assert not TenantEmbeddingProfileGrant.objects.filter(organization=other).exists()


@override_settings(CONFLUENCE_NETWORK_POLICIES={"corp": ["10.20.30.0/24"]})
def test_platform_registers_and_grants_connector_without_tenant_secret_disclosure(
    client: Client,
) -> None:
    organization = Organization.objects.create(slug="connector-ready", name="Connector Ready")
    document_set = create_document_set(
        organization=organization,
        logical_id="kb",
        name="KB",
        actor="seed",
    )
    manager = _document_manager("connector-manager", document_set)
    admin = User.objects.create_superuser("connector-platform", password=None)
    client.force_login(admin)
    confluence_payload = {
        "logical_id": "corp-wiki",
        "revision": 1,
        "base_url": "https://confluence.corp.example/confluence",
        "secret_ref": "secret:wiki-reader",  # noqa: S106
        "network_policy_id": "corp",
        "timeout_seconds": 30,
        "page_size": 50,
        "max_pages": 100,
        "max_depth": 10,
        "max_requests": 500,
        "max_retries": 2,
        "max_response_bytes": 5_000_000,
        "max_page_body_bytes": 4_000_000,
        "max_total_bytes": 100_000_000,
    }
    registered = client.post(
        reverse("console:platform_profile_create", args=["confluence"]),
        confluence_payload,
    )
    assert registered.status_code == 302
    profile = ConfluenceProfile.objects.get(logical_id="corp-wiki")
    grant_url = reverse(
        "console:platform_profile_grant",
        args=["confluence", profile.public_id],
    )
    grant_page = client.get(grant_url)
    assert "Connector Ready · KB · kb" in grant_page.content.decode()
    assert client.post(grant_url, {"document_set": document_set.pk}).status_code == 302
    assert TenantConfluenceProfileGrant.objects.filter(
        organization=organization,
        document_set=document_set,
        confluence_profile=profile,
    ).exists()

    client.force_login(manager)
    page = client.get(
        reverse("console:document_set_connectors_public", args=[document_set.public_id])
    )
    body = page.content.decode()
    assert page.status_code == 200
    assert "corp-wiki" in body
    assert "confluence.corp.example" not in body
    assert "wiki-reader" not in body
    assert reverse("console:platform_setup") not in body
    assert client.post(grant_url, {"document_set": document_set.pk}).status_code == 403


def test_platform_registers_rest_profile_without_opening_egress(client: Client) -> None:
    admin = User.objects.create_superuser("rest-platform", password=None)
    client.force_login(admin)
    response = client.post(
        reverse("console:platform_profile_create", args=["rest"]),
        {
            "logical_id": "public-api",
            "revision": 1,
            "base_url": "https://api.example.com",
            "path_prefix": "/knowledge",
            "method": "GET",
            "auth_mode": "none",
            "secret_ref": "",
            "api_key_header_name": "",
            "timeout_seconds": 30,
            "max_response_bytes": 5_000_000,
            "max_total_bytes": 100_000_000,
            "max_requests": 1_000,
            "max_items": 50_000,
            "max_pages": 1_000,
            "max_retries": 2,
            "max_decoded_item_bytes": 25_000_000,
        },
    )

    assert response.status_code == 302
    profile = RestPullProfile.objects.get(logical_id="public-api")
    assert not profile.tenant_document_set_grants.exists()
    assert not profile.sources.exists()


def test_disabled_connector_profiles_cannot_be_granted_through_stale_objects() -> None:
    organization = Organization.objects.create(slug="stale-grant", name="Stale grant")
    document_set = create_document_set(
        organization=organization,
        logical_id="kb",
        name="KB",
        actor="seed",
    )
    admin = User.objects.create_superuser("stale-platform", password=None)
    confluence = ConfluenceProfile.objects.create(
        logical_id="stale-wiki",
        revision=1,
        host="confluence.private.example",
        secret_ref="secret:wiki",  # noqa: S106
        network_policy_id="corp",
        created_by="seed",
    )
    rest = RestPullProfile.objects.create(
        logical_id="stale-rest",
        revision=1,
        host="api.example.com",
        created_by="seed",
    )

    disable_confluence_profile(actor=admin, confluence_profile=confluence)
    disable_rest_profile(actor=admin, rest_profile=rest)

    with pytest.raises(ConfluenceServiceError, match="CONFLUENCE_PROFILE_DISABLED"):
        grant_confluence_profile(
            actor=admin,
            organization=organization,
            document_set=document_set,
            confluence_profile=confluence,
        )
    with pytest.raises(RestServiceError, match="REST_PROFILE_DISABLED"):
        grant_rest_profile(
            actor=admin,
            organization=organization,
            document_set=document_set,
            rest_profile=rest,
        )
