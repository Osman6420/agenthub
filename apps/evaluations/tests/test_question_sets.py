from __future__ import annotations

import hashlib
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.documents import services as document_services
from apps.documents.models import DocumentSetVersionStatus
from apps.evaluations.models import (
    QuestionEvaluationStatus,
    QuestionSetVersion,
)
from apps.evaluations.question_services import (
    QuestionEvaluationError,
    ask_document_set_once,
    create_answer_evaluation,
    create_question_set,
    create_retrieval_evaluation,
    evaluate_answer_assertions,
    execute_question_evaluation,
    normalize_cases,
    publish_question_set,
    purge_expired_question_evidence,
    request_evaluation_cancellation,
    score_retrieval,
    update_question_set_draft,
)
from apps.identity.models import DocumentSetManagerAssignment
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.observability.metrics import render_metrics
from apps.orchestration.providers import ModelResponse
from apps.releases.compiler import ArtifactRef, compile_release
from apps.retrieval.providers import StaticRetrievalProvider
from apps.retrieval.types import RetrievedChunk
from apps.tenancy.models import Organization, OrganizationMembership, Role

pytestmark = pytest.mark.django_db


def _admin(organization: Organization, username: str = "admin"):
    user = get_user_model().objects.create_user(
        username=username,
        password="test-password",  # noqa: S106
    )
    OrganizationMembership.objects.create(
        organization=organization,
        user=user,
        role=Role.ORGANIZATION_ADMIN,
    )
    return user


def _cases(*, with_anchor: bool = True) -> list[dict[str, object]]:
    anchors: list[dict[str, object]] = (
        [{"document_version_id": 77, "ordinal": 2}] if with_anchor else []
    )
    return [
        {
            "id": "refund-1",
            "question": "İade süresi nedir?",
            "input": {"question": "İade süresi nedir?"},
            "assertions": [{"type": "normalized_contains", "value": "14 gün"}],
            "expected_anchors": anchors,
        }
    ]


def _retrieval_target(organization: Organization, user):
    document_set = document_services.create_document_set(
        organization=organization,
        logical_id="policy",
        name="Policy",
        actor="admin",
    )
    DocumentSetManagerAssignment.objects.create(
        organization=organization,
        document_set=document_set,
        user=user,
        assigned_by=user,
    )
    set_version = document_services.create_document_set_version(
        document_set=document_set, actor="admin"
    )
    set_version.status = DocumentSetVersionStatus.ACTIVE
    set_version.save(update_fields=["status", "updated_at"])
    profile = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.RETRIEVAL_PROFILE,
        logical_id="evaluate",
        body={
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "hybrid",
            "top_k": 5,
            "score_threshold": 0.0,
            "vector_weight": 0.5,
            "keyword_weight": 0.5,
        },
        created_by="admin",
    )
    index = IndexVersion.objects.create(
        organization=organization,
        document_set_version=set_version,
        retrieval_profile=profile,
        version=1,
        status=IndexStatus.ACTIVE,
        store_ready=True,
        dimensions=64,
        index_type="vector",
    )
    set_version.built_index_version = index
    set_version.save(update_fields=["built_index_version", "updated_at"])
    return set_version, index, profile


def _release(organization: Organization):
    project = AIProject.objects.create(organization=organization, slug="eval", name="Eval")
    scenario = Scenario.objects.create(project=project, slug="answer", name="Answer")
    create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="answer_workflow",
        body={
            "api_version": "agenthub/v1",
            "kind": "Workflow",
            "metadata": {"id": "answer.v1"},
            "spec": {
                "input_node": "request",
                "nodes": [
                    {"id": "request", "type": "input"},
                    {
                        "id": "answer",
                        "type": "format_output",
                        "config": {"template_ref": "14 gün"},
                    },
                    {"id": "done", "type": "end"},
                ],
                "edges": [
                    {"from": "request", "to": "answer"},
                    {"from": "answer", "to": "done"},
                ],
            },
        },
        created_by="admin",
    )
    return compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                "workflow_definition",
                ArtifactType.WORKFLOW_DEFINITION,
                "answer_workflow",
                1,
            )
        ],
        runtime_version="rt:3.0.0",
        created_by="admin",
    )


def test_normalize_cases_rejects_duplicate_ids_and_unbounded_assertions() -> None:
    cases = _cases()
    cases.append(dict(cases[0]))
    with pytest.raises(QuestionEvaluationError, match="QUESTION_CASE_ID_INVALID"):
        normalize_cases(cases)
    invalid = _cases()
    invalid[0]["assertions"] = [{"type": "regex", "value": ".*"}]
    with pytest.raises(QuestionEvaluationError, match="QUESTION_ASSERTION_INVALID"):
        normalize_cases(invalid)


