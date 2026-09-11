"""Real persistence evidence for cancellation/retry and late-worker fencing."""

from threading import Event, Thread

import pytest
from django.db import DatabaseError, close_old_connections, connection, transaction

from apps.ingestion.job_lifecycle import (
    BuildJobError,
    cancel_build_job,
    claim_build_job,
    complete_build_job,
    create_build_job,
    fail_build_job,
    retry_build_job,
    update_progress,
)
from apps.ingestion.models import IndexVersion, SharedVectorChunk
from apps.ingestion.staged_build import promote_staged_index
from apps.ingestion.tests.test_job_lifecycle import lineage as lineage
from apps.ingestion.vector_store import VectorRow, VectorStoreError, write_chunks

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="generation fence requires PostgreSQL"
    ),
]


def _claimed(lineage):
    org, version, profile = lineage
    job, _ = create_build_job(
        document_set_version=version,
        embedding_profile=profile,
        ocr_profile=None,
        actor="synthetic",
    )
    claimed = claim_build_job(public_id=str(job.public_id), organization_id=org.pk)
    assert claimed is not None
    return claimed


def _generation(job, version, layout="shared_v1"):
    return IndexVersion.objects.create(
        organization_id=job.organization_id,
        document_set_version=job.document_set_version,
        embedding_profile=job.embedding_profile,
        dimensions=64,
        index_type="vector",
        pipeline_fingerprint=job.pipeline_fingerprint,
        version=version,
        storage_layout=layout,
        storage_state="open",
        build_request=job,
        build_attempt=job.attempt,
    )


def _row(index, ordinal=0):
    return VectorRow(
        index.organization_id,
        index.document_set_version.memberships.get().document_version_id,
        ordinal,
        "synthetic attempt",
        [1.0] + [0.0] * 63,
    )


def test_old_worker_cannot_write_or_finish_a_cancelled_retried_attempt(lineage):
    first_claim = _claimed(lineage)
    first = _generation(first_claim, 1)
    write_chunks(first, [_row(first)])
    update_progress(
        job_id=first_claim.pk,
        organization_id=first_claim.organization_id,
        expected_attempt=first_claim.attempt,
        documents=1,
        chunks=1,
    )
    cancel_build_job(job=first_claim, actor="synthetic")
    retried = retry_build_job(job=first_claim, actor="synthetic")
    # An old failure is also fenced in the window before the retry is claimed.
    fail_build_job(
        job_id=first_claim.pk,
        organization_id=first_claim.organization_id,
        expected_attempt=first_claim.attempt,
        error_code="OLD_ERROR",
        ambiguous=False,
    )
    retried.refresh_from_db()
    assert retried.status == "dispatch_pending"
    second_claim = claim_build_job(
        public_id=str(retried.public_id), organization_id=retried.organization_id
    )
    assert second_claim is not None
    assert second_claim.attempt == 2 and second_claim.chunks_completed == 0
    second = _generation(second_claim, 2)
    with pytest.raises(BuildJobError, match="BUILD_ATTEMPT_FENCED"):
        update_progress(
            job_id=first_claim.pk,
            organization_id=first_claim.organization_id,
            expected_attempt=first_claim.attempt,
            documents=2,
            chunks=2,
        )
    with pytest.raises(VectorStoreError, match="BUILD_GENERATION_FENCED"):
        write_chunks(first, [_row(first, 1)])
    with pytest.raises(DatabaseError, match="BUILD_GENERATION_FENCED"), transaction.atomic():
        SharedVectorChunk.objects.create(
            organization_id=first.organization_id,
            index_version=first,
            document_version_id=_row(first).document_version_id,
            ordinal=1,
            text="late direct insert",
            embedding=[1.0] * 64,
            dimensions=64,
            representation="vector",
        )
    with pytest.raises(DatabaseError, match="BUILD_GENERATION_FENCED"), transaction.atomic():
        IndexVersion.objects.filter(pk=first.pk).update(storage_state="sealed")
    with pytest.raises(DatabaseError, match="BUILD_ATTEMPT_IMMUTABLE"), transaction.atomic():
        IndexVersion.objects.filter(pk=first.pk).update(build_attempt=2)
    complete_build_job(
        job_id=first_claim.pk,
        organization_id=first_claim.organization_id,
        expected_attempt=first_claim.attempt,
        index=first,
    )
    fail_build_job(
        job_id=first_claim.pk,
        organization_id=first_claim.organization_id,
        expected_attempt=first_claim.attempt,
        error_code="OLD_ERROR",
        ambiguous=True,
    )
    second_claim.refresh_from_db()
    assert second_claim.status == "running" and second_claim.result_index_version_id is None
    write_chunks(second, [_row(second)])
    second.storage_state = "sealed"
    second.status = "promotable"
    second.store_ready = True
    second.chunk_count = second.document_count = 1
    second.save(
        update_fields=["storage_state", "status", "store_ready", "chunk_count", "document_count"]
    )
    complete_build_job(
        job_id=second_claim.pk,
        organization_id=second_claim.organization_id,
        expected_attempt=second_claim.attempt,
        index=second,
    )
    second_claim.refresh_from_db()
    assert second_claim.status == "succeeded" and second_claim.result_index_version_id == second.pk
    promote_staged_index(second, actor="synthetic")
    assert SharedVectorChunk.objects.filter(index_version=first).count() == 1


