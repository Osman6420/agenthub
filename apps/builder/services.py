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
import re
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import ArtifactValidationError, compute_checksum, validate_body
from apps.audit.services import record_event
from apps.builder.models import ArtifactDraft, WorkflowDraft
from apps.catalog.models import AIProject, Scenario
from apps.tenancy.models import Organization
from apps.workflows.compiler import compile_workflow

# Draft bodies are author working state, not production payloads; keep them bounded so a
# single draft cannot exhaust storage or the JSON parser.
MAX_DRAFT_BODY_BYTES = 256 * 1024
_ARTIFACT_LOGICAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
AUTHORABLE_ARTIFACT_TYPES = frozenset(
    {
        ArtifactType.INPUT_CONTRACT,
        ArtifactType.OUTPUT_CONTRACT,
        ArtifactType.PROMPT_TEMPLATE,
        ArtifactType.CHUNKING_PROFILE,
        ArtifactType.RETRIEVAL_PROFILE,
    }
)


def ai_authoring_request_limit(*, accept: bool) -> int:
    """Bound request bytes before JSON decoding; includes envelope overhead."""
    from django.conf import settings

    setting_name = (
        "AI_AUTHORING_MAX_CANDIDATE_BYTES" if accept else "AI_AUTHORING_MAX_DESCRIPTION_BYTES"
    )
    default = MAX_DRAFT_BODY_BYTES if accept else 8192
    return int(getattr(settings, setting_name, default)) + 16 * 1024


