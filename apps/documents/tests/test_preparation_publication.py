"""Publishing an auto-prepared version cannot commit without its durable work."""

from unittest.mock import patch

import pytest
from django.db import transaction

from apps.documents import services
from apps.documents.tests.test_phase_2_8_part_5 import _profiles
from apps.ingestion.models import StagedIndexBuildJob, StagedIndexBuildOutbox
from apps.ingestion.preparation import configure_preparation
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db(transaction=True)


def _draft():
    org = Organization.objects.create(slug="atomic-prepare", name="Atomic preparation")
    embedding, chunking, retrieval = _profiles(org)
    docset = services.create_document_set(
        organization=org, logical_id="kb", name="KB", actor="manager"
    )
    configure_preparation(
        document_set=docset,
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=True,
        actor="manager",
    )
    draft = services.create_document_set_version(document_set=docset, actor="manager")
    services.upload_document(
        organization=org,
        logical_id="policy",
        title="Policy",
        mime_type="text/plain",
        data=b"synthetic policy",
        actor="manager",
        document_set_version=draft,
    )
    return draft, embedding, chunking, retrieval


def test_publication_commits_exact_job_before_broker_delivery():
    draft, embedding, chunking, retrieval = _draft()
    with patch("apps.ingestion.job_lifecycle.dispatch_outbox") as dispatch:
        with transaction.atomic():
            services.publish_document_set_version(set_version=draft, actor="manager")
            job = StagedIndexBuildJob.objects.get(document_set_version=draft)
            assert job.embedding_profile_id == embedding.pk
            assert job.chunking_profile_id == chunking.pk
            assert job.retrieval_profile_id == retrieval.pk
            assert job.status == "dispatch_pending"
            assert StagedIndexBuildOutbox.objects.get(job=job).published_at is None
            dispatch.assert_not_called()
        dispatch.assert_called_once_with(
            limit=1,
            job_public_id=job.public_id,
            organization_id=draft.organization_id,
        )
    draft.refresh_from_db()
    assert draft.status == "promotable"
    assert not job.result_index_version_id


@pytest.mark.parametrize("failure", ["job_audit", "outer_rollback"])
def test_publication_and_preparation_roll_back_together(failure, monkeypatch):
    import apps.ingestion.job_lifecycle as jobs

    draft, *_ = _draft()
    original = jobs.record_event

    def reject_job_audit(**kwargs):
        if kwargs["action"] == "ingestion.staged_index.job_requested":
            raise RuntimeError("synthetic audit failure")
        return original(**kwargs)

    if failure == "job_audit":
        monkeypatch.setattr(jobs, "record_event", reject_job_audit)
    with patch("apps.ingestion.job_lifecycle.dispatch_outbox") as dispatch:
        with pytest.raises(RuntimeError, match="synthetic"):
            with transaction.atomic():
                services.publish_document_set_version(set_version=draft, actor="manager")
                assert StagedIndexBuildJob.objects.filter(document_set_version=draft).exists()
                raise RuntimeError("synthetic outer rollback")
        dispatch.assert_not_called()
    draft.refresh_from_db()
    assert draft.status == "draft"
    assert not StagedIndexBuildJob.objects.exists()
    assert not StagedIndexBuildOutbox.objects.exists()
    assert draft.memberships.count() == 1
