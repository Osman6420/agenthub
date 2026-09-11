"""Capture one checked legacy composition as an immutable executable revision."""

from copy import deepcopy
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Max, Q

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.documents.models import DocumentSet, DocumentSetVersion
from apps.identity.scenario_actions import authorize_scenario_action
from apps.ingestion.models import IndexVersion
from apps.releases.models import ScenarioRelease, ScenarioRevision
from apps.releases.revision_schema import (
    MAX_REVISION_ROLES,
    REVISION_CONTRACT,
    RevisionError,
    validate_revision_snapshot,
)
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization
from apps.workflows.models import WorkflowVersion


def _artifact_snapshot(release: ScenarioRelease) -> dict[str, Any]:
    pins = release.manifest.get("artifacts")
    if not isinstance(pins, dict) or not 1 <= len(pins) <= MAX_REVISION_ROLES:
        raise RevisionError("REVISION_ARTIFACTS_INVALID")
    selectors = Q(pk__in=[])
    identities = {}
    for role, pin in pins.items():
        if not isinstance(pin, dict):
            raise RevisionError("REVISION_ARTIFACTS_INVALID")
        ref, artifact_type = pin.get("ref"), pin.get("type")
        if not isinstance(ref, str) or len(ref) > 1000 or not isinstance(artifact_type, str):
            raise RevisionError("REVISION_ARTIFACTS_INVALID")
        logical_id, separator, raw_version = ref.rpartition(":v")
        if (
            not separator
            or not raw_version.isascii()
            or not raw_version.isdigit()
            or len(raw_version) > 9
        ):
            raise RevisionError("REVISION_ARTIFACTS_INVALID")
        identity = (artifact_type, logical_id, int(raw_version))
        identities[role] = identity
        selectors |= Q(type=identity[0], logical_id=identity[1], version=identity[2])
    artifacts = {
        (row.type, row.logical_id, row.version): row
        for row in ArtifactVersion.objects.filter(organization_id=release.organization_id).filter(
            selectors
        )
    }
    result = {}
    for role, identity in identities.items():
        artifact = artifacts.get(identity)
        if artifact is None or artifact.checksum != pins[role].get("checksum"):
            raise RevisionError("REVISION_ARTIFACT_UNRESOLVED")
        result[role] = {
            "id": artifact.pk,
            "type": artifact.type,
            "ref": artifact.ref,
            "checksum": artifact.checksum,
            "body": artifact.body,
        }
    return result


def read_revision_snapshot(revision: ScenarioRevision) -> dict[str, Any]:
    """Detached, verified value; this function grants no user or retrieval authority."""
    validate_revision_snapshot(revision.snapshot)
    if (
        revision.contract_version != REVISION_CONTRACT
        or compute_checksum(revision.snapshot) != revision.checksum
        or compute_checksum(revision.snapshot["manifest"]) != revision.source_manifest_checksum
        or revision.snapshot["scope"]
        != {
            "organization_id": revision.organization_id,
            "scenario_id": revision.scenario_id,
            "source_release_id": revision.source_release_id,
        }
        or revision.snapshot["workflow"]["id"] != revision.workflow_version_id
    ):
        raise RevisionError("REVISION_INTEGRITY_FAILED")
    return deepcopy(revision.snapshot)


