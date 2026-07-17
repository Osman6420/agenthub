"""Governed transient AI candidates and explicit type-aware draft transfer."""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.core.cache import cache

from apps.artifacts.types import ArtifactType
from apps.audit.services import record_event
from apps.builder import services
from apps.builder.authoring_context import build_authoring_context, validate_workflow_references
from apps.catalog.models import AIProject, Scenario
from apps.orchestration.authoring import (
    AuthoringContract,
    AuthoringProviderError,
    get_authoring_contract,
    get_authoring_provider,
)
from apps.tenancy.identifiers import IdentifierAllocationError, allocate_identifier
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
    artifact_type: str = ArtifactType.WORKFLOW_DEFINITION,
    after: dict[str, Any] | None = None,
) -> None:
    record_event(
        actor_type="user",
        actor_id=actor,
        action="console.builder.ai_candidate.generate",
        outcome=outcome,
        organization_id=org.id,
        resource_type="artifact_candidate",
        resource_id=str(getattr(settings, "AI_AUTHORING_MODEL_PROFILE_ID", "")),
        reason=reason,
        request_id=request_id,
        after={"artifact_type": artifact_type, **(after or {})},
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
    *,
    organization: Organization,
    project: AIProject,
    scenario: Scenario | None,
    actor: str,
    actor_id: int,
    description: Any,
    artifact_type: Any = ArtifactType.WORKFLOW_DEFINITION,
    request_id: str = "",
) -> dict[str, Any]:
    if not isinstance(artifact_type, str):
        raise services.BuilderError("unsupported_artifact_type")
    try:
        contract = get_authoring_contract(artifact_type)
    except AuthoringProviderError as exc:
        raise services.BuilderError(exc.code.lower()) from exc
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
            artifact_type=artifact_type,
        )
        raise
    _audit(
        actor=actor,
        org=organization,
        outcome="success",
        reason="requested",
        request_id=request_id,
        artifact_type=artifact_type,
        after={
            "description_bytes": len(description.encode("utf-8")),
            "contract_id": contract.contract_id,
            "contract_revision": contract.revision,
            "contract_checksum": contract.checksum,
        },
    )
    try:
        try:
            context: dict[str, Any] = (
                build_authoring_context(project=project, scenario=scenario)
                if scenario
                else {"snapshot": {}, "checksum": "", "bytes": 0, "token_estimate": 0}
            )
        except ValueError as exc:
            raise services.BuilderError(str(exc)) from exc
        provider = get_authoring_provider()
        if scenario is None:
            response = provider.generate(
                profile_id=profile_id, description=description, contract=contract
            )
        else:
            response = provider.generate(
                profile_id=profile_id,
                description=description,
                contract=contract,
                server_context=context["snapshot"],
            )
        structured = parse_candidate(response.text)
        if artifact_type != ArtifactType.WORKFLOW_DEFINITION or scenario is None:
            candidate = structured
            diagnostics = services.diagnose_artifact(artifact_type, candidate)
            return {
                "artifact_type": artifact_type,
                "candidate": candidate,
                "diagnostics": diagnostics,
                "prompt_contract": _contract_metadata(contract),
            }
        status = structured.get("status")
        if status == "capability_missing":
            if set(structured) != {"status", "required_capability", "suggested_custom_node"}:
                raise services.BuilderError("model_response_invalid")
            suggestion = structured["suggested_custom_node"]
            required = structured["required_capability"]
            expected_suggestion = {
                "display_name",
                "purpose",
                "input_summary",
                "config_summary",
                "output_summary",
            }
            if (
                not isinstance(required, str)
                or not 1 <= len(required) <= 128
                or not isinstance(suggestion, dict)
                or set(suggestion) != expected_suggestion
                or any(
                    not isinstance(value, str) or not 1 <= len(value) <= 1000
                    for value in suggestion.values()
                )
            ):
                raise services.BuilderError("model_response_invalid")
            _audit(
                actor=actor,
                org=organization,
                outcome="success",
                reason="capability_missing",
                request_id=request_id,
                artifact_type=artifact_type,
                after={
                    "context_checksum": context["checksum"],
                    "context_bytes": context["bytes"],
                },
            )
            return {
                "status": status,
                "suggestion": suggestion,
                "required_capability": required,
                "authoring_context": {
                    "contract": context["snapshot"]["contract"],
                    "checksum": context["checksum"],
                },
            }
        if status != "workflow_candidate" or set(structured) != {"status", "candidate"}:
            raise services.BuilderError("model_response_invalid")
        workflow_candidate = structured.get("candidate")
        if not isinstance(workflow_candidate, dict):
            raise services.BuilderError("model_response_invalid")
        services._validated_body(workflow_candidate)
        try:
            validate_workflow_references(workflow_candidate, context)
        except ValueError as exc:
            raise services.BuilderError(str(exc)) from exc
        diagnostics = services.diagnose_artifact(artifact_type, workflow_candidate)
        _audit(
            actor=actor,
            org=organization,
            outcome="success",
            reason="succeeded",
            request_id=request_id,
            artifact_type=artifact_type,
            after={
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "candidate_bytes": len(response.text.encode("utf-8")),
                "valid": diagnostics["ok"],
                "context_checksum": context["checksum"],
                "context_bytes": context["bytes"],
            },
        )
        return {
            "status": "workflow_candidate",
            "artifact_type": artifact_type,
            "candidate": workflow_candidate,
            "diagnostics": diagnostics,
            "prompt_contract": _contract_metadata(contract),
            "authoring_context": {
                "contract": context["snapshot"].get("contract", ""),
                "checksum": context["checksum"],
            },
        }
    except AuthoringProviderError as exc:
        _audit(
            actor=actor,
            org=organization,
            outcome="failure",
            reason=exc.code,
            request_id=request_id,
            artifact_type=artifact_type,
        )
        raise services.BuilderError(exc.code.lower()) from exc
    except services.BuilderError as exc:
        _audit(
            actor=actor,
            org=organization,
            outcome="failure",
            reason=exc.code,
            request_id=request_id,
            artifact_type=artifact_type,
        )
        raise


