"""Console release-lifecycle actions are role-gated, POST-only, and fail safely."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.identity.roles import Role
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.presets import empty_workflow

User = get_user_model()
SUITE = {"cases": [{"id": "c1", "input": {"query": "q"}, "assertions": [{"type": "grounded"}]}]}


def _candidate(org: Organization) -> ScenarioRelease:
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
        logical_id="flow",
        body=empty_workflow(logical_id="flow"),
        created_by="alice",
    )
    return compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("workflow_definition", ArtifactType.WORKFLOW_DEFINITION, "flow", 1),
            ArtifactRef("eval_suite", ArtifactType.EVAL_SUITE, "s", 1),
        ],
        runtime_version="rt:3",
        created_by="alice",
    )


def _login(client: Client, org: Organization, role: str, username: str = "u") -> None:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    client.force_login(user)


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Role.AUDITOR, Role.RELEASE_MANAGER])
def test_non_release_authority_cannot_promote(client: Client, role: str) -> None:
    org = Organization.objects.create(slug="mcm", name="MCM")
    release = _candidate(org)
    _login(client, org, role)
    response = client.post(reverse("console:release_promote", args=[release.pk]))
    assert response.status_code == 403
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE


@pytest.mark.django_db
def test_manager_promote_without_eval_is_denied_gracefully(client: Client) -> None:
    org = Organization.objects.create(slug="mcm", name="MCM")
    release = _candidate(org)
    _login(client, org, Role.ORGANIZATION_ADMIN)
    response = client.post(reverse("console:release_promote", args=[release.pk]))
    assert response.status_code == 302  # denial is surfaced as a message, not a crash
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE


@pytest.mark.django_db
def test_promote_action_is_post_only(client: Client) -> None:
    org = Organization.objects.create(slug="mcm", name="MCM")
    release = _candidate(org)
    _login(client, org, Role.ORGANIZATION_ADMIN)
    response = client.get(reverse("console:release_promote", args=[release.pk]))
    assert response.status_code == 405
