"""Scenario Studio release-manifest authoring services.

The browser supplies only exact artifact-version identifiers and manifest roles.
This module re-resolves those identifiers within the trusted scenario tenant and
reuses the canonical release compiler for both no-write preflight and candidate
creation. It intentionally contains no alternate manifest validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.identity.scenario_actions import authorize_scenario_action
from apps.releases.compiler import (
    MAX_MANIFEST_ROLE_LENGTH,
    ArtifactRef,
    CompileError,
    compile_release,
    workflow_manifest_requirements,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.releases.scenario_artifacts import (
    SCENARIO_SCOPED_ROLES,
    scenario_artifact_logical_id,
)
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization
from apps.workflows.compiler import WorkflowCompileError, compile_workflow
from apps.workflows.models import CustomNodeDefinition, CustomNodeStatus

MAX_MANIFEST_ARTIFACTS = 50
MAX_MANIFEST_REQUEST_BYTES = 64 * 1024


def compile_operator_candidate(
    *,
    scenario: Scenario,
    refs: list[ArtifactRef],
    runtime_version: str,
    actor: Any,
    request_id: str = "",
    trace_id: str = "",
) -> ScenarioRelease:
    """Serialize with access transitions/offboarding, then compile and audit atomically."""
    try:
        with transaction.atomic():
            set_tenant_context(scenario.organization_id)
            organization = (
                Organization.objects.select_for_update()
                .filter(pk=scenario.organization_id, status="active")
                .first()
            )
            if organization is None:
                raise PermissionDenied
            current = (
                Scenario.objects.select_for_update()
                .filter(
                    pk=scenario.pk,
                    organization=organization,
                    project__organization=organization,
                )
                .first()
            )
            if current is None:
                raise PermissionDenied
            if not authorize_scenario_action(
                user=actor, scenario=current, action="compile"
            ).allowed:
                raise PermissionDenied
            release = compile_release(
                scenario=current,
                refs=refs,
                runtime_version=runtime_version,
                created_by=actor.get_username(),
            )
            record_event(
                actor_type="user",
                actor_id=actor.get_username(),
                action="console.scenario.release.compile",
                outcome="success",
                organization_id=current.organization_id,
                resource_type="scenario_release",
                resource_id=str(release.pk),
                reason=release.artifact_manifest_sha256,
                request_id=request_id,
                trace_id=trace_id,
            )
            return release
    except PermissionDenied:
        record_event(
            actor_type="user",
            actor_id=actor.get_username(),
            action="console.scenario.release.compile",
            outcome="deny",
            organization_id=scenario.organization_id,
            resource_type="scenario",
            resource_id=str(scenario.pk),
            reason="SCENARIO_COMPILE_FORBIDDEN",
            request_id=request_id,
            trace_id=trace_id,
        )
        raise


_REQUEST_ERROR_MESSAGES = {
    "manifest_items_invalid": "Manifest 1–50 exact artifact seçimi içermelidir.",
    "manifest_item_invalid": "Manifest satırı exact artifact ID ve rol içermelidir.",
    "manifest_role_invalid": "Manifest rolü geçersizdir.",
    "duplicate_artifact_version": "Aynı exact artifact manifestte bir kez seçilebilir.",
    "artifact_not_found": "Seçilen exact artifact bu senaryo kapsamında bulunamadı.",
    "workflow_artifact_required": "Dependency analizi için exact workflow artifact seçilmelidir.",
}


class ManifestRequestError(ValueError):
    """Stable, content-free request failure before canonical compilation."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _REQUEST_ERROR_MESSAGES else "manifest_item_invalid"
        super().__init__(_REQUEST_ERROR_MESSAGES[self.code])

    def as_diagnostic(self) -> dict[str, str]:
        return {"code": self.code, "message": _REQUEST_ERROR_MESSAGES[self.code]}


@dataclass(frozen=True)
class ManifestPreflightResult:
    ok: bool
    diagnostics: list[dict[str, Any]]
    artifact_manifest_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "diagnostics": self.diagnostics,
        }
        if self.artifact_manifest_sha256 is not None:
            result["artifact_manifest_sha256"] = self.artifact_manifest_sha256
        return result