def capture_scenario_revision(
    *,
    release: ScenarioRelease,
    workflow_version: WorkflowVersion,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioRevision:
    """Explicit preparation only: neither switches runtime nor changes live traffic."""
    return _capture_revision(
        release=release,
        workflow_version=workflow_version,
        actor=actor,
        actor_name=actor.get_username(),
        request_id=request_id,
        trace_id=trace_id,
    )


def _capture_compiled_revision(
    *,
    release: ScenarioRelease,
    workflow_version: WorkflowVersion,
    created_by: str,
) -> ScenarioRevision:
    """Compiler-only persistence seam; its caller owns admission/CLI authorization.

    This is not an operator endpoint. The compiler must call it in the same
    transaction as release creation, after the complete canonical validation.
    """
    if not connection.in_atomic_block:
        raise RevisionError("REVISION_REQUIRES_COMPILER_TRANSACTION")
    return _capture_revision(
        release=release,
        workflow_version=workflow_version,
        actor=None,
        actor_name=created_by,
        trusted_compiler=True,
    )


def _capture_revision(
    *,
    release: ScenarioRelease,
    workflow_version: WorkflowVersion,
    actor: Any,
    actor_name: str,
    trusted_compiler: bool = False,
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioRevision:
    try:
        with transaction.atomic():
            set_tenant_context(release.organization_id)
            organization = (
                Organization.objects.select_for_update()
                .filter(pk=release.organization_id, status="active")
                .first()
            )
            if organization is None:
                raise RevisionError("REVISION_CAPTURE_FORBIDDEN")
            scenario = (
                Scenario.objects.select_for_update()
                .filter(
                    pk=release.scenario_id,
                    organization=organization,
                    project__organization=organization,
                )
                .first()
            )
            if scenario is None or (
                not trusted_compiler
                and not authorize_scenario_action(
                    user=actor, scenario=scenario, action="compile"
                ).allowed
            ):
                raise RevisionError("REVISION_CAPTURE_FORBIDDEN")
            current = (
                ScenarioRelease.objects.select_for_update()
                .filter(pk=release.pk, organization=organization, scenario=scenario)
                .first()
            )
            if current is None:
                raise RevisionError("REVISION_RELEASE_UNRESOLVED")
            existing = ScenarioRevision.objects.filter(source_release=current).first()
            if existing is not None:
                read_revision_snapshot(existing)
                if (
                    existing.source_manifest_checksum != current.artifact_manifest_sha256
                    or compute_checksum(current.manifest) != existing.source_manifest_checksum
                ):
                    raise RevisionError("REVISION_SOURCE_CONFLICT")
                if existing.workflow_version_id != workflow_version.pk:
                    raise RevisionError("REVISION_WORKFLOW_CONFLICT")
                return existing
            # Compiled workflows are immutable and the runtime role deliberately has
            # no UPDATE privilege. The mutable publication roots above remain locked.
            workflow = WorkflowVersion.objects.filter(
                pk=workflow_version.pk, organization=organization, scenario=scenario
            ).first()
            if (
                workflow is None
                or not isinstance(current.manifest, dict)
                or compute_checksum(current.manifest) != current.artifact_manifest_sha256
                or current.manifest.get("workflow_checksum") != workflow.checksum
            ):
                raise RevisionError("REVISION_SOURCE_INTEGRITY")
            artifacts = _artifact_snapshot(current)
            if artifacts.get("workflow_definition", {}).get("id") != workflow.source_artifact_id:
                raise RevisionError("REVISION_WORKFLOW_CONFLICT")
            snapshot: dict[str, Any] = {
                "contract": REVISION_CONTRACT,
                "scope": {
                    "organization_id": organization.pk,
                    "scenario_id": scenario.pk,
                    "source_release_id": current.pk,
                },
                "runtime_version": current.runtime_version,
                "manifest": current.manifest,
                "artifacts": artifacts,
                "workflow": {
                    "id": workflow.pk,
                    "checksum": workflow.checksum,
                    "compiler_version": workflow.compiler_version,
                    "graph": workflow.compiled_graph,
                },
                "data": {
                    "selection": current.manifest.get("data_selection", "legacy_pinned"),
                    "document_set_ids": current.manifest.get("document_set_ids", []),
                    "document_set_version_ids": current.manifest.get("document_set_versions", []),
                    "index_version_ids": current.manifest.get("index_versions", []),
                },
            }
            validate_revision_snapshot(snapshot)
            data = snapshot["data"]
            if DocumentSet.objects.filter(
                pk__in=data["document_set_ids"], organization=organization
            ).count() != len(data["document_set_ids"]):
                raise RevisionError("REVISION_DATA_SCOPE_INVALID")
            if DocumentSetVersion.objects.filter(
                pk__in=data["document_set_version_ids"], organization=organization
            ).count() != len(data["document_set_version_ids"]) or IndexVersion.objects.filter(
                pk__in=data["index_version_ids"], organization=organization
            ).count() != len(data["index_version_ids"]):
                raise RevisionError("REVISION_DATA_SCOPE_INVALID")
            last_number = (
                ScenarioRevision.objects.filter(scenario=scenario).aggregate(n=Max("number"))["n"]
                or 0
            )
            revision = ScenarioRevision.objects.create(
                organization=organization,
                scenario=scenario,
                source_release=current,
                workflow_version=workflow,
                number=last_number + 1,
                contract_version=REVISION_CONTRACT,
                snapshot=deepcopy(snapshot),
                checksum=compute_checksum(snapshot),
                source_manifest_checksum=current.artifact_manifest_sha256,
                created_by=actor_name,
            )
            record_event(
                actor_type="user",
                actor_id=actor_name,
                action="scenario.revision.capture",
                outcome="success",
                organization_id=organization.pk,
                resource_type="scenario_revision",
                resource_id=str(revision.pk),
                reason="IMMUTABLE_EXECUTION_SNAPSHOT",
                request_id=request_id,
                trace_id=trace_id,
                after={
                    "number": revision.number,
                    "checksum": revision.checksum,
                    "source_release_id": current.pk,
                    "workflow_version_id": workflow.pk,
                },
            )
            return revision
    except (RevisionError, ValidationError, IntegrityError) as exc:
        error = (
            exc if isinstance(exc, RevisionError) else RevisionError("REVISION_CAPTURE_CONFLICT")
        )
        record_event(
            actor_type="user",
            actor_id=actor_name,
            action="scenario.revision.capture",
            outcome="deny",
            organization_id=release.organization_id,
            resource_type="scenario_release",
            resource_id=str(release.pk),
            reason=error.code,
            request_id=request_id,
            trace_id=trace_id,
        )
        if error is exc:
            raise
        raise error from exc
