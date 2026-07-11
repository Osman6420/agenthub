"""Builder domain services.

These own every draft state change and its audit event, all within a transaction so an
audit-write failure fails closed with the data write. The frontend is non-authoritative:
diagnostics reuse the Sprint 8 workflow compiler verbatim, and publish reuses the Sprint 2
:func:`apps.artifacts.services.create_artifact_version` path (schema validation, inline
secret rejection, checksum, version assignment) — the builder grants no capability the
GitOps path does not.
"""

from __future__ import annotations

import json
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import ArtifactValidationError, validate_body
from apps.audit.services import record_event
from apps.builder.models import WorkflowDraft
from apps.catalog.models import AIProject
from apps.tenancy.models import Organization
from apps.workflows.compiler import compile_workflow

# Draft bodies are author working state, not production payloads; keep them bounded so a
# single draft cannot exhaust storage or the JSON parser.
MAX_DRAFT_BODY_BYTES = 256 * 1024


class BuilderError(ValueError):
    """A safe, content-free builder error carrying a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _validated_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise BuilderError("invalid_body", "draft body must be a JSON object")
    encoded = json.dumps(body, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_DRAFT_BODY_BYTES:
        raise BuilderError("body_too_large", "draft body exceeds the size limit")
    return body


@transaction.atomic
def create_draft(
    *,
    organization: Organization,
    name: str,
    logical_id: str,
    body: dict[str, Any] | None,
    actor: str,
    project: AIProject | None = None,
    request_id: str = "",
) -> WorkflowDraft:
    name = (name or "").strip()
    logical_id = (logical_id or "").strip()
    if not name:
        raise BuilderError("name_required", "draft name is required")
    if not logical_id:
        raise BuilderError("logical_id_required", "logical_id is required")
    if project is not None and project.organization_id != organization.id:
        raise BuilderError("project_mismatch", "project must belong to the organization")
    if WorkflowDraft.objects.filter(organization=organization, logical_id=logical_id).exists():
        raise BuilderError("duplicate_logical_id", "a draft with this logical_id already exists")
    draft = WorkflowDraft.objects.create(
        organization=organization,
        project=project,
        name=name,
        logical_id=logical_id,
        body=_validated_body(body or {}),
        created_by=actor,
        updated_by=actor,
    )
    _audit(actor, "create", draft, request_id=request_id)
    return draft


@transaction.atomic
def update_draft(
    draft: WorkflowDraft,
    *,
    actor: str,
    name: str | None = None,
    body: dict[str, Any] | None = None,
    request_id: str = "",
) -> WorkflowDraft:
    locked = WorkflowDraft.objects.select_for_update().get(pk=draft.pk)
    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise BuilderError("name_required", "draft name is required")
        locked.name = stripped
    if body is not None:
        locked.body = _validated_body(body)
    locked.updated_by = actor
    locked.save(update_fields=["name", "body", "updated_by", "updated_at"])
    _audit(actor, "update", locked, request_id=request_id)
    return locked


@transaction.atomic
def delete_draft(draft: WorkflowDraft, *, actor: str, request_id: str = "") -> None:
    _audit(actor, "delete", draft, request_id=request_id)
    draft.delete()


def diagnose(body: Any) -> dict[str, Any]:
    """Validate a draft body without persisting anything.

    Runs the same validation as publish — :func:`validate_body` for
    ``workflow_definition`` (inline-secret rejection *and* the workflow compiler, with no
    custom-node allowlist; the release compiler applies the org allowlist later) — and
    additionally returns the compiled checksum. Returns structured, content-free
    diagnostics so the frontend can surface them on the graph.
    """
    if not isinstance(body, dict):
        return {
            "ok": False,
            "errors": [{"code": "invalid_body", "message": "body must be an object"}],
        }
    try:
        validate_body(ArtifactType.WORKFLOW_DEFINITION, body)
    except ArtifactValidationError as exc:
        return {"ok": False, "errors": [{"code": "invalid_workflow", "message": str(exc)}]}
    return {"ok": True, "errors": [], "compiled_checksum": compile_workflow(body).checksum}


@transaction.atomic
def publish_draft(
    draft: WorkflowDraft,
    *,
    actor: str,
    source_git_revision: str = "",
    request_id: str = "",
) -> ArtifactVersion:
    """Publish the draft body as an immutable ``workflow_definition`` artifact.

    Routes through the shared, validated authoring path. Compiling/promoting a release
    from the resulting artifact remains the existing release-manager flow — the builder
    introduces no parallel lifecycle.
    """
    locked = WorkflowDraft.objects.select_for_update().get(pk=draft.pk)
    try:
        artifact = create_artifact_version(
            organization=locked.organization,
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
            logical_id=locked.logical_id,
            body=_validated_body(locked.body),
            created_by=actor,
            source_git_revision=source_git_revision,
        )
    except ArtifactValidationError as exc:
        # The shared validator rejects an invalid DSL or an inline secret; the builder
        # grants no bypass of that gate.
        raise BuilderError("publish_rejected", str(exc)) from exc

    locked.last_published_version = artifact.version
    locked.last_published_at = timezone.now()
    locked.save(update_fields=["last_published_version", "last_published_at", "updated_at"])
    record_event(
        actor_type="user",
        actor_id=actor,
        action="console.builder.draft.publish",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="workflow_definition",
        resource_id=f"{locked.logical_id}:v{artifact.version}",
        reason=artifact.checksum,
        request_id=request_id,
    )
    return artifact


def _audit(actor: str, verb: str, draft: WorkflowDraft, *, request_id: str) -> None:
    record_event(
        actor_type="user",
        actor_id=actor,
        action=f"console.builder.draft.{verb}",
        outcome="success",
        organization_id=draft.organization_id,
        resource_type="workflow_draft",
        resource_id=draft.logical_id,
        request_id=request_id,
    )