def test_unknown_provider_outcome_cannot_be_reclaimed_by_duplicate_delivery(lineage):
    job = _claimed(lineage)
    fail_build_job(
        job_id=job.pk,
        organization_id=job.organization_id,
        expected_attempt=job.attempt,
        error_code="PROVIDER_OUTCOME_UNKNOWN",
        ambiguous=True,
    )
    assert (
        claim_build_job(public_id=str(job.public_id), organization_id=job.organization_id) is None
    )
    job.refresh_from_db()
    assert job.status == "reconciliation_required" and job.attempt == 1


def test_owner_backfill_cannot_certify_an_unsuccessful_bound_job(lineage):
    from apps.ingestion.shared_backfill import backfill_generation
    from apps.ingestion.vector_store import provision_store

    job = _claimed(lineage)
    index = _generation(job, 1, layout="legacy")
    provision_store(index)
    index.status = "promotable"
    index.store_ready = True
    index.save(update_fields=["status", "store_ready"])
    fail_build_job(
        job_id=job.pk,
        organization_id=job.organization_id,
        expected_attempt=job.attempt,
        error_code="PROVIDER_FAILED",
        ambiguous=False,
    )
    with pytest.raises(VectorStoreError, match="SHARED_BACKFILL_REJECTED"):
        backfill_generation(
            index_version_id=index.pk,
            organization_id=index.organization_id,
            actor="synthetic-owner",
            apply=True,
        )
    index.refresh_from_db()
    assert index.storage_layout == "legacy"


@pytest.mark.django_db(transaction=True)
def test_cancel_serializes_after_inflight_write_then_blocks_late_writes(lineage):
    job = _claimed(lineage)
    index = _generation(job, 1)
    row = _row(index)
    written, release, cancelled = Event(), Event(), Event()
    errors = []

    def writer():
        close_old_connections()
        try:
            with transaction.atomic():
                write_chunks(index, [row])
                written.set()
                assert release.wait(10)
        except Exception as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    def canceller():
        close_old_connections()
        try:
            cancel_build_job(job=job, actor="synthetic")
            cancelled.set()
        except Exception as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    write_thread = Thread(target=writer)
    cancel_thread = Thread(target=canceller)
    write_thread.start()
    try:
        assert written.wait(10)
        cancel_thread.start()
        assert not cancelled.wait(0.1)
    finally:
        release.set()
        write_thread.join(10)
        if cancel_thread.ident is not None:
            cancel_thread.join(10)
    assert not errors and cancelled.is_set()
    assert not write_thread.is_alive() and not cancel_thread.is_alive()
    with pytest.raises(VectorStoreError, match="BUILD_GENERATION_FENCED"):
        write_chunks(index, [_row(index, 1)])
