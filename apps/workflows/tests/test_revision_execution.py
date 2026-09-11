"""New execution snapshots and legacy runs coexist across admission and resume."""

from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from rest_framework.test import APIClient

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.catalog.models import ScenarioExecutionContract
from apps.orchestration.resolver import resolve_bundle
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.releases.execution import release_revision, run_workflow_graph
from apps.releases.models import ScenarioRelease, ScenarioRevision
from apps.releases.revision_schema import RevisionError
from apps.releases.services import get_artifact_body_for_role
from apps.workflows.compiler import COMPILER_VERSION, SNAPSHOT_COMPILER_VERSION
from apps.workflows.models import Run, WorkflowVersion
from apps.workflows.run_waits import resume_run_wait
from apps.workflows.tests.conftest import simple_workflow
from apps.workflows.tests.test_unified_run import _execute_queued
from apps.workflows.unified_executor import execute_background_delivery, service_revision

pytestmark = pytest.mark.django_db


def _compile_snapshot(f, body=None):
    f.scenario.execution_contract = ScenarioExecutionContract.SNAPSHOT
    f.scenario.save(update_fields=["execution_contract"])
    refs = []
    for role, pin in f.release.manifest["artifacts"].items():
        logical_id, _, version = pin["ref"].rpartition(":v")
        refs.append(ArtifactRef(role, pin["type"], logical_id, int(version)))
    if body is not None:
        artifact = create_artifact_version(
            organization=f.organization,
            artifact_type="workflow_definition",
            logical_id="revision-flow",
            body=body,
            created_by="snapshot-test",
        )
        refs = [ref for ref in refs if ref.role != "workflow_definition"] + [
            ArtifactRef("workflow_definition", artifact.type, artifact.logical_id, artifact.version)
        ]
    release = compile_release(
        scenario=f.scenario, refs=refs, runtime_version="workflow:1", created_by="snapshot-test"
    )
    promote_release(release)
    return release


def _admit(f, key, *, background=False):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {f.token}")
    response = client.post(
        "/v1/responses",
        {
            "model": f.alias,
            "input": "hello",
            "background": background,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert response.status_code == (202 if background else 200), response.content
    return Run.objects.get(consumer=f.consumer, idempotency_key=key)


def test_snapshot_gateway_uses_resolved_bodies_after_catalog_drift(workflow_fixture):
    f = workflow_fixture
    release = _compile_snapshot(f)
    revision, snapshot = release_revision(release)
    assert revision is not None and snapshot is not None
    assert revision.workflow_version.compiler_version == SNAPSHOT_COMPILER_VERSION
    assert f.release.execution_contract == ScenarioExecutionContract.LEGACY
    # Updating the legacy registry cannot rewrite the already captured new execution.
    ArtifactVersion.objects.filter(organization=f.organization, type="input_contract").update(
        body={"type": "object", "required": ["missing"]},
        checksum="0" * 64,
    )
    input_contract = get_artifact_body_for_role(release, "input_contract")
    assert input_contract is not None and input_contract["required"] == ["query"]
    run = _admit(f, "snapshot-sync")
    assert run.status == "completed"
    assert run.scenario_revision_id == revision.pk
    assert run.checkpoint["output"] == {"answer": "ok", "sources": []}
    assert run.compiler_version == SNAPSHOT_COMPILER_VERSION


def test_bundle_resolves_snapshot_once_without_per_role_database_reads(workflow_fixture):
    from django.test.utils import CaptureQueriesContext

    release = _compile_snapshot(workflow_fixture)
    cache.clear()
    with CaptureQueriesContext(connection) as queries:
        bundle = resolve_bundle(release)
    revision_reads = [q for q in queries if "releases_scenariorevision" in q["sql"]]
    assert len(revision_reads) == 1
    assert not any("artifacts_artifactversion" in q["sql"] for q in queries)
    assert bundle.input_contract is not None
    assert bundle.input_contract["required"] == ["query"]


def test_background_run_keeps_admitted_revision_after_new_publication(
    workflow_fixture, monkeypatch
):
    f = workflow_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async", lambda *a, **k: None
    )
    first = _compile_snapshot(f)
    run = _admit(f, "snapshot-background", background=True)
    first_revision = run.scenario_revision_id
    body = simple_workflow()
    body["spec"]["nodes"][1]["config"]["template_ref"] = "new-publication"
    second = _compile_snapshot(f, body)
    assert second.pk != first.pk
    cache.clear()
    token = uuid4()
    delivery: dict[str, object] = {"run_id": str(run.pk), "delivery_token": str(token)}
    headers = {"organization_id": f.organization.pk, "service_revision": service_revision()}
    assert execute_background_delivery(body=delivery, headers=headers) == "completed"
    run.refresh_from_db()
    assert run.scenario_revision_id == first_revision
    assert run.release_id == first.pk
    assert run.checkpoint["output"] == {"answer": "ok", "sources": []}
    before = run.events.count()
    assert execute_background_delivery(body=delivery, headers=headers) == "completed"
    assert run.events.count() == before


def test_legacy_run_retains_legacy_contract_after_scenario_opt_in(workflow_fixture, monkeypatch):
    f = workflow_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async", lambda *a, **k: None
    )
    run = _admit(f, "old-admitted", background=True)
    assert run.scenario_revision_id is None and run.compiler_version == COMPILER_VERSION
    _compile_snapshot(f)
    assert (
        execute_background_delivery(
            body={"run_id": str(run.pk), "delivery_token": str(uuid4())},
            headers={"organization_id": f.organization.pk, "service_revision": service_revision()},
        )
        == "completed"
    )
    run.refresh_from_db()
    assert run.scenario_revision_id is None and run.checkpoint["output"]["answer"] == "ok"


