"""Release compiler and promotion.

``compile_release`` resolves artifact references to exact versions within the
scenario's organization, re-validates each body, computes a manifest checksum, and
creates a ``candidate`` release. It fails closed: a missing reference, a validation
failure, or an inline secret raises ``CompileError`` and no candidate is created.

``promote_release`` performs the atomic active-pointer swap; the database
single-active constraint guarantees only one active release per scenario.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import canonical_json, compute_checksum, validate_body
from apps.catalog.models import Scenario
from apps.releases.models import ReleaseStatus, ScenarioRelease

MAX_MANIFEST_ROLE_LENGTH = 128


_PUBLIC_DIAGNOSTIC_MESSAGES = {
    "release_compile_failed": "Candidate manifest canonical compiler tarafından reddedildi.",
    "manifest_empty": "Candidate manifest en az bir exact artifact içermelidir.",
    "index_version_invalid": "Index version pinleri pozitif tam sayı olmalıdır.",
    "artifact_unresolved": "Seçilen exact artifact bu senaryo kapsamında çözümlenemedi.",
    "duplicate_manifest_role": "Manifest rolleri benzersiz olmalıdır.",
    "role_type_mismatch": "Manifest rolü seçilen artifact type ile uyumlu değildir.",
    "artifact_validation_failed": "Immutable artifact canonical doğrulamadan geçemedi.",
    "artifact_checksum_mismatch": "Immutable artifact checksum doğrulaması başarısız oldu.",
    "tool_binding_invalid": "Tool binding aktif, kayıtlı veya release için uygun değildir.",
    "workflow_role_invalid": "Ana workflow canonical workflow_definition rolünü kullanmalıdır.",
    "workflow_compile_failed": "Workflow canonical compiler tarafından reddedildi.",
    "transform_profile_unpinned": "Transform node için exact transform profile pini eksik.",
    "child_workflow_invalid": "Child workflow pini eksik, belirsiz veya geçersiz.",
    "workflow_missing": "Candidate manifest bir canonical workflow_definition pini içermelidir.",
    "compiled_workflow_invalid": "Derlenen workflow graph yapısı geçersiz.",
    "agent_policy_invalid": "Agent loop policy derlenmiş graph içinde geçersiz.",
    "agent_tool_unpinned": "Agent loop için gerekli exact tool binding pini eksik.",
    "agent_verification_tool_invalid": "Agent doğrulama tool pini eksik veya yan etkisiz değildir.",
}


def _safe_diagnostic_identifier(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_MANIFEST_ROLE_LENGTH:
        return None
    if not all(character.isalnum() or character in "._-" for character in value):
        return None
    return value


class CompileError(ValueError):
    """Internal compiler failure with a stable, safe operator diagnostic."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "release_compile_failed",
        role: str | None = None,
        artifact_type: str | None = None,
        node_id: str | None = None,
        json_pointer: str | None = None,
    ) -> None:
        self.code = code if code in _PUBLIC_DIAGNOSTIC_MESSAGES else "release_compile_failed"
        self.role = _safe_diagnostic_identifier(role)
        self.artifact_type = artifact_type if artifact_type in ArtifactType.values else None
        self.node_id = _safe_diagnostic_identifier(node_id)
        self.json_pointer = (
            json_pointer
            if isinstance(json_pointer, str)
            and json_pointer.startswith("/")
            and len(json_pointer) <= 512
            else None
        )
        super().__init__(message)

    def as_diagnostic(self) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {
            "code": self.code,
            "message": _PUBLIC_DIAGNOSTIC_MESSAGES[self.code],
        }
        for key in ("role", "artifact_type", "node_id", "json_pointer"):
            value = getattr(self, key)
            if value is not None:
                diagnostic[key] = value
        return diagnostic


@dataclass(frozen=True)
class ArtifactRef:
    """A reference to a specific artifact version, bound to a manifest role."""

    role: str
    type: str
    logical_id: str
    version: int


