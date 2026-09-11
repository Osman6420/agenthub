"""Scenario discovery and section navigation preserve existing object scope."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.catalog.models import AIProject, Scenario
from apps.console.context import SESSION_KEY
from apps.console.navigation import navigation_context
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def navigation_data() -> Any:
    org = Organization.objects.create(slug="nav-a", name="Navigation A")
    other = Organization.objects.create(slug="nav-b", name="Navigation B")
    project = AIProject.objects.create(organization=org, slug="p", name="Project A")
    foreign = AIProject.objects.create(organization=other, slug="p", name="Foreign project")
    scenario = Scenario.objects.create(
        organization=org, project=project, slug="visible", name="Visible scenario"
    )
    sibling = Scenario.objects.create(
        organization=org, project=project, slug="sibling", name="Hidden sibling"
    )
    hidden = Scenario.objects.create(
        organization=other, project=foreign, slug="foreign", name="Foreign scenario"
    )
    user = get_user_model().objects.create_user("navigation-reader")
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    assignment = ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=user,
    )
    return SimpleNamespace(**locals())


def test_scenario_list_exposes_only_current_exact_scope(
    client: Client, navigation_data: Any
) -> None:
    data = navigation_data
    client.force_login(data.user)
    response = client.get(reverse("console:scenarios"))
    assert response.status_code == 200
    assert list(response.context["scenarios"]) == [data.scenario]
    body = response.content.decode()
    assert data.scenario.name in body
    assert data.sibling.name not in body
    assert data.hidden.name not in body
    assert 'aria-current="page">Senaryolar</a>' in body
    assert 'href="/console/question-sets/"' not in body
    assert response.context["can_create_any"] is False
    assert (
        client.get(reverse("console:scenarios"), {"project": data.project.public_id}).context[
            "can_create"
        ]
        is False
    )
    assert (
        client.get(
            reverse("console:scenario_detail_public", args=[data.sibling.public_id])
        ).status_code
        == 404
    )
    assert (
        client.get(
            reverse("console:scenario_detail_public", args=[data.hidden.public_id])
        ).status_code
        == 404
    )


def test_scenario_list_requires_login_and_rejects_post(client: Client) -> None:
    response = client.get(reverse("console:scenarios"))
    assert response.status_code == 302
    assert "/login/" in response.headers["Location"]


def test_unassigned_and_revoked_members_get_no_scenarios(
    client: Client, navigation_data: Any
) -> None:
    data = navigation_data
    data.assignment.delete()
    client.force_login(data.user)
    response = client.get(reverse("console:scenarios"))
    assert not list(response.context["scenarios"])
    sidebar = response.content.decode().split('<aside class="sidebar">')[1].split("</aside>")[0]
    assert ">Senaryolar</a>" not in sidebar
    assert client.post(reverse("console:scenarios")).status_code == 405


@pytest.mark.parametrize("project", ["invalid", "00000000-0000-0000-0000-000000000000"])
def test_invalid_project_filter_is_not_ignored(
    client: Client, navigation_data: Any, project: str
) -> None:
    client.force_login(navigation_data.user)
    assert client.get(reverse("console:scenarios"), {"project": project}).status_code == 404


def test_foreign_filter_cannot_widen_scope(client: Client, navigation_data: Any) -> None:
    client.force_login(navigation_data.user)
    response = client.get(
        reverse("console:scenarios"), {"project": navigation_data.foreign.public_id}
    )
    assert response.status_code == 404
    session = client.session
    session[SESSION_KEY] = navigation_data.other.pk
    session.save()
    response = client.get(reverse("console:scenarios"))
    assert list(response.context["scenarios"]) == [navigation_data.scenario]


def test_filters_pagination_and_creation_keep_project_context(
    client: Client, navigation_data: Any
) -> None:
    data = navigation_data
    ProjectResponsibilityAssignment.objects.create(
        organization=data.org,
        membership=data.membership,
        project=data.project,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=data.user,
    )
    OrganizationResponsibilityAssignment.objects.create(
        organization=data.org,
        membership=data.membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=data.user,
    )
    Scenario.objects.bulk_create(
        [
            Scenario(
                organization=data.org, project=data.project, slug=f"match-{i}", name=f"Match {i:02}"
            )
            for i in range(28)
        ]
    )
    client.force_login(data.user)
    query = {"q": "Match", "project": str(data.project.public_id), "status": "draft"}
    response = client.get(reverse("console:scenarios"), query)
    assert response.context["page"].paginator.count == 28
    assert len(response.context["scenarios"]) == 25
    assert response.context["can_create"] is True
    body = response.content.decode()
    assert reverse("console:project_scenario_create", args=[data.project.public_id]) in body
    assert f"q=Match&amp;project={data.project.public_id}&amp;status=draft&amp;page=2" in body
    second = client.get(reverse("console:scenarios"), {**query, "page": "2"})
    assert len(second.context["scenarios"]) == 3
    assert (
        client.get(reverse("console:scenarios"), {**query, "page": "bad"}).context["page"].number
        == 1
    )
    data.org.status = "disabled"
    data.org.save(update_fields=["status"])
    assert client.get(reverse("console:scenarios"), query).context["can_create"] is False


def test_search_is_bounded_and_escaped(client: Client, navigation_data: Any) -> None:
    client.force_login(navigation_data.user)
    response = client.get(
        reverse("console:scenarios"), {"q": '<script>alert("x")</script>', "status": "invalid"}
    )
    assert "<script>alert" not in response.content.decode()
    assert "&lt;script&gt;" in response.content.decode()
    assert response.context["status_filter"] == ""
    response = client.get(reverse("console:scenarios"), {"q": "x" * 300})
    assert len(response.context["search"]) == 200


@pytest.mark.parametrize(
    ("name", "section"),
    [
        ("dashboard", "dashboard"),
        ("organization_create", "dashboard"),
        ("project_detail_public", "projects"),
        ("project_create", "projects"),
        ("scenarios", "scenarios"),
        ("scenario_detail_public", "scenarios"),
        ("project_scenario_create", "scenarios"),
        ("builder", "scenarios"),
        ("release_detail", "scenarios"),
        ("artifact_detail", "scenarios"),
        ("documents", "documents"),
        ("document_set_document_detail", "documents"),
        ("connector_source_detail", "documents"),
        ("advanced_document_inventory", "documents"),
        ("question_set_detail", "questions"),
        ("question_evaluation_detail", "questions"),
        ("consumer_create", "consumers"),
        ("binding_create", "consumers"),
        ("workflow_run_detail", "runs"),
        ("tool_approvals", "approvals"),
        ("retention_operations", "platform"),
        ("organization_members", "members"),
        ("platform_profile_create", "platform"),
    ],
)
def test_route_families_have_stable_parent_navigation(name: str, section: str) -> None:
    request = RequestFactory().get("/console/")
    request.resolver_match = SimpleNamespace(url_name=name, kwargs={})  # type: ignore[assignment]
    context = navigation_context(request)
    assert context["navigation_section"] == section
    assert str(context["navigation_url"]).startswith("/console/")


def test_active_organization_narrows_multi_membership_list(
    client: Client, navigation_data: Any
) -> None:
    data = navigation_data
    for org in (data.org, data.other):
        membership, _ = OrganizationMembership.objects.get_or_create(
            organization=org, user=data.user
        )
        OrganizationResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            responsibility=OrganizationResponsibility.ADMINISTRATOR,
            assigned_by=data.user,
        )
    client.force_login(data.user)
    session = client.session
    session[SESSION_KEY] = data.other.pk
    session.save()
    response = client.get(reverse("console:scenarios"))
    assert list(response.context["scenarios"]) == [data.hidden]
