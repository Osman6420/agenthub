"""Phase 2.5 Part 4 document-set-first lifecycle and authorization tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.documents import services, storage
from apps.documents.models import DocumentLifecycle, DocumentSetMembership, DocumentSetVersionStatus
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
)
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
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
        for document_set in org.document_sets.all():
            DocumentSetResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                document_set=document_set,
                responsibility=DocumentSetResponsibility.MANAGER,
                assigned_by=user,
            )
    elif role == Role.AUDITOR:
        OrganizationResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            responsibility=OrganizationResponsibility.AUDITOR,
            assigned_by=user,
        )
    else:
        for document_set in org.document_sets.all():
            DocumentSetResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                document_set=document_set,
                responsibility=DocumentSetResponsibility.MANAGER,
                assigned_by=user,
            )
    return user


def _set_with_draft(org: Organization) -> tuple[Any, Any, Any, Any]:
    document_set = services.create_document_set(
        organization=org, logical_id="kb", name="Bilgi bankası", actor="seed"
    )
    draft = services.get_or_create_manual_draft(document_set=document_set, actor="seed")
    version = services.upload_document(
        organization=org,
        logical_id="rehber",
        title="Rehber",
        mime_type="text/plain",
        data=b"v1",
        actor="seed",
        document_set_version=draft,
    )
    membership = services.upsert_document_in_set_draft(
        set_version=draft, document_version=version, actor="seed"
    )
    return document_set, version.document, draft, membership


def test_primary_navigation_and_advanced_inventory_are_separated(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set, document, _, _ = _set_with_draft(org)

    client.force_login(_member("author", org, Role.PROJECT_OWNER))
    primary = client.get(reverse("console:documents"))
    assert primary.status_code == 200
    assert document_set.name in primary.content.decode()
    assert document.logical_id not in primary.content.decode()
    assert client.get(reverse("console:advanced_document_inventory")).status_code == 403

    client.force_login(_member("admin", org, Role.ORGANIZATION_ADMIN))
    advanced = client.get(reverse("console:advanced_document_inventory"))
    assert advanced.status_code == 200
    assert document.logical_id in advanced.content.decode()
    assert "geri alınamaz" in advanced.content.decode()

    document.lifecycle_state = DocumentLifecycle.TOMBSTONED
    document.save(update_fields=["lifecycle_state"])
    body = client.get(reverse("console:advanced_document_inventory")).content.decode()
    assert "Set sürümünde pinli; purge engelli." in body
    assert reverse("console:document_purge_public", args=[document.public_id]) not in body


def test_advanced_inventory_lists_only_administered_organizations(client: Client) -> None:
    org_admin = Organization.objects.create(slug="org-admin", name="Admin")
    org_reader = Organization.objects.create(slug="org-reader", name="Reader")
    _, admin_document, _, _ = _set_with_draft(org_admin)
    _, reader_document, _, _ = _set_with_draft(org_reader)
    reader_document.logical_id = "reader-secret"
    reader_document.save(update_fields=["logical_id"])
    user = _member("mixed-role", org_admin, Role.ORGANIZATION_ADMIN)
    OrganizationMembership.objects.create(organization=org_reader, user=user)
    client.force_login(user)

    body = client.get(reverse("console:advanced_document_inventory")).content.decode()
    assert admin_document.logical_id in body
    assert org_admin.slug in body
    assert org_reader.slug not in body
    assert reader_document.logical_id not in body


def test_set_document_detail_shows_lineage_without_storage_secrets(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set, document, draft, _ = _set_with_draft(org)
    reader = _member("reader", org, Role.AUDITOR)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=org,
        membership=OrganizationMembership.objects.get(organization=org, user=reader),
        document_set=document_set,
        responsibility=DocumentSetResponsibility.CONTENT_READER,
        assigned_by=reader,
    )
    client.force_login(reader)

    response = client.get(
        reverse(
            "console:document_set_document_detail",
            args=[document_set.public_id, document.public_id],
        )
    )
    body = response.content.decode()
    assert response.status_code == 200
    assert "Rehber" in body
    assert f"Set v{draft.version}" in body
    assert document.versions.get().object_key not in body
    assert document.versions.get().checksum not in body
    assert "Yeni sürüm yükle" not in body


def test_author_replaces_document_and_pins_new_version_into_draft(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set, document, draft, _ = _set_with_draft(org)
    client.force_login(_member("author", org, Role.PROJECT_OWNER))

    response = client.post(
        reverse(
            "console:document_set_document_replace",
            args=[document_set.public_id, document.public_id],
        ),
        {"file": SimpleUploadedFile("rehber.txt", b"v2", content_type="evil/type")},
    )
    assert response.status_code == 302
    document.refresh_from_db()
    draft.refresh_from_db()
    assert document.current_version == 2
    membership = draft.memberships.get()
    assert membership.document_version.version == 2
    assert AuditEvent.objects.filter(action="documents.document.upload").count() == 2
    assert AuditEvent.objects.filter(action="documents.set_version.upsert_member").count() == 2


def test_author_removes_only_draft_membership_and_audits(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set, document, draft, membership = _set_with_draft(org)
    client.force_login(_member("author", org, Role.PROJECT_OWNER))

    response = client.post(
        reverse("console:document_set_remove_member", args=[draft.pk, membership.pk])
    )
    assert response.status_code == 302
    assert not DocumentSetMembership.objects.filter(pk=membership.pk).exists()
    assert document.versions.count() == 1
    assert AuditEvent.objects.filter(action="documents.set_version.remove_member").exists()
    assert response.headers["Location"] == reverse(
        "console:document_set_detail_public", args=[document_set.public_id]
    )


def test_published_membership_cannot_be_removed(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    _, _, draft, membership = _set_with_draft(org)
    services.publish_document_set_version(set_version=draft, actor="seed")
    client.force_login(_member("author", org, Role.PROJECT_OWNER))

    response = client.post(
        reverse("console:document_set_remove_member", args=[draft.pk, membership.pk])
    )
    assert response.status_code == 302
    assert DocumentSetMembership.objects.filter(pk=membership.pk).exists()
    assert not AuditEvent.objects.filter(action="documents.set_version.remove_member").exists()


def test_remove_member_rolls_back_when_audit_write_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    _, _, draft, membership = _set_with_draft(org)

    def fail_audit(**_: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(services, "record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        services.remove_document_from_set_draft(
            set_version=draft, membership_id=membership.pk, actor="author"
        )
    assert DocumentSetMembership.objects.filter(pk=membership.pk).exists()


def test_tombstone_preserves_historical_pin_and_bytes(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set, document, draft, membership = _set_with_draft(org)
    services.publish_document_set_version(set_version=draft, actor="seed")
    object_key = document.versions.get().object_key
    client.force_login(_member("author", org, Role.PROJECT_OWNER))

    response = client.post(
        reverse(
            "console:document_set_document_tombstone",
            args=[document_set.public_id, document.public_id],
        )
    )
    assert response.status_code == 302
    document.refresh_from_db()
    assert document.lifecycle_state == DocumentLifecycle.TOMBSTONED
    assert DocumentSetMembership.objects.filter(pk=membership.pk).exists()
    assert storage.get_object_store().get(object_key) == b"v1"


def test_set_document_routes_fail_closed_across_tenants(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    set_b, document_b, draft_b, membership_b = _set_with_draft(org_b)
    client.force_login(_member("author-a", org_a, Role.PROJECT_OWNER))

    detail_url = reverse(
        "console:document_set_document_detail", args=[set_b.public_id, document_b.public_id]
    )
    replace_url = reverse(
        "console:document_set_document_replace", args=[set_b.public_id, document_b.public_id]
    )
    tombstone_url = reverse(
        "console:document_set_document_tombstone", args=[set_b.public_id, document_b.public_id]
    )
    remove_url = reverse("console:document_set_remove_member", args=[draft_b.pk, membership_b.pk])
    assert client.get(detail_url).status_code == 404
    assert client.post(replace_url, {"file": SimpleUploadedFile("x.txt", b"x")}).status_code == 404
    assert client.post(tombstone_url).status_code == 404
    assert client.post(remove_url).status_code == 404
    document_b.refresh_from_db()
    assert document_b.lifecycle_state == DocumentLifecycle.ACTIVE
    assert document_b.current_version == 1
    assert draft_b.status == DocumentSetVersionStatus.DRAFT
    assert DocumentSetMembership.objects.filter(pk=membership_b.pk).exists()


def test_document_must_be_a_member_of_the_requested_set(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    requested_set, _, _, _ = _set_with_draft(org)
    other_set = services.create_document_set(
        organization=org, logical_id="other", name="Other", actor="seed"
    )
    other_draft = services.get_or_create_manual_draft(document_set=other_set, actor="seed")
    other_version = services.upload_document(
        organization=org,
        logical_id="other-document",
        title="Other",
        mime_type="text/plain",
        data=b"other",
        actor="seed",
        document_set_version=other_draft,
    )
    services.upsert_document_in_set_draft(
        set_version=other_draft, document_version=other_version, actor="seed"
    )
    client.force_login(_member("reader", org, Role.AUDITOR))

    response = client.get(
        reverse(
            "console:document_set_document_detail",
            args=[requested_set.public_id, other_version.document.public_id],
        )
    )
    assert response.status_code == 404