def role_accepts_artifact_type(role: str, artifact_type: str) -> bool:
    """Return whether a manifest role may pin ``artifact_type``.

    Canonical singleton roles use the artifact type verbatim. Repeatable roles use a
    type-prefixed namespace (for example ``tool_binding.search`` or
    ``prompt_template.summary``). This prevents type confusion while retaining
    multiple exact pins of one compatible type.
    """
    if (
        not isinstance(role, str)
        or not role
        or len(role) > MAX_MANIFEST_ROLE_LENGTH
        or not all(character.isalnum() or character in "._-" for character in role)
    ):
        return False
    # Child composition pins exact workflow definitions through the same registry.
    if role.startswith("child_workflow."):
        return artifact_type == ArtifactType.WORKFLOW_DEFINITION
    reserved = {value for value, _label in ArtifactType.choices}
    prefix = role.split(".", 1)[0]
    if role in reserved or prefix in reserved:
        return role == artifact_type or role.startswith(f"{artifact_type}.")
    # Workflow runtimes require their canonical singleton role. Other
    # types may intentionally use semantic roles such as ``prompt`` or ``search``;
    # those remain compatible unless they impersonate a reserved type namespace.
    return artifact_type != ArtifactType.WORKFLOW_DEFINITION


def _resolve(scenario: Scenario, ref: ArtifactRef) -> ArtifactVersion:
    organization_id = scenario.project.organization_id
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type=ref.type,
        logical_id=ref.logical_id,
        version=ref.version,
    ).first()
    if artifact is None:
        raise CompileError(
            f"unresolved reference for role '{ref.role}': "
            f"{ref.type} {ref.logical_id}:v{ref.version} not found in organization",
            code="artifact_unresolved",
            role=ref.role,
            artifact_type=ref.type,
        )
    return artifact


