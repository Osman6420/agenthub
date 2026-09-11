from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("identity", "0007_globaladministrator")]
AFTER = [("identity", "0008_delegated_assignments")]


def _state_apps(targets: list[tuple[str, str]]) -> Any:
    # These historical model classes deliberately differ from the live registry
    # understood by django-stubs (some no longer exist after later migrations).
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


def test_assignment_migration_reverses_and_reforwards() -> None:
    old_apps = _state_apps(BEFORE)
    assert "ProjectAdministratorAssignment" not in {
        model.__name__ for model in old_apps.get_models()
    }

    current_apps = _state_apps(AFTER)
    for model_name in (
        "ProjectAdministratorAssignment",
        "ScenarioEditorAssignment",
        "DocumentSetManagerAssignment",
    ):
        assert current_apps.get_model("identity", model_name) is not None

    _state_apps(BEFORE)
    reforwarded_apps = _state_apps(AFTER)
    assert reforwarded_apps.get_model("identity", "ProjectAdministratorAssignment") is not None