def resolve_manifest_refs(*, scenario: Scenario, items: Any) -> list[ArtifactRef]:
    """Resolve a bounded browser manifest within ``scenario``'s organization."""

    if not isinstance(items, list) or not 1 <= len(items) <= MAX_MANIFEST_ARTIFACTS:
        raise ManifestRequestError("manifest_items_invalid")

    parsed: list[tuple[int, str]] = []
    artifact_ids: list[int] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"artifact_version_id", "role"}:
            raise ManifestRequestError("manifest_item_invalid")
        artifact_id = item.get("artifact_version_id")
        role = item.get("role")
        if isinstance(artifact_id, bool) or not isinstance(artifact_id, int) or artifact_id <= 0:
            raise ManifestRequestError("manifest_item_invalid")
        if (
            not isinstance(role, str)
            or not role
            or len(role) > MAX_MANIFEST_ROLE_LENGTH
            or not all(character.isalnum() or character in "._-" for character in role)
        ):
            raise ManifestRequestError("manifest_role_invalid")
        parsed.append((artifact_id, role))
        artifact_ids.append(artifact_id)

    if len(set(artifact_ids)) != len(artifact_ids):
        raise ManifestRequestError("duplicate_artifact_version")

    artifacts = {
        artifact.pk: artifact
        for artifact in ArtifactVersion.objects.filter(
            organization_id=scenario.organization_id,
            pk__in=artifact_ids,
        )
    }
    if len(artifacts) != len(artifact_ids):
        # Foreign and nonexistent IDs deliberately share one non-disclosing result.
        raise ManifestRequestError("artifact_not_found")

    return [
        ArtifactRef(
            role=role,
            type=artifacts[artifact_id].type,
            logical_id=artifacts[artifact_id].logical_id,
            version=artifacts[artifact_id].version,
        )
        for artifact_id, role in parsed
    ]


def candidate_runtime_version(scenario: Scenario) -> str:
    active = ScenarioRelease.objects.filter(
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
    ).first()
    return active.runtime_version if active is not None else "runtime:v1"


def analyze_workflow_requirements(
    *,
    scenario: Scenario,
    workflow_artifact_id: Any,
) -> dict[str, Any]:
    """Extract exact manifest-role requirements from the canonical compiled graph."""

    if (
        isinstance(workflow_artifact_id, bool)
        or not isinstance(workflow_artifact_id, int)
        or workflow_artifact_id <= 0
    ):
        raise ManifestRequestError("workflow_artifact_required")
    artifact = ArtifactVersion.objects.filter(
        pk=workflow_artifact_id,
        organization_id=scenario.organization_id,
        type=ArtifactType.WORKFLOW_DEFINITION,
    ).first()
    if artifact is None:
        raise ManifestRequestError("artifact_not_found")
    if compute_checksum(artifact.body) != artifact.checksum:
        raise CompileError(
            "workflow artifact checksum mismatch",
            code="artifact_checksum_mismatch",
            role="workflow_definition",
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        )

    allowed_custom_nodes = frozenset(
        f"{item.logical_id}.v{item.version}"
        for item in CustomNodeDefinition.objects.filter(
            organization_id=scenario.organization_id,
            status=CustomNodeStatus.ACTIVE,
        )
    )
    try:
        compiled = compile_workflow(
            artifact.body,
            allowed_custom_nodes=allowed_custom_nodes,
        )
    except WorkflowCompileError as exc:
        raise CompileError(
            f"workflow compilation failed: {exc}",
            code="workflow_compile_failed",
            role="workflow_definition",
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        ) from exc

    requirements = workflow_manifest_requirements(compiled.graph)

    ordered = sorted(
        requirements.values(),
        key=lambda item: (item["role"] != "workflow_definition", item["role"]),
    )
    for item in ordered:
        item["node_ids"].sort()
    return {
        "workflow": {
            "artifact_version_id": artifact.pk,
            "logical_id": artifact.logical_id,
            "version": artifact.version,
            "checksum": artifact.checksum,
        },
        "requirements": ordered,
    }


_MISSING_ROLE_LABELS: dict[str, str] = {
    ArtifactType.PROMPT_TEMPLATE: "istem metni",
    ArtifactType.MODEL_PROFILE: "model seçimi",
    ArtifactType.RETRIEVAL_PROFILE: "arama profili",
    ArtifactType.TRANSFORM_PROFILE: "dönüşüm profili",
    ArtifactType.TOOL_BINDING: "araç bağlantısı",
    ArtifactType.WORKFLOW_DEFINITION: "akış tanımı",
    ArtifactType.INPUT_CONTRACT: "girdi sözleşmesi",
    ArtifactType.OUTPUT_CONTRACT: "çıktı sözleşmesi",
    ArtifactType.EVAL_SUITE: "test soruları",
}


