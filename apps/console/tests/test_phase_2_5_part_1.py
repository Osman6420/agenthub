"""Phase 2.5 Part 1 dashboard, organization overview and navigation security tests."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet, DocumentSetGrant, ScenarioDocumentSetBinding
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.roles import Role
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus
from apps.tenancy.services import can_admin_org, can_author_scenarios, can_manage_releases

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member(username: str, organization: Organization, role: str = Role.AUDITOR) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=organization, user=user, role=role)
    return user


def _scenario(organization: Organization, slug: str = "yardim") -> Scenario:
    project = AIProject.objects.create(
        organization=organization, slug=f"proje-{slug}", name=f"Proje {slug}"
    )
    return Scenario.objects.create(
        organization=organization,
        project=project,
        slug=slug,
        name=f"Senaryo {slug}",
        type="rag",
    )


def test_dashboard_lists_authorized_active_and_disabled_organizations(client: Client) -> None:
    active = Organization.objects.create(slug="aktif", name="Aktif Kurum")
    disabled = Organization.objects.create(
        slug="pasif", name="Pasif Kurum", status=OrganizationStatus.DISABLED
    )
    foreign = Organization.objects.create(slug="yabanci", name="Yabancı Kurum")
    user = _member("member", active)
    OrganizationMembership.objects.create(organization=disabled, user=user, role=Role.AUDITOR)
    client.force_login(user)

    response = client.get(reverse("console:dashboard"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Aktif Kurum" in body
    assert "Pasif Kurum" in body
    assert "Yabancı Kurum" not in body
    assert reverse("console:organization_detail", args=[active.slug]) in body
    assert reverse("console:organization_detail", args=[disabled.slug]) in body
    assert foreign.slug not in body


def test_organization_overview_is_tenant_scoped_and_cross_links_inventory(client: Client) -> None:
    organization = Organization.objects.create(slug="kurum", name="Kurum")
    foreign = Organization.objects.create(slug="gizli", name="Gizli Kurum")
    scenario = _scenario(organization)
    foreign_scenario = _scenario(foreign, "gizli")
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="bilgi", name="Bilgi Seti"
    )
    consumer = Consumer.objects.create(
        organization=organization,
        subject="portal",
        name="Portal İstemcisi",
        protocol=ConsumerProtocol.REST,
    )
    artifact = ArtifactVersion.objects.create(
        organization=organization,
        type="prompt_template",
        logical_id="cevap",
        version=1,
        body={"template": "Yanıtla"},
        checksum="a" * 64,
        created_by="test",
    )
    release = ScenarioRelease.objects.create(
        scenario=scenario,
        status="candidate",
        runtime_version="runtime/v1",
        manifest={
            "artifacts": {
                "prompt": {
                    "type": artifact.type,
                    "ref": artifact.ref,
                    "checksum": artifact.checksum,
                }
            }
        },
        artifact_manifest_sha256="b" * 64,
        created_by="test",
    )
    user = _member("auditor", organization)
    client.force_login(user)

    response = client.get(reverse("console:organization_detail", args=[organization.slug]))
    body = response.content.decode()

    assert response.status_code == 200
    for name in [
        scenario.project.name,
        scenario.name,
        document_set.name,
        consumer.name,
        artifact.ref,
    ]:
        assert name in body
    assert reverse("console:project_detail", args=[scenario.project_id]) in body
    assert reverse("console:scenario_detail", args=[scenario.id]) in body
    assert reverse("console:document_set_detail", args=[document_set.id]) in body
    assert reverse("console:consumer_detail", args=[consumer.id]) in body
    assert reverse("console:artifact_detail", args=[artifact.id]) in body
    assert reverse("console:release_detail", args=[release.id]) in body
    assert "auditor" in body
    release_body = client.get(reverse("console:release_detail", args=[release.id])).content.decode()
    assert reverse("console:artifact_detail", args=[artifact.id]) in release_body
    assert foreign_scenario.name not in body
    assert (
        client.get(reverse("console:organization_detail", args=[foreign.slug])).status_code == 404
    )


def test_disabled_organization_is_readable_but_rejects_direct_mutation(client: Client) -> None:
    organization = Organization.objects.create(
        slug="pasif", name="Pasif", status=OrganizationStatus.DISABLED
    )
    scenario = _scenario(organization)
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="bilgi", name="Bilgi"
    )
    editor = _member("editor", organization, Role.ORGANIZATION_ADMIN)
    client.force_login(editor)

    detail = client.get(reverse("console:organization_detail", args=[organization.slug]))
    mutation = client.post(
        reverse("console:scenario_bind_document_set", args=[scenario.id]),
        {"document_set_id": document_set.id},
    )

    assert detail.status_code == 200
    assert "salt okunur" in detail.content.decode().lower()
    assert mutation.status_code == 403
    assert can_admin_org(editor, organization.id) is False
    assert can_author_scenarios(editor, organization.id) is False
    assert can_manage_releases(editor, organization.id) is False


def test_platform_admin_cannot_mutate_disabled_organization() -> None:
    organization = Organization.objects.create(
        slug="pasif", name="Pasif", status=OrganizationStatus.DISABLED
    )
    root = User.objects.create_superuser("root", "root@example.com", "x")  # noqa: S106

    assert can_admin_org(root, organization.id) is False
    assert can_author_scenarios(root, organization.id) is False
    assert can_manage_releases(root, organization.id) is False


def test_disabled_organization_is_not_offered_by_creation_forms(client: Client) -> None:
    active = Organization.objects.create(slug="aktif", name="Aktif")
    disabled = Organization.objects.create(
        slug="pasif", name="Pasif", status=OrganizationStatus.DISABLED
    )
    root = User.objects.create_superuser("root", "root@example.com", "x")  # noqa: S106
    client.force_login(root)

    response = client.get(reverse("console:project_create"))
    body = response.content.decode()

    assert response.status_code == 200
    assert f'value="{active.id}"' in body
    assert f'value="{disabled.id}"' not in body


def test_detail_pages_are_cross_tenant_safe_and_keep_canonical_urls(client: Client) -> None:
    own = Organization.objects.create(slug="kendi", name="Kendi")
    foreign = Organization.objects.create(slug="yabanci", name="Yabancı")
    own_scenario = _scenario(own, "kendi")
    foreign_scenario = _scenario(foreign, "yabanci")
    foreign_consumer = Consumer.objects.create(
        organization=foreign,
        subject="foreign-client",
        name="Yabancı İstemci",
        protocol=ConsumerProtocol.REST,
    )
    foreign_release = ScenarioRelease.objects.create(
        scenario=foreign_scenario,
        status="candidate",
        runtime_version="runtime/v1",
        manifest={"artifacts": {}},
        artifact_manifest_sha256="c" * 64,
        created_by="test",
    )
    client.force_login(_member("member", own))

    assert reverse("console:scenario_detail", args=[own_scenario.id]) == (
        f"/console/scenarios/{own_scenario.id}/"
    )
    assert (
        client.get(
            reverse("console:project_detail", args=[foreign_scenario.project_id])
        ).status_code
        == 404
    )
    assert (
        client.get(reverse("console:consumer_detail", args=[foreign_consumer.id])).status_code
        == 404
    )
    assert (
        client.get(reverse("console:release_detail", args=[foreign_release.id])).status_code == 404
    )


def test_organization_and_target_details_narrow_transaction_scope(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization = Organization.objects.create(slug="kurum", name="Kurum")
    scenario = _scenario(organization)
    client.force_login(_member("member", organization))
    calls: list[int] = []
    monkeypatch.setattr("apps.console.views.set_tenant_context", calls.append)

    assert (
        client.get(reverse("console:organization_detail", args=[organization.slug])).status_code
        == 200
    )
    assert client.get(reverse("console:scenario_detail", args=[scenario.id])).status_code == 200

    assert calls == [organization.id, organization.id]


def test_scenario_document_set_consumer_and_release_names_cross_link(client: Client) -> None:
    organization = Organization.objects.create(slug="kurum", name="Kurum")
    scenario = _scenario(organization)
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="bilgi", name="Bilgi"
    )
    consumer = Consumer.objects.create(
        organization=organization,
        subject="portal",
        name="Portal",
        protocol=ConsumerProtocol.REST,
    )
    ConsumerBinding.objects.create(
        organization=organization,
        consumer=consumer,
        scenario=scenario,
        capabilities=["query"],
    )
    ScenarioDocumentSetBinding.objects.create(
        organization=organization, scenario=scenario, document_set=document_set
    )
    DocumentSetGrant.objects.create(
        organization=organization,
        document_set=document_set,
        principal_type="consumer",
        principal_ref=str(consumer.id),
        permission="retrieve",
    )
    release = ScenarioRelease.objects.create(
        scenario=scenario,
        status="candidate",
        runtime_version="runtime/v1",
        manifest={"artifacts": {}},
        artifact_manifest_sha256="d" * 64,
        created_by="test",
    )
    client.force_login(_member("auditor", organization))

    scenario_body = client.get(
        reverse("console:scenario_detail", args=[scenario.id])
    ).content.decode()
    consumer_body = client.get(
        reverse("console:consumer_detail", args=[consumer.id])
    ).content.decode()
    release_body = client.get(reverse("console:release_detail", args=[release.id])).content.decode()

    assert reverse("console:consumer_detail", args=[consumer.id]) in scenario_body
    assert reverse("console:scenario_detail", args=[scenario.id]) in consumer_body
    assert reverse("console:document_set_detail", args=[document_set.id]) in consumer_body
    assert reverse("console:scenario_detail", args=[scenario.id]) in release_body
