"""Exact candidate reads exercise real snapshots, builds, ACLs and Run execution."""

from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario, ScenarioExecutionContract
from apps.documents.models import (
    DocumentSetGrant,
    ScenarioDocumentSetBinding,
    ScenarioDocumentSetGrant,
)
from apps.evaluations.models import EvalDataGeneration, EvalRun
from apps.evaluations.prepared import admit_prepared_evaluation, prepared_run_generations
from apps.evaluations.services import (
    EvalError,
    _admit_eval,
    _admit_evaluation_input,
    evaluation_consumer_for_organization,
    resume_eval,
)
from apps.evaluations.tests.test_evaluations import _suite, _workflow
from apps.identity.models import Consumer, ScenarioResponsibilityAssignment
from apps.ingestion import vector_store
from apps.ingestion.connector_jobs import create_connector_job, execute_connector_job
from apps.ingestion.models import (
    DocumentSetPreparationProfile,
    TenantConfluenceProfileGrant,
    TenantMcpResourceGrant,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest import RestPullItem
from apps.ingestion.shared_retention import reclaim_shared_generation
from apps.ingestion.staged_build import promote_staged_index
from apps.ingestion.tests.test_connector_jobs import isolated_delivery as isolated_delivery
from apps.ingestion.tests.test_manual_preparation import completed_source as completed_source
from apps.ingestion.tests.test_manual_preparation import governed_rest as governed_rest
from apps.ingestion.tests.test_manual_preparation import governed_source as governed_source
from apps.ingestion.tests.test_manual_preparation import setup as setup
from apps.ingestion.tests.test_manual_preparation import wire as wire
from apps.ingestion.tests.test_rest_pull import _SyncClient
from apps.ingestion.tests.test_source_revisions import prepare
from apps.ingestion.vector_store import VectorStoreError
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.lifecycle import LifecycleError, _assert_release_gate
from apps.retrieval.providers import PgvectorRetrievalProvider
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import OrganizationMembership
from apps.workflows.models import Run

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def prepared_layout(request, settings):
    settings.INGESTION_VECTOR_STORAGE_LAYOUT = getattr(request, "param", "legacy")


@pytest.fixture(params=["legacy_pinned", "active_generation"])
def prepared(request, completed_source):
    if connection.vendor != "postgresql":
        pytest.skip("Real pgvector candidate preparation")
    actor, source, job, policy = completed_source
    index = prepare(actor, source, job, policy)
    org, docset = source.organization, source.document_set
    project = AIProject.objects.create(organization=org, slug="evaluation", name="Evaluation")
    scenario = Scenario.objects.create(
        organization=org,
        project=project,
        slug="prepared",
        name="Prepared",
        execution_contract=ScenarioExecutionContract.SNAPSHOT
        if request.param == "active_generation"
        else ScenarioExecutionContract.LEGACY,
        data_selection=request.param,
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=OrganizationMembership.objects.get(organization=org, user=actor),
        scenario=scenario,
        responsibility="scenario_manager",
        assigned_by=actor,
    )
    ScenarioDocumentSetGrant.objects.create(
        organization=org,
        scenario=scenario,
        document_set=docset,
        granted_by=actor,
        granted_at=timezone.now(),
    )
    ScenarioDocumentSetBinding.objects.create(
        organization=org, scenario=scenario, document_set=docset
    )
    consumer = evaluation_consumer_for_organization(org.pk)
    DocumentSetGrant.objects.get_or_create(
        organization=org,
        document_set=docset,
        principal_type="consumer",
        principal_ref=str(consumer.pk),
    )
    body = _workflow("ok")
    body["spec"]["nodes"].insert(1, {"id": "search", "type": "retrieve"})
    body["spec"]["edges"] = [
        {"from": "request", "to": "search"},
        {"from": "search", "to": "answer"},
        {"from": "answer", "to": "done"},
    ]
    artifacts = []
    for kind, artifact_body in (
        ("workflow_definition", body),
        ("eval_suite", _suite([{"type": "workflow_completed"}])),
    ):
        artifact = create_artifact_version(
            organization=org,
            artifact_type=kind,
            logical_id=kind,
            body=artifact_body,
            created_by=str(actor.pk),
        )
        artifacts.append(ArtifactRef(kind, kind, artifact.logical_id, artifact.version))
    release = compile_release(
        scenario=scenario, refs=artifacts, runtime_version="test", created_by=str(actor.pk)
    )
    job.refresh_from_db()
    return actor, source, job, policy, release, index, consumer


def admit(fixture):
    actor, _, job, _, release, *_ = fixture
    return admit_prepared_evaluation(actor=actor, release=release, source_job=job)


@pytest.mark.parametrize("completed_source", ["rest"], indirect=True)
@pytest.mark.parametrize("prepared_layout", ["shared_v1"], indirect=True)
def test_retention_preserves_prepared_evaluation_data(prepared):
    _, source, _, _, _, index, _ = prepared
    evaluation = admit(prepared)
    type(index).objects.filter(pk=index.pk).update(updated_at=timezone.now() - timedelta(days=91))
    result = reclaim_shared_generation(
        organization_id=source.organization_id,
        index_version_id=index.pk,
        actor="test-owner",
        apply=True,
    )
    assert not result.eligible and result.reason == "SHARED_RETENTION_REFERENCED"
    assert result.remaining > 0 and result.deleted == 0
    index.refresh_from_db()
    assert index.storage_state == "sealed" and index.store_ready
    assert evaluation.data_generations.filter(index_version=index).exists()


@pytest.mark.parametrize("prepared_layout", ["legacy", "shared_v1"], indirect=True)
def test_real_candidate_eval_never_changes_live_selection(prepared, monkeypatch):
    _, source, _, _, release, index, consumer = prepared
    provider = PgvectorRetrievalProvider()
    observed = []

    class ObservedProvider(PgvectorRetrievalProvider):
        def retrieve_prepared(self, **kwargs):
            chunks = super().retrieve_prepared(**kwargs)
            assert chunks
            observed.extend(c.index_version_id for c in chunks)
            return chunks

    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", ObservedProvider)
    evaluation = admit(prepared)
    result = resume_eval(eval_run_id=evaluation.pk, organization_id=release.organization_id)
    assert result.status == "passed", result.error_code
    assert observed and set(observed) == {index.pk}
    index.refresh_from_db()
    assert index.status == "promotable"
    assert not source.document_set.versions.filter(status="active").exists()
    assert (
        provider.retrieve(
            query="body",
            profile={"score_threshold": -1},
            organization_id=release.organization_id,
            scenario_id=release.scenario_id,
            consumer_id=consumer.pk,
            index_versions=[],
            document_set_version_ids=[index.document_set_version_id],
        )
        == []
    )
    original_count = Run.objects.count()
    assert (
        resume_eval(eval_run_id=evaluation.pk, organization_id=release.organization_id).status
        == "passed"
    )
    assert Run.objects.count() == original_count
    assert AuditEvent.objects.filter(action="eval.prepared.admitted").count() == 1
    with pytest.raises(LifecycleError, match="EVAL_REQUIRED"):
        _assert_release_gate(release, actor="test", action="release.promote")
    promote_staged_index(index, actor="test")
    _assert_release_gate(release, actor="test", action="release.promote")


@pytest.mark.parametrize("blocker", ["actor", "scenario", "consumer", "policy", "source_grant"])
def test_revoke_after_admission_stops_before_provider(prepared, monkeypatch, blocker):
    actor, source, _, policy, release, _, consumer = prepared
    evaluation = admit(prepared)
    if blocker == "actor":
        type(actor).objects.filter(pk=actor.pk).update(is_active=False)
    elif blocker == "scenario":
        ScenarioDocumentSetGrant.objects.filter(scenario=release.scenario).update(status="revoked")
    elif blocker == "consumer":
        DocumentSetGrant.objects.filter(
            document_set=source.document_set, principal_ref=str(consumer.pk)
        ).delete()
    elif blocker == "policy":
        DocumentSetPreparationProfile.objects.filter(pk=policy.pk).update(retrieval_profile=None)
    else:
        TenantRestPullProfileGrant.objects.filter(document_set=source.document_set).delete()
        TenantConfluenceProfileGrant.objects.filter(document_set=source.document_set).delete()
        TenantMcpResourceGrant.objects.filter(document_set=source.document_set).update(
            enabled=False
        )
    called = []
    monkeypatch.setattr(
        "apps.orchestration.rag_steps.get_retrieval_provider", lambda: called.append(True)
    )
    result = resume_eval(eval_run_id=evaluation.pk, organization_id=release.organization_id)
    assert result.status == "error"
    assert called == [] and not Run.objects.exists()


def test_wrong_actor_source_and_audit_failure_create_no_evaluation(prepared, monkeypatch):
    actor, _, job, _, release, *_ = prepared
    with pytest.raises(EvalError, match="DENIED"):
        admit_prepared_evaluation(actor=object(), release=release, source_job=job)

    def fail(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.evaluations.prepared.record_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        admit(prepared)
    assert not EvalRun.objects.exists() and not EvalDataGeneration.objects.exists()
    assert actor.is_active


def test_sql_pin_tamper_run_scope_and_nonempty_reverse(prepared):
    _, _, _, _, release, index, consumer = prepared
    evaluation = admit(prepared)
    run, _ = _admit_evaluation_input(
        release=release,
        input_payload={"query": "body"},
        request_key="prepared-sql",
        prepared_evaluation=evaluation,
    )
    assert [p.index_version_id for p in prepared_run_generations(run)] == [index.pk]
    for mutation in (
        lambda: EvalDataGeneration.objects.filter(evaluation=evaluation).update(
            index_version_id=index.pk
        ),
        lambda: EvalDataGeneration.objects.filter(evaluation=evaluation).delete(),
        lambda: EvalRun.objects.filter(pk=evaluation.pk).update(generation_count=2),
        lambda: Run.objects.filter(pk=run.pk).update(prepared_evaluation=None),
        lambda: type(index).objects.filter(pk=index.pk).update(store_ready=False),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            mutation()
    other = Consumer.objects.create(
        organization=release.organization, subject="other", name="Other"
    )
    with pytest.raises(EvalError, match="RUN_INVALID"):
        PgvectorRetrievalProvider().retrieve_prepared(
            query="body",
            profile={},
            organization_id=release.organization_id,
            scenario_id=release.scenario_id,
            consumer_id=other.pk,
            release_id=release.pk,
            run_id=run.pk,
        )
    for module in (
        "apps.evaluations.migrations.0006_prepared_evaluation",
        "apps.workflows.migrations.0021_prepared_evaluation",
    ):
        with (
            connection.schema_editor() as editor,
            pytest.raises(RuntimeError, match="EMPTY_HISTORY"),
        ):
            import_module(module).unprotect(apps, editor)


@pytest.mark.parametrize("completed_source", ["rest"], indirect=True)
@pytest.mark.parametrize("prepared_layout", ["legacy", "shared_v1"], indirect=True)
def test_changed_candidate_is_read_while_old_live_data_stays_active(prepared, monkeypatch):
    actor, source, _, policy, release, old, consumer = prepared
    promote_staged_index(old, actor=str(actor.pk))
    job, _ = create_connector_job(actor=actor, source=source)
    assert (
        execute_connector_job(
            public_id=str(job.public_id),
            organization_id=source.organization_id,
            rest_client=_SyncClient(
                [RestPullItem("a", "r2", "Doc A", False, "")], {"a": b"new candidate content"}
            ),
        )
        == "succeeded"
    )
    job.refresh_from_db()
    candidate = prepare(actor, source, job, policy)
    assert candidate.document_set_version_id != old.document_set_version_id
    refs = []
    for role, pin in release.manifest["artifacts"].items():
        logical_id, _, version = pin["ref"].rpartition(":v")
        refs.append(ArtifactRef(role, pin["type"], logical_id, int(version)))
    next_release = compile_release(
        scenario=release.scenario, refs=refs, runtime_version="test", created_by=str(actor.pk)
    )
    evaluation = admit_prepared_evaluation(actor=actor, release=next_release, source_job=job)
    observed = []

    class CandidateReader(PgvectorRetrievalProvider):
        def retrieve_prepared(self, **kwargs):
            chunks = super().retrieve_prepared(**kwargs)
            assert chunks and {c.index_version_id for c in chunks} == {candidate.pk}
            observed.extend(c.text for c in chunks)
            return chunks

    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", CandidateReader)
    result = resume_eval(eval_run_id=evaluation.pk, organization_id=source.organization_id)
    assert result.status == "passed", result.error_code
    assert observed and all("new candidate" in text for text in observed)
    old.refresh_from_db()
    candidate.refresh_from_db()
    assert old.status == "active" and candidate.status == "promotable"
    assert source.document_set.versions.get(status="active").pk == old.document_set_version_id
    hits = PgvectorRetrievalProvider().retrieve(
        query="content",
        profile={"mode": "keyword"},
        organization_id=source.organization_id,
        scenario_id=release.scenario_id,
        consumer_id=consumer.pk,
        index_versions=[],
        document_set_version_ids=[old.document_set_version_id],
    )
    assert hits and {h.index_version_id for h in hits} == {old.pk}
    assert all("new candidate" not in h.text for h in hits)


@pytest.mark.parametrize("completed_source", ["rest"], indirect=True)
def test_deferred_completeness_and_retained_store_cannot_be_bypassed(prepared):
    actor, _, job, _, release, index, _ = prepared
    with pytest.raises(DatabaseError, match="INCOMPLETE"), transaction.atomic():
        _admit_eval(
            release=release,
            created_by=str(actor.pk),
            prepared_source_job=job,
            prepared_actor=actor,
            generation_count=1,
        )
    assert not EvalRun.objects.exists()
    evaluation = admit(prepared)
    with pytest.raises(VectorStoreError):
        vector_store.drop_store(index)
    assert vector_store.store_exists(index)
    assert evaluation.data_generations.get().index_version_id == index.pk
    role = f"prepared_eval_rls_{uuid4().hex[:12]}"
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
            cursor.execute(f'GRANT SELECT ON evaluations_evaldatageneration TO "{role}"')
            cursor.execute(
                f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
            )
            for scope, expected in ((str(release.organization_id), 1), ("", 0), ("99999999", 0)):
                cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [scope])
                try:
                    cursor.execute(f'SET LOCAL ROLE "{role}"')
                    cursor.execute("SELECT count(*) FROM evaluations_evaldatageneration")
                    assert cursor.fetchone()[0] == expected
                finally:
                    cursor.execute("RESET ROLE")
            cursor.execute(f'DROP OWNED BY "{role}"')
            cursor.execute(f'DROP ROLE "{role}"')


@pytest.mark.parametrize("completed_source", ["rest"], indirect=True)
def test_prepared_link_is_not_derived_from_request_key_or_client_json(prepared):
    _, _, _, _, release, _, _ = prepared
    evaluation = admit(prepared)
    first, _ = _admit_evaluation_input(
        release=release,
        input_payload={"query": "body"},
        request_key=f"eval:{evaluation.pk}:0",
    )
    assert first.prepared_evaluation_id is None
    from apps.workflows.services import WorkflowRequestError

    with pytest.raises(WorkflowRequestError, match="IDEMPOTENCY_CONFLICT"):
        _admit_evaluation_input(
            release=release,
            input_payload={"query": "body"},
            request_key=f"eval:{evaluation.pk}:0",
            prepared_evaluation=evaluation,
        )
    other, _ = _admit_evaluation_input(
        release=release,
        input_payload={"query": "body", "prepared_evaluation_id": evaluation.pk},
        request_key="untrusted-input",
    )
    assert other.prepared_evaluation_id is None


@pytest.mark.parametrize("completed_source", ["rest"], indirect=True)
def test_non_owner_candidate_execution_and_catalog_least_privilege(prepared, monkeypatch):
    _, _, _, _, release, index, _ = prepared
    role = f"prepared_eval_app_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_connection, ingestion_restpullprofile, "
            "ingestion_embeddingprofile, ingestion_ocrprofile, orchestration_modelprofile "
            f'FROM "{role}"'
        )
        cursor.execute(f'SET ROLE "{role}"')
    try:
        monkeypatch.setattr(
            "apps.orchestration.rag_steps.get_retrieval_provider", PgvectorRetrievalProvider
        )
        evaluation = admit(prepared)
        result = resume_eval(eval_run_id=evaluation.pk, organization_id=release.organization_id)
        assert result.status == "passed", result.error_code
        with transaction.atomic():
            set_tenant_context(release.organization_id)
            assert evaluation.data_generations.get().index_version_id == index.pk
        with (
            connection.schema_editor() as editor,
            pytest.raises(RuntimeError, match="PRIVILEGED_ROLE"),
        ):
            import_module("apps.evaluations.migrations.0006_prepared_evaluation").unprotect(
                apps, editor
            )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            cursor.execute(f'DROP OWNED BY "{role}"')
            cursor.execute(f'DROP ROLE "{role}"')
