"""Phase 2.9 Part 3 exact release/runtime console surfaces."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agents.models import AgentRuntimeControl, RuntimeControlScope
from apps.catalog.models import AIProject, Scenario
from apps.identity.models import (
    Consumer,
    ConsumerProtocol,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.releases.models import ReleaseCanary, ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus

User = get_user_model()
pytestmark = pytest.mark.django_db


def _scenario(organization: Organization, slug: str) -> Scenario:
    project = AIProject.objects.create(organization=organization, slug=f"p-{slug}", name=slug)
    return Scenario.objects.create(project=project, slug=slug, name=slug)


def _release(scenario: Scenario, status: str = ReleaseStatus.CANDIDATE) -> ScenarioRelease:
    return ScenarioRelease.objects.create(
        scenario=scenario,
        status=status,
        runtime_version="runtime:1",
        manifest={},
        artifact_manifest_sha256=(scenario.slug[0] * 64),
        created_by="qa",
    )


def _assign(username: str, scenario: Scenario, responsibility: str):
    user = User.objects.create_user(username, password="unused")  # noqa: S106
    membership = OrganizationMembership.objects.create(
        organization=scenario.organization,
        user=user,
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=scenario.organization,
        membership=membership,
        scenario=scenario,
        responsibility=responsibility,
        assigned_by=user,
    )
    return user


def test_release_manager_reaches_contextual_lifecycle_and_inventory_is_exact(
    client: Client,
) -> None:
    organization = Organization.objects.create(slug="release-ui", name="Release UI")
    assigned = _scenario(organization, "assigned")
    hidden = _scenario(organization, "hidden")
    release = _release(assigned)
    hidden_release = _release(hidden)
    manager = _assign("release-manager", assigned, ScenarioResponsibility.RELEASE_MANAGER)
    client.force_login(manager)

    inventory = client.get(reverse("console:releases"))
    body = inventory.content.decode()
    assert inventory.status_code == 200
    assert reverse("console:release_detail", args=[release.pk]) in body
    assert reverse("console:release_detail", args=[hidden_release.pk]) not in body

    scenario_body = client.get(
        reverse("console:scenario_detail_public", args=[assigned.public_id])
    ).content.decode()
    expected_created_at = timezone.localtime(release.created_at).strftime("%d.%m.%Y %H:%M")
    assert expected_created_at in scenario_body

    detail = client.get(reverse("console:release_detail", args=[release.pk]))
    detail_body = detail.content.decode()
    assert "Yetkili release'ler" in detail_body
    assert "Eksik: Input contract, Output contract, Eval suite" in detail_body
    assert detail.status_code == 200
    assert reverse("console:release_run_eval", args=[release.pk]) in detail_body
    assert reverse("console:release_promote", args=[release.pk]) in detail_body
    assert reverse("console:canary_start", args=[release.pk]) in detail_body
    assert client.get(reverse("console:release_promote", args=[release.pk])).status_code == 405
    assert (
        client.get(reverse("console:release_detail", args=[hidden_release.pk])).status_code == 404
    )


def test_neighboring_release_role_direct_post_is_denied(client: Client) -> None:
    organization = Organization.objects.create(slug="release-deny", name="Release Deny")
    scenario = _scenario(organization, "assigned")
    release = _release(scenario)
    editor = _assign("release-editor", scenario, ScenarioResponsibility.EDITOR)
    client.force_login(editor)

    response = client.post(reverse("console:release_promote", args=[release.pk]))

    assert response.status_code == 403
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE


def test_disabled_organization_release_actions_are_not_offered(client: Client) -> None:
    organization = Organization.objects.create(slug="release-disabled", name="Disabled")
    scenario = _scenario(organization, "assigned")
    release = _release(scenario)
    consumer = Consumer.objects.create(
        organization=organization,
        subject="disabled-consumer",
        name="Disabled consumer",
        protocol=ConsumerProtocol.REST,
    )
    canary = ReleaseCanary.objects.create(
        organization=organization,
        scenario=scenario,
        consumer=consumer,
        release=release,
        expires_at=timezone.now() + timedelta(hours=1),
        created_by="qa",
    )
    manager = _assign("disabled-release-manager", scenario, ScenarioResponsibility.RELEASE_MANAGER)
    organization.status = OrganizationStatus.DISABLED
    organization.save(update_fields=["status", "updated_at"])
    client.force_login(manager)

    response = client.get(reverse("console:release_detail", args=[release.pk]))
    body = response.content.decode()

    assert response.status_code == 200
    assert reverse("console:release_promote", args=[release.pk]) not in body
    assert reverse("console:canary_stop", args=[canary.pk]) not in body


def test_runtime_operator_pauses_and_resumes_exact_scenario_from_context(client: Client) -> None:
    organization = Organization.objects.create(slug="runtime-ui", name="Runtime UI")
    scenario = _scenario(organization, "assigned")
    operator = _assign("runtime-operator", scenario, ScenarioResponsibility.RUNTIME_OPERATOR)
    client.force_login(operator)
    detail_url = reverse("console:scenario_detail_public", args=[scenario.public_id])

    detail = client.get(detail_url)
    assert detail.status_code == 200
    assert "Exact senaryoyu durdur" in detail.content.decode()
    runs_body = client.get(reverse("console:runs")).content.decode()
    assert "Exact senaryo runtime operator kontrolleri" in runs_body
    assert detail_url in runs_body
    pause = client.post(
        reverse("console:runtime_control_change"),
        {
            "scope_type": "scenario",
            "target": str(scenario.public_id),
            "action": "pause",
            "reason_code": "incident_response",
            "reason": "Exact scenario containment",
            "next": detail_url,
        },
    )
    assert pause.status_code == 302
    assert pause.headers["Location"] == detail_url
    control = AgentRuntimeControl.objects.get(
        scope_type=RuntimeControlScope.SCENARIO,
        scenario=scenario,
    )
    assert control.suspended is True
    assert "Exact senaryoyu devam ettir" in client.get(detail_url).content.decode()

    resume = client.post(
        reverse("console:runtime_control_change"),
        {
            "scope_type": "scenario",
            "target": str(scenario.public_id),
            "action": "resume",
            "reason_code": "manual_safety_stop",
            "reason": "Exact scenario resume",
            "next": detail_url,
        },
    )
    assert resume.status_code == 302
    control.refresh_from_db()
    assert control.suspended is False


def test_runtime_neighbor_and_same_tenant_other_scenario_are_denied(client: Client) -> None:
    organization = Organization.objects.create(slug="runtime-deny", name="Runtime Deny")
    assigned = _scenario(organization, "assigned")
    hidden = _scenario(organization, "hidden")
    operator = _assign("runtime-exact", assigned, ScenarioResponsibility.RUNTIME_OPERATOR)
    client.force_login(operator)
    url = reverse("console:runtime_control_change")
    payload = {
        "scope_type": "scenario",
        "target": str(hidden.public_id),
        "action": "pause",
        "reason_code": "incident_response",
        "reason": "Forged scope",
    }
    assert client.post(url, payload).status_code == 404
    assert not AgentRuntimeControl.objects.exists()

    editor = _assign("runtime-editor", assigned, ScenarioResponsibility.EDITOR)
    client.force_login(editor)
    payload["target"] = str(assigned.public_id)
    assert client.post(url, payload).status_code == 403
    assert not AgentRuntimeControl.objects.exists()
