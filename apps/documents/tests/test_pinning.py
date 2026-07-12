"""Deny-by-default binding -> document-set-version pinning (P4.2)."""

from __future__ import annotations

import pytest

from apps.catalog.models import AIProject, Scenario
from apps.documents import services
from apps.documents.models import DocumentSet, DocumentSetVersion, DocumentSetVersionStatus
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
    assert services.pinned_document_set_version_ids(scenario) == [v2.id]


def test_binding_to_unpublished_set_pins_nothing() -> None:
    org = Organization.objects.create(slug="o", name="O")
    scenario = _scenario(org)
    doc_set = DocumentSet.objects.create(organization=org, logical_id="kb", name="KB")
    _version(doc_set, 1, DocumentSetVersionStatus.DRAFT)
    services.bind_scenario_document_set(scenario=scenario, document_set=doc_set, actor="op")
    assert services.pinned_document_set_version_ids(scenario) == []
