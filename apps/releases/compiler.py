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

from django.db import transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import canonical_json, compute_checksum, validate_body
from apps.catalog.models import Scenario
from apps.releases.models import ReleaseStatus, ScenarioRelease

MAX_MANIFEST_ROLE_LENGTH = 128


class CompileError(ValueError):
    """Raised when a release cannot be compiled from its references."""


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
    reserved = {value for value, _label in ArtifactType.choices}
    prefix = role.split(".", 1)[0]
    if role in reserved or prefix in reserved:
        return role == artifact_type or role.startswith(f"{artifact_type}.")
    # Workflow and agent runtimes require their canonical singleton roles. Other
    # types may intentionally use semantic roles such as ``prompt`` or ``search``;
    # those remain compatible unless they impersonate a reserved type namespace.
    return artifact_type not in {
        ArtifactType.WORKFLOW_DEFINITION,
        ArtifactType.AGENT_DEFINITION,
    }


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
            f"{ref.type} {ref.logical_id}:v{ref.version} not found in organization"
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
        raise CompileError("a release must reference at least one artifact")

    # Optional pinned retrieval indexes. Readiness/tenant checks happen at the
    # promotion gate (Sprint 6); the retriever additionally filters by the release's
    # organization, so a stray pin can never surface another tenant's chunks.
    pinned_indexes = sorted({int(v) for v in (index_versions or [])})
    if any(v <= 0 for v in pinned_indexes):
        raise CompileError("index version ids must be positive integers")

    artifacts_manifest: dict[str, dict[str, object]] = {}
    workflow_checksum = ""
    compiled_workflow_graph: dict[str, object] | None = None
    agent_checksum = ""
    agent_tools: list[str] = []
    for ref in refs:
        if ref.role in artifacts_manifest:
            raise CompileError(f"duplicate role in release: {ref.role}")
        if not role_accepts_artifact_type(ref.role, ref.type):
            raise CompileError(f"role '{ref.role}' is incompatible with artifact type '{ref.type}'")
        artifact = _resolve(scenario, ref)
        # Defense in depth: re-validate the pinned body at compile time.
        try:
            validate_body(artifact.type, artifact.body)
        except ValueError as exc:
            raise CompileError(f"role '{ref.role}' failed validation: {exc}") from exc
        # Detect drift between stored checksum and current body.
        if compute_checksum(artifact.body) != artifact.checksum:
            raise CompileError(f"checksum mismatch for role '{ref.role}'")
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
                raise CompileError(f"role '{ref.role}' tool binding failed: {exc}") from exc
        if artifact.type == "workflow_definition":
            if ref.role != "workflow_definition":
                raise CompileError("workflow definition must use the workflow_definition role")
            from apps.workflows.compiler import WorkflowCompileError
            from apps.workflows.services import compile_workflow_version

            try:
                workflow_version = compile_workflow_version(
                    scenario=scenario,
                    source_artifact=artifact,
                    created_by=created_by,
                )
            except WorkflowCompileError as exc:
                raise CompileError(f"workflow compilation failed: {exc}") from exc
            workflow_checksum = workflow_version.checksum
            compiled_workflow_graph = workflow_version.compiled_graph
        if artifact.type == "agent_definition":
            if ref.role != "agent_definition":
                raise CompileError("agent definition must use the agent_definition role")
            from apps.agents.compiler import AgentCompileError
            from apps.agents.services import compile_agent_version

            try:
                agent_version = compile_agent_version(
                    scenario=scenario,
                    source_artifact=artifact,
                    created_by=created_by,
                )
            except AgentCompileError as exc:
                raise CompileError(f"agent compilation failed: {exc}") from exc
            agent_checksum = agent_version.checksum
            agent_tools = list(agent_version.compiled_config.get("tools", []))

    if agent_checksum:
        # Fail closed: every tool the agent may propose must resolve to a tool_binding
        # role pinned into this same release, so the runtime's allowlist is complete.
        tool_roles = {
            role for role, entry in artifacts_manifest.items() if entry["type"] == "tool_binding"
        }
        missing = sorted(t for t in agent_tools if t not in tool_roles)
        if missing:
            raise CompileError(f"agent declares tools with no pinned tool_binding role: {missing}")

    if compiled_workflow_graph is not None:
        # Fail closed: every workflow ``transform`` node must reference a manifest role that pins
        # an immutable ``transform_profile`` in this same release (P2.6.1 D1), so the runtime can
        # never resolve an unpinned, foreign, mutable or ``latest`` transform profile.
        _assert_transform_profiles_pinned(compiled_workflow_graph, artifacts_manifest)

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
    if agent_checksum:
        manifest["agent_checksum"] = agent_checksum
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
                f"transform node references an unpinned transform_profile role: {role!r}"
            )


def canonical_manifest(release: ScenarioRelease) -> str:
    """Canonical serialization of a release manifest (for diffing/snapshotting)."""
    return canonical_json(release.manifest)
