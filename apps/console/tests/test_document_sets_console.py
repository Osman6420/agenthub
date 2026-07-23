"""Console document-set lifecycle UI tests (Phase 2 · P8.2).

Create a set, open a draft version, add a member, publish — role/tenant-scoped, over the audited
``apps.documents.services``. Hermetic in-memory object store (uploads need no MinIO).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.documents import storage
from apps.documents.models import (
    DocumentSet,
    DocumentSetVersion,
    DocumentSetVersionStatus,
)
from apps.documents.services import create_document_set, upload_document
from apps.identity.roles import Role
from apps.ingestion.job_lifecycle import create_build_job
from apps.ingestion.tests.test_staged_build import _granted_profile, _published_set_version
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


def _member(username: str, org: Organization, role: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


@pytest.mark.django_db
def test_author_can_create_document_set(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))

    response = client.post(
        reverse("console:document_set_create"),
        {"organization": org.id, "logical_id": "kb", "name": "Knowledge base"},
    )
    assert response.status_code == 302
    document_set = DocumentSet.objects.get(organization=org)
    assert document_set.logical_id.startswith("knowledge-base-")


@pytest.mark.django_db
def test_full_set_version_lifecycle(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    upload_document(
        organization=org,
        logical_id="doc-1",
        title="Doc 1",
        mime_type="text/plain",
        data=b"hello",
        actor="seed",
    )
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))

    # 1. open a draft version
    client.post(reverse("console:document_set_version_create", args=[document_set.id]))
    version = DocumentSetVersion.objects.get(document_set=document_set)
    assert version.status == DocumentSetVersionStatus.DRAFT

    # 2. add a member (pins the document's current version)
    from apps.documents.models import Document

    document = Document.objects.get(organization=org, logical_id="doc-1")
    client.post(
        reverse("console:document_set_add_member", args=[version.id]),
        {"document_id": document.id},
    )
    assert version.memberships.count() == 1

    # 3. publish → promotable
    client.post(reverse("console:document_set_version_publish", args=[version.id]))
    version.refresh_from_db()
    assert version.status == DocumentSetVersionStatus.PROMOTABLE


@pytest.mark.django_db
def test_publish_empty_version_fails_gracefully(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    client.post(reverse("console:document_set_version_create", args=[document_set.id]))
    version = DocumentSetVersion.objects.get(document_set=document_set)

    response = client.post(reverse("console:document_set_version_publish", args=[version.id]))
    assert response.status_code == 302  # redirected with an error, not a 500
    version.refresh_from_db()
    assert version.status == DocumentSetVersionStatus.DRAFT  # unchanged (SET_VERSION_EMPTY)


@pytest.mark.django_db
def test_cross_tenant_set_detail_is_not_found(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    set_b = create_document_set(organization=org_b, logical_id="kb-b", name="B", actor="seed")
    client.force_login(_member("owner-a", org_a, Role.PROJECT_OWNER))

    assert client.get(reverse("console:document_set_detail", args=[set_b.id])).status_code == 404


@pytest.mark.django_db
def test_non_author_cannot_create_set(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    client.force_login(_member("readonly", org, Role.AUDITOR))

    response = client.post(
        reverse("console:document_set_create"),
        {"organization": org.id, "logical_id": "kb", "name": "KB"},
    )
    assert response.status_code == 403
    assert not DocumentSet.objects.filter(organization=org, logical_id="kb").exists()


@pytest.mark.django_db
def test_build_job_actions_are_role_and_tenant_scoped(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)
    org_a = Organization.objects.create(slug="job-a", name="A")
    org_b = Organization.objects.create(slug="job-b", name="B")
    version_b = _published_set_version(org_b, ["text"])
    profile_b = _granted_profile(org_b)
    job, _ = create_build_job(
        document_set_version=version_b,
        embedding_profile=profile_b,
        ocr_profile=None,
        actor="owner-b",
    )
    client.force_login(_member("owner-a", org_a, Role.PROJECT_OWNER))
    assert (
        client.post(
            reverse("console:document_set_cancel_build_job", args=[job.public_id])
        ).status_code
        == 404
    )
    client.force_login(_member("auditor-b", org_b, Role.AUDITOR))
    assert (
        client.post(
            reverse("console:document_set_cancel_build_job", args=[job.public_id])
        ).status_code
        == 403
    )
    assert AuditEvent.objects.filter(
        action="ingestion.staged_index.authorization_denied",
        outcome="failure",
        resource_id=str(job.public_id),
    ).exists()
