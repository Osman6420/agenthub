"""Atomic entry into REST setup: exact existing scope or explicitly managed new set."""

from __future__ import annotations

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.documents.models import DocumentSet
from apps.documents.services import DocumentError, create_document_set
from apps.identity.assignment_services import AssignmentError, grant_document_set_responsibility
from apps.identity.authorization import Capability, authorize
from apps.identity.models import DocumentSetResponsibilityAssignment
from apps.ingestion.models import RestSetupDraft
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError, _audit
from apps.ingestion.rest_setup_drafts import load_setup_draft, save_setup_draft
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tenancy.services import UserLike, can_admin_org, can_manage_documents


def manageable_setup_sets(actor: UserLike, organization: Organization) -> QuerySet[DocumentSet]:
    """Scoped form choices only; begin_rest_setup reauthorizes the submitted target."""
    query = DocumentSet.objects.filter(organization=organization, status="active")
    actor_id = actor.pk
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "is_active", False):
        return query.none()
    if actor_id is None:
        return query.none()
    if not organization.is_active:
        return query.none()
    if getattr(actor, "is_superuser", False):
        return query
    grants = DocumentSetResponsibilityAssignment.objects.filter(
        organization=organization,
        membership__organization=organization,
        membership__user_id=actor_id,
        membership__status="active",
        status="active",
        responsibility="document_set_manager",
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
    return query.filter(pk__in=grants.values("document_set_id"))


def can_begin_new_set(actor: UserLike, organization: Organization) -> bool:
    actor_id = actor.pk
    if actor_id is None:
        return False
    if not organization.is_active or not can_admin_org(actor, organization.pk):
        return False
    if getattr(actor, "is_superuser", False):
        return True
    return (
        authorize(
            user=actor, capability=Capability.RESPONSIBILITY_MANAGE, organization=organization
        ).allowed
        and OrganizationMembership.objects.filter(
            organization=organization,
            user_id=actor_id,
            status="active",
            user__is_active=True,
            user__is_superuser=False,
        ).exists()
    )


def begin_rest_setup(
    *,
    actor: UserLike,
    organization: Organization,
    intent: UUID,
    source_name: str,
    document_set: DocumentSet | None = None,
    new_set_name: str = "",
    manage_new_set: bool = False,
) -> RestSetupDraft:
    try:
        return _begin_rest_setup(
            actor=actor,
            organization=organization,
            intent=intent,
            source_name=source_name,
            document_set=document_set,
            new_set_name=new_set_name,
            manage_new_set=manage_new_set,
        )
    except (
        RestAuthorizationError,
        RestServiceError,
        DocumentError,
        AssignmentError,
        ValidationError,
        IntegrityError,
    ) as exc:
        with transaction.atomic():
            set_tenant_context(organization.pk)
            _audit(
                "rest_setup.begin",
                str(getattr(actor, "pk", "anonymous")),
                "deny",
                organization_id=organization.pk,
                resource_id=str(intent),
                reason=getattr(exc, "code", "REST_SETUP_SCOPE_DENIED"),
            )
        raise


@transaction.atomic
def _begin_rest_setup(
    *,
    actor: UserLike,
    organization: Organization,
    intent: UUID,
    source_name: str,
    document_set: DocumentSet | None,
    new_set_name: str,
    manage_new_set: bool,
) -> RestSetupDraft:
    if (
        not isinstance(intent, UUID)
        or not isinstance(source_name, str)
        or not 1 <= len(source_name.strip()) <= 200
        or not isinstance(new_set_name, str)
        or type(manage_new_set) is not bool
        or (document_set is not None and (new_set_name or manage_new_set))
        or (
            document_set is None
            and (not manage_new_set or not 1 <= len(new_set_name.strip()) <= 200)
        )
    ):
        raise RestServiceError("REST_SETUP_SCOPE_INVALID")
    actor_id = actor.pk
    if actor_id is None:
        raise RestAuthorizationError("AUTHENTICATED_ACTIVE_USER_REQUIRED")
    set_tenant_context(organization.pk)
    organization = Organization.objects.select_for_update(no_key=True).get(pk=organization.pk)
    if not organization.is_active:
        raise RestAuthorizationError("ORGANIZATION_INACTIVE")
    logical_id = f"rest-set-{intent.hex}"
    previous = (
        RestSetupDraft.objects.select_related("document_set").filter(public_id=intent).first()
    )
    if previous is not None:
        if (
            previous.organization_id != organization.pk
            or previous.owner_id != actor_id
            or previous.name != source_name.strip()
            or (document_set is not None and previous.document_set_id != document_set.pk)
            or (
                document_set is None
                and (
                    previous.document_set.logical_id != logical_id
                    or previous.document_set.name != new_set_name.strip()
                )
            )
        ):
            raise RestServiceError("REST_SETUP_SCOPE_CONFLICT")
        return load_setup_draft(actor=actor, document_set=previous.document_set, intent=intent)
    if document_set is None:
        if not can_begin_new_set(actor, organization):
            raise RestAuthorizationError("ORGANIZATION_ADMINISTRATOR_REQUIRED")
        document_set = create_document_set(
            organization=organization,
            logical_id=logical_id,
            name=new_set_name.strip(),
            actor=str(actor_id),
        )
        if not getattr(actor, "is_superuser", False):
            membership = OrganizationMembership.objects.get(
                organization=organization, user_id=actor_id, status="active"
            )
            grant_document_set_responsibility(
                document_set=document_set,
                membership=membership,
                responsibility="document_set_manager",
                actor=actor,
            )
    else:
        document_set = DocumentSet.objects.filter(
            pk=document_set.pk, organization=organization, status="active"
        ).first()
        if document_set is None or not can_manage_documents(
            actor, organization.pk, document_set=document_set
        ):
            raise RestAuthorizationError("DOCUMENT_SET_MANAGER_REQUIRED")
    return save_setup_draft(
        actor=actor,
        document_set=document_set,
        intent=intent,
        payload={"name": source_name.strip(), "step": 1, "mode": "visual"},
    )