def test_required_revision_and_run_pins_never_fall_back(workflow_fixture):
    f = workflow_fixture
    release = _compile_snapshot(f)
    run = _admit(f, "pin-check")
    run.scenario_revision_id = None
    with pytest.raises(RevisionError, match="RUN_REVISION_CONFLICT"):
        run_workflow_graph(run)
    release.execution_contract = "unrecognized"
    with pytest.raises(RevisionError, match="REVISION_CONTRACT_UNSUPPORTED"):
        resolve_bundle(release)


def test_postgres_release_workflow_and_run_pins_are_immutable(workflow_fixture):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL pin guards")
    release = _compile_snapshot(workflow_fixture)
    run = _admit(workflow_fixture, "db-pin-check")
    with pytest.raises(IntegrityError, match="RUN_REVISION_PINS_IMMUTABLE"), transaction.atomic():
        Run.objects.filter(pk=run.pk).update(scenario_revision=None)
    with (
        pytest.raises(IntegrityError, match="RELEASE_EXECUTION_PINS_IMMUTABLE"),
        transaction.atomic(),
    ):
        ScenarioRelease.objects.filter(pk=release.pk).update(execution_contract="legacy")
    with pytest.raises(IntegrityError, match="REVISION_WORKFLOW_IMMUTABLE"), transaction.atomic():
        WorkflowVersion.objects.filter(pk=run.workflow_version_id).update(compiled_graph={})
    assert ScenarioRevision.objects.filter(pk=run.scenario_revision_id).exists()


