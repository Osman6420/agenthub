"""Operator console views (server-rendered, tenant-scoped, login required).

Authentication is handled by Django's auth backends — LDAP in production (ADR-0001)
or the local model backend when LDAP is disabled. Authorization scope for every
screen comes from :mod:`apps.console.scoping`.
"""

from __future__ import annotations

from collections.abc import Callable

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from apps.agents.models import AgentRun
from apps.agents.services import AgentRequestError, operator_cancel_agent_run
from apps.audit.services import record_event
from apps.catalog.models import Scenario, ScenarioAlias
from apps.console import scoping
from apps.console.forms import (
    BindingForm,
    CanaryForm,
    ConsumerForm,
    DocumentSetForm,
    DocumentUploadForm,
    OrganizationForm,
    ProjectForm,
    ScenarioForm,
)
from apps.documents import services as document_services
from apps.documents.models import (
    Document,
    DocumentLifecycle,
    DocumentSet,
    DocumentSetGrant,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    DocumentVersion,
    GrantPrincipalType,
    ScenarioDocumentSetBinding,
)
from apps.documents.services import DocumentError
from apps.evaluations.services import EvalError, run_eval
from apps.identity.models import Consumer, ConsumerStatus
from apps.releases.lifecycle import LifecycleError, promote, rollback, start_canary, stop_canary
from apps.releases.models import CanaryStatus, ReleaseCanary, ReleaseStatus, ScenarioRelease
from apps.tenancy.services import (
    UserLike,
    admin_organization_ids,
    allowed_organization_ids,
    author_organization_ids,
    can_admin_org,
    can_author_scenarios,
    can_create_organization,
    can_manage_releases,
    is_platform_admin,
)
from apps.tools.approvals import ToolApprovalError, cancel_invocation, decide_approval
from apps.tools.authz import resolve_actor_roles
from apps.tools.models import ApprovalRequest, ApprovalStatus, ToolInvocation