@transaction.atomic
def compile_release(
    *,
    scenario: Scenario,
    refs: list[ArtifactRef],
    runtime_version: str,
    created_by: str,
    index_versions: list[int] | None = None,
) -> ScenarioRelease:
    if not refs:
        raise CompileError(
            "a release must reference at least one artifact",
            code="manifest_empty",
        )

    # Optional pinned retrieval indexes. Readiness/tenant checks happen at the
    # promotion gate (Sprint 6); the retriever additionally filters by the release's
    # organization, so a stray pin can never surface another tenant's chunks.
    pinned_indexes = sorted({int(v) for v in (index_versions or [])})
    if any(v <= 0 for v in pinned_indexes):
        raise CompileError(
            "index version ids must be positive integers",
            code="index_version_invalid",
        )

    artifacts_manifest: dict[str, dict[str, object]] = {}
    workflow_checksum = ""
    compiled_workflow_graph: dict[str, object] | None = None
    for ref in refs:
        if ref.role in artifacts_manifest:
            raise CompileError(
                f"duplicate role in release: {ref.role}",
                code="duplicate_manifest_role",
                role=ref.role,
                artifact_type=ref.type,
            )
        if not role_accepts_artifact_type(ref.role, ref.type):
            raise CompileError(
                f"role '{ref.role}' is incompatible with artifact type '{ref.type}'",
                code="role_type_mismatch",
                role=ref.role,
                artifact_type=ref.type,
            )
        artifact = _resolve(scenario, ref)
        # Defense in depth: re-validate the pinned body at compile time.
        try:
            validate_body(artifact.type, artifact.body)
        except ValueError as exc:
            raise CompileError(
                f"role '{ref.role}' failed validation: {exc}",
                code="artifact_validation_failed",
                role=ref.role,
                artifact_type=ref.type,
            ) from exc
        # Detect drift between stored checksum and current body.
        if compute_checksum(artifact.body) != artifact.checksum:
            raise CompileError(
                f"checksum mismatch for role '{ref.role}'",
                code="artifact_checksum_mismatch",
                role=ref.role,
                artifact_type=ref.type,
            )
        artifacts_manifest[ref.role] = {
            "type": artifact.type,
            "ref": artifact.ref,
            "checksum": artifact.checksum,
        }
        if artifact.type == "tool_binding":
            # Pin the exact, active, registered binding (and its definition) so the
            # execution proxy enforces a release-pinned allowlist. Fails closed.
            from apps.tools.services import ToolRegistryError, resolve_pinned_tool_binding

            try:
                artifacts_manifest[ref.role]["tool"] = resolve_pinned_tool_binding(
                    scenario=scenario, artifact=artifact
                )
            except ToolRegistryError as exc:
                raise CompileError(
                    f"role '{ref.role}' tool binding failed: {exc}",
                    code="tool_binding_invalid",
                    role=ref.role,
                    artifact_type=ref.type,
                ) from exc
        if artifact.type == "workflow_definition":
            if ref.role.startswith("child_workflow."):
                # A pinned child runtime (P2.6.5). It is not the parent's own workflow; the
                # composition pinner below derives its released scenario/release from this pin.
                pass
            elif ref.role != "workflow_definition":
                raise CompileError(
                    "workflow definition must use the workflow_definition or child_workflow.* role",
                    code="workflow_role_invalid",
                    role=ref.role,
                    artifact_type=ref.type,
                )
            else:
                from apps.workflows.compiler import WorkflowCompileError
                from apps.workflows.services import compile_workflow_version

                try:
                    workflow_version = compile_workflow_version(
                        scenario=scenario,
                        source_artifact=artifact,
                        created_by=created_by,
                    )
                except WorkflowCompileError as exc:
                    raise CompileError(
                        f"workflow compilation failed: {exc}",
                        code="workflow_compile_failed",
                        role=ref.role,
                        artifact_type=ref.type,
                    ) from exc
                workflow_checksum = workflow_version.checksum
                compiled_workflow_graph = workflow_version.compiled_graph
    if compiled_workflow_graph is not None:
        # Fail closed: every workflow ``transform`` node must reference a manifest role that pins
        # an immutable ``transform_profile`` in this same release (P2.6.1 D1), so the runtime can
        # never resolve an unpinned, foreign, mutable or ``latest`` transform profile.
        _assert_transform_profiles_pinned(compiled_workflow_graph, artifacts_manifest)
        # Embedded agent policy is executable authority. Every declared/verification tool role must
        # resolve to the same release's exact active binding, with verification remaining
        # observation-only, matching the governed agent policy contract.
        _assert_agent_loop_tools_pinned(compiled_workflow_graph, artifacts_manifest)
        # Fail closed: every ``subworkflow`` node must reference a pinned child role
        # that resolves to an exact same-organization released child scenario (P2.6.5 / ADR-0009).
        # The pin records the child kind/scenario/release/checksum so the runtime can never resolve
        # a newer, mutable, foreign or cyclic child.
        from apps.workflows.composition import (
            CompositionCompileError,
            pin_composition_children,
        )

        try:
            pin_composition_children(
                scenario=scenario,
                graph=compiled_workflow_graph,
                artifacts_manifest=artifacts_manifest,
            )
        except CompositionCompileError as exc:
            raise CompileError(
                str(exc),
                code="child_workflow_invalid",
            ) from exc

    # Deny-by-default document-ACL pins (P4.2): compile the scenario's mandatory
    # ``ScenarioDocumentSetBinding``s to published document-set-version ids. A scenario with no
    # binding pins nothing and therefore retrieves nothing. The resolver expands each to its active
    # index version at request time (pointer flip), so promotion/rollback need no recompile.
    from apps.documents.services import pinned_document_set_version_ids

    document_set_versions = pinned_document_set_version_ids(scenario)

    manifest: dict[str, object] = {
        "scenario_id": scenario.id,
        "runtime_version": runtime_version,
        "artifacts": artifacts_manifest,
    }
    if pinned_indexes:
        manifest["index_versions"] = pinned_indexes
    if document_set_versions:
        manifest["document_set_versions"] = document_set_versions
    if workflow_checksum:
        manifest["workflow_checksum"] = workflow_checksum
        if compiled_workflow_graph is not None:
            manifest["execution_mode_analysis"] = _release_execution_mode_analysis(
                compiled_workflow_graph, artifacts_manifest
            )
    if not workflow_checksum or compiled_workflow_graph is None:
        raise CompileError(
            "a release must pin one canonical workflow_definition",
            code="workflow_missing",
            role="workflow_definition",
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        )
    manifest_sha = compute_checksum(manifest)

    return ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.CANDIDATE,
        runtime_version=runtime_version,
        manifest=manifest,
        artifact_manifest_sha256=manifest_sha,
        created_by=created_by,
    )


