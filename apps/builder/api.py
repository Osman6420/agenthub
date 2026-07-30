"""Operator JSON API for the visual workflow builder (session/LDAP authenticated).

This is an *operator* surface: it reuses the console's Django authentication (LDAP in
production per ADR-0001, or the model backend when LDAP is disabled) and the Sprint 1
tenant/role authorization helpers. It is **not** the public consumer gateway — there is no
bearer-token path, no CORS, and CSRF applies to every mutating method. The frontend is
non-authoritative: it renders backend state and diagnostics; every decision is re-made
here on the server.

Authorization:
- read (list/retrieve/diagnostics/node-schema) is membership-scoped
  (:func:`allowed_organization_ids`);
- create/update/delete/publish require ``can_author_scenarios`` in the target organization.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import wraps
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from apps.audit.services import record_event
from apps.builder import authoring, services
from apps.builder.models import ArtifactDraft, WorkflowDraft
from apps.builder.node_schema import build_node_schema
from apps.catalog.models import AIProject, Scenario
from apps.identity.authorization import Capability, authorize
from apps.releases import authoring as release_authoring
from apps.releases.compiler import CompileError, compile_release
from apps.tenancy.models import Organization
from apps.tenancy.services import allowed_organization_ids, can_author_scenarios


def operator_api(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Require an authenticated operator and translate errors to JSON envelopes.

    Unlike ``login_required`` this returns a 401 JSON body (not an HTML redirect) so the
    SPA can react, and it maps the builder's typed errors to stable status codes.
    """

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return JsonResponse({"error": {"code": "authentication_required"}}, status=401)
        try:
            return view(request, *args, **kwargs)
        except services.BuilderError as exc:
            status = 409 if exc.code == "stale_revision" else 400
            return JsonResponse({"error": {"code": exc.code, "message": str(exc)}}, status=status)
        except PermissionDenied:
            return JsonResponse({"error": {"code": "forbidden"}}, status=403)
        except Http404:
            return JsonResponse({"error": {"code": "not_found"}}, status=404)

    return wrapper


def _request_id(request: HttpRequest) -> str:
    return str(getattr(request, "request_id", ""))[:64]


def _trace_id(request: HttpRequest) -> str:
    return str(getattr(request, "trace_id", ""))[:64]


def _actor(request: HttpRequest) -> str:
    return request.user.get_username()


def _actor_id(request: HttpRequest) -> int:
    if request.user.pk is None:
        raise PermissionDenied
    return request.user.pk


@operator_api
@require_http_methods(["POST"])
def ai_candidates(request: HttpRequest) -> HttpResponse:
    payload = _json_body(request, max_bytes=services.ai_authoring_request_limit(accept=False))
    _reject_unknown_fields(
        payload, {"organization", "project_id", "scenario_id", "description", "artifact_type"}
    )
    org = _resolve_org_in_scope(request, payload.get("organization"))
    _require_author(request, org.id)
    project = _resolve_project(org, payload.get("project_id"))
    if project is None:
        raise services.BuilderError("project_required")
    scenario = _resolve_scenario(org, project, payload.get("scenario_id"))
    result = authoring.generate_candidate(
        organization=org,
        project=project,
        scenario=scenario,
        actor=_actor(request),
        actor_id=_actor_id(request),
        description=payload.get("description"),
        artifact_type=payload.get("artifact_type", "workflow_definition"),
        request_id=_request_id(request),
    )
    return JsonResponse(result)


@operator_api
@require_http_methods(["POST"])
def ai_candidate_repair(request: HttpRequest) -> HttpResponse:
    """Run one human-triggered repair turn over an unsaved Scenario Studio candidate."""

    payload = _json_body(request, max_bytes=services.ai_authoring_request_limit(accept=True))
    _reject_unknown_fields(
        payload,
        {
            "organization",
            "project_id",
            "scenario_id",
            "candidate",
            "instruction",
            "prompt_contract",
            "authoring_context",
        },
    )
    org = _resolve_org_in_scope(request, payload.get("organization"))
    _require_author(request, org.id)
    project = _resolve_project(org, payload.get("project_id"))
    if project is None:
        raise services.BuilderError("project_required")
    scenario = _resolve_scenario(org, project, payload.get("scenario_id"))
    if scenario is None:
        raise services.BuilderError("scenario_required")
    result = authoring.repair_candidate(
        organization=org,
        project=project,
        scenario=scenario,
        actor=_actor(request),
        actor_id=_actor_id(request),
        candidate=payload.get("candidate"),
        instruction=payload.get("instruction"),
        prompt_contract=payload.get("prompt_contract"),
        authoring_context=payload.get("authoring_context"),
        request_id=_request_id(request),
    )
    return JsonResponse(result)