def _audit_create(
    request: HttpRequest, resource_type: str, resource_id: str, org_id: int | None
) -> None:
    record_event(
        actor_type="user",
        actor_id=request.user.get_username(),
        action=f"console.{resource_type}.create",
        outcome="success",
        organization_id=org_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    user = request.user
    context = {
        "is_platform_admin": is_platform_admin(user),
        "counts": {
            "organizations": scoping.scoped_organizations(user).count(),
            "projects": scoping.scoped_projects(user).count(),
            "scenarios": scoping.scoped_scenarios(user).count(),
            "consumers": scoping.scoped_consumers(user).count(),
            "artifacts": scoping.scoped_artifacts(user).count(),
            "releases": scoping.scoped_releases(user).count(),
        },
    }
    return render(request, "console/dashboard.html", context)


@login_required
def organizations(request: HttpRequest) -> HttpResponse:
    rows = [
        {"cols": [o.slug, o.name, o.status]} for o in scoping.scoped_organizations(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Organizations",
            "headers": ["Slug", "Name", "Status"],
            "rows": rows,
            "create_links": (
                [{"url": "console:organization_create", "label": "New organization"}]
                if can_create_organization(request.user)
                else []
            ),
        },
    )


@login_required
def projects(request: HttpRequest) -> HttpResponse:
    rows = [
        {"cols": [p.organization.slug, p.slug, p.name, p.risk_level, p.status]}
        for p in scoping.scoped_projects(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "AI Projects",
            "headers": ["Organization", "Slug", "Name", "Risk", "Status"],
            "rows": rows,
            "create_links": (
                [{"url": "console:project_create", "label": "New project"}]
                if admin_organization_ids(request.user) != set()
                else []
            ),
        },
    )


@login_required
def scenarios(request: HttpRequest) -> HttpResponse:
    rows = [
        {
            "cols": [
                s.project.organization.slug,
                s.project.slug,
                s.slug,
                s.type,
                s.status,
            ]
        }
        for s in scoping.scoped_scenarios(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Scenarios",
            "headers": ["Organization", "Project", "Slug", "Type", "Status"],
            "rows": rows,
            "create_links": (
                [{"url": "console:scenario_create", "label": "New scenario"}]
                if author_organization_ids(request.user) != set()
                else []
            ),
        },
    )


@login_required
def consumers(request: HttpRequest) -> HttpResponse:
    rows = [
        {"cols": [c.organization.slug, c.name, c.subject, c.protocol, c.status]}
        for c in scoping.scoped_consumers(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Consumers",
            "headers": ["Organization", "Name", "Subject", "Protocol", "Status"],
            "rows": rows,
            "create_links": (
                [
                    {"url": "console:consumer_create", "label": "New consumer"},
                    {"url": "console:binding_create", "label": "New binding"},
                ]
                if admin_organization_ids(request.user) != set()
                else []
            ),
        },
    )


@login_required
def artifacts(request: HttpRequest) -> HttpResponse:
    rows = [
        {"cols": [a.organization.slug, a.type, a.logical_id, f"v{a.version}", a.checksum[:12]]}
        for a in scoping.scoped_artifacts(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Artifacts",
            "headers": ["Organization", "Type", "Logical ID", "Version", "Checksum"],
            "rows": rows,
        },
    )


@login_required
def releases(request: HttpRequest) -> HttpResponse:
    user = request.user
    rows = []
    for r in scoping.scoped_releases(user).select_related("scenario__project__organization"):
        manageable = can_manage_releases(user, r.scenario.project.organization_id)
        pre_active = r.status in (ReleaseStatus.CANDIDATE, ReleaseStatus.CANARY)
        rows.append(
            {
                "id": r.pk,
                "org": r.scenario.project.organization.slug,
                "scenario": r.scenario.slug,
                "status": r.status,
                "runtime": r.runtime_version,
                "manifest": r.artifact_manifest_sha256[:12],
                "can_eval": manageable and pre_active,
                "can_promote": manageable and pre_active,
                "can_canary": manageable and pre_active,
                "can_rollback": manageable and r.status == ReleaseStatus.SUPERSEDED,
            }
        )

    allowed = allowed_organization_ids(user)
    canary_qs = ReleaseCanary.objects.filter(status=CanaryStatus.ACTIVE).select_related(
        "scenario__project__organization", "consumer"
    )
    if allowed is not None:
        canary_qs = canary_qs.filter(scenario__project__organization_id__in=allowed)
    canaries = [
        {
            "id": c.pk,
            "scenario": c.scenario.slug,
            "consumer": c.consumer.subject,
            "release": c.release_id,
            "expires": c.expires_at,
            "can_stop": can_manage_releases(user, c.scenario.project.organization_id),
        }
        for c in canary_qs
    ]
    return render(
        request, "console/releases.html", {"title": "Releases", "rows": rows, "canaries": canaries}
    )


def _manageable_release(user: UserLike, release_id: int) -> ScenarioRelease:
    release = (
        ScenarioRelease.objects.select_related("scenario__project__organization")
        .filter(pk=release_id)
        .first()
    )
    if release is None:
        raise Http404
    if not can_manage_releases(user, release.scenario.project.organization_id):
        raise PermissionDenied
    return release


@login_required
@require_POST
def release_run_eval(request: HttpRequest, release_id: int) -> HttpResponse:
    release = _manageable_release(request.user, release_id)
    try:
        run = run_eval(release=release, created_by=request.user.get_username())
        messages.success(
            request, f"Eval {run.status}: {run.passed_cases}/{run.total_cases} cases passed."
        )
    except EvalError as exc:
        messages.error(request, f"Eval could not start: {exc.code}")
    return redirect("console:releases")


@login_required
@require_POST
def release_promote(request: HttpRequest, release_id: int) -> HttpResponse:
    release = _manageable_release(request.user, release_id)
    try:
        promote(release=release, actor=request.user.get_username())
        messages.success(request, f"Release {release.pk} promoted to active.")
    except LifecycleError as exc:
        messages.error(request, f"Promotion denied: {exc.code}")
    return redirect("console:releases")


@login_required
@require_POST
def release_rollback(request: HttpRequest, release_id: int) -> HttpResponse:
    release = _manageable_release(request.user, release_id)
    try:
        rollback(scenario=release.scenario, target=release, actor=request.user.get_username())
        messages.success(request, f"Rolled back to release {release.pk}.")
    except LifecycleError as exc:
        messages.error(request, f"Rollback denied: {exc.code}")
    return redirect("console:releases")


@login_required
def canary_start(request: HttpRequest, release_id: int) -> HttpResponse:
    release = _manageable_release(request.user, release_id)
    form = CanaryForm(request.POST or None, release=release)
    if request.method == "POST" and form.is_valid():
        try:
            start_canary(
                release=release,
                consumer=form.cleaned_data["consumer"],
                ttl_seconds=form.cleaned_data["ttl_hours"] * 3600,
                actor=request.user.get_username(),
            )
            messages.success(request, "Canary started.")
            return redirect("console:releases")
        except LifecycleError as exc:
            messages.error(request, f"Canary denied: {exc.code}")
    return render(
        request,
        "console/form.html",
        {"title": f"Start canary for release {release.pk}", "form": form},
    )


@login_required
@require_POST
def canary_stop(request: HttpRequest, canary_id: int) -> HttpResponse:
    canary = (
        ReleaseCanary.objects.select_related("scenario__project__organization")
        .filter(pk=canary_id)
        .first()
    )
    if canary is None:
        raise Http404
    if not can_manage_releases(request.user, canary.scenario.project.organization_id):
        raise PermissionDenied
    try:
        stop_canary(canary=canary, actor=request.user.get_username())
        messages.success(request, "Canary stopped.")
    except LifecycleError as exc:
        messages.error(request, f"Stop denied: {exc.code}")
    return redirect("console:releases")


@login_required
def tool_approvals(request: HttpRequest) -> HttpResponse:
    user = request.user
    allowed = allowed_organization_ids(user)
    queryset = (
        ApprovalRequest.objects.filter(status=ApprovalStatus.PENDING)
        .select_related("invocation", "organization")
        .order_by("expires_at")
    )
    if allowed is not None:
        queryset = queryset.filter(organization_id__in=allowed)
    rows = []
    for approval in queryset:
        roles = resolve_actor_roles(
            username=user.get_username(), organization_id=approval.organization_id
        )
        rows.append(
            {
                "id": approval.pk,
                "org": approval.organization.slug,
                "invocation": approval.invocation_id,
                "tool_ref": approval.invocation.tool_ref,
                "risk": approval.invocation.risk,
                "expires": approval.expires_at,
                "can_decide": bool(set(roles or []) & set(approval.approver_roles)),
            }
        )
    return render(request, "console/tool_approvals.html", {"title": "Tool approvals", "rows": rows})


@login_required
@require_POST
def tool_approval_decide(request: HttpRequest, approval_id: int) -> HttpResponse:
    approval = ApprovalRequest.objects.filter(pk=approval_id).first()
    if approval is None:
        raise Http404
    if not _operator_can_access_org(request.user, approval.organization_id):
        raise PermissionDenied
    roles = resolve_actor_roles(
        username=request.user.get_username(), organization_id=approval.organization_id
    )
    if roles is None:
        raise PermissionDenied
    approve = request.POST.get("decision") == "approve"
    try:
        decide_approval(
            approval_id=approval.pk,
            organization_id=approval.organization_id,
            actor=request.user.get_username(),
            actor_roles=roles,
            approve=approve,
            reason=request.POST.get("reason", ""),
        )
        messages.success(
            request, f"Approval {approval.pk} {'approved' if approve else 'rejected'}."
        )
    except ToolApprovalError as exc:
        messages.error(request, f"Decision denied: {exc.code}")
    return redirect("console:tool_approvals")


@login_required
@require_POST
def tool_invocation_cancel(request: HttpRequest, invocation_id: int) -> HttpResponse:
    invocation = ToolInvocation.objects.filter(pk=invocation_id).first()
    if invocation is None:
        raise Http404
    if not _operator_can_access_org(request.user, invocation.organization_id):
        raise PermissionDenied
    try:
        cancel_invocation(
            invocation_id=invocation.pk,
            organization_id=invocation.organization_id,
            actor=request.user.get_username(),
        )
        messages.success(request, f"Invocation {invocation.pk} cancelled.")
    except ToolApprovalError as exc:
        messages.error(request, f"Cancel denied: {exc.code}")
    return redirect("console:tool_approvals")


@login_required
def agent_runs(request: HttpRequest) -> HttpResponse:
    rows = [
        {
            "public_id": str(run.public_id),
            "org": run.organization.slug,
            "scenario": run.scenario.slug,
            "status": run.status,
            "steps": run.step_count,
            "tool_calls": run.tool_call_count,
            "error": run.error_code,
            "created": run.created_at,
        }
        for run in scoping.scoped_agent_runs(request.user).order_by("-created_at")[:200]
    ]
    return render(request, "console/agent_runs.html", {"title": "Agent runs", "rows": rows})


@login_required
def agent_run_detail(request: HttpRequest, public_id: str) -> HttpResponse:
    run = _scoped_agent_run(request.user, public_id)
    # Only bounded, already-redacted fields reach the template: the event trail carries
    # allowlisted decision/outcome labels and checksums, never raw state or payloads.
    events = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "step_index": event.step_index,
            "decision": event.decision,
            "outcome": event.outcome,
            "reason_code": event.reason_code,
            "checksum": event.state_checksum[:12],
            "occurred_at": event.occurred_at,
        }
        for event in run.events.order_by("sequence")
    ]
    public = str(run.public_id)
    summary = {
        "public_id": public,
        "org": run.organization.slug,
        "scenario": run.scenario.slug,
        "status": run.status,
        "error": run.error_code,
        "steps": run.step_count,
        "tool_calls": run.tool_call_count,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "awaiting_role": run.awaiting_role,
        "created": run.created_at,
        "finished": run.finished_at,
        "can_cancel": run.status not in {"completed", "failed", "timed_out", "cancelled"},
    }
    return render(
        request,
        "console/agent_run_detail.html",
        {"title": f"Agent run {public[:8]}", "run": summary, "events": events},
    )