class BuilderError(ValueError):
    """A safe, content-free builder error carrying a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _require_revision(*, expected: Any, actual: int) -> None:
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
        raise BuilderError("revision_required")
    if expected != actual:
        raise BuilderError("stale_revision")


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
    logical_description: str = "",
    body: dict[str, Any] | None,
    actor: str,
    project: AIProject | None = None,
    scenario: Scenario | None = None,
    request_id: str = "",
) -> WorkflowDraft:
    name = (name or "").strip()
    logical_id = (logical_id or "").strip()
    logical_description = " ".join((logical_description or "").split())
    if not name:
        raise BuilderError("name_required", "draft name is required")
    if not logical_id:
        raise BuilderError("logical_id_required", "logical_id is required")
    if not logical_description:
        logical_description = f"{name} workflow"
    if len(logical_description) > 1000:
        raise BuilderError("logical_description_too_large")
    if project is not None and project.organization_id != organization.id:
        raise BuilderError("project_mismatch", "project must belong to the organization")
    if scenario is not None:
        if scenario.organization_id != organization.id:
            raise BuilderError("scenario_mismatch")
        if project is None or scenario.project_id != project.id:
            raise BuilderError("scenario_project_mismatch")
    if WorkflowDraft.objects.filter(organization=organization, logical_id=logical_id).exists():
        raise BuilderError("duplicate_logical_id", "a draft with this logical_id already exists")
    candidate = _validated_body(body or {})
    if candidate and not diagnose(candidate)["ok"]:
        raise BuilderError("candidate_invalid_workflow")
    draft = WorkflowDraft.objects.create(
        organization=organization,
        project=project,
        scenario=scenario,
        name=name,
        logical_id=logical_id,
        logical_description=logical_description,
        body=candidate,
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
    expected_revision: Any,
    name: str | None = None,
    logical_description: str | None = None,
    body: dict[str, Any] | None = None,
    request_id: str = "",
) -> WorkflowDraft:
    locked = WorkflowDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise BuilderError("name_required", "draft name is required")
        locked.name = stripped
    if body is not None:
        locked.body = _validated_body(body)
    if logical_description is not None:
        normalized_description = " ".join(logical_description.split())
        if not normalized_description:
            raise BuilderError("logical_description_required")
        if len(normalized_description) > 1000:
            raise BuilderError("logical_description_too_large")
        if locked.last_published_version and normalized_description != locked.logical_description:
            raise BuilderError("logical_description_immutable_after_publish")
        locked.logical_description = normalized_description
    locked.updated_by = actor
    locked.revision += 1
    locked.save(
        update_fields=[
            "name",
            "logical_description",
            "body",
            "updated_by",
            "revision",
            "updated_at",
        ]
    )
    _audit(actor, "update", locked, request_id=request_id)
    return locked


@transaction.atomic
def delete_draft(
    draft: WorkflowDraft, *, actor: str, expected_revision: Any, request_id: str = ""
) -> None:
    locked = WorkflowDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    _audit(actor, "delete", locked, request_id=request_id)
    locked.delete()


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


def diagnose_artifact(artifact_type: str, body: Any) -> dict[str, Any]:
    """Run the canonical validator for an allowlisted AI candidate type."""
    if artifact_type == ArtifactType.WORKFLOW_DEFINITION:
        return diagnose(body)
    if artifact_type not in AUTHORABLE_ARTIFACT_TYPES:
        raise BuilderError("unsupported_artifact_type")
    if not isinstance(body, dict):
        return {
            "ok": False,
            "errors": [{"code": "invalid_body", "message": "body must be an object"}],
        }
    try:
        validate_body(artifact_type, body)
    except ArtifactValidationError as exc:
        return {"ok": False, "errors": [{"code": "invalid_artifact", "message": str(exc)}]}
    return {"ok": True, "errors": [], "compiled_checksum": compute_checksum(body)}


@transaction.atomic
def create_artifact_draft(
    *,
    organization: Organization,
    project: AIProject,
    scenario: Scenario,
    artifact_type: str,
    name: str,
    logical_id: str,
    logical_description: str = "",
    body: Any,
    actor: str,
    request_id: str = "",
    prompt_contract: dict[str, Any] | None = None,
) -> ArtifactDraft:
    """Persist validated non-workflow author state without publishing an artifact."""
    if artifact_type not in AUTHORABLE_ARTIFACT_TYPES:
        raise BuilderError("unsupported_artifact_type")
    if project.organization_id != organization.id:
        raise BuilderError("project_mismatch")
    if scenario.organization_id != organization.id or scenario.project_id != project.id:
        raise BuilderError("scenario_mismatch")
    name = (name or "").strip()
    logical_id = (logical_id or "").strip()
    logical_description = " ".join((logical_description or "").split())
    if not name:
        raise BuilderError("name_required")
    if len(name) > 200:
        raise BuilderError("name_too_large")
    if not logical_id:
        raise BuilderError("logical_id_required")
    if len(logical_id) > 128:
        raise BuilderError("logical_id_too_large")
    if not _ARTIFACT_LOGICAL_ID.fullmatch(logical_id):
        raise BuilderError("logical_id_invalid")
    if not logical_description:
        logical_description = f"{name} {artifact_type}"
    if len(logical_description) > 1000:
        raise BuilderError("logical_description_too_large")
    existing_description = (
        ArtifactVersion.objects.filter(
            organization=organization,
            type=artifact_type,
            logical_id=logical_id,
        )
        .order_by("-version")
        .values_list("logical_description", flat=True)
        .first()
    )
    if existing_description and logical_description != existing_description:
        raise BuilderError("logical_description_mismatch")
    safe_prompt_contract = _safe_prompt_contract_metadata(prompt_contract)
    diagnostics = diagnose_artifact(artifact_type, _validated_body(body))
    if not diagnostics["ok"]:
        raise BuilderError("candidate_invalid_artifact")
    if ArtifactDraft.objects.filter(
        organization=organization, artifact_type=artifact_type, logical_id=logical_id
    ).exists():
        raise BuilderError("duplicate_logical_id")
    draft = ArtifactDraft.objects.create(
        organization=organization,
        project=project,
        scenario=scenario,
        artifact_type=artifact_type,
        name=name,
        logical_id=logical_id,
        logical_description=logical_description,
        body=body,
        created_by=actor,
        updated_by=actor,
    )
    record_event(
        actor_type="user",
        actor_id=actor,
        action="console.builder.artifact_draft.create",
        outcome="success",
        organization_id=organization.id,
        resource_type="artifact_draft",
        resource_id=f"{artifact_type}:{logical_id}",
        reason="ai_candidate_accepted",
        request_id=request_id,
        after={"prompt_contract": safe_prompt_contract} if safe_prompt_contract else None,
    )
    return draft


def _safe_prompt_contract_metadata(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if set(value) != {"id", "revision", "checksum"}:
        raise BuilderError("prompt_contract_invalid")
    contract_id = value.get("id")
    revision = value.get("revision")
    checksum = value.get("checksum")
    if (
        not isinstance(contract_id, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,99}", contract_id)
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or not isinstance(checksum, str)
        or not re.fullmatch(r"[0-9a-f]{64}", checksum)
    ):
        raise BuilderError("prompt_contract_invalid")
    return {"id": contract_id, "revision": revision, "checksum": checksum}


@transaction.atomic
def update_artifact_draft(
    draft: ArtifactDraft,
    *,
    actor: str,
    expected_revision: Any,
    name: str | None = None,
    body: dict[str, Any] | None = None,
    request_id: str = "",
) -> ArtifactDraft:
    locked = ArtifactDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise BuilderError("name_required")
        if len(stripped) > 200:
            raise BuilderError("name_too_large")
        locked.name = stripped
    if body is not None:
        candidate = _validated_body(body)
        diagnostics = diagnose_artifact(locked.artifact_type, candidate)
        if not diagnostics["ok"]:
            raise BuilderError("candidate_invalid_artifact")
        locked.body = candidate
    locked.updated_by = actor
    locked.revision += 1
    locked.save(update_fields=["name", "body", "updated_by", "revision", "updated_at"])
    _audit_artifact_draft(actor, "update", locked, request_id=request_id)
    return locked


@transaction.atomic
def delete_artifact_draft(
    draft: ArtifactDraft, *, actor: str, expected_revision: Any, request_id: str = ""
) -> None:
    locked = ArtifactDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    _audit_artifact_draft(actor, "delete", locked, request_id=request_id)
    locked.delete()


def _audit_artifact_draft(actor: str, verb: str, draft: ArtifactDraft, *, request_id: str) -> None:
    record_event(
        actor_type="user",
        actor_id=actor,
        action=f"console.builder.artifact_draft.{verb}",
        outcome="success",
        organization_id=draft.organization_id,
        resource_type="artifact_draft",
        resource_id=f"{draft.artifact_type}:{draft.logical_id}",
        request_id=request_id,
    )


@transaction.atomic
def publish_artifact_draft(
    draft: ArtifactDraft,
    *,
    actor: str,
    expected_revision: Any,
    version_description: str,
    request_id: str = "",
) -> ArtifactVersion:
    """Publish mutable governed artifact author state as a new immutable exact version."""

    locked = ArtifactDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    version_description = " ".join((version_description or "").split())
    if not version_description:
        raise BuilderError("version_description_required")
    if len(version_description) > 1000:
        raise BuilderError("version_description_too_large")
    try:
        artifact = create_artifact_version(
            organization=locked.organization,
            artifact_type=locked.artifact_type,
            logical_id=locked.logical_id,
            logical_description=locked.logical_description,
            version_description=version_description,
            body=_validated_body(locked.body),
            created_by=actor,
        )
    except (ArtifactValidationError, ValueError) as exc:
        raise BuilderError("publish_rejected", str(exc)) from exc
    locked.last_published_version = artifact.version
    locked.last_published_at = timezone.now()
    locked.revision += 1
    locked.save(
        update_fields=["last_published_version", "last_published_at", "revision", "updated_at"]
    )
    record_event(
        actor_type="user",
        actor_id=actor,
        action="console.builder.artifact_draft.publish",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type=locked.artifact_type,
        resource_id=f"{locked.logical_id}:v{artifact.version}",
        reason=artifact.checksum,
        request_id=request_id,
    )
    return artifact


@transaction.atomic
def publish_draft(
    draft: WorkflowDraft,
    *,
    actor: str,
    expected_revision: Any,
    version_description: str = "",
    source_git_revision: str = "",
    request_id: str = "",
) -> ArtifactVersion:
    """Publish the draft body as an immutable ``workflow_definition`` artifact.

    Routes through the shared, validated authoring path. Compiling/promoting a release
    from the resulting artifact remains the existing release-manager flow — the builder
    introduces no parallel lifecycle.
    """
    locked = WorkflowDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    version_description = " ".join((version_description or "").split())
    if not version_description:
        raise BuilderError("version_description_required")
    if len(version_description) > 1000:
        raise BuilderError("version_description_too_large")
    try:
        artifact = create_artifact_version(
            organization=locked.organization,
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
            logical_id=locked.logical_id,
            logical_description=locked.logical_description,
            version_description=version_description,
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
    locked.revision += 1
    locked.save(
        update_fields=["last_published_version", "last_published_at", "revision", "updated_at"]
    )
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
