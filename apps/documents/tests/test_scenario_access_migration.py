from __future__ import annotations

import uuid

import pytest
from django.apps.registry import Apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet, ScenarioDocumentSetGrant
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("documents", "0005_public_ids_constrain")]
AFTER = [("documents", "0006_scenario_document_set_access")]


def _state_apps(targets: list[tuple[str, str]]) -> Apps:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture(autouse=True)
def restore_full_migration_state():
    """Re-apply every leaf migration afterwards.

    Reversing one app cascades to whatever depends on it, so a test left pinned at an old target
    silently drops other apps' tables for the rest of the session.
    """
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_scenario_access_migration_reverses_and_reforwards() -> None:
    old_apps = _state_apps(BEFORE)
    model_names = {model.__name__ for model in old_apps.get_models()}
    assert "ScenarioDocumentSetAccessRequest" not in model_names
    assert "ScenarioDocumentSetGrant" not in model_names

    current_apps = _state_apps(AFTER)
    assert current_apps.get_model("documents", "ScenarioDocumentSetAccessRequest") is not None
    assert current_apps.get_model("documents", "ScenarioDocumentSetGrant") is not None

    _state_apps(BEFORE)
    reforwarded = _state_apps(AFTER)
    assert reforwarded.get_model("documents", "ScenarioDocumentSetGrant") is not None


@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_scenario_access_tables_have_canonical_forced_rls() -> None:
    for table in (
        "documents_scenariodocumentsetaccessrequest",
        "documents_scenariodocumentsetgrant",
    ):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                [table],
            )
            assert cursor.fetchone() == (True, True)
            cursor.execute(
                "SELECT policyname FROM pg_policies WHERE tablename = %s",
                [table],
            )
            assert cursor.fetchall() == [("tenant_isolation",)]


@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_scenario_grant_is_hidden_outside_tenant_scope() -> None:
    organization = Organization.objects.create(slug="grant-rls", name="Grant RLS")
    project = AIProject.objects.create(organization=organization, slug="p", name="P")
    scenario = Scenario.objects.create(
        organization=organization,
        project=project,
        slug="s",
        name="S",
    )
    document_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="set",
        name="Set",
    )
    actor = get_user_model().objects.create_user(username="grant-rls-actor", password=None)
    ScenarioDocumentSetGrant.objects.create(
        organization=organization,
        scenario=scenario,
        document_set=document_set,
        granted_by=actor,
        granted_at=timezone.now(),
    )
    role = f"grant_rls_{uuid.uuid4().hex[:12]}"
    table = "documents_scenariodocumentsetgrant"

    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(f'GRANT SELECT ON "{table}" TO "{role}"')  # noqa: S608
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'  # noqa: S608
        )
        cursor.execute("SELECT set_config('app.tenant_scope', %s, false)", [str(organization.pk)])
        cursor.execute(f'SET ROLE "{role}"')
        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
        own_count = cursor.fetchone()[0]
        cursor.execute("RESET ROLE")
        assert own_count == 1

        cursor.execute(
            "SELECT set_config('app.tenant_scope', %s, false)",
            [str(organization.pk + 99_999)],
        )
        cursor.execute(f'SET ROLE "{role}"')
        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
        foreign_count = cursor.fetchone()[0]
        cursor.execute("RESET ROLE")
        assert foreign_count == 0