@login_required
@ensure_csrf_cookie
def builder(request: HttpRequest) -> HttpResponse:
    """Host the React Flow workflow builder SPA.

    The page only carries mount configuration — the operator's organizations in read
    scope with their per-org authoring flag (which drives the SPA's read-only mode). All
    authoritative validation, authorization, and publishing happen in the builder API;
    ``@ensure_csrf_cookie`` guarantees the SPA can obtain a CSRF token for its writes.
    """
    orgs = [
        {
            "slug": org.slug,
            "name": org.name,
            "can_write": can_author_scenarios(request.user, org.id),
        }
        for org in scoping.scoped_organizations(request.user).order_by("slug")
    ]
    return render(
        request,
        "console/builder.html",
        {"title": "Workflow builder", "builder_orgs": orgs},
    )


@login_required
def documents(request: HttpRequest) -> HttpResponse:
    """List the operator's document sets + documents and offer upload (P8.1).

    Read scope is tenant membership (``allowed_organization_ids``); upload/soft-delete require
    ``can_author_scenarios`` in the target org and are re-checked server-side. Non-authoritative:
    all state changes go through the audited ``apps.documents.services``.
    """
    user = request.user
    sets = [
        {
            "id": s.id,
            "org": s.organization.slug,
            "logical_id": s.logical_id,
            "name": s.name,
            "status": s.status,
            "versions": s.versions.count(),
        }
        for s in scoping.scoped_document_sets(user).order_by("organization_id", "logical_id")
    ]
    docs = [
        {
            "id": d.id,
            "org": d.organization.slug,
            "logical_id": d.logical_id,
            "title": d.title,
            "version": d.current_version,
            "tombstoned": d.is_tombstoned,
            "can_write": can_author_scenarios(user, d.organization_id),
            "can_purge": can_admin_org(user, d.organization_id),
        }
        for d in scoping.scoped_documents(user).order_by("organization_id", "logical_id")
    ]
    upload_form = DocumentUploadForm(user=user)
    set_form = DocumentSetForm(user=user)
    # An operator can upload iff they may author in at least one org (None = platform admin).
    can_upload = author_organization_ids(user) != set()
    return render(
        request,
        "console/documents.html",
        {
            "title": "Documents",
            "sets": sets,
            "documents": docs,
            "set_form": set_form,
            "form": upload_form,
            "can_upload": can_upload,
        },
    )