def test_question_set_publish_is_immutable_and_optimistically_locked() -> None:
    organization = Organization.objects.create(slug="questions", name="Questions")
    user = _admin(organization)
    question_set = create_question_set(
        organization=organization,
        user=user,
        name="Refund benchmark",
        description="Published exact questions",
        cases=_cases(),
    )
    version = publish_question_set(
        question_set=question_set,
        user=user,
        expected_revision=question_set.draft_revision,
    )
    assert version.version == 1
    assert version.case_count == 1
    assert version.cases.get().question == "İade süresi nedir?"
    with pytest.raises(ValidationError, match="immutable"):
        version.save()
    with pytest.raises(QuestionEvaluationError, match="QUESTION_SET_REVISION_CONFLICT"):
        update_question_set_draft(
            question_set=question_set,
            user=user,
            expected_revision=999,
            name=question_set.name,
            description=question_set.description,
            cases=_cases(),
        )
    assert (
        publish_question_set(
            question_set=question_set,
            user=user,
            expected_revision=question_set.draft_revision,
        ).pk
        == version.pk
    )


def test_score_retrieval_uses_explicit_denominators_and_passage_checksum() -> None:
    text = "Ürün tesliminden itibaren 14 gün."
    checksum = hashlib.sha256("ürün tesliminden itibaren 14 gün.".encode()).hexdigest()
    chunks = [
        RetrievedChunk(
            text=text,
            source_id="docset-version:1",
            source_uri="refund",
            document_version_id=77,
            document_set_version_id=1,
            index_version_id=9,
            ordinal=2,
            score=0.9,
            vector_score=0.8,
            keyword_score=0.7,
            fused_score=0.9,
        )
    ]
    scores, evidence = score_retrieval(
        [{"document_version_id": 77, "ordinal": 2, "passage_checksum": checksum}],
        chunks,
    )
    assert scores == {
        "hit": 1,
        "recall": 1.0,
        "reciprocal_rank": 1.0,
        "anchor_count": 1,
    }
    assert evidence[0]["matched"] is True
    assert "text" not in evidence[0]
    unscored, _ = score_retrieval([], chunks)
    assert unscored["hit"] is None


def test_retrieval_evaluation_is_idempotent_and_keeps_metrics_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization.objects.create(slug="eval", name="Eval")
    user = _admin(organization)
    question_set = create_question_set(
        organization=organization,
        user=user,
        name="Retrieval",
        description="",
        cases=_cases(),
    )
    version = publish_question_set(
        question_set=question_set,
        user=user,
        expected_revision=question_set.draft_revision,
    )
    set_version, index, profile = _retrieval_target(organization, user)
    chunk = RetrievedChunk(
        text="İade süresi 14 gündür.",
        source_id=f"docset-version:{set_version.pk}",
        source_uri="refund",
        document_version_id=77,
        document_set_version_id=set_version.pk,
        index_version_id=index.pk,
        ordinal=2,
        score=0.9,
    )
    monkeypatch.setattr(
        "apps.evaluations.question_services.get_retrieval_provider",
        lambda: StaticRetrievalProvider([chunk]),
    )
    run, created = create_retrieval_evaluation(
        user=user,
        question_set_version=version,
        document_set_version=set_version,
        index_version=index,
        retrieval_profile=profile,
        idempotency_key="retrieval-1",
    )
    duplicate, duplicate_created = create_retrieval_evaluation(
        user=user,
        question_set_version=version,
        document_set_version=set_version,
        index_version=index,
        retrieval_profile=profile,
        idempotency_key="retrieval-1",
    )
    assert created is True
    assert duplicate_created is False
    assert duplicate.pk == run.pk
    execute_question_evaluation(run=run)
    run.refresh_from_db()
    assert run.status == QuestionEvaluationStatus.COMPLETED
    assert run.metrics["hit_at_k"] == 1.0
    assert run.metrics["recall_at_k"] == 1.0
    assert run.metrics["mrr"] == 1.0
    assert run.metrics["retrieval_denominator"] == 1
    assert run.case_evidence.get().retrieval_evidence[0]["matched"] is True
    rendered = render_metrics().decode()
    assert "agenthub_question_eval_cases_total" in rendered
    assert "agenthub_question_eval_runs_total" in rendered
    assert "İade süresi" not in rendered
    run.retention_until = timezone.now()
    run.save(update_fields=["retention_until", "updated_at"])
    assert purge_expired_question_evidence(organization=organization, actor="retention-worker") == 1
    evidence = run.case_evidence.get()
    assert evidence.retrieval_evidence == []


