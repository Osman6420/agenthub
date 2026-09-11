"""Executable revision provenance, authorization, immutability and PostgreSQL guards."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.audit.models import AuditEvent
from apps.console.tests.test_candidate_authority import candidate as candidate
from apps.identity.models import ScenarioResponsibilityAssignment
from apps.releases.models import ScenarioRevision
from apps.releases.revision_schema import RevisionError
from apps.releases.revisions import capture_scenario_revision, read_revision_snapshot
from apps.workflows.services import resolve_release_workflow

pytestmark = pytest.mark.django_db


def _capture(f):
    return capture_scenario_revision(
        release=f["release"],
        workflow_version=resolve_release_workflow(f["release"]),
        actor=f["editor"],
        request_id="revision-test",
    )


def test_snapshot_is_detached_immutable_idempotent_and_does_not_move_traffic(candidate):
    revision = _capture(candidate)
    assert revision.number == 1
    assert _capture(candidate).pk == revision.pk
    snapshot = read_revision_snapshot(revision)
    assert snapshot["artifacts"]["workflow_definition"]["id"] == candidate["workflow"].pk
    assert snapshot["data"] == {
        "selection": "legacy_pinned",
        "document_set_ids": [],
        "document_set_version_ids": [],
        "index_version_ids": [],
    }
    snapshot["workflow"]["graph"]["workflow_id"] = "caller-mutated-copy"
    assert (
        read_revision_snapshot(revision)["workflow"]["graph"]["workflow_id"]
        != "caller-mutated-copy"
    )
    # Catalog drift cannot silently rewrite an already captured executable body.
    ArtifactVersion.objects.filter(pk=candidate["workflow"].pk).update(body={"drift": True})
    assert read_revision_snapshot(revision)["artifacts"]["workflow_definition"]["body"] != {
        "drift": True
    }
    candidate["release"].refresh_from_db()
    assert candidate["release"].status == "candidate"
    with pytest.raises(ValidationError, match="immutable"):
        revision.save()
    event = AuditEvent.objects.get(action="scenario.revision.capture", outcome="success")
    assert isinstance(event.after, dict)
    assert event.after["checksum"] == revision.checksum
    assert "body" not in str(event.after) and "graph" not in str(event.after)


def test_capture_works_without_update_privilege_on_immutable_workflow(candidate):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL read-only workflow grant")
    workflow = resolve_release_workflow(candidate["release"])
    role = f"revision_capture_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')  # noqa: S608
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )  # noqa: S608
        cursor.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{role}"')  # noqa: S608
        cursor.execute(f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO "{role}"')  # noqa: S608
        cursor.execute(
            "GRANT UPDATE ON tenancy_organization, catalog_aiproject, "
            f'catalog_scenario, releases_scenariorelease TO "{role}"'
        )  # noqa: S608
        cursor.execute(f'GRANT INSERT ON releases_scenariorevision, audit_auditevent TO "{role}"')  # noqa: S608
        cursor.execute(
            "SELECT has_table_privilege(%s, 'workflows_workflowversion', 'UPDATE')", [role]
        )
        assert cursor.fetchone()[0] is False
        try:
            cursor.execute(f'SET LOCAL ROLE "{role}"')  # noqa: S608
            revision = capture_scenario_revision(
                release=candidate["release"],
                workflow_version=workflow,
                actor=candidate["editor"],
            )
            assert revision.workflow_version_id == workflow.pk
            cursor.execute(
                "SELECT has_function_privilege(%s, 'agenthub_revision_integrity()', 'EXECUTE')",
                [role],
            )
            assert cursor.fetchone()[0] is False
            for denied_scope in ("", "999999999"):
                with pytest.raises(IntegrityError, match="SCENARIO_REVISION_SCOPE_INVALID"):
                    with transaction.atomic():
                        cursor.execute(
                            "SELECT set_config('app.tenant_scope', %s, true)", [denied_scope]
                        )
                        # Even before final INSERT RLS, no elevated workflow lock is allowed.
                        cursor.execute(
                            "INSERT INTO releases_scenariorevision "
                            "(organization_id, scenario_id, workflow_version_id) "
                            "VALUES (%s, %s, %s)",
                            [revision.organization_id, revision.scenario_id, workflow.pk],
                        )
        finally:
            cursor.execute("RESET ROLE")


def test_capture_rechecks_permission_scope_and_audit_failure(candidate, monkeypatch):
    workflow = resolve_release_workflow(candidate["release"])
    with pytest.raises(RevisionError, match="REVISION_CAPTURE_FORBIDDEN"):
        capture_scenario_revision(
            release=candidate["release"], workflow_version=workflow, actor=candidate["viewer"]
        )

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("apps.releases.revisions.record_event", unavailable)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            _capture(candidate)
    assert not ScenarioRevision.objects.exists()
    revision = _capture(candidate)
    ScenarioResponsibilityAssignment.objects.filter(membership__user=candidate["editor"]).update(
        status="revoked", revoked_at=timezone.now(), revoked_by=candidate["editor"]
    )
    with pytest.raises(RevisionError, match="REVISION_CAPTURE_FORBIDDEN"):
        _capture(candidate)
    assert ScenarioRevision.objects.count() == 1 and revision.number == 1


@pytest.mark.parametrize(
    "change", ["checksum", "scope", "compiler", "data_mode", "secret", "too_large", "nan"]
)
def test_snapshot_rejects_corruption_unknown_modes_secrets_and_unbounded_values(candidate, change):
    revision = _capture(candidate)
    if change == "checksum":
        revision.checksum = "0" * 64
    elif change == "scope":
        revision.organization_id += 1000
    elif change == "compiler":
        revision.snapshot["workflow"]["compiler_version"] = ""
    elif change == "data_mode":
        revision.snapshot["data"]["selection"] = "all_tenants"
    elif change == "secret":
        revision.snapshot["manifest"]["authorization"] = "synthetic-inline-secret"
    elif change == "too_large":
        revision.snapshot["manifest"]["padding"] = "x" * (4 * 1024 * 1024)
    else:
        revision.snapshot["manifest"]["invalid_number"] = float("nan")
    with pytest.raises(RevisionError):
        read_revision_snapshot(revision)


def test_missing_or_modified_source_is_not_replaced_with_latest(candidate):
    workflow = resolve_release_workflow(candidate["release"])
    ArtifactVersion.objects.filter(pk=candidate["workflow"].pk).update(checksum="0" * 64)
    with pytest.raises(RevisionError, match="REVISION_ARTIFACT_UNRESOLVED"):
        capture_scenario_revision(
            release=candidate["release"], workflow_version=workflow, actor=candidate["editor"]
        )
    assert not ScenarioRevision.objects.exists()


def test_foreign_data_pin_cannot_be_captured_even_with_a_matching_manifest_checksum(candidate):
    from apps.artifacts.validation import compute_checksum
    from apps.documents.models import DocumentSet, DocumentSetVersion
    from apps.tenancy.models import Organization

    foreign = Organization.objects.create(slug="revision-foreign", name="Foreign")
    document_set = DocumentSet.objects.create(
        organization=foreign, logical_id="foreign", name="Foreign"
    )
    version = DocumentSetVersion.objects.create(
        organization=foreign, document_set=document_set, version=1
    )
    release = candidate["release"]
    release.manifest["document_set_versions"] = [version.pk]
    release.artifact_manifest_sha256 = compute_checksum(release.manifest)
    release.save(update_fields=["manifest", "artifact_manifest_sha256"])
    with pytest.raises(RevisionError, match="REVISION_DATA_SCOPE_INVALID"):
        _capture(candidate)
    assert not ScenarioRevision.objects.exists()


def test_postgres_enforces_immutability_and_tenant_visibility(candidate):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL trigger and FORCE RLS")
    revision = _capture(candidate)
    with pytest.raises(IntegrityError, match="SCENARIO_REVISION_IMMUTABLE"), transaction.atomic():
        ScenarioRevision.objects.filter(pk=revision.pk).update(checksum="0" * 64)
    with pytest.raises(IntegrityError, match="SCENARIO_REVISION_IMMUTABLE"), transaction.atomic():
        ScenarioRevision.objects.filter(pk=revision.pk).delete()
    role = f"revision_rls_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(f'GRANT SELECT ON releases_scenariorevision TO "{role}"')  # noqa: S608
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )  # noqa: S608
        for scope, expected in ((str(candidate["org"].pk), 1), ("", 0), ("999999999", 0)):
            cursor.execute("SELECT set_config('app.tenant_scope', %s, true)", [scope])
            try:
                cursor.execute(f'SET LOCAL ROLE "{role}"')
                cursor.execute("SELECT count(*) FROM releases_scenariorevision")
                assert cursor.fetchone()[0] == expected
            finally:
                cursor.execute("RESET ROLE")


@pytest.mark.django_db(transaction=True)
def test_concurrent_capture_has_one_number_one_receipt(candidate):
    if connection.vendor != "postgresql":
        pytest.skip("Real row lock serialization")
    workflow = resolve_release_workflow(candidate["release"])
    barrier = Barrier(2)

    def capture():
        close_old_connections()
        try:
            barrier.wait()
            return capture_scenario_revision(
                release=candidate["release"], workflow_version=workflow, actor=candidate["editor"]
            ).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: capture(), range(2)))
    assert results[0] == results[1]
    assert ScenarioRevision.objects.count() == 1
    assert (
        AuditEvent.objects.filter(action="scenario.revision.capture", outcome="success").count()
        == 1
    )