@login_required
@require_POST
def document_upload(request: HttpRequest) -> HttpResponse:
    form = DocumentUploadForm(request.POST, request.FILES, user=request.user)
    if not form.is_valid():
        messages.error(request, "Upload failed: check the form fields.")
        return redirect("console:documents")
    organization = form.cleaned_data["organization"]
    # Server-side authorization re-check (the scoped choices are UI convenience only).
    if not can_author_scenarios(request.user, organization.id):
        raise PermissionDenied
    upload = form.cleaned_data["file"]
    try:
        document_services.upload_document(
            organization=organization,
            logical_id=form.cleaned_data["logical_id"],
            title=form.cleaned_data["title"],
            mime_type=(upload.content_type or "application/octet-stream"),
            data=upload.read(),
            actor=request.user.get_username(),
        )
        messages.success(request, "Document uploaded.")
    except DocumentError as exc:
        messages.error(request, f"Upload failed: {exc.code}")
    return redirect("console:documents")


@login_required
@require_POST
def document_soft_delete(request: HttpRequest, pk: int) -> HttpResponse:
    document = _scoped_document(request.user, pk)
    if not can_author_scenarios(request.user, document.organization_id):
        raise PermissionDenied
    document_services.soft_delete_document(document, actor=request.user.get_username())
    messages.success(request, f"Document {document.logical_id} tombstoned.")
    return redirect("console:documents")


