"""Durable generation choice and replay, exercised independently of node I/O."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connection,
    transaction,
)
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.catalog.models import ScenarioDataSelection, ScenarioExecutionContract
from apps.documents.models import (
    DocumentSet,
    DocumentSetGrant,
    DocumentSetVersion,
    ScenarioDocumentSetBinding,
    ScenarioDocumentSetGrant,
)
from apps.ingestion.models import IndexVersion
from apps.workflows.models import Run, RunRetrievalGeneration, RunRetrievalSelection
from apps.workflows.retrieval_selection import RetrievalSelectionError, capture_active_selection
from apps.workflows.tests.conftest import simple_workflow
from apps.workflows.tests.test_revision_execution import _admit, _compile_snapshot

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("elapsed", [float("nan"), float("inf"), -1, True, "1", 30.0])
def test_agent_resume_rejects_invalid_or_exhausted_time_budget(monkeypatch, elapsed):
    from apps.workflows.runtime import WorkflowRuntimeError
    from apps.workflows.unified_executor import _AGENT_RESUME_KEY, _run_eligible

    monkeypatch.setattr("apps.workflows.unified_executor.MAX_NODE_SECONDS", 30)
    calls = []
    monkeypatch.setattr(
        "apps.workflows.unified_executor._execute_eligible_node",
        lambda **kwargs: calls.append(kwargs),
    )
    with pytest.raises(WorkflowRuntimeError, match="WORKFLOW_NODE_TIMED_OUT"):
        _run_eligible(
            run=Run(),
            node={"id": "agent", "type": "agent_loop"},
            state={
                _AGENT_RESUME_KEY: {
                    "node_id": "agent",
                    "checkpoint": {"_embedded_elapsed_seconds": elapsed},
                }
            },
        )
    assert calls == []


def test_agent_time_budget_accumulates_across_selection_boundaries(monkeypatch):
    from types import SimpleNamespace

    from apps.agents.runtime import AgentRetrievalBoundary
    from apps.workflows.runtime import WorkflowRuntimeError
    from apps.workflows.unified_executor import _AGENT_RESUME_KEY, _run_eligible

    ticks = iter([0, 12, 20, 39])
    monkeypatch.setattr(
        "apps.workflows.unified_executor.time", SimpleNamespace(monotonic=lambda: next(ticks))
    )
    monkeypatch.setattr("apps.workflows.unified_executor.MAX_NODE_SECONDS", 30)

    def select(**kwargs):
        raise AgentRetrievalBoundary(checkpoint={}, step=0, query="query", profile={})

    monkeypatch.setattr("apps.workflows.unified_executor._execute_eligible_node", select)
    node = {"id": "agent", "type": "agent_loop"}
    with pytest.raises(AgentRetrievalBoundary) as first:
        _run_eligible(run=Run(), node=node, state={})
    assert first.value.checkpoint["_embedded_elapsed_seconds"] == 12
    with pytest.raises(WorkflowRuntimeError, match="WORKFLOW_NODE_TIMED_OUT"):
        _run_eligible(
            run=Run(),
            node=node,
            state={_AGENT_RESUME_KEY: {"node_id": "agent", "checkpoint": first.value.checkpoint}},
        )


@pytest.mark.django_db(transaction=True)
def test_active_data_sync_http_commits_each_choice_before_provider(selection_fixture, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Independent HTTP commit visibility")
    observed = []

    class Provider:
        def retrieve_selected(self, **arguments):
            probe = connection.copy(alias="http-selection-probe")
            try:
                with probe.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM workflows_runretrievalselection WHERE id = %s",
                        [arguments["selection_id"]],
                    )
                    assert cursor.fetchone()[0] == 1
            finally:
                probe.close()
            observed.append(arguments["selection_id"])
            return []

    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", Provider)
    f, *_ = selection_fixture
    run = _admit(f, "active-http-sync")
    assert run.status == "completed"
    assert len(set(observed)) == 2
    assert run.retrieval_selections.count() == 2
    assert _admit(f, "active-http-sync").pk == run.pk
    assert len(observed) == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("region", ["parallel", "for_each"])
def test_active_branch_selection_is_durable_and_next_branch_tracks_refresh(
    selection_fixture, monkeypatch, region
):
    if connection.vendor != "postgresql":
        pytest.skip("Independent branch commit visibility")
    from copy import deepcopy

    from apps.workflows.tests.test_unified_parallel import (
        _FOR_EACH_EDGES,
        _FOR_EACH_NODES,
        _PARALLEL_EDGES,
        _PARALLEL_NODES,
        _branch_ids,
        _deliver,
    )
    from apps.workflows.tests.test_unified_run import _execute_queued

    f, _, _, docset, dsv, index = selection_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_run_branch.apply_async", lambda *a, **k: None
    )
    nodes = deepcopy(_PARALLEL_NODES if region == "parallel" else _FOR_EACH_NODES)
    edges = deepcopy(_PARALLEL_EDGES if region == "parallel" else _FOR_EACH_EDGES)
    if region == "for_each":
        nodes[2] = {
            "id": "each",
            "type": "retrieve",
            "input_mapping": [{"from": "/item", "to": "/query"}],
        }
    body = simple_workflow()
    body["spec"] = {"input_node": "start", "nodes": nodes, "edges": edges}
    _compile_snapshot(f, body)
    parent = _admit(f, f"active-{region}-success", background=True)
    if region == "for_each":
        parent.checkpoint = {"input": {"query": "hello", "items": ["one", "two"]}}
        parent.redacted_state = parent.checkpoint
        parent.save(update_fields=["checkpoint", "redacted_state"])
    assert _execute_queued(parent).status == "waiting_child"
    observed = []

    class Provider:
        def retrieve_selected(self, **arguments):
            probe = connection.copy(alias="branch-selection-probe")
            try:
                with probe.cursor() as cursor:
                    cursor.execute(
                        "SELECT index_version_id FROM workflows_runretrievalgeneration "
                        "WHERE selection_id = %s",
                        [arguments["selection_id"]],
                    )
                    observed.append(cursor.fetchone()[0])
            finally:
                probe.close()
            return []

    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", Provider)
    first, second = _branch_ids(parent)
    assert _deliver(parent, first) == "committed"
    IndexVersion.objects.filter(pk=index.pk).update(status="superseded")
    DocumentSetVersion.objects.filter(pk=dsv.pk).update(status="superseded")
    _, latest = _generation(f, docset, 2)
    assert _deliver(parent, second) == "committed"
    assert _deliver(parent, first) == "duplicate"
    assert observed == [index.pk, latest.pk]
    assert parent.retrieval_selections.count() == 2
    assert _execute_queued(parent).status == "completed"


def _generation(f, docset, version, *, active=True):
    dsv = DocumentSetVersion.objects.create(
        organization=f.organization,
        document_set=docset,
        version=version,
        status="active" if active else "promotable",
    )
    index = IndexVersion.objects.create(
        organization=f.organization,
        document_set_version=dsv,
        version=version,
        status="active" if active else "promotable",
        store_ready=True,
    )
    dsv.built_index_version = index
    dsv.save(update_fields=["built_index_version"])
    return dsv, index


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("surface", ["ask", "evaluation", "worker", "studio", "prepare"])
@pytest.mark.parametrize("non_owner", [False, True])
def test_operator_active_data_uses_short_scoped_transactions(
    selection_fixture, monkeypatch, client, surface, non_owner
):
    if connection.vendor != "postgresql":
        pytest.skip("Durable operator HTTP and non-owner RLS")
    from django.urls import reverse

    from apps.artifacts.services import create_artifact_version
    from apps.console.tests.test_candidate_authority import _user
    from apps.evaluations.models import EvalRun
    from apps.evaluations.question_services import (
        create_answer_evaluation,
        create_question_set,
        publish_question_set,
    )
    from apps.evaluations.services import evaluation_consumer_for_organization
    from apps.evaluations.tasks import execute_question_evaluation_task
    from apps.evaluations.tests.test_question_sets import _admin, _cases
    from apps.releases.models import ScenarioRelease

    f, _, _, docset, _, index = selection_fixture
    f.release = ScenarioRelease.objects.get(scenario=f.scenario, status="active")
    suite = create_artifact_version(
        organization=f.organization,
        artifact_type="eval_suite",
        logical_id="active-suite",
        body={
            "cases": [
                {
                    "id": "smoke",
                    "input": {"query": "hello"},
                    "assertions": [{"type": "workflow_completed"}],
                }
            ]
        },
        created_by="test",
    )
    f.release.manifest["artifacts"]["eval_suite"] = {"type": suite.type, "ref": suite.ref}
    release = _compile_snapshot(f)
    user = _user(f.organization, "operator-active", f.scenario, "scenario_manager")
    consumer = evaluation_consumer_for_organization(f.organization.pk)
    DocumentSetGrant.objects.create(
        organization=f.organization,
        document_set=docset,
        principal_type="consumer",
        principal_ref=str(consumer.pk),
    )
    client.force_login(user)
    draft = None
    if surface in {"studio", "prepare"}:
        from apps.builder.services import create_draft
        from apps.releases.scenario_artifacts import (
            SCENARIO_SCOPED_ROLES,
            scenario_artifact_logical_id,
        )

        snapshot = release.execution_revision.snapshot
        for role_name in SCENARIO_SCOPED_ROLES:
            captured = snapshot["artifacts"][role_name]
            create_artifact_version(
                organization=f.organization,
                artifact_type=role_name,
                logical_id=scenario_artifact_logical_id(f.scenario, role_name),
                body=captured["body"],
                created_by="test",
            )
        draft = create_draft(
            organization=f.organization,
            project=f.scenario.project,
            scenario=f.scenario,
            logical_id="durable-builder",
            name="Durable builder",
            actor=user.username,
            body=snapshot["artifacts"]["workflow_definition"]["body"],
        )
    evaluation = None
    if surface == "worker":
        admin = _admin(f.organization, "question-author")
        cases = _cases(with_anchor=False)
        cases[0]["input"] = {"query": "hello"}
        cases[0]["assertions"] = [{"type": "exact", "value": "ok"}]
        question_set = create_question_set(
            organization=f.organization,
            user=admin,
            name="Active worker",
            description="",
            cases=cases,
        )
        version = publish_question_set(
            question_set=question_set,
            user=admin,
            expected_revision=question_set.draft_revision,
        )
        evaluation, _ = create_answer_evaluation(
            user=user,
            question_set_version=version,
            release=release,
            idempotency_key="active-worker",
        )
    observed = []

    class Provider:
        def retrieve_selected(self, **arguments):
            probe = connection.copy(alias="operator-selection-probe")
            try:
                with probe.cursor() as cursor:
                    cursor.execute(
                        "SELECT index_version_id FROM workflows_runretrievalgeneration "
                        "WHERE selection_id = %s",
                        [arguments["selection_id"]],
                    )
                    observed.append(cursor.fetchone()[0])
            finally:
                probe.close()
            return []

    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", Provider)
    role = f"operator_selection_{uuid4().hex[:12]}"
    if non_owner:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
            cursor.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'
            )
            cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
            cursor.execute(f'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "{role}"')
            cursor.execute(f'SET ROLE "{role}"')
    try:
        if surface == "worker":
            assert evaluation is not None
            execute_question_evaluation_task(
                organization_id=f.organization.pk, run_id=evaluation.pk
            )
            execute_question_evaluation_task(
                organization_id=f.organization.pk, run_id=evaluation.pk
            )
            response = None
        elif surface == "studio":
            assert draft is not None
            response = client.post(
                reverse("builder_api:draft_publish_and_verify", args=[draft.pk]),
                {"revision": draft.revision, "version_description": "durable candidate"},
                content_type="application/json",
            )
            assert response.status_code == 201, response.content
            assert response.json()["evaluation"]["status"] == "passed", response.content
            assert len(response.json()["evaluation"]["cases"]) == 1
            response = None
        elif surface == "prepare":
            response = client.post(
                reverse("console:scenario_publish_and_verify", args=[f.scenario.public_id]),
                {"version_description": "durable candidate"},
            )
        elif surface == "ask":
            response = client.post(
                reverse("console:scenario_ask", args=[f.scenario.public_id]), {"question": "hello"}
            )
        else:
            response = client.post(reverse("console:release_run_eval", args=[release.pk]))
        if response is not None:
            assert response.status_code == 302, response.content
    finally:
        if non_owner:
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
                for objects in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                    cursor.execute(
                        f'REVOKE ALL PRIVILEGES ON ALL {objects} IN SCHEMA public FROM "{role}"'
                    )
                cursor.execute(f'DROP ROLE "{role}"')
    assert observed == [index.pk, index.pk]
    if surface == "worker":
        assert evaluation is not None
        evaluation.refresh_from_db()
        assert evaluation.status == "completed"
        assert evaluation.error_cases == 0 and evaluation.completed_cases == 1
    elif surface in {"studio", "prepare"}:
        assert EvalRun.objects.filter(release__scenario=f.scenario, status="passed").count() == 1
        assert ScenarioRelease.objects.get(pk=release.pk).status == "active"
    elif surface == "evaluation":
        assert EvalRun.objects.get(release=release).status == "passed"
    else:
        assert client.session["scenario_ask"]["answer"] == "ok"
    # Revoked access is checked again even when the same URL and session remain open.
    user.org_memberships.update(status="revoked", revoked_at=timezone.now(), revoked_by=user)
    response = client.post(
        reverse("console:scenario_ask", args=[f.scenario.public_id]), {"question": "second"}
    )
    assert response.status_code in {403, 404}
    assert len(observed) == 2


@pytest.fixture
def selection_fixture(workflow_fixture, monkeypatch):
    f = workflow_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async", lambda *a, **k: None
    )
    docset = DocumentSet.objects.create(organization=f.organization, logical_id="kb", name="KB")
    ScenarioDocumentSetBinding.objects.create(
        organization=f.organization, scenario=f.scenario, document_set=docset, created_by="test"
    )
    manager = get_user_model().objects.create_user(username="data-manager", password=None)
    ScenarioDocumentSetGrant.objects.create(
        organization=f.organization,
        scenario=f.scenario,
        document_set=docset,
        granted_by=manager,
        granted_at=timezone.now(),
    )
    DocumentSetGrant.objects.create(
        organization=f.organization,
        document_set=docset,
        principal_type="consumer",
        principal_ref=str(f.consumer.pk),
    )
    dsv, index = _generation(f, docset, 1)
    f.scenario.execution_contract = ScenarioExecutionContract.SNAPSHOT
    f.scenario.data_selection = ScenarioDataSelection.ACTIVE_GENERATION
    f.scenario.save(update_fields=["execution_contract", "data_selection"])
    body = simple_workflow()
    body["spec"]["nodes"][1:1] = [{"id": name, "type": "retrieve"} for name in ("first", "second")]
    body["spec"]["nodes"][1]["retry_policy"] = {
        "max_attempts": 2,
        "backoff_seconds": 0,
        "retry_on": ["transient"],
        "idempotent": True,
    }
    body["spec"]["edges"][:1] = [
        {"from": "request", "to": "first"},
        {"from": "first", "to": "second"},
        {"from": "second", "to": "format"},
    ]
    _compile_snapshot(f, body)
    run = _admit(f, "selection", background=True)
    # Same claim and start transition as the real worker, without entering node I/O.
    from apps.workflows.background_claims import claim_background_run
    from apps.workflows.transitions import transition_run

    token = uuid4()
    claim = claim_background_run(
        organization_id=f.organization.pk, run_id=run.pk, claim_token=token, lease_seconds=60
    )
    transition_run(
        organization_id=f.organization.pk,
        run_id=run.pk,
        transition_token=uuid4(),
        expected_checkpoint_version=claim.checkpoint_version,
        expected_status="queued",
        target_status="running",
        background_claim_token=token,
    )
    return f, run, token, docset, dsv, index


def _capture(fixture, **overrides):
    f, run, token, *_ = fixture
    arguments = {
        "organization_id": f.organization.pk,
        "run_id": run.pk,
        "owner_token": token,
        "node_id": "first",
        "query": "synthetic private query",
        "profile": {"mode": "keyword"},
    }
    return capture_active_selection(**(arguments | overrides))


def test_retry_keeps_choice_and_next_step_selects_new_active_generation(selection_fixture):
    f, run, token, docset, dsv, index = selection_fixture
    first = _capture(selection_fixture)
    assert first.index_version_ids == (index.pk,)
    DocumentSetVersion.objects.filter(pk=dsv.pk).update(status="superseded")
    IndexVersion.objects.filter(pk=index.pk).update(status="superseded")
    next_dsv, next_index = _generation(f, docset, 2)
    assert _capture(selection_fixture) == first
    second = _capture(selection_fixture, node_id="second")
    assert second.index_version_ids == (next_index.pk,)
    assert second.document_set_version_ids == (next_dsv.pk,)
    events = AuditEvent.objects.filter(action="run.retrieval.selected")
    assert events.count() == 2
    assert "synthetic private query" not in str(list(events.values()))
    assert RunRetrievalGeneration.objects.filter(selection__run=run).count() == 2


def test_empty_choice_stays_empty_on_retry_after_a_new_grant(selection_fixture):
    f, run, token, docset, *_ = selection_fixture
    grant = DocumentSetGrant.objects.get(document_set=docset)
    grant.delete()
    empty = _capture(selection_fixture)
    assert empty.index_version_ids == ()
    grant.pk = None
    grant.save()
    assert _capture(selection_fixture) == empty
    assert _capture(selection_fixture, node_id="second").index_version_ids


@pytest.mark.parametrize(
    "change,code",
    [
        ({"owner_token": uuid4()}, "OWNER_INVALID"),
        ({"node_id": "format"}, "NODE_INVALID"),
        ({"organization_id": 99999999}, "RUN_UNRESOLVED"),
        ({"profile": {"invalid": float("nan")}}, "INPUT_INVALID"),
    ],
)
def test_selection_rejects_invalid_owner_scope_node_and_input(selection_fixture, change, code):
    with pytest.raises(RetrievalSelectionError, match=code):
        _capture(selection_fixture, **change)
    assert not RunRetrievalSelection.objects.exists()


def test_changed_retry_input_is_a_conflict_and_not_a_new_choice(selection_fixture):
    _capture(selection_fixture)
    with pytest.raises(RetrievalSelectionError, match="REPLAY_CONFLICT"):
        _capture(selection_fixture, query="different")
    assert RunRetrievalSelection.objects.count() == 1


def test_missing_active_generation_and_audit_failure_leave_no_partial_receipt(
    selection_fixture, monkeypatch
):
    *_, index = selection_fixture
    IndexVersion.objects.filter(pk=index.pk).update(store_ready=False)
    with pytest.raises(RetrievalSelectionError, match="GENERATION_NOT_READY"):
        _capture(selection_fixture)
    assert not RunRetrievalSelection.objects.exists()
    IndexVersion.objects.filter(pk=index.pk).update(store_ready=True)

    def fail_audit(**kwargs):
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr("apps.workflows.retrieval_selection.record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit outage"):
        _capture(selection_fixture)
    assert not RunRetrievalSelection.objects.exists()
    assert not RunRetrievalGeneration.objects.exists()


def test_selection_cannot_be_nested_in_a_node_transaction(selection_fixture):
    with transaction.atomic(), pytest.raises(RuntimeError, match="durable atomic"):
        _capture(selection_fixture)


def test_postgres_selection_and_generation_are_immutable_and_complete(selection_fixture):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL immutable and deferred guards")
    result = _capture(selection_fixture)
    with pytest.raises(IntegrityError, match="SELECTION_IMMUTABLE"), transaction.atomic():
        RunRetrievalSelection.objects.filter(pk=result.id).update(criteria_checksum="0" * 64)
    with pytest.raises(IntegrityError, match="SELECTION_IMMUTABLE"), transaction.atomic():
        RunRetrievalGeneration.objects.filter(selection_id=result.id).delete()
    original = RunRetrievalSelection.objects.get(pk=result.id)
    with pytest.raises(IntegrityError, match="SELECTION_INCOMPLETE"), transaction.atomic():
        RunRetrievalSelection.objects.create(
            organization=original.organization,
            run=original.run,
            revision=original.revision,
            step_key="node:second",
            criteria_checksum=original.criteria_checksum,
            generation_count=1,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS retrieval_selection_complete IMMEDIATE")


@pytest.mark.parametrize("layout", ["legacy", "shared_v1"])
def test_selected_generation_is_readable_after_promotion_with_live_revocation_and_tombstone(
    selection_fixture, layout
):
    if connection.vendor != "postgresql":
        pytest.skip("Real vector stores and tenant policy")
    from apps.documents.models import Document, DocumentSetMembership, DocumentVersion
    from apps.ingestion import vector_store
    from apps.ingestion.vector_store import VectorRow, VectorStoreError
    from apps.retrieval.providers import PgvectorRetrievalProvider

    f, run, token, docset, dsv, index = selection_fixture
    document = Document.objects.create(
        organization=f.organization, logical_id="evidence", title="Synthetic evidence"
    )
    version = DocumentVersion.objects.create(
        organization=f.organization,
        document=document,
        version=1,
        checksum="a" * 64,
        mime_type="text/plain",
        object_key=f"synthetic/{f.organization.pk}/evidence",
    )
    DocumentSetMembership.objects.create(
        organization=f.organization, document_set_version=dsv, document_version=version
    )
    # Build a synthetic store through the real DAL before capturing any receipt.
    index.dimensions, index.index_type = 64, "vector"
    index.storage_layout, index.storage_state = layout, "open"
    index.status, index.store_ready = "building", False
    index.save()
    vector_store.provision_store(index)
    vector_store.write_chunks(
        index,
        [
            VectorRow(
                f.organization.pk,
                version.pk,
                0,
                "synthetic private query passage",
                [1.0] + [0.0] * 63,
            )
        ],
    )
    index.storage_state, index.status, index.store_ready = "sealed", "active", True
    index.save()
    chosen = _capture(selection_fixture)
    IndexVersion.objects.filter(pk=index.pk).update(status="superseded")
    DocumentSetVersion.objects.filter(pk=dsv.pk).update(status="superseded")
    _generation(f, docset, 2)
    provider = PgvectorRetrievalProvider()
    arguments = {
        "organization_id": f.organization.pk,
        "run_id": run.pk,
        "release_id": run.release_id,
        "scenario_id": run.scenario_id,
        "consumer_id": f.consumer.pk,
        "selection_id": chosen.id,
        "query": "synthetic private query",
        "profile": {"mode": "keyword"},
    }
    hits = provider.retrieve_selected(**arguments)
    assert len(hits) == 1 and hits[0].index_version_id == index.pk
    with pytest.raises(RetrievalSelectionError, match="UNRESOLVED"):
        provider.retrieve_selected(**(arguments | {"run_id": uuid4()}))
    with pytest.raises(IntegrityError, match="GENERATION_PROTECTED"), transaction.atomic():
        IndexVersion.objects.filter(pk=index.pk).update(store_ready=False)
    with pytest.raises(VectorStoreError), transaction.atomic():
        vector_store.drop_store(index)
    if layout == "legacy":
        role = f"selected_store_ddl_{uuid4().hex[:12]}"
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
            cursor.execute(f'GRANT SELECT ON ingestion_indexversion TO "{role}"')
            cursor.execute(
                f'GRANT EXECUTE ON FUNCTION agenthub_drop_index_store(bigint) TO "{role}"'
            )
            cursor.execute(f'SET LOCAL ROLE "{role}"')
        try:
            with pytest.raises(OperationalError, match="RETRIEVAL_GENERATION_PROTECTED"):
                with transaction.atomic():
                    from apps.tenancy.context import set_tenant_context

                    set_tenant_context(f.organization.pk)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT agenthub_drop_index_store(%s)", [index.pk])
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
        assert vector_store.store_exists(index)
        assert len(provider.retrieve_selected(**arguments)) == 1
    grant = DocumentSetGrant.objects.get(document_set=docset)
    grant.delete()
    assert provider.retrieve_selected(**arguments) == []
    grant.pk = None
    grant.save()
    Document.objects.filter(pk=document.pk).update(deleted_at=timezone.now())
    assert provider.retrieve_selected(**arguments) == []


def test_postgres_selection_tables_force_tenant_scope(selection_fixture):
    if connection.vendor != "postgresql":
        pytest.skip("Non-owner PostgreSQL RLS")
    _capture(selection_fixture)
    f, *_ = selection_fixture
    role = f"selection_rls_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(
            "GRANT SELECT ON workflows_runretrievalselection, workflows_runretrievalgeneration "
            f'TO "{role}"'
        )
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        for scope, expected in ((str(f.organization.pk), 1), ("", 0), ("99999999", 0)):
            cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [scope])
            try:
                cursor.execute(f'SET LOCAL ROLE "{role}"')
                cursor.execute("SELECT count(*) FROM workflows_runretrievalselection")
                assert cursor.fetchone()[0] == expected
                cursor.execute("SELECT count(*) FROM workflows_runretrievalgeneration")
                assert cursor.fetchone()[0] == expected
            finally:
                cursor.execute("RESET ROLE")


@pytest.mark.django_db(transaction=True)
def test_executor_commits_selection_before_io_and_retry_keeps_it(selection_fixture, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Independent connection commit visibility")
    from apps.workflows.unified_executor import execute_claimed_bounded_run

    f, run, token, docset, dsv, index = selection_fixture
    observed = []

    class Provider:
        def retrieve_selected(self, **arguments):
            probe = connection.copy(alias="selection-commit-probe")
            try:
                with probe.cursor() as cursor:
                    cursor.execute(
                        "SELECT g.index_version_id FROM workflows_runretrievalgeneration g "
                        "JOIN workflows_runretrievalselection s ON s.id = g.selection_id "
                        "WHERE s.id = %s AND s.run_id = %s",
                        [arguments["selection_id"], run.pk],
                    )
                    rows = cursor.fetchall()
                    assert len(rows) == 1
                    observed.append(rows[0][0])
            finally:
                probe.close()
            if len(observed) == 1:
                IndexVersion.objects.filter(pk=index.pk).update(status="superseded")
                DocumentSetVersion.objects.filter(pk=dsv.pk).update(status="superseded")
                _generation(f, docset, 2)
                raise TimeoutError("synthetic provider failure")
            return []

    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", Provider)
    result = execute_claimed_bounded_run(
        organization_id=f.organization.pk,
        run_id=run.pk,
        claim_token=token,
    )
    assert result.status == "completed"
    run.refresh_from_db()
    assert observed[:2] == [index.pk, index.pk]
    assert len(observed) == 3 and observed[2] != index.pk
    assert run.retrieval_selections.count() == 2
    assert run.step_count == 5
    assert run.events.filter(event_type="run.started").count() == 1
    assert run.events.filter(event_type="run.checkpointed").count() == 2
    assert run.checkpoint["output"]["answer"] == "ok"


@pytest.mark.django_db(transaction=True)
def test_concurrent_selection_commits_one_receipt(selection_fixture):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL durable row lock serialization")
    barrier = Barrier(2)

    def capture(_):
        close_old_connections()
        try:
            barrier.wait()
            return _capture(selection_fixture)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(capture, range(2)))
    assert results[0] == results[1]
    assert RunRetrievalSelection.objects.count() == 1
    assert AuditEvent.objects.filter(action="run.retrieval.selected").count() == 1


@pytest.mark.django_db(transaction=True)
def test_branch_crash_keeps_choice_and_rejects_a_late_worker(selection_fixture, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Real durable branch crash boundary")
    from copy import deepcopy
    from datetime import timedelta

    from apps.workflows.models import RunBranch
    from apps.workflows.run_parallel import reconcile_run_parallel_work
    from apps.workflows.tests.test_unified_parallel import (
        _PARALLEL_EDGES,
        _PARALLEL_NODES,
        _branch_ids,
        _deliver,
    )
    from apps.workflows.tests.test_unified_run import _execute_queued

    f, _, _, docset, dsv, index = selection_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_run_branch.apply_async", lambda *a, **k: None
    )
    body = simple_workflow()
    body["spec"] = {
        "input_node": "start",
        "nodes": deepcopy(_PARALLEL_NODES),
        "edges": deepcopy(_PARALLEL_EDGES),
    }
    _compile_snapshot(f, body)
    parent = _admit(f, "active-parallel", background=True)
    assert _execute_queued(parent).status == "waiting_child"
    first, second = _branch_ids(parent)
    old_token = RunBranch.objects.get(pk=first).delivery_token
    should_crash = True
    observed = []

    class Provider:
        def retrieve_selected(self, **arguments):
            nonlocal should_crash
            receipt = RunRetrievalGeneration.objects.get(selection_id=arguments["selection_id"])
            observed.append(receipt.index_version_id)
            if should_crash:
                should_crash = False
                raise SystemExit("synthetic worker loss")
            return []

    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", Provider)
    with pytest.raises(SystemExit, match="worker loss"):
        _deliver(parent, first)
    assert parent.retrieval_selections.count() == 1
    IndexVersion.objects.filter(pk=index.pk).update(status="superseded")
    DocumentSetVersion.objects.filter(pk=dsv.pk).update(status="superseded")
    _generation(f, docset, 2)
    RunBranch.objects.filter(pk=first).update(
        claim_expires_at=timezone.now() - timedelta(seconds=1)
    )
    reconcile_run_parallel_work(organization_id=f.organization.pk, limit=10)
    abandoned = RunBranch.objects.get(pk=first)
    assert abandoned.status == "failed"
    assert abandoned.reason_code == "WORKFLOW_BRANCH_RECOVERY_REQUIRED"
    from apps.workflows.tasks import execute_unified_run_branch

    assert execute_unified_run_branch(str(first), f.organization.pk, str(old_token)) in {
        "stale",
        "terminal",
    }
    assert observed == [index.pk]
    assert parent.retrieval_selections.count() == 1


@pytest.mark.django_db(transaction=True)
def test_embedded_agent_preserves_decisions_across_durable_data_boundaries(
    selection_fixture, monkeypatch
):
    if connection.vendor != "postgresql":
        pytest.skip("Durable agent selection visibility")
    from apps.agents.planner import AgentDecision
    from apps.workflows.presets import agent_loop_workflow
    from apps.workflows.tests.test_unified_run import _execute_queued

    f, _, _, docset, dsv, index = selection_fixture
    body = agent_loop_workflow(
        policy={
            "tool_binding_roles": [],
            "retrieval": {"enabled": True},
            "limits": {"max_steps": 4, "max_tool_calls": 0},
            "actions": {"verify_roles": ["retrieval"], "repeat_retrieval": True},
        }
    )
    _compile_snapshot(f, body)
    run = _admit(f, "active-agent", background=True)
    proposed = []
    observed = []

    class Planner:
        def next_action(self, *, step_index, **kwargs):
            proposed.append(step_index)
            return [
                AgentDecision("retrieve"),
                AgentDecision("verify", role="retrieval"),
                AgentDecision("respond"),
            ][step_index]

    class Provider:
        def retrieve_selected(self, **arguments):
            probe = connection.copy(alias="agent-selection-probe")
            try:
                with probe.cursor() as cursor:
                    cursor.execute(
                        "SELECT index_version_id FROM workflows_runretrievalgeneration "
                        "WHERE selection_id = %s",
                        [arguments["selection_id"]],
                    )
                    rows = cursor.fetchall()
                    assert len(rows) == 1
                    observed.append(rows[0][0])
            finally:
                probe.close()
            if len(observed) == 1:
                IndexVersion.objects.filter(pk=index.pk).update(status="superseded")
                DocumentSetVersion.objects.filter(pk=dsv.pk).update(status="superseded")
                _generation(f, docset, 2)
            return []

    monkeypatch.setattr("apps.agents.runtime.get_configured_planner", Planner)
    monkeypatch.setattr("apps.orchestration.rag_steps.get_retrieval_provider", Provider)
    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    assert proposed == [0, 1, 2]
    assert observed[0] == index.pk and len(observed) == 2 and observed[1] != index.pk
    assert list(
        run.retrieval_selections.order_by("step_key").values_list("step_key", flat=True)
    ) == [
        "node:agent:agent:0",
        "node:agent:agent:1",
    ]
    assert run.step_count == 3
    assert run.tool_call_count == 0
    from apps.workflows.unified_executor import _AGENT_RESUME_KEY

    assert _AGENT_RESUME_KEY not in run.checkpoint
