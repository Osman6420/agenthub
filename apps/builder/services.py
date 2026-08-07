"""Builder domain services.

These own every draft state change and its audit event, all within a transaction so an
audit-write failure fails closed with the data write. The frontend is non-authoritative:
diagnostics reuse the Sprint 8 workflow compiler verbatim, and publish reuses the Sprint 2
:func:`apps.artifacts.services.create_artifact_version` path (schema validation, inline
secret rejection, checksum, version assignment) — the builder grants no capability the
GitOps path does not.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
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
from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.tenancy.models import Organization
from apps.workflows.compiler import compile_workflow

# Draft bodies are author working state, not production payloads; keep them bounded so a
# single draft cannot exhaust storage or the JSON parser.
MAX_DRAFT_BODY_BYTES = 256 * 1024
_ARTIFACT_LOGICAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
# Chunking is owned by the document set, not the scenario: it is consumed only by
# ``apps.ingestion`` staged preparation and is authored from the document-set page. Studio must
# not offer a second, scenario-scoped way to write it.
DOCUMENT_SET_OWNED_ARTIFACT_TYPES = frozenset({ArtifactType.CHUNKING_PROFILE})
AUTHORABLE_ARTIFACT_TYPES = frozenset(
    {
        ArtifactType.INPUT_CONTRACT,
        ArtifactType.OUTPUT_CONTRACT,
        ArtifactType.PROMPT_TEMPLATE,
        ArtifactType.MODEL_PROFILE,
        ArtifactType.RETRIEVAL_PROFILE,
    }
)

_GENERATE_ROLE_PREFIX = "gen_"
_RETRIEVE_ROLE_PREFIX = "ret_"


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


def generate_node_roles(draft: WorkflowDraft, node_id: str) -> dict[str, str]:
    """Return stable, server-owned manifest roles for one Generate node."""

    if not isinstance(node_id, str) or not node_id:
        raise BuilderError("generate_node_invalid")
    seed = f"{draft.organization_id}:{draft.logical_id}:{node_id}".encode()
    identity = hashlib.sha256(seed).hexdigest()[:24]
    return {
        "prompt_ref": f"{_GENERATE_ROLE_PREFIX}{identity}_prompt",
        "model_profile_ref": f"{_GENERATE_ROLE_PREFIX}{identity}_model",
    }


def retrieve_node_role(draft: WorkflowDraft, node_id: str) -> str:
    """Return the stable, server-owned retrieval manifest role for one Retrieve node."""

    if not isinstance(node_id, str) or not node_id:
        raise BuilderError("retrieve_node_invalid")
    seed = f"{draft.organization_id}:{draft.logical_id}:{node_id}".encode()
    identity = hashlib.sha256(seed).hexdigest()[:24]
    return f"{_RETRIEVE_ROLE_PREFIX}{identity}_profile"


def _workflow_node(body: dict[str, Any], node_id: str, *, node_type: str) -> dict[str, Any]:
    spec = body.get("spec")
    nodes = spec.get("nodes") if isinstance(spec, dict) else None
    if not isinstance(nodes, list):
        raise BuilderError(f"{node_type}_node_not_found")
    matches = [node for node in nodes if isinstance(node, dict) and node.get("id") == node_id]
    if len(matches) != 1 or matches[0].get("type") != node_type:
        raise BuilderError(f"{node_type}_node_not_found")
    return matches[0]


def _require_generate_role_unique(
    draft: WorkflowDraft,
    body: dict[str, Any],
    *,
    node_id: str,
    roles: dict[str, str],
) -> None:
    spec = body.get("spec")
    nodes = spec.get("nodes", []) if isinstance(spec, dict) else []
    selected_roles = set(roles.values())
    for candidate in nodes:
        if not isinstance(candidate, dict) or candidate.get("type") != "generate":
            continue
        other_id = candidate.get("id")
        if not isinstance(other_id, str) or other_id == node_id:
            continue
        if selected_roles.intersection(generate_node_roles(draft, other_id).values()):
            raise BuilderError("generate_binding_collision")


def _binding_artifact_body(
    draft: WorkflowDraft, *, artifact_type: str, configured_role: Any, expected_role: str
) -> dict[str, Any] | None:
    role = (
        configured_role if isinstance(configured_role, str) and configured_role else expected_role
    )
    author_draft = ArtifactDraft.objects.filter(
        organization=draft.organization,
        scenario=draft.scenario,
        artifact_type=artifact_type,
        logical_id=role,
    ).first()
    if author_draft is not None:
        return author_draft.body
    return (
        ArtifactVersion.objects.filter(
            organization=draft.organization,
            type=artifact_type,
            logical_id=role,
        )
        .order_by("-version")
        .values_list("body", flat=True)
        .first()
    )


def get_generate_node_binding(draft: WorkflowDraft, *, node_id: str) -> dict[str, Any]:
    body = _validated_body(draft.body)
    node = _workflow_node(body, node_id, node_type="generate")
    raw_config = node.get("config")
    config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
    roles = generate_node_roles(draft, node_id)
    prompt_body = _binding_artifact_body(
        draft,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        configured_role=config.get("prompt_ref"),
        expected_role=roles["prompt_ref"],
    )
    model_body = _binding_artifact_body(
        draft,
        artifact_type=ArtifactType.MODEL_PROFILE,
        configured_role=config.get("model_profile_ref"),
        expected_role=roles["model_profile_ref"],
    )
    prompt_values: dict[str, Any] = prompt_body if isinstance(prompt_body, dict) else {}
    model_values: dict[str, Any] = model_body if isinstance(model_body, dict) else {}
    return {
        "node_id": node_id,
        "prompt_text": prompt_values.get("template", ""),
        "model_profile_id": model_values.get("profile_id", ""),
        "configured": config.get("prompt_ref") == roles["prompt_ref"]
        and config.get("model_profile_ref") == roles["model_profile_ref"],
    }


def _upsert_node_artifact_draft(
    *,
    workflow: WorkflowDraft,
    artifact_type: str,
    logical_id: str,
    name: str,
    body: dict[str, Any],
    actor: str,
    request_id: str,
) -> ArtifactDraft:
    existing = (
        ArtifactDraft.objects.select_for_update()
        .filter(
            organization=workflow.organization,
            artifact_type=artifact_type,
            logical_id=logical_id,
        )
        .first()
    )
    if existing is not None:
        if (
            existing.project_id != workflow.project_id
            or existing.scenario_id != workflow.scenario_id
        ):
            raise BuilderError("node_binding_collision")
        return update_artifact_draft(
            existing,
            actor=actor,
            expected_revision=existing.revision,
            name=name,
            body=body,
            request_id=request_id,
        )
    if workflow.project is None or workflow.scenario is None:
        raise BuilderError("scenario_required")
    return create_artifact_draft(
        organization=workflow.organization,
        project=workflow.project,
        scenario=workflow.scenario,
        artifact_type=artifact_type,
        name=name,
        logical_id=logical_id,
        logical_description=f"Generate node {workflow.logical_id}/{name}",
        body=body,
        actor=actor,
        request_id=request_id,
    )


@transaction.atomic
def save_generate_node_binding(
    draft: WorkflowDraft,
    *,
    actor: str,
    expected_revision: Any,
    workflow_body: Any,
    node_id: str,
    prompt_text: Any,
    model_profile_id: Any,
    request_id: str = "",
) -> WorkflowDraft:
    """Save one Generate node and its governed prompt/model author state atomically."""

    # Lock only the workflow row. ``project`` and ``scenario`` are nullable, so joining
    # them here creates nullable-side outer joins that PostgreSQL refuses to lock.
    locked = WorkflowDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise BuilderError("prompt_text_required")
    if not isinstance(model_profile_id, str):
        raise BuilderError("model_profile_invalid")
    try:
        from uuid import UUID

        UUID(model_profile_id)
    except (TypeError, ValueError) as exc:
        raise BuilderError("model_profile_invalid") from exc

    candidate = copy.deepcopy(_validated_body(workflow_body))
    node = _workflow_node(candidate, node_id, node_type="generate")
    roles = generate_node_roles(locked, node_id)
    _require_generate_role_unique(locked, candidate, node_id=node_id, roles=roles)
    raw_config = node.get("config")
    config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
    node["config"] = {**config, **roles}

    safe_node_name = node_id[:80]
    _upsert_node_artifact_draft(
        workflow=locked,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        logical_id=roles["prompt_ref"],
        name=f"{safe_node_name} prompt",
        body={"template": prompt_text},
        actor=actor,
        request_id=request_id,
    )
    _upsert_node_artifact_draft(
        workflow=locked,
        artifact_type=ArtifactType.MODEL_PROFILE,
        logical_id=roles["model_profile_ref"],
        name=f"{safe_node_name} model",
        body={"profile_id": model_profile_id},
        actor=actor,
        request_id=request_id,
    )
    return update_draft(
        locked,
        actor=actor,
        expected_revision=locked.revision,
        body=candidate,
        request_id=request_id,
    )


def get_retrieve_node_binding(draft: WorkflowDraft, *, node_id: str) -> dict[str, Any]:
    body = _validated_body(draft.body)
    node = _workflow_node(body, node_id, node_type="retrieve")
    raw_config = node.get("config")
    config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
    expected_role = retrieve_node_role(draft, node_id)
    configured_role = config.get("retrieval_profile_ref")
    profile_body = _binding_artifact_body(
        draft,
        artifact_type=ArtifactType.RETRIEVAL_PROFILE,
        configured_role=configured_role,
        expected_role=expected_role,
    )
    scenario = draft.scenario
    if profile_body is None and not configured_role and scenario is not None:
        from apps.releases.services import get_active_release, get_artifact_body_for_role

        active_release = get_active_release(scenario)
        if active_release is not None:
            profile_body = get_artifact_body_for_role(active_release, "retrieval_profile")
    if not isinstance(profile_body, dict):
        profile_body = {
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "hybrid",
            "top_k": 8,
            "score_threshold": 0,
            "vector_weight": 0.7,
            "keyword_weight": 0.3,
        }
    return {
        "node_id": node_id,
        "profile_body": profile_body,
        "configured": configured_role == expected_role,
    }


@transaction.atomic
def save_retrieve_node_binding(
    draft: WorkflowDraft,
    *,
    actor: str,
    expected_revision: Any,
    workflow_body: Any,
    node_id: str,
    profile_body: Any,
    request_id: str = "",
) -> WorkflowDraft:
    """Save one Retrieve node and its governed retrieval profile atomically."""

    locked = WorkflowDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    candidate = copy.deepcopy(_validated_body(workflow_body))
    node = _workflow_node(candidate, node_id, node_type="retrieve")
    role = retrieve_node_role(locked, node_id)
    spec = candidate.get("spec")
    nodes = spec.get("nodes", []) if isinstance(spec, dict) else []
    for other in nodes:
        if not isinstance(other, dict) or other.get("type") != "retrieve":
            continue
        other_id = other.get("id")
        if isinstance(other_id, str) and other_id != node_id:
            if retrieve_node_role(locked, other_id) == role:
                raise BuilderError("node_binding_collision")
    raw_config = node.get("config")
    config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
    node["config"] = {**config, "retrieval_profile_ref": role}

    _upsert_node_artifact_draft(
        workflow=locked,
        artifact_type=ArtifactType.RETRIEVAL_PROFILE,
        logical_id=role,
        name=f"{node_id[:80]} retrieval",
        body=_validated_body(profile_body),
        actor=actor,
        request_id=request_id,
    )
    return update_draft(
        locked,
        actor=actor,
        expected_revision=locked.revision,
        body=candidate,
        request_id=request_id,
    )


def _require_active_model_profile(artifact_type: str, body: dict[str, Any]) -> None:
    if artifact_type != ArtifactType.MODEL_PROFILE:
        return
    profile_id = body.get("profile_id")
    if not isinstance(profile_id, str):
        raise BuilderError("candidate_invalid_artifact")
    if not ModelProfile.objects.filter(
        public_id=profile_id,
        status=ModelProfileStatus.ACTIVE,
    ).exists():
        raise BuilderError("model_profile_unavailable")


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


def node_owned_role_ids(draft: WorkflowDraft) -> set[str]:
    """Return every server-owned artifact role this workflow's nodes generate."""

    body = draft.body if isinstance(draft.body, dict) else {}
    spec = body.get("spec")
    nodes = spec.get("nodes", []) if isinstance(spec, dict) else []
    roles: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            continue
        if node.get("type") == "generate":
            roles.update(generate_node_roles(draft, node_id).values())
        elif node.get("type") == "retrieve":
            roles.add(retrieve_node_role(draft, node_id))
    return roles