@login_required
@require_POST
def document_purge(request: HttpRequest, pk: int) -> HttpResponse:
    document = _scoped_document(request.user, pk)
    if not can_admin_org(request.user, document.organization_id):
        raise PermissionDenied
    confirmation = request.POST.get("confirm_logical_id", "")
    if not document.is_tombstoned:
        messages.error(request, "Purge denied: document must be tombstoned first.")
    elif confirmation != document.logical_id:
        messages.error(request, "Purge denied: confirmation does not match the document ID.")
    else:
        try:
            removed = document_services.purge_document(document, actor=request.user.get_username())
            messages.success(request, f"Document purged ({removed} versions removed).")
        except DocumentError as exc:
            messages.error(request, f"Purge failed: {exc.code}")
    return redirect("console:documents")


def _scoped_document(user: UserLike, pk: int) -> Document:
    try:
        return scoping.scoped_documents(user).get(pk=pk)
    except Document.DoesNotExist as exc:
        raise Http404 from exc


@login_required
@require_POST
def document_set_create(request: HttpRequest) -> HttpResponse:
    form = DocumentSetForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, "Create failed: check the form fields.")
        return redirect("console:documents")
    organization = form.cleaned_data["organization"]
    if not can_author_scenarios(request.user, organization.id):
        raise PermissionDenied
    try:
        document_services.create_document_set(
            organization=organization,
            logical_id=form.cleaned_data["logical_id"],
            name=form.cleaned_data["name"],
            actor=request.user.get_username(),
        )
        messages.success(request, "Document set created.")
    except DocumentError as exc:
        messages.error(request, f"Create failed: {exc.code}")
    return redirect("console:documents")


