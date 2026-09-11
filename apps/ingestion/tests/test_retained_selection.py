"""New evaluation/selected-set references cannot race retired generation cleanup."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue

import pytest
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.utils import timezone

from apps.documents.models import DocumentSetVersion
from apps.evaluations.models import QuestionEvaluationRun
from apps.evaluations.question_services import (
    QuestionEvaluationError,
    create_question_set,
    create_retrieval_evaluation,
    publish_question_set,
)
from apps.evaluations.tests.test_question_sets import _admin, _cases, _retrieval_target
from apps.ingestion.models import IndexVersion
from apps.ingestion.shared_retention import reclaim_shared_generation
from apps.ingestion.tests.test_shared_retention import _wait_for_blocked
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL reference locks",
    ),
]


@pytest.fixture
def target():
    org = Organization.objects.create(slug="retained-selection", name="Selection")
    user = _admin(org)
    questions = create_question_set(
        organization=org,
        user=user,
        name="Questions",
        description="",
        cases=_cases(),
    )
    version = publish_question_set(
        question_set=questions,
        user=user,
        expected_revision=questions.draft_revision,
    )
    docset, index, profile = _retrieval_target(org, user)
    DocumentSetVersion.objects.filter(pk=docset.pk).update(built_index_version=None)
    IndexVersion.objects.filter(pk=index.pk).update(
        status="promotable",
        storage_layout="shared_v1",
        storage_state="sealed",
        updated_at=timezone.now() - timedelta(days=91),
    )
    index.refresh_from_db()
    return user, version, docset, index, profile


def reclaim(index):
    return reclaim_shared_generation(
        organization_id=index.organization_id,
        index_version_id=index.pk,
        actor="synthetic-owner",
        apply=True,
    )


@pytest.mark.parametrize("kind", ["evaluation", "selected_set"])
@pytest.mark.parametrize("retention_first", [True, False])
def test_reference_and_retention_serialize_both_orders(target, kind, retention_first):
    user, questions, docset, index, profile = target
    backend = Queue()

    def pin():
        if kind == "selected_set":
            DocumentSetVersion.objects.filter(pk=docset.pk).update(built_index_version=index)
        else:
            QuestionEvaluationRun.objects.create(
                organization_id=index.organization_id,
                question_set_version=questions,
                document_set_version=docset,
                index_version=index,
                retrieval_profile=profile,
                kind="retrieval",
                idempotency_key="concurrent",
                created_by=str(user.pk),
            )

    def contender():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend.put(cursor.fetchone()[0])
            with transaction.atomic():
                set_tenant_context(index.organization_id)
                return pin() if retention_first else reclaim(index)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            set_tenant_context(index.organization_id)
            reclaim(index) if retention_first else pin()
            pending = pool.submit(contender)
            _wait_for_blocked(backend.get(timeout=10))
        if retention_first:
            with pytest.raises(DatabaseError, match="GENERATION_SELECTION_UNAVAILABLE"):
                pending.result(timeout=10)
        else:
            assert pending.result(timeout=10).reason == "SHARED_RETENTION_REFERENCED"
    index.refresh_from_db()
    assert index.storage_state == ("retired" if retention_first else "sealed")


def test_retrieval_admission_reloads_stale_ready_generation(target):
    user, questions, docset, index, profile = target
    reclaim(index)
    assert index.store_ready  # Deliberately stale caller object.
    with pytest.raises(QuestionEvaluationError, match="INDEX_VERSION_NOT_EVALUABLE"):
        create_retrieval_evaluation(
            user=user,
            question_set_version=questions,
            document_set_version=docset,
            index_version=index,
            retrieval_profile=profile,
            idempotency_key="stale",
        )
    assert not QuestionEvaluationRun.objects.exists()


def test_selected_reference_cannot_move_to_another_set_version(target):
    user, questions, docset, index, profile = target
    other = DocumentSetVersion.objects.create(
        organization_id=docset.organization_id,
        document_set_id=docset.document_set_id,
        version=docset.version + 1,
    )
    with pytest.raises(DatabaseError, match="GENERATION_SELECTION_SCOPE"), transaction.atomic():
        DocumentSetVersion.objects.filter(pk=other.pk).update(built_index_version=index)
    run = QuestionEvaluationRun.objects.create(
        organization_id=index.organization_id,
        question_set_version=questions,
        document_set_version=docset,
        index_version=index,
        retrieval_profile=profile,
        kind="retrieval",
        idempotency_key="exact-selection",
        created_by=str(user.pk),
    )
    with pytest.raises(DatabaseError, match="GENERATION_SELECTION_SCOPE"), transaction.atomic():
        QuestionEvaluationRun.objects.filter(pk=run.pk).update(document_set_version=other)
    run.refresh_from_db()
    assert run.document_set_version_id == docset.pk
