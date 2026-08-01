"""Legacy split served-index metadata converges before uniqueness constraints apply."""

from __future__ import annotations

import pytest
from django.apps.registry import Apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [
    ("documents", "0008_document_set_quarantine"),
    ("ingestion", "0012_document_profiles_index_automation"),
]
AFTER = [
    ("documents", "0010_active_document_set_version_constraint"),
    ("ingestion", "0013_atomic_served_index_constraint"),
]


def _state_apps(targets: list[tuple[str, str]]) -> Apps:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture(autouse=True)
def restore_leaf_state():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_split_active_index_is_linked_to_the_served_set_version() -> None:
    old_apps = _state_apps(BEFORE)
    Organization = old_apps.get_model("tenancy", "Organization")
    DocumentSet = old_apps.get_model("documents", "DocumentSet")
    DocumentSetVersion = old_apps.get_model("documents", "DocumentSetVersion")
    IndexVersion = old_apps.get_model("ingestion", "IndexVersion")
    organization = Organization.objects.create(slug="legacy-split", name="Legacy")
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="knowledge", name="Knowledge"
    )
    set_version = DocumentSetVersion.objects.create(
        organization=organization,
        document_set=document_set,
        version=1,
        status="promotable",
    )
    index = IndexVersion.objects.create(
        organization=organization,
        document_set_version=set_version,
        version=1,
        status="active",
        store_ready=True,
        dimensions=64,
        index_type="vector",
    )

    current_apps = _state_apps(AFTER)
    CurrentSetVersion = current_apps.get_model("documents", "DocumentSetVersion")
    CurrentIndex = current_apps.get_model("ingestion", "IndexVersion")
    migrated_version = CurrentSetVersion.objects.get(pk=set_version.pk)
    migrated_index = CurrentIndex.objects.get(pk=index.pk)
    assert migrated_version.status == "active"
    assert migrated_version.built_index_version_id == migrated_index.pk
    assert migrated_index.status == "active"