@transaction.atomic
def promote_release(release: ScenarioRelease) -> ScenarioRelease:
    """Make ``release`` the single active release for its scenario (atomic swap).

    Minimal Sprint 2 promotion — the full gated promotion/canary/rollback path is
    Sprint 6. The DB constraint guarantees the single-active invariant.
    """
    previous = (
        ScenarioRelease.objects.select_for_update()
        .filter(scenario_id=release.scenario_id, status=ReleaseStatus.ACTIVE)
        .exclude(pk=release.pk)
        .first()
    )
    if previous is not None:
        previous.status = ReleaseStatus.SUPERSEDED
        previous.save(update_fields=["status"])

    release.status = ReleaseStatus.ACTIVE
    release.promoted_at = timezone.now()
    release.save(update_fields=["status", "promoted_at"])
    return release


def _assert_transform_profiles_pinned(
    graph: dict[str, object], manifest: dict[str, dict[str, object]]
) -> None:
    nodes = graph.get("nodes", [])
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "transform":
            continue
        config = node.get("config", {})
        role = config.get("transform_profile_ref") if isinstance(config, dict) else None
        entry = manifest.get(role) if isinstance(role, str) else None
        if not isinstance(entry, dict) or entry.get("type") != ArtifactType.TRANSFORM_PROFILE:
            raise CompileError(
                f"transform node references an unpinned transform_profile role: {role!r}",
                code="transform_profile_unpinned",
                role=role if isinstance(role, str) else None,
                artifact_type=ArtifactType.TRANSFORM_PROFILE,
                node_id=str(node.get("id", "")),
            )


_MISSING_ANALYSIS = {
    "supported_execution_modes": ["background"],
    "sync_blockers": [{"code": "compiled_mode_analysis_missing", "node_ids": []}],
    "sync_budget_seconds": 0,
}


def _tool_sync_evidence(
    node: object, manifest: dict[str, dict[str, object]]
) -> tuple[str | None, int]:
    """Decide whether one pinned ``tool`` node is safe for a synchronous request."""

    from apps.tools.tool_schema import MAX_TIMEOUT_SECONDS

    if not isinstance(node, dict) or node.get("type") != "tool":
        return "tool_pause_policy_unproven", 0
    config = node.get("config")
    role = config.get("binding_role") if isinstance(config, dict) else None
    entry = manifest.get(role) if isinstance(role, str) else None
    pin = entry.get("tool") if isinstance(entry, dict) else None
    if not isinstance(pin, dict):
        return "tool_not_pinned", 0
    if pin.get("approval_required"):
        # An approval is a durable pause; a synchronous request can never wait for one.
        return "tool_requires_approval", 0
    timeout = pin.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        return "tool_timeout_unpinned", 0
    if not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        return "tool_timeout_unpinned", 0
    return None, timeout


