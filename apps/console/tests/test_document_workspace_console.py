"""P9.2 document-set-first bulk upload and staged-index console controls."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.documents import storage
from apps.documents.models import Document, DocumentSetVersionStatus
from apps.documents.services import (
    create_document_set,
    publish_document_set_version,
)
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
)
from apps.identity.roles import Role
from apps.ingestion.models import (
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IndexStatus,
    IndexVersion,
    TenantEmbeddingProfileGrant,
)
from apps.ingestion.tasks import build_document_set_index_task
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    settings.DOCUMENTS_MAX_BATCH_UPLOAD_FILES = 20
    settings.DOCUMENTS_MAX_BATCH_UPLOAD_BYTES = 100_000_000
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


def _member(username: str, org: Organization, role: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    if role == Role.ORGANIZATION_ADMIN:
        OrganizationResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            responsibility=OrganizationResponsibility.ADMINISTRATOR,
            assigned_by=user,
        )
    elif role == Role.AUDITOR:
        OrganizationResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            responsibility=OrganizationResponsibility.AUDITOR,
            assigned_by=user,
        )
    elif role in {Role.PROJECT_OWNER, Role.DOCUMENT_MANAGER}:
        for document_set in org.document_sets.all():
            DocumentSetResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                document_set=document_set,
                responsibility=DocumentSetResponsibility.MANAGER,
                assigned_by=user,
            )
    return user


def _profile(org: Organization, *, logical_id: str = "embed") -> EmbeddingProfile:
    profile = EmbeddingProfile.objects.create(
        logical_id=logical_id,
        revision=1,
        host="embedding.internal.example",
        model="embed-v1",
        secret_ref="secret://embedding",  # noqa: S106 -- opaque test reference, not a credential
        dimensions=64,
        created_by="platform-admin",
    )
    TenantEmbeddingProfileGrant.objects.create(
        organization=org, embedding_profile=profile, created_by="platform-admin"
    )
    return profile


def _document_profiles(org: Organization) -> tuple[ArtifactVersion, ArtifactVersion]:
    chunking = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.CHUNKING_PROFILE,
        logical_id="chunk",
        body={
            "api_version": "agenthub/chunking/v1",
            "kind": "ChunkingProfile",
            "strategy": "characters",
            "size": 500,
            "overlap": 50,
            "max_chunks": 1000,
        },
        created_by="owner",
    )
    retrieval = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.RETRIEVAL_PROFILE,
        logical_id="retrieve",
        body={
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "hybrid",
            "top_k": 5,
            "score_threshold": 0.0,
            "vector_weight": 0.5,
            "keyword_weight": 0.5,
        },
        created_by="owner",
    )
    return chunking, retrieval


@pytest.mark.django_db
def test_bulk_upload_generates_metadata_and_replaces_same_document(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))

    response = client.post(
        reverse("console:document_set_bulk_upload", args=[document_set.pk]),
        {
            "uploads": [
                SimpleUploadedFile("İnsan Kaynakları.md", b"ilk", content_type="evil/type"),
                SimpleUploadedFile("Rehber.pdf", b"pdf", content_type="text/plain"),
            ]
        },
    )
    assert response.status_code == 302
    draft = document_set.versions.get()
    assert draft.status == DocumentSetVersionStatus.DRAFT
    assert set(Document.objects.values_list("logical_id", flat=True)) == {
        "insan-kaynaklari",
        "rehber",
    }
    assert draft.memberships.count() == 2

    client.post(
        reverse("console:document_set_bulk_upload", args=[document_set.pk]),
        {"uploads": SimpleUploadedFile("Rehber.pdf", b"pdf-v2")},
    )
    draft.refresh_from_db()
    memberships = draft.memberships.filter(document_version__document__logical_id="rehber")
    assert memberships.count() == 1
    assert memberships.get().document_version.version == 2
    assert AuditEvent.objects.filter(action="documents.set_version.upsert_member").count() == 3


@pytest.mark.django_db
def test_new_manual_draft_preserves_latest_published_members(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    url = reverse("console:document_set_bulk_upload", args=[document_set.pk])
    client.post(url, {"uploads": SimpleUploadedFile("Bir.txt", b"one")})
    first = document_set.versions.get()
    publish_document_set_version(set_version=first, actor="seed")

    client.post(url, {"uploads": SimpleUploadedFile("İki.txt", b"two")})
    second = document_set.versions.order_by("-version").first()
    assert second is not None and second.version == 2
    assert set(
        second.memberships.values_list("document_version__document__logical_id", flat=True)
    ) == {"bir", "iki"}


@pytest.mark.django_db
def test_bulk_upload_rejects_duplicate_and_size_bound_before_writes(
    client: Client, settings: Any
) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    url = reverse("console:document_set_bulk_upload", args=[document_set.pk])

    client.post(
        url,
        {
            "uploads": [
                SimpleUploadedFile("same.txt", b"one"),
                SimpleUploadedFile("same.txt", b"two"),
            ]
        },
    )
    assert Document.objects.count() == 0
    assert document_set.versions.count() == 0

    settings.DOCUMENTS_MAX_BATCH_UPLOAD_FILES = 1
    client.post(
        url,
        {
            "uploads": [
                SimpleUploadedFile("one.txt", b"one"),
                SimpleUploadedFile("two.txt", b"two"),
            ]
        },
    )
    assert Document.objects.count() == 0
    assert document_set.versions.count() == 0

    settings.DOCUMENTS_MAX_BATCH_UPLOAD_FILES = 20
    client.post(url, {"uploads": SimpleUploadedFile("unsafe.exe", b"binary")})
    assert Document.objects.count() == 0
    assert document_set.versions.count() == 0

    settings.DOCUMENTS_MAX_BATCH_UPLOAD_BYTES = 3
    client.post(url, {"uploads": SimpleUploadedFile("large.txt", b"four")})
    assert Document.objects.count() == 0
    assert document_set.versions.count() == 0


@pytest.mark.django_db
def test_bulk_upload_is_tenant_scoped_and_author_gated(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    set_b = create_document_set(organization=org_b, logical_id="kb", name="KB", actor="seed")
    client.force_login(_member("owner-a", org_a, Role.PROJECT_OWNER))
    url = reverse("console:document_set_bulk_upload", args=[set_b.pk])
    assert client.post(url, {"uploads": SimpleUploadedFile("x.txt", b"x")}).status_code == 404

    client.force_login(_member("auditor-b", org_b, Role.AUDITOR))
    assert client.post(url, {"uploads": SimpleUploadedFile("x.txt", b"x")}).status_code == 403
    assert Document.objects.count() == 0


@pytest.mark.django_db
def test_build_request_accepts_only_tenant_granted_profile(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    other = Organization.objects.create(slug="org-b", name="B")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    client.post(
        reverse("console:document_set_bulk_upload", args=[document_set.pk]),
        {"uploads": SimpleUploadedFile("one.txt", b"one")},
    )
    version = document_set.versions.get()
    publish_document_set_version(set_version=version, actor="seed")
    granted = _profile(org)
    foreign = _profile(other, logical_id="foreign")
    chunking, retrieval = _document_profiles(org)
    url = reverse("console:document_set_build_index", args=[version.pk])

    detail = client.get(reverse("console:document_set_detail", args=[document_set.pk]))
    assert "embed" in detail.content.decode()
    assert "embedding.internal.example" not in detail.content.decode()
    assert "secret://embedding" not in detail.content.decode()

    with patch("apps.console.views.create_build_job", return_value=(object(), True)) as create_job:
        response = client.post(
            url,
            {
                "embedding_profile": granted.pk,
                "ocr_profile": "",
                "chunking_profile": chunking.pk,
                "retrieval_profile": retrieval.pk,
            },
        )
        assert response.status_code == 302
        create_job.assert_called_once()

    with patch("apps.console.views.create_build_job") as create_job:
        client.post(url, {"embedding_profile": foreign.pk, "ocr_profile": ""})
        create_job.assert_not_called()


@pytest.mark.django_db
def test_index_promotion_requires_document_set_manager(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    other = Organization.objects.create(slug="org-b", name="B")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    version = document_set.versions.create(
        organization=org, version=1, status=DocumentSetVersionStatus.PROMOTABLE
    )
    profile = _profile(org)
    index = IndexVersion.objects.create(
        organization=org,
        document_set_version=version,
        embedding_profile=profile,
        version=1,
        status=IndexStatus.PROMOTABLE,
        store_ready=True,
        dimensions=64,
        index_type="vector",
    )
    url = reverse("console:document_set_promote_index", args=[index.pk])

    client.force_login(_member("owner", org, Role.AUDITOR))
    assert client.post(url).status_code == 403
    client.force_login(_member("foreign-release", other, Role.RELEASE_MANAGER))
    assert client.post(url).status_code == 404
    client.force_login(_member("legacy-release", org, Role.RELEASE_MANAGER))
    assert client.post(url).status_code == 404
    manager = _member("set-manager", org, Role.AUDITOR)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=org,
        document_set=document_set,
        membership=OrganizationMembership.objects.get(organization=org, user=manager),
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=manager,
    )
    client.force_login(manager)
    with patch("apps.console.views.promote_staged_index") as promote:
        assert client.post(url).status_code == 302
        promote.assert_called_once_with(index, actor="set-manager")


@pytest.mark.django_db
def test_build_worker_revalidates_tenant_and_is_idempotent() -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    other = Organization.objects.create(slug="org-b", name="B")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    version = document_set.versions.create(
        organization=org, version=1, status=DocumentSetVersionStatus.PROMOTABLE
    )
    profile = _profile(org)
    index = IndexVersion.objects.create(
        organization=org,
        document_set_version=version,
        embedding_profile=profile,
        version=1,
        status=IndexStatus.PROMOTABLE,
        store_ready=True,
        dimensions=64,
        index_type="vector",
    )
    assert (
        build_document_set_index_task.run(version.pk, profile.pk, org.pk, "owner")
        == f"already_promotable:{index.pk}"
    )
    with pytest.raises(ValueError, match="DOCUMENT_SET_VERSION_NOT_FOUND"):
        build_document_set_index_task.run(version.pk, profile.pk, other.pk, "owner")
    profile.status = EmbeddingProfileStatus.DISABLED
    profile.save(update_fields=["status"])
    with pytest.raises(ValueError, match="EMBEDDING_PROFILE_NOT_GRANTED"):
        build_document_set_index_task.run(version.pk, profile.pk, org.pk, "owner")