def test_wait_resume_keeps_snapshot_after_publication_and_catalog_change(
    workflow_fixture, monkeypatch
):
    f = workflow_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async", lambda *a, **k: None
    )
    body = simple_workflow()
    body["spec"]["nodes"].insert(
        1,
        {
            "id": "external",
            "type": "event_wait",
            "config": {
                "event_role": "evidence_ready",
                "timeout_seconds": 60,
                "payload_schema": {
                    "type": "object",
                    "properties": {"approved": {"type": "boolean"}},
                    "required": ["approved"],
                    "additionalProperties": False,
                },
            },
            "output_mapping": [{"from": "/payload/approved", "to": "/decisions/approved"}],
        },
    )
    body["spec"]["edges"][:1] = [
        {"from": "request", "to": "external"},
        {"from": "external", "to": "format"},
    ]
    first = _compile_snapshot(f, body)
    run = _admit(f, "snapshot-wait", background=True)
    waiting = _execute_queued(run)
    assert waiting.status == "waiting_event" and waiting.resume_token is not None
    replacement = simple_workflow()
    replacement["spec"]["nodes"][1]["config"]["template_ref"] = "replacement"
    _compile_snapshot(f, replacement)
    ArtifactVersion.objects.filter(pk=run.workflow_version.source_artifact_id).update(body={})
    cache.clear()
    for _ in range(2):
        resume_run_wait(
            organization_id=f.organization.pk,
            resume_token=waiting.resume_token,
            actor_id="consumer:producer",
            payload={"approved": True},
        )
    run.refresh_from_db()
    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    assert run.release_id == first.pk
    assert run.scenario_revision.source_release_id == first.pk
    assert run.checkpoint["output"]["answer"] == "ok"
    assert run.checkpoint["decisions"] == {"approved": True}
    assert run.waits.count() == 1


def test_snapshot_child_and_parent_resume_keep_their_admitted_revisions(
    workflow_fixture, monkeypatch
):
    from apps.workflows.models import RunChildLink
    from apps.workflows.run_children import converge_run_child
    from apps.workflows.tests.test_unified_children import _parent_run

    f = workflow_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.dispatch_unified_background_run", lambda **kwargs: None
    )
    first_child = _compile_snapshot(f)
    parent = _parent_run(f, execution_contract=ScenarioExecutionContract.SNAPSHOT)
    parent_revision = parent.scenario_revision_id
    assert _execute_queued(parent).status == "waiting_child"
    link = RunChildLink.objects.select_related("child_run").get(parent_run=parent)
    assert link.child_run.scenario_revision_id == first_child.execution_revision.pk
    next_body = simple_workflow()
    next_body["spec"]["nodes"][1]["config"]["template_ref"] = "next-child"
    _compile_snapshot(f, next_body)
    cache.clear()
    assert _execute_queued(link.child_run).status == "completed"
    assert converge_run_child(child_run_id=link.child_run_id, organization_id=f.organization.pk)
    parent.refresh_from_db()
    assert _execute_queued(parent).status == "completed"
    parent.refresh_from_db()
    assert parent.scenario_revision_id == parent_revision
    assert parent.checkpoint["output"]["answer"] == "ok"


@pytest.mark.parametrize("contract", ["", "unknown"])
def test_unknown_explicit_compiler_contract_cannot_fall_back(workflow_fixture, contract):
    from apps.workflows.compiler import WorkflowCompileError
    from apps.workflows.services import compile_workflow_version

    f = workflow_fixture
    workflow = WorkflowVersion.objects.get(scenario=f.scenario)
    with pytest.raises(WorkflowCompileError, match="execution contract is unsupported"):
        compile_workflow_version(
            scenario=f.scenario,
            source_artifact=workflow.source_artifact,
            created_by="test",
            execution_contract=contract,
        )


