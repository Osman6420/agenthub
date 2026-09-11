"""Pointer-flip promotion / rollback of a staged index version (P4.4, metadata-only)."""

from __future__ import annotations

from io import StringIO
from threading import Barrier, Thread

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet, DocumentSetVersion, DocumentSetVersionStatus
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
)
from apps.ingestion import staged_build
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.ingestion.staged_build import (
    StagedBuildError,
    active_releases_pinning_document_set_version,
    promote_staged_index,
    rollback_staged_index,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership

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
    dsv.refresh_from_db()
    assert dsv.status == DocumentSetVersionStatus.ACTIVE
    assert dsv.built_index_version_id == iv1.pk
    assert AuditEvent.objects.filter(action="ingestion.staged_index.promoted").exists()

    iv2 = _index(org, dsv, 2)
    promote_staged_index(iv2, actor="op")
    iv1.refresh_from_db()
    iv2.refresh_from_db()
    assert iv1.status == IndexStatus.SUPERSEDED  # pointer moved off the old index
    assert iv2.status == IndexStatus.ACTIVE
    dsv.refresh_from_db()
    assert dsv.built_index_version_id == iv2.pk
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
    dsv.refresh_from_db()
    assert dsv.status == DocumentSetVersionStatus.ACTIVE
    assert dsv.built_index_version_id == iv1.pk
    assert AuditEvent.objects.filter(action="ingestion.staged_index.rolled_back").exists()


@pytest.mark.django_db
def test_promotion_atomically_supersedes_prior_served_set_version() -> None:
    org, first = _setup()
    first_index = _index(org, first, 1)
    promote_staged_index(first_index, actor="op")
    second = DocumentSetVersion.objects.create(
        organization=org,
        document_set=first.document_set,
        version=2,
        status=DocumentSetVersionStatus.PROMOTABLE,
    )
    second_index = _index(org, second, 1)

    promote_staged_index(second_index, actor="op")

    first.refresh_from_db()
    first_index.refresh_from_db()
    second.refresh_from_db()
    second_index.refresh_from_db()
    assert first.status == DocumentSetVersionStatus.SUPERSEDED
    assert first_index.status == IndexStatus.SUPERSEDED
    assert second.status == DocumentSetVersionStatus.ACTIVE
    assert second.built_index_version_id == second_index.pk
    assert second_index.status == IndexStatus.ACTIVE

    rollback_staged_index(first_index, actor="op")
    first.refresh_from_db()
    first_index.refresh_from_db()
    second.refresh_from_db()
    second_index.refresh_from_db()
    assert first.status == DocumentSetVersionStatus.ACTIVE
    assert first.built_index_version_id == first_index.pk
    assert first_index.status == IndexStatus.ACTIVE
    assert second.status == DocumentSetVersionStatus.SUPERSEDED
    assert second_index.status == IndexStatus.SUPERSEDED


@pytest.mark.django_db
def test_exact_served_pair_retry_is_idempotent() -> None:
    org, dsv = _setup()
    index = _index(org, dsv, 1)
    promote_staged_index(index, actor="op", request_id="first")

    replay = promote_staged_index(index, actor="op", request_id="replay")

    assert replay.pk == index.pk
    assert AuditEvent.objects.filter(
        action="ingestion.staged_index.promoted",
        reason="ALREADY_SERVED",
        request_id="replay",
    ).exists()


@pytest.mark.django_db
def test_audit_failure_rolls_back_entire_served_pointer_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, first = _setup()
    first_index = _index(org, first, 1)
    promote_staged_index(first_index, actor="op")
    second = DocumentSetVersion.objects.create(
        organization=org,
        document_set=first.document_set,
        version=2,
        status=DocumentSetVersionStatus.PROMOTABLE,
    )
    second_index = _index(org, second, 1)

    def fail_audit(**_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(staged_build, "record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        promote_staged_index(second_index, actor="op")

    first.refresh_from_db()
    first_index.refresh_from_db()
    second.refresh_from_db()
    second_index.refresh_from_db()
    assert first.status == DocumentSetVersionStatus.ACTIVE
    assert first.built_index_version_id == first_index.pk
    assert first_index.status == IndexStatus.ACTIVE
    assert second.status == DocumentSetVersionStatus.PROMOTABLE
    assert second.built_index_version_id is None
    assert second_index.status == IndexStatus.PROMOTABLE


def _active_release(org: Organization, document_set_version_id: int) -> ScenarioRelease:
    project = AIProject.objects.create(organization=org, slug="p", name="P")
    scenario = Scenario.objects.create(organization=org, project=project, slug="s", name="S")
    return ScenarioRelease.objects.create(
        organization=org,
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="1",
        manifest={"document_set_versions": [document_set_version_id]},
        artifact_manifest_sha256="0" * 64,
        created_by="op",
    )


def test_promote_blocks_when_an_active_release_still_pins_the_superseded_version() -> None:
    """BUG-010: a routine "update the document" promote must not silently ungroun a live
    scenario -- the operator must see and confirm the impact first."""
    org, first = _setup()
    first_index = _index(org, first, 1)
    promote_staged_index(first_index, actor="op")
    release = _active_release(org, first.pk)
    second = DocumentSetVersion.objects.create(
        organization=org,
        document_set=first.document_set,
        version=2,
        status=DocumentSetVersionStatus.PROMOTABLE,
    )
    second_index = _index(org, second, 1)

    assert active_releases_pinning_document_set_version(
        organization_id=org.pk, document_set_version_id=first.pk
    ) == [release]

    with pytest.raises(StagedBuildError, match="ACTIVE_RELEASES_AFFECTED"):
        promote_staged_index(second_index, actor="op")

    first.refresh_from_db()
    first_index.refresh_from_db()
    assert first.status == DocumentSetVersionStatus.ACTIVE
    assert first_index.status == IndexStatus.ACTIVE
    assert AuditEvent.objects.filter(
        action="ingestion.staged_index.promoted",
        outcome="failure",
        reason="ACTIVE_RELEASES_AFFECTED",
    ).exists()

    promote_staged_index(second_index, actor="op", confirm_active_release_impact=True)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == DocumentSetVersionStatus.SUPERSEDED
    assert second.status == DocumentSetVersionStatus.ACTIVE


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


@pytest.mark.django_db
def test_management_command_requires_exact_document_set_manager() -> None:
    org, dsv = _setup()
    index = _index(org, dsv, 1)
    user = get_user_model().objects.create_user("operator", password="unused")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)

    with pytest.raises(CommandError, match="not authorized"):
        call_command(
            "promote_staged_index",
            actor=user.get_username(),
            index_version=index.pk,
            stdout=StringIO(),
        )
    assert AuditEvent.objects.filter(
        action="ingestion.staged_index.promoted",
        outcome="deny",
        reason="DOCUMENT_SET_OPERATIONS_AUTHORITY_REQUIRED",
    ).exists()
    DocumentSetResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        document_set=dsv.document_set,
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=user,
    )

    call_command(
        "promote_staged_index",
        actor=user.get_username(),
        index_version=index.pk,
        stdout=StringIO(),
    )
    dsv.refresh_from_db()
    index.refresh_from_db()
    assert dsv.status == DocumentSetVersionStatus.ACTIVE
    assert dsv.built_index_version_id == index.pk
    assert index.status == IndexStatus.ACTIVE


@pytest.mark.django_db
def test_database_rejects_duplicate_active_served_metadata() -> None:
    org, first = _setup()
    first_index = _index(org, first, 1)
    promote_staged_index(first_index, actor="op")
    second = DocumentSetVersion.objects.create(
        organization=org,
        document_set=first.document_set,
        version=2,
        status=DocumentSetVersionStatus.PROMOTABLE,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            second.status = DocumentSetVersionStatus.ACTIVE
            second.save(update_fields=["status", "updated_at"])

    other_index = _index(org, first, 2)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            other_index.status = IndexStatus.ACTIVE
            other_index.save(update_fields=["status", "updated_at"])


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row locking requires PostgreSQL")
@pytest.mark.django_db(transaction=True)
def test_concurrent_promotions_serialize_to_one_coherent_served_pair() -> None:
    org, first = _setup()
    second = DocumentSetVersion.objects.create(
        organization=org,
        document_set=first.document_set,
        version=2,
        status=DocumentSetVersionStatus.PROMOTABLE,
    )
    candidates = [_index(org, first, 1), _index(org, second, 1)]
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def attempt(candidate_pk: int) -> None:
        close_old_connections()
        try:
            barrier.wait()
            promote_staged_index(IndexVersion.objects.get(pk=candidate_pk), actor="concurrent-op")
        except BaseException as exc:  # pragma: no cover - asserted by parent thread
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=attempt, args=(candidate.pk,)) for candidate in candidates]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    served_version = DocumentSetVersion.objects.get(
        document_set=first.document_set,
        status=DocumentSetVersionStatus.ACTIVE,
    )
    served_index = IndexVersion.objects.get(
        document_set_version__document_set=first.document_set,
        status=IndexStatus.ACTIVE,
    )
    assert served_version.built_index_version_id == served_index.pk
    assert served_index.document_set_version_id == served_version.pk
