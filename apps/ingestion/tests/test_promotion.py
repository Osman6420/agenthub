"""Pointer-flip promotion / rollback of a staged index version (P4.4, metadata-only)."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.documents.models import DocumentSet, DocumentSetVersion, DocumentSetVersionStatus
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.ingestion.staged_build import (
    StagedBuildError,
    promote_staged_index,
    rollback_staged_index,
)
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def _setup() -> tuple[Organization, DocumentSetVersion]:
    org = Organization.objects.create(slug="o", name="O")
    doc_set = DocumentSet.objects.create(organization=org, logical_id="kb", name="KB")
    dsv = DocumentSetVersion.objects.create(
        organization=org,
        document_set=doc_set,
        version=1,
        status=DocumentSetVersionStatus.PROMOTABLE,
    )
    return org, dsv


def _index(org: Organization, dsv: DocumentSetVersion, version: int) -> IndexVersion:
    return IndexVersion.objects.create(
        organization=org,
        document_set_version=dsv,
        dimensions=64,
        index_type="vector",
        version=version,
        status=IndexStatus.PROMOTABLE,
        store_ready=True,
    )


def test_promote_flips_pointer_and_supersedes_previous() -> None:
    org, dsv = _setup()
    iv1 = _index(org, dsv, 1)
    promoted = promote_staged_index(iv1, actor="op")
    assert promoted.status == IndexStatus.ACTIVE
    assert AuditEvent.objects.filter(action="ingestion.staged_index.promoted").exists()

    iv2 = _index(org, dsv, 2)
    promote_staged_index(iv2, actor="op")
    iv1.refresh_from_db()
    iv2.refresh_from_db()
    assert iv1.status == IndexStatus.SUPERSEDED  # pointer moved off the old index
    assert iv2.status == IndexStatus.ACTIVE
    # Single active per document-set version.
    assert (
        IndexVersion.objects.filter(document_set_version=dsv, status=IndexStatus.ACTIVE).count()
        == 1
    )


def test_rollback_restores_superseded_index() -> None:
    org, dsv = _setup()
    iv1 = _index(org, dsv, 1)
    promote_staged_index(iv1, actor="op")
    iv2 = _index(org, dsv, 2)
    promote_staged_index(iv2, actor="op")  # iv1 -> superseded, iv2 -> active

    iv1.refresh_from_db()
    rollback_staged_index(iv1, actor="op")
    iv1.refresh_from_db()
    iv2.refresh_from_db()
    assert iv1.status == IndexStatus.ACTIVE
    assert iv2.status == IndexStatus.SUPERSEDED
    assert AuditEvent.objects.filter(action="ingestion.staged_index.rolled_back").exists()


def test_promote_rejects_non_promotable() -> None:
    org, dsv = _setup()
    iv = _index(org, dsv, 1)
    iv.status = IndexStatus.BUILDING
    iv.save(update_fields=["status"])
    with pytest.raises(StagedBuildError, match="INDEX_NOT_PROMOTABLE"):
        promote_staged_index(iv, actor="op")


def test_rollback_rejects_non_superseded() -> None:
    org, dsv = _setup()
    iv = _index(org, dsv, 1)
    with pytest.raises(StagedBuildError, match="INDEX_NOT_ROLLBACKABLE"):
        rollback_staged_index(iv, actor="op")
