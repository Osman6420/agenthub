from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import AIProject, Scenario, ScenarioAlias
from apps.catalog.services import create_console_project, create_console_scenario
from apps.console.forms import (
    DocumentSetForm,
    DocumentUploadForm,
    OrganizationForm,
    ProjectForm,
    ScenarioForm,
)
from apps.documents.models import Document, DocumentLifecycle, DocumentSet
from apps.documents.services import create_console_document_set
from apps.identity.models import Consumer, ConsumerProtocol
from apps.identity.roles import Role
from apps.tenancy.identifiers import IdentifierAllocationError, allocate_identifier
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tenancy.services import create_console_organization

pytestmark = pytest.mark.django_db


def _member_client(organization: Organization) -> Client:
    user = get_user_model().objects.create_user(username="part2-author")
    OrganizationMembership.objects.create(
        organization=organization, user=user, role=Role.ORGANIZATION_ADMIN
    )
    client = Client()
    client.force_login(user)
    return client


def test_covered_console_forms_do_not_accept_technical_identifiers() -> None:
    assert "slug" not in OrganizationForm().fields
    assert "slug" not in ProjectForm(user=None).fields
    assert "slug" not in ScenarioForm(user=None).fields
    assert "alias" not in ScenarioForm(user=None).fields
    assert "logical_id" not in DocumentUploadForm(user=None).fields
    assert "logical_id" not in DocumentSetForm(user=None).fields


def test_identifier_allocation_is_bounded_and_handles_empty_normalization() -> None:
    value = allocate_identifier(
        "!!!", fallback="fallback", max_length=24, exists=lambda _candidate: False
    )
    assert re.fullmatch(r"fallback-[a-z2-7]{10}", value)
    with pytest.raises(IdentifierAllocationError):
        allocate_identifier(
            "Collision", fallback="fallback", max_length=24, exists=lambda _candidate: True
        )


def test_console_services_generate_organization_and_document_set_ids() -> None:
    organization = create_console_organization(name="\u0130nsan Kaynaklar\u0131", status="active")
    document_set = create_console_document_set(
        organization=organization, name="Politikalar", actor="part2-author"
    )

    assert organization.slug.startswith("insan-kaynaklari-")
    assert document_set.logical_id.startswith("politikalar-")


def test_catalog_console_services_generate_stable_ids_and_atomic_alias() -> None:
    organization = Organization.objects.create(slug="existing", name="Existing")
    project = create_console_project(organization=organization, name="İş Süreçleri")
    scenario = create_console_scenario(project=project, name="Müşteri Yanıtı")

    assert project.slug.startswith("is-surecleri-")
    assert scenario.slug.startswith("musteri-yaniti-")
    alias = ScenarioAlias.objects.get(scenario=scenario)
    alias_pattern = r"is-surecleri-musteri-yaniti-[a-z2-7]{4}"
    assert re.fullmatch(alias_pattern, alias.alias)
    original = (project.slug, project.public_id, scenario.slug, scenario.public_id)
    project.name = "Renamed"
    project.save(update_fields=["name"])
    scenario.name = "Renamed"
    scenario.save(update_fields=["name"])
    assert original == (project.slug, project.public_id, scenario.slug, scenario.public_id)

    project.public_id = uuid.uuid4()
    with pytest.raises(ValueError, match="public_id is immutable"):
        project.save()


def test_uuid_routes_are_canonical_and_legacy_routes_remain_scoped() -> None:
    organization = Organization.objects.create(slug="route-org", name="Route Org")
    client = _member_client(organization)
    project = AIProject.objects.create(organization=organization, slug="p", name="P")
    scenario = Scenario.objects.create(
        organization=organization, project=project, slug="s", name="S"
    )
    document = Document.objects.create(organization=organization, logical_id="d")
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="set", name="Set"
    )
    consumer = Consumer.objects.create(
        organization=organization, subject="sub", name="Consumer", protocol=ConsumerProtocol.REST
    )

    objects_and_routes: list[tuple[Any, str, str]] = [
        (project, "project_detail_public", "project_detail"),
        (scenario, "scenario_detail_public", "scenario_detail"),
        (document_set, "document_set_detail_public", "document_set_detail"),
        (consumer, "consumer_detail_public", "consumer_detail"),
    ]
    for instance, public_route, legacy_route in objects_and_routes:
        public_response = client.get(reverse(f"console:{public_route}", args=[instance.public_id]))
        assert public_response.status_code == 200
        assert client.get(reverse(f"console:{legacy_route}", args=[instance.pk])).status_code == 200

    assert (
        reverse("console:document_soft_delete_public", args=[document.public_id])
        in client.get(reverse("console:advanced_document_inventory")).content.decode()
    )
    assert (
        reverse("console:consumer_detail_public", args=[consumer.public_id])
        in client.get(reverse("console:consumers")).content.decode()
    )
    assert client.get("/console/projects/id/not-a-uuid/").status_code == 404
    assert (
        client.post(
            reverse("console:document_soft_delete_public", args=[document.public_id])
        ).status_code
        == 302
    )
    document.refresh_from_db()
    assert document.lifecycle_state == DocumentLifecycle.TOMBSTONED

    foreign = Organization.objects.create(slug="foreign", name="Foreign")
    foreign_project = AIProject.objects.create(organization=foreign, slug="secret", name="Secret")
    assert (
        client.get(
            reverse("console:project_detail_public", args=[foreign_project.public_id])
        ).status_code
        == 404
    )
    legacy_foreign = client.get(reverse("console:project_detail", args=[foreign_project.pk]))
    assert legacy_foreign.status_code == 404