@transaction.atomic
def delete_draft(
    draft: WorkflowDraft, *, actor: str, expected_revision: Any, request_id: str = ""
) -> None:
    locked = WorkflowDraft.objects.select_for_update().get(pk=draft.pk)
    _require_revision(expected=expected_revision, actual=locked.revision)
    # Node-owned artifact drafts exist only to back this workflow's nodes, so deleting the
    # workflow must not leave them orphaned and unreachable. Published immutable versions are
    # never touched, and an author's own logical artifacts keep their own lifecycle.
    roles = node_owned_role_ids(locked)
    if roles and locked.project_id is not None and locked.scenario_id is not None:
        orphans = list(
            ArtifactDraft.objects.select_for_update().filter(
                organization_id=locked.organization_id,
                project_id=locked.project_id,
                scenario_id=locked.scenario_id,
                logical_id__in=roles,
            )
        )
        for orphan in orphans:
            _audit_artifact_draft(actor, "delete", orphan, request_id=request_id)
            orphan.delete()
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
    _require_active_model_profile(artifact_type, body)
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
        _require_active_model_profile(locked.artifact_type, candidate)
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
    body = _validated_body(locked.body)
    try:
        validate_body(locked.artifact_type, body)
    except ArtifactValidationError as exc:
        raise BuilderError("publish_rejected", str(exc)) from exc
    _require_active_model_profile(locked.artifact_type, body)
    try:
        artifact = create_artifact_version(
            organization=locked.organization,
            artifact_type=locked.artifact_type,
            logical_id=locked.logical_id,
            logical_description=locked.logical_description,
            version_description=version_description,
            body=body,
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


def _publish_node_artifact_if_changed(
    *,
    workflow: WorkflowDraft,
    node_id: str,
    artifact_type: str,
    logical_id: str,
    actor: str,
    version_description: str,
    request_id: str,
) -> ArtifactVersion:
    author_draft = (
        ArtifactDraft.objects.select_for_update()
        .filter(
            organization=workflow.organization,
            project=workflow.project,
            scenario=workflow.scenario,
            artifact_type=artifact_type,
            logical_id=logical_id,
        )
        .first()
    )
    if author_draft is None:
        raise BuilderError("node_binding_missing", f"node {node_id} binding is missing")
    body = _validated_body(author_draft.body)
    try:
        validate_body(artifact_type, body)
    except ArtifactValidationError as exc:
        raise BuilderError("publish_rejected", str(exc)) from exc
    _require_active_model_profile(artifact_type, body)
    checksum = compute_checksum(body)
    latest = (
        ArtifactVersion.objects.filter(
            organization=workflow.organization,
            type=artifact_type,
            logical_id=logical_id,
        )
        .order_by("-version")
        .first()
    )
    if latest is not None and latest.checksum == checksum:
        return latest
    artifact = create_artifact_version(
        organization=workflow.organization,
        artifact_type=artifact_type,
        logical_id=logical_id,
        logical_description=author_draft.logical_description,
        version_description=version_description,
        body=body,
        created_by=actor,
    )
    author_draft.last_published_version = artifact.version
    author_draft.last_published_at = timezone.now()
    author_draft.revision += 1
    author_draft.save(
        update_fields=["last_published_version", "last_published_at", "revision", "updated_at"]
    )
    record_event(
        actor_type="user",
        actor_id=actor,
        action="console.builder.node_binding.publish",
        outcome="success",
        organization_id=workflow.organization_id,
        resource_type=artifact_type,
        resource_id=f"{logical_id}:v{artifact.version}",
        reason=artifact.checksum,
        request_id=request_id,
    )
    return artifact


def _publish_generate_bindings(
    workflow: WorkflowDraft,
    *,
    actor: str,
    version_description: str,
    request_id: str,
) -> None:
    body = _validated_body(workflow.body)
    spec = body.get("spec")
    nodes = spec.get("nodes", []) if isinstance(spec, dict) else []
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "generate":
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        roles = generate_node_roles(workflow, node_id)
        raw_config = node.get("config")
        config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
        for field, artifact_type in (
            ("prompt_ref", ArtifactType.PROMPT_TEMPLATE),
            ("model_profile_ref", ArtifactType.MODEL_PROFILE),
        ):
            if config.get(field) != roles[field]:
                continue  # Legacy/custom roles remain release-manager pinned and untouched.
            _publish_node_artifact_if_changed(
                workflow=workflow,
                node_id=node_id,
                artifact_type=artifact_type,
                logical_id=roles[field],
                actor=actor,
                version_description=version_description,
                request_id=request_id,
            )


def _publish_retrieve_bindings(
    workflow: WorkflowDraft,
    *,
    actor: str,
    version_description: str,
    request_id: str,
) -> None:
    body = _validated_body(workflow.body)
    spec = body.get("spec")
    nodes = spec.get("nodes", []) if isinstance(spec, dict) else []
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "retrieve":
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        role = retrieve_node_role(workflow, node_id)
        raw_config = node.get("config")
        config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
        if config.get("retrieval_profile_ref") != role:
            continue  # Legacy nodes retain release-level fallback or custom exact pins.
        _publish_node_artifact_if_changed(
            workflow=workflow,
            node_id=node_id,
            artifact_type=ArtifactType.RETRIEVAL_PROFILE,
            logical_id=role,
            actor=actor,
            version_description=version_description,
            request_id=request_id,
        )


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
    _publish_generate_bindings(
        locked,
        actor=actor,
        version_description=version_description,
        request_id=request_id,
    )
    _publish_retrieve_bindings(
        locked,
        actor=actor,
        version_description=version_description,
        request_id=request_id,
    )
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


@dataclass(frozen=True)
class PublishAndVerifyResult:
    """Outcome of one operator action: publish, derive, compile, evaluate.

    ``missing`` names what the scenario still needs in author language; ``diagnostics``
    carries a canonical compiler rejection. Both are empty on success. The draft is always
    published — only candidate creation and evaluation are withheld.
    """

    published: ArtifactVersion
    draft_revision: int
    missing: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    release: Any | None = None
    eval_run: Any | None = None

    @property
    def ok(self) -> bool:
        return not self.missing and not self.diagnostics and self.release is not None


def publish_and_verify(
    draft: WorkflowDraft,
    *,
    actor: str,
    expected_revision: Any,
    version_description: str = "",
    request_id: str = "",
    trace_id: str = "",
) -> PublishAndVerifyResult:
    """Take a draft all the way to an evaluated candidate in one operator action.

    Both the Studio API and the scenario console page call this, so the sequence, its audit
    trail and its failure semantics cannot drift between the two surfaces. Authorization is
    the caller's responsibility: this is candidate preparation, which an exact Scenario
    Editor may perform, and it never promotes or changes live traffic.
    """

    from apps.evaluations.services import EvalError, run_eval
    from apps.releases import authoring as release_authoring
    from apps.releases.compiler import CompileError, compile_release

    scenario = draft.scenario
    if scenario is None:
        raise BuilderError("draft_not_bound_to_scenario")

    artifact = publish_draft(
        draft,
        actor=actor,
        expected_revision=expected_revision,
        version_description=version_description,
        request_id=request_id,
    )
    draft.refresh_from_db(fields=["revision"])

    derived = release_authoring.derive_manifest(scenario=scenario, workflow_artifact=artifact)
    if not derived.ok:
        return PublishAndVerifyResult(
            published=artifact,
            draft_revision=draft.revision,
            missing=derived.missing,
            diagnostics=[],
        )

    try:
        with transaction.atomic():
            release = compile_release(
                scenario=scenario,
                refs=derived.refs,
                runtime_version=release_authoring.candidate_runtime_version(scenario),
                created_by=actor,
            )
            record_event(
                actor_type="user",
                actor_id=actor,
                action="console.scenario.release.compile",
                outcome="success",
                organization_id=scenario.organization_id,
                resource_type="scenario_release",
                resource_id=str(release.pk),
                reason=release.artifact_manifest_sha256,
                request_id=request_id,
                trace_id=trace_id,
            )
    except CompileError as exc:
        record_event(
            actor_type="user",
            actor_id=actor,
            action="console.scenario.release.compile",
            outcome="failure",
            organization_id=scenario.organization_id,
            resource_type="scenario",
            resource_id=str(scenario.pk),
            reason=exc.code,
            request_id=request_id,
            trace_id=trace_id,
        )
        return PublishAndVerifyResult(
            published=artifact,
            draft_revision=draft.revision,
            missing=[],
            diagnostics=[exc.as_diagnostic()],
        )

    try:
        eval_run = run_eval(release=release, created_by=actor)
    except EvalError as exc:
        return PublishAndVerifyResult(
            published=artifact,
            draft_revision=draft.revision,
            missing=[],
            diagnostics=[{"code": exc.code, "message": f"Eval başlatılamadı: {exc.code}"}],
            release=release,
        )
    return PublishAndVerifyResult(
        published=artifact,
        draft_revision=draft.revision,
        missing=[],
        diagnostics=[],
        release=release,
        eval_run=eval_run,
    )
