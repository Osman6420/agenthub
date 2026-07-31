"""Responsibility-scoped querysets for human-operator console screens."""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import Document, DocumentSet, DocumentSetVersion
from apps.identity.models import (
    Consumer,
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibilityAssignment,
    ProjectResponsibilityAssignment,
    ResponsibilityStatus,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.ingestion.models import ConnectorType, Source
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import MembershipStatus, Organization
from apps.tenancy.services import allowed_organization_ids, is_platform_admin
from apps.workflows.models import Run

UserLike = object


def _active_assignment_filter(user: UserLike) -> dict[str, object]:
    return {
        "membership__user_id": getattr(user, "pk", None),
        "membership__status": MembershipStatus.ACTIVE,
        "membership__user__is_active": True,
        "status": ResponsibilityStatus.ACTIVE,
    }


def _active_expiry() -> Q:
    return Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())


def _organization_responsibility_ids(user: UserLike) -> set[int]:
    return set(
        OrganizationResponsibilityAssignment.objects.filter(**_active_assignment_filter(user))
        .filter(_active_expiry())
        .values_list("organization_id", flat=True)
    )


def _project_responsibility_ids(user: UserLike) -> set[int]:
    return set(
        ProjectResponsibilityAssignment.objects.filter(**_active_assignment_filter(user))
        .filter(_active_expiry())
        .values_list("project_id", flat=True)
    )


def _scenario_responsibility_ids(
    user: UserLike, responsibilities: tuple[str, ...] | None = None
) -> set[int]:
    queryset = ScenarioResponsibilityAssignment.objects.filter(
        **_active_assignment_filter(user)
    ).filter(_active_expiry())
    if responsibilities is not None:
        queryset = queryset.filter(responsibility__in=responsibilities)
    return set(queryset.values_list("scenario_id", flat=True))


def _document_set_responsibility_ids(
    user: UserLike, responsibilities: tuple[str, ...] | None = None
) -> set[int]:
    queryset = DocumentSetResponsibilityAssignment.objects.filter(
        **_active_assignment_filter(user)
    ).filter(_active_expiry())
    if responsibilities is not None:
        queryset = queryset.filter(responsibility__in=responsibilities)
    return set(queryset.values_list("document_set_id", flat=True))


def scoped_organizations(user: UserLike) -> QuerySet[Organization]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = Organization.objects.all()
    return qs if allowed is None else qs.filter(id__in=allowed)


def scoped_projects(user: UserLike) -> QuerySet[AIProject]:
    qs = AIProject.objects.select_related("organization")
    if is_platform_admin(user):  # type: ignore[arg-type]
        return qs
    organization_ids = _organization_responsibility_ids(user)
    project_ids = _project_responsibility_ids(user)
    scenario_project_ids = (
        ScenarioResponsibilityAssignment.objects.filter(**_active_assignment_filter(user))
        .filter(_active_expiry())
        .values_list("scenario__project_id", flat=True)
    )
    return qs.filter(
        Q(organization_id__in=organization_ids)
        | Q(id__in=project_ids)
        | Q(id__in=scenario_project_ids)
    ).distinct()


def scoped_scenarios(user: UserLike) -> QuerySet[Scenario]:
    qs = Scenario.objects.select_related("project", "project__organization")
    if is_platform_admin(user):  # type: ignore[arg-type]
        return qs
    return qs.filter(
        Q(organization_id__in=_organization_responsibility_ids(user))
        | Q(project_id__in=_project_responsibility_ids(user))
        | Q(id__in=_scenario_responsibility_ids(user))
    ).distinct()


def scoped_consumers(user: UserLike) -> QuerySet[Consumer]:
    qs = Consumer.objects.select_related("organization")
    return (
        qs
        if is_platform_admin(user)  # type: ignore[arg-type]
        else qs.filter(organization_id__in=_organization_responsibility_ids(user))
    )


def scoped_artifacts(user: UserLike) -> QuerySet[ArtifactVersion]:
    qs = ArtifactVersion.objects.select_related("organization")
    return (
        qs
        if is_platform_admin(user)  # type: ignore[arg-type]
        else qs.filter(organization_id__in=_organization_responsibility_ids(user))
    )


def scoped_releases(user: UserLike) -> QuerySet[ScenarioRelease]:
    qs = ScenarioRelease.objects.select_related(
        "scenario", "scenario__project", "scenario__project__organization"
    )
    if is_platform_admin(user):  # type: ignore[arg-type]
        return qs
    visible_scenarios = scoped_scenarios(user).values_list("id", flat=True)
    return qs.filter(scenario_id__in=visible_scenarios)


def scoped_runs(user: UserLike) -> QuerySet[Run]:
    qs = Run.objects.select_related("organization", "scenario", "scenario__project")
    if is_platform_admin(user):  # type: ignore[arg-type]
        return qs
    scenario_ids = _scenario_responsibility_ids(user, (ScenarioResponsibility.RUNTIME_OPERATOR,))
    return qs.filter(
        Q(organization_id__in=_organization_responsibility_ids(user))
        | Q(scenario_id__in=scenario_ids)
    ).distinct()


def scoped_documents(user: UserLike) -> QuerySet[Document]:
    qs = Document.objects.select_related("organization")
    if is_platform_admin(user):  # type: ignore[arg-type]
        return qs
    set_ids = _document_set_responsibility_ids(
        user,
        (
            DocumentSetResponsibility.CONTENT_READER,
            DocumentSetResponsibility.MANAGER,
        ),
    )
    return qs.filter(
        versions__memberships__document_set_version__document_set_id__in=set_ids
    ).distinct()


def scoped_document_sets(user: UserLike) -> QuerySet[DocumentSet]:
    qs = DocumentSet.objects.select_related("organization")
    if is_platform_admin(user):  # type: ignore[arg-type]
        return qs
    return qs.filter(
        Q(organization_id__in=_organization_responsibility_ids(user))
        | Q(id__in=_document_set_responsibility_ids(user))
    ).distinct()


def scoped_document_set_versions(user: UserLike) -> QuerySet[DocumentSetVersion]:
    qs = DocumentSetVersion.objects.select_related("document_set", "organization")
    if is_platform_admin(user):  # type: ignore[arg-type]
        return qs
    return qs.filter(
        Q(organization_id__in=_organization_responsibility_ids(user))
        | Q(document_set_id__in=_document_set_responsibility_ids(user))
    ).distinct()


def narrow_to_active_organization(
    queryset: QuerySet,
    active_organization: Organization | None,
    *,
    field: str = "organization_id",
) -> QuerySet:
    """Narrow an already-tenant-scoped queryset to the active organization when one is set.

    ``active_organization`` is the membership-validated value from
    :func:`apps.console.context.resolve_active_organization`; ``None`` means
    "all organizations" and returns the queryset unchanged. This only ever *narrows* an
    already-scoped queryset — it is a readability filter, never the authorization boundary.
    ``field`` is the queryset's lookup path to the organization (e.g. ``organization_id``,
    ``project__organization_id``, or ``pk`` for the organization list itself).
    """
    if active_organization is None:
        return queryset
    return queryset.filter(**{field: active_organization.pk})


def scoped_connector_sources(user: UserLike) -> QuerySet[Source]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = Source.objects.filter(
        connector_type__in=[ConnectorType.CONFLUENCE_DC, ConnectorType.GENERIC_REST]
    ).select_related(
        "organization", "document_set", "confluence_profile", "rest_profile", "rest_contract"
    )
    return qs if allowed is None else qs.filter(organization_id__in=allowed)