def test_parallel_deliveries_rejoin_the_original_snapshot_after_new_publication(
    workflow_fixture, monkeypatch
):
    from copy import deepcopy

    from apps.workflows.models import RunJoin
    from apps.workflows.tests.test_unified_parallel import (
        _PARALLEL_EDGES,
        _PARALLEL_NODES,
        _branch_ids,
        _deliver,
    )

    f = workflow_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_run_branch.apply_async", lambda *a, **k: None
    )
    body = simple_workflow()
    body["spec"] = {
        "input_node": "start",
        "nodes": deepcopy(_PARALLEL_NODES),
        "edges": deepcopy(_PARALLEL_EDGES),
    }
    first = _compile_snapshot(f, body)
    run = _admit(f, "snapshot-parallel", background=True)
    assert _execute_queued(run).status == "waiting_child"
    branch_a, branch_b = _branch_ids(run)
    assert _deliver(run, branch_a) == "committed"
    _compile_snapshot(f)
    cache.clear()
    assert _deliver(run, branch_b) == "committed"
    run.refresh_from_db()
    assert _execute_queued(run).status == "completed"
    run.refresh_from_db()
    assert run.release_id == first.pk
    assert run.checkpoint["output"]["answer"] == "ok"
    assert set(run.checkpoint["evidence"]) == {"a", "b"}
    assert RunJoin.objects.filter(run=run, status="succeeded").count() == 1


def test_worker_rejects_revision_compiler_mismatch_before_claim(workflow_fixture, monkeypatch):
    from apps.workflows.background_claims import BackgroundClaimError, claim_background_run

    f = workflow_fixture
    monkeypatch.setattr(
        "apps.workflows.tasks.execute_unified_background_run.apply_async", lambda *a, **k: None
    )
    _compile_snapshot(f)
    run = _admit(f, "snapshot-worker-contract", background=True)
    # Emulate a worker that supports another snapshot compiler contract, without
    # changing the persisted revision or suppressing its database integrity guard.
    monkeypatch.setattr("apps.workflows.background_claims.SNAPSHOT_COMPILER_VERSION", "future")
    with pytest.raises(BackgroundClaimError, match="RUN_BACKGROUND_COMPILER_INCOMPATIBLE"):
        claim_background_run(
            organization_id=f.organization.pk,
            run_id=run.pk,
            claim_token=uuid4(),
            lease_seconds=30,
        )
    run.refresh_from_db()
    assert run.background_claim_token is None and run.status == "queued"


def test_postgres_snapshot_release_requires_revision_before_commit(workflow_fixture):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL deferred revision constraint")
    original = workflow_fixture.release
    with pytest.raises(IntegrityError, match="RELEASE_REVISION_REQUIRED"), transaction.atomic():
        ScenarioRelease.objects.create(
            scenario=original.scenario,
            organization=original.organization,
            execution_contract=ScenarioExecutionContract.SNAPSHOT,
            runtime_version=original.runtime_version,
            manifest=original.manifest,
            artifact_manifest_sha256=original.artifact_manifest_sha256,
            created_by="test",
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS release_revision_required IMMEDIATE")


def test_snapshot_evaluation_and_lifecycle_preserve_revision_and_live_gate():
    from apps.evaluations.services import run_eval
    from apps.releases.lifecycle import LifecycleError, promote, rollback
    from apps.releases.tests.test_lifecycle import _release, _scenario

    scenario = _scenario()
    scenario.execution_contract = ScenarioExecutionContract.SNAPSHOT
    scenario.save(update_fields=["execution_contract"])
    first = _release(scenario)
    original = first.execution_revision.checksum
    with pytest.raises(LifecycleError, match="EVAL_REQUIRED"):
        promote(release=first, actor="test")
    # Neither a changed reusable suite nor workflow may redefine the captured test.
    ArtifactVersion.objects.filter(organization=scenario.organization).update(body={})
    evaluated = run_eval(release=first, created_by="test")
    assert evaluated.status == "passed"
    executed = Run.objects.get(release=first)
    assert executed.scenario_revision_id == first.execution_revision.pk
    promote(release=first, actor="test")
    second = _release(scenario)
    assert run_eval(release=second, created_by="test").status == "passed"
    promote(release=second, actor="test")
    first.refresh_from_db()
    rollback(scenario=scenario, target=first, actor="test")
    first.refresh_from_db()
    assert first.status == "active"
    assert first.execution_revision.checksum == original
