"""Scenario↔document-set binding and ACL grant foundation (P4.1)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario
from apps.documents import services
from apps.documents.models import (
    DocumentSet,
    DocumentSetGrant,
    GrantPrincipalType,
    ScenarioDocumentSetBinding,
)
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def _scenario(org: Organization, slug: str = "sc") -> Scenario:
    project = AIProject.objects.create(organization=org, slug=f"p-{slug}", name="P")
    return Scenario.objects.create(project=project, slug=slug, name="S")


def _set(org: Organization, logical_id: str = "kb") -> DocumentSet:
    return DocumentSet.objects.create(organization=org, logical_id=logical_id, name="KB")


def test_bind_same_tenant_and_audit() -> None:
    org = Organization.objects.create(slug="o", name="O")
    binding = services.bind_scenario_document_set(
        scenario=_scenario(org), document_set=_set(org), actor="op"
    )
    assert ScenarioDocumentSetBinding.objects.filter(pk=binding.pk).exists()
    assert AuditEvent.objects.filter(action="documents.binding.create", outcome="success").exists()


def test_bind_cross_tenant_is_rejected() -> None:
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    with pytest.raises(ValidationError):
        services.bind_scenario_document_set(
            scenario=_scenario(org_a), document_set=_set(org_b), actor="op"
        )
    assert not ScenarioDocumentSetBinding.objects.exists()


def test_duplicate_binding_is_rejected() -> None:
    org = Organization.objects.create(slug="o", name="O")
    scenario, doc_set = _scenario(org), _set(org)
    services.bind_scenario_document_set(scenario=scenario, document_set=doc_set, actor="op")
    with pytest.raises(services.DocumentError) as exc:
        services.bind_scenario_document_set(scenario=scenario, document_set=doc_set, actor="op")
    assert exc.value.code == "DUPLICATE_BINDING"


def test_unbind_removes_and_audits() -> None:
    org = Organization.objects.create(slug="o", name="O")
    binding = services.bind_scenario_document_set(
        scenario=_scenario(org), document_set=_set(org), actor="op"
    )
    services.unbind_scenario_document_set(binding, actor="op")
    assert not ScenarioDocumentSetBinding.objects.exists()
    assert AuditEvent.objects.filter(action="documents.binding.remove").exists()


def test_grant_consumer_and_audit() -> None:
    org = Organization.objects.create(slug="o", name="O")
    grant = services.grant_document_set(
        document_set=_set(org),
        principal_type=GrantPrincipalType.CONSUMER,
        principal_ref="consumer-123",
        actor="op",
    )
    assert grant.permission == "retrieve"
    assert AuditEvent.objects.filter(action="documents.grant.create").exists()


def test_grant_rejects_unknown_principal_type() -> None:
    org = Organization.objects.create(slug="o", name="O")
    with pytest.raises(services.DocumentError) as exc:
        services.grant_document_set(
            document_set=_set(org),
            principal_type="robot",
            principal_ref="x",
            actor="op",
        )
    assert exc.value.code == "invalid_principal_type"


def test_duplicate_grant_is_rejected() -> None:
    org = Organization.objects.create(slug="o", name="O")
    doc_set = _set(org)
    services.grant_document_set(
        document_set=doc_set,
        principal_type=GrantPrincipalType.CONSUMER,
        principal_ref="c1",
        actor="op",
    )
    with pytest.raises(services.DocumentError) as exc:
        services.grant_document_set(
            document_set=doc_set,
            principal_type=GrantPrincipalType.CONSUMER,
            principal_ref="c1",
            actor="op",
        )
    assert exc.value.code == "DUPLICATE_GRANT"
    assert DocumentSetGrant.objects.count() == 1
