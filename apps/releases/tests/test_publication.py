"""Atomic publication, exact retries and fail-closed operator boundaries."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.builder.models import WorkflowDraft
from apps.catalog.models import ScenarioExecutionContract
from apps.console.tests.test_scenario_step_actions import setup as setup
from apps.evaluations.models import EvalRun
from apps.identity.models import ScenarioResponsibilityAssignment
from apps.releases import publication as service
from apps.releases.models import ScenarioPublication, ScenarioRelease
from apps.workflows.models import Run

pytestmark = pytest.mark.django_db(transaction=True)


def submit(setup, **kwargs):
    _, _, scenario, actor = setup
    scenario.refresh_from_db()
    return service.publish_scenario(
        actor=actor,
        scenario=scenario,
        intent=kwargs.pop("intent", uuid4()),
        expected=kwargs.pop("expected", service.publication_token(scenario)),
        **kwargs,
    )


@pytest.mark.parametrize("contract", ScenarioExecutionContract.values)
def test_publish_once_and_replay_preserves_exact_work(setup, contract):
    scenario = setup[2]
    scenario.execution_contract = contract
    scenario.data_selection = "legacy_pinned"
    scenario.save(update_fields=["execution_contract", "data_selection"])
    receipt = submit(setup)
    scenario.refresh_from_db()
    receipt.refresh_from_db()
    assert scenario.status == "active" and receipt.release.status == "active"
    assert receipt.completed_at is not None and receipt.evaluation.status == "passed"
    count = Run.objects.count()
    same = submit(setup, intent=receipt.public_id, expected=receipt.request_checksum)
    assert same.pk == receipt.pk and Run.objects.count() == count
    assert ScenarioRelease.objects.count() == EvalRun.objects.count() == 1
    if contract == ScenarioExecutionContract.SNAPSHOT:
        assert receipt.release.execution_revision.pk is not None
    assert AuditEvent.objects.filter(action="scenario.publication.completed").count() == 1


def test_stale_review_and_revoked_actor_create_nothing(setup):
    scenario, actor = setup[2:]
    token = service.publication_token(scenario)
    draft = WorkflowDraft.objects.get(scenario=scenario)
    draft.revision += 1
    draft.save(update_fields=["revision"])
    with pytest.raises(service.PublicationError, match="SETTINGS_CHANGED"):
        submit(setup, expected=token)
    ScenarioResponsibilityAssignment.objects.filter(membership__user=actor).update(
        status="revoked", revoked_at=timezone.now(), revoked_by=actor
    )
    with pytest.raises(PermissionDenied):
        submit(setup)
    assert not ScenarioPublication.objects.exists()
    assert not ScenarioRelease.objects.exists()
    assert set(
        AuditEvent.objects.filter(action="scenario.publication.blocked").values_list(
            "reason", flat=True
        )
    ) == {"PUBLICATION_SETTINGS_CHANGED", "PUBLICATION_FORBIDDEN"}


@pytest.mark.parametrize(
    "change", ["draft", "permission", "account", "binding", "alias", "audit", "readiness"]
)
def test_failure_after_evaluation_preserves_previous_live_release(setup, monkeypatch, change):
    original = submit(setup)
    scenario, actor = setup[2:]
    resume = service.resume_eval

    def change_during_eval(**kwargs):
        assert not connection.in_atomic_block
        result = resume(**kwargs)
        if change == "draft":
            draft = WorkflowDraft.objects.get(scenario=scenario)
            draft.revision += 1
            draft.save(update_fields=["revision"])
        elif change == "permission":
            ScenarioResponsibilityAssignment.objects.filter(membership__user=actor).update(
                status="revoked", revoked_at=timezone.now(), revoked_by=actor
            )
        elif change == "alias":
            scenario.aliases.update(status="disabled")
        elif change == "account":
            type(actor).objects.filter(pk=actor.pk).update(is_active=False)
        elif change == "binding":
            from apps.documents.models import DocumentSet, ScenarioDocumentSetBinding

            document_set = DocumentSet.objects.create(
                organization_id=scenario.organization_id, logical_id="late-binding", name="Late"
            )
            ScenarioDocumentSetBinding.objects.create(
                organization_id=scenario.organization_id,
                scenario=scenario,
                document_set=document_set,
            )
        return result

    monkeypatch.setattr(service, "resume_eval", change_during_eval)
    record = service.record_event

    def fail_audit(**kwargs):
        if kwargs["action"] == "scenario.publication.completed":
            raise RuntimeError("audit unavailable")
        return record(**kwargs)

    def not_ready(*args):
        raise service.PublicationError("INDEX_NOT_READY")

    if change == "audit":
        monkeypatch.setattr(service, "record_event", fail_audit)
    if change == "readiness":
        monkeypatch.setattr(service, "_assert_release_indexes_served", not_ready)
    with pytest.raises((service.PublicationError, PermissionDenied, RuntimeError)):
        submit(setup)
    original.release.refresh_from_db()
    assert original.release.status == "active"
    latest = ScenarioPublication.objects.first()
    assert latest.pk != original.pk and latest.completed_at is None
    assert latest.release.status == "candidate" and latest.evaluation.status == "passed"


def test_process_loss_then_resume_reuses_prepared_candidate(setup, monkeypatch):
    intent = uuid4()
    expected = service.publication_token(setup[2])

    def lost(**kwargs):
        raise SystemExit("lost process")

    with monkeypatch.context() as patch:
        patch.setattr(service, "resume_eval", lost)
        with pytest.raises(SystemExit):
            submit(setup, intent=intent, expected=expected)
    pending = ScenarioPublication.objects.get(public_id=intent)
    assert pending.evaluation.status == "pending" and pending.completed_at is None
    completed = submit(setup, intent=intent, expected=expected)
    assert completed.pk == pending.pk and completed.completed_at is not None
    assert ScenarioRelease.objects.count() == EvalRun.objects.count() == 1


def test_superseded_receipt_replay_never_reactivates_old_release(setup):
    first = submit(setup)
    second = submit(setup)
    replay = submit(setup, intent=first.public_id, expected=first.request_checksum)
    assert replay.pk == first.pk and replay.release.status == "superseded"
    second.release.refresh_from_db()
    assert second.release.status == "active" and EvalRun.objects.count() == 2


def test_pending_stale_intent_stops_before_resuming_paid_work(setup, monkeypatch):
    scenario, actor = setup[2:]
    receipt = service._prepare(
        actor=actor,
        scenario=scenario,
        intent=uuid4(),
        expected=service.publication_token(scenario),
        request_id="test-pending",
    )
    draft = WorkflowDraft.objects.get(scenario=scenario)
    draft.revision += 1
    draft.save(update_fields=["revision"])

    def unexpected(**kwargs):
        pytest.fail("Stale intent must not execute")

    monkeypatch.setattr(service, "resume_eval", unexpected)
    with pytest.raises(service.PublicationError, match="SETTINGS_CHANGED"):
        submit(setup, intent=receipt.public_id, expected=receipt.request_checksum)
    assert not Run.objects.exists()


def test_other_live_replacement_is_preserved_at_final_commit(setup):
    from apps.evaluations.services import run_eval
    from apps.releases.lifecycle import promote

    initial = submit(setup)
    scenario, actor = setup[2:]
    scenario.refresh_from_db()
    receipt = service._prepare(
        actor=actor,
        scenario=scenario,
        intent=uuid4(),
        expected=service.publication_token(scenario),
        request_id="baseline-race",
    )
    service.resume_eval(eval_run_id=receipt.evaluation_id, organization_id=scenario.organization_id)
    # Another authorized lifecycle entry can choose the exact previously evaluated
    # composition while this publication is outside its final transaction.
    other = ScenarioRelease.objects.create(
        organization=initial.release.organization,
        scenario=scenario,
        runtime_version=initial.release.runtime_version,
        manifest=initial.release.manifest,
        artifact_manifest_sha256=initial.release.artifact_manifest_sha256,
        created_by=actor.get_username(),
    )
    assert run_eval(release=other, created_by=actor.get_username()).status == "passed"
    promote(release=other, actor=actor.get_username())
    with pytest.raises(service.PublicationError, match="SETTINGS_CHANGED"):
        service._finish(publication=receipt, actor=actor, scenario=scenario, request_id="race-end")
    other.refresh_from_db()
    receipt.refresh_from_db()
    assert other.status == "active" and receipt.release.status == "candidate"
    assert receipt.completed_at is None


def test_failed_evaluation_requires_explicit_new_attempt(setup, monkeypatch):
    from apps.evaluations import services as evaluation_services
    from apps.evaluations.services import EvalError

    def provider_down(**kwargs):
        raise EvalError("PROVIDER_UNAVAILABLE")

    monkeypatch.setattr(evaluation_services, "_execute_case", provider_down)
    intent = uuid4()
    token = service.publication_token(setup[2])
    for _ in range(2):
        with pytest.raises(service.PublicationError, match="EVALUATION_NOT_PASSED"):
            submit(setup, intent=intent, expected=token)
    assert EvalRun.objects.count() == 1 and EvalRun.objects.get().status == "error"
    assert ScenarioRelease.objects.get().status == "candidate"


def test_postgresql_seals_receipt_release_evaluation_and_case(setup):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL SQL guards")
    receipt = submit(setup)
    queries = [
        lambda: ScenarioPublication.objects.filter(pk=receipt.pk).update(created_by="forged"),
        lambda: ScenarioPublication.objects.filter(pk=receipt.pk).update(completed_at=None),
        lambda: ScenarioRelease.objects.filter(pk=receipt.release_id).update(runtime_version="x"),
        lambda: EvalRun.objects.filter(pk=receipt.evaluation_id).update(suite_checksum="0" * 64),
        lambda: receipt.evaluation.case_results.update(passed=False),
    ]
    for change in queries:
        with pytest.raises(DatabaseError, match="IMMUTABLE"), transaction.atomic():
            change()


def test_other_authorized_manager_cannot_resume_someone_elses_intent(setup):
    from apps.console.tests.test_candidate_authority import _user
    from apps.identity.models import ScenarioResponsibility

    receipt = submit(setup)
    other = _user(setup[0], "other-publisher", setup[2], ScenarioResponsibility.MANAGER)
    with pytest.raises(PermissionDenied):
        service.publish_scenario(
            actor=other,
            scenario=setup[2],
            intent=receipt.public_id,
            expected=receipt.request_checksum,
        )
    assert ScenarioPublication.objects.count() == EvalRun.objects.count() == 1


def test_concurrent_publication_uses_one_intent_and_one_evaluation(setup, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL ownership and row locks")
    from apps.evaluations import services as evaluations
    from apps.evaluations.services import EvalError

    scenario, actor = setup[2:]
    intent, token = uuid4(), service.publication_token(scenario)
    entered, finish = Event(), Event()
    execute = evaluations._execute_case

    def paused(**kwargs):
        entered.set()
        assert finish.wait(15)
        return execute(**kwargs)

    monkeypatch.setattr(evaluations, "_execute_case", paused)

    def publish():
        close_old_connections()
        try:
            return service.publish_scenario(
                actor=actor, scenario=scenario, intent=intent, expected=token
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(publish)
        try:
            assert entered.wait(15)
            with pytest.raises(EvalError, match="EVALUATION_ALREADY_RUNNING"):
                service.publish_scenario(
                    actor=actor, scenario=scenario, intent=intent, expected=token
                )
        finally:
            finish.set()
        assert result.result().completed_at is not None
    assert ScenarioPublication.objects.count() == EvalRun.objects.count() == 1


def test_receipt_rls_and_nonempty_migration_rollback_are_fail_closed(setup):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RLS and guarded DDL")
    receipt = submit(setup)
    role = f"publication_rls_{uuid4().hex[:12]}"
    # DDL role changes are transactional and discarded with this probe.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
            cursor.execute(f'GRANT SELECT ON releases_scenariopublication TO "{role}"')
            cursor.execute(
                f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
            )  # noqa: S608
            for scope, expected in ((str(setup[0].pk), 1), ("", 0), ("999999999", 0)):
                cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [scope])
                cursor.execute(f'SET LOCAL ROLE "{role}"')
                try:
                    cursor.execute("SELECT count(*) FROM releases_scenariopublication")
                    assert cursor.fetchone()[0] == expected
                finally:
                    cursor.execute("RESET ROLE")
        transaction.set_rollback(True)
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    try:
        with pytest.raises(RuntimeError, match="ROLLBACK_REQUIRES_EMPTY_HISTORY"):
            executor.migrate([("releases", "0005_execution_revision_binding")])
        assert ScenarioPublication.objects.get(pk=receipt.pk).completed_at is not None
    finally:
        MigrationExecutor(connection).migrate(current)


def test_empty_publication_migration_roundtrip():
    executor = MigrationExecutor(connection)
    current = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("releases", "0005_execution_revision_binding")])
        MigrationExecutor(connection).migrate(current)
        assert not ScenarioPublication.objects.exists()
    finally:
        MigrationExecutor(connection).migrate(current)


def test_postgresql_rejects_forged_lineage_and_unfinished_completion(setup):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL lineage and completion guards")
    from apps.tenancy.models import Organization

    scenario, actor = setup[2:]
    receipt = service._prepare(
        actor=actor,
        scenario=scenario,
        intent=uuid4(),
        expected=service.publication_token(scenario),
        request_id="pending-lineage",
    )
    with pytest.raises(DatabaseError, match="COMPLETION_INVALID"), transaction.atomic():
        ScenarioPublication.objects.filter(pk=receipt.pk).update(completed_at=timezone.now())
    foreign = Organization.objects.create(slug="foreign-publication", name="Foreign")
    forged = ScenarioPublication(
        public_id=uuid4(),
        organization=foreign,
        scenario=scenario,
        draft=receipt.draft,
        release=receipt.release,
        evaluation=receipt.evaluation,
        created_by=str(actor.pk),
        request_checksum=receipt.request_checksum,
        prepared_checksum=receipt.prepared_checksum,
    )
    with pytest.raises(DatabaseError, match="SCOPE_INVALID"), transaction.atomic():
        ScenarioPublication.objects.bulk_create([forged])
    assert ScenarioPublication.objects.count() == 1
