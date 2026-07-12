"""Document-plane service behavior: upload, versioning, removal, and sets."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.documents import services, storage
from apps.documents.models import (
    Document,
    DocumentLifecycle,
    DocumentSetVersionStatus,
    DocumentVersion,
)
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(slug="svc-org", name="Svc Org")


def _upload(
    org: Organization, logical_id: str = "doc-a", data: bytes = b"hello"
) -> DocumentVersion:
    return services.upload_document(
        organization=org,
        logical_id=logical_id,
        title="A",
        mime_type="text/plain",
        data=data,
        actor="op",
    )


def test_upload_creates_document_version_and_stores_blob(org: Organization) -> None:
    version = _upload(org)
    assert version.version == 1
    assert version.document.current_version == 1
    assert version.byte_size == 5
    # Bytes are in the object store under the recorded key.
    assert storage.get_object_store().get(version.object_key) == b"hello"
    # Audit records the upload with the checksum, not content.
    event = AuditEvent.objects.get(action="documents.document.upload")
    assert event.reason == version.checksum
    assert event.organization_id == org.id


def test_second_upload_advances_version(org: Organization) -> None:
    _upload(org, data=b"v1")
    v2 = _upload(org, data=b"v2 content")
    assert v2.version == 2
    assert Document.objects.get(organization=org, logical_id="doc-a").current_version == 2
    assert DocumentVersion.objects.filter(document=v2.document).count() == 2


def test_upload_rejects_tombstoned_document(org: Organization) -> None:
    version = _upload(org)
    services.soft_delete_document(version.document, actor="op")
    with pytest.raises(services.DocumentError) as exc:
        _upload(org)
    assert exc.value.code == "DOCUMENT_TOMBSTONED"


@pytest.mark.parametrize(
    ("mime", "data", "code"),
    [
        ("text/plain", b"", "EMPTY_UPLOAD"),
        ("application/x-msdownload", b"data", "MIME_TYPE_DENIED"),
    ],
)
def test_upload_validation(org: Organization, mime: str, data: bytes, code: str) -> None:
    with pytest.raises(services.DocumentError) as exc:
        services.upload_document(
            organization=org,
            logical_id="x",
            title="",
            mime_type=mime,
            data=data,
            actor="op",
        )
    assert exc.value.code == code


def test_upload_too_large_is_rejected_and_leaves_no_blob(org: Organization, settings) -> None:
    settings.DOCUMENTS_MAX_UPLOAD_BYTES = 4
    with pytest.raises(services.DocumentError) as exc:
        _upload(org, data=b"toolong")
    assert exc.value.code == "UPLOAD_TOO_LARGE"
    assert DocumentVersion.objects.count() == 0


def test_soft_delete_is_idempotent_and_audited(org: Organization) -> None:
    version = _upload(org)
    services.soft_delete_document(version.document, actor="op")
    doc = Document.objects.get(pk=version.document_id)
    assert doc.lifecycle_state == DocumentLifecycle.TOMBSTONED
    assert doc.deleted_at is not None
    # Second call is a no-op (no duplicate audit event).
    services.soft_delete_document(doc, actor="op")
    assert AuditEvent.objects.filter(action="documents.document.soft_delete").count() == 1


def test_purge_removes_blobs_and_versions(org: Organization) -> None:
    version = _upload(org)
    key = version.object_key
    removed = services.purge_document(version.document, actor="admin")
    assert removed == 1
    assert not Document.objects.filter(pk=version.document_id).exists()
    assert not DocumentVersion.objects.filter(pk=version.pk).exists()
    with pytest.raises(storage.StorageError):
        storage.get_object_store().get(key)  # blob physically gone
    assert AuditEvent.objects.filter(action="documents.document.purge").exists()


def test_purge_refuses_document_pinned_in_set(org: Organization) -> None:
    version = _upload(org)
    doc_set = services.create_document_set(
        organization=org, logical_id="set-a", name="Set A", actor="op"
    )
    set_version = services.create_document_set_version(document_set=doc_set, actor="op")
    services.add_document_to_set_version(
        set_version=set_version, document_version=version, actor="op"
    )
    services.publish_document_set_version(set_version=set_version, actor="op")
    with pytest.raises(services.DocumentError) as exc:
        services.purge_document(version.document, actor="admin")
    assert exc.value.code == "DOCUMENT_IN_USE"


def test_document_set_lifecycle(org: Organization) -> None:
    version = _upload(org)
    doc_set = services.create_document_set(
        organization=org, logical_id="set-a", name="Set A", actor="op"
    )
    with pytest.raises(services.DocumentError):
        services.create_document_set(organization=org, logical_id="set-a", name="dup", actor="op")
    set_version = services.create_document_set_version(document_set=doc_set, actor="op")
    assert set_version.status == DocumentSetVersionStatus.DRAFT

    # Cannot publish an empty version.
    with pytest.raises(services.DocumentError) as exc:
        services.publish_document_set_version(set_version=set_version, actor="op")
    assert exc.value.code == "SET_VERSION_EMPTY"

    services.add_document_to_set_version(
        set_version=set_version, document_version=version, actor="op"
    )
    published = services.publish_document_set_version(set_version=set_version, actor="op")
    assert published.status == DocumentSetVersionStatus.PROMOTABLE

    # A frozen version rejects new members and re-publish.
    with pytest.raises(services.DocumentError) as exc:
        services.add_document_to_set_version(
            set_version=published, document_version=version, actor="op"
        )
    assert exc.value.code == "SET_VERSION_FROZEN"


def test_add_member_rejects_cross_tenant_document(org: Organization) -> None:
    other = Organization.objects.create(slug="other", name="Other")
    other_version = _upload(other, logical_id="other-doc")
    doc_set = services.create_document_set(
        organization=org, logical_id="set-a", name="Set A", actor="op"
    )
    set_version = services.create_document_set_version(document_set=doc_set, actor="op")
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        services.add_document_to_set_version(
            set_version=set_version, document_version=other_version, actor="op"
        )
