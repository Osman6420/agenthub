"""Console UX overhaul tests: active-org navigation, dashboard, role-honest affordances,
row-open, document-set simplification, chunk-visibility gating, and run filters.

These cover the presentation-layer changes only; every underlying action remains
server-authorized (the active organization is a display filter, never an access grant).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agents.models import AgentRuntimeControl
from apps.artifacts.models import ArtifactVersion
from apps.catalog.models import AIProject, Scenario
from apps.console import views
from apps.console.context import SESSION_KEY
from apps.documents.models import (
    Document,
    DocumentLifecycle,
    DocumentSet,
    DocumentSetMembership,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    DocumentVersion,
    ParseStatus,
)
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.roles import Role
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.models import WorkflowRun, WorkflowRunStatus, WorkflowVersion

User = get_user_model()
pytestmark = pytest.mark.django_db


def _org(slug: str, name: str | None = None) -> Organization:
    return Organization.objects.create(slug=slug, name=name or slug.title())


def _member(
    username: str, org: Organization, role: str = Role.AUDITOR, *others: Organization
) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    for extra in others:
        OrganizationMembership.objects.create(organization=extra, user=user, role=role)
    return user


def _scenario(org: Organization, slug: str = "s") -> Scenario:
    project = AIProject.objects.create(organization=org, slug=f"p-{slug}", name=f"P {slug}")
    return Scenario.objects.create(
        organization=org, project=project, slug=slug, name=f"Senaryo {slug}", type="rag"
    )


# --------------------------------------------------------------------------- A/B


def test_switch_organization_rejects_non_member(client: Client) -> None:
    own = _org("own")
    foreign = _org("foreign")
    client.force_login(_member("u", own))
    response = client.post(reverse("console:switch_organization"), {"organization_id": foreign.id})
    assert response.status_code == 403
    # Session is not populated with a non-member org.
    assert client.session.get(SESSION_KEY) is None


def test_switch_organization_sets_active_and_rejects_clearing(client: Client) -> None:
    own = _org("own")
    other = _org("other")
    client.force_login(_member("u", own, Role.AUDITOR, other))
    set_response = client.post(reverse("console:switch_organization"), {"organization_id": own.id})
    assert set_response.status_code == 302
    assert client.session.get(SESSION_KEY) == own.id
    clear_response = client.post(reverse("console:switch_organization"), {"organization_id": ""})
    assert clear_response.status_code == 403
    assert client.session.get(SESSION_KEY) == own.id


def test_switch_organization_requires_post(client: Client) -> None:
    own = _org("own")
    client.force_login(_member("u", own))
    assert client.get(reverse("console:switch_organization")).status_code == 405


def test_forged_active_org_in_session_is_cleared(client: Client) -> None:
    own = _org("own")
    foreign = _org("foreign")
    client.force_login(_member("u", own))
    session = client.session
    session[SESSION_KEY] = foreign.id  # never a member
    session.save()
    response = client.get(reverse("console:dashboard"))
    assert response.status_code == 200
    # The forged id is cleared, then the single-membership default is applied.
    assert client.session.get(SESSION_KEY) == own.id
    assert "Own" in response.content.decode()


def test_active_org_narrows_project_list_and_scenarios_live_under_project(client: Client) -> None:
    org_a = _org("a")
    org_b = _org("b")
    _scenario(org_a, "alpha")
    _scenario(org_b, "beta")
    client.force_login(_member("u", org_a, Role.AUDITOR, org_b))

    session = client.session
    session[SESSION_KEY] = org_a.id
    session.save()
    scoped = client.get(reverse("console:projects")).content.decode()
    assert "P alpha" in scoped
    assert "P beta" not in scoped

    # Missing state deterministically restores one authorized workspace, never a
    # cross-organization view.
    session[SESSION_KEY] = None
    session.save()
    defaulted = client.get(reverse("console:projects")).content.decode()
    assert "P alpha" in defaulted
    assert "P beta" not in defaulted
    assert client.get(reverse("console:scenarios")).headers["Location"] == reverse(
        "console:projects"
    )


def test_single_org_user_gets_static_label_not_dropdown(client: Client) -> None:
    org = _org("solo")
    client.force_login(_member("u", org))
    body = client.get(reverse("console:dashboard")).content.decode()
    assert 'id="org-switch"' not in body  # no selector for a single-org user
    assert 'class="org-static"' in body
    assert client.session.get(SESSION_KEY) == org.id


def test_platform_admin_with_one_org_defaults_to_that_workspace(client: Client) -> None:
    User = get_user_model()
    admin = User.objects.create_superuser(username="platform-one", password=None)
    organization = Organization.objects.create(slug="only-platform-org", name="Only platform org")
    client.force_login(admin)

    response = client.get(reverse("console:dashboard"))

    assert response.status_code == 200
    assert client.session.get(SESSION_KEY) == organization.pk
    assert "Tüm organizasyonlar" not in response.content.decode()


def test_multi_org_user_gets_server_post_organization_menu(client: Client) -> None:
    org_a = _org("a")
    org_b = _org("b")
    client.force_login(_member("u", org_a, Role.AUDITOR, org_b))
    body = client.get(reverse("console:dashboard")).content.decode()
    assert '<details class="org-menu">' in body
    assert body.count('name="organization_id"') == 2


# ----------------------------------------------------------------------------- C


def test_dashboard_shows_kill_switch_banner_when_globally_suspended(client: Client) -> None:
    org = _org("org")
    AgentRuntimeControl.objects.create(
        organization=None, suspended=True, updated_by="admin", reason="incident-42"
    )
    client.force_login(_member("u", org))
    body = client.get(reverse("console:dashboard")).content.decode()
    assert "askıya alınmış" in body
    assert "incident-42" in body


def test_dashboard_renders_operational_sections(client: Client) -> None:
    org = _org("org")
    client.force_login(_member("u", org))
    body = client.get(reverse("console:dashboard")).content.decode()
    assert "Şu an ne çalışıyor?" in body
    assert "Bekleyen kararlar" in body
    assert "Yayın durumu" in body


# ----------------------------------------------------------------------------- D


def test_auditor_sees_disabled_studio_button_and_no_builder_link(client: Client) -> None:
    org = _org("org")
    scenario = _scenario(org)
    client.force_login(_member("auditor", org, Role.AUDITOR))
    body = client.get(reverse("console:scenario_detail", args=[scenario.pk])).content.decode()
    assert "Scenario Studio'yu aç" in body
    assert "disabled" in body
    assert "scenario_editor" in body  # the reason names the required role
    # The Studio deep-link carries this scenario; for a read-only role it is a disabled
    # button, so the scenario-scoped builder link must be absent. (The sidebar keeps a
    # plain builder nav link for read-only viewing, which is fine.)
    assert f"scenario={scenario.public_id}" not in body


def test_author_sees_active_studio_link(client: Client) -> None:
    org = _org("org")
    scenario = _scenario(org)
    client.force_login(_member("editor", org, Role.SCENARIO_EDITOR))
    body = client.get(reverse("console:scenario_detail", args=[scenario.pk])).content.decode()
    assert f"scenario={scenario.public_id}" in body  # the scenario-scoped Studio link renders


# ----------------------------------------------------------------------------- E


def test_scenario_rows_are_row_clickable_with_anchor(client: Client) -> None:
    org = _org("org")
    scenario = _scenario(org, "clickable")
    client.force_login(_member("u", org))
    body = client.get(
        reverse("console:project_detail_public", args=[scenario.project.public_id])
    ).content.decode()
    detail = reverse("console:scenario_detail_public", args=[scenario.public_id])
    assert f'href="{detail}"' in body  # keyboard/no-JS anchor kept in the primary cell


# ----------------------------------------------------------------------------- F


def test_documents_list_has_no_advanced_card_but_org_admin_gets_relocated_entry(
    client: Client,
) -> None:
    org = _org("org")
    admin = _member("admin", org, Role.ORGANIZATION_ADMIN)
    client.force_login(admin)
    docs = client.get(reverse("console:documents")).content.decode()
    assert "Gelişmiş saklama yönetimi" not in docs
    assert reverse("console:advanced_document_inventory") not in docs


def _document_in_set(org: Organization) -> tuple[DocumentSet, Document]:
    document_set = DocumentSet.objects.create(organization=org, logical_id="ds", name="Set")
    document = Document.objects.create(
        organization=org,
        logical_id="doc",
        title="Doküman",
        current_version=1,
        lifecycle_state=DocumentLifecycle.ACTIVE,
    )
    version = DocumentVersion.objects.create(
        organization=org,
        document=document,
        version=1,
        checksum="a" * 64,
        mime_type="text/plain",
        object_key="k",
        byte_size=10,
        parse_status=ParseStatus.PARSED,
    )
    for n in (1, 2):
        set_version = DocumentSetVersion.objects.create(
            organization=org,
            document_set=document_set,
            version=n,
            status=DocumentSetVersionStatus.DRAFT if n == 2 else DocumentSetVersionStatus.ACTIVE,
        )
        DocumentSetMembership.objects.create(
            organization=org, document_set_version=set_version, document_version=version, ordinal=0
        )
    return document_set, document


def test_document_set_detail_shows_current_version_and_history(client: Client) -> None:
    org = _org("org")
    document_set, _ = _document_in_set(org)
    client.force_login(_member("u", org))
    body = client.get(
        reverse("console:document_set_detail_public", args=[document_set.public_id])
    ).content.decode()
    assert "Güncel set sürümü v2" in body  # latest version expanded
    assert "Geçmiş sürümler (1)" in body  # older versions collapsed behind a control


# ----------------------------------------------------------------------------- G


def test_document_chunk_view_returns_none_off_postgres() -> None:
    # The per-IndexVersion vector store is PostgreSQL-only; on SQLite the helper degrades to
    # None instead of raising, so the console never shows a broken chunk panel.
    org = _org("org")
    document_set, document = _document_in_set(org)
    versions = list(document.versions.all())
    assert views._document_chunk_view(document_set, versions) is None


def test_document_detail_hides_chunk_section_for_auditor(client: Client) -> None:
    org = _org("org")
    document_set, document = _document_in_set(org)
    client.force_login(_member("auditor", org, Role.AUDITOR))
    response = client.get(
        reverse(
            "console:document_set_document_detail",
            args=[document_set.public_id, document.public_id],
        )
    )
    assert response.status_code == 200
    assert response.context["chunk_view"] is None  # gated off for a read-only role
    assert "İndeks parçaları" not in response.content.decode()


# ----------------------------------------------------------------------------- H


def _workflow_run(
    org: Organization,
    scenario: Scenario,
    release: ScenarioRelease,
    version: WorkflowVersion,
    consumer: Consumer,
    *,
    status: str,
    key: str,
    created_days_ago: int = 0,
) -> WorkflowRun:
    run = WorkflowRun.objects.create(
        organization=org,
        scenario=scenario,
        release=release,
        workflow_version=version,
        consumer=consumer,
        idempotency_key=key,
        input_checksum="d" * 64,
        execution_context={},
        status=status,
        deadline_at=timezone.now() + timedelta(hours=1),
    )
    if created_days_ago:
        WorkflowRun.objects.filter(pk=run.pk).update(
            created_at=timezone.now() - timedelta(days=created_days_ago)
        )
    return run


def _workflow_run_fixture(org: Organization, scenario: Scenario) -> tuple[Any, ...]:
    artifact = ArtifactVersion.objects.create(
        organization=org,
        type="workflow_definition",
        logical_id="wf",
        version=1,
        body={"nodes": {}},
        checksum="a" * 64,
        created_by="t",
    )
    release = ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="rt",
        manifest={"artifacts": {}},
        artifact_manifest_sha256="b" * 64,
        created_by="t",
    )
    version = WorkflowVersion.objects.create(
        organization=org,
        scenario=scenario,
        source_artifact=artifact,
        compiled_graph={"nodes": {}},
        checksum="c" * 64,
        compiler_version="v",
        created_by="t",
    )
    consumer = Consumer.objects.create(
        organization=org, subject="c", name="C", protocol=ConsumerProtocol.REST
    )
    return release, version, consumer


def test_workflow_run_status_and_bucket_filters(client: Client) -> None:
    org = _org("org")
    scenario = _scenario(org)
    release, version, consumer = _workflow_run_fixture(org, scenario)
    _workflow_run(
        org, scenario, release, version, consumer, status=WorkflowRunStatus.RUNNING, key="1"
    )
    _workflow_run(
        org, scenario, release, version, consumer, status=WorkflowRunStatus.FAILED, key="2"
    )
    _workflow_run(
        org, scenario, release, version, consumer, status=WorkflowRunStatus.COMPLETED, key="3"
    )
    client.force_login(_member("u", org))

    url = reverse("console:workflow_runs")
    all_body = client.get(url).content.decode()
    assert all_body.count("<tr data-href") == 3

    failed = client.get(url, {"status": WorkflowRunStatus.FAILED}).content.decode()
    assert failed.count("<tr data-href") == 1

    # The "attention" bucket includes failed/timed_out/recovery_required.
    attention = client.get(url, {"bucket": "attention"}).content.decode()
    assert attention.count("<tr data-href") == 1
    assert "Grup: attention" in attention


def test_run_filters_cannot_widen_beyond_tenant_scope(client: Client) -> None:
    org = _org("org")
    foreign = _org("foreign")
    scenario = _scenario(org)
    foreign_scenario = _scenario(foreign, "fs")
    release, version, consumer = _workflow_run_fixture(org, scenario)
    f_release, f_version, f_consumer = _workflow_run_fixture(foreign, foreign_scenario)
    _workflow_run(
        org, scenario, release, version, consumer, status=WorkflowRunStatus.RUNNING, key="1"
    )
    _workflow_run(
        foreign,
        foreign_scenario,
        f_release,
        f_version,
        f_consumer,
        status=WorkflowRunStatus.RUNNING,
        key="2",
    )
    # Member of ``org`` only; no filter (or any filter) can reveal the foreign run.
    client.force_login(_member("u", org))
    body = client.get(
        reverse("console:workflow_runs"), {"status": WorkflowRunStatus.RUNNING}
    ).content.decode()
    assert body.count("<tr data-href") == 1
    assert "<td>fs</td>" not in body  # the foreign scenario slug never renders as a row


def test_workflow_runs_paginate(client: Client) -> None:
    org = _org("org")
    scenario = _scenario(org)
    release, version, consumer = _workflow_run_fixture(org, scenario)
    for n in range(views._RUN_PAGE_SIZE + 5):
        _workflow_run(
            org,
            scenario,
            release,
            version,
            consumer,
            status=WorkflowRunStatus.COMPLETED,
            key=str(n),
        )
    client.force_login(_member("u", org))
    page1 = client.get(reverse("console:workflow_runs")).content.decode()
    assert page1.count("<tr data-href") == views._RUN_PAGE_SIZE
    assert "Sayfa 1 /" in page1
    page2 = client.get(reverse("console:workflow_runs"), {"page": 2}).content.decode()
    assert page2.count("<tr data-href") == 5
