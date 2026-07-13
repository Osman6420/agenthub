"""P8.3 scenario binding and effective consumer retrieval-grant console tests."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet, DocumentSetGrant, ScenarioDocumentSetBinding
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.roles import Role
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member(username: str, org: Organization, role: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


def _scenario(org: Organization, slug: str = "rag") -> Scenario:
    project = AIProject.objects.create(organization=org, slug=f"p-{slug}", name="P")
    return Scenario.objects.create(project=project, slug=slug, name=slug, type="rag")


def _consumer(org: Organization, subject: str = "client") -> Consumer:
    return Consumer.objects.create(
        organization=org, subject=subject, name=subject, protocol=ConsumerProtocol.REST
    )


def test_author_can_bind_and_unbind_scenario(client: Client) -> None:
    org = Organization.objects.create(slug="a", name="A")
    document_set = DocumentSet.objects.create(organization=org, logical_id="kb", name="KB")
    scenario = _scenario(org)
    client.force_login(_member("editor", org, Role.SCENARIO_EDITOR))

    response = client.post(
        reverse("console:document_set_bind_scenario", args=[document_set.id]),
        {"scenario_id": scenario.id},
    )
    assert response.status_code == 302
    binding = ScenarioDocumentSetBinding.objects.get(scenario=scenario, document_set=document_set)
    assert AuditEvent.objects.filter(action="documents.binding.create").exists()

    response = client.post(reverse("console:document_set_unbind_scenario", args=[binding.id]))
    assert response.status_code == 302
    assert not ScenarioDocumentSetBinding.objects.filter(pk=binding.id).exists()
    assert AuditEvent.objects.filter(action="documents.binding.remove").exists()


def test_author_can_grant_and_revoke_consumer(client: Client) -> None:
    org = Organization.objects.create(slug="a", name="A")
    document_set = DocumentSet.objects.create(organization=org, logical_id="kb", name="KB")
    consumer = _consumer(org)
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))

    response = client.post(
        reverse("console:document_set_grant_consumer", args=[document_set.id]),
        {"consumer_id": consumer.id},
    )
    assert response.status_code == 302
    grant = DocumentSetGrant.objects.get(document_set=document_set)
    assert grant.principal_ref == str(consumer.id)
    assert AuditEvent.objects.filter(action="documents.grant.create").exists()

    response = client.post(reverse("console:document_set_revoke_grant", args=[grant.id]))
    assert response.status_code == 302
    assert not DocumentSetGrant.objects.filter(pk=grant.id).exists()
    assert AuditEvent.objects.filter(action="documents.grant.remove").exists()


@pytest.mark.parametrize(
    ("route", "field"),
    [
        ("console:document_set_bind_scenario", "scenario_id"),
        ("console:document_set_grant_consumer", "consumer_id"),
    ],
)
def test_cross_tenant_principal_is_rejected(client: Client, route: str, field: str) -> None:
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    document_set = DocumentSet.objects.create(organization=org_a, logical_id="kb", name="KB")
    target_id = _scenario(org_b).id if field == "scenario_id" else _consumer(org_b).id
    client.force_login(_member("editor", org_a, Role.SCENARIO_EDITOR))

    response = client.post(reverse(route, args=[document_set.id]), {field: target_id})
    assert response.status_code == 302
    assert not ScenarioDocumentSetBinding.objects.exists()
    assert not DocumentSetGrant.objects.exists()


def test_non_author_cannot_change_acl(client: Client) -> None:
    org = Organization.objects.create(slug="a", name="A")
    document_set = DocumentSet.objects.create(organization=org, logical_id="kb", name="KB")
    scenario = _scenario(org)
    client.force_login(_member("auditor", org, Role.AUDITOR))

    response = client.post(
        reverse("console:document_set_bind_scenario", args=[document_set.id]),
        {"scenario_id": scenario.id},
    )
    assert response.status_code == 403
    assert not ScenarioDocumentSetBinding.objects.exists()


def test_cross_tenant_binding_and_grant_targets_are_not_found(client: Client) -> None:
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    set_b = DocumentSet.objects.create(organization=org_b, logical_id="kb", name="KB")
    binding = ScenarioDocumentSetBinding.objects.create(
        organization=org_b, scenario=_scenario(org_b), document_set=set_b
    )
    grant = DocumentSetGrant.objects.create(
        organization=org_b,
        document_set=set_b,
        principal_type="consumer",
        principal_ref=str(_consumer(org_b).id),
        permission="retrieve",
    )
    client.force_login(_member("editor", org_a, Role.SCENARIO_EDITOR))

    assert (
        client.post(reverse("console:document_set_unbind_scenario", args=[binding.id])).status_code
        == 404
    )
    assert (
        client.post(reverse("console:document_set_revoke_grant", args=[grant.id])).status_code
        == 404
    )
    assert ScenarioDocumentSetBinding.objects.filter(pk=binding.id).exists()
    assert DocumentSetGrant.objects.filter(pk=grant.id).exists()
