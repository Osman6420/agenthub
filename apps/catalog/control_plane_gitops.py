"""Validated, create-only GitOps import for control-plane records."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.models import AIProject, Scenario, ScenarioAlias
from apps.identity.models import Consumer, ConsumerBinding
from apps.tenancy.models import Organization

API_VERSION = "agenthub/v1"


class ControlPlaneGitOpsError(ValueError):
    """Raised when a control-plane document is malformed or conflicts with state."""


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ControlPlaneGitOpsError(f"{field} must be a mapping")
    return value


def _required(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ControlPlaneGitOpsError(f"{field} is required")
    return value


def _organization(slug: str) -> Organization:
    organization = Organization.objects.filter(slug=slug).first()
    if organization is None:
        raise ControlPlaneGitOpsError(f"unknown organization: {slug}")
    return organization


def _create_only(
    model: Any,
    *,
    lookup: dict[str, Any],
    values: dict[str, Any],
) -> tuple[models.Model, bool]:
    instance = model.objects.filter(**lookup).first()
    if instance is not None:
        conflicts = [field for field, value in values.items() if getattr(instance, field) != value]
        if conflicts:
            raise ControlPlaneGitOpsError(
                f"existing {model.__name__} conflicts in fields: {', '.join(sorted(conflicts))}"
            )
        return instance, False
    instance = model(**lookup, **values)
    try:
        instance.full_clean()
        instance.save()
    except ValidationError as exc:
        raise ControlPlaneGitOpsError(str(exc)) from exc
    return instance, True


def import_control_plane_document(doc: Any) -> tuple[models.Model, bool, int]:
    """Import one document, returning instance, created flag, and organization id."""
    document = _mapping(doc, "document")
    if document.get("api_version") != API_VERSION:
        raise ControlPlaneGitOpsError(f"api_version must be {API_VERSION!r}")
    kind = document.get("kind")
    metadata = _mapping(document.get("metadata"), "metadata")
    spec = _mapping(document.get("spec"), "spec")

    if kind == "Organization":
        slug = _required(metadata, "slug")
        instance, created = _create_only(
            Organization,
            lookup={"slug": slug},
            values={"name": _required(spec, "name"), "status": spec.get("status", "active")},
        )
        return instance, created, instance.pk

    organization = _organization(_required(metadata, "organization"))
    if kind == "AIProject":
        instance, created = _create_only(
            AIProject,
            lookup={"organization": organization, "slug": _required(metadata, "slug")},
            values={
                "name": _required(spec, "name"),
                "owner": spec.get("owner", ""),
                "risk_level": spec.get("risk_level", "medium"),
                "status": spec.get("status", "active"),
            },
        )
    elif kind == "Scenario":
        project = AIProject.objects.filter(
            organization=organization, slug=_required(metadata, "project")
        ).first()
        if project is None:
            raise ControlPlaneGitOpsError("unknown project in organization")
        instance, created = _create_only(
            Scenario,
            lookup={"project": project, "slug": _required(metadata, "slug")},
            values={
                "name": _required(spec, "name"),
                "type": _required(spec, "type"),
                "visibility": spec.get("visibility", "internal"),
                "risk_level": spec.get("risk_level", "medium"),
                "status": spec.get("status", "draft"),
            },
        )
    elif kind == "ScenarioAlias":
        scenario = Scenario.objects.filter(
            project__organization=organization,
            project__slug=_required(metadata, "project"),
            slug=_required(spec, "scenario"),
        ).first()
        if scenario is None:
            raise ControlPlaneGitOpsError("unknown scenario in organization/project")
        instance, created = _create_only(
            ScenarioAlias,
            lookup={"organization": organization, "alias": _required(metadata, "alias")},
            values={"scenario": scenario, "status": spec.get("status", "active")},
        )
    elif kind == "Consumer":
        instance, created = _create_only(
            Consumer,
            lookup={"organization": organization, "subject": _required(metadata, "subject")},
            values={
                "name": _required(spec, "name"),
                "protocol": _required(spec, "protocol"),
                "status": spec.get("status", "active"),
            },
        )
    elif kind == "ConsumerBinding":
        consumer = Consumer.objects.filter(
            organization=organization, subject=_required(metadata, "consumer_subject")
        ).first()
        scenario = Scenario.objects.filter(
            project__organization=organization,
            project__slug=_required(metadata, "project"),
            slug=_required(metadata, "scenario"),
        ).first()
        if consumer is None or scenario is None:
            raise ControlPlaneGitOpsError("unknown consumer or scenario in organization")
        capabilities = spec.get("capabilities")
        if not isinstance(capabilities, list):
            raise ControlPlaneGitOpsError("capabilities must be a list")
        instance, created = _create_only(
            ConsumerBinding,
            lookup={"consumer": consumer, "scenario": scenario},
            values={"capabilities": capabilities, "status": spec.get("status", "active")},
        )
    else:
        raise ControlPlaneGitOpsError(f"unsupported kind: {kind!r}")
    return instance, created, organization.pk
