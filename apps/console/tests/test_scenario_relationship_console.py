"""P9.1 scenario-centred document-set and consumer relationship console tests."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario, ScenarioAlias
from apps.documents.models import DocumentSet, DocumentSetGrant, ScenarioDocumentSetBinding
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.roles import Role
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.models import ReleaseStatus
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.presets import empty_workflow

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member(username: str, organization: Organization, role: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=organization, user=user, role=role)
    return user


def _scenario(organization: Organization, slug: str = "yardim") -> Scenario:
    project = AIProject.objects.create(
        organization=organization, slug=f"proje-{slug}", name=f"Proje {slug}"
    )
    return Scenario.objects.create(
        project=project,
        slug=slug,
        name=f"Senaryo {slug}",
        status="active",
    )


def _consumer(organization: Organization, scenario: Scenario, subject: str) -> Consumer:
    consumer = Consumer.objects.create(
        organization=organization,
        subject=subject,
        name=f"Consumer {subject}",
        protocol=ConsumerProtocol.REST,
    )
    ConsumerBinding.objects.create(
        consumer=consumer, scenario=scenario, capabilities=["workflow_run"]
    )
    return consumer


def test_scenario_detail_shows_relationship_and_effective_consumer_access(
    client: Client,
) -> None:
    organization = Organization.objects.create(slug="kurum", name="Kurum")
    scenario = _scenario(organization)
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="bilgi", name="Bilgi Bankası"
    )
    consumer = _consumer(organization, scenario, "portal")
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
    client.force_login(_member("auditor", organization, Role.AUDITOR))

    response = client.get(reverse("console:scenario_detail", args=[scenario.id]))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Senaryo yardim" in body
    assert "Bilgi Bankası" in body
    assert "Consumer portal" in body
    assert "Doküman erişimi var" in body
    assert "Set bağını kaldır" not in body


def test_scenario_detail_is_tenant_scoped(client: Client) -> None:
    organization_a = Organization.objects.create(slug="a", name="A")
    organization_b = Organization.objects.create(slug="b", name="B")
    foreign_scenario = _scenario(organization_b)
    client.force_login(_member("member-a", organization_a, Role.AUDITOR))

    response = client.get(reverse("console:scenario_detail", args=[foreign_scenario.id]))

    assert response.status_code == 404


def test_scenario_and_consumer_show_protocol_specific_invocation_guidance(
    client: Client,
) -> None:
    organization = Organization.objects.create(slug="kurum", name="Kurum")
    scenario = _scenario(organization)
    ScenarioAlias.objects.create(
        organization=organization, scenario=scenario, alias="proje-yardim-ab12"
    )
    workflow = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="guidance_flow",
        logical_description="Invocation guidance workflow",
        version_description="Initial synchronous release",
        body=empty_workflow(logical_id="guidance_flow"),
        created_by="test",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                role="workflow_definition",
                type=workflow.type,
                logical_id=workflow.logical_id,
                version=workflow.version,
            )
        ],
        runtime_version="runtime:v1",
        created_by="test",
    )
    release.status = ReleaseStatus.ACTIVE
    release.save(update_fields=["status"])
    rest_consumer = _consumer(organization, scenario, "portal")
    mcp_consumer = Consumer.objects.create(
        organization=organization,
        subject="mcp-client",
        name="MCP Client",
        protocol=ConsumerProtocol.MCP,
    )
    ConsumerBinding.objects.create(
        consumer=mcp_consumer, scenario=scenario, capabilities=["workflow_run"]
    )
    client.force_login(_member("auditor-guidance", organization, Role.AUDITOR))

    scenario_response = client.get(reverse("console:scenario_detail", args=[scenario.id]))
    scenario_body = scenario_response.content.decode()
    assert scenario_response.status_code == 200
    assert "/v1/chat/completions" in scenario_body
    assert "/v1/responses" in scenario_body
    assert "proje-yardim-ab12" in scenario_body
    assert "POST /mcp/" in scenario_body

    rest_response = client.get(
        reverse("console:consumer_detail_public", args=[rest_consumer.public_id])
    )
    assert rest_response.status_code == 200
    assert "/v1/chat/completions" in rest_response.content.decode()

    mcp_response = client.get(
        reverse("console:consumer_detail_public", args=[mcp_consumer.public_id])
    )
    assert mcp_response.status_code == 200
    assert "yalnız <code>POST /mcp/</code>" in mcp_response.content.decode()


def test_author_manages_relationships_from_scenario_screen(client: Client) -> None:
    organization = Organization.objects.create(slug="kurum", name="Kurum")
    scenario = _scenario(organization)
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="bilgi", name="Bilgi"
    )
    consumer = _consumer(organization, scenario, "portal")
    client.force_login(_member("editor", organization, Role.SCENARIO_EDITOR))

    response = client.post(
        reverse("console:scenario_bind_document_set", args=[scenario.id]),
        {"document_set_id": document_set.id},
    )
    assert response.status_code == 302
    binding = ScenarioDocumentSetBinding.objects.get(scenario=scenario, document_set=document_set)

    response = client.post(
        reverse("console:scenario_grant_consumer", args=[scenario.id, document_set.id]),
        {"consumer_id": consumer.id},
    )
    assert response.status_code == 302
    grant = DocumentSetGrant.objects.get(document_set=document_set, principal_ref=str(consumer.id))

    response = client.post(
        reverse("console:scenario_revoke_consumer", args=[scenario.id, grant.id])
    )
    assert response.status_code == 302
    assert not DocumentSetGrant.objects.filter(pk=grant.id).exists()

    response = client.post(
        reverse("console:scenario_unbind_document_set", args=[scenario.id, binding.id])
    )
    assert response.status_code == 302
    assert not ScenarioDocumentSetBinding.objects.filter(pk=binding.id).exists()
    assert set(
        AuditEvent.objects.filter(
            action__in=[
                "documents.binding.create",
                "documents.grant.create",
                "documents.grant.remove",
                "documents.binding.remove",
            ]
        ).values_list("action", flat=True)
    ) == {
        "documents.binding.create",
        "documents.grant.create",
        "documents.grant.remove",
        "documents.binding.remove",
    }


def test_non_author_cannot_mutate_from_scenario_screen(client: Client) -> None:
    organization = Organization.objects.create(slug="kurum", name="Kurum")
    scenario = _scenario(organization)
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="bilgi", name="Bilgi"
    )
    client.force_login(_member("auditor", organization, Role.AUDITOR))

    response = client.post(
        reverse("console:scenario_bind_document_set", args=[scenario.id]),
        {"document_set_id": document_set.id},
    )

    assert response.status_code == 403
    assert not ScenarioDocumentSetBinding.objects.exists()


def test_cross_tenant_targets_cannot_change_scenario_relationships(
    client: Client,
) -> None:
    organization_a = Organization.objects.create(slug="a", name="A")
    organization_b = Organization.objects.create(slug="b", name="B")
    scenario_a = _scenario(organization_a, "a")
    scenario_b = _scenario(organization_b, "b")
    set_b = DocumentSet.objects.create(
        organization=organization_b, logical_id="gizli", name="Gizli"
    )
    binding_b = ScenarioDocumentSetBinding.objects.create(
        organization=organization_b, scenario=scenario_b, document_set=set_b
    )
    client.force_login(_member("editor-a", organization_a, Role.SCENARIO_EDITOR))

    response = client.post(
        reverse("console:scenario_bind_document_set", args=[scenario_a.id]),
        {"document_set_id": set_b.id},
    )
    assert response.status_code == 302
    assert not ScenarioDocumentSetBinding.objects.filter(scenario=scenario_a).exists()

    response = client.post(
        reverse(
            "console:scenario_unbind_document_set",
            args=[scenario_a.id, binding_b.id],
        )
    )
    assert response.status_code == 404
    assert ScenarioDocumentSetBinding.objects.filter(pk=binding_b.id).exists()


def test_grant_requires_active_consumer_binding_to_scenario(client: Client) -> None:
    organization = Organization.objects.create(slug="kurum", name="Kurum")
    scenario = _scenario(organization, "hedef")
    other_scenario = _scenario(organization, "diger")
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="bilgi", name="Bilgi"
    )
    ScenarioDocumentSetBinding.objects.create(
        organization=organization, scenario=scenario, document_set=document_set
    )
    consumer = _consumer(organization, other_scenario, "yanlis")
    client.force_login(_member("editor", organization, Role.SCENARIO_EDITOR))

    response = client.post(
        reverse("console:scenario_grant_consumer", args=[scenario.id, document_set.id]),
        {"consumer_id": consumer.id},
        follow=True,
    )

    assert response.status_code == 200
    assert not DocumentSetGrant.objects.exists()
    assert "istemci bu senaryoya bağlı değil" in response.content.decode().lower()
