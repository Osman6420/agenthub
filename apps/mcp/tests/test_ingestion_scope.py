"""Ingestion metadata must follow the exact consumer/scenario/document permission chain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import (
    DocumentSet,
    DocumentSetGrant,
    ScenarioDocumentSetBinding,
    ScenarioDocumentSetGrant,
)
from apps.gateway.errors import ApiError
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding
from apps.identity.tokens import create_token
from apps.ingestion.models import IngestionRun, RestPullContract, RestPullProfile, Source
from apps.mcp.service import _ingestion_status
from apps.tenancy.context import set_tenant_scope
from apps.tenancy.models import Organization


@dataclass
class ScopeFixture:
    client: APIClient
    consumer: Consumer
    binding: ConsumerBinding
    set_binding: ScenarioDocumentSetBinding
    scenario_grant: ScenarioDocumentSetGrant
    consumer_grant: DocumentSetGrant
    run: IngestionRun


def _source(organization: Organization, name: str, document_set: DocumentSet | None) -> Source:
    if document_set is None:
        return Source.objects.create(organization=organization, slug=name, connector_type="https")
    profile = RestPullProfile.objects.create(
        logical_id=f"{organization.pk}-{name}",
        revision=1,
        host="example.invalid",
        created_by="test",
    )
    contract = RestPullContract.objects.create(
        organization=organization,
        logical_id=name,
        revision=1,
        definition={
            "version": 1,
            "inputs": {},
            "request": {"method": "GET", "path": "/items"},
            "response": {
                "items_pointer": "/items",
                "id_pointer": "/id",
                "content_pointer": "/content",
                "content_encoding": "utf8_text",
                "mime_type": "text/plain",
            },
            "pagination": {"mode": "none"},
        },
        created_by="test",
    )
    return Source.objects.create(
        organization=organization,
        slug=name,
        connector_type="generic_rest",
        connector_config={"inputs": {}},
        rest_profile=profile,
        rest_contract=contract,
        document_set=document_set,
    )


@pytest.fixture
def scope_fixture(db: object) -> ScopeFixture:
    organization = Organization.objects.create(slug="ingestion-scope", name="Scope")
    project = AIProject.objects.create(organization=organization, slug="one", name="One")
    scenario = Scenario.objects.create(project=project, slug="one", name="One")
    consumer = Consumer.objects.create(
        organization=organization, subject="scope-consumer", name="Scope", protocol="mcp"
    )
    binding = ConsumerBinding.objects.create(
        consumer=consumer, scenario=scenario, capabilities=[Capability.INGESTION_READ]
    )
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="one", name="One"
    )
    set_binding = ScenarioDocumentSetBinding.objects.create(
        organization=organization, scenario=scenario, document_set=document_set
    )
    grantor = get_user_model().objects.create_user(username="scope-grantor")
    scenario_grant = ScenarioDocumentSetGrant.objects.create(
        organization=organization,
        scenario=scenario,
        document_set=document_set,
        granted_by=grantor,
        granted_at=timezone.now(),
    )
    consumer_grant = DocumentSetGrant.objects.create(
        organization=organization,
        document_set=document_set,
        principal_type="consumer",
        principal_ref=str(consumer.pk),
        permission="retrieve",
    )
    run = IngestionRun.objects.create(
        organization=organization, source=_source(organization, "one", document_set)
    )
    _, token = create_token(consumer, "test")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return ScopeFixture(client, consumer, binding, set_binding, scenario_grant, consumer_grant, run)


def _status(fixture: ScopeFixture, run_id: int | None = None) -> Any:
    return fixture.client.post(
        "/mcp/",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "agenthub__ingestion_status",
                "arguments": {} if run_id is None else {"run_id": run_id},
            },
        },
        format="json",
    )


def test_exact_grant_chain_allows_existing_response(scope_fixture: ScopeFixture) -> None:
    response = _status(scope_fixture, scope_fixture.run.pk)
    assert response.status_code == 200
    result = response.json()["result"]["structuredContent"]
    assert set(result) == {"run_id", "source_id", "status", "updated_at"}
    assert result["run_id"] == scope_fixture.run.pk


def test_shared_consent_replaces_only_consumer_intersection_and_remains_live(scope_fixture):
    from apps.documents.shared_access import set_shared_consumer_consent
    from apps.identity.models import DocumentSetResponsibilityAssignment
    from apps.tenancy.models import OrganizationMembership

    f = scope_fixture
    scenario = f.binding.scenario
    scenario.data_access_mode = "scenario_shared"
    scenario.save(update_fields=["data_access_mode"])
    f.consumer_grant.delete()
    denied = _status(f, f.run.pk)
    assert denied.status_code == 404
    assert denied.json()["result"]["structuredContent"]["error"]["code"] == "RUN_NOT_FOUND"
    manager = f.scenario_grant.granted_by
    membership = OrganizationMembership.objects.create(
        organization=f.consumer.organization, user=manager
    )
    DocumentSetResponsibilityAssignment.objects.create(
        organization=f.consumer.organization,
        membership=membership,
        document_set=f.scenario_grant.document_set,
        responsibility="document_set_manager",
        assigned_by=manager,
    )
    set_shared_consumer_consent(
        grant=f.scenario_grant, actor=manager, enabled=True, acknowledge_future_consumers=True
    )
    assert _status(f, f.run.pk).json()["result"]["structuredContent"]["run_id"] == f.run.pk
    set_shared_consumer_consent(grant=f.scenario_grant, actor=manager, enabled=False)
    denied = _status(f, f.run.pk)
    assert denied.status_code == 404
    assert denied.json()["result"]["structuredContent"]["error"]["code"] == "RUN_NOT_FOUND"


@pytest.mark.parametrize("foreign_tenant", [False, True])
def test_neighbor_source_is_hidden_and_latest_is_filtered_first(
    scope_fixture: ScopeFixture, foreign_tenant: bool
) -> None:
    organization = (
        Organization.objects.create(slug="foreign", name="Foreign")
        if foreign_tenant
        else scope_fixture.consumer.organization
    )
    document_set = DocumentSet.objects.create(
        organization=organization, logical_id="neighbor", name="Neighbor"
    )
    neighbor = IngestionRun.objects.create(
        organization=organization, source=_source(organization, "neighbor", document_set)
    )
    denied = _status(scope_fixture, neighbor.pk)
    missing = _status(scope_fixture, neighbor.pk + 10_000)
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()
    latest = _status(scope_fixture)
    assert latest.status_code == 200
    assert latest.json()["result"]["structuredContent"]["run_id"] == scope_fixture.run.pk
    assert AuditEvent.objects.filter(
        action="mcp.tools.call", outcome="deny", reason="RUN_NOT_FOUND"
    ).exists()


@pytest.mark.parametrize(
    "removed", ["binding", "capability", "set_binding", "scenario_grant", "consumer_grant"]
)
def test_each_permission_link_is_required_and_revocation_is_live(
    scope_fixture: ScopeFixture, removed: str
) -> None:
    assert _status(scope_fixture, scope_fixture.run.pk).status_code == 200
    if removed == "binding":
        scope_fixture.binding.status = "disabled"
        scope_fixture.binding.save()
    elif removed == "capability":
        scope_fixture.binding.capabilities = [Capability.WORKFLOW_RUN]
        scope_fixture.binding.save()
    elif removed == "set_binding":
        scope_fixture.set_binding.delete()
    elif removed == "scenario_grant":
        scope_fixture.scenario_grant.revoked_at = timezone.now()
        scope_fixture.scenario_grant.save()
    else:
        scope_fixture.consumer_grant.delete()
    assert _status(scope_fixture, scope_fixture.run.pk).status_code == 404


def test_source_without_verified_document_set_is_hidden(scope_fixture: ScopeFixture) -> None:
    organization = scope_fixture.consumer.organization
    run = IngestionRun.objects.create(
        organization=organization, source=_source(organization, "unbound", None)
    )
    assert _status(scope_fixture, run.pk).status_code == 404


def test_binding_and_grant_cannot_be_combined_across_scenarios(scope_fixture: ScopeFixture) -> None:
    original = scope_fixture.binding.scenario
    other = Scenario.objects.create(project=original.project, slug="other", name="Other")
    scope_fixture.scenario_grant.scenario = other
    scope_fixture.scenario_grant.save()
    assert _status(scope_fixture, scope_fixture.run.pk).status_code == 404


@pytest.mark.skipif(connection.vendor != "postgresql", reason="requires PostgreSQL RLS")
def test_scope_query_under_non_owner_role(scope_fixture: ScopeFixture) -> None:
    role = f"mcp_scope_{uuid4().hex[:12]}"
    # This fixture uses pytest's rollback transaction, including the temporary role
    # and its grants. No application or production role is modified.
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
        cursor.execute(  # noqa: S608
            f"GRANT SELECT ON tenancy_organization, catalog_aiproject, catalog_scenario, "
            f"identity_consumer, identity_consumerbinding, documents_documentset, "
            f"documents_documentsetgrant, documents_scenariodocumentsetbinding, "
            f"documents_scenariodocumentsetgrant, ingestion_source, ingestion_ingestionrun "
            f'TO "{role}"'
        )
        cursor.execute(  # noqa: S608
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f'SET LOCAL ROLE "{role}"')  # noqa: S608
            set_tenant_scope(())
            assert not IngestionRun.objects.exists()
            result = _ingestion_status({}, scope_fixture.consumer)
            assert result["run_id"] == scope_fixture.run.pk
            set_tenant_scope(())
            assert not IngestionRun.objects.exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
    scope_fixture.consumer_grant.delete()
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f'SET LOCAL ROLE "{role}"')  # noqa: S608
            with pytest.raises(ApiError):
                _ingestion_status({}, scope_fixture.consumer)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