@dataclass(frozen=True)
class DerivedManifest:
    """A manifest computed from the scenario and its workflow, with nothing to choose."""

    refs: list[ArtifactRef]
    missing: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return not self.missing

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "missing": self.missing,
            "pins": [
                {
                    "role": ref.role,
                    "artifact_type": ref.type,
                    "logical_id": ref.logical_id,
                    "version": ref.version,
                }
                for ref in self.refs
            ],
        }


def _describe_missing(role: str, artifact_type: str, node_ids: list[str]) -> dict[str, Any]:
    label = _MISSING_ROLE_LABELS.get(artifact_type, artifact_type)
    if node_ids:
        where = ", ".join(node_ids[:3])
        message = f"'{where}' adımının {label} henüz yayımlanmamış."
    else:
        message = f"Senaryonun {label} henüz yayımlanmamış."
    return {
        "role": role,
        "artifact_type": artifact_type,
        "node_ids": node_ids,
        "message": message,
    }


def derive_manifest(*, scenario: Scenario, workflow_artifact: ArtifactVersion) -> DerivedManifest:
    """Compute the exact manifest for ``workflow_artifact`` without operator input.

    Every pin a release needs is already determined by the scenario and the published
    workflow, so asking an author to re-select them by logical id was pure ceremony that
    silently produced wrong roles (a role defaulted to the *artifact type* name, so a
    ``retrieve`` node looking up ``ret_<identity>_profile`` found nothing and failed closed
    at request time).

    Resolution is deterministic: node-derived roles, tool bindings and transform profiles
    name their artifact's ``logical_id`` verbatim, and the scenario-owned contracts and
    evaluation suite use :func:`scenario_artifact_logical_id`. Missing artifacts are
    reported in author-facing language rather than raising, so a caller can render "what is
    still needed" instead of a compiler diagnostic.
    """

    organization_id = scenario.organization_id
    refs: list[ArtifactRef] = [
        ArtifactRef(
            role="workflow_definition",
            type=ArtifactType.WORKFLOW_DEFINITION,
            logical_id=workflow_artifact.logical_id,
            version=workflow_artifact.version,
        )
    ]
    missing: list[dict[str, Any]] = []

    requirements = analyze_workflow_requirements(
        scenario=scenario,
        workflow_artifact_id=workflow_artifact.pk,
    )["requirements"]

    wanted: list[tuple[str, str, str, list[str]]] = []
    for requirement in requirements:
        role = str(requirement["role"])
        if role == "workflow_definition":
            continue
        artifact_type = str(requirement["artifact_type"])
        # Node-derived roles, tool binding roles and transform profile roles are the
        # artifact's logical id verbatim; a child workflow strips its reserved prefix.
        logical_id = role[len("child_workflow.") :] if role.startswith("child_workflow.") else role
        wanted.append((role, artifact_type, logical_id, list(requirement["node_ids"])))

    for artifact_type in SCENARIO_SCOPED_ROLES:
        wanted.append(
            (
                artifact_type,
                artifact_type,
                scenario_artifact_logical_id(scenario, artifact_type),
                [],
            )
        )

    for role, artifact_type, logical_id, node_ids in wanted:
        artifact = (
            ArtifactVersion.objects.filter(
                organization_id=organization_id,
                type=artifact_type,
                logical_id=logical_id,
            )
            .order_by("-version")
            .first()
        )
        if artifact is None:
            missing.append(_describe_missing(role, artifact_type, node_ids))
            continue
        refs.append(
            ArtifactRef(
                role=role,
                type=artifact.type,
                logical_id=artifact.logical_id,
                version=artifact.version,
            )
        )
    return DerivedManifest(refs=refs, missing=missing)


def preflight_release(
    *,
    scenario: Scenario,
    refs: list[ArtifactRef],
    runtime_version: str,
    created_by: str,
) -> ManifestPreflightResult:
    """Run the canonical compiler and roll back every database write.

    ``compile_release`` may create a canonical ``WorkflowVersion`` and candidate
    ``ScenarioRelease``. The outer transaction is always marked for rollback, so a
    successful preflight has the same durable no-write property as a rejected one.
    """

    with transaction.atomic():
        try:
            release = compile_release(
                scenario=scenario,
                refs=refs,
                runtime_version=runtime_version,
                created_by=created_by,
            )
        except CompileError as exc:
            result = ManifestPreflightResult(
                ok=False,
                diagnostics=[exc.as_diagnostic()],
            )
        else:
            result = ManifestPreflightResult(
                ok=True,
                diagnostics=[],
                artifact_manifest_sha256=release.artifact_manifest_sha256,
            )
        finally:
            transaction.set_rollback(True)
    return result