def accept_candidate(
    *,
    organization: Organization,
    project: AIProject | None,
    scenario: Scenario | None = None,
    actor: str,
    name: str,
    logical_id: str,
    candidate: Any,
    artifact_type: Any = ArtifactType.WORKFLOW_DEFINITION,
    prompt_contract: Any = None,
    authoring_context: Any = None,
    draft_id: int | None = None,
    expected_revision: int | None = None,
    request_id: str = "",
):
    if not isinstance(artifact_type, str):
        raise services.BuilderError("unsupported_artifact_type")
    try:
        contract = get_authoring_contract(artifact_type)
    except AuthoringProviderError as exc:
        raise services.BuilderError(exc.code.lower()) from exc
    if artifact_type != ArtifactType.WORKFLOW_DEFINITION and prompt_contract is None:
        raise services.BuilderError("prompt_contract_required")
    if prompt_contract is not None and prompt_contract != _contract_metadata(contract):
        raise services.BuilderError("prompt_contract_mismatch")
    body = parse_candidate(json.dumps(candidate, ensure_ascii=False))
    diagnostics = services.diagnose_artifact(artifact_type, body)
    if not diagnostics["ok"]:
        code = (
            "candidate_invalid_workflow"
            if artifact_type == ArtifactType.WORKFLOW_DEFINITION
            else "candidate_invalid_artifact"
        )
        raise services.BuilderError(code)
    if artifact_type != ArtifactType.WORKFLOW_DEFINITION:
        if project is None:
            raise services.BuilderError("project_required")
        if draft_id is not None:
            raise services.BuilderError("draft_id_not_supported")
        return services.create_artifact_draft(
            organization=organization,
            project=project,
            artifact_type=artifact_type,
            name=name,
            logical_id=logical_id,
            body=body,
            actor=actor,
            request_id=request_id,
            prompt_contract=_contract_metadata(contract),
        )
    if scenario is not None and authoring_context is None:
        raise services.BuilderError("authoring_context_required")
    if draft_id is None:
        if authoring_context is not None:
            if project is None or scenario is None:
                raise services.BuilderError("scenario_required")
            live_context = build_authoring_context(project=project, scenario=scenario)
            if (
                not isinstance(authoring_context, dict)
                or authoring_context.get("checksum") != live_context["checksum"]
            ):
                raise services.BuilderError("authoring_context_stale")
            try:
                validate_workflow_references(body, live_context)
                logical_id = allocate_identifier(
                    name or scenario.name,
                    fallback="workflow",
                    max_length=128,
                    exists=lambda value: services.WorkflowDraft.objects.filter(
                        organization=organization, logical_id=value
                    ).exists(),
                )
            except ValueError as exc:
                raise services.BuilderError(str(exc)) from exc
            except IdentifierAllocationError as exc:
                raise services.BuilderError("identifier_allocation_exhausted") from exc
        return services.create_draft(
            organization=organization,
            project=project,
            scenario=scenario,
            name=name,
            logical_id=logical_id,
            body=body,
            actor=actor,
            request_id=request_id,
        )
    draft = services.WorkflowDraft.objects.filter(pk=draft_id, organization=organization).first()
    if draft is None or (project is not None and draft.project_id != project.id):
        raise services.BuilderError("draft_not_found")
    if scenario is None or draft.scenario_id != scenario.id:
        raise services.BuilderError("scenario_mismatch")
    if project is None:
        raise services.BuilderError("project_required")
    live_context = build_authoring_context(project=project, scenario=scenario)
    if authoring_context is not None and (
        not isinstance(authoring_context, dict)
        or authoring_context.get("checksum") != live_context["checksum"]
    ):
        raise services.BuilderError("authoring_context_stale")
    try:
        validate_workflow_references(body, live_context)
    except ValueError as exc:
        raise services.BuilderError(str(exc)) from exc
    return services.update_draft(
        draft,
        actor=actor,
        expected_revision=expected_revision,
        name=name or None,
        body=body,
        request_id=request_id,
    )


def _contract_metadata(contract: AuthoringContract) -> dict[str, Any]:
    return {
        "id": contract.contract_id,
        "revision": contract.revision,
        "checksum": contract.checksum,
    }