@operator_api
@require_http_methods(["POST"])
def ai_candidate_accept(request: HttpRequest) -> HttpResponse:
    payload = _json_body(request, max_bytes=services.ai_authoring_request_limit(accept=True))
    _reject_unknown_fields(
        payload,
        {
            "organization",
            "project_id",
            "scenario_id",
            "name",
            "logical_id",
            "candidate",
            "artifact_type",
            "prompt_contract",
            "authoring_context",
            "draft_id",
            "revision",
        },
    )
    org = _resolve_org_in_scope(request, payload.get("organization"))
    _require_author(request, org.id)
    project = _resolve_project(org, payload.get("project_id"))
    if project is None:
        raise services.BuilderError("project_required")
    draft = authoring.accept_candidate(
        organization=org,
        project=project,
        scenario=_resolve_scenario(org, project, payload.get("scenario_id")),
        actor=_actor(request),
        name=payload.get("name", ""),
        logical_id=payload.get("logical_id", ""),
        candidate=payload.get("candidate"),
        artifact_type=payload.get("artifact_type", "workflow_definition"),
        prompt_contract=payload.get("prompt_contract"),
        authoring_context=payload.get("authoring_context"),
        draft_id=payload.get("draft_id"),
        expected_revision=payload.get("revision"),
        request_id=_request_id(request),
    )
    if isinstance(draft, ArtifactDraft):
        return JsonResponse(_serialize_artifact_draft(draft, can_write=True), status=201)
    return JsonResponse(_serialize(draft, can_write=True), status=201)


@operator_api
@require_http_methods(["POST"])
def transient_diagnostics(request: HttpRequest) -> HttpResponse:
    """Canonical validation for an unsaved Studio candidate; never persists it."""
    payload = _json_body(request, max_bytes=services.ai_authoring_request_limit(accept=True))
    _reject_unknown_fields(payload, {"organization", "body"})
    org = _resolve_org_in_scope(request, payload.get("organization"))
    _require_author(request, org.id)
    return JsonResponse(services.diagnose(payload.get("body")))


def _release_scenario(request: HttpRequest, public_id: UUID) -> Scenario:
    scenario = (
        Scenario.objects.select_related("organization", "project")
        .filter(public_id=public_id)
        .first()
    )
    if scenario is None:
        raise Http404
    allowed = allowed_organization_ids(request.user)
    if allowed is not None and scenario.organization_id not in allowed:
        raise Http404
    decision = authorize(
        user=request.user,
        capability=Capability.SCENARIO_RELEASE,
        organization=scenario.organization,
        project=scenario.project,
        scenario=scenario,
    )
    if not decision.allowed:
        raise PermissionDenied
    return scenario


def _manifest_payload_result(
    *, scenario: Scenario, payload: dict[str, Any]
) -> tuple[list[Any] | None, JsonResponse | None]:
    _reject_unknown_fields(payload, {"items"})
    try:
        refs = release_authoring.resolve_manifest_refs(
            scenario=scenario,
            items=payload.get("items"),
        )
    except release_authoring.ManifestRequestError as exc:
        return None, JsonResponse(
            {"ok": False, "diagnostics": [exc.as_diagnostic()]},
        )
    return refs, None


@operator_api
@require_http_methods(["POST"])
def release_manifest_preflight(request: HttpRequest, public_id: UUID) -> HttpResponse:
    """Run canonical release compilation inside an always-rollback transaction."""

    scenario = _release_scenario(request, public_id)
    payload = _json_body(
        request,
        max_bytes=release_authoring.MAX_MANIFEST_REQUEST_BYTES,
    )
    refs, error_response = _manifest_payload_result(scenario=scenario, payload=payload)
    if error_response is not None:
        return error_response
    if refs is None:
        raise services.BuilderError("manifest_invalid")
    result = release_authoring.preflight_release(
        scenario=scenario,
        refs=refs,
        runtime_version=release_authoring.candidate_runtime_version(scenario),
        created_by=_actor(request),
    )
    return JsonResponse(result.as_dict())


