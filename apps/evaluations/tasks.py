"""Celery entry points for bounded Part 6 evaluation runs."""

from __future__ import annotations

from celery import shared_task
from django.db import transaction

from apps.evaluations.models import QuestionEvaluationRun
from apps.evaluations.question_services import execute_question_evaluation
from apps.tenancy.context import set_tenant_context


@shared_task(
    bind=True,
    queue="eval",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=2,
)
def execute_question_evaluation_task(self: object, *, organization_id: int, run_id: int) -> None:
    with transaction.atomic():
        set_tenant_context(organization_id)
        run = (
            QuestionEvaluationRun.objects.select_related(
                "question_set_version",
                "document_set_version__document_set",
                "index_version",
                "retrieval_profile",
                "release__scenario__project",
                "judge_model_profile",
                "judge_prompt_contract",
            )
            .prefetch_related("question_set_version__cases", "case_evidence")
            .get(pk=run_id, organization_id=organization_id)
        )
    execute_question_evaluation(run=run)
