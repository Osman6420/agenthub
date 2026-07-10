"""GitOps import/export mapping between YAML documents and artifact versions.

The runtime never reads YAML; GitOps is a review/import surface only (v3 plan §1.4,
§6.4). Import validates and rejects inline secrets before persisting; export never
emits secret values (artifact bodies cannot contain them by construction).
"""

from __future__ import annotations

from typing import Any

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.tenancy.models import Organization

# GitOps schema version. It is independent from the target document revision.
API_VERSION = "agenthub/v1"

# GitOps "kind" (CamelCase) <-> ArtifactType value.
TYPE_BY_KIND: dict[str, str] = {
    "InputContract": ArtifactType.INPUT_CONTRACT,
    "OutputContract": ArtifactType.OUTPUT_CONTRACT,
    "PromptTemplate": ArtifactType.PROMPT_TEMPLATE,
    "PolicyProfile": ArtifactType.POLICY_PROFILE,
    "ModelProfile": ArtifactType.MODEL_PROFILE,
    "SourceDefinition": ArtifactType.SOURCE_DEFINITION,
    "ChunkingProfile": ArtifactType.CHUNKING_PROFILE,
    "RetrievalProfile": ArtifactType.RETRIEVAL_PROFILE,
    "WorkflowDefinition": ArtifactType.WORKFLOW_DEFINITION,
    "ToolDefinition": ArtifactType.TOOL_DEFINITION,
    "ToolBinding": ArtifactType.TOOL_BINDING,
    "MemoryPolicy": ArtifactType.MEMORY_POLICY,
    "EvalSuite": ArtifactType.EVAL_SUITE,
}
KIND_BY_TYPE: dict[str, str] = {v: k for k, v in TYPE_BY_KIND.items()}


class GitOpsError(ValueError):
    """Raised when a GitOps document is malformed."""


def import_document(
    doc: Any,
    *,
    default_organization: Organization | None,
    created_by: str,
    source_git_revision: str = "",
) -> ArtifactVersion:
    """Create an artifact version from a single parsed GitOps document."""
    if not isinstance(doc, dict):
        raise GitOpsError("document must be a mapping")
    kind = doc.get("kind")
    if kind not in TYPE_BY_KIND:
        raise GitOpsError(f"unsupported kind: {kind!r}")
    metadata = doc.get("metadata") or {}
    spec = doc.get("spec")
    if not isinstance(metadata, dict) or spec is None:
        raise GitOpsError("document must have 'metadata' and 'spec'")

    logical_id = metadata.get("logical_id")
    if not logical_id:
        raise GitOpsError("metadata.logical_id is required")

    organization = default_organization
    org_slug = metadata.get("organization")
    if org_slug:
        organization = Organization.objects.filter(slug=org_slug).first()
        if organization is None:
            raise GitOpsError(f"unknown organization: {org_slug}")
    if organization is None:
        raise GitOpsError("organization is required (metadata.organization or default)")

    version = metadata.get("version")
    return create_artifact_version(
        organization=organization,
        artifact_type=TYPE_BY_KIND[kind],
        logical_id=str(logical_id),
        body=spec,
        created_by=created_by,
        source_git_revision=source_git_revision,
        version=int(version) if version is not None else None,
    )


def artifact_to_document(artifact: ArtifactVersion) -> dict[str, Any]:
    """Serialize an artifact version to a GitOps document (no secrets)."""
    return {
        "api_version": API_VERSION,
        "kind": KIND_BY_TYPE[artifact.type],
        "metadata": {
            "organization": artifact.organization.slug,
            "logical_id": artifact.logical_id,
            "version": artifact.version,
            "checksum": artifact.checksum,
        },
        "spec": artifact.body,
    }
