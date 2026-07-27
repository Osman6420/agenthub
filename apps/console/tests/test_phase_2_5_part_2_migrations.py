from __future__ import annotations

import pytest
from django.apps.registry import Apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

PRE_EXPAND = [
    ("catalog", "0002_scenario_organization"),
    ("documents", "0002_documentsetgrant_scenariodocumentsetbinding"),
    ("identity", "0003_direct_tenant_lineage"),
]
EXPANDED = [
    ("catalog", "0003_public_ids_expand"),
    ("documents", "0003_public_ids_expand"),
    ("identity", "0004_consumer_public_id_expand"),
]
CONSTRAINED = [
    ("catalog", "0005_public_ids_constrain"),
    ("documents", "0005_public_ids_constrain"),
    ("identity", "0006_consumer_public_id_constrain"),
]
LATEST = [
    ("catalog", "0006_aiproject_owner_membership"),
    ("documents", "0005_public_ids_constrain"),
    ("identity", "0006_consumer_public_id_constrain"),
]


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


def test_public_id_migrations_backfill_preserve_and_reforward() -> None:
    old_apps = _state_apps(PRE_EXPAND)
    Organization = old_apps.get_model("tenancy", "Organization")
    Project = old_apps.get_model("catalog", "AIProject")
    Scenario = old_apps.get_model("catalog", "Scenario")
    Document = old_apps.get_model("documents", "Document")
    DocumentSet = old_apps.get_model("documents", "DocumentSet")
    Consumer = old_apps.get_model("identity", "Consumer")

    organization = Organization.objects.create(slug="migration-org", name="Migration Org")
    project = Project.objects.create(organization=organization, slug="project", name="Project")
    Scenario.objects.create(
        organization=organization, project=project, slug="scenario", name="Scenario", type="rag"
    )
    Document.objects.create(organization=organization, logical_id="document")
    DocumentSet.objects.create(organization=organization, logical_id="set", name="Set")
    Consumer.objects.create(
        organization=organization, subject="consumer", name="Consumer", protocol="rest"
    )

    current_apps = _state_apps(CONSTRAINED)
    model_keys = [
        ("catalog", "AIProject", "slug", "project"),
        ("catalog", "Scenario", "slug", "scenario"),
        ("documents", "Document", "logical_id", "document"),
        ("documents", "DocumentSet", "logical_id", "set"),
        ("identity", "Consumer", "subject", "consumer"),
    ]
    public_ids: dict[tuple[str, str], object] = {}
    for app_label, model_name, lookup, value in model_keys:
        model = current_apps.get_model(app_label, model_name)
        row = model.objects.get(**{lookup: value})
        assert row.public_id is not None
        public_ids[(app_label, model_name)] = row.public_id

    _state_apps(EXPANDED)
    reforwarded_apps = _state_apps(CONSTRAINED)
    for app_label, model_name, lookup, value in model_keys:
        model = reforwarded_apps.get_model(app_label, model_name)
        row = model.objects.get(**{lookup: value})
        assert row.public_id == public_ids[(app_label, model_name)]

    # Migration tests share the test database schema; restore the current leaf for later tests.
    _state_apps(LATEST)
