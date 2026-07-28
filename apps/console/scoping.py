"""Tenant-scoped querysets for console screens.

Every console list derives its scope from :func:`allowed_organization_ids` so a
missing filter in a template can never widen what an operator sees.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.artifacts.models import ArtifactVersion
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import Document, DocumentSet, DocumentSetVersion
from apps.identity.models import Consumer
from apps.ingestion.models import ConnectorType, Source
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization
from apps.tenancy.services import allowed_organization_ids
from apps.workflows.models import Run

UserLike = object


def scoped_organizations(user: UserLike) -> QuerySet[Organization]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = Organization.objects.all()
    return qs if allowed is None else qs.filter(id__in=allowed)


def scoped_projects(user: UserLike) -> QuerySet[AIProject]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = AIProject.objects.select_related("organization", "owner_membership__user")
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def scoped_scenarios(user: UserLike) -> QuerySet[Scenario]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = Scenario.objects.select_related("project", "project__organization")
    return qs if allowed is None else qs.filter(project__organization_id__in=allowed)


def scoped_consumers(user: UserLike) -> QuerySet[Consumer]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = Consumer.objects.select_related("organization")
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def scoped_artifacts(user: UserLike) -> QuerySet[ArtifactVersion]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = ArtifactVersion.objects.select_related("organization")
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def scoped_releases(user: UserLike) -> QuerySet[ScenarioRelease]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = ScenarioRelease.objects.select_related(
        "scenario", "scenario__project", "scenario__project__organization"
    )
    return qs if allowed is None else qs.filter(scenario__project__organization_id__in=allowed)


def scoped_runs(user: UserLike) -> QuerySet[Run]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = Run.objects.select_related("organization", "scenario", "scenario__project")
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def scoped_documents(user: UserLike) -> QuerySet[Document]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = Document.objects.select_related("organization")
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def scoped_document_sets(user: UserLike) -> QuerySet[DocumentSet]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = DocumentSet.objects.select_related("organization")
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def scoped_document_set_versions(user: UserLike) -> QuerySet[DocumentSetVersion]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = DocumentSetVersion.objects.select_related("document_set", "organization")
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


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