@login_required
def document_set_detail(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
    can_write = can_author_scenarios(request.user, document_set.organization_id)
    versions = [
        {
            "id": v.id,
            "version": v.version,
            "status": v.status,
            "is_draft": v.status == DocumentSetVersionStatus.DRAFT,
            "members": [
                {
                    "logical_id": m.document_version.document.logical_id,
                    "version": m.document_version.version,
                    "ordinal": m.ordinal,
                }
                for m in v.memberships.select_related("document_version__document").order_by(
                    "ordinal"
                )
            ],
        }
        for v in document_set.versions.order_by("-version")
    ]
    # Active, uploaded documents in this set's tenant, offered as members of a draft version.
    candidate_docs = [
        {"id": d.id, "logical_id": d.logical_id, "version": d.current_version}
        for d in Document.objects.filter(
            organization_id=document_set.organization_id,
            lifecycle_state=DocumentLifecycle.ACTIVE,
            current_version__gt=0,
        ).order_by("logical_id")
    ]
    bindings = list(
        document_set.scenario_bindings.select_related("scenario__project").order_by(
            "scenario__project__slug", "scenario__slug"
        )
    )
    grants = list(
        document_set.grants.filter(principal_type=GrantPrincipalType.CONSUMER).order_by(
            "principal_ref"
        )
    )
    consumer_ids = [int(g.principal_ref) for g in grants if g.principal_ref.isdigit()]
    consumers_by_id = {
        c.id: c
        for c in Consumer.objects.filter(
            id__in=consumer_ids, organization_id=document_set.organization_id
        )
    }
    return render(
        request,
        "console/document_set_detail.html",
        {
            "title": f"Document set · {document_set.logical_id}",
            "set": {
                "id": document_set.id,
                "org": document_set.organization.slug,
                "logical_id": document_set.logical_id,
                "name": document_set.name,
                "status": document_set.status,
            },
            "versions": versions,
            "candidate_docs": candidate_docs,
            "bindings": bindings,
            "candidate_scenarios": Scenario.objects.filter(
                project__organization_id=document_set.organization_id
            ).order_by("project__slug", "slug"),
            "grants": [
                {
                    "id": grant.id,
                    "principal_ref": grant.principal_ref,
                    "consumer": consumers_by_id.get(int(grant.principal_ref))
                    if grant.principal_ref.isdigit()
                    else None,
                }
                for grant in grants
            ],
            "candidate_consumers": Consumer.objects.filter(
                organization_id=document_set.organization_id,
                status=ConsumerStatus.ACTIVE,
            ).order_by("name", "subject"),
            "can_write": can_write,
        },
    )


@login_required
@require_POST
def document_set_version_create(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
    if not can_author_scenarios(request.user, document_set.organization_id):
        raise PermissionDenied
    document_services.create_document_set_version(
        document_set=document_set, actor=request.user.get_username()
    )
    messages.success(request, "Draft version created.")
    return redirect("console:document_set_detail", pk=document_set.pk)


@login_required
@require_POST
def document_set_add_member(request: HttpRequest, version_pk: int) -> HttpResponse:
    set_version = _scoped_set_version(request.user, version_pk)
    if not can_author_scenarios(request.user, set_version.organization_id):
        raise PermissionDenied
    document_id = request.POST.get("document_id", "")
    document = (
        Document.objects.filter(
            pk=document_id,
            organization_id=set_version.organization_id,
            lifecycle_state=DocumentLifecycle.ACTIVE,
            current_version__gt=0,
        ).first()
        if document_id.isdigit()
        else None
    )
    version = (
        DocumentVersion.objects.filter(document=document, version=document.current_version).first()
        if document is not None
        else None
    )
    if version is None:
        messages.error(request, "Add member failed: invalid document.")
        return redirect("console:document_set_detail", pk=set_version.document_set_id)
    try:
        document_services.add_document_to_set_version(
            set_version=set_version, document_version=version, actor=request.user.get_username()
        )
        messages.success(request, "Member added.")
    except DocumentError as exc:
        messages.error(request, f"Add member failed: {exc.code}")
    return redirect("console:document_set_detail", pk=set_version.document_set_id)


@login_required
@require_POST
def document_set_version_publish(request: HttpRequest, version_pk: int) -> HttpResponse:
    set_version = _scoped_set_version(request.user, version_pk)
    if not can_author_scenarios(request.user, set_version.organization_id):
        raise PermissionDenied
    try:
        document_services.publish_document_set_version(
            set_version=set_version, actor=request.user.get_username()
        )
        messages.success(request, "Version published.")
    except DocumentError as exc:
        messages.error(request, f"Publish failed: {exc.code}")
    return redirect("console:document_set_detail", pk=set_version.document_set_id)


def _scoped_document_set(user: UserLike, pk: int) -> DocumentSet:
    try:
        return scoping.scoped_document_sets(user).get(pk=pk)
    except DocumentSet.DoesNotExist as exc:
        raise Http404 from exc


def _scoped_set_version(user: UserLike, pk: int) -> DocumentSetVersion:
    try:
        return scoping.scoped_document_set_versions(user).get(pk=pk)
    except DocumentSetVersion.DoesNotExist as exc:
        raise Http404 from exc


@login_required
@require_POST
def document_set_bind_scenario(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
    if not can_author_scenarios(request.user, document_set.organization_id):
        raise PermissionDenied
    scenario_id = request.POST.get("scenario_id", "")
    scenario = (
        Scenario.objects.filter(
            id=scenario_id, project__organization_id=document_set.organization_id
        ).first()
        if scenario_id.isdigit()
        else None
    )
    if scenario is None:
        messages.error(request, "Bind failed: invalid scenario.")
    else:
        try:
            document_services.bind_scenario_document_set(
                scenario=scenario, document_set=document_set, actor=request.user.get_username()
            )
            messages.success(request, "Scenario bound. Recompile its release to apply the change.")
        except DocumentError as exc:
            messages.error(request, f"Bind failed: {exc.code}")
    return redirect("console:document_set_detail", pk=document_set.pk)


@login_required
@require_POST
def document_set_unbind_scenario(request: HttpRequest, binding_pk: int) -> HttpResponse:
    binding = (
        ScenarioDocumentSetBinding.objects.select_related("document_set")
        .filter(pk=binding_pk)
        .first()
    )
    if (
        binding is None
        or not scoping.scoped_document_sets(request.user)
        .filter(pk=binding.document_set_id)
        .exists()
    ):
        raise Http404
    if not can_author_scenarios(request.user, binding.organization_id):
        raise PermissionDenied
    document_set_id = binding.document_set_id
    document_services.unbind_scenario_document_set(binding, actor=request.user.get_username())
    messages.success(request, "Scenario unbound. Recompile its release to apply the change.")
    return redirect("console:document_set_detail", pk=document_set_id)


@login_required
@require_POST
def document_set_grant_consumer(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
    if not can_author_scenarios(request.user, document_set.organization_id):
        raise PermissionDenied
    consumer_id = request.POST.get("consumer_id", "")
    consumer = (
        Consumer.objects.filter(
            id=consumer_id,
            organization_id=document_set.organization_id,
            status=ConsumerStatus.ACTIVE,
        ).first()
        if consumer_id.isdigit()
        else None
    )
    if consumer is None:
        messages.error(request, "Grant failed: invalid consumer.")
    else:
        try:
            document_services.grant_document_set(
                document_set=document_set,
                principal_type=GrantPrincipalType.CONSUMER,
                principal_ref=str(consumer.id),
                actor=request.user.get_username(),
            )
            messages.success(request, "Consumer retrieval granted.")
        except DocumentError as exc:
            messages.error(request, f"Grant failed: {exc.code}")
    return redirect("console:document_set_detail", pk=document_set.pk)


@login_required
@require_POST
def document_set_revoke_grant(request: HttpRequest, grant_pk: int) -> HttpResponse:
    grant = DocumentSetGrant.objects.select_related("document_set").filter(pk=grant_pk).first()
    if (
        grant is None
        or not scoping.scoped_document_sets(request.user).filter(pk=grant.document_set_id).exists()
    ):
        raise Http404
    if not can_author_scenarios(request.user, grant.organization_id):
        raise PermissionDenied
    document_set_id = grant.document_set_id
    document_services.revoke_document_set_grant(grant, actor=request.user.get_username())
    messages.success(request, "Consumer retrieval grant revoked.")
    return redirect("console:document_set_detail", pk=document_set_id)


@login_required
@require_POST
def agent_run_cancel(request: HttpRequest, public_id: str) -> HttpResponse:
    run = _scoped_agent_run(request.user, public_id)
    try:
        operator_cancel_agent_run(
            run=run,
            organization_id=run.organization_id,
            actor=request.user.get_username(),
        )
        messages.success(request, f"Agent run {run.public_id} cancelled.")
    except AgentRequestError as exc:
        messages.error(request, f"Cancel denied: {exc.code}")
    return redirect("console:agent_run_detail", public_id=str(run.public_id))


def _scoped_agent_run(user: UserLike, public_id: str) -> AgentRun:
    import uuid as _uuid

    try:
        parsed = _uuid.UUID(str(public_id))
    except ValueError as exc:
        raise Http404 from exc
    run = (
        AgentRun.objects.select_related("organization", "scenario", "consumer")
        .filter(public_id=parsed)
        .first()
    )
    if run is None:
        raise Http404
    if not _operator_can_access_org(user, run.organization_id):
        raise PermissionDenied
    return run


def _operator_can_access_org(user: UserLike, organization_id: int) -> bool:
    allowed = allowed_organization_ids(user)
    return allowed is None or organization_id in allowed


def _create(
    request: HttpRequest,
    *,
    form_class: type,
    title: str,
    resource_type: str,
    permission: Callable[[int | None], bool],
    success_url: str,
) -> HttpResponse:
    form = form_class(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        instance = form.save(commit=False)
        organization_id = getattr(instance, "organization_id", None)
        if resource_type == "project":
            organization_id = instance.organization_id
        elif resource_type == "scenario":
            organization_id = instance.project.organization_id
        elif resource_type == "binding":
            organization_id = instance.consumer.organization_id
        if not permission(organization_id):
            raise PermissionDenied
        with transaction.atomic():
            instance = form.save()
            if resource_type == "organization":
                organization_id = instance.pk
            if organization_id is None:
                raise PermissionDenied
            if resource_type == "scenario" and form.cleaned_data["alias"]:
                ScenarioAlias.objects.create(
                    organization_id=organization_id,
                    scenario=instance,
                    alias=form.cleaned_data["alias"],
                )
            _audit_create(request, resource_type, str(instance.pk), organization_id)
        return redirect(success_url)
    return render(request, "console/form.html", {"title": title, "form": form})


@login_required
def organization_create(request: HttpRequest) -> HttpResponse:
    if not can_create_organization(request.user):
        raise PermissionDenied
    return _create(
        request,
        form_class=OrganizationForm,
        title="New organization",
        resource_type="organization",
        permission=lambda _org_id: True,
        success_url="console:organizations",
    )


@login_required
def project_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=ProjectForm,
        title="New project",
        resource_type="project",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:projects",
    )


@login_required
def scenario_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=ScenarioForm,
        title="New scenario",
        resource_type="scenario",
        permission=lambda org_id: org_id is not None and can_author_scenarios(request.user, org_id),
        success_url="console:scenarios",
    )


@login_required
def consumer_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=ConsumerForm,
        title="New consumer",
        resource_type="consumer",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:consumers",
    )


@login_required
def binding_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=BindingForm,
        title="New consumer binding",
        resource_type="binding",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:consumers",
    )
