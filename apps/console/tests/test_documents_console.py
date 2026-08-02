"""Console document-plane UI tests (Phase 2 · P8.1).

Server-rendered, tenant-scoped, role-gated. Uploads use the hermetic in-memory object store
(config.settings.test defaults ``DOCUMENTS_OBJECT_STORE_BACKEND=memory``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.documents import services, storage
from apps.documents.models import Document, DocumentLifecycle, DocumentSet
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
)
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
    # Force the hermetic in-memory object store so uploads need no MinIO/S3 (config.settings.local
    # defaults the backend to "s3").
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
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
    elif role == Role.PROJECT_OWNER:
        for document_set in org.document_sets.all():
            DocumentSetResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                document_set=document_set,
                responsibility=DocumentSetResponsibility.MANAGER,
                assigned_by=user,
            )
    return user


def _draft(org: Organization):
    document_set, _ = DocumentSet.objects.get_or_create(
        organization=org,
        logical_id="test-documents",
        defaults={"name": "Test documents"},
    )
    return services.get_or_create_manual_draft(document_set=document_set, actor="seed")


@pytest.mark.django_db
def test_documents_list_is_tenant_scoped(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    services.upload_document(
        organization=org_a,
        logical_id="doc-a",
        title="Alpha doc",
        mime_type="text/plain",
        data=b"a",
        actor="seed",
        document_set_version=_draft(org_a),
    )
    services.upload_document(
        organization=org_b,
        logical_id="doc-b",
        title="Beta doc",
        mime_type="text/plain",
        data=b"b",
        actor="seed",
        document_set_version=_draft(org_b),
    )
    DocumentSet.objects.create(organization=org_a, logical_id="set-a", name="Set A")
    DocumentSet.objects.create(organization=org_b, logical_id="set-b", name="Set B")

    client.force_login(_member("alice", org_a, Role.PROJECT_OWNER))
    body = client.get(reverse("console:documents")).content.decode()
    assert "set-a" in body
    assert "set-b" not in body
    assert "doc-a" not in body  # standalone inventory is not part of the primary journey
    assert "doc-b" not in body
    assert "Gelişmiş envanteri aç" not in body


@pytest.mark.django_db
def test_standalone_console_upload_is_denied(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))

    response = client.post(
        reverse("console:document_upload"),
        {
            "organization": org.id,
            "logical_id": "policy",
            "title": "Return policy",
            "file": SimpleUploadedFile(
                "policy.txt", b"thirty day window", content_type="text/plain"
            ),
        },
    )
    assert response.status_code == 302
    assert not Document.objects.filter(organization=org).exists()
    assert not AuditEvent.objects.filter(action="documents.document.upload").exists()


@pytest.mark.django_db
def test_upload_denied_for_non_author(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    client.force_login(_member("readonly", org, Role.AUDITOR))  # read-only, not an author

    response = client.post(
        reverse("console:document_upload"),
        {
            "organization": org.id,
            "logical_id": "policy",
            "title": "x",
            "file": SimpleUploadedFile("p.txt", b"data", content_type="text/plain"),
        },
    )
    assert response.status_code == 302  # redirected with an error message
    assert not Document.objects.filter(organization=org, logical_id="policy").exists()


@pytest.mark.django_db
def test_soft_delete_tombstones_document(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    version = services.upload_document(
        organization=org,
        logical_id="doc",
        title="Doc",
        mime_type="text/plain",
        data=b"data",
        actor="seed",
        document_set_version=_draft(org),
    )
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))

    response = client.post(reverse("console:document_soft_delete", args=[version.document_id]))
    assert response.status_code == 302
    version.document.refresh_from_db()
    assert version.document.lifecycle_state == DocumentLifecycle.TOMBSTONED
    assert AuditEvent.objects.filter(action="documents.document.soft_delete").exists()


@pytest.mark.django_db
def test_cross_tenant_soft_delete_is_not_found(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    version_b = services.upload_document(
        organization=org_b,
        logical_id="doc-b",
        title="B",
        mime_type="text/plain",
        data=b"b",
        actor="seed",
        document_set_version=_draft(org_b),
    )
    client.force_login(_member("owner-a", org_a, Role.PROJECT_OWNER))

    response = client.post(reverse("console:document_soft_delete", args=[version_b.document_id]))
    assert response.status_code == 404
    version_b.document.refresh_from_db()
    assert version_b.document.lifecycle_state == DocumentLifecycle.ACTIVE  # untouched


@pytest.mark.django_db
def test_document_set_manager_can_confirm_and_purge_tombstoned_document(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    version = services.upload_document(
        organization=org,
        logical_id="obsolete",
        title="Old",
        mime_type="text/plain",
        data=b"old",
        actor="seed",
        document_set_version=_draft(org),
    )
    document = version.document
    document.lifecycle_state = DocumentLifecycle.TOMBSTONED
    document.deleted_at = timezone.now()
    document.save(update_fields=["lifecycle_state", "deleted_at"])
    manager = _member("manager", org, Role.ORGANIZATION_ADMIN)
    membership = OrganizationMembership.objects.get(organization=org, user=manager)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        document_set=DocumentSet.objects.get(versions__memberships__document_version=version),
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=manager,
    )
    client.force_login(manager)

    response = client.post(
        reverse("console:document_purge", args=[document.id]),
        {"confirm_logical_id": "obsolete"},
    )
    assert response.status_code == 302
    assert Document.objects.filter(pk=document.id).exists()
    assert not AuditEvent.objects.filter(action="documents.document.purge").exists()


@pytest.mark.django_db
def test_purge_requires_admin_tombstone_and_exact_confirmation(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    version = services.upload_document(
        organization=org,
        logical_id="keep",
        title="Keep",
        mime_type="text/plain",
        data=b"keep",
        actor="seed",
        document_set_version=_draft(org),
    )
    document = version.document
    client.force_login(_member("editor", org, Role.SCENARIO_EDITOR))
    response = client.post(
        reverse("console:document_purge", args=[document.id]),
        {"confirm_logical_id": "keep"},
    )
    assert response.status_code == 404

    client.force_login(_member("admin", org, Role.ORGANIZATION_ADMIN))
    client.post(
        reverse("console:document_purge", args=[document.id]),
        {"confirm_logical_id": "keep"},
    )
    assert Document.objects.filter(pk=document.id).exists()  # active -> denied
    document.lifecycle_state = DocumentLifecycle.TOMBSTONED
    document.deleted_at = timezone.now()
    document.save(update_fields=["lifecycle_state", "deleted_at"])
    client.post(
        reverse("console:document_purge", args=[document.id]),
        {"confirm_logical_id": "wrong"},
    )
    assert Document.objects.filter(pk=document.id).exists()


@pytest.mark.django_db
def test_cross_tenant_purge_is_not_found(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    version = services.upload_document(
        organization=org_b,
        logical_id="foreign",
        title="Foreign",
        mime_type="text/plain",
        data=b"x",
        actor="seed",
        document_set_version=_draft(org_b),
    )
    client.force_login(_member("admin-a", org_a, Role.ORGANIZATION_ADMIN))
    response = client.post(
        reverse("console:document_purge", args=[version.document_id]),
        {"confirm_logical_id": "foreign"},
    )
    assert response.status_code == 404
    assert Document.objects.filter(pk=version.document_id).exists()
