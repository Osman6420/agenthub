"""Phase 2.8 Part 1 task-oriented console information architecture."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import AIProject, Scenario
from apps.console.context import SESSION_KEY
from apps.documents.models import (
    DocumentSet,
    DocumentSetVersion,
    DocumentSetVersionStatus,
)
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
)
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member(org: Organization, *, username: str = "operator") -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(
        organization=org,
        user=user,
    )
    OrganizationResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    return user


def _project(org: Organization, *, slug: str = "support") -> AIProject:
    return AIProject.objects.create(
        organization=org,
        slug=slug,
        name="Destek Projesi",
    )


def test_sidebar_exposes_only_task_oriented_primary_navigation(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    client.force_login(_member(org))

    body = client.get(reverse("console:dashboard")).content.decode()
    sidebar = body.split('<aside class="sidebar">', maxsplit=1)[1].split("</aside>", maxsplit=1)[0]

    assert ">Ana Sayfa</a>" in sidebar
    assert ">Projeler</a>" in sidebar
    assert ">Dokümanlar</a>" in sidebar
    assert ">İstemciler</a>" in sidebar
    assert ">Çalıştırmalar</a>" in sidebar
    for removed in (
        "Organizasyonlar",
        "Senaryolar",
        "Workflow izleri",
        "Recovery kararları",
        "DSL / grafik",
        "Artifact’ler",
        "Release’ler",
    ):
        assert removed not in sidebar


def test_user_and_logout_are_in_topbar_not_sidebar(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    client.force_login(_member(org, username="alice"))

    body = client.get(reverse("console:dashboard")).content.decode()
    sidebar = body.split('<aside class="sidebar">', maxsplit=1)[1].split("</aside>", maxsplit=1)[0]
    topbar = body.split('<header class="topbar">', maxsplit=1)[1].split("</header>", maxsplit=1)[0]

    assert "alice" not in sidebar
    assert "alice" in topbar
    assert "Çıkış yap" in topbar
    assert "Oturum açık" not in body


def test_organization_menu_uses_direct_post_buttons_without_javascript(client: Client) -> None:
    first = Organization.objects.create(slug="first", name="First")
    second = Organization.objects.create(slug="second", name="Second")
    user = _member(first)
    OrganizationMembership.objects.create(organization=second, user=user)
    client.force_login(user)

    body = client.get(reverse("console:dashboard")).content.decode()

    assert '<details class="org-menu">' in body
    assert "data-autosubmit" not in body
    assert 'name="organization_id"' in body
    assert f'value="{second.id}"' in body
    assert 'name="next"' not in body

    response = client.post(
        reverse("console:switch_organization"), {"organization_id": str(second.id)}
    )
    assert response.headers["Location"] == reverse("console:dashboard")
    assert client.session[SESSION_KEY] == second.id


def test_dashboard_health_keeps_only_kpis_and_links_to_filtered_lists(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    project = _project(org)
    scenario = Scenario.objects.create(
        organization=org, project=project, slug="waiting", name="Waiting"
    )
    client.force_login(_member(org))

    body = client.get(reverse("console:dashboard")).content.decode()

    for category in (
        "no-active-release",
        "active-canary",
        "promotable-index",
        "failed-index-build",
    ):
        assert reverse("console:health_issues", args=[category]) in body
    assert reverse("console:scenario_detail_public", args=[scenario.public_id]) not in body
    assert "Release bekliyor" not in body
    assert "İndeks aktivasyon bekliyor" not in body


def test_health_results_list_exact_scenarios_and_document_sets(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    unhealthy_project = _project(org)
    healthy_project = AIProject.objects.create(
        organization=org, slug="healthy", name="Healthy Project"
    )
    Scenario.objects.create(
        organization=org,
        project=unhealthy_project,
        slug="waiting",
        name="Waiting",
    )
    healthy_scenario = Scenario.objects.create(
        organization=org,
        project=healthy_project,
        slug="ready",
        name="Ready",
    )
    ScenarioRelease.objects.create(
        scenario=healthy_scenario,
        status="active",
        runtime_version="runtime/v1",
        manifest={},
        artifact_manifest_sha256="a" * 64,
        created_by="test",
    )
    promotable_set = DocumentSet.objects.create(
        organization=org, logical_id="promotable", name="Promotable Set"
    )
    other_set = DocumentSet.objects.create(organization=org, logical_id="other", name="Other Set")
    set_version = DocumentSetVersion.objects.create(
        organization=org,
        document_set=promotable_set,
        version=1,
        status=DocumentSetVersionStatus.ACTIVE,
    )
    IndexVersion.objects.create(
        organization=org,
        document_set_version=set_version,
        version=1,
        status=IndexStatus.PROMOTABLE,
    )
    client.force_login(_member(org))

    scenarios = client.get(
        reverse("console:health_issues", args=["no-active-release"])
    ).content.decode()
    documents = client.get(
        reverse("console:health_issues", args=["promotable-index"])
    ).content.decode()

    assert "Waiting" in scenarios
    assert healthy_scenario.name not in scenarios
    assert (
        reverse(
            "console:scenario_detail_public", args=[Scenario.objects.get(slug="waiting").public_id]
        )
        in scenarios
    )
    assert promotable_set.name in documents
    assert other_set.name not in documents
    assert (
        reverse("console:document_set_detail_public", args=[promotable_set.public_id]) in documents
    )


@pytest.mark.parametrize(
    ("route_name", "target_name"),
    [
        ("console:organizations", "console:dashboard"),
        ("console:scenarios", "console:projects"),
        ("console:artifacts", "console:projects"),
        ("console:releases", "console:projects"),
    ],
)
def test_legacy_catalog_gets_redirect_to_authorized_context(
    client: Client, route_name: str, target_name: str
) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    client.force_login(_member(org))

    response = client.get(reverse(route_name))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse(target_name)


def test_legacy_catalog_post_is_not_downgraded_to_get_redirect(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    client.force_login(_member(org))

    response = client.post(reverse("console:scenarios"))

    assert response.status_code == 405
    assert "Location" not in response.headers


def test_organization_workspace_selects_authorized_org_then_redirects_home(
    client: Client,
) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    client.force_login(_member(org))

    response = client.get(reverse("console:organization_detail", args=[org.slug]))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("console:dashboard")
    assert client.session[SESSION_KEY] == org.pk


def test_runs_landing_groups_existing_authorized_run_surfaces(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    client.force_login(_member(org))

    response = client.get(reverse("console:runs"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Çalıştırmalar" in body
    assert reverse("console:workflow_runs") in body


def test_project_and_document_lists_put_object_name_before_organization(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    project = _project(org)
    DocumentSet.objects.create(organization=org, logical_id="knowledge", name="Bilgi Bankası")
    client.force_login(_member(org))

    projects = client.get(reverse("console:projects")).content.decode()
    documents = client.get(reverse("console:documents")).content.decode()

    assert projects.index("<th>Proje</th>") < projects.index("<th>Organizasyon</th>")
    project_row = projects.split("<tbody>", maxsplit=1)[1].split("</tbody>", maxsplit=1)[0]
    assert project_row.index(project.name) < project_row.index(org.name)
    assert documents.index("<th>Doküman seti</th>") < documents.index("<th>Organizasyon</th>")


def test_project_is_scenario_entry_point_with_accessible_tabs(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    project = _project(org)
    scenario = Scenario.objects.create(
        organization=org,
        project=project,
        slug="answer",
        name="Yanıt Senaryosu",
    )
    operator = _member(org)
    ProjectResponsibilityAssignment.objects.create(
        organization=org,
        membership=OrganizationMembership.objects.get(organization=org, user=operator),
        project=project,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=operator,
    )
    client.force_login(operator)

    response = client.get(reverse("console:project_detail_public", args=[project.public_id]))
    body = response.content.decode()

    assert response.status_code == 200
    assert 'role="tablist"' in body
    assert 'aria-current="page">Senaryolar' in body
    assert reverse("console:scenario_detail_public", args=[scenario.public_id]) in body
    create_url = reverse("console:project_scenario_create", args=[project.public_id])
    assert create_url in body
    assert "Bu projede senaryo yok" not in body

    create_response = client.get(create_url)
    assert create_response.status_code == 200
    assert "project" not in create_response.context["form"].fields


def test_scenario_breadcrumb_and_task_tabs_preserve_project_context(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    project = _project(org)
    scenario = Scenario.objects.create(
        organization=org,
        project=project,
        slug="answer",
        name="Yanıt Senaryosu",
    )
    client.force_login(_member(org))

    body = client.get(
        reverse("console:scenario_detail_public", args=[scenario.public_id])
    ).content.decode()

    assert reverse("console:dashboard") in body
    assert reverse("console:project_detail_public", args=[project.public_id]) in body
    assert 'role="tablist"' in body
    for label in ("Genel", "Dokümanlar", "Yapılandırma", "Release’ler"):
        assert label in body


def test_document_set_uses_task_tabs_for_existing_sections(client: Client) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    document_set = DocumentSet.objects.create(
        organization=org,
        logical_id="knowledge",
        name="Bilgi Bankası",
    )
    client.force_login(_member(org))

    body = client.get(
        reverse("console:document_set_detail_public", args=[document_set.public_id])
    ).content.decode()

    assert 'role="tablist"' in body
    for label in ("Genel", "Dokümanlar", "Sürümler ve indeks", "Kaynaklar"):
        assert label in body
    assert "scroll-margin-top: 84px" in body
    assert (
        body.count(reverse("console:document_set_connectors_public", args=[document_set.public_id]))
        == 1
    )
    assert '<div class="card" id="sources">' in body


def test_document_lifecycle_does_not_mix_old_active_index_with_new_draft(
    client: Client,
) -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    document_set = DocumentSet.objects.create(
        organization=org, logical_id="knowledge", name="Bilgi Bankası"
    )
    active_version = DocumentSetVersion.objects.create(
        organization=org,
        document_set=document_set,
        version=1,
        status=DocumentSetVersionStatus.ACTIVE,
    )
    IndexVersion.objects.create(
        organization=org,
        document_set_version=active_version,
        version=1,
        status=IndexStatus.ACTIVE,
        store_ready=True,
    )
    DocumentSetVersion.objects.create(
        organization=org,
        document_set=document_set,
        version=2,
        status=DocumentSetVersionStatus.DRAFT,
    )
    client.force_login(_member(org))

    response = client.get(
        reverse("console:document_set_detail_public", args=[document_set.public_id])
    )
    steps = response.context["lifecycle_steps"]

    assert [step["complete"] for step in steps] == [False, False, False, False, False, False]
    assert "set v1 serviste" in steps[-1]["detail"]
    assert steps[2]["action"] is None
    assert steps[3]["action"] is None
