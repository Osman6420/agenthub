"""Management commands enforce release-manager authorization and the eval gate."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.evaluations.models import EvalRun
from apps.evaluations.services import run_eval
from apps.identity.roles import Role
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.presets import empty_workflow

SUITE = {
    "cases": [
        {
            "id": "c1",
            "input": {"query": "q"},
            "assertions": [{"type": "workflow_completed"}],
        }
    ]
}


def _evaluated_release() -> tuple[Organization, ScenarioRelease]:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(project=project, slug="info", name="Info")
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.EVAL_SUITE,
        logical_id="s",
        body=SUITE,
        created_by="alice",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="workflow",
        body=empty_workflow(logical_id="workflow"),
        created_by="alice",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("eval_suite", ArtifactType.EVAL_SUITE, "s", 1),
            ArtifactRef(
                "workflow_definition",
                ArtifactType.WORKFLOW_DEFINITION,
                "workflow",
                1,
            ),
        ],
        runtime_version="rt:3",
        created_by="alice",
    )
    run_eval(release=release, created_by="alice")
    return org, release


def _manager(org: Organization, username: str = "rm") -> None:
    user = get_user_model().objects.create_user(username=username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=Role.ORGANIZATION_ADMIN,
    )


@pytest.mark.django_db
def test_promote_command_denied_for_non_manager() -> None:
    _org, release = _evaluated_release()
    get_user_model().objects.create_user(username="ns", password="x")  # noqa: S106
    with pytest.raises(CommandError, match="not authorized"):
        call_command("promote_release", "--release", str(release.pk), "--actor", "ns")
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE


@pytest.mark.django_db
def test_promote_command_denied_for_unknown_actor() -> None:
    _org, release = _evaluated_release()
    with pytest.raises(CommandError, match="not authorized"):
        call_command("promote_release", "--release", str(release.pk), "--actor", "ghost")


@pytest.mark.django_db
def test_promote_command_promotes_for_organization_admin() -> None:
    org, release = _evaluated_release()
    _manager(org)
    call_command("promote_release", "--release", str(release.pk), "--actor", "rm")
    release.refresh_from_db()
    assert release.status == ReleaseStatus.ACTIVE


@pytest.mark.django_db
def test_run_eval_command_creates_a_run() -> None:
    org, release = _evaluated_release()
    _manager(org)
    call_command("run_eval", "--release", str(release.pk), "--actor", "rm")
    # The helper already ran one eval; the command adds a second.
    assert EvalRun.objects.filter(release=release).count() == 2
