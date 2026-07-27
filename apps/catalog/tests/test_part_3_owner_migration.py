from __future__ import annotations

import pytest
from django.apps.registry import Apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("catalog", "0005_public_ids_constrain")]
AFTER = [("catalog", "0006_aiproject_owner_membership")]


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


def test_owner_membership_backfill_preserves_legacy_text_and_reforwards() -> None:
    old_apps = _state_apps(BEFORE)
    User = old_apps.get_model("auth", "User")
    Organization = old_apps.get_model("tenancy", "Organization")
    Membership = old_apps.get_model("tenancy", "OrganizationMembership")
    Project = old_apps.get_model("catalog", "AIProject")

    organization = Organization.objects.create(slug="migration-org", name="Migration Org")
    user = User.objects.create(username="matched-owner")
    membership = Membership.objects.create(
        organization=organization, user=user, role="project_owner"
    )
    Project.objects.create(
        organization=organization, slug="matched", name="Matched", owner="matched-owner"
    )
    Project.objects.create(
        organization=organization, slug="unmatched", name="Unmatched", owner="legacy-only"
    )
    Project.objects.create(organization=organization, slug="blank", name="Blank", owner="")

    current_apps = _state_apps(AFTER)
    CurrentProject = current_apps.get_model("catalog", "AIProject")
    matched = CurrentProject.objects.get(slug="matched")
    unmatched = CurrentProject.objects.get(slug="unmatched")
    blank = CurrentProject.objects.get(slug="blank")
    assert matched.owner == "matched-owner"
    assert matched.owner_membership_id == membership.pk
    assert unmatched.owner == "legacy-only"
    assert unmatched.owner_membership_id is None
    assert blank.owner == ""
    assert blank.owner_membership_id is None

    _state_apps(BEFORE)
    reforwarded_apps = _state_apps(AFTER)
    ReforwardedProject = reforwarded_apps.get_model("catalog", "AIProject")
    assert ReforwardedProject.objects.get(slug="matched").owner_membership_id == membership.pk
    assert ReforwardedProject.objects.get(slug="unmatched").owner == "legacy-only"
