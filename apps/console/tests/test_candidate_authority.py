"""An exact Scenario Editor can reach an evaluated candidate but can never move traffic."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.catalog.services import create_console_scenario
from apps.evaluations.models import EvalRun
from apps.identity.models import (
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.presets import empty_workflow

User = get_user_model()
pytestmark = pytest.mark.django_db


def _user(org: Organization, username: str, scenario: Scenario, responsibility: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        scenario=scenario,
        responsibility=responsibility,
        assigned_by=user,
    )
    return user


@pytest.fixture
def candidate() -> dict[str, Any]:
    org = Organization.objects.create(slug="authority-org", name="Authority")
    project = AIProject.objects.create(organization=org, slug="project", name="Project")
    scenario = create_console_scenario(project=project, name="Scenario")
    workflow = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="authority_flow",
        logical_description="Authority workflow",
        version_description="Initial",
        body=empty_workflow(logical_id="authority_flow"),
        created_by="author",
    )
    suite = create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.EVAL_SUITE,
        logical_id="authority_suite",
        logical_description="Authority eval suite",
        version_description="Initial",
        body={
            "cases": [
                {
                    "id": "smoke-1",
                    "input": {"query": "Kontrollü bir test sorusu"},
                    "assertions": [{"type": "workflow_completed"}],
                }
            ]
        },
        created_by="author",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                role="workflow_definition",
                type=workflow.type,
                logical_id=workflow.logical_id,
                version=workflow.version,
            ),
            ArtifactRef(
                role="eval_suite",
                type=suite.type,
                logical_id=suite.logical_id,
                version=suite.version,
            ),
        ],
        runtime_version="runtime:v1",
        created_by="release-manager",
    )
    return {
        "org": org,
        "scenario": scenario,
        "workflow": workflow,
        "release": release,
        "editor": _user(org, "authority-editor", scenario, ScenarioResponsibility.EDITOR),
        "viewer": _user(org, "authority-viewer", scenario, ScenarioResponsibility.VIEWER),
    }


def test_scenario_editor_can_preflight_and_compile_a_candidate(
    client: Client, candidate: dict[str, Any]
) -> None:
    scenario: Scenario = candidate["scenario"]
    workflow = candidate["workflow"]
    client.force_login(candidate["editor"])
    payload = {"items": [{"artifact_version_id": workflow.pk, "role": "workflow_definition"}]}

    requirements = client.post(
        reverse("builder_api:release_manifest_requirements", args=[scenario.public_id]),
        data=json.dumps({"workflow_artifact_id": workflow.pk}),
        content_type="application/json",
    )
    assert requirements.status_code == 200

    preflight = client.post(
        reverse("builder_api:release_manifest_preflight", args=[scenario.public_id]),
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert preflight.status_code == 200

    before = ScenarioRelease.objects.filter(scenario=scenario).count()
    compiled = client.post(
        reverse("builder_api:release_manifest_compile", args=[scenario.public_id]),
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert compiled.status_code == 201
    assert ScenarioRelease.objects.filter(scenario=scenario).count() == before + 1
    # Compilation only ever produces a candidate; it never activates anything.
    assert not ScenarioRelease.objects.filter(
        scenario=scenario, status=ReleaseStatus.ACTIVE
    ).exists()


def test_scenario_editor_can_run_required_evaluation(
    client: Client, candidate: dict[str, Any]
) -> None:
    release: ScenarioRelease = candidate["release"]
    client.force_login(candidate["editor"])

    response = client.post(reverse("console:release_run_eval", args=[release.pk]))

    assert response.status_code == 302
    release.refresh_from_db()
    # Evaluation produced a report and left the release status untouched.
    assert release.status == ReleaseStatus.CANDIDATE
    assert EvalRun.objects.filter(release=release).exists()


def test_editor_django_candidate_and_shared_ui_actions_match_builder(client, candidate):
    scenario = candidate["scenario"]
    workflow = candidate["workflow"]
    client.force_login(candidate["editor"])
    detail = client.get(reverse("console:scenario_detail_public", args=[scenario.public_id]))
    actions = detail.context["allowed_actions"]
    assert actions["edit"] and actions["compile"] and actions["test"]
    assert not actions["release"] and not actions["runtime_pause"] and not actions["approve"]
    assert (
        reverse("console:scenario_lifecycle_change", args=[scenario.public_id])
        not in detail.content.decode()
    )
    studio = client.get(
        reverse("console:builder"),
        {
            "organization": candidate["org"].slug,
            "scenario": scenario.public_id,
        },
    )
    assert studio.context["builder_initial"]["allowed_actions"] == actions
    assert (
        client.get(
            reverse("console:scenario_artifact_options", args=[scenario.public_id]),
            {
                "preset": "minimum",
            },
        ).status_code
        == 200
    )
    before = ScenarioRelease.objects.filter(scenario=scenario).count()
    response = client.post(
        reverse("console:scenario_compile_candidate", args=[scenario.public_id]),
        {
            "artifact_ids": [workflow.pk],
            f"role_{workflow.pk}": "workflow_definition",
        },
    )
    assert response.status_code == 302
    assert ScenarioRelease.objects.filter(scenario=scenario).count() == before + 1
    assert not ScenarioRelease.objects.filter(
        scenario=scenario, status=ReleaseStatus.ACTIVE
    ).exists()


def test_candidate_rechecks_revocation_after_http_precheck(client, candidate, monkeypatch):
    from apps.audit.models import AuditEvent
    from apps.releases.authoring import compile_operator_candidate

    scenario = candidate["scenario"]
    workflow = candidate["workflow"]
    client.force_login(candidate["editor"])
    before = ScenarioRelease.objects.count()

    def revoked_before_lock(**kwargs):
        from django.utils import timezone

        ScenarioResponsibilityAssignment.objects.filter(
            scenario=scenario,
            membership__user=candidate["editor"],
        ).update(status="revoked", revoked_at=timezone.now(), revoked_by=candidate["editor"])
        return compile_operator_candidate(**kwargs)

    monkeypatch.setattr("apps.console.views.compile_operator_candidate", revoked_before_lock)
    response = client.post(
        reverse("console:scenario_compile_candidate", args=[scenario.public_id]),
        {
            "artifact_ids": [workflow.pk],
            f"role_{workflow.pk}": "workflow_definition",
            "allowed_actions": '{"compile":true,"release":true}',
        },
    )
    assert response.status_code == 403
    assert ScenarioRelease.objects.count() == before
    assert AuditEvent.objects.filter(
        action="console.scenario.release.compile", outcome="deny"
    ).exists()


@pytest.mark.parametrize(
    "url_name",
    ["console:release_promote", "console:release_rollback"],
)
def test_scenario_editor_is_denied_every_live_traffic_transition(
    client: Client, candidate: dict[str, Any], url_name: str
) -> None:
    release: ScenarioRelease = candidate["release"]
    client.force_login(candidate["editor"])

    response = client.post(reverse(url_name, args=[release.pk]))

    assert response.status_code == 403
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE
    assert not ScenarioRelease.objects.filter(
        scenario=candidate["scenario"], status=ReleaseStatus.ACTIVE
    ).exists()


def test_scenario_editor_is_denied_canary_and_scenario_activation(
    client: Client, candidate: dict[str, Any]
) -> None:
    release: ScenarioRelease = candidate["release"]
    scenario: Scenario = candidate["scenario"]
    client.force_login(candidate["editor"])

    assert client.get(reverse("console:canary_start", args=[release.pk])).status_code == 403
    activate = client.post(
        reverse("console:scenario_lifecycle_change", args=[scenario.public_id]),
        {"action": "activate"},
    )
    assert activate.status_code in {403, 404}
    scenario.refresh_from_db()
    assert scenario.status != "active"


def test_release_page_offers_evaluation_but_no_traffic_controls_to_an_editor(
    client: Client, candidate: dict[str, Any]
) -> None:
    release: ScenarioRelease = candidate["release"]
    client.force_login(candidate["editor"])

    body = client.get(reverse("console:release_detail", args=[release.pk])).content.decode()

    assert reverse("console:release_run_eval", args=[release.pk]) in body
    assert reverse("console:release_promote", args=[release.pk]) not in body
    assert reverse("console:release_rollback", args=[release.pk]) not in body
    assert reverse("console:canary_start", args=[release.pk]) not in body


def test_viewer_can_neither_prepare_nor_evaluate_a_candidate(
    client: Client, candidate: dict[str, Any]
) -> None:
    scenario: Scenario = candidate["scenario"]
    release: ScenarioRelease = candidate["release"]
    client.force_login(candidate["viewer"])

    preflight = client.post(
        reverse("builder_api:release_manifest_preflight", args=[scenario.public_id]),
        data=json.dumps({"items": []}),
        content_type="application/json",
    )
    assert preflight.status_code == 403
    assert client.post(reverse("console:release_run_eval", args=[release.pk])).status_code == 403
    assert not EvalRun.objects.filter(release=release).exists()


def test_foreign_tenant_editor_cannot_reach_the_candidate_surface(
    client: Client, candidate: dict[str, Any]
) -> None:
    scenario: Scenario = candidate["scenario"]
    release: ScenarioRelease = candidate["release"]
    other_org = Organization.objects.create(slug="authority-other", name="Other")
    other_project = AIProject.objects.create(organization=other_org, slug="p", name="P")
    other_scenario = create_console_scenario(project=other_project, name="Other scenario")
    outsider = _user(other_org, "authority-outsider", other_scenario, ScenarioResponsibility.EDITOR)
    client.force_login(outsider)

    preflight = client.post(
        reverse("builder_api:release_manifest_preflight", args=[scenario.public_id]),
        data=json.dumps({"items": []}),
        content_type="application/json",
    )
    assert preflight.status_code == 404
    assert client.post(reverse("console:release_run_eval", args=[release.pk])).status_code == 404