def test_cross_tenant_question_set_version_is_rejected_without_disclosure() -> None:
    organization = Organization.objects.create(slug="first", name="First")
    other = Organization.objects.create(slug="second", name="Second")
    user = _admin(organization)
    other_user = _admin(other, "other-admin")
    question_set = create_question_set(
        organization=other,
        user=other_user,
        name="Foreign",
        description="",
        cases=_cases(),
    )
    version: QuestionSetVersion = publish_question_set(
        question_set=question_set,
        user=other_user,
        expected_revision=question_set.draft_revision,
    )
    set_version, index, profile = _retrieval_target(organization, user)
    with pytest.raises(QuestionEvaluationError, match="QUESTION_SET_VERSION_NOT_FOUND"):
        create_retrieval_evaluation(
            user=user,
            question_set_version=version,
            document_set_version=set_version,
            index_version=index,
            retrieval_profile=profile,
            idempotency_key="foreign",
        )


def test_one_off_retrieval_never_mutates_question_or_aggregate_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization.objects.create(slug="one-off", name="One Off")
    user = _admin(organization)
    set_version, index, profile = _retrieval_target(organization, user)
    monkeypatch.setattr(
        "apps.evaluations.question_services.get_retrieval_provider",
        lambda: StaticRetrievalProvider(
            [
                RetrievedChunk(
                    text="Private answer",
                    source_id="source",
                    source_uri="policy",
                    document_version_id=1,
                    ordinal=0,
                )
            ]
        ),
    )
    result = ask_document_set_once(
        user=user,
        document_set_version=set_version,
        index_version=index,
        retrieval_profile=profile,
        question="What is the policy?",
    )
    assert result.chunks[0].text == "Private answer"
    assert QuestionSetVersion.objects.count() == 0
    assert set_version.question_evaluation_runs.count() == 0


def test_cancellation_is_authorized_and_stops_before_case_execution() -> None:
    organization = Organization.objects.create(slug="cancel", name="Cancel")
    user = _admin(organization)
    question_set = create_question_set(
        organization=organization,
        user=user,
        name="Cancelled benchmark",
        description="",
        cases=_cases(),
    )
    version = publish_question_set(
        question_set=question_set,
        user=user,
        expected_revision=question_set.draft_revision,
    )
    set_version, index, profile = _retrieval_target(organization, user)
    run, _ = create_retrieval_evaluation(
        user=user,
        question_set_version=version,
        document_set_version=set_version,
        index_version=index,
        retrieval_profile=profile,
        idempotency_key="cancel-before-start",
    )
    request_evaluation_cancellation(run=run, user=user)
    run.refresh_from_db()
    execute_question_evaluation(run=run)
    run.refresh_from_db()
    assert run.status == QuestionEvaluationStatus.CANCELLED
    assert run.completed_cases == 0
    assert not run.case_evidence.exists()


def test_answer_evaluation_pins_release_and_keeps_answer_metrics_independent() -> None:
    organization = Organization.objects.create(slug="answer-eval", name="Answer Eval")
    user = _admin(organization)
    question_set = create_question_set(
        organization=organization,
        user=user,
        name="Answer quality",
        description="",
        cases=_cases(with_anchor=False),
    )
    version = publish_question_set(
        question_set=question_set,
        user=user,
        expected_revision=question_set.draft_revision,
    )
    release = _release(organization)
    run, created = create_answer_evaluation(
        user=user,
        question_set_version=version,
        release=release,
        idempotency_key="answer-1",
    )
    assert created is True
    assert run.provenance["release_manifest_checksum"] == release.artifact_manifest_sha256
    execute_question_evaluation(run=run)
    run.refresh_from_db()
    assert run.status == QuestionEvaluationStatus.COMPLETED
    assert run.metrics["answer_denominator"] == 1
    assert run.metrics["answer_pass_rate"] == 1.0
    assert "hit_at_k" not in run.metrics
    assert run.case_evidence.get().generated_answer == "14 gün"