@operator_api
@require_http_methods(["POST"])
def release_manifest_requirements(request: HttpRequest, public_id: UUID) -> HttpResponse:
    """Return deterministic manifest roles required by one exact published workflow."""

    scenario = _release_scenario(request, public_id)
    payload = _json_body(
        request,
        max_bytes=release_authoring.MAX_MANIFEST_REQUEST_BYTES,
    )
    _reject_unknown_fields(payload, {"workflow_artifact_id"})
    try:
        result = release_authoring.analyze_workflow_requirements(
            scenario=scenario,
            workflow_artifact_id=payload.get("workflow_artifact_id"),
        )
    except release_authoring.ManifestRequestError as exc:
        return JsonResponse({"ok": False, "diagnostics": [exc.as_diagnostic()]})
    except CompileError as exc:
        return JsonResponse({"ok": False, "diagnostics": [exc.as_diagnostic()]})
    return JsonResponse({"ok": True, "diagnostics": [], **result})


@operator_api
@require_http_methods(["POST"])
def release_manifest_compile(request: HttpRequest, public_id: UUID) -> HttpResponse:
    """Create one audited candidate or return a safe canonical diagnostic."""

    scenario = _release_scenario(request, public_id)
    payload = _json_body(
        request,
        max_bytes=release_authoring.MAX_MANIFEST_REQUEST_BYTES,
    )
    refs, error_response = _manifest_payload_result(scenario=scenario, payload=payload)
    if error_response is not None:
        return error_response
    if refs is None:
        raise services.BuilderError("manifest_invalid")
    try:
        with transaction.atomic():
            release = compile_release(
                scenario=scenario,
                refs=refs,
                runtime_version=release_authoring.candidate_runtime_version(scenario),
                created_by=_actor(request),
            )
            record_event(
                actor_type="user",
                actor_id=_actor(request),
                action="console.scenario.release.compile",
                outcome="success",
                organization_id=scenario.organization_id,
                resource_type="scenario_release",
                resource_id=str(release.pk),
                reason=release.artifact_manifest_sha256,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
            )
    except CompileError as exc:
        record_event(
            actor_type="user",
            actor_id=_actor(request),
            action="console.scenario.release.compile",
            outcome="failure",
            organization_id=scenario.organization_id,
            resource_type="scenario",
            resource_id=str(scenario.pk),
            reason=exc.code,
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
        return JsonResponse({"ok": False, "diagnostics": [exc.as_diagnostic()]})
    return JsonResponse(
        {
            "ok": True,
            "diagnostics": [],
            "release": {
                "id": release.pk,
                "status": release.status,
                "artifact_manifest_sha256": release.artifact_manifest_sha256,
            },
        },
        status=201,
    )


def _json_body(request: HttpRequest, *, max_bytes: int | None = None) -> dict[str, Any]:
    if not request.body:
        return {}
    if max_bytes is not None and len(request.body) > max_bytes:
        raise services.BuilderError("request_too_large")
    try:
        parsed = json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise services.BuilderError("invalid_json", "request body is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise services.BuilderError("invalid_json", "request body must be a JSON object")
    return parsed


def _reject_unknown_fields(payload: dict[str, Any], allowed: set[str]) -> None:
    if set(payload) - allowed:
        raise services.BuilderError("unexpected_field")


def _resolve_org_in_scope(request: HttpRequest, ref: Any) -> Organization:
    allowed = allowed_organization_ids(request.user)
    qs = Organization.objects.all()
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        org = qs.filter(pk=int(ref)).first()
    elif isinstance(ref, str) and ref:
        org = qs.filter(slug=ref).first()
    else:
        raise services.BuilderError("organization_required", "organization is required")
    if org is None or (allowed is not None and org.id not in allowed):
        raise Http404
    return org


def _require_author(request: HttpRequest, organization_id: int) -> None:
    if not can_author_scenarios(request.user, organization_id):
        raise PermissionDenied


def _scoped_draft(request: HttpRequest, pk: int) -> WorkflowDraft:
    allowed = allowed_organization_ids(request.user)
    qs = WorkflowDraft.objects.select_related("organization", "project")
    if allowed is not None:
        qs = qs.filter(organization_id__in=allowed)
    draft = qs.filter(pk=pk).first()
    if draft is None:
        raise Http404
    return draft


def _scoped_artifact_draft(request: HttpRequest, pk: int) -> ArtifactDraft:
    allowed = allowed_organization_ids(request.user)
    qs = ArtifactDraft.objects.select_related("organization", "project")
    if allowed is not None:
        qs = qs.filter(organization_id__in=allowed)
    draft = qs.filter(pk=pk).first()
    if draft is None:
        raise Http404
    return draft


def _serialize(draft: WorkflowDraft, *, can_write: bool) -> dict[str, Any]:
    return {
        "id": draft.pk,
        "organization": draft.organization.slug,
        "organization_id": draft.organization_id,
        "project_id": draft.project_id,
        "scenario_id": draft.scenario_id,
        "name": draft.name,
        "logical_id": draft.logical_id,
        "logical_description": draft.logical_description,
        "body": draft.body,
        "last_published_version": draft.last_published_version,
        "last_published_at": (
            draft.last_published_at.isoformat() if draft.last_published_at else None
        ),
        "created_by": draft.created_by,
        "updated_by": draft.updated_by,
        "revision": draft.revision,
        "updated_at": draft.updated_at.isoformat(),
        # Drives the frontend read-only mode; the server still re-checks on every write.
        "can_write": can_write,
    }


def _serialize_artifact_draft(draft: ArtifactDraft, *, can_write: bool) -> dict[str, Any]:
    return {
        "id": draft.pk,
        "draft_kind": "artifact",
        "artifact_type": draft.artifact_type,
        "organization": draft.organization.slug,
        "organization_id": draft.organization_id,
        "project_id": draft.project_id,
        "name": draft.name,
        "logical_id": draft.logical_id,
        "body": draft.body,
        "created_by": draft.created_by,
        "updated_by": draft.updated_by,
        "revision": draft.revision,
        "updated_at": draft.updated_at.isoformat(),
        "can_write": can_write,
    }


@operator_api
@require_http_methods(["GET"])
def node_schema(request: HttpRequest) -> HttpResponse:
    org = _resolve_org_in_scope(request, request.GET.get("organization"))
    schema = build_node_schema(organization_id=org.id)
    schema["organization"] = org.slug
    schema["can_write"] = can_author_scenarios(request.user, org.id)
    schema["projects"] = [
        {"id": project.id, "slug": project.slug, "name": project.name}
        for project in AIProject.objects.filter(organization=org).order_by("name", "id")
    ]
    return JsonResponse(schema)


@operator_api
@require_http_methods(["GET", "POST"])
def drafts(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        allowed = allowed_organization_ids(request.user)
        qs = WorkflowDraft.objects.select_related("organization")
        if allowed is not None:
            qs = qs.filter(organization_id__in=allowed)
        items = [
            {
                "id": d.pk,
                "organization": d.organization.slug,
                "organization_id": d.organization_id,
                "project_id": d.project_id,
                "scenario_id": d.scenario_id,
                "name": d.name,
                "logical_id": d.logical_id,
                "logical_description": d.logical_description,
                "last_published_version": d.last_published_version,
                "updated_at": d.updated_at.isoformat(),
                "revision": d.revision,
                "can_write": can_author_scenarios(request.user, d.organization_id),
            }
            for d in qs
        ]
        return JsonResponse({"drafts": items})

    payload = _json_body(request)
    _reject_unknown_fields(
        payload,
        {
            "organization",
            "project_id",
            "scenario_id",
            "name",
            "logical_id",
            "logical_description",
            "body",
        },
    )
    org = _resolve_org_in_scope(request, payload.get("organization"))
    _require_author(request, org.id)
    project = _resolve_project(org, payload.get("project_id"))
    scenario = _resolve_scenario(org, project, payload.get("scenario_id"))
    draft = services.create_draft(
        organization=org,
        name=payload.get("name", ""),
        logical_id=payload.get("logical_id", ""),
        logical_description=payload.get("logical_description", ""),
        body=payload.get("body"),
        actor=_actor(request),
        project=project,
        scenario=scenario,
        request_id=_request_id(request),
    )
    return JsonResponse(_serialize(draft, can_write=True), status=201)


@operator_api
@require_http_methods(["GET", "PUT", "DELETE"])
def draft_detail(request: HttpRequest, pk: int) -> HttpResponse:
    draft = _scoped_draft(request, pk)
    can_write = can_author_scenarios(request.user, draft.organization_id)
    if request.method == "GET":
        return JsonResponse(_serialize(draft, can_write=can_write))

    _require_author(request, draft.organization_id)
    if request.method == "DELETE":
        payload = _json_body(request)
        _reject_unknown_fields(payload, {"revision"})
        services.delete_draft(
            draft,
            actor=_actor(request),
            expected_revision=payload.get("revision"),
            request_id=_request_id(request),
        )
        return JsonResponse({"deleted": True})

    payload = _json_body(request)
    _reject_unknown_fields(payload, {"name", "logical_description", "body", "revision"})
    updated = services.update_draft(
        draft,
        actor=_actor(request),
        expected_revision=payload.get("revision"),
        name=payload.get("name"),
        logical_description=payload.get("logical_description"),
        body=payload.get("body"),
        request_id=_request_id(request),
    )
    return JsonResponse(_serialize(updated, can_write=True))


@operator_api
@require_http_methods(["POST"])
def draft_diagnostics(request: HttpRequest, pk: int) -> HttpResponse:
    draft = _scoped_draft(request, pk)
    payload = _json_body(request)
    # Allow validating an unsaved editor body; fall back to the stored draft body.
    body = payload["body"] if "body" in payload else draft.body
    return JsonResponse(services.diagnose(body))


@operator_api
@require_http_methods(["POST"])
def draft_publish(request: HttpRequest, pk: int) -> HttpResponse:
    draft = _scoped_draft(request, pk)
    _require_author(request, draft.organization_id)
    payload = _json_body(request)
    _reject_unknown_fields(payload, {"revision", "version_description"})
    artifact = services.publish_draft(
        draft,
        actor=_actor(request),
        expected_revision=payload.get("revision"),
        version_description=payload.get("version_description", ""),
        request_id=_request_id(request),
    )
    draft.refresh_from_db(fields=["revision"])
    return JsonResponse(
        {
            "published": True,
            "artifact_type": artifact.type,
            "logical_id": artifact.logical_id,
            "logical_description": artifact.logical_description,
            "version": artifact.version,
            "version_description": artifact.version_description,
            "checksum": artifact.checksum,
            "revision": draft.revision,
        },
        status=201,
    )


@operator_api
@require_http_methods(["GET"])
def artifact_drafts(request: HttpRequest) -> HttpResponse:
    allowed = allowed_organization_ids(request.user)
    qs = ArtifactDraft.objects.select_related("organization", "project")
    if allowed is not None:
        qs = qs.filter(organization_id__in=allowed)
    return JsonResponse(
        {
            "drafts": [
                _serialize_artifact_draft(
                    draft,
                    can_write=can_author_scenarios(request.user, draft.organization_id),
                )
                for draft in qs
            ]
        }
    )


@operator_api
@require_http_methods(["GET", "PUT", "DELETE"])
def artifact_draft_detail(request: HttpRequest, pk: int) -> HttpResponse:
    draft = _scoped_artifact_draft(request, pk)
    can_write = can_author_scenarios(request.user, draft.organization_id)
    if request.method == "GET":
        return JsonResponse(_serialize_artifact_draft(draft, can_write=can_write))
    _require_author(request, draft.organization_id)
    if request.method == "DELETE":
        payload = _json_body(request)
        _reject_unknown_fields(payload, {"revision"})
        services.delete_artifact_draft(
            draft,
            actor=_actor(request),
            expected_revision=payload.get("revision"),
            request_id=_request_id(request),
        )
        return JsonResponse({"deleted": True})
    payload = _json_body(request, max_bytes=services.ai_authoring_request_limit(accept=True))
    _reject_unknown_fields(payload, {"name", "body", "revision"})
    updated = services.update_artifact_draft(
        draft,
        actor=_actor(request),
        expected_revision=payload.get("revision"),
        name=payload.get("name"),
        body=payload.get("body"),
        request_id=_request_id(request),
    )
    return JsonResponse(_serialize_artifact_draft(updated, can_write=True))


@operator_api
@require_http_methods(["POST"])
def artifact_draft_diagnostics(request: HttpRequest, pk: int) -> HttpResponse:
    draft = _scoped_artifact_draft(request, pk)
    payload = _json_body(request, max_bytes=services.ai_authoring_request_limit(accept=True))
    _reject_unknown_fields(payload, {"body"})
    body = payload["body"] if "body" in payload else draft.body
    return JsonResponse(services.diagnose_artifact(draft.artifact_type, body))


def _resolve_project(org: Organization, ref: Any) -> AIProject | None:
    if ref in (None, ""):
        return None
    project = AIProject.objects.filter(pk=ref, organization_id=org.id).first()
    if project is None:
        raise services.BuilderError("project_not_found", "project not found in organization")
    return project


def _resolve_scenario(org: Organization, project: AIProject | None, ref: Any) -> Scenario | None:
    if ref in (None, ""):
        return None
    if not isinstance(ref, int) and not (isinstance(ref, str) and ref.isdigit()):
        raise services.BuilderError("scenario_invalid")
    scenario = Scenario.objects.filter(pk=int(ref), organization=org).first()
    if scenario is None:
        raise services.BuilderError("scenario_not_found")
    if project is None or scenario.project_id != project.id:
        raise services.BuilderError("scenario_project_mismatch")
    return scenario
