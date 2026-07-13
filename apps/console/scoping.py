"""Tenant-scoped querysets for console screens.

Every console list derives its scope from :func:`allowed_organization_ids` so a
missing filter in a template can never widen what an operator sees.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.agents.models import AgentRun
from apps.artifacts.models import ArtifactVersion
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import Document, DocumentSet, DocumentSetVersion
from apps.identity.models import Consumer
from apps.releases.models import ScenarioRelease
from apps.tenancy.models import Organization
from apps.tenancy.services import allowed_organization_ids

UserLike = object


def scoped_organizations(user: UserLike) -> QuerySet[Organization]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = Organization.objects.all()
    return qs if allowed is None else qs.filter(id__in=allowed)


def scoped_projects(user: UserLike) -> QuerySet[AIProject]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = AIProject.objects.select_related("organization")
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


def scoped_agent_runs(user: UserLike) -> QuerySet[AgentRun]:
    allowed = allowed_organization_ids(user)  # type: ignore[arg-type]
    qs = AgentRun.objects.select_related(
        "organization", "scenario", "scenario__project", "consumer"
    )
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