def _release_execution_mode_analysis(
    graph: dict[str, object], manifest: dict[str, dict[str, object]]
) -> dict[str, object]:
    """Re-decide synchronous support against the release's pinned tool evidence.

    The workflow compiler cannot see a binding, so every ``tool`` node is unproven there. Here the
    pin is exact: a bounded transport timeout with no approval pause makes the call safe to run
    inside a request, and the summed timeouts give admission a finite wall-clock budget.
    """

    analysis = graph.get("execution_mode_analysis")
    if not isinstance(analysis, dict):
        return dict(_MISSING_ANALYSIS)
    raw_blockers = analysis.get("sync_blockers")
    raw_nodes = graph.get("nodes")
    if not isinstance(raw_blockers, list) or not isinstance(raw_nodes, list):
        return dict(_MISSING_ANALYSIS)
    nodes_by_id = {
        node["id"]: node
        for node in raw_nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }

    blocker_nodes: dict[str, list[str]] = {}
    budget = 0
    for entry in raw_blockers:
        if not isinstance(entry, dict):
            return dict(_MISSING_ANALYSIS)
        code = entry.get("code")
        node_ids = entry.get("node_ids")
        if not isinstance(code, str) or not isinstance(node_ids, list):
            return dict(_MISSING_ANALYSIS)
        if code != "tool_pause_policy_unproven":
            # Only the tool blocker carries release-pinned evidence. Everything else — durable
            # waits, fan-out, child runs, unproven agent/custom bounds — stays background-only.
            blocker_nodes.setdefault(code, []).extend(str(node_id) for node_id in node_ids)
            continue
        for node_id in node_ids:
            resolved, seconds = _tool_sync_evidence(nodes_by_id.get(str(node_id)), manifest)
            if resolved is not None:
                blocker_nodes.setdefault(resolved, []).append(str(node_id))
            else:
                budget += seconds

    blockers = [
        {"code": code, "node_ids": sorted(blocker_nodes[code])} for code in sorted(blocker_nodes)
    ]
    supported = ["background"]
    if not blockers:
        supported.append("sync")
    return {
        "supported_execution_modes": supported,
        "sync_blockers": blockers,
        "sync_budget_seconds": budget if not blockers else 0,
    }


def _assert_agent_loop_tools_pinned(
    graph: dict[str, object], manifest: dict[str, dict[str, object]]
) -> None:
    """Bind every embedded agent policy to exact release-pinned tool roles."""

    tool_roles = {
        role for role, entry in manifest.items() if entry.get("type") == ArtifactType.TOOL_BINDING
    }
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise CompileError(
            "compiled workflow nodes are invalid",
            code="compiled_workflow_invalid",
        )
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "agent_loop":
            continue
        node_id = str(node.get("id", ""))
        config = node.get("config")
        policy = config.get("policy") if isinstance(config, dict) else None
        if not isinstance(policy, dict):
            raise CompileError(
                f"agent_loop compiled policy is missing: {node_id}",
                code="agent_policy_invalid",
                node_id=node_id,
            )
        declared = policy.get("tools")
        if not isinstance(declared, list) or any(not isinstance(role, str) for role in declared):
            raise CompileError(
                f"agent_loop compiled tools are invalid: {node_id}",
                code="agent_policy_invalid",
                node_id=node_id,
            )
        missing = sorted(set(declared) - tool_roles)
        if missing:
            raise CompileError(
                f"agent_loop declares tools with no pinned tool_binding role: {missing}",
                code="agent_tool_unpinned",
                role=missing[0],
                artifact_type=ArtifactType.TOOL_BINDING,
                node_id=node_id,
            )

        actions = policy.get("actions")
        verify_roles = actions.get("verify_roles", []) if isinstance(actions, dict) else []
        if not isinstance(verify_roles, list):
            raise CompileError(
                f"agent_loop verification roles are invalid: {node_id}",
                code="agent_policy_invalid",
                node_id=node_id,
            )
        for role in verify_roles:
            if role == "retrieval":
                continue
            pinned = manifest.get(str(role), {}).get("tool")
            if not isinstance(pinned, dict):
                raise CompileError(
                    f"agent_loop verification role has no pinned tool_binding: {role}",
                    code="agent_verification_tool_invalid",
                    role=str(role),
                    artifact_type=ArtifactType.TOOL_BINDING,
                    node_id=node_id,
                )
            if pinned.get("side_effecting") or pinned.get("approval_required"):
                raise CompileError(
                    f"agent_loop verification role must be a no-side-effect action: {role}",
                    code="agent_verification_tool_invalid",
                    role=str(role),
                    artifact_type=ArtifactType.TOOL_BINDING,
                    node_id=node_id,
                )


def canonical_manifest(release: ScenarioRelease) -> str:
    """Canonical serialization of a release manifest (for diffing/snapshotting)."""
    return canonical_json(release.manifest)
