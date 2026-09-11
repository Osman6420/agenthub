"""Tool registry services: register reviewed definitions/bindings and resolve the
exact, active binding a release pins. All resolution is tenant-scoped and fails
closed; nothing here performs egress (that is the proxy's job in a later increment).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.catalog.models import Scenario
from apps.tools.models import ToolBinding, ToolDefinition, ToolStatus
from apps.tools.tool_schema import MAX_TIMEOUT_SECONDS


class ToolRegistryError(ValueError):
    """Raised for safe, content-free tool-registry diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@transaction.atomic
def register_tool_definition(*, artifact: ArtifactVersion) -> ToolDefinition:
    from apps.ingestion.connections import materialize_connection

    if artifact.type != ArtifactType.TOOL_DEFINITION:
        raise ToolRegistryError("NOT_A_TOOL_DEFINITION")
    spec = artifact.body.get("spec", {})
    if artifact.organization.slug not in spec.get("allowed_organizations", []):
        raise ToolRegistryError("TOOL_NOT_ALLOWED_FOR_ORG")
    existing = ToolDefinition.objects.filter(
        organization_id=artifact.organization_id,
        logical_id=artifact.logical_id,
        version=artifact.version,
    ).first()
    if existing is not None:
        if existing.checksum != artifact.checksum:
            raise ToolRegistryError("TOOL_DEFINITION_CHECKSUM_CONFLICT")
        materialize_connection(profile=existing, actor=artifact.created_by)
        return existing
    definition, _ = ToolDefinition.objects.get_or_create(
        organization_id=artifact.organization_id,
        logical_id=artifact.logical_id,
        version=artifact.version,
        defaults={
            "manifest": artifact.body,
            "checksum": artifact.checksum,
            "protocol": str(spec["protocol"]),
            "risk": str(spec["risk"]),
            "side_effecting": bool(spec["side_effecting"]),
            "status": ToolStatus.ACTIVE,
        },
    )
    if definition.checksum != artifact.checksum:
        raise ToolRegistryError("TOOL_DEFINITION_CHECKSUM_CONFLICT")
    materialize_connection(profile=definition, actor=artifact.created_by)
    return definition


@transaction.atomic
def register_tool_binding(*, artifact: ArtifactVersion) -> ToolBinding:
    if artifact.type != ArtifactType.TOOL_BINDING:
        raise ToolRegistryError("NOT_A_TOOL_BINDING")
    spec = artifact.body.get("spec", {})
    definition = _resolve_active_definition(
        organization_id=artifact.organization_id, tool_ref=str(spec["tool_ref"])
    )
    approval = spec["approval"]
    # Fail-closed policy invariant: high-risk side effects require approval.
    # Approver authority and typed human SoD are server policy, not artifact input.
    if definition.requires_approval and not approval["required"]:
        raise ToolRegistryError("HIGH_RISK_REQUIRES_APPROVAL")

    existing = ToolBinding.objects.filter(
        organization_id=artifact.organization_id,
        logical_id=artifact.logical_id,
        version=artifact.version,
    ).first()
    if existing is not None:
        if existing.checksum != artifact.checksum:
            raise ToolRegistryError("TOOL_BINDING_CHECKSUM_CONFLICT")
        return existing
    binding = ToolBinding(
        organization=artifact.organization,
        tool_definition=definition,
        logical_id=artifact.logical_id,
        version=artifact.version,
        manifest=artifact.body,
        checksum=artifact.checksum,
        approval_required=bool(approval["required"]) or definition.requires_approval,
        status=ToolStatus.ACTIVE,
    )
    binding.full_clean()
    binding.save()
    return binding


def resolve_pinned_tool_binding(*, scenario: Scenario, artifact: ArtifactVersion) -> dict[str, Any]:
    """Return the manifest enrichment for a release-pinned tool binding.

    Fails closed unless a registered, active binding whose checksum matches the pinned
    artifact — and an active definition — exist in the scenario's organization.
    """
    organization_id = scenario.project.organization_id
    if artifact.organization_id != organization_id:
        raise ToolRegistryError("TOOL_BINDING_CROSS_TENANT")
    binding = ToolBinding.objects.filter(
        organization_id=organization_id,
        logical_id=artifact.logical_id,
        version=artifact.version,
        status=ToolStatus.ACTIVE,
    ).first()
    if binding is None:
        raise ToolRegistryError("TOOL_BINDING_NOT_REGISTERED")
    if binding.checksum != artifact.checksum:
        raise ToolRegistryError("TOOL_BINDING_CHECKSUM_CONFLICT")
    definition = binding.tool_definition
    if definition.status != ToolStatus.ACTIVE:
        raise ToolRegistryError("TOOL_DEFINITION_DISABLED")
    spec = definition.manifest.get("spec", {})
    timeout_seconds = spec.get("timeout_seconds") if isinstance(spec, dict) else None
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ToolRegistryError("TOOL_TIMEOUT_UNBOUNDED")
    return {
        "binding_ref": f"{binding.logical_id}:v{binding.version}",
        "binding_checksum": binding.checksum,
        "definition_ref": f"{definition.logical_id}:v{definition.version}",
        "definition_checksum": definition.checksum,
        "protocol": definition.protocol,
        "risk": definition.risk,
        "side_effecting": definition.side_effecting,
        "approval_required": binding.approval_required,
        # Pinned so synchronous admission can bound a call from the manifest alone, without
        # re-reading a definition the release has already checksum-matched.
        "timeout_seconds": timeout_seconds,
    }


def _resolve_active_definition(*, organization_id: int, tool_ref: str) -> ToolDefinition:
    if ":v" not in tool_ref:
        raise ToolRegistryError("TOOL_REF_INVALID")
    logical_id, _, version_text = tool_ref.rpartition(":v")
    if not version_text.isdigit():
        raise ToolRegistryError("TOOL_REF_INVALID")
    definition = ToolDefinition.objects.filter(
        organization_id=organization_id,
        logical_id=logical_id,
        version=int(version_text),
        status=ToolStatus.ACTIVE,
    ).first()
    if definition is None:
        raise ToolRegistryError("TOOL_DEFINITION_NOT_FOUND")
    return definition
