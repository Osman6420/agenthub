"""Model-level tenant-isolation and integrity invariants."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.documents.models import (
    Document,
    DocumentSet,
    DocumentSetMembership,
    DocumentSetVersion,
    DocumentVersion,
)
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def _org(slug: str) -> Organization:
    return Organization.objects.create(slug=slug, name=slug)


def test_document_version_rejects_cross_tenant_document() -> None:
    org_a, org_b = _org("a"), _org("b")
    doc = Document.objects.create(organization=org_a, logical_id="d1")
    version = DocumentVersion(
        organization=org_b,  # mismatched tenant
        document=doc,
        version=1,
        checksum="x" * 64,
        mime_type="text/plain",
        object_key="tenants/1/documents/z",
    )
    with pytest.raises(ValidationError):
        version.clean()


def test_document_set_version_rejects_cross_tenant_set() -> None:
    org_a, org_b = _org("a"), _org("b")
    doc_set = DocumentSet.objects.create(organization=org_a, logical_id="s1", name="S1")
    version = DocumentSetVersion(organization=org_b, document_set=doc_set, version=1)
    with pytest.raises(ValidationError):
        version.clean()


def test_membership_rejects_cross_tenant_document_version() -> None:
    org_a, org_b = _org("a"), _org("b")
    doc_set = DocumentSet.objects.create(organization=org_a, logical_id="s1", name="S1")
    set_version = DocumentSetVersion.objects.create(
        organization=org_a, document_set=doc_set, version=1
    )
    # A document version owned by a *different* tenant must never be pinnable.
    other_doc = Document.objects.create(organization=org_b, logical_id="d1")
    other_version = DocumentVersion.objects.create(
        organization=org_b,
        document=other_doc,
        version=1,
        checksum="y" * 64,
        mime_type="text/plain",
        object_key="tenants/2/documents/z",
    )
    membership = DocumentSetMembership(
        organization=org_a, document_set_version=set_version, document_version=other_version
    )
    with pytest.raises(ValidationError):
        membership.clean()


def test_object_key_is_globally_unique() -> None:
    from django.db import IntegrityError

    org = _org("a")
    doc = Document.objects.create(organization=org, logical_id="d1")
    DocumentVersion.objects.create(
        organization=org,
        document=doc,
        version=1,
        checksum="a" * 64,
        mime_type="text/plain",
        object_key="tenants/1/documents/dup",
    )
    with pytest.raises(IntegrityError):
        DocumentVersion.objects.create(
            organization=org,
            document=doc,
            version=2,
            checksum="b" * 64,
            mime_type="text/plain",
            object_key="tenants/1/documents/dup",
        )
