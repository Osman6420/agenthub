"""Governed transient AI candidate handling for workflow drafts."""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.core.cache import cache

from apps.audit.services import record_event
from apps.builder import services
from apps.catalog.models import AIProject
from apps.orchestration.authoring import AuthoringProviderError, get_authoring_provider
from apps.tenancy.models import Organization


def _limit(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def validate_description(value: Any) -> str:
    if not isinstance(value, str):
        raise services.BuilderError("description_invalid")
    value = value.strip()
    if not value:
        raise services.BuilderError("description_required")
    if len(value.encode("utf-8")) > _limit("AI_AUTHORING_MAX_DESCRIPTION_BYTES", 8192):
        raise services.BuilderError("description_too_large")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise services.BuilderError("description_invalid")
    return value


def _depth(value: Any, current: int = 0) -> int:
    if current > _limit("AI_AUTHORING_MAX_JSON_DEPTH", 20):
        raise services.BuilderError("candidate_too_deep")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise services.BuilderError("candidate_invalid")
            _depth(child, current + 1)
    elif isinstance(value, list):
        for child in value:
            _depth(child, current + 1)
    return current


def parse_candidate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise services.BuilderError("candidate_invalid")
    if len(raw.encode("utf-8")) > _limit("AI_AUTHORING_MAX_CANDIDATE_BYTES", 262144):
        raise services.BuilderError("candidate_too_large")
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
            if text.lstrip().lower().startswith("json\n"):
                text = text.lstrip()[5:]
    try:
        value = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise services.BuilderError("candidate_invalid_json") from exc
    if not isinstance(value, dict):
        raise services.BuilderError("candidate_not_object")
    _depth(value)
    services._validated_body(value)
    return value


def _audit(
    *,
    actor: str,
    org: Organization,
    outcome: str,
    reason: str,
    request_id: str,
    after: dict[str, Any] | None = None,
) -> None:
    record_event(
        actor_type="user",
        actor_id=actor,
        action="console.builder.ai_candidate.generate",
        outcome=outcome,
        organization_id=org.id,
        resource_type="workflow_candidate",
        resource_id=str(getattr(settings, "AI_AUTHORING_MODEL_PROFILE_ID", "")),
        reason=reason,
        request_id=request_id,
        after=after,
    )


def _consume_rate(*, actor_id: int, organization_id: int) -> None:
    limit = _limit("AI_AUTHORING_RATE_LIMIT", 5)
    window = _limit("AI_AUTHORING_RATE_WINDOW_SECONDS", 600)
    key = f"ai-authoring:{actor_id}:{organization_id}"
    try:
        if cache.add(key, 1, timeout=window):
            return
        if cache.incr(key) <= limit:
            return
    except Exception as exc:
        raise services.BuilderError("rate_limit_unavailable") from exc
    raise services.BuilderError("rate_limited")


def generate_candidate(
    *, organization: Organization, actor: str, actor_id: int, description: Any, request_id: str = ""
) -> dict[str, Any]:
    profile_id = str(getattr(settings, "AI_AUTHORING_MODEL_PROFILE_ID", "")).strip()
    if not profile_id:
        raise services.BuilderError("ai_authoring_disabled")
    description = validate_description(description)
    try:
        _consume_rate(actor_id=actor_id, organization_id=organization.id)
    except services.BuilderError as exc:
        _audit(
            actor=actor,
            org=organization,
            outcome="deny",
            reason=exc.code,
            request_id=request_id,
        )
        raise
    _audit(
        actor=actor,
        org=organization,
        outcome="success",
        reason="requested",
        request_id=request_id,
        after={"description_bytes": len(description.encode("utf-8"))},
    )
    try:
        response = get_authoring_provider().generate(profile_id=profile_id, description=description)
        candidate = parse_candidate(response.text)
        diagnostics = services.diagnose(candidate)
        _audit(
            actor=actor,
            org=organization,
            outcome="success",
            reason="succeeded",
            request_id=request_id,
            after={
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "candidate_bytes": len(response.text.encode("utf-8")),
                "valid": diagnostics["ok"],
            },
        )
        return {"candidate": candidate, "diagnostics": diagnostics}
    except AuthoringProviderError as exc:
        _audit(
            actor=actor, org=organization, outcome="failure", reason=exc.code, request_id=request_id
        )
        raise services.BuilderError(exc.code.lower()) from exc
    except services.BuilderError as exc:
        _audit(
            actor=actor, org=organization, outcome="failure", reason=exc.code, request_id=request_id
        )
        raise


def accept_candidate(
    *,
    organization: Organization,
    project: AIProject | None,
    actor: str,
    name: str,
    logical_id: str,
    candidate: Any,
    draft_id: int | None = None,
    request_id: str = "",
):
    body = parse_candidate(json.dumps(candidate, ensure_ascii=False))
    diagnostics = services.diagnose(body)
    if not diagnostics["ok"]:
        raise services.BuilderError("candidate_invalid_workflow")
    if draft_id is None:
        return services.create_draft(
            organization=organization,
            project=project,
            name=name,
            logical_id=logical_id,
            body=body,
            actor=actor,
            request_id=request_id,
        )
    draft = services.WorkflowDraft.objects.filter(pk=draft_id, organization=organization).first()
    if draft is None or (project is not None and draft.project_id != project.id):
        raise services.BuilderError("draft_not_found")
    return services.update_draft(
        draft, actor=actor, name=name or None, body=body, request_id=request_id
    )
