"""Deny-by-default binding -> document-set-version pinning (P4.2)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import AIProject, Scenario
from apps.documents import services
from apps.documents.models import (
    DocumentSet,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    ScenarioDocumentSetGrant,
)
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def _scenario(org: Organization) -> Scenario:
    project = AIProject.objects.create(organization=org, slug="p", name="P")
    return Scenario.objects.create(project=project, slug="sc", name="S", type="rag")


def _version(doc_set: DocumentSet, version: int, status: str) -> DocumentSetVersion:
    return DocumentSetVersion.objects.create(
        organization_id=doc_set.organization_id,
        document_set=doc_set,
        version=version,
        status=status,
    )


def _grant(scenario: Scenario, document_set: DocumentSet) -> None:
    actor = get_user_model().objects.create_user(
        username=f"grant-{scenario.pk}-{document_set.pk}",
        password=None,
    )
    ScenarioDocumentSetGrant.objects.create(
        organization=scenario.organization,
        scenario=scenario,
        document_set=document_set,
        granted_by=actor,
        granted_at=timezone.now(),
    )


def test_no_binding_pins_nothing() -> None:
    org = Organization.objects.create(slug="o", name="O")
    assert services.pinned_document_set_version_ids(_scenario(org)) == []


def test_pins_latest_published_version() -> None:
    org = Organization.objects.create(slug="o", name="O")
    scenario = _scenario(org)
    doc_set = DocumentSet.objects.create(organization=org, logical_id="kb", name="KB")
    _version(doc_set, 1, DocumentSetVersionStatus.PROMOTABLE)
    v2 = _version(doc_set, 2, DocumentSetVersionStatus.ACTIVE)
    _version(doc_set, 3, DocumentSetVersionStatus.DRAFT)  # unpublished -> ignored
    services.bind_scenario_document_set(scenario=scenario, document_set=doc_set, actor="op")
    _grant(scenario, doc_set)
    assert services.pinned_document_set_version_ids(scenario) == [v2.id]


def test_binding_to_unpublished_set_pins_nothing() -> None:
    org = Organization.objects.create(slug="o", name="O")
    scenario = _scenario(org)
    doc_set = DocumentSet.objects.create(organization=org, logical_id="kb", name="KB")
    _version(doc_set, 1, DocumentSetVersionStatus.DRAFT)
    services.bind_scenario_document_set(scenario=scenario, document_set=doc_set, actor="op")
    _grant(scenario, doc_set)
    assert services.pinned_document_set_version_ids(scenario) == []
