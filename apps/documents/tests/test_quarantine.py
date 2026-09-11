from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model

from apps.documents.models import DocumentSet, DocumentSetStatus
from apps.documents.services import (
    DocumentSetControlError,
    set_document_set_quarantine,
)
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member(username: str, organization: Organization) -> tuple[Any, OrganizationMembership]:
    user = User.objects.create_user(username=username, password=None)
    membership = OrganizationMembership.objects.create(
        organization=organization,
        user=user,
    )
    return user, membership


def test_document_manager_and_superadmin_recovery_quarantine_without_content_grant() -> None:
    organization = Organization.objects.create(slug="docs", name="Docs")
    document_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="safe-set",
        name="Safe Set",
    )
    organization_admin, admin_membership = _member("org-admin", organization)
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=admin_membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=organization_admin,
    )
    manager, manager_membership = _member("set-manager", organization)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=organization,
        document_set=document_set,
        membership=manager_membership,
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=organization_admin,
    )
    recovery = User.objects.create_superuser(username="recovery", password=None)

    quarantined = set_document_set_quarantine(
        document_set=document_set,
        actor=manager,
        quarantined=True,
        reason="Unsafe ingestion signal",
    )
    assert quarantined.status == DocumentSetStatus.QUARANTINED

    with pytest.raises(DocumentSetControlError, match="DOCUMENT_SET_CONTROL_FORBIDDEN"):
        set_document_set_quarantine(
            document_set=quarantined,
            actor=organization_admin,
            quarantined=False,
            reason="Organization admin attempt",
        )

    restored = set_document_set_quarantine(
        document_set=quarantined,
        actor=recovery,
        quarantined=False,
        reason="Global safety review",
    )
    assert restored.status == DocumentSetStatus.ACTIVE


def test_quarantine_audit_failure_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization.objects.create(slug="docs", name="Docs")
    document_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="safe-set",
        name="Safe Set",
    )
    organization_admin, admin_membership = _member("org-admin", organization)
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=admin_membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=organization_admin,
    )
    manager, manager_membership = _member("set-manager", organization)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=organization,
        document_set=document_set,
        membership=manager_membership,
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=organization_admin,
    )

    def fail_audit(**_kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.documents.services.record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        set_document_set_quarantine(
            document_set=document_set,
            actor=manager,
            quarantined=True,
            reason="Unsafe ingestion signal",
        )
    document_set.refresh_from_db()
    assert document_set.status == DocumentSetStatus.ACTIVE