def test_output_schema_and_citation_assertions_are_closed_and_deterministic() -> None:
    outcomes = evaluate_answer_assertions(
        [
            {"type": "exact", "value": "14 GÜN"},
            {"type": "citation_source", "value": "policy"},
            {
                "type": "output_schema",
                "schema": {
                    "type": "object",
                    "required": ["answer", "sources"],
                    "additionalProperties": True,
                },
            },
        ],
        {
            "answer": "14 gün",
            "sources": [{"source_uri": "policy"}],
        },
    )
    assert [item["passed"] for item in outcomes] == [True, True, True]


def test_pinned_judge_success_and_malformed_output_have_explicit_states(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    organization = Organization.objects.create(slug="judge", name="Judge")
    user = _admin(organization)
    cases = _cases(with_anchor=False)
    cases[0]["judge"] = {"enabled": True, "required": True}
    question_set = create_question_set(
        organization=organization,
        user=user,
        name="Judged answers",
        description="",
        cases=cases,
    )
    version = publish_question_set(
        question_set=question_set,
        user=user,
        expected_revision=question_set.draft_revision,
    )
    release = _release(organization)
    model = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.MODEL_PROFILE,
        logical_id="judge-model",
        body={"profile_id": str(uuid.uuid4())},
        created_by="admin",
    )
    prompt = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        logical_id="judge-prompt",
        body={"template": "Return strict JSON with verdict pass or fail."},
        created_by="admin",
    )
    settings.EVALUATION_LLM_JUDGE_ENABLED = True

    class _Provider:
        text = '{"verdict":"pass"}'

        def generate(self, **_: object) -> ModelResponse:
            return ModelResponse(text=self.text)

    provider = _Provider()
    monkeypatch.setattr("apps.evaluations.question_services.get_model_provider", lambda: provider)
    passing, _ = create_answer_evaluation(
        user=user,
        question_set_version=version,
        release=release,
        judge_model_profile=model,
        judge_prompt_contract=prompt,
        idempotency_key="judge-pass",
    )
    execute_question_evaluation(run=passing)
    assert passing.case_evidence.get().judge["verdict"] == "pass"

    provider.text = "not-json"
    malformed, _ = create_answer_evaluation(
        user=user,
        question_set_version=version,
        release=release,
        judge_model_profile=model,
        judge_prompt_contract=prompt,
        idempotency_key="judge-malformed",
    )
    execute_question_evaluation(run=malformed)
    evidence = malformed.case_evidence.get()
    assert evidence.status == "unscored"
    assert evidence.judge == {
        "status": "unscored",
        "reason_code": "JUDGE_PROVIDER_FAILED",
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_part6_tables_force_rls_and_isolate_non_owner_reads() -> None:
    organizations = [
        Organization.objects.create(slug=f"part6-{suffix}", name=f"Part 6 {suffix}")
        for suffix in ("a", "b")
    ]
    for index, organization in enumerate(organizations):
        user = _admin(organization, f"rls-admin-{index}")
        question_set = create_question_set(
            organization=organization,
            user=user,
            name="RLS benchmark",
            description="",
            cases=_cases(),
        )
        publish_question_set(
            question_set=question_set,
            user=user,
            expected_revision=question_set.draft_revision,
        )
    role = f"part6_rls_{uuid.uuid4().hex[:12]}"
    tables = (
        "evaluations_evalrun",
        "evaluations_evalcaseresult",
        "evaluations_questionset",
        "evaluations_questionsetversion",
        "evaluations_questioncase",
        "evaluations_questionevaluationrun",
        "evaluations_questionevaluationevidence",
    )
    count_tables = (
        "evaluations_questionset",
        "evaluations_questionsetversion",
        "evaluations_questioncase",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
            for table in tables:
                cursor.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                    [table],
                )
                assert cursor.fetchone() == (True, True)
                cursor.execute(f'GRANT SELECT ON "{table}" TO "{role}"')  # noqa: S608
            cursor.execute(  # noqa: S608
                f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
            )
            for organization in organizations:
                cursor.execute(
                    "SELECT set_config('app.tenant_scope', %s, false)",
                    [str(organization.pk)],
                )
                cursor.execute(f'SET ROLE "{role}"')  # noqa: S608
                for table in count_tables:
                    cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
                    assert cursor.fetchone()[0] == 1
                cursor.execute("RESET ROLE")
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            for table in tables:
                cursor.execute(f'REVOKE ALL PRIVILEGES ON "{table}" FROM "{role}"')  # noqa: S608
            cursor.execute(  # noqa: S608
                f'REVOKE EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) FROM "{role}"'
            )
            cursor.execute(f'DROP ROLE IF EXISTS "{role}"')  # noqa: S608
