"""Operator console views (server-rendered, tenant-scoped, login required).

Authentication is handled by Django's auth backends — LDAP in production (ADR-0001)
or the local model backend when LDAP is disabled. Authorization scope for every
screen comes from :mod:`apps.console.scoping`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Count, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.module_loading import import_string
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from apps.agents.models import AgentRuntimeControl, RuntimeControlScope
from apps.agents.services import (
    RUNTIME_CONTROL_REASON_CODES,
    RuntimeControlError,
    applicable_runtime_controls,
    change_runtime_control,
)
from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.audit.services import record_event
from apps.builder import services as builder_services
from apps.builder.models import WorkflowDraft
from apps.builder.services import BuilderError
from apps.catalog.models import AIProject, Scenario
from apps.catalog.services import ProjectOwnerError, create_console_project, create_console_scenario
from apps.console import context as console_context
from apps.console import operations, scoping
from apps.console.forms import (
    APPLICATION_MEMBERSHIP_ROLE_CHOICES,
    BindingForm,
    CanaryForm,
    ConfluenceSourceForm,
    ConnectorScheduleForm,
    ConsumerForm,
    ConsumerTokenIssueForm,
    DelegatedAssignmentForm,
    DocumentReplacementForm,
    DocumentSetBuildForm,
    DocumentSetBulkUploadForm,
    DocumentSetForm,
    DocumentUploadForm,
    MembershipCreateForm,
    MembershipRoleForm,
    OrganizationForm,
    ProjectForm,
    RestContractForm,
    RestSourceForm,
    ScenarioForm,
)
from apps.documents import services as document_services
from apps.documents.models import (
    Document,
    DocumentLifecycle,
    DocumentSet,
    DocumentSetGrant,
    DocumentSetMembership,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    DocumentVersion,
    GrantPrincipalType,
    ParseStatus,
    ScenarioDocumentSetBinding,
)
from apps.documents.services import DocumentError, DocumentSetControlError
from apps.documents.storage import StorageError
from apps.evaluations.forms import (
    EvaluationTargetForm,
    OneOffQuestionForm,
    QuestionSetDraftForm,
)
from apps.evaluations.models import (
    QuestionEvaluationEvidenceStatus,
    QuestionEvaluationKind,
    QuestionEvaluationRun,
    QuestionEvaluationStatus,
    QuestionSet,
    QuestionSetVersion,
)
from apps.evaluations.question_services import (
    QuestionEvaluationError,
    ask_document_set_once,
    ask_scenario_once,
    can_manage_question_sets,
    can_read_question_sets,
    create_answer_evaluation,
    create_question_set,
    create_retrieval_evaluation,
    publish_question_set,
    request_evaluation_cancellation,
    update_question_set_draft,
)
from apps.evaluations.services import EvalError, run_eval
from apps.evaluations.tasks import execute_question_evaluation_task
from apps.identity.assignment_services import (
    AssignmentError,
    assign_document_set_manager,
    assign_project_administrator,
    assign_scenario_editor,
    remove_delegated_assignment,
)
from apps.identity.authorization import AuthoritySource
from apps.identity.authorization import Capability as OperatorCapability
from apps.identity.authorization import authorize as authorize_operator
from apps.identity.credentials import (
    ConsumerSubjectAllocationError,
    CredentialLifecycleError,
    create_console_consumer,
    issue_consumer_token,
    revoke_consumer_token,
    rotate_consumer_token,
)
from apps.identity.models import (
    BindingStatus,
    Consumer,
    ConsumerBinding,
    ConsumerStatus,
    DelegatedAssignmentStatus,
    DocumentSetManagerAssignment,
    ProjectAdministratorAssignment,
    ScenarioEditorAssignment,
)
from apps.ingestion.confluence_services import (
    ConfluenceAuthorizationError,
    ConfluenceServiceError,
    create_confluence_source,
    create_confluence_sync_run,
    mark_confluence_dispatch_failed,
)
from apps.ingestion.job_lifecycle import (
    BuildJobError,
    cancel_build_job,
    compatible_worker_available,
    create_build_job,
    retry_build_job,
)
from apps.ingestion.models import (
    ConfluenceSyncRun,
    ConnectorType,
    IndexStatus,
    IndexVersion,
    RestSyncRun,
    ScheduleAutomationMode,
    Source,
    StagedIndexBuildJob,
    StagedIndexBuildJobStatus,
)
from apps.ingestion.rest import RestPullError, preview_rest_response
from apps.ingestion.rest_schema import RestContractError, validate_contract
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    configure_sync_schedule,
    create_rest_contract,
    create_rest_source,
    create_rest_sync_run,
    mark_rest_dispatch_failed,
)
from apps.ingestion.staged_build import StagedBuildError, promote_staged_index
from apps.ingestion.tasks import sync_confluence_source, sync_rest_source
from apps.ingestion.vector_store import (
    VectorStoreError,
    chunk_counts_by_document,
    chunk_preview_for_document,
    exact_chunk_text,
    set_tenant_context,
)
from apps.observability.retention import RETENTION_DAYS, run_retention
from apps.orchestration.authoring_guide import workflow_authoring_guide
from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.releases.compiler import (
    ArtifactRef,
    CompileError,
    compile_release,
    role_accepts_artifact_type,
)
from apps.releases.lifecycle import LifecycleError, promote, rollback, start_canary, stop_canary
from apps.releases.models import CanaryStatus, ReleaseCanary, ReleaseStatus, ScenarioRelease
from apps.tenancy.identifiers import IdentifierAllocationError
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus
from apps.tenancy.services import (
    MembershipManagementError,
    UserLike,
    add_organization_membership,
    admin_organization_ids,
    allowed_organization_ids,
    can_admin_org,
    can_author_scenarios,
    can_create_organization,
    can_manage_document_set_operations,
    can_manage_documents,
    can_manage_scenario_releases,
    change_organization_membership,
    create_console_organization,
    is_platform_admin,
    remove_organization_membership,
)
from apps.tools.approvals import ToolApprovalError, cancel_invocation, decide_approval
from apps.tools.authz import resolve_actor_roles
from apps.tools.models import ApprovalRequest, ApprovalStatus, ToolInvocation
from apps.workflows.models import (
    RUN_TERMINAL_STATUSES,
    Run,
    RunStatus,
    RunWait,
    RunWaitKind,
    RunWaitStatus,
)
from apps.workflows.presets import (
    agent_loop_workflow,
    document_answer_workflow,
    empty_workflow,
)
from apps.workflows.run_recovery import RunRecoveryError, resolve_run_recovery
from apps.workflows.run_waits import RunWaitError, decide_run_human_task
from apps.workflows.tasks import dispatch_unified_background_run
from apps.workflows.transitions import (
    RunTransitionError,
    request_run_cancellation,
)

# Role-honest affordance reasons (Scope D). When an action the user cannot perform is
# rendered, it is shown disabled with one of these operator-facing reasons rather than
# hidden, so the required role is discoverable. These are UX copy only — the server still
# re-authorizes every action; a disabled control is never the access boundary.
_CREATE_ORG_REASON = "Organizasyon oluşturmak yalnızca platform yöneticisine açıktır."
_CREATE_PROJECT_REASON = (
    "Yeni proje oluşturmak için organizasyon yöneticisi (organization_admin) rolü gerekir."
)
_CREATE_SCENARIO_REASON = (
    "Yeni senaryo oluşturmak için senaryo düzenleyici (scenario_editor) veya üzeri bir rol gerekir."
)
_CREATE_CONSUMER_REASON = (
    "İstemci yönetimi için organizasyon yöneticisi (organization_admin) rolü gerekir."
)
_AUTHOR_REASON = (
    "Bu işlem için senaryo düzenleyici (scenario_editor) veya üzeri bir yazma rolü gerekir."
)
_RELEASE_AUTHORITY_REASON = (
    "Bu işlem için Global Administrator veya organizasyon yöneticisi yetkisi gerekir."
)
_ADMIN_REASON = "Bu işlem için organizasyon yöneticisi (organization_admin) rolü gerekir."

# --- Dashboard run-status buckets (Scope C/H) --------------------------------
# Persisted statuses grouped into operator-facing buckets. Deep-links to the filtered
# run lists (Scope H) use the same bucket names via the ``?bucket=`` query param.
_RUN_ACTIVE_STATUSES = (
    RunStatus.REQUESTED,
    RunStatus.QUEUED,
    RunStatus.RUNNING,
    RunStatus.WAITING_APPROVAL,
    RunStatus.WAITING_EVENT,
    RunStatus.WAITING_HUMAN,
    RunStatus.WAITING_TIMER,
    RunStatus.WAITING_CHILD,
)
_RUN_ATTENTION_STATUSES = (
    RunStatus.FAILED,
    RunStatus.TIMED_OUT,
    RunStatus.RECOVERY_REQUIRED,
)
_RUN_DONE_STATUSES = (RunStatus.COMPLETED, RunStatus.CANCELLED)
# Bucket -> the concrete statuses it deep-links to on the run-monitoring screens (Scope H).
RUN_BUCKETS: dict[str, tuple[str, ...]] = {
    "active": tuple(str(s) for s in _RUN_ACTIVE_STATUSES),
    "attention": tuple(str(s) for s in _RUN_ATTENTION_STATUSES),
    "done": tuple(str(s) for s in _RUN_DONE_STATUSES),
}
# How far back "completed" and "recent failures" look on the dashboard.
_DASHBOARD_RECENT_HOURS = 24

_UPLOAD_MIME_BY_SUFFIX = {
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".json": "application/json",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_TURKISH_SLUG_TRANSLATION = str.maketrans(
    {
        "ç": "c",
        "Ç": "C",
        "ğ": "g",
        "Ğ": "G",
        "ı": "i",
        "İ": "I",
        "ö": "o",
        "Ö": "O",
        "ş": "s",
        "Ş": "S",
        "ü": "u",
        "Ü": "U",
    }
)
_REST_CONTRACT_EXAMPLE = {
    "version": 1,
    "inputs": {"space": {"type": "string", "max_length": 64}},
    "request": {
        "method": "GET",
        "path": "/documents/{input:space}",
        "query": {},
    },
    "response": {
        "items_pointer": "/data/items",
        "id_pointer": "/id",
        "revision_pointer": "/revision",
        "title_pointer": "/title",
        "content_pointer": "/content",
        "content_encoding": "utf8_text",
        "mime_type": "text/markdown",
    },
    "pagination": {"mode": "none"},
}


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


def _request_id(request: HttpRequest) -> str:
    return str(getattr(request, "request_id", ""))[:64]


def _trace_id(request: HttpRequest) -> str:
    return str(getattr(request, "trace_id", ""))[:64]


def _authorize_consumer_credentials(request: HttpRequest, consumer: Consumer, action: str) -> None:
    if can_admin_org(request.user, consumer.organization_id):
        return
    record_event(
        actor_type="user",
        actor_id=request.user.get_username(),
        action=action,
        outcome="deny",
        organization_id=consumer.organization_id,
        resource_type="consumer",
        resource_id=str(consumer.pk),
        reason="CREDENTIAL_ADMIN_REQUIRED_OR_ORGANIZATION_INACTIVE",
        request_id=_request_id(request),
        trace_id=_trace_id(request),
    )
    raise PermissionDenied


def _audit_credential_failure(
    request: HttpRequest, consumer: Consumer, action: str, reason: str
) -> None:
    record_event(
        actor_type="user",
        actor_id=request.user.get_username(),
        action=action,
        outcome="failure",
        organization_id=consumer.organization_id,
        resource_type="consumer",
        resource_id=str(consumer.pk),
        reason=reason,
        request_id=_request_id(request),
        trace_id=_trace_id(request),
    )


@sensitive_variables("raw_token")
def _token_reveal_response(
    request: HttpRequest,
    *,
    consumer: Consumer,
    raw_token: str,
    token_name: str,
    action_label: str,
) -> HttpResponse:
    response = render(
        request,
        "console/consumer_token_reveal.html",
        {
            "consumer": consumer,
            "raw_token": raw_token,
            "token_name": token_name,
            "action_label": action_label,
        },
    )
    response["Cache-Control"] = "no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _safe_redirect_target(request: HttpRequest, *, default: str) -> str:
    """Return a same-origin ``next`` target or the named ``default`` (open-redirect safe)."""
    nxt = request.POST.get("next", "") or request.GET.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return default


@login_required
@require_POST
def switch_organization(request: HttpRequest) -> HttpResponse:
    """Set the session's active organization (a display filter, not authorization).

    Membership is the authorization boundary: blank and non-member ids are rejected with
    403 (no existence signal). The active
    organization only ever narrows an already-tenant-scoped list.
    """
    raw = request.POST.get("organization_id", "").strip()
    if raw == "":
        raise PermissionDenied
    try:
        org_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise PermissionDenied from exc
    if scoping.scoped_organizations(request.user).filter(pk=org_id).first() is None:
        raise PermissionDenied
    request.session[console_context.SESSION_KEY] = org_id
    return redirect(_safe_redirect_target(request, default="console:dashboard"))


def _kill_switch_state(active_organization: Organization | None) -> dict[str, object] | None:
    """Return the strongest effective platform/organization control for the dashboard."""
    if active_organization is not None:
        controls = applicable_runtime_controls(active_organization.pk)
        control = controls[0] if controls else None
    else:
        control = AgentRuntimeControl.objects.filter(
            scope_type=RuntimeControlScope.PLATFORM,
            suspended=True,
        ).first()
    if control is None:
        return None
    return {
        "scope": control.scope_type,
        "reason": control.reason or "",
    }


def _dashboard_metrics(
    user: UserLike, active_organization: Organization | None
) -> dict[str, object]:
    """Bounded operational snapshot for the landing dashboard (counts only, no N+1).

    Everything is derived from the already-tenant-scoped console querysets and narrowed to
    the active organization when one is selected; codes/counts only, no payloads.
    """
    cutoff = timezone.now() - timedelta(hours=_DASHBOARD_RECENT_HOURS)
    operations_cutoff = timezone.now() - timedelta(days=operations.MAX_DAYS)
    allowed = allowed_organization_ids(user)

    def _org_scope(queryset: QuerySet[Any], *, field: str = "organization_id") -> QuerySet[Any]:
        qs = queryset if allowed is None else queryset.filter(**{f"{field}__in": allowed})
        return scoping.narrow_to_active_organization(qs, active_organization, field=field)

    unified_runs = scoping.narrow_to_active_organization(
        scoping.scoped_runs(user), active_organization, field="organization_id"
    )
    run_agg = unified_runs.aggregate(
        active=Count(
            "id",
            filter=Q(
                status__in=_RUN_ACTIVE_STATUSES,
                created_at__gte=operations_cutoff,
            ),
        ),
        attention=Count(
            "id",
            filter=Q(
                status__in=_RUN_ATTENTION_STATUSES,
                created_at__gte=operations_cutoff,
            ),
        ),
        done=Count("id", filter=Q(status__in=_RUN_DONE_STATUSES, created_at__gte=cutoff)),
    )
    runs = {
        "active": run_agg["active"],
        "attention": run_agg["attention"],
        "done": run_agg["done"],
        "agent_active": 0,
        "workflow_active": run_agg["active"],
    }

    # Pending human decisions (only surfaces are counted; each list view re-authorizes).
    approvals = _org_scope(ApprovalRequest.objects.filter(status=ApprovalStatus.PENDING)).count()
    human_tasks = _org_scope(
        RunWait.objects.filter(kind=RunWaitKind.HUMAN, status=RunWaitStatus.PENDING)
    ).count()
    recoveries = unified_runs.filter(status=RunStatus.RECOVERY_REQUIRED).count()

    # Serving / index health.
    scenarios_qs = scoping.narrow_to_active_organization(
        scoping.scoped_scenarios(user), active_organization, field="project__organization_id"
    )
    no_active_release_qs = scenarios_qs.exclude(
        id__in=ScenarioRelease.objects.filter(status=ReleaseStatus.ACTIVE).values("scenario_id")
    )
    no_active_release = no_active_release_qs.count()
    promotable_indexes_qs = _org_scope(IndexVersion.objects.filter(status=IndexStatus.PROMOTABLE))
    promotable_indexes = promotable_indexes_qs.count()
    failed_builds_qs = _org_scope(
        StagedIndexBuildJob.objects.filter(
            status__in=[
                StagedIndexBuildJobStatus.FAILED,
                StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED,
            ]
        )
    )
    failed_builds = failed_builds_qs.count()
    active_canaries_qs = _org_scope(
        ReleaseCanary.objects.filter(status=CanaryStatus.ACTIVE),
        field="scenario__project__organization_id",
    )
    active_canaries = active_canaries_qs.count()

    return {
        "runs": runs,
        "decisions": {
            "approvals": approvals,
            "human_tasks": human_tasks,
            "recoveries": recoveries,
            "total": approvals + human_tasks + recoveries,
        },
        "health": {
            "no_active_release": no_active_release,
            "promotable_indexes": promotable_indexes,
            "failed_builds": failed_builds,
            "active_canaries": active_canaries,
        },
        "recent_hours": _DASHBOARD_RECENT_HOURS,
        "operations_days": operations.MAX_DAYS,
    }


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    user = request.user
    active_org = console_context.resolve_active_organization(request)
    organizations_qs = scoping.scoped_organizations(user).order_by("name", "slug")
    context = {
        "is_platform_admin": is_platform_admin(user),
        "active_organization": active_org,
        "organizations": organizations_qs[:50],
        "metrics": _dashboard_metrics(user, active_org),
        "kill_switch": _kill_switch_state(active_org),
        "counts": {
            "organizations": organizations_qs.count(),
            "projects": scoping.narrow_to_active_organization(
                scoping.scoped_projects(user), active_org, field="organization_id"
            ).count(),
            "scenarios": scoping.narrow_to_active_organization(
                scoping.scoped_scenarios(user), active_org, field="project__organization_id"
            ).count(),
            "document_sets": scoping.narrow_to_active_organization(
                scoping.scoped_document_sets(user), active_org, field="organization_id"
            ).count(),
            "consumers": scoping.narrow_to_active_organization(
                scoping.scoped_consumers(user), active_org, field="organization_id"
            ).count(),
            "releases": scoping.narrow_to_active_organization(
                scoping.scoped_releases(user),
                active_org,
                field="scenario__project__organization_id",
            ).count(),
        },
    }
    return render(request, "console/dashboard.html", context)


@login_required
@require_GET
def health_issues(request: HttpRequest, category: str) -> HttpResponse:
    """List the exact tenant-scoped objects represented by a dashboard health KPI."""
    active_org = console_context.resolve_active_organization(request)
    scenarios_qs = scoping.narrow_to_active_organization(
        scoping.scoped_scenarios(request.user).select_related("project__organization"),
        active_org,
        field="project__organization_id",
    )
    document_sets_qs = scoping.narrow_to_active_organization(
        scoping.scoped_document_sets(request.user).select_related("organization"),
        active_org,
        field="organization_id",
    )

    if category == "no-active-release":
        scenarios = list(
            scenarios_qs.exclude(
                id__in=ScenarioRelease.objects.filter(status=ReleaseStatus.ACTIVE).values(
                    "scenario_id"
                )
            ).order_by("project__name", "name")[:201]
        )
        title = "Aktif release'i olmayan senaryolar"
        headers = ["Senaryo", "Proje", "Organizasyon", "Durum"]
        rows = [
            {
                "href": reverse("console:scenario_detail_public", args=[scenario.public_id]),
                "cols": [
                    {
                        "text": scenario.name,
                        "url": "console:scenario_detail_public",
                        "arg": scenario.public_id,
                    },
                    scenario.project.name,
                    scenario.project.organization.name,
                    scenario.status,
                ],
            }
            for scenario in scenarios
        ]
    elif category == "active-canary":
        canaries = list(
            ReleaseCanary.objects.filter(scenario__in=scenarios_qs, status=CanaryStatus.ACTIVE)
            .select_related("scenario__project__organization", "release")
            .order_by("expires_at", "pk")[:201]
        )
        title = "Aktif canary'ler"
        headers = ["Senaryo", "Proje", "Organizasyon", "Release", "Bitiş"]
        rows = [
            {
                "href": reverse("console:scenario_detail_public", args=[canary.scenario.public_id]),
                "cols": [
                    {
                        "text": canary.scenario.name,
                        "url": "console:scenario_detail_public",
                        "arg": canary.scenario.public_id,
                    },
                    canary.scenario.project.name,
                    canary.scenario.project.organization.name,
                    f"#{canary.release_id}",
                    canary.expires_at,
                ],
            }
            for canary in canaries
        ]
    elif category == "promotable-index":
        indexes = list(
            IndexVersion.objects.filter(
                document_set_version__document_set__in=document_sets_qs,
                status=IndexStatus.PROMOTABLE,
            )
            .select_related("document_set_version__document_set__organization")
            .order_by("document_set_version__document_set__name", "version")[:201]
        )
        title = "Aktive edilmeyi bekleyen indeksler"
        headers = ["Doküman seti", "Organizasyon", "Set sürümü", "İndeks"]
        rows = []
        for index in indexes:
            set_version = index.document_set_version
            if set_version is None:
                continue
            document_set = set_version.document_set
            rows.append(
                {
                    "href": reverse(
                        "console:document_set_detail_public",
                        args=[document_set.public_id],
                    ),
                    "cols": [
                        {
                            "text": document_set.name,
                            "url": "console:document_set_detail_public",
                            "arg": document_set.public_id,
                        },
                        document_set.organization.name,
                        f"v{set_version.version}",
                        f"v{index.version}",
                    ],
                }
            )
    elif category == "failed-index-build":
        jobs = list(
            StagedIndexBuildJob.objects.filter(
                document_set_version__document_set__in=document_sets_qs,
                status__in=[
                    StagedIndexBuildJobStatus.FAILED,
                    StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED,
                ],
            )
            .select_related("document_set_version__document_set__organization")
            .order_by("-updated_at", "-pk")[:201]
        )
        title = "Başarısız indeks işleri"
        headers = ["Doküman seti", "Organizasyon", "Durum", "Hata kodu"]
        rows = [
            {
                "href": reverse(
                    "console:document_set_detail_public",
                    args=[job.document_set_version.document_set.public_id],
                ),
                "cols": [
                    {
                        "text": job.document_set_version.document_set.name,
                        "url": "console:document_set_detail_public",
                        "arg": job.document_set_version.document_set.public_id,
                    },
                    job.document_set_version.document_set.organization.name,
                    job.status,
                    job.error_code or "—",
                ],
            }
            for job in jobs
        ]
    else:
        raise Http404

    return render(
        request,
        "console/list.html",
        {
            "title": title,
            "description": "Ana Sayfa sağlık göstergesinin kapsamındaki kesin kayıtlar.",
            "headers": headers,
            "rows": rows[:200],
            "rows_limited": len(rows) > 200,
        },
    )


def _scoped_organization(user: UserLike, slug: str) -> Organization:
    try:
        organization = scoping.scoped_organizations(user).get(slug=slug)
    except Organization.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(organization.pk)
    return organization


@login_required
@require_GET
def organization_detail(request: HttpRequest, slug: str) -> HttpResponse:
    organization = _scoped_organization(request.user, slug)
    request.session[console_context.SESSION_KEY] = organization.pk
    return redirect("console:dashboard")


@login_required
@require_GET
def organizations(request: HttpRequest) -> HttpResponse:
    console_context.resolve_active_organization(request)
    return redirect("console:dashboard")


def _managed_active_organization(request: HttpRequest) -> Organization:
    organization = console_context.resolve_active_organization(request)
    if organization is None:
        raise PermissionDenied
    if not can_admin_org(request.user, organization.pk):
        record_event(
            actor_type="user",
            actor_id=request.user.get_username(),
            action="organization_membership.manage",
            outcome="deny",
            organization_id=organization.pk,
            resource_type="organization",
            resource_id=str(organization.pk),
            reason="ADMIN_REQUIRED_OR_ORGANIZATION_INACTIVE",
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
        raise PermissionDenied
    return organization


def _audit_membership_failure(
    request: HttpRequest, organization_id: int, membership_id: int | None, code: str
) -> None:
    record_event(
        actor_type="user",
        actor_id=request.user.get_username(),
        action="organization_membership.manage",
        outcome="failure",
        organization_id=organization_id,
        resource_type="organization_membership",
        resource_id=str(membership_id or ""),
        reason=code,
        request_id=_request_id(request),
        trace_id=_trace_id(request),
    )


@login_required
@require_GET
def organization_members(request: HttpRequest) -> HttpResponse:
    organization = _managed_active_organization(request)
    memberships = list(
        OrganizationMembership.objects.filter(organization=organization)
        .select_related("user")
        .order_by("user__username", "pk")[:201]
    )
    visible_memberships = memberships[:200]
    # Revoked rows are retained for lineage but carry no authority, so the operator view and its
    # delegation counts must show active assignments only.
    project_assignments = list(
        ProjectAdministratorAssignment.objects.filter(
            organization=organization,
            status=DelegatedAssignmentStatus.ACTIVE,
        )
        .select_related("user", "project")
        .order_by("user__username", "project__name", "pk")[:201]
    )
    scenario_assignments = list(
        ScenarioEditorAssignment.objects.filter(
            organization=organization,
            status=DelegatedAssignmentStatus.ACTIVE,
        )
        .select_related("user", "scenario__project")
        .order_by("user__username", "scenario__name", "pk")[:201]
    )
    document_set_assignments = list(
        DocumentSetManagerAssignment.objects.filter(
            organization=organization,
            status=DelegatedAssignmentStatus.ACTIVE,
        )
        .select_related("user", "document_set")
        .order_by("user__username", "document_set__name", "pk")[:201]
    )
    delegated_counts: dict[int, dict[str, int]] = {
        membership.user_id: {"projects": 0, "scenarios": 0, "document_sets": 0}
        for membership in visible_memberships
    }
    for project_assignment in project_assignments:
        delegated_counts.setdefault(
            project_assignment.user_id,
            {"projects": 0, "scenarios": 0, "document_sets": 0},
        )["projects"] += 1
    for scenario_assignment in scenario_assignments:
        delegated_counts.setdefault(
            scenario_assignment.user_id,
            {"projects": 0, "scenarios": 0, "document_sets": 0},
        )["scenarios"] += 1
    for document_set_assignment in document_set_assignments:
        delegated_counts.setdefault(
            document_set_assignment.user_id,
            {"projects": 0, "scenarios": 0, "document_sets": 0},
        )["document_sets"] += 1
    for membership in visible_memberships:
        cast(Any, membership).delegated_counts = delegated_counts[membership.user_id]
    return render(
        request,
        "console/organization_members.html",
        {
            "organization": organization,
            "memberships": visible_memberships,
            "memberships_limited": len(memberships) > 200,
            "add_form": MembershipCreateForm(organization=organization),
            "assignment_form": DelegatedAssignmentForm(organization=organization),
            "role_choices": APPLICATION_MEMBERSHIP_ROLE_CHOICES,
            "project_assignments": project_assignments[:200],
            "scenario_assignments": scenario_assignments[:200],
            "document_set_assignments": document_set_assignments[:200],
            "assignments_limited": any(
                len(assignments) > 200
                for assignments in (
                    project_assignments,
                    scenario_assignments,
                    document_set_assignments,
                )
            ),
        },
    )


@login_required
@require_POST
def organization_member_add(request: HttpRequest) -> HttpResponse:
    organization = _managed_active_organization(request)
    form = MembershipCreateForm(request.POST, organization=organization)
    if not form.is_valid():
        messages.error(request, "Üyelik eklenemedi: kullanıcı veya rol geçersiz.")
    else:
        try:
            add_organization_membership(
                organization=organization,
                user=form.cleaned_data["user"],
                role=form.cleaned_data["role"],
                actor=request.user,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
            )
            messages.success(request, "Üyelik eklendi.")
        except MembershipManagementError as exc:
            _audit_membership_failure(request, organization.pk, None, exc.code)
            messages.error(request, f"Üyelik eklenemedi: {exc.code}")
    return redirect("console:organization_members")


def _managed_membership(request: HttpRequest, membership_id: int) -> OrganizationMembership:
    organization = _managed_active_organization(request)
    membership = OrganizationMembership.objects.filter(
        pk=membership_id, organization=organization
    ).first()
    if membership is None:
        raise Http404
    return membership


@login_required
@require_POST
def organization_member_role(request: HttpRequest, membership_id: int) -> HttpResponse:
    membership = _managed_membership(request, membership_id)
    form = MembershipRoleForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Rol değiştirilemedi: rol geçersiz.")
    else:
        try:
            change_organization_membership(
                membership=membership,
                role=form.cleaned_data["role"],
                actor=request.user,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
            )
            messages.success(request, "Rol güncellendi.")
        except MembershipManagementError as exc:
            _audit_membership_failure(request, membership.organization_id, membership.pk, exc.code)
            messages.error(request, f"Rol değiştirilemedi: {exc.code}")
    return redirect("console:organization_members")


@login_required
@require_POST
def organization_member_remove(request: HttpRequest, membership_id: int) -> HttpResponse:
    membership = _managed_membership(request, membership_id)
    try:
        remove_organization_membership(
            membership=membership,
            actor=request.user,
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
        messages.success(request, "Üyelik kaldırıldı.")
    except MembershipManagementError as exc:
        _audit_membership_failure(request, membership.organization_id, membership.pk, exc.code)
        messages.error(request, f"Üyelik kaldırılamadı: {exc.code}")
    return redirect("console:organization_members")


@login_required
@require_POST
def delegated_assignment_add(request: HttpRequest) -> HttpResponse:
    organization = _managed_active_organization(request)
    form = DelegatedAssignmentForm(request.POST, organization=organization)
    if not form.is_valid():
        messages.error(request, "Sorumluluk atanamadı: üye veya hedef geçersiz.")
        return redirect("console:organization_members")

    membership = form.cleaned_data["member"]
    responsibility = form.cleaned_data["responsibility"]
    common = {
        "target_user": membership.user,
        "actor": request.user,
        "request_id": _request_id(request),
        "trace_id": _trace_id(request),
    }
    try:
        if responsibility == DelegatedAssignmentForm.PROJECT_ADMINISTRATOR:
            assign_project_administrator(project=form.cleaned_data["target"], **common)
        elif responsibility == DelegatedAssignmentForm.SCENARIO_EDITOR:
            assign_scenario_editor(scenario=form.cleaned_data["target"], **common)
        else:
            assign_document_set_manager(document_set=form.cleaned_data["target"], **common)
        messages.success(request, "Sorumluluk atandı.")
    except AssignmentError as exc:
        messages.error(request, f"Sorumluluk atanamadı: {exc.code}")
    return redirect("console:organization_members")


@login_required
@require_POST
def delegated_assignment_remove(
    request: HttpRequest, assignment_type: str, assignment_id: int
) -> HttpResponse:
    organization = _managed_active_organization(request)
    model: Any = {
        DelegatedAssignmentForm.PROJECT_ADMINISTRATOR: ProjectAdministratorAssignment,
        DelegatedAssignmentForm.SCENARIO_EDITOR: ScenarioEditorAssignment,
        DelegatedAssignmentForm.DOCUMENT_SET_MANAGER: DocumentSetManagerAssignment,
    }.get(assignment_type)
    if model is None:
        raise Http404
    assignment = (
        model.objects.filter(
            pk=assignment_id,
            organization=organization,
            status=DelegatedAssignmentStatus.ACTIVE,
        )
        .select_related("user")
        .first()
    )
    if assignment is None:
        raise Http404
    try:
        remove_delegated_assignment(
            assignment=assignment,
            actor=request.user,
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
        messages.success(request, "Sorumluluk kaldırıldı.")
    except AssignmentError as exc:
        messages.error(request, f"Sorumluluk kaldırılamadı: {exc.code}")
    return redirect("console:organization_members")


@login_required
def projects(request: HttpRequest) -> HttpResponse:
    active_org = console_context.resolve_active_organization(request)
    can_create_project = active_org is not None and can_admin_org(request.user, active_org.pk)
    projects_qs = scoping.narrow_to_active_organization(
        scoping.scoped_projects(request.user), active_org, field="organization_id"
    )
    rows = [
        {
            "href": reverse("console:project_detail_public", args=[p.public_id]),
            "cols": [
                {"text": p.name, "url": "console:project_detail_public", "arg": p.public_id},
                p.organization.name,
                p.slug,
                p.risk_level,
                p.status,
            ],
        }
        for p in projects_qs
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Projeler",
            "description": "Senaryolar projeler içinde hazırlanır ve yönetilir.",
            "headers": ["Proje", "Organizasyon", "Slug", "Risk", "Durum"],
            "rows": rows,
            "create_links": [
                {
                    "url": "console:project_create",
                    "label": "Yeni proje",
                    "disabled": not can_create_project,
                    "reason": _CREATE_PROJECT_REASON,
                }
            ],
        },
    )


def _scoped_project(user: UserLike, pk: int | None = None, public_id: object = None) -> AIProject:
    try:
        project = scoping.scoped_projects(user).get(
            **({"public_id": public_id} if public_id is not None else {"pk": pk})
        )
    except AIProject.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(project.organization_id)
    return project


@login_required
def project_detail(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    project = _scoped_project(request.user, pk, public_id)
    request.session[console_context.SESSION_KEY] = project.organization_id
    scenarios_qs = Scenario.objects.filter(project=project).order_by("name", "slug")
    scenario_candidates = list(scenarios_qs[:201])
    return render(
        request,
        "console/project_detail.html",
        {
            "project": project,
            "organization": project.organization,
            "scenarios": scenario_candidates[:200],
            "scenarios_limited": len(scenario_candidates) > 200,
            "is_disabled": project.organization.status == OrganizationStatus.DISABLED,
            "can_create_scenario": project.organization.status == OrganizationStatus.ACTIVE
            and can_author_scenarios(request.user, project.organization_id),
            "create_scenario_reason": _CREATE_SCENARIO_REASON,
            "administrator_assignments": project.administrator_assignments.filter(
                status=DelegatedAssignmentStatus.ACTIVE
            )
            .select_related("user")
            .order_by("user__username", "user_id"),
            "can_manage_access": can_admin_org(request.user, project.organization_id),
        },
    )


@login_required
@require_GET
def scenarios(request: HttpRequest) -> HttpResponse:
    console_context.resolve_active_organization(request)
    return redirect("console:projects")


def _scoped_scenario(user: UserLike, pk: int | None = None, public_id: object = None) -> Scenario:
    try:
        scenario = scoping.scoped_scenarios(user).get(
            **({"public_id": public_id} if public_id is not None else {"pk": pk})
        )
    except Scenario.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(scenario.organization_id)
    return scenario


def _release_artifact_rows(release: ScenarioRelease) -> list[dict[str, object]]:
    """Resolve untrusted manifest refs to exact artifacts inside the scenario tenant."""
    manifest = release.manifest
    if not isinstance(manifest, dict):
        return []
    raw_artifacts = manifest.get("artifacts", {})
    if not isinstance(raw_artifacts, dict) or len(raw_artifacts) > 100:
        return []
    organization_id = release.scenario.project.organization_id
    prepared: list[tuple[str, str, str, object, tuple[str, str, int] | None]] = []
    exact_keys: set[tuple[str, str, int]] = set()
    for role, raw_entry in sorted(raw_artifacts.items(), key=lambda item: str(item[0])):
        if not isinstance(role, str) or len(role) > 128 or not isinstance(raw_entry, dict):
            continue
        artifact_type = raw_entry.get("type")
        ref = raw_entry.get("ref")
        manifest_checksum = raw_entry.get("checksum")
        exact_key: tuple[str, str, int] | None = None
        if (
            isinstance(artifact_type, str)
            and isinstance(ref, str)
            and len(artifact_type) <= 32
            and len(ref) <= 260
            and ":v" in ref
        ):
            logical_id, _, version_text = ref.rpartition(":v")
            if (
                logical_id
                and version_text.isdigit()
                and len(version_text) <= 10
                and 0 < int(version_text) <= 2_147_483_647
            ):
                exact_key = (artifact_type, logical_id, int(version_text))
                exact_keys.add(exact_key)
        prepared.append(
            (
                role,
                artifact_type
                if isinstance(artifact_type, str) and len(artifact_type) <= 32
                else "geçersiz",
                ref if isinstance(ref, str) and len(ref) <= 260 else "geçersiz",
                manifest_checksum,
                exact_key,
            )
        )
    resolved = {
        (artifact.type, artifact.logical_id, artifact.version): artifact
        for artifact in ArtifactVersion.objects.filter(
            organization_id=organization_id,
            type__in={key[0] for key in exact_keys},
            logical_id__in={key[1] for key in exact_keys},
            version__in={key[2] for key in exact_keys},
        )
    }
    rows: list[dict[str, object]] = []
    for role, artifact_type, ref, manifest_checksum, exact_key in prepared:
        artifact = resolved.get(exact_key) if exact_key is not None else None
        rows.append(
            {
                "role": role,
                "type": artifact_type,
                "ref": ref,
                "artifact": artifact,
                "checksum_matches": (
                    artifact is not None
                    and isinstance(manifest_checksum, str)
                    and artifact.checksum == manifest_checksum
                ),
            }
        )
    return rows


def _workflow_dsl_guide() -> str:
    return workflow_authoring_guide()


def _scenario_preset_body(preset: str, *, logical_id: str) -> dict[str, Any]:
    if preset == "empty_workflow":
        return empty_workflow(logical_id=logical_id)
    if preset == "document_answer":
        return document_answer_workflow(logical_id=logical_id)
    if preset == "agent_loop":
        return agent_loop_workflow(
            logical_id=logical_id,
            policy={
                "tool_binding_roles": [],
                "retrieval": {"enabled": True},
                "limits": {"max_steps": 4, "max_tool_calls": 0},
            },
        )
    raise ValueError("unknown scenario preset")


def _invocation_guidance(
    active_release: ScenarioRelease | None, alias: str | None
) -> dict[str, object]:
    if active_release is None or not alias:
        return {"ready": False, "examples": []}
    analysis = active_release.manifest.get("execution_mode_analysis", {})
    raw_modes = analysis.get("supported_execution_modes", []) if isinstance(analysis, dict) else []
    modes = {mode for mode in raw_modes if mode in {"sync", "background"}}
    examples: list[dict[str, str]] = []
    if "sync" in modes:
        examples.append(
            {
                "label": "Senkron Chat Completions",
                "description": "Derlenen workflow senkron çalışmayı destekliyor.",
                "command": (
                    'curl -sS -X POST "$AGENTHUB_BASE_URL/v1/chat/completions" '
                    '-H "Authorization: Bearer $AGENTHUB_TOKEN" '
                    '-H "Content-Type: application/json" '
                    f'-d \'{{"model":"{alias}","messages":[{{"role":"user",'
                    '"content":"Merhaba"}}]}\''
                ),
            }
        )
    if "background" in modes:
        examples.append(
            {
                "label": "Responses background",
                "description": (
                    "Arka plan çalışması bir response kimliği ve X-AgentHub-Run-Id döndürür."
                ),
                "command": (
                    'curl -sS -X POST "$AGENTHUB_BASE_URL/v1/responses" '
                    '-H "Authorization: Bearer $AGENTHUB_TOKEN" '
                    '-H "Content-Type: application/json" '
                    '-H "Idempotency-Key: replace-with-unique-key" '
                    f'-d \'{{"model":"{alias}","input":"Merhaba","background":true}}\''
                ),
            }
        )
    return {"ready": bool(examples), "examples": examples, "modes": sorted(modes)}


def _ai_authoring_preflight() -> dict[str, object]:
    profile_id = str(getattr(settings, "AI_AUTHORING_MODEL_PROFILE_ID", "")).strip()
    if not profile_id:
        return {
            "available": False,
            "message": (
                "AI authoring kapalı: deployment yöneticisi onaylı immutable model profile ID "
                "ve provider yapılandırmalıdır."
            ),
        }
    try:
        parsed_profile_id = uuid.UUID(profile_id)
    except ValueError:
        return {
            "available": False,
            "message": "AI authoring model profile ayarı geçersiz; deployment ayarını doğrulayın.",
        }
    if not ModelProfile.objects.filter(
        public_id=parsed_profile_id, status=ModelProfileStatus.ACTIVE
    ).exists():
        return {
            "available": False,
            "message": "Yapılandırılan AI authoring model profili aktif veya erişilebilir değil.",
        }
    provider_path = str(getattr(settings, "AI_AUTHORING_PROVIDER", "")).strip()
    if provider_path:
        try:
            import_string(provider_path)
        except ImportError:
            return {
                "available": False,
                "message": "AI authoring provider yüklenemedi; deployment ayarını doğrulayın.",
            }
    return {
        "available": True,
        "message": "AI authoring hazır; çıktı geçici adaydır ve açık kabul olmadan kaydedilmez.",
    }


@login_required
def scenario_detail(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk, public_id)
    request.session[console_context.SESSION_KEY] = scenario.organization_id
    organization_id = scenario.project.organization_id
    active_release = ScenarioRelease.objects.filter(
        scenario=scenario, status=ReleaseStatus.ACTIVE
    ).first()
    aliases = list(scenario.aliases.order_by("alias"))
    raw_pinned_version_ids = (
        active_release.manifest.get("document_set_versions", []) if active_release else []
    )
    pinned_version_ids = {
        value
        for value in raw_pinned_version_ids
        if isinstance(value, int) and not isinstance(value, bool)
    }
    consumer_bindings = list(
        ConsumerBinding.objects.select_related("consumer")
        .filter(scenario=scenario)
        .order_by("consumer__name", "consumer__subject")
    )
    active_consumer_bindings = [
        binding
        for binding in consumer_bindings
        if binding.status == BindingStatus.ACTIVE
        and binding.consumer.status == ConsumerStatus.ACTIVE
    ]
    active_consumer_ids = {binding.consumer_id for binding in active_consumer_bindings}
    bindings = list(
        ScenarioDocumentSetBinding.objects.select_related("document_set")
        .filter(scenario=scenario, organization_id=organization_id)
        .order_by("document_set__name", "document_set__logical_id")
    )
    relationship_rows = []
    for binding in bindings:
        document_set = binding.document_set
        latest_published_version = (
            document_set.versions.select_related("built_index_version")
            .filter(
                status__in=[
                    DocumentSetVersionStatus.PROMOTABLE,
                    DocumentSetVersionStatus.ACTIVE,
                ]
            )
            .order_by("-version")
            .first()
        )
        release_version = (
            document_set.versions.select_related("built_index_version")
            .filter(id__in=pinned_version_ids)
            .first()
        )
        grants = list(
            document_set.grants.filter(principal_type=GrantPrincipalType.CONSUMER).order_by(
                "principal_ref"
            )
        )
        grants_by_consumer_id = {
            int(grant.principal_ref): grant for grant in grants if grant.principal_ref.isdigit()
        }
        relationship_rows.append(
            {
                "binding": binding,
                "document_set": document_set,
                "latest_version": latest_published_version,
                "release_version": release_version,
                "index": release_version.built_index_version if release_version else None,
                "scenario_count": document_set.scenario_bindings.count(),
                "consumer_rows": [
                    {
                        "binding": consumer_binding,
                        "grant": grants_by_consumer_id.get(consumer_binding.consumer_id),
                    }
                    for consumer_binding in active_consumer_bindings
                ],
                "other_grants": [
                    grant
                    for grant in grants
                    if not grant.principal_ref.isdigit()
                    or int(grant.principal_ref) not in active_consumer_ids
                ],
            }
        )
    bound_set_ids = {binding.document_set_id for binding in bindings}
    project_drafts = list(
        WorkflowDraft.objects.filter(
            organization_id=organization_id, project=scenario.project, scenario=scenario
        ).order_by("-updated_at")[:50]
    )
    drafts_by_logical_id = {draft.logical_id: draft for draft in project_drafts}
    active_artifacts = _release_artifact_rows(active_release) if active_release else []
    for row in active_artifacts:
        artifact = row["artifact"]
        row["workflow_draft"] = (
            drafts_by_logical_id.get(artifact.logical_id)
            if isinstance(artifact, ArtifactVersion) and artifact.type == "workflow_definition"
            else None
        )
    release_rows = [
        {
            "release": release,
            "artifacts": _release_artifact_rows(release),
        }
        for release in ScenarioRelease.objects.filter(scenario=scenario).order_by(
            "-created_at", "-pk"
        )[:20]
    ]
    return render(
        request,
        "console/scenario_detail.html",
        {
            "title": scenario.name,
            "scenario": scenario,
            "aliases": aliases,
            "active_release": active_release,
            "active_artifacts": active_artifacts,
            "has_output_contract": any(
                row["role"] == "output_contract" for row in active_artifacts
            ),
            "release_rows": release_rows,
            "artifact_type_descriptions": ARTIFACT_TYPE_DESCRIPTIONS,
            "invocation_guidance": _invocation_guidance(
                active_release, aliases[0].alias if aliases else None
            ),
            "project_drafts": project_drafts,
            "dsl_guide": _workflow_dsl_guide(),
            "consumer_bindings": consumer_bindings,
            "relationship_rows": relationship_rows,
            "candidate_document_sets": scoping.scoped_document_sets(request.user)
            .filter(organization_id=organization_id, status="active")
            .exclude(id__in=bound_set_ids)
            .order_by("name", "logical_id"),
            "can_write": can_author_scenarios(request.user, organization_id),
            "can_evaluate": authorize_operator(
                user=request.user,
                capability=OperatorCapability.SCENARIO_TEST,
                organization=scenario.organization,
                project=scenario.project,
                scenario=scenario,
            ).allowed,
            "can_compile_release": authorize_operator(
                user=request.user,
                capability=OperatorCapability.SCENARIO_RELEASE,
                organization=scenario.organization,
                project=scenario.project,
                scenario=scenario,
            ).allowed,
            "editor_assignments": scenario.editor_assignments.filter(
                status=DelegatedAssignmentStatus.ACTIVE
            )
            .select_related("user")
            .order_by("user__username", "user_id"),
            "can_manage_access": can_admin_org(request.user, organization_id),
            # Role-honest affordances (Scope D): reasons shown on disabled authoring controls.
            "author_reason": _AUTHOR_REASON,
            "release_reason": _RELEASE_AUTHORITY_REASON,
        },
    )


@login_required
@require_GET
def scenario_artifact_options(request: HttpRequest, public_id: object) -> JsonResponse:
    scenario = _scoped_scenario(request.user, public_id=public_id)
    if not authorize_operator(
        user=request.user,
        capability=OperatorCapability.SCENARIO_RELEASE,
        organization=scenario.organization,
        project=scenario.project,
        scenario=scenario,
    ).allowed:
        raise PermissionDenied
    if scenario.organization.status != OrganizationStatus.ACTIVE:
        raise PermissionDenied
    artifact_type = request.GET.get("artifact_type", "").strip()
    logical_id = request.GET.get("logical_id", "").strip()
    queryset = ArtifactVersion.objects.filter(organization_id=scenario.organization_id)

    if not artifact_type:
        available_types = set(queryset.values_list("type", flat=True).distinct())
        options = [
            {
                "value": value,
                "label": label,
                "description": ARTIFACT_TYPE_DESCRIPTIONS.get(value, ""),
            }
            for value, label in ArtifactType.choices
            if value in available_types
        ]
        return JsonResponse({"level": "artifact_type", "options": options})

    if artifact_type not in ArtifactType.values:
        raise Http404
    queryset = queryset.filter(type=artifact_type)
    if not logical_id:
        rows = list(
            queryset.order_by("logical_id", "-version").values(
                "logical_id", "logical_description", "version"
            )[:501]
        )
        logical_options: list[dict[str, object]] = []
        seen: set[str] = set()
        for row in rows:
            value = str(row["logical_id"])
            if value in seen:
                continue
            seen.add(value)
            logical_options.append(
                {
                    "value": value,
                    "label": value,
                    "description": row["logical_description"],
                    "latest_version": row["version"],
                }
            )
        return JsonResponse(
            {
                "level": "logical_artifact",
                "artifact_type": artifact_type,
                "options": logical_options[:100],
                "limited": len(rows) > 500 or len(logical_options) > 100,
            }
        )

    if len(logical_id) > 128:
        raise Http404
    versions = list(queryset.filter(logical_id=logical_id).order_by("-version")[:101])
    if not versions:
        raise Http404
    refs = {(artifact_type, logical_id, artifact.version): 0 for artifact in versions[:100]}
    releases = ScenarioRelease.objects.filter(organization_id=scenario.organization_id).only(
        "manifest"
    )[:500]
    for release in releases:
        manifest_artifacts = release.manifest.get("artifacts", {})
        if not isinstance(manifest_artifacts, dict):
            continue
        for item in manifest_artifacts.values():
            if not isinstance(item, dict):
                continue
            key = (item.get("type"), item.get("logical_id"), item.get("version"))
            if key in refs:
                refs[key] += 1
    role_candidates = [artifact_type, f"{artifact_type}.{logical_id}"]
    if artifact_type == ArtifactType.WORKFLOW_DEFINITION:
        role_candidates = ["workflow_definition", f"child_workflow.{logical_id}"]
    roles = [role for role in role_candidates if role_accepts_artifact_type(role, artifact_type)]
    return JsonResponse(
        {
            "level": "exact_version",
            "artifact_type": artifact_type,
            "logical_id": logical_id,
            "logical_description": versions[0].logical_description,
            "roles": roles,
            "options": [
                {
                    "id": artifact.pk,
                    "version": artifact.version,
                    "description": artifact.version_description,
                    "checksum": artifact.checksum,
                    "status": "published",
                    "pinned_release_count": refs[
                        (artifact.type, artifact.logical_id, artifact.version)
                    ],
                }
                for artifact in versions[:100]
            ],
            "limited": len(versions) > 100,
        }
    )


@login_required
@require_POST
def scenario_compile_candidate(request: HttpRequest, public_id: object) -> HttpResponse:
    scenario = _scoped_scenario(request.user, public_id=public_id)
    organization_id = scenario.organization_id
    if not authorize_operator(
        user=request.user,
        capability=OperatorCapability.SCENARIO_RELEASE,
        organization=scenario.organization,
        project=scenario.project,
        scenario=scenario,
    ).allowed:
        raise PermissionDenied
    if scenario.organization.status != OrganizationStatus.ACTIVE:
        raise PermissionDenied
    raw_ids = request.POST.getlist("artifact_ids")
    if not raw_ids or len(raw_ids) > 50 or len(set(raw_ids)) != len(raw_ids):
        messages.error(request, "Candidate için 1–50 benzersiz artifact sürümü seçin.")
        return redirect("console:scenario_detail_public", public_id=scenario.public_id)
    if any(not value.isdigit() or len(value) > 19 for value in raw_ids):
        raise Http404
    artifacts = list(
        ArtifactVersion.objects.filter(
            organization_id=organization_id, pk__in=[int(value) for value in raw_ids]
        )
    )
    if len(artifacts) != len(raw_ids):
        raise Http404
    refs: list[ArtifactRef] = []
    for artifact in artifacts:
        role = request.POST.get(f"role_{artifact.pk}", "").strip()
        if not role_accepts_artifact_type(role, artifact.type):
            messages.error(
                request,
                f"{artifact.type} için manifest rolü canonical role/type sözleşmesiyle uyumsuz.",
            )
            return redirect("console:scenario_detail_public", public_id=scenario.public_id)
        refs.append(ArtifactRef(role, artifact.type, artifact.logical_id, artifact.version))
    if len({ref.role for ref in refs}) != len(refs):
        messages.error(request, "Manifest rolleri benzersiz olmalıdır.")
        return redirect("console:scenario_detail_public", public_id=scenario.public_id)
    active = ScenarioRelease.objects.filter(scenario=scenario, status=ReleaseStatus.ACTIVE).first()
    runtime_version = active.runtime_version if active else "runtime:v1"
    try:
        with transaction.atomic():
            release = compile_release(
                scenario=scenario,
                refs=refs,
                runtime_version=runtime_version,
                created_by=request.user.get_username(),
            )
            record_event(
                actor_type="user",
                actor_id=request.user.get_username(),
                action="console.scenario.release.compile",
                outcome="success",
                organization_id=organization_id,
                resource_type="scenario_release",
                resource_id=str(release.pk),
                reason=release.artifact_manifest_sha256,
                request_id=_request_id(request),
                trace_id=_trace_id(request),
            )
    except CompileError as exc:
        diagnostic = exc.as_diagnostic()
        record_event(
            actor_type="user",
            actor_id=request.user.get_username(),
            action="console.scenario.release.compile",
            outcome="failure",
            organization_id=organization_id,
            resource_type="scenario",
            resource_id=str(scenario.pk),
            reason=diagnostic["code"],
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
        messages.error(
            request,
            f"{diagnostic['message']} ({diagnostic['code']})",
        )
        return redirect("console:scenario_detail_public", public_id=scenario.public_id)
    messages.success(request, f"Candidate release #{release.pk} oluşturuldu; runtime değişmedi.")
    return redirect("console:release_detail", release_id=release.pk)


@login_required
@require_POST
def scenario_bind_document_set(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk, public_id)
    organization_id = scenario.project.organization_id
    if not can_author_scenarios(request.user, organization_id):
        raise PermissionDenied
    document_set_id = request.POST.get("document_set_id", "")
    document_set = (
        scoping.scoped_document_sets(request.user)
        .filter(id=document_set_id, organization_id=organization_id, status="active")
        .first()
        if document_set_id.isdigit()
        else None
    )
    if document_set is None:
        messages.error(request, "Bağ kurulamadı: geçersiz doküman seti.")
    else:
        try:
            document_services.bind_scenario_document_set(
                scenario=scenario,
                document_set=document_set,
                actor=request.user.get_username(),
            )
            messages.success(
                request,
                "Doküman seti bağlandı. Değişiklik yeni release derlendiğinde sabitlenir.",
            )
        except DocumentError as exc:
            messages.error(request, f"Bağ kurulamadı: {exc.code}")
    return redirect("console:scenario_detail_public", public_id=scenario.public_id)


@login_required
@require_POST
def scenario_unbind_document_set(
    request: HttpRequest,
    binding_pk: int,
    pk: int | None = None,
    public_id: object = None,
) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk, public_id)
    organization_id = scenario.project.organization_id
    if not can_author_scenarios(request.user, organization_id):
        raise PermissionDenied
    binding = (
        ScenarioDocumentSetBinding.objects.select_related("document_set")
        .filter(pk=binding_pk, scenario=scenario, organization_id=organization_id)
        .first()
    )
    if binding is None:
        raise Http404
    document_services.unbind_scenario_document_set(binding, actor=request.user.get_username())
    messages.success(
        request, "Doküman seti bağı kaldırıldı. Aktif release yeniden derlenene kadar değişmez."
    )
    return redirect("console:scenario_detail_public", public_id=scenario.public_id)


@login_required
@require_POST
def scenario_grant_consumer(
    request: HttpRequest,
    document_set_pk: int,
    pk: int | None = None,
    public_id: object = None,
) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk, public_id)
    organization_id = scenario.project.organization_id
    if not can_author_scenarios(request.user, organization_id):
        raise PermissionDenied
    document_set = (
        scoping.scoped_document_sets(request.user)
        .filter(
            pk=document_set_pk,
            organization_id=organization_id,
            scenario_bindings__scenario=scenario,
        )
        .first()
    )
    if document_set is None:
        raise Http404
    consumer_id = request.POST.get("consumer_id", "")
    consumer = (
        Consumer.objects.filter(
            id=consumer_id,
            organization_id=organization_id,
            status=ConsumerStatus.ACTIVE,
            bindings__scenario=scenario,
            bindings__status=BindingStatus.ACTIVE,
        ).first()
        if consumer_id.isdigit()
        else None
    )
    if consumer is None:
        messages.error(request, "Erişim verilemedi: istemci bu senaryoya bağlı değil.")
    else:
        try:
            document_services.grant_document_set(
                document_set=document_set,
                principal_type=GrantPrincipalType.CONSUMER,
                principal_ref=str(consumer.id),
                actor=request.user.get_username(),
            )
            messages.success(request, "İstemci için doküman erişimi verildi.")
        except DocumentError as exc:
            messages.error(request, f"Erişim verilemedi: {exc.code}")
    return redirect("console:scenario_detail_public", public_id=scenario.public_id)


@login_required
@require_POST
def scenario_revoke_consumer(
    request: HttpRequest,
    grant_pk: int,
    pk: int | None = None,
    public_id: object = None,
) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk, public_id)
    organization_id = scenario.project.organization_id
    if not can_author_scenarios(request.user, organization_id):
        raise PermissionDenied
    grant = (
        DocumentSetGrant.objects.select_related("document_set")
        .filter(
            pk=grant_pk,
            organization_id=organization_id,
            principal_type=GrantPrincipalType.CONSUMER,
            document_set__scenario_bindings__scenario=scenario,
        )
        .first()
    )
    if grant is None:
        raise Http404
    document_services.revoke_document_set_grant(grant, actor=request.user.get_username())
    messages.success(request, "İstemci doküman erişimi kaldırıldı.")
    return redirect("console:scenario_detail_public", public_id=scenario.public_id)


@login_required
def consumers(request: HttpRequest) -> HttpResponse:
    active_org = console_context.resolve_active_organization(request)
    consumers_qs = scoping.narrow_to_active_organization(
        scoping.scoped_consumers(request.user), active_org, field="organization_id"
    )
    _no_consumer_admin = active_org is None or not can_admin_org(request.user, active_org.pk)
    rows = [
        {
            "href": reverse("console:consumer_detail_public", args=[c.public_id]),
            "cols": [
                c.organization.slug,
                {"text": c.name, "url": "console:consumer_detail_public", "arg": c.public_id},
                c.subject,
                c.protocol,
                c.status,
            ],
        }
        for c in consumers_qs
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "İstemciler",
            "headers": ["Organizasyon", "Ad", "Subject", "Protokol", "Durum"],
            "rows": rows,
            "create_links": [
                {
                    "url": "console:consumer_create",
                    "label": "Yeni istemci",
                    "disabled": _no_consumer_admin,
                    "reason": _CREATE_CONSUMER_REASON,
                },
                {
                    "url": "console:binding_create",
                    "label": "Yeni istemci bağı",
                    "disabled": _no_consumer_admin,
                    "reason": _CREATE_CONSUMER_REASON,
                },
            ],
        },
    )


def _scoped_consumer(user: UserLike, pk: int | None = None, public_id: object = None) -> Consumer:
    try:
        consumer = scoping.scoped_consumers(user).get(
            **({"public_id": public_id} if public_id is not None else {"pk": pk})
        )
    except Consumer.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(consumer.organization_id)
    return consumer


@login_required
def consumer_detail(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    consumer = _scoped_consumer(request.user, pk, public_id)
    request.session[console_context.SESSION_KEY] = consumer.organization_id
    binding_candidates = list(
        consumer.bindings.select_related("scenario", "scenario__project")
        .prefetch_related("scenario__aliases")
        .order_by("scenario__project__name", "scenario__name")[:101]
    )
    bindings_limited = len(binding_candidates) > 100
    bindings = binding_candidates[:100]
    scenario_ids = {binding.scenario_id for binding in bindings}
    grant_candidates = list(
        DocumentSetGrant.objects.filter(
            organization_id=consumer.organization_id,
            principal_type=GrantPrincipalType.CONSUMER,
            principal_ref=str(consumer.pk),
        )
        .select_related("document_set")
        .order_by("document_set__name", "document_set__logical_id")[:101]
    )
    grants_limited = len(grant_candidates) > 100
    grants = grant_candidates[:100]
    document_set_ids = {grant.document_set_id for grant in grants}
    related_bindings = ScenarioDocumentSetBinding.objects.filter(
        document_set_id__in=document_set_ids, scenario_id__in=scenario_ids
    ).select_related("scenario", "scenario__project")
    bindings_by_document_set: dict[int, list[ScenarioDocumentSetBinding]] = {}
    for binding in related_bindings.order_by("scenario__project__name", "scenario__name"):
        bindings_by_document_set.setdefault(binding.document_set_id, []).append(binding)
    grant_rows = []
    for grant in grants:
        grant_rows.append(
            {
                "grant": grant,
                "scenario_bindings": bindings_by_document_set.get(grant.document_set_id, []),
            }
        )
    token_candidates = list(consumer.tokens.order_by("name", "prefix")[:101])
    return render(
        request,
        "console/consumer_detail.html",
        {
            "consumer": consumer,
            "bindings": bindings,
            "bindings_limited": bindings_limited,
            "grant_rows": grant_rows,
            "grants_limited": grants_limited,
            "tokens": token_candidates[:100],
            "tokens_limited": len(token_candidates) > 100,
            "is_disabled": consumer.organization.status == OrganizationStatus.DISABLED,
            "can_manage_credentials": can_admin_org(request.user, consumer.organization_id),
            "can_issue_credentials": can_admin_org(request.user, consumer.organization_id)
            and consumer.status == ConsumerStatus.ACTIVE,
            "token_issue_form": ConsumerTokenIssueForm(),
        },
    )


@login_required
@require_POST
@sensitive_variables("raw")
def consumer_token_issue(request: HttpRequest, public_id: object) -> HttpResponse:
    consumer = _scoped_consumer(request.user, public_id=public_id)
    _authorize_consumer_credentials(request, consumer, "consumer_token.issue")
    form = ConsumerTokenIssueForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Token adı geçersiz.")
        return redirect("console:consumer_detail_public", public_id=consumer.public_id)
    try:
        token, raw = issue_consumer_token(
            consumer=consumer,
            name=form.cleaned_data["name"],
            actor_id=request.user.get_username(),
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
    except CredentialLifecycleError as exc:
        _audit_credential_failure(request, consumer, "consumer_token.issue", exc.code)
        messages.error(request, "Pasif bir istemci için yeni token oluşturulamaz.")
        return redirect("console:consumer_detail_public", public_id=consumer.public_id)
    return _token_reveal_response(
        request,
        consumer=consumer,
        raw_token=raw,
        token_name=token.name,
        action_label="Token oluşturuldu",
    )


@login_required
@require_POST
@sensitive_variables("raw")
def consumer_token_rotate(request: HttpRequest, public_id: object, token_id: int) -> HttpResponse:
    consumer = _scoped_consumer(request.user, public_id=public_id)
    _authorize_consumer_credentials(request, consumer, "consumer_token.rotate")
    try:
        token, raw = rotate_consumer_token(
            consumer=consumer,
            token_id=token_id,
            actor_id=request.user.get_username(),
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
    except CredentialLifecycleError as exc:
        if exc.code == "TOKEN_NOT_FOUND":
            raise Http404 from exc
        _audit_credential_failure(request, consumer, "consumer_token.rotate", exc.code)
        messages.error(request, "Yalnız etkin istemci ve token döndürülebilir.")
        return redirect("console:consumer_detail_public", public_id=consumer.public_id)
    return _token_reveal_response(
        request,
        consumer=consumer,
        raw_token=raw,
        token_name=token.name,
        action_label="Token döndürüldü",
    )


@login_required
@require_POST
def consumer_token_revoke(request: HttpRequest, public_id: object, token_id: int) -> HttpResponse:
    consumer = _scoped_consumer(request.user, public_id=public_id)
    _authorize_consumer_credentials(request, consumer, "consumer_token.revoke")
    try:
        changed = revoke_consumer_token(
            consumer=consumer,
            token_id=token_id,
            actor_id=request.user.get_username(),
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
    except CredentialLifecycleError as exc:
        raise Http404 from exc
    messages.success(
        request,
        "Token iptal edildi." if changed else "Token daha önce iptal edilmişti.",
    )
    return redirect("console:consumer_detail_public", public_id=consumer.public_id)


@login_required
@require_GET
def artifacts(request: HttpRequest) -> HttpResponse:
    console_context.resolve_active_organization(request)
    return redirect("console:projects")


def _scoped_artifact(user: UserLike, pk: int) -> ArtifactVersion:
    try:
        artifact = scoping.scoped_artifacts(user).get(pk=pk)
    except ArtifactVersion.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(artifact.organization_id)
    return artifact


@login_required
def artifact_detail(request: HttpRequest, pk: int) -> HttpResponse:
    artifact = _scoped_artifact(request.user, pk)
    request.session[console_context.SESSION_KEY] = artifact.organization_id
    pinned_by: list[dict[str, object]] = []
    releases = scoping.scoped_releases(request.user).filter(
        scenario__project__organization_id=artifact.organization_id
    )
    release_scan_limit = 500
    pin_scan_limited = releases.count() > release_scan_limit
    for release in releases.order_by("-created_at", "-pk")[:release_scan_limit]:
        roles = [
            row["role"]
            for row in _release_artifact_rows(release)
            if isinstance(row["artifact"], ArtifactVersion) and row["artifact"].pk == artifact.pk
        ]
        if roles:
            pinned_by.append({"release": release, "roles": roles})
    matching_draft_candidates = (
        list(
            WorkflowDraft.objects.filter(
                organization_id=artifact.organization_id, logical_id=artifact.logical_id
            )
            .select_related("project")
            .order_by("-updated_at")[:51]
        )
        if artifact.type == "workflow_definition"
        else []
    )
    matching_drafts_limited = len(matching_draft_candidates) > 50
    matching_drafts = matching_draft_candidates[:50]
    canonical_body = json.dumps(artifact.body, ensure_ascii=False, indent=2, sort_keys=True)
    display_limit = int(getattr(settings, "CONSOLE_MAX_ARTIFACT_DISPLAY_CHARS", 500_000))
    body_too_large = len(canonical_body) > display_limit
    return render(
        request,
        "console/artifact_detail.html",
        {
            "artifact": artifact,
            "canonical_body": "" if body_too_large else canonical_body,
            "body_too_large": body_too_large,
            "pinned_by": pinned_by,
            "pin_scan_limited": pin_scan_limited,
            "matching_drafts": matching_drafts,
            "matching_drafts_limited": matching_drafts_limited,
            "dsl_guide": _workflow_dsl_guide(),
        },
    )


@login_required
@require_GET
def releases(request: HttpRequest) -> HttpResponse:
    console_context.resolve_active_organization(request)
    return redirect("console:projects")


@login_required
@require_GET
def runs(request: HttpRequest) -> HttpResponse:
    """Render the bounded unified operational projection for one active organization."""
    organization = console_context.resolve_active_organization(request)
    if organization is None:
        return render(
            request,
            "console/runs.html",
            {
                "organization_required": True,
                "kind_choices": (),
                "status_choices": (),
            },
        )
    filter_error = ""
    try:
        filters = operations.parse_operation_filters(
            request.GET,
            organization=organization,
        )
        page = operations.project_operations(
            organization=organization,
            filters=filters,
        )
    except operations.OperationFilterError as exc:
        filter_error = str(exc)
        filters = None
        page = None

    projects = list(
        scoping.narrow_to_active_organization(
            scoping.scoped_projects(request.user),
            organization,
            field="organization_id",
        ).order_by("name")
    )
    scenarios = list(
        scoping.narrow_to_active_organization(
            scoping.scoped_scenarios(request.user),
            organization,
            field="organization_id",
        )
        .select_related("project")
        .order_by("name")
    )
    document_sets = list(
        scoping.narrow_to_active_organization(
            scoping.scoped_document_sets(request.user),
            organization,
            field="organization_id",
        ).order_by("name")
    )
    controls = list(
        AgentRuntimeControl.objects.filter(
            Q(scope_type=RuntimeControlScope.PLATFORM) | Q(organization_id=organization.pk),
            suspended=True,
        )
        .select_related("organization", "project", "scenario")
        .order_by("scope_type", "updated_at")
    )
    can_manage_platform = authorize_operator(
        user=request.user,
        capability=OperatorCapability.RUNTIME_PAUSE,
    ).allowed
    can_manage_organization = authorize_operator(
        user=request.user,
        capability=OperatorCapability.RUNTIME_PAUSE,
        organization=organization,
    ).allowed
    response = render(
        request,
        "console/runs.html",
        {
            "page": page,
            "filter_error": filter_error,
            "applied": request.GET,
            "kind_choices": [
                (kind.value, operations.KIND_LABELS[kind]) for kind in operations.OperationKind
            ],
            "status_choices": [
                (status.value, operations.STATUS_LABELS[status])
                for status in operations.OperationStatusGroup
            ],
            "days_choices": (1, 7, 14, 30, 60, 90),
            "projects": projects,
            "scenarios": scenarios,
            "document_sets": document_sets,
            "controls": controls,
            "can_manage_platform": can_manage_platform,
            "can_manage_organization": can_manage_organization,
            "reason_codes": sorted(RUNTIME_CONTROL_REASON_CODES),
            "base_query": _query_without_page(request),
        },
    )
    if filter_error:
        response.status_code = 400
    return response


@login_required
@require_POST
def runtime_control_change(request: HttpRequest) -> HttpResponse:
    """Resolve trusted scope lineage and reauthorize every control mutation."""

    organization = console_context.resolve_active_organization(request)
    if organization is None:
        raise PermissionDenied
    scope_type = request.POST.get("scope_type", "")
    target = request.POST.get("target", "")
    project = None
    scenario = None
    control_organization: Organization | None = organization
    if scope_type == RuntimeControlScope.PLATFORM:
        control_organization = None
        if target:
            raise PermissionDenied
    elif scope_type == RuntimeControlScope.ORGANIZATION:
        if target:
            raise PermissionDenied
    elif scope_type == RuntimeControlScope.PROJECT:
        try:
            target_id = uuid.UUID(target)
        except (TypeError, ValueError):
            raise Http404 from None
        project = AIProject.objects.filter(
            organization=organization,
            public_id=target_id,
        ).first()
        if project is None:
            raise Http404
    elif scope_type == RuntimeControlScope.SCENARIO:
        try:
            target_id = uuid.UUID(target)
        except (TypeError, ValueError):
            raise Http404 from None
        scenario = (
            Scenario.objects.select_related("project")
            .filter(
                organization=organization,
                public_id=target_id,
            )
            .first()
        )
        if scenario is None:
            raise Http404
    else:
        raise PermissionDenied

    action = request.POST.get("action", "")
    if action not in {"pause", "resume"}:
        raise PermissionDenied
    try:
        change_runtime_control(
            user=request.user,
            scope_type=scope_type,
            suspended=action == "pause",
            reason_code=request.POST.get("reason_code", ""),
            reason=request.POST.get("reason", ""),
            organization=control_organization,
            project=project,
            scenario=scenario,
        )
    except RuntimeControlError as exc:
        if str(exc) == "RUNTIME_CONTROL_FORBIDDEN":
            raise PermissionDenied from exc
        messages.error(request, f"Çalışma zamanı kontrolü reddedildi: {exc}")
    else:
        messages.success(
            request,
            "Çalışma zamanı durduruldu." if action == "pause" else "Çalışma zamanı açıldı.",
        )
    return redirect("console:runs")


def _scoped_release(user: UserLike, release_id: int) -> ScenarioRelease:
    try:
        release = scoping.scoped_releases(user).get(pk=release_id)
    except ScenarioRelease.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(release.organization_id)
    return release


@login_required
def release_detail(request: HttpRequest, release_id: int) -> HttpResponse:
    release = _scoped_release(request.user, release_id)
    request.session[console_context.SESSION_KEY] = release.organization_id
    manifest_json = json.dumps(release.manifest, ensure_ascii=False, indent=2, sort_keys=True)
    display_limit = int(getattr(settings, "CONSOLE_MAX_ARTIFACT_DISPLAY_CHARS", 500_000))
    manifest_too_large = len(manifest_json) > display_limit
    return render(
        request,
        "console/release_detail.html",
        {
            "release": release,
            "artifact_rows": _release_artifact_rows(release),
            "manifest_json": "" if manifest_too_large else manifest_json,
            "manifest_too_large": manifest_too_large,
            "canaries": release.canaries.select_related("consumer").order_by("-created_at")[:100],
            "can_manage": can_manage_scenario_releases(request.user, release.organization_id),
            "is_disabled": release.organization.status == OrganizationStatus.DISABLED,
        },
    )


def _manageable_release(user: UserLike, release_id: int) -> ScenarioRelease:
    release = _scoped_release(user, release_id)
    if not can_manage_scenario_releases(user, release.scenario.project.organization_id):
        raise PermissionDenied
    return release


@login_required
@require_POST
def release_run_eval(request: HttpRequest, release_id: int) -> HttpResponse:
    release = _manageable_release(request.user, release_id)
    try:
        run = run_eval(release=release, created_by=request.user.get_username())
        messages.success(
            request, f"Eval {run.status}: {run.passed_cases}/{run.total_cases} vaka geçti."
        )
    except EvalError as exc:
        messages.error(request, f"Eval başlatılamadı: {exc.code}")
    return redirect("console:releases")


@login_required
@require_POST
def release_promote(request: HttpRequest, release_id: int) -> HttpResponse:
    release = _manageable_release(request.user, release_id)
    try:
        promote(release=release, actor=request.user.get_username())
        messages.success(request, f"Release {release.pk} aktif edildi.")
    except LifecycleError as exc:
        messages.error(request, f"Aktivasyon reddedildi: {exc.code}")
    return redirect("console:releases")


@login_required
@require_POST
def release_rollback(request: HttpRequest, release_id: int) -> HttpResponse:
    release = _manageable_release(request.user, release_id)
    try:
        rollback(scenario=release.scenario, target=release, actor=request.user.get_username())
        messages.success(request, f"Release {release.pk} sürümüne geri dönüldü.")
    except LifecycleError as exc:
        messages.error(request, f"Geri alma reddedildi: {exc.code}")
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
            messages.success(request, "Canary başlatıldı.")
            return redirect("console:releases")
        except LifecycleError as exc:
            messages.error(request, f"Canary reddedildi: {exc.code}")
    return render(
        request,
        "console/form.html",
        {"title": f"Release {release.pk} için canary başlat", "form": form},
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
    if not can_manage_scenario_releases(request.user, canary.scenario.project.organization_id):
        raise PermissionDenied
    set_tenant_context(canary.organization_id)
    try:
        stop_canary(canary=canary, actor=request.user.get_username())
        messages.success(request, "Canary durduruldu.")
    except LifecycleError as exc:
        messages.error(request, f"Durdurma reddedildi: {exc.code}")
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
                "can_decide": approval.organization.status == OrganizationStatus.ACTIVE
                and bool(set(roles or []) & set(approval.approver_roles)),
            }
        )
    return render(request, "console/tool_approvals.html", {"title": "Tool onayları", "rows": rows})


@login_required
@require_POST
def tool_approval_decide(request: HttpRequest, approval_id: int) -> HttpResponse:
    approval = ApprovalRequest.objects.filter(pk=approval_id).first()
    if approval is None:
        raise Http404
    if not _operator_can_mutate_org(request.user, approval.organization_id):
        raise PermissionDenied
    set_tenant_context(approval.organization_id)
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
            request, f"Onay {approval.pk} {'kabul edildi' if approve else 'reddedildi'}."
        )
    except ToolApprovalError as exc:
        messages.error(request, f"Karar reddedildi: {exc.code}")
    return redirect("console:tool_approvals")


@login_required
@require_POST
def tool_invocation_cancel(request: HttpRequest, invocation_id: int) -> HttpResponse:
    invocation = ToolInvocation.objects.filter(pk=invocation_id).first()
    if invocation is None:
        raise Http404
    if not _operator_can_mutate_org(request.user, invocation.organization_id):
        raise PermissionDenied
    set_tenant_context(invocation.organization_id)
    try:
        cancel_invocation(
            invocation_id=invocation.pk,
            organization_id=invocation.organization_id,
            actor=request.user.get_username(),
        )
        messages.success(request, f"Tool çağrısı {invocation.pk} iptal edildi.")
    except ToolApprovalError as exc:
        messages.error(request, f"İptal reddedildi: {exc.code}")
    return redirect("console:tool_approvals")


@login_required
@require_POST
def workflow_human_task_decide(request: HttpRequest, wait_id: uuid.UUID) -> HttpResponse:
    allowed = allowed_organization_ids(request.user)
    waits = RunWait.objects.filter(
        pk=wait_id,
        kind=RunWaitKind.HUMAN,
        status=RunWaitStatus.PENDING,
    )
    if allowed is not None:
        waits = waits.filter(organization_id__in=allowed)
    wait = waits.first()
    if wait is None:
        raise Http404
    if not _operator_can_mutate_org(request.user, wait.organization_id):
        raise PermissionDenied
    raw_decision = request.POST.get("decision", "")
    try:
        decision = json.loads(raw_decision)
    except (TypeError, json.JSONDecodeError):
        messages.error(request, "Karar reddedildi: WAIT_PAYLOAD_INVALID")
        return redirect("console:tool_approvals")
    set_tenant_context(wait.organization_id)
    try:
        roles = resolve_actor_roles(
            username=request.user.get_username(),
            organization_id=wait.organization_id,
        )
        decide_run_human_task(
            organization_id=wait.organization_id,
            wait_id=wait.id,
            actor_id=request.user.get_username(),
            actor_roles=set(roles or []),
            payload=decision,
        )
    except RunWaitError as exc:
        messages.error(request, f"Karar reddedildi: {exc.code}")
    else:
        transaction.on_commit(
            lambda: dispatch_unified_background_run(
                run_id=wait.run_id,
                organization_id=wait.organization_id,
            )
        )
        messages.success(request, "İnsan görevi kararı kaydedildi.")
    return redirect("console:tool_approvals")


_RUN_DAYS_CHOICES = (1, 7, 30, 90)
_RUN_PAGE_SIZE = 50

ARTIFACT_TYPE_DESCRIPTIONS: dict[str, str] = {
    ArtifactType.INPUT_CONTRACT: "Senaryonun kabul ettiği giriş yapısını doğrular.",
    ArtifactType.OUTPUT_CONTRACT: "Çıktı biçimini ve alanlarını doğrular.",
    ArtifactType.PROMPT_TEMPLATE: "Tekrar kullanılabilir, sürümlenmiş prompt metnidir.",
    ArtifactType.POLICY_PROFILE: "Çalışma zamanı davranış ve güvenlik politikasını tanımlar.",
    ArtifactType.MODEL_PROFILE: "Onaylı model seçimi ve çalışma sınırlarını tanımlar.",
    ArtifactType.SOURCE_DEFINITION: "Yönetilen veri kaynağı tanımıdır.",
    ArtifactType.TRANSFORM_PROFILE: "Girdi veya çıktı dönüşüm sözleşmesini tanımlar.",
    ArtifactType.CHUNKING_PROFILE: "Doküman parçalama davranışını tanımlar.",
    ArtifactType.RETRIEVAL_PROFILE: "Arama ve retrieval davranışını tanımlar.",
    ArtifactType.WORKFLOW_DEFINITION: "Senaryonun derlenen node/edge çalışma grafiğidir.",
    ArtifactType.CUSTOM_NODE_DEFINITION: "Onaylı özel workflow node sözleşmesidir.",
    ArtifactType.TOOL_DEFINITION: "Bir aracın güvenli çağrı sözleşmesini tanımlar.",
    ArtifactType.TOOL_BINDING: "Aracı onaylı hedef ve yetki sınırlarıyla bağlar.",
    ArtifactType.MEMORY_POLICY: "Agent belleğinin sınırlarını ve saklama davranışını tanımlar.",
    ArtifactType.EVAL_SUITE: "Release değerlendirmesinde kullanılan immutable test setidir.",
}


def _query_without_page(request: HttpRequest) -> str:
    """Current querystring minus ``page``, so pagination links keep the active filters."""
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def _apply_run_filters(
    request: HttpRequest, queryset: QuerySet[Any], buckets: dict[str, tuple[str, ...]]
) -> tuple[QuerySet[Any], dict[str, object]]:
    """Apply bounded server-side run filters (status/bucket/scenario/date) within tenant scope.

    Filters only ever narrow the already-tenant-scoped queryset. Unknown values are ignored
    (never raise), and the returned ``applied`` mapping drives the sticky filter UI and
    pagination query string.
    """
    status = request.GET.get("status", "").strip()
    bucket = request.GET.get("bucket", "").strip()
    scenario_q = request.GET.get("q", "").strip()[:100]
    days_raw = request.GET.get("days", "").strip()
    applied: dict[str, object] = {}
    if status:
        queryset = queryset.filter(status=status)
        applied["status"] = status
    elif bucket in buckets:
        queryset = queryset.filter(status__in=buckets[bucket])
        applied["bucket"] = bucket
    if scenario_q:
        queryset = queryset.filter(scenario__slug__icontains=scenario_q)
        applied["q"] = scenario_q
    if days_raw:
        try:
            days = int(days_raw)
        except ValueError:
            days = 0
        if days in _RUN_DAYS_CHOICES:
            queryset = queryset.filter(created_at__gte=timezone.now() - timedelta(days=days))
            applied["days"] = days
    return queryset, applied


@login_required
def workflow_runs(request: HttpRequest) -> HttpResponse:
    active_org = console_context.resolve_active_organization(request)
    base = scoping.narrow_to_active_organization(
        scoping.scoped_runs(request.user), active_org, field="organization_id"
    ).order_by("-created_at")
    filtered, applied = _apply_run_filters(request, base, RUN_BUCKETS)
    page = Paginator(filtered, _RUN_PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [
        {
            "id": run.pk,
            "href": reverse("console:workflow_run_detail", args=[run.pk]),
            "org": run.organization.slug,
            "scenario": run.scenario.slug,
            "status": run.status,
            "error": run.error_code,
            "awaiting_node": run.awaiting_reference,
            "created": run.created_at,
        }
        for run in page
    ]
    return render(
        request,
        "console/workflow_runs.html",
        {
            "title": "Workflow çalıştırmaları",
            "rows": rows,
            "page": page,
            "applied": applied,
            "status_choices": RunStatus.choices,
            "days_choices": _RUN_DAYS_CHOICES,
            "base_query": _query_without_page(request),
        },
    )


@login_required
def workflow_run_detail(request: HttpRequest, run_id: uuid.UUID) -> HttpResponse:
    """Render a redacted, tenant-scoped workflow run trace (P2.6.11).

    Only bounded metadata reaches the template — statuses, reason codes, failure classes,
    counts, truncated checksums/correlation hashes and timestamps. Payload-bearing columns
    (branch input/result state, join merged_state, wait payloads, redacted_state,
    execution_context) are never read here, so no tenant content or secret can leak onto an
    operator screen.
    """
    run = _scoped_run(request.user, run_id)
    branches = [
        {
            "region": b.region_node_id,
            "branch": b.branch_name,
            "ordinal": b.item_ordinal,
            "status": b.status,
            "attempts": b.attempt_count,
            "reason": b.reason_code,
            "checksum": b.result_checksum[:12],
            "started": b.started_at,
            "finished": b.finished_at,
        }
        for b in run.branches.order_by("region_node_id", "branch_name", "item_ordinal")
    ]
    joins = [
        {
            "region": j.region_node_id,
            "join": j.join_node_id,
            "mode": j.mode,
            "required": j.required_count,
            "branches": j.branch_count,
            "status": j.status,
            "closed": j.closed_at,
        }
        for j in run.joins.order_by("region_node_id")
    ]
    waits = [
        {
            "kind": w.kind,
            "node": w.node_id,
            "status": w.status,
            "correlation": w.resume_token_hash[:12],
            "deadline": w.deadline_at,
            "escalated": None,
            "consumed": w.consumed_at,
        }
        for w in run.waits.order_by("created_at")
    ]
    attempts = [
        {
            "node": event.node_id,
            "ordinal": event.payload.get("attempt", ""),
            "status": event.outcome,
            "reason": event.reason_code,
        }
        for event in run.events.filter(event_type="run.node_retried").order_by("sequence")
    ]
    compensations = [
        {
            "sequence": item.sequence,
            "source": item.source_node_id,
            "compensation": item.compensation_node_id,
            "status": item.status,
            "reason": item.reason_code,
            "finished": item.updated_at,
        }
        for item in run.compensations.order_by("sequence")
    ]
    children = [
        {
            "call_site": item.call_site,
            "depth": item.depth,
            "kind": "workflow",
            "status": item.status,
            "reason": item.reason_code,
        }
        for item in run.child_links.order_by("created_at")
    ]
    events = [
        {
            "sequence": e.sequence,
            "event_type": e.event_type,
            "node": e.node_id,
        }
        for e in run.events.order_by("sequence")
    ]
    summary = {
        "id": run.pk,
        "org": run.organization.slug,
        "scenario": run.scenario.slug,
        "status": run.status,
        "error": run.error_code,
        "awaiting_node": run.awaiting_reference,
        "created": run.created_at,
        "started": run.started_at,
        "finished": run.finished_at,
    }
    cancel_decision = authorize_operator(
        user=request.user,
        capability=OperatorCapability.RUNTIME_CANCEL,
        organization=run.organization,
        project=run.scenario.project,
        scenario=run.scenario,
    )
    return render(
        request,
        "console/workflow_run_detail.html",
        {
            "title": f"Workflow çalıştırması {run.pk}",
            "run": summary,
            "branches": branches,
            "joins": joins,
            "waits": waits,
            "attempts": attempts,
            "compensations": compensations,
            "children": children,
            "events": events,
            "can_recover": run.status == RunStatus.RECOVERY_REQUIRED
            and can_admin_org(request.user, run.organization_id),
            "can_cancel": cancel_decision.allowed and run.status not in RUN_TERMINAL_STATUSES,
        },
    )


@login_required
@require_POST
def workflow_run_cancel(request: HttpRequest, run_id: uuid.UUID) -> HttpResponse:
    """Cooperatively cancel one exact run after native object authorization."""

    run = _scoped_run(request.user, run_id)
    decision = authorize_operator(
        user=request.user,
        capability=OperatorCapability.RUNTIME_CANCEL,
        organization=run.organization,
        project=run.scenario.project,
        scenario=run.scenario,
    )
    if not decision.allowed:
        record_event(
            actor_type="user",
            actor_id=str(request.user.pk),
            action="runtime.run_cancel",
            outcome="deny",
            organization_id=run.organization_id,
            resource_type="run",
            resource_id=str(run.id),
            reason=f"{decision.reason}:{decision.source}"[:128],
        )
        raise PermissionDenied
    try:
        with transaction.atomic():
            request_run_cancellation(
                organization_id=run.organization_id,
                run_id=run.id,
                reason_code="OPERATOR_REQUESTED",
            )
            record_event(
                actor_type="user",
                actor_id=str(request.user.pk),
                action="runtime.run_cancel",
                outcome="allow",
                organization_id=run.organization_id,
                resource_type="run",
                resource_id=str(run.id),
                reason=f"OPERATOR_REQUESTED:{decision.source}"[:128],
            )
    except RunTransitionError as exc:
        messages.error(request, f"İptal isteği reddedildi: {exc}")
    else:
        messages.success(request, "İptal isteği kaydedildi; çalışma güvenli sınırda duracak.")
    return redirect("console:workflow_run_detail", run_id=run.id)


@login_required
@require_POST
def workflow_run_recovery_decide(request: HttpRequest, run_id: uuid.UUID) -> HttpResponse:
    run = _scoped_run(request.user, run_id)
    if not can_admin_org(request.user, run.organization_id):
        raise PermissionDenied
    try:
        resolve_run_recovery(
            organization_id=run.organization_id,
            run_id=run.id,
            actor_id=request.user.get_username(),
            decision=request.POST.get("decision", ""),
        )
    except RunRecoveryError as exc:
        messages.error(request, f"Recovery kararı reddedildi: {exc.code}")
    else:
        messages.success(request, "Recovery kararı kaydedildi.")
    return redirect("console:workflow_run_detail", run_id=run.id)


@login_required
def retention_operations(request: HttpRequest) -> HttpResponse:
    """Platform-admin retention/purge operations surface (P2.6.11).

    GET reports eligible bulky-state counts per class (no mutation). POST with an explicit
    confirmation performs the owner-approved, audited, fail-closed purge. Restricted to a
    platform admin; the purge itself re-audits every batch server-side.
    """
    if not is_platform_admin(request.user):
        raise PermissionDenied
    committed = False
    if request.method == "POST":
        if request.POST.get("confirm") != "purge":
            messages.error(request, "Silme işlemi için onay kutusunu işaretleyin.")
            return redirect("console:retention_operations")
        reports = run_retention(commit=True, actor=request.user.get_username())
        committed = True
        total = sum(r.purged for r in reports)
        messages.success(request, f"Retention purhe tamamlandı: {total} kayıt temizlendi.")
    else:
        reports = run_retention(commit=False)
    rows = [
        {"retention_class": r.retention_class, "eligible": r.eligible, "purged": r.purged}
        for r in reports
    ]
    return render(
        request,
        "console/retention_operations.html",
        {
            "title": "Saklama / temizleme",
            "rows": rows,
            "window_days": RETENTION_DAYS,
            "committed": committed,
        },
    )


def _scoped_run(user: UserLike, run_id: uuid.UUID) -> Run:
    run = (
        Run.objects.select_related("organization", "scenario", "scenario__project")
        .filter(pk=run_id)
        .first()
    )
    if run is None:
        raise Http404
    if not _operator_can_access_org(user, run.organization_id):
        raise PermissionDenied
    set_tenant_context(run.organization_id)
    return run


@login_required
@ensure_csrf_cookie
def builder(request: HttpRequest) -> HttpResponse:
    """Host the React Flow workflow builder SPA.

    The page only carries mount configuration — the operator's organizations in read
    scope with their per-org authoring flag (which drives the SPA's read-only mode). All
    authoritative validation, authorization, and publishing happen in the builder API;
    ``@ensure_csrf_cookie`` guarantees the SPA can obtain a CSRF token for its writes.
    """
    scoped_orgs = list(scoping.scoped_organizations(request.user).order_by("slug"))
    orgs = [
        {
            "slug": org.slug,
            "name": org.name,
            "can_write": can_author_scenarios(request.user, org.id),
        }
        for org in scoped_orgs
    ]
    organizations_by_slug = {org.slug: org for org in scoped_orgs}
    requested_org = request.GET.get("organization", "")
    requested_draft = request.GET.get("draft", "")
    requested_scenario = request.GET.get("scenario", "")
    initial: dict[str, object] = {}
    scenario = None
    if requested_scenario:
        scenario = (
            scoping.scoped_scenarios(request.user).filter(public_id=requested_scenario).first()
        )
        if scenario is None or (requested_org and requested_org != scenario.organization.slug):
            raise Http404
        initial = {
            "organization": scenario.organization.slug,
            "project_id": scenario.project_id,
            "scenario_id": scenario.pk,
            "scenario_public_id": str(scenario.public_id),
            "scenario_name": scenario.name,
            "project_name": scenario.project.name,
        }
        release_decision = authorize_operator(
            user=request.user,
            capability=OperatorCapability.SCENARIO_RELEASE,
            organization=scenario.organization,
            project=scenario.project,
            scenario=scenario,
        )
        initial["can_compile_release"] = release_decision.allowed
        if release_decision.allowed:
            initial["artifact_options_url"] = reverse(
                "console:scenario_artifact_options",
                args=[scenario.public_id],
            )
        active_release = ScenarioRelease.objects.filter(
            scenario=scenario, status=ReleaseStatus.ACTIVE
        ).first()
        if active_release is not None:
            for row in _release_artifact_rows(active_release):
                artifact = row["artifact"]
                if (
                    row["role"] == "workflow_definition"
                    and row["checksum_matches"]
                    and isinstance(artifact, ArtifactVersion)
                    and artifact.type == "workflow_definition"
                ):
                    initial["active_workflow"] = {
                        "logical_id": artifact.logical_id,
                        "name": f"{scenario.name} aktif workflow",
                        "version": artifact.version,
                        "checksum": artifact.checksum,
                        "body": artifact.body,
                    }
                    break
    if requested_draft:
        if not requested_draft.isdigit() or len(requested_draft) > 19:
            raise Http404
        requested_draft_id = int(requested_draft)
        if not 0 < requested_draft_id <= 9_223_372_036_854_775_807:
            raise Http404
        draft = WorkflowDraft.objects.filter(
            pk=requested_draft_id, organization_id__in=[org.pk for org in scoped_orgs]
        ).first()
        if draft is None or (requested_org and requested_org != draft.organization.slug):
            raise Http404
        if scenario is not None and (
            draft.scenario_id != scenario.pk or draft.project_id != scenario.project_id
        ):
            raise Http404
        initial.update({"organization": draft.organization.slug, "draft_id": draft.pk})
    elif requested_org and scenario is None:
        if requested_org not in organizations_by_slug:
            raise Http404
        initial = {"organization": requested_org}
    initial["ai_authoring"] = _ai_authoring_preflight()
    return render(
        request,
        "console/builder.html",
        {"title": "Workflow builder", "builder_orgs": orgs, "builder_initial": initial},
    )


@login_required
def documents(request: HttpRequest) -> HttpResponse:
    """List tenant-scoped document sets as the primary content workspace."""
    user = request.user
    active_org = console_context.resolve_active_organization(request)
    document_sets_qs = scoping.narrow_to_active_organization(
        scoping.scoped_document_sets(user), active_org, field="organization_id"
    ).order_by("name", "organization__name", "logical_id")
    sets = [
        {
            "id": s.id,
            "public_id": s.public_id,
            "href": reverse("console:document_set_detail_public", args=[s.public_id]),
            "org": s.organization.name,
            "logical_id": s.logical_id,
            "name": s.name,
            "status": s.status,
            "versions": s.versions.count(),
        }
        for s in document_sets_qs
    ]
    can_upload = active_org is not None and can_manage_documents(user, active_org.pk)
    return render(
        request,
        "console/documents.html",
        {
            "title": "Doküman setleri",
            "sets": sets,
            "set_form": DocumentSetForm(user=user, organization=active_org),
            "can_upload": can_upload,
            # Role-honest affordance (Scope D): explain the disabled create form.
            "create_reason": "" if can_upload else _AUTHOR_REASON,
        },
    )


@login_required
def advanced_document_inventory(request: HttpRequest) -> HttpResponse:
    """Elevated storage/tombstone/purge inventory, separate from the product journey."""
    organization_ids = admin_organization_ids(request.user)
    if organization_ids == set():
        raise PermissionDenied
    queryset = scoping.scoped_documents(request.user)
    if organization_ids is not None:
        queryset = queryset.filter(organization_id__in=organization_ids)
    pinned_document_ids = set(
        DocumentSetMembership.objects.filter(document_version__document__in=queryset).values_list(
            "document_version__document_id", flat=True
        )
    )
    docs = [
        {
            "public_id": document.public_id,
            "org": document.organization.slug,
            "logical_id": document.logical_id,
            "title": document.title,
            "version": document.current_version,
            "tombstoned": document.is_tombstoned,
            "pinned": document.pk in pinned_document_ids,
            "can_write": can_manage_documents(request.user, document.organization_id),
            "can_purge": can_admin_org(request.user, document.organization_id),
        }
        for document in queryset.order_by("organization_id", "logical_id")
    ]
    return render(
        request,
        "console/document_inventory_advanced.html",
        {"title": "Gelişmiş doküman envanteri", "documents": docs},
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
    if not can_manage_documents(request.user, organization.id):
        raise PermissionDenied
    upload = form.cleaned_data["file"]
    try:
        document_services.upload_console_document(
            organization=organization,
            title=form.cleaned_data["title"],
            mime_type=(upload.content_type or "application/octet-stream"),
            data=upload.read(),
            actor=request.user.get_username(),
        )
        messages.success(request, "Document uploaded.")
    except (DocumentError, IdentifierAllocationError) as exc:
        code = getattr(exc, "code", IdentifierAllocationError.code)
        messages.error(request, f"Upload failed: {code}")
    return redirect("console:documents")


@login_required
@require_POST
def document_soft_delete(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document = _scoped_document(request.user, pk, public_id)
    if not can_manage_documents(request.user, document.organization_id):
        raise PermissionDenied
    document_services.soft_delete_document(document, actor=request.user.get_username())
    messages.success(request, f"Document {document.logical_id} tombstoned.")
    return redirect("console:advanced_document_inventory")


@login_required
@require_POST
def document_purge(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document = _scoped_document(request.user, pk, public_id)
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
    return redirect("console:advanced_document_inventory")


def _scoped_document(user: UserLike, pk: int | None = None, public_id: object = None) -> Document:
    try:
        document = scoping.scoped_documents(user).get(
            **({"public_id": public_id} if public_id is not None else {"pk": pk})
        )
    except Document.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(document.organization_id)
    return document


@login_required
@require_POST
def document_set_create(request: HttpRequest) -> HttpResponse:
    organization = console_context.resolve_active_organization(request)
    if organization is None or not can_manage_documents(request.user, organization.pk):
        raise PermissionDenied
    form = DocumentSetForm(request.POST, user=request.user, organization=organization)
    if not form.is_valid():
        messages.error(request, "Create failed: check the form fields.")
        return redirect("console:documents")
    try:
        document_set = document_services.create_console_document_set(
            organization=organization,
            name=form.cleaned_data["name"],
            actor=request.user.get_username(),
        )
        messages.success(request, "Document set created.")
        return redirect("console:document_set_detail_public", public_id=document_set.public_id)
    except (DocumentError, IdentifierAllocationError) as exc:
        code = getattr(exc, "code", IdentifierAllocationError.code)
        messages.error(request, f"Create failed: {code}")
    return redirect("console:documents")


@login_required
def document_set_detail(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    request.session[console_context.SESSION_KEY] = document_set.organization_id
    can_write = can_manage_documents(request.user, document_set.organization_id)
    can_promote_index = can_manage_document_set_operations(request.user, document_set)
    worker_available = compatible_worker_available()
    job_labels: dict[str, tuple[str, str]] = {
        StagedIndexBuildJobStatus.DISPATCH_PENDING: (
            "İstek kaydedildi",
            "Dağıtım yeniden denenecek",
        ),
        StagedIndexBuildJobStatus.QUEUED: (
            "Kuyrukta" if worker_available else "Kuyrukta · uyumlu worker bekleniyor",
            "Worker talebi aldığında çalışma başlayacak",
        ),
        StagedIndexBuildJobStatus.RUNNING: (
            "Çalışıyor",
            "İlerleme güvenli aralıklarla güncellenir",
        ),
        StagedIndexBuildJobStatus.RETRY_WAIT: (
            "Yeniden deneme bekleniyor",
            "Sınır içinde yeniden denenecek",
        ),
        StagedIndexBuildJobStatus.SUCCEEDED: (
            "Promotable indeks hazır",
            "Aktivasyon ayrı yetki gerektirir",
        ),
        StagedIndexBuildJobStatus.FAILED: (
            "Başarısız",
            "Güvenli hata kodunu inceleyip yeniden deneyin",
        ),
        StagedIndexBuildJobStatus.CANCELLED: ("İptal edildi", "Geç sonuç durumu değiştiremez"),
        StagedIndexBuildJobStatus.RECONCILIATION_REQUIRED: (
            "Sonuç uzlaştırma gerektiriyor",
            "Operatör doğrulaması olmadan yeniden denenmez",
        ),
    }

    def _version_detail(v: DocumentSetVersion) -> dict[str, object]:
        """Full authoring detail for one set version (members/indexes/jobs)."""
        return {
            "id": v.id,
            "version": v.version,
            "status": v.status,
            "is_draft": v.status == DocumentSetVersionStatus.DRAFT,
            "can_build": v.status
            in [DocumentSetVersionStatus.PROMOTABLE, DocumentSetVersionStatus.ACTIVE],
            "indexes": [
                {
                    "id": index.id,
                    "version": index.version,
                    "status": index.status,
                    "profile": index.embedding_profile.logical_id
                    if index.embedding_profile
                    else "silinmiş profil",
                    "documents": index.document_count,
                    "chunks": index.chunk_count,
                    "reused_documents": index.reused_document_count,
                    "can_promote": can_promote_index and index.status == IndexStatus.PROMOTABLE,
                }
                for index in v.index_versions.select_related("embedding_profile").order_by(
                    "-version"
                )
            ],
            "jobs": [
                {
                    "public_id": job.public_id,
                    "status": job.status,
                    "label": job_labels[job.status][0],
                    "next": job_labels[job.status][1],
                    "documents": job.documents_completed,
                    "chunks": job.chunks_completed,
                    "attempt": job.attempt,
                    "max_attempts": job.max_attempts,
                    "error_code": job.error_code,
                    "can_cancel": can_write
                    and job.status
                    not in {
                        StagedIndexBuildJobStatus.SUCCEEDED,
                        StagedIndexBuildJobStatus.FAILED,
                        StagedIndexBuildJobStatus.CANCELLED,
                    },
                    "can_retry": can_write
                    and job.status == StagedIndexBuildJobStatus.FAILED
                    and job.attempt < job.max_attempts,
                }
                for job in v.index_build_jobs.order_by("-created_at", "-pk")[:5]
            ],
            "members": [
                {
                    "membership_id": m.id,
                    "public_id": m.document_version.document.public_id,
                    "logical_id": m.document_version.document.logical_id,
                    "title": m.document_version.document.title,
                    "version": m.document_version.version,
                    "parse_status": m.document_version.parse_status,
                    "tombstoned": m.document_version.document.is_tombstoned,
                    "ordinal": m.ordinal,
                }
                for m in v.memberships.select_related("document_version__document").order_by(
                    "ordinal"
                )
            ],
        }

    # Show only the current (latest) version expanded; older versions collapse behind a
    # "Geçmiş sürümler" control as read-only summaries (Scope F).
    all_versions = list(
        document_set.versions.order_by("-version").annotate(_member_count=Count("memberships"))
    )
    latest_version = all_versions[0] if all_versions else None
    selected_version = latest_version
    requested_version_id = request.GET.get("version", "")
    if requested_version_id.isdigit():
        selected_version = next(
            (version for version in all_versions if version.pk == int(requested_version_id)),
            latest_version,
        )
    current_version = _version_detail(selected_version) if selected_version is not None else None
    older_versions = [
        {
            "id": v.id,
            "version": v.version,
            "status": v.status,
            "member_count": getattr(v, "_member_count", 0),
        }
        for v in all_versions
        if selected_version is None or v.pk != selected_version.pk
    ]
    active_index = (
        IndexVersion.objects.filter(
            document_set_version__document_set=document_set,
            organization_id=document_set.organization_id,
            status=IndexStatus.ACTIVE,
            store_ready=True,
        )
        .select_related("document_set_version", "embedding_profile")
        .order_by("-updated_at", "-id")
        .first()
    )
    latest_members = (
        list(latest_version.memberships.select_related("document_version").all())
        if latest_version is not None
        else []
    )
    parsed_count = sum(
        item.document_version.parse_status == ParseStatus.PARSED for item in latest_members
    )
    uploaded_complete = bool(latest_members)
    parsed_complete = uploaded_complete and parsed_count == len(latest_members)
    draft_complete = uploaded_complete and latest_version is not None
    promotable_index = (
        IndexVersion.objects.filter(
            organization_id=document_set.organization_id,
            document_set_version=latest_version,
            status=IndexStatus.PROMOTABLE,
        )
        .order_by("-version")
        .first()
        if latest_version is not None
        else None
    )
    is_draft_current = (
        latest_version is not None and latest_version.status == DocumentSetVersionStatus.DRAFT
    )
    is_published_current = (
        latest_version is not None and latest_version.status != DocumentSetVersionStatus.DRAFT
    )
    published_complete = draft_complete and is_published_current
    staged_ready = (
        published_complete
        and IndexVersion.objects.filter(
            organization_id=document_set.organization_id,
            document_set_version=latest_version,
            status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
        ).exists()
    )
    serving_set_version = active_index.document_set_version if active_index is not None else None
    current_active_index = (
        active_index
        if active_index is not None
        and serving_set_version is not None
        and latest_version is not None
        and active_index.document_set_version_id == latest_version.id
        else None
    )
    publish_url = (
        reverse("console:document_set_version_publish", args=[latest_version.id])
        if latest_version is not None
        else ""
    )
    promote_url = (
        reverse("console:document_set_promote_index", args=[promotable_index.id])
        if promotable_index is not None
        else ""
    )
    # Each incomplete step the operator is authorized for carries an actionable control
    # (Scope F): a one-click POST where it is unambiguous (publish / promote), otherwise a
    # link to the on-page section that performs it (upload / build).
    _anchor = lambda href, label: {"type": "anchor", "href": href, "label": label}  # noqa: E731
    lifecycle_steps = [
        {
            "label": "Yüklendi",
            "complete": uploaded_complete,
            "detail": f"{len(latest_members)} doküman sürümü"
            if latest_members
            else "Henüz içerik yok",
            "action": _anchor("#uploads", "Dosya yükle")
            if can_write and not latest_members
            else None,
        },
        {
            "label": "Ayrıştırıldı / normalize edildi",
            "complete": parsed_complete,
            "detail": f"{parsed_count}/{len(latest_members)} hazır",
            "action": _anchor("#build", "İndeks oluştur (ayrıştırmayı çalıştırır)")
            if can_write and published_complete and not parsed_complete
            else None,
        },
        {
            "label": "Set taslağı",
            "complete": draft_complete,
            "detail": latest_version.status if latest_version else "Taslak yok",
            "action": None,
        },
        {
            "label": "Set sürümü yayımlandı",
            "complete": published_complete,
            "detail": "Yayımlandı" if published_complete else "Taslak üyelik değişebilir",
            "action": {"type": "post", "url": publish_url, "label": "Taslağı yayımla"}
            if can_write and is_draft_current and draft_complete
            else None,
        },
        {
            "label": "Staged indeks hazır",
            "complete": staged_ready,
            "detail": "İndeks sürümü mevcut" if staged_ready else "Promotable indeks yok",
            "action": _anchor("#build", "Staged indeks oluştur")
            if can_write and published_complete and not staged_ready
            else None,
        },
        {
            "label": "Aktif indeks",
            "complete": current_active_index is not None and staged_ready,
            "detail": f"İndeks v{current_active_index.version}"
            if current_active_index
            else (
                f"Güncel sürüm bekliyor; set v{serving_set_version.version} serviste"
                if serving_set_version is not None
                else "Serve edilmiyor"
            ),
            "action": {"type": "post", "url": promote_url, "label": "Promotable indeksi aktif et"}
            if can_promote_index and current_active_index is None and promotable_index is not None
            else (
                _anchor("#build", "Önce staged indeks oluştur")
                if can_write
                and published_complete
                and current_active_index is None
                and promotable_index is None
                else None
            ),
        },
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
    document_control_decision = authorize_operator(
        user=request.user,
        capability=OperatorCapability.DOCUMENT_SET_OPERATIONS_MANAGE,
        organization=document_set.organization,
        document_set=document_set,
    )
    platform_control_decision = authorize_operator(
        user=request.user,
        capability=OperatorCapability.PLATFORM_MANAGE,
        organization=document_set.organization,
        document_set=document_set,
    )
    can_quarantine = (
        document_control_decision.allowed
        and document_control_decision.source == AuthoritySource.DOCUMENT_SET_MANAGER
    ) or (
        platform_control_decision.allowed
        and platform_control_decision.source
        in {
            AuthoritySource.GLOBAL_ADMINISTRATOR,
            AuthoritySource.SUPERADMIN_RECOVERY,
        }
    )
    return render(
        request,
        "console/document_set_detail.html",
        {
            "title": f"Document set · {document_set.logical_id}",
            "organization": document_set.organization,
            "set": {
                "id": document_set.id,
                "public_id": document_set.public_id,
                "org": document_set.organization.slug,
                "logical_id": document_set.logical_id,
                "name": document_set.name,
                "status": document_set.status,
            },
            "current_version": current_version,
            "older_versions": older_versions,
            "latest_version": latest_version,
            "active_index": active_index,
            "lifecycle_steps": lifecycle_steps,
            "sources": document_set.connector_sources.order_by("name"),
            "bulk_upload_form": DocumentSetBulkUploadForm(),
            # The same choices render once per published set version; omit duplicate HTML ids.
            "build_form": DocumentSetBuildForm(
                organization_id=document_set.organization_id, auto_id=False
            ),
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
            "can_evaluate": authorize_operator(
                user=request.user,
                capability=OperatorCapability.DOCUMENT_SET_OPERATIONS_MANAGE,
                organization=document_set.organization,
                document_set=document_set,
            ).allowed,
            "can_promote_index": can_promote_index,
            "manager_assignments": document_set.manager_assignments.filter(
                status=DelegatedAssignmentStatus.ACTIVE
            )
            .select_related("user")
            .order_by("user__username", "user_id"),
            "can_manage_access": can_admin_org(request.user, document_set.organization_id),
            "can_quarantine": can_quarantine,
            "max_batch_files": int(getattr(settings, "DOCUMENTS_MAX_BATCH_UPLOAD_FILES", 20)),
        },
    )


@login_required
@require_POST
def document_set_quarantine_change(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    """Apply the separate document-set safety stop through its exact capability boundary."""

    document_set = _scoped_document_set(request.user, public_id=public_id)
    action = request.POST.get("action", "")
    if action not in {"quarantine", "restore"}:
        raise PermissionDenied
    try:
        document_services.set_document_set_quarantine(
            document_set=document_set,
            actor=request.user,
            quarantined=action == "quarantine",
            reason=request.POST.get("reason", ""),
        )
    except DocumentSetControlError as exc:
        if str(exc) == "DOCUMENT_SET_CONTROL_FORBIDDEN":
            raise PermissionDenied from exc
        messages.error(request, f"Doküman seti kontrolü reddedildi: {exc}")
    else:
        messages.success(
            request,
            "Doküman seti karantinaya alındı; yeni ingestion/indeks claim'leri durdu."
            if action == "quarantine"
            else "Doküman seti karantinadan çıkarıldı.",
        )
    return redirect("console:document_set_detail_public", public_id=document_set.public_id)


def _scoped_set_document(
    user: UserLike, document_set: DocumentSet, document_public_id: object
) -> Document:
    document = (
        scoping.scoped_documents(user)
        .filter(
            public_id=str(document_public_id),
            organization_id=document_set.organization_id,
            versions__memberships__document_set_version__document_set=document_set,
        )
        .select_related("source", "organization")
        .distinct()
        .first()
    )
    if document is None:
        raise Http404
    return document


@login_required
def document_set_document_detail(
    request: HttpRequest, public_id: object, document_public_id: object
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, public_id=public_id)
    document = _scoped_set_document(request.user, document_set, document_public_id)
    request.session[console_context.SESSION_KEY] = document_set.organization_id
    memberships = list(
        DocumentSetMembership.objects.filter(
            organization_id=document_set.organization_id,
            document_version__document=document,
            document_set_version__document_set=document_set,
        )
        .select_related("document_set_version", "document_version")
        .order_by("-document_set_version__version", "-document_version__version")
    )
    versions = list(document.versions.order_by("-version"))
    can_write = can_manage_documents(request.user, document.organization_id)
    chunk_view = _document_chunk_view(document_set, versions) if can_write else None
    return render(
        request,
        "console/document_set_document_detail.html",
        {
            "title": f"{document.title or document.logical_id} · {document_set.name}",
            "organization": document_set.organization,
            "set": document_set,
            "document": document,
            "versions": versions,
            "memberships": memberships,
            "replacement_form": DocumentReplacementForm(),
            "can_write": can_write,
            "chunk_view": chunk_view,
        },
    )


def _document_chunk_view(
    document_set: DocumentSet, versions: list[DocumentVersion]
) -> dict[str, object] | None:
    """Chunk count + bounded text preview for a document in the set's active served index.

    Authorized-operator inspection (Scope G): resolves the content-plane document versions to
    their chunks in the active per-``IndexVersion`` store (keyed by ``document_version_id``),
    under tenant RLS. PostgreSQL-only (the blue/green vector store is not built on SQLite);
    returns ``None`` off PostgreSQL, when nothing is served, or when the store is unavailable.
    Embeddings are never read; text is truncated in the database.
    """
    if connection.vendor != "postgresql" or not versions:
        return None
    active_index = (
        IndexVersion.objects.filter(
            document_set_version__document_set=document_set,
            organization_id=document_set.organization_id,
            status=IndexStatus.ACTIVE,
            store_ready=True,
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    if active_index is None:
        return None
    version_ids = [v.pk for v in versions]
    try:
        counts = chunk_counts_by_document(active_index, version_ids)
        if not counts:
            return {"index_version": active_index.version, "total_chunks": 0, "preview": []}
        target_vid = max(counts, key=lambda key: counts[key])
        preview = chunk_preview_for_document(active_index, target_vid, max_chunks=5, max_chars=600)
    except VectorStoreError:
        return None
    return {
        "index_version": active_index.version,
        "total_chunks": sum(counts.values()),
        "preview": [{"ordinal": ordinal, "text": text} for ordinal, text in preview],
    }


@login_required
@require_POST
def document_set_document_replace(
    request: HttpRequest, public_id: object, document_public_id: object
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, public_id=public_id)
    document = _scoped_set_document(request.user, document_set, document_public_id)
    if not can_manage_documents(request.user, document.organization_id):
        raise PermissionDenied
    form = DocumentReplacementForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Yeni sürüm yüklenemedi: bir dosya seçin.")
    else:
        upload = form.cleaned_data["file"]
        mime_type = _UPLOAD_MIME_BY_SUFFIX.get(Path(upload.name).suffix.lower(), "")
        try:
            draft = document_services.get_or_create_manual_draft(
                document_set=document_set,
                actor=request.user.get_username(),
                request_id=_request_id(request),
            )
            version = document_services.upload_document(
                organization=document.organization,
                logical_id=document.logical_id,
                title=document.title or Path(upload.name).stem,
                mime_type=mime_type,
                data=upload.read(),
                actor=request.user.get_username(),
                document_set_version=draft,
                source=document.source,
                request_id=_request_id(request),
            )
            messages.success(
                request, f"Yeni v{version.version} sürümü taslak v{draft.version}'e eklendi."
            )
        except (DocumentError, StorageError) as exc:
            messages.error(
                request, f"Yeni sürüm yüklenemedi: {getattr(exc, 'code', 'STORAGE_ERROR')}"
            )
    return redirect(
        "console:document_set_document_detail",
        public_id=document_set.public_id,
        document_public_id=document.public_id,
    )


@login_required
@require_POST
def document_set_remove_member(
    request: HttpRequest, version_pk: int, membership_pk: int
) -> HttpResponse:
    set_version = _scoped_set_version(request.user, version_pk)
    if not can_manage_documents(request.user, set_version.organization_id):
        raise PermissionDenied
    try:
        document_services.remove_document_from_set_draft(
            set_version=set_version,
            membership_id=membership_pk,
            actor=request.user.get_username(),
            request_id=_request_id(request),
        )
        messages.success(request, "Doküman taslaktan çıkarıldı; saklanan içerik silinmedi.")
    except DocumentError as exc:
        messages.error(request, f"Doküman çıkarılamadı: {exc.code}")
    return redirect(
        "console:document_set_detail_public", public_id=set_version.document_set.public_id
    )


@login_required
@require_POST
def document_set_document_tombstone(
    request: HttpRequest, public_id: object, document_public_id: object
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, public_id=public_id)
    document = _scoped_set_document(request.user, document_set, document_public_id)
    if not can_manage_documents(request.user, document.organization_id):
        raise PermissionDenied
    document_services.soft_delete_document(
        document,
        actor=request.user.get_username(),
        request_id=_request_id(request),
    )
    messages.success(
        request,
        "Doküman tombstone edildi; yayımlanmış sürümler ve saklanan baytlar korunuyor.",
    )
    return redirect(
        "console:document_set_document_detail",
        public_id=document_set.public_id,
        document_public_id=document.public_id,
    )


def _connector_context(
    request: HttpRequest,
    document_set: DocumentSet,
    *,
    contract_form: RestContractForm | None = None,
    preview_items: list[dict[str, object]] | None = None,
    preview_valid: bool = False,
) -> dict[str, object]:
    can_write = can_manage_documents(request.user, document_set.organization_id)
    can_promote = can_manage_document_set_operations(request.user, document_set)
    sources: list[dict[str, object]] = []
    source_qs = (
        scoping.scoped_connector_sources(request.user)
        .filter(document_set=document_set)
        .order_by("name", "slug")
    )
    for source in source_qs:
        latest_run: object | None
        if source.connector_type == ConnectorType.CONFLUENCE_DC:
            latest_run = source.confluence_sync_runs.order_by("-created_at", "-pk").first()
            confluence_profile = source.confluence_profile
            profile_label = (
                f"{confluence_profile.logical_id} · r{confluence_profile.revision}"
                if confluence_profile is not None
                else "—"
            )
            contract_label = "Confluence sayfa ağacı"
            config_summary = f"{len(source.connector_config.get('root_page_ids', []))} kök sayfa"
        else:
            latest_run = source.rest_sync_runs.order_by("-created_at", "-pk").first()
            rest_profile = source.rest_profile
            contract = source.rest_contract
            profile_label = (
                f"{rest_profile.logical_id} · r{rest_profile.revision}"
                if rest_profile is not None
                else "—"
            )
            contract_label = (
                f"{contract.logical_id} · r{contract.revision}" if contract is not None else "—"
            )
            config_summary = "Input değerleri güvenlik nedeniyle gösterilmez"
        schedule = getattr(source, "sync_schedule", None)
        schedule_initial = {
            "interval_seconds": schedule.interval_seconds if schedule else 86_400,
            "enabled": schedule.enabled if schedule else False,
            "automation_mode": (
                schedule.automation_mode if schedule else ScheduleAutomationMode.DRAFT_ONLY
            ),
            "embedding_profile": schedule.embedding_profile_id if schedule else None,
            "scenarios": (
                list(schedule.promotion_targets.values_list("scenario_id", flat=True))
                if schedule
                else []
            ),
        }
        sources.append(
            {
                "object": source,
                "type_label": (
                    "Confluence" if source.connector_type == ConnectorType.CONFLUENCE_DC else "REST"
                ),
                "profile_label": profile_label,
                "contract_label": contract_label,
                "config_summary": config_summary,
                "schedule": schedule,
                "schedule_form": ConnectorScheduleForm(
                    document_set=document_set,
                    allow_authoring=can_write,
                    allow_promotion=can_promote,
                    prefix=f"schedule-{source.pk}",
                    initial=schedule_initial,
                ),
                "latest_run": latest_run,
                "can_configure": can_write or can_promote,
            }
        )
    return {
        "set": document_set,
        "sources": sources,
        "can_write": can_write,
        "can_promote": can_promote,
        "confluence_form": ConfluenceSourceForm(document_set=document_set, prefix="confluence"),
        "contract_form": contract_form
        or RestContractForm(
            prefix="contract",
            initial={
                "revision": 1,
                "definition": json.dumps(_REST_CONTRACT_EXAMPLE, ensure_ascii=False, indent=2),
            },
        ),
        "rest_source_form": RestSourceForm(
            document_set=document_set,
            prefix="rest-source",
            initial={"inputs": "{}"},
        ),
        "preview_items": preview_items,
        "preview_valid": preview_valid,
    }


@login_required
@transaction.atomic
def document_set_connectors(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    set_tenant_context(document_set.organization_id)
    return render(
        request,
        "console/document_set_connectors.html",
        _connector_context(request, document_set),
    )


def _validate_rest_contract_preview(
    form: RestContractForm,
) -> tuple[list[dict[str, object]], bool]:
    definition = form.cleaned_data["definition"]
    validate_contract(definition)
    synthetic = form.cleaned_data.get("synthetic_response")
    if synthetic is None:
        return [], True
    items = preview_rest_response(definition, synthetic, max_items=20)
    return [
        {
            "external_id": item.external_id,
            "revision": item.revision,
            "title": item.title,
            "deleted": item.deleted,
        }
        for item in items
    ], True


def _clear_synthetic_response(form: RestContractForm) -> None:
    """Do not reflect synthetic document content after validation, including error responses."""
    data: dict[str, object] = {key: form.data[key] for key in form.data}
    data[form.add_prefix("synthetic_response")] = ""
    form.data = data


@login_required
@transaction.atomic
@require_POST
def rest_contract_preview(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    set_tenant_context(document_set.organization_id)
    if not can_manage_documents(request.user, document_set.organization_id):
        raise PermissionDenied
    form = RestContractForm(request.POST, prefix="contract")
    preview_items: list[dict[str, object]] = []
    preview_valid = False
    if form.is_valid():
        try:
            preview_items, preview_valid = _validate_rest_contract_preview(form)
        except (RestContractError, RestPullError) as exc:
            form.add_error("synthetic_response", f"Preview reddedildi: {exc.code}")
    _clear_synthetic_response(form)
    return render(
        request,
        "console/document_set_connectors.html",
        _connector_context(
            request,
            document_set,
            contract_form=form,
            preview_items=preview_items,
            preview_valid=preview_valid,
        ),
    )


@login_required
@transaction.atomic
@require_POST
def rest_contract_create(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    set_tenant_context(document_set.organization_id)
    if not can_manage_documents(request.user, document_set.organization_id):
        raise PermissionDenied
    form = RestContractForm(request.POST, prefix="contract")
    if form.is_valid():
        try:
            _validate_rest_contract_preview(form)
            contract = create_rest_contract(
                actor=request.user,
                organization=document_set.organization,
                logical_id=form.cleaned_data["logical_id"],
                revision=form.cleaned_data["revision"],
                definition=form.cleaned_data["definition"],
            )
            messages.success(
                request,
                f"REST sözleşmesi {contract.logical_id} r{contract.revision} oluşturuldu.",
            )
            return redirect(
                "console:document_set_connectors_public", public_id=document_set.public_id
            )
        except (RestAuthorizationError, RestServiceError, RestContractError, RestPullError) as exc:
            code = getattr(exc, "code", str(exc))
            form.add_error(None, f"Sözleşme oluşturulamadı: {code}")
    _clear_synthetic_response(form)
    return render(
        request,
        "console/document_set_connectors.html",
        _connector_context(request, document_set, contract_form=form),
    )


@login_required
@transaction.atomic
@require_POST
def confluence_source_create(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    set_tenant_context(document_set.organization_id)
    if not can_manage_documents(request.user, document_set.organization_id):
        raise PermissionDenied
    form = ConfluenceSourceForm(request.POST, document_set=document_set, prefix="confluence")
    if form.is_valid():
        try:
            create_confluence_source(
                actor=request.user,
                organization=document_set.organization,
                document_set=document_set,
                confluence_profile=form.cleaned_data["confluence_profile"],
                slug=form.cleaned_data["slug"],
                name=form.cleaned_data["name"],
                connector_config={
                    "root_page_ids": form.cleaned_data["root_page_ids"],
                    "excluded_page_ids": form.cleaned_data["excluded_page_ids"],
                    "include_root": form.cleaned_data["include_root"],
                },
            )
            messages.success(request, "Confluence kaynağı oluşturuldu.")
        except (ConfluenceAuthorizationError, ConfluenceServiceError) as exc:
            messages.error(request, f"Confluence kaynağı oluşturulamadı: {exc}")
    else:
        messages.error(request, "Confluence kaynağı formunu kontrol edin.")
    return redirect("console:document_set_connectors_public", public_id=document_set.public_id)


@login_required
@transaction.atomic
@require_POST
def rest_source_create(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    set_tenant_context(document_set.organization_id)
    if not can_manage_documents(request.user, document_set.organization_id):
        raise PermissionDenied
    form = RestSourceForm(request.POST, document_set=document_set, prefix="rest-source")
    if form.is_valid():
        try:
            create_rest_source(
                actor=request.user,
                organization=document_set.organization,
                document_set=document_set,
                rest_profile=form.cleaned_data["rest_profile"],
                rest_contract=form.cleaned_data["rest_contract"],
                slug=form.cleaned_data["slug"],
                name=form.cleaned_data["name"],
                inputs=form.cleaned_data["inputs"],
            )
            messages.success(request, "REST kaynağı oluşturuldu.")
        except (RestAuthorizationError, RestServiceError) as exc:
            messages.error(request, f"REST kaynağı oluşturulamadı: {exc}")
    else:
        messages.error(request, "REST kaynağı formunu kontrol edin.")
    return redirect("console:document_set_connectors_public", public_id=document_set.public_id)


def _scoped_connector_source(user: UserLike, source_pk: int) -> Source:
    source = scoping.scoped_connector_sources(user).filter(pk=source_pk).first()
    if source is None or source.document_set_id is None:
        raise Http404
    set_tenant_context(source.organization_id)
    return source


@login_required
@transaction.atomic
def connector_source_detail(request: HttpRequest, source_pk: int) -> HttpResponse:
    source = _scoped_connector_source(request.user, source_pk)
    document_set = source.document_set
    if document_set is None:
        raise Http404
    latest_run: ConfluenceSyncRun | RestSyncRun | None
    if source.connector_type == ConnectorType.CONFLUENCE_DC:
        latest_run = source.confluence_sync_runs.order_by("-created_at", "-pk").first()
        confluence_profile = source.confluence_profile
        profile_label = (
            f"{confluence_profile.logical_id} · r{confluence_profile.revision}"
            if confluence_profile
            else "—"
        )
        contract_label = "Confluence sayfa ağacı"
    else:
        latest_run = source.rest_sync_runs.order_by("-created_at", "-pk").first()
        rest_profile = source.rest_profile
        contract = source.rest_contract
        profile_label = (
            f"{rest_profile.logical_id} · r{rest_profile.revision}" if rest_profile else "—"
        )
        contract_label = f"{contract.logical_id} · r{contract.revision}" if contract else "—"
    versions = document_set.versions.order_by("-version", "-pk")
    draft_version = versions.filter(status=DocumentSetVersionStatus.DRAFT).first()
    published_version = versions.exclude(status=DocumentSetVersionStatus.DRAFT).first()
    indexes = IndexVersion.objects.filter(
        Q(source=source) | Q(document_set_version__document_set=document_set),
        organization_id=source.organization_id,
    ).order_by("-created_at", "-pk")
    staged_index = indexes.filter(
        status__in=[IndexStatus.BUILDING, IndexStatus.PROMOTABLE, IndexStatus.FAILED]
    ).first()
    active_index = indexes.filter(status=IndexStatus.ACTIVE).first()
    lifecycle = [
        {"label": "Kaynak bağlandı", "done": True, "detail": source.get_status_display()},
        {
            "label": "Senkron tamamlandı",
            "done": bool(latest_run and latest_run.snapshot_complete),
            "detail": latest_run.status if latest_run else "Henüz çalıştırılmadı",
        },
        {
            "label": "Taslak adayı üretildi",
            "done": draft_version is not None,
            "detail": f"v{draft_version.version}" if draft_version else "Değişiklik bekleniyor",
        },
        {
            "label": "Set sürümü yayımlandı",
            "done": published_version is not None,
            "detail": f"v{published_version.version}" if published_version else "Yayın bekleniyor",
        },
        {
            "label": "Staged indeks hazırlandı",
            "done": bool(staged_index and staged_index.status == IndexStatus.PROMOTABLE),
            "detail": staged_index.status if staged_index else "Build bekleniyor",
        },
        {
            "label": "Aktif indeks promote edildi",
            "done": active_index is not None,
            "detail": f"v{active_index.version}" if active_index else "Promotion bekleniyor",
        },
    ]
    return render(
        request,
        "console/connector_source_detail.html",
        {
            "source": source,
            "set": document_set,
            "latest_run": latest_run,
            "profile_label": profile_label,
            "contract_label": contract_label,
            "lifecycle": lifecycle,
            "draft_version": draft_version,
            "published_version": published_version,
            "staged_index": staged_index,
            "active_index": active_index,
            "can_write": can_manage_documents(request.user, source.organization_id),
        },
    )


@login_required
@require_POST
def connector_source_run(request: HttpRequest, source_pk: int) -> HttpResponse:
    source = _scoped_connector_source(request.user, source_pk)
    document_set = source.document_set
    if document_set is None:
        raise Http404
    if not can_manage_documents(request.user, source.organization_id):
        raise PermissionDenied
    try:
        if source.connector_type == ConnectorType.CONFLUENCE_DC:
            confluence_run = create_confluence_sync_run(actor=request.user, source=source)
            try:
                sync_confluence_source.apply_async(
                    args=[confluence_run.pk, source.organization_id], queue="ingestion"
                )
            except Exception:
                mark_confluence_dispatch_failed(run=confluence_run, actor=request.user)
                raise
            run_id = confluence_run.pk
        else:
            rest_run = create_rest_sync_run(actor=request.user, source=source)
            try:
                sync_rest_source.apply_async(
                    args=[rest_run.pk, source.organization_id], queue="ingestion"
                )
            except Exception:
                mark_rest_dispatch_failed(run=rest_run, actor=request.user)
                raise
            run_id = rest_run.pk
        messages.success(request, f"Senkron işi kuyruğa alındı (run #{run_id}).")
    except (
        ConfluenceAuthorizationError,
        ConfluenceServiceError,
        RestAuthorizationError,
        RestServiceError,
    ) as exc:
        messages.error(request, f"Senkron başlatılamadı: {exc}")
    except Exception:
        messages.error(request, "Senkron kuyruğuna erişilemedi; run başarısız kapatıldı.")
    return redirect("console:document_set_connectors_public", public_id=document_set.public_id)


@login_required
@transaction.atomic
@require_POST
def connector_schedule_configure(request: HttpRequest, source_pk: int) -> HttpResponse:
    source = _scoped_connector_source(request.user, source_pk)
    set_tenant_context(source.organization_id)
    document_set = source.document_set
    if document_set is None:
        raise Http404
    can_author = can_manage_documents(request.user, source.organization_id)
    can_promote = can_manage_document_set_operations(request.user, document_set)
    if not can_author and not can_promote:
        raise PermissionDenied
    requested_mode = request.POST.get(f"schedule-{source.pk}-automation_mode", "")
    if requested_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE and not can_promote:
        raise PermissionDenied
    if requested_mode != ScheduleAutomationMode.PROMOTE_IF_SAFE and not can_author:
        raise PermissionDenied
    form = ConnectorScheduleForm(
        request.POST,
        document_set=document_set,
        allow_authoring=can_author,
        allow_promotion=can_promote,
        prefix=f"schedule-{source.pk}",
    )
    if form.is_valid():
        try:
            interval = form.cleaned_data["interval_seconds"]
            configure_sync_schedule(
                actor=request.user,
                source=source,
                interval_seconds=interval,
                enabled=form.cleaned_data["enabled"],
                next_run_at=timezone.now() + timedelta(seconds=interval),
                automation_mode=form.cleaned_data["automation_mode"],
                embedding_profile=form.cleaned_data["embedding_profile"],
                scenarios=form.cleaned_data["scenarios"],
            )
            messages.success(request, "Kaynak yenileme planı güncellendi.")
        except (RestAuthorizationError, RestServiceError, ValueError) as exc:
            messages.error(request, f"Plan güncellenemedi: {exc}")
    else:
        messages.error(request, "Plan formunu ve rolünüze açık seçenekleri kontrol edin.")
    return redirect("console:document_set_connectors_public", public_id=document_set.public_id)


def _bulk_upload_metadata(files: list[object], document_set: DocumentSet) -> list[dict[str, str]]:
    """Derive bounded, stable metadata without trusting browser MIME declarations."""
    reserved: dict[str, str] = {
        item.logical_id: item.title
        for item in Document.objects.filter(organization_id=document_set.organization_id)
    }
    metadata: list[dict[str, str]] = []
    for upload in files:
        raw_name = Path(str(getattr(upload, "name", ""))).name
        suffix = Path(raw_name).suffix.lower()
        mime_type = _UPLOAD_MIME_BY_SUFFIX.get(suffix)
        if mime_type is None:
            raise DocumentError("FILE_EXTENSION_DENIED")
        title = Path(raw_name).stem.strip()[:500] or "Doküman"
        base = slugify(title.translate(_TURKISH_SLUG_TRANSLATION))[:128] or "dokuman"
        logical_id = base
        if logical_id in reserved and reserved[logical_id] != title:
            digest = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:10]
            logical_id = f"{base[:117]}-{digest}"
        if logical_id in reserved and reserved[logical_id] != title:
            raise DocumentError("GENERATED_ID_CONFLICT")
        if any(item["logical_id"] == logical_id for item in metadata):
            raise DocumentError("DUPLICATE_BATCH_DOCUMENT")
        reserved[logical_id] = title
        metadata.append({"logical_id": logical_id, "title": title, "mime_type": mime_type})
    return metadata


@login_required
@require_POST
def document_set_bulk_upload(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    if not can_manage_documents(request.user, document_set.organization_id):
        raise PermissionDenied
    form = DocumentSetBulkUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Yükleme başarısız: en az bir dosya seçin.")
        return redirect("console:document_set_detail_public", public_id=document_set.public_id)
    files = list(form.cleaned_data["uploads"])
    max_files = int(getattr(settings, "DOCUMENTS_MAX_BATCH_UPLOAD_FILES", 20))
    max_file_bytes = int(getattr(settings, "DOCUMENTS_MAX_UPLOAD_BYTES", 25_000_000))
    max_batch_bytes = int(getattr(settings, "DOCUMENTS_MAX_BATCH_UPLOAD_BYTES", 100_000_000))
    sizes = [int(getattr(upload, "size", 0)) for upload in files]
    if len(files) > max_files:
        messages.error(request, f"Yükleme başarısız: en fazla {max_files} dosya seçilebilir.")
        return redirect("console:document_set_detail_public", public_id=document_set.public_id)
    if any(size <= 0 or size > max_file_bytes for size in sizes):
        messages.error(
            request, "Yükleme başarısız: boş veya dosya boyutu sınırını aşan içerik var."
        )
        return redirect("console:document_set_detail_public", public_id=document_set.public_id)
    if sum(sizes) > max_batch_bytes:
        messages.error(request, "Yükleme başarısız: toplam batch boyutu sınırı aşıldı.")
        return redirect("console:document_set_detail_public", public_id=document_set.public_id)
    uploaded = 0
    try:
        metadata = _bulk_upload_metadata(files, document_set)
        draft = document_services.get_or_create_manual_draft(
            document_set=document_set, actor=request.user.get_username()
        )
        for upload, item in zip(files, metadata, strict=True):
            document_services.upload_document(
                organization=document_set.organization,
                logical_id=item["logical_id"],
                title=item["title"],
                mime_type=item["mime_type"],
                data=upload.read(),
                actor=request.user.get_username(),
                document_set_version=draft,
            )
            uploaded += 1
        messages.success(
            request, f"{uploaded} doküman yüklendi ve taslak v{draft.version} güncellendi."
        )
    except (DocumentError, StorageError) as exc:
        code = getattr(exc, "code", "OBJECT_STORE_UNAVAILABLE")
        if uploaded:
            messages.error(
                request,
                f"Toplu yükleme kısmen tamamlandı: {uploaded} dosya kaydedildi; "
                f"işlem durdu ({code}).",
            )
        else:
            messages.error(request, f"Yükleme başarısız: {code}")
    return redirect("console:document_set_detail_public", public_id=document_set.public_id)


@login_required
@require_POST
def document_set_build_index(request: HttpRequest, version_pk: int) -> HttpResponse:
    set_version = _scoped_set_version(request.user, version_pk)
    if not can_manage_documents(request.user, set_version.organization_id):
        raise PermissionDenied
    form = DocumentSetBuildForm(request.POST, organization_id=set_version.organization_id)
    if not form.is_valid():
        messages.error(request, "İndeks isteği reddedildi: tenant’a açık bir profil seçin.")
        return redirect(
            "console:document_set_detail_public", public_id=set_version.document_set.public_id
        )
    if set_version.status not in [
        DocumentSetVersionStatus.PROMOTABLE,
        DocumentSetVersionStatus.ACTIVE,
    ]:
        messages.error(request, "İndeks için önce taslak sürümü yayımlayın.")
        return redirect(
            "console:document_set_detail_public", public_id=set_version.document_set.public_id
        )
    profile = form.cleaned_data["embedding_profile"]
    ocr_profile = form.cleaned_data["ocr_profile"]
    try:
        from apps.ingestion.preparation import configure_preparation

        configure_preparation(
            document_set=set_version.document_set,
            embedding_profile=profile,
            ocr_profile=ocr_profile,
            chunking_profile=form.cleaned_data["chunking_profile"],
            retrieval_profile=form.cleaned_data["retrieval_profile"],
            summary_model_profile=form.cleaned_data["summary_model_profile"],
            summary_prompt_contract=form.cleaned_data["summary_prompt_contract"],
            auto_prepare=form.cleaned_data["auto_prepare"],
            actor=request.user.get_username(),
            request_id=request.headers.get("X-Request-ID", ""),
        )
        job, created = create_build_job(
            document_set_version=set_version,
            embedding_profile=profile,
            ocr_profile=ocr_profile,
            chunking_profile=form.cleaned_data["chunking_profile"],
            retrieval_profile=form.cleaned_data["retrieval_profile"],
            summary_model_profile=form.cleaned_data["summary_model_profile"],
            summary_prompt_contract=form.cleaned_data["summary_prompt_contract"],
            actor=request.user.get_username(),
            request_id=request.headers.get("X-Request-ID", ""),
        )
        messages.success(
            request,
            "İndeks oluşturma isteği kaydedildi; durum kalıcı olarak izlenebilir."
            if created
            else "Aynı indeks isteği zaten kayıtlı; mevcut iş gösteriliyor.",
        )
    except Exception:
        record_event(
            actor_type="user",
            actor_id=request.user.get_username(),
            action="ingestion.staged_index.dispatch_failed",
            outcome="failure",
            organization_id=set_version.organization_id,
            resource_type="document_set_version",
            resource_id=f"{set_version.document_set.logical_id}:v{set_version.version}",
            reason="queue_unavailable",
        )
        messages.error(request, "İndeks kuyruğuna erişilemedi; daha sonra yeniden deneyin.")
    return redirect(
        "console:document_set_detail_public", public_id=set_version.document_set.public_id
    )


def _scoped_build_job(user: UserLike, public_id: uuid.UUID) -> StagedIndexBuildJob:
    job = StagedIndexBuildJob.objects.filter(
        public_id=public_id,
        document_set_version__in=scoping.scoped_document_set_versions(user),
    ).first()
    if job is None:
        raise Http404
    set_tenant_context(job.organization_id)
    return job


def _require_build_job_author(request: HttpRequest, job: StagedIndexBuildJob, action: str) -> None:
    if can_manage_documents(request.user, job.organization_id):
        return
    record_event(
        actor_type="user",
        actor_id=request.user.get_username(),
        action="ingestion.staged_index.authorization_denied",
        outcome="failure",
        organization_id=job.organization_id,
        resource_type="staged_index_build_job",
        resource_id=str(job.public_id),
        reason=action,
    )
    raise PermissionDenied


@login_required
@require_POST
def document_set_cancel_build_job(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    job = _scoped_build_job(request.user, public_id)
    _require_build_job_author(request, job, "cancel")
    cancel_build_job(job=job, actor=request.user.get_username())
    messages.success(request, "İndeks işi iptal edildi; geç sonuçlar durumu değiştiremez.")
    return redirect(
        "console:document_set_detail_public",
        public_id=job.document_set_version.document_set.public_id,
    )


@login_required
@require_POST
def document_set_retry_build_job(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    job = _scoped_build_job(request.user, public_id)
    _require_build_job_author(request, job, "retry")
    try:
        retry_build_job(job=job, actor=request.user.get_username())
        messages.success(request, "İndeks işi güvenli yeniden deneme için kaydedildi.")
    except BuildJobError as exc:
        messages.error(request, f"İş yeniden denenemedi: {exc.code}")
    return redirect(
        "console:document_set_detail_public",
        public_id=job.document_set_version.document_set.public_id,
    )


@login_required
@require_POST
def document_set_promote_index(request: HttpRequest, index_pk: int) -> HttpResponse:
    index = (
        IndexVersion.objects.select_related("document_set_version__document_set")
        .filter(
            pk=index_pk,
            document_set_version__in=scoping.scoped_document_set_versions(request.user),
        )
        .first()
    )
    if index is None or index.document_set_version is None:
        raise Http404
    set_tenant_context(index.organization_id)
    if not can_manage_document_set_operations(
        request.user,
        index.document_set_version.document_set,
    ):
        raise PermissionDenied
    try:
        promote_staged_index(index, actor=request.user.get_username())
        messages.success(request, "Staged indeks aktif hale getirildi.")
    except StagedBuildError as exc:
        messages.error(request, f"Promotion başarısız: {exc.code}")
    return redirect(
        "console:document_set_detail_public",
        public_id=index.document_set_version.document_set.public_id,
    )


@login_required
@require_POST
def document_set_version_create(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    if not can_manage_documents(request.user, document_set.organization_id):
        raise PermissionDenied
    document_services.create_document_set_version(
        document_set=document_set, actor=request.user.get_username()
    )
    messages.success(request, "Draft version created.")
    return redirect("console:document_set_detail_public", public_id=document_set.public_id)


@login_required
@require_POST
def document_set_add_member(request: HttpRequest, version_pk: int) -> HttpResponse:
    set_version = _scoped_set_version(request.user, version_pk)
    if not can_manage_documents(request.user, set_version.organization_id):
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
        return redirect(
            "console:document_set_detail_public", public_id=set_version.document_set.public_id
        )
    try:
        document_services.add_document_to_set_version(
            set_version=set_version, document_version=version, actor=request.user.get_username()
        )
        messages.success(request, "Member added.")
    except DocumentError as exc:
        messages.error(request, f"Add member failed: {exc.code}")
    return redirect(
        "console:document_set_detail_public", public_id=set_version.document_set.public_id
    )


@login_required
@require_POST
def document_set_version_publish(request: HttpRequest, version_pk: int) -> HttpResponse:
    set_version = _scoped_set_version(request.user, version_pk)
    if not can_manage_documents(request.user, set_version.organization_id):
        raise PermissionDenied
    try:
        document_services.publish_document_set_version(
            set_version=set_version, actor=request.user.get_username()
        )
        messages.success(request, "Version published.")
    except DocumentError as exc:
        messages.error(request, f"Publish failed: {exc.code}")
    return redirect(
        "console:document_set_detail_public", public_id=set_version.document_set.public_id
    )


def _scoped_document_set(
    user: UserLike, pk: int | None = None, public_id: object = None
) -> DocumentSet:
    try:
        document_set = scoping.scoped_document_sets(user).get(
            **({"public_id": public_id} if public_id is not None else {"pk": pk})
        )
    except DocumentSet.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(document_set.organization_id)
    return document_set


def _scoped_set_version(user: UserLike, pk: int) -> DocumentSetVersion:
    try:
        set_version = scoping.scoped_document_set_versions(user).get(pk=pk)
    except DocumentSetVersion.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(set_version.organization_id)
    return set_version


@login_required
@require_POST
def document_set_bind_scenario(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    if not can_manage_documents(request.user, document_set.organization_id):
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
    return redirect("console:document_set_detail_public", public_id=document_set.public_id)


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
    set_tenant_context(binding.organization_id)
    if not can_manage_documents(request.user, binding.organization_id):
        raise PermissionDenied
    document_set_public_id = binding.document_set.public_id
    document_services.unbind_scenario_document_set(binding, actor=request.user.get_username())
    messages.success(request, "Scenario unbound. Recompile its release to apply the change.")
    return redirect("console:document_set_detail_public", public_id=document_set_public_id)


@login_required
@require_POST
def document_set_grant_consumer(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk, public_id)
    if not can_manage_documents(request.user, document_set.organization_id):
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
        messages.error(request, "İzin verilemedi: geçersiz istemci.")
    else:
        try:
            document_services.grant_document_set(
                document_set=document_set,
                principal_type=GrantPrincipalType.CONSUMER,
                principal_ref=str(consumer.id),
                actor=request.user.get_username(),
            )
            messages.success(request, "İstemci retrieval izni verildi.")
        except DocumentError as exc:
            messages.error(request, f"Grant failed: {exc.code}")
    return redirect("console:document_set_detail_public", public_id=document_set.public_id)


@login_required
@require_POST
def document_set_revoke_grant(request: HttpRequest, grant_pk: int) -> HttpResponse:
    grant = DocumentSetGrant.objects.select_related("document_set").filter(pk=grant_pk).first()
    if (
        grant is None
        or not scoping.scoped_document_sets(request.user).filter(pk=grant.document_set_id).exists()
    ):
        raise Http404
    set_tenant_context(grant.organization_id)
    if not can_manage_documents(request.user, grant.organization_id):
        raise PermissionDenied
    document_set_public_id = grant.document_set.public_id
    document_services.revoke_document_set_grant(grant, actor=request.user.get_username())
    messages.success(request, "İstemci retrieval izni kaldırıldı.")
    return redirect("console:document_set_detail_public", public_id=document_set_public_id)


def _operator_can_access_org(user: UserLike, organization_id: int) -> bool:
    allowed = allowed_organization_ids(user)
    return allowed is None or organization_id in allowed


def _operator_can_mutate_org(user: UserLike, organization_id: int) -> bool:
    return (
        _operator_can_access_org(user, organization_id)
        and Organization.objects.filter(
            pk=organization_id, status=OrganizationStatus.ACTIVE
        ).exists()
    )


def _create(
    request: HttpRequest,
    *,
    form_class: type,
    title: str,
    resource_type: str,
    permission: Callable[[int | None], bool],
    success_url: str,
    initial: dict[str, object] | None = None,
) -> HttpResponse:
    form = form_class(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        instance = None
        organization_id = None
        if resource_type == "organization":
            organization_id = None
        elif resource_type in {"project", "scenario"}:
            parent = form.cleaned_data["organization" if resource_type == "project" else "project"]
            organization_id = parent.pk if resource_type == "project" else parent.organization_id
        else:
            instance = form.save(commit=False)
            organization_id = getattr(instance, "organization_id", None)
            if resource_type == "binding":
                organization_id = instance.consumer.organization_id
        if not permission(organization_id):
            raise PermissionDenied
        try:
            with transaction.atomic():
                if resource_type == "organization":
                    instance = create_console_organization(
                        name=form.cleaned_data["name"],
                        status=form.cleaned_data["status"],
                        initial_admin=request.user,
                    )
                    organization_id = instance.pk
                elif resource_type == "project":
                    instance = create_console_project(
                        organization=form.cleaned_data["organization"],
                        name=form.cleaned_data["name"],
                        owner_membership=form.cleaned_data["owner_membership"],
                        risk_level=form.cleaned_data["risk_level"],
                        status=form.cleaned_data["status"],
                    )
                elif resource_type == "scenario":
                    instance = create_console_scenario(
                        project=form.cleaned_data["project"],
                        name=form.cleaned_data["name"],
                        visibility=form.cleaned_data["visibility"],
                        risk_level=form.cleaned_data["risk_level"],
                        status=form.cleaned_data["status"],
                    )
                elif resource_type == "consumer":
                    instance = create_console_consumer(
                        organization=form.cleaned_data["organization"],
                        name=form.cleaned_data["name"],
                        protocol=form.cleaned_data["protocol"],
                        status=form.cleaned_data["status"],
                    )
                else:
                    instance = form.save()
                if organization_id is None or instance is None:
                    raise PermissionDenied
                _audit_create(request, resource_type, str(instance.pk), organization_id)
        except IdentifierAllocationError:
            form.add_error(None, IdentifierAllocationError.code)
        except ConsumerSubjectAllocationError:
            form.add_error(None, ConsumerSubjectAllocationError.code)
        except ProjectOwnerError:
            form.add_error(
                "owner_membership", "Seçilen proje sahibi artık bu organizasyona atanamaz."
            )
        else:
            if resource_type == "organization":
                organization = cast(Organization, instance)
                request.session[console_context.SESSION_KEY] = organization.pk
                return redirect("console:organization_detail", slug=organization.slug)
            if resource_type == "project":
                project = cast(AIProject, instance)
                return redirect("console:project_detail_public", public_id=project.public_id)
            if resource_type == "scenario":
                scenario = cast(Scenario, instance)
                return redirect("console:scenario_detail_public", public_id=scenario.public_id)
            if resource_type == "consumer":
                consumer = cast(Consumer, instance)
                return redirect("console:consumer_detail_public", public_id=consumer.public_id)
            return redirect(success_url)
    return render(request, "console/form.html", {"title": title, "form": form})


@login_required
def organization_create(request: HttpRequest) -> HttpResponse:
    if not can_create_organization(request.user):
        record_event(
            actor_type="user",
            actor_id=request.user.get_username(),
            action="console.organization.create",
            outcome="deny",
            resource_type="organization",
            reason="PLATFORM_ADMIN_REQUIRED",
            request_id=_request_id(request),
            trace_id=_trace_id(request),
        )
        raise PermissionDenied
    return _create(
        request,
        form_class=OrganizationForm,
        title="Yeni organizasyon",
        resource_type="organization",
        permission=lambda _org_id: True,
        success_url="console:organizations",
    )


@login_required
def project_create(request: HttpRequest) -> HttpResponse:
    organization = console_context.resolve_active_organization(request)
    if organization is None or not can_admin_org(request.user, organization.pk):
        raise PermissionDenied
    form = ProjectForm(request.POST or None, user=request.user, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                project = create_console_project(
                    organization=organization,
                    name=form.cleaned_data["name"],
                    owner_membership=form.cleaned_data["owner_membership"],
                    risk_level=form.cleaned_data["risk_level"],
                    status=form.cleaned_data["status"],
                )
                _audit_create(request, "project", str(project.pk), organization.pk)
        except IdentifierAllocationError:
            form.add_error(None, IdentifierAllocationError.code)
        except ProjectOwnerError:
            form.add_error("owner_membership", "Seçilen proje sahibi artık atanamaz.")
        else:
            return redirect("console:project_detail_public", public_id=project.public_id)
    return render(request, "console/form.html", {"title": "Yeni proje", "form": form})


@login_required
def scenario_create(
    request: HttpRequest, project_public_id: uuid.UUID | None = None
) -> HttpResponse:
    if project_public_id is None:
        requested_project = (
            request.GET.get("project", "").strip() if request.method == "GET" else ""
        )
        if not requested_project:
            return redirect("console:projects")
        try:
            contextual_project_id = uuid.UUID(requested_project)
        except ValueError as exc:
            raise Http404 from exc
        return redirect("console:project_scenario_create", project_public_id=contextual_project_id)
    project = scoping.scoped_projects(request.user).filter(public_id=project_public_id).first()
    if project is None:
        raise Http404
    if not can_author_scenarios(request.user, project.organization_id):
        raise PermissionDenied
    form = ScenarioForm(request.POST or None, user=request.user, project=project)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                scenario = create_console_scenario(
                    project=project,
                    name=form.cleaned_data["name"],
                )
                logical_id = f"{scenario.slug}_workflow"
                builder_services.create_draft(
                    organization=project.organization,
                    project=project,
                    scenario=scenario,
                    name=f"{scenario.name} workflow",
                    logical_id=logical_id,
                    logical_description=form.cleaned_data["logical_description"],
                    body=_scenario_preset_body(form.cleaned_data["preset"], logical_id=logical_id),
                    actor=request.user.get_username(),
                    request_id=_request_id(request),
                )
                _audit_create(request, "scenario", str(scenario.pk), project.organization_id)
        except (BuilderError, ValueError):
            form.add_error(None, "Preset canonical workflow compiler tarafından reddedildi.")
        except IdentifierAllocationError:
            form.add_error(None, IdentifierAllocationError.code)
        else:
            return redirect("console:scenario_detail_public", public_id=scenario.public_id)
    return render(
        request,
        "console/scenario_create.html",
        {"title": "Yeni senaryo", "form": form, "project": project},
    )


@login_required
def consumer_create(request: HttpRequest) -> HttpResponse:
    organization = console_context.resolve_active_organization(request)
    if organization is None or not can_admin_org(request.user, organization.pk):
        raise PermissionDenied
    form = ConsumerForm(request.POST or None, user=request.user, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                consumer = create_console_consumer(
                    organization=organization,
                    name=form.cleaned_data["name"],
                    protocol=form.cleaned_data["protocol"],
                    status=form.cleaned_data["status"],
                )
                _audit_create(request, "consumer", str(consumer.pk), organization.pk)
        except ConsumerSubjectAllocationError:
            form.add_error(None, ConsumerSubjectAllocationError.code)
        else:
            return redirect("console:consumer_detail_public", public_id=consumer.public_id)
    return render(request, "console/form.html", {"title": "Yeni istemci", "form": form})


@login_required
def binding_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=BindingForm,
        title="Yeni istemci bağı",
        resource_type="binding",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:consumers",
    )


# --- Phase 2.8 Part 6 question sets and evaluation ----------------------------


def _active_question_organization(request: HttpRequest) -> Organization:
    organization = console_context.resolve_active_organization(request)
    if organization is None:
        raise Http404
    return organization


def _scoped_question_set(request: HttpRequest, public_id: uuid.UUID) -> QuestionSet:
    queryset = QuestionSet.objects.select_related("organization").filter(public_id=public_id)
    organization_ids = allowed_organization_ids(request.user)
    if organization_ids is not None:
        queryset = queryset.filter(organization_id__in=organization_ids)
    question_set = queryset.first()
    if question_set is None or not can_read_question_sets(request.user, question_set.organization):
        raise Http404
    request.session[console_context.SESSION_KEY] = question_set.organization_id
    return question_set


def _question_version_choices(question_set: QuestionSet) -> list[tuple[str, str]]:
    return [
        (
            str(version.public_id),
            f"v{version.version} · {version.case_count} vaka · {version.checksum[:12]}",
        )
        for version in question_set.versions.order_by("-version")
    ]


def _retrieval_target_choices(
    request: HttpRequest, organization: Organization
) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    indexes = (
        IndexVersion.objects.select_related(
            "document_set_version__document_set", "retrieval_profile"
        )
        .filter(
            organization=organization,
            document_set_version__status__in=[
                DocumentSetVersionStatus.PROMOTABLE,
                DocumentSetVersionStatus.ACTIVE,
            ],
            status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
            store_ready=True,
            retrieval_profile__isnull=False,
        )
        .order_by("document_set_version__document_set__name", "-version")[:100]
    )
    for index in indexes:
        set_version = index.document_set_version
        profile = index.retrieval_profile
        if set_version is None or profile is None:
            continue
        if not authorize_operator(
            user=request.user,
            capability=OperatorCapability.DOCUMENT_SET_OPERATIONS_MANAGE,
            organization=organization,
            document_set=set_version.document_set,
        ).allowed:
            continue
        choices.append(
            (
                f"{set_version.pk}:{index.pk}:{profile.pk}",
                (
                    f"{set_version.document_set.name} · set v{set_version.version} · "
                    f"index v{index.version} ({index.status}) · {profile.ref}"
                ),
            )
        )
    return choices


def _answer_target_choices(
    request: HttpRequest, organization: Organization
) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    releases = (
        ScenarioRelease.objects.select_related("scenario__project")
        .filter(
            organization=organization,
            status__in=[ReleaseStatus.CANDIDATE, ReleaseStatus.ACTIVE],
        )
        .order_by("scenario__name", "-created_at")[:100]
    )
    for release in releases:
        if authorize_operator(
            user=request.user,
            capability=OperatorCapability.SCENARIO_TEST,
            organization=organization,
            project=release.scenario.project,
            scenario=release.scenario,
        ).allowed:
            choices.append(
                (
                    str(release.pk),
                    f"{release.scenario.name} · release #{release.pk} ({release.status})",
                )
            )
    return choices


@login_required
def question_sets(request: HttpRequest) -> HttpResponse:
    organization = _active_question_organization(request)
    if not can_read_question_sets(request.user, organization):
        raise Http404
    form = QuestionSetDraftForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            question_set = create_question_set(
                organization=organization,
                user=request.user,
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                cases=form.cleaned_data["cases_json"],
                request_id=_request_id(request),
            )
        except QuestionEvaluationError as exc:
            form.add_error(None, exc.code)
        else:
            messages.success(request, "Soru seti taslağı oluşturuldu.")
            return redirect("console:question_set_detail", public_id=question_set.public_id)
    if request.method == "GET":
        form = QuestionSetDraftForm(
            initial={
                "cases_json": json.dumps(
                    [
                        {
                            "id": "case-1",
                            "question": "Sorunuzu yazın",
                            "input": {},
                            "assertions": [],
                            "expected_anchors": [],
                        }
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            }
        )
    return render(
        request,
        "console/question_sets.html",
        {
            "title": "Soru setleri",
            "organization": organization,
            "question_sets": QuestionSet.objects.filter(organization=organization).order_by("name"),
            "runs": QuestionEvaluationRun.objects.filter(organization=organization)
            .select_related("question_set_version__question_set")
            .order_by("-created_at")[:30],
            "form": form,
            "can_write": can_manage_question_sets(request.user, organization),
        },
    )


@login_required
def question_set_detail(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    question_set = _scoped_question_set(request, public_id)
    versions = list(question_set.versions.prefetch_related("cases").order_by("-version"))
    version_choices = _question_version_choices(question_set)
    retrieval_choices = _retrieval_target_choices(request, question_set.organization)
    answer_choices = _answer_target_choices(request, question_set.organization)
    return render(
        request,
        "console/question_set_detail.html",
        {
            "title": question_set.name,
            "question_set": question_set,
            "versions": versions,
            "draft_form": QuestionSetDraftForm(
                initial={
                    "name": question_set.name,
                    "description": question_set.description,
                    "cases_json": json.dumps(
                        question_set.draft_cases, ensure_ascii=False, indent=2
                    ),
                    "expected_revision": question_set.draft_revision,
                }
            ),
            "retrieval_form": EvaluationTargetForm(
                version_choices=version_choices,
                target_choices=retrieval_choices,
                initial={"idempotency_key": str(uuid.uuid4())},
            ),
            "answer_form": EvaluationTargetForm(
                version_choices=version_choices,
                target_choices=answer_choices,
                initial={"idempotency_key": str(uuid.uuid4())},
            ),
            "can_write": can_manage_question_sets(request.user, question_set.organization),
            "retrieval_targets_available": bool(retrieval_choices),
            "answer_targets_available": bool(answer_choices),
            "runs": QuestionEvaluationRun.objects.filter(
                organization=question_set.organization,
                question_set_version__question_set=question_set,
            ).order_by("-created_at")[:30],
        },
    )


@login_required
@require_POST
def question_set_update(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    question_set = _scoped_question_set(request, public_id)
    form = QuestionSetDraftForm(request.POST)
    if form.is_valid():
        try:
            update_question_set_draft(
                question_set=question_set,
                user=request.user,
                expected_revision=form.cleaned_data["expected_revision"],
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                cases=form.cleaned_data["cases_json"],
                request_id=_request_id(request),
            )
        except QuestionEvaluationError as exc:
            messages.error(request, exc.code)
        else:
            messages.success(request, "Soru seti taslağı güncellendi.")
    else:
        messages.error(request, "Soru seti taslağı geçerli değil.")
    return redirect("console:question_set_detail", public_id=question_set.public_id)


@login_required
@require_POST
def question_set_publish(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    question_set = _scoped_question_set(request, public_id)
    try:
        expected_revision = int(request.POST.get("expected_revision", ""))
        version = publish_question_set(
            question_set=question_set,
            user=request.user,
            expected_revision=expected_revision,
            request_id=_request_id(request),
        )
    except (ValueError, QuestionEvaluationError) as exc:
        code = exc.code if isinstance(exc, QuestionEvaluationError) else "REVISION_INVALID"
        messages.error(request, code)
    else:
        messages.success(request, f"Soru seti v{version.version} yayımlandı.")
    return redirect("console:question_set_detail", public_id=question_set.public_id)


def _dispatch_question_evaluation(run: QuestionEvaluationRun) -> None:
    try:
        execute_question_evaluation_task.delay(organization_id=run.organization_id, run_id=run.pk)
    except Exception:
        run.status = QuestionEvaluationStatus.FAILED
        run.error_code = "QUEUE_DISPATCH_FAILED"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_code", "finished_at", "updated_at"])


@login_required
@require_POST
def question_set_start_retrieval(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    question_set = _scoped_question_set(request, public_id)
    form = EvaluationTargetForm(
        request.POST,
        version_choices=_question_version_choices(question_set),
        target_choices=_retrieval_target_choices(request, question_set.organization),
    )
    if not form.is_valid():
        messages.error(request, "Retrieval değerlendirme hedefi geçerli değil.")
        return redirect("console:question_set_detail", public_id=question_set.public_id)
    try:
        set_version_id, index_id, profile_id = (
            int(value) for value in form.cleaned_data["target"].split(":")
        )
        version = QuestionSetVersion.objects.get(
            public_id=form.cleaned_data["question_set_version"],
            question_set=question_set,
            organization=question_set.organization,
        )
        set_version = DocumentSetVersion.objects.select_related("document_set").get(
            pk=set_version_id, organization=question_set.organization
        )
        index = IndexVersion.objects.get(pk=index_id, organization=question_set.organization)
        profile = ArtifactVersion.objects.get(pk=profile_id, organization=question_set.organization)
        run, created = create_retrieval_evaluation(
            user=request.user,
            question_set_version=version,
            document_set_version=set_version,
            index_version=index,
            retrieval_profile=profile,
            idempotency_key=form.cleaned_data["idempotency_key"],
            request_id=_request_id(request),
        )
    except (
        ValueError,
        QuestionSetVersion.DoesNotExist,
        DocumentSetVersion.DoesNotExist,
        IndexVersion.DoesNotExist,
        ArtifactVersion.DoesNotExist,
        QuestionEvaluationError,
    ) as exc:
        raise Http404 from exc
    if created:
        _dispatch_question_evaluation(run)
    return redirect("console:question_evaluation_detail", public_id=run.public_id)


@login_required
@require_POST
def question_set_start_answer(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    question_set = _scoped_question_set(request, public_id)
    form = EvaluationTargetForm(
        request.POST,
        version_choices=_question_version_choices(question_set),
        target_choices=_answer_target_choices(request, question_set.organization),
    )
    if not form.is_valid():
        messages.error(request, "Cevap değerlendirme hedefi geçerli değil.")
        return redirect("console:question_set_detail", public_id=question_set.public_id)
    try:
        version = QuestionSetVersion.objects.get(
            public_id=form.cleaned_data["question_set_version"],
            question_set=question_set,
            organization=question_set.organization,
        )
        release = ScenarioRelease.objects.select_related("scenario__project").get(
            pk=int(form.cleaned_data["target"]),
            organization=question_set.organization,
        )
        run, created = create_answer_evaluation(
            user=request.user,
            question_set_version=version,
            release=release,
            idempotency_key=form.cleaned_data["idempotency_key"],
            request_id=_request_id(request),
        )
    except (
        ValueError,
        QuestionSetVersion.DoesNotExist,
        ScenarioRelease.DoesNotExist,
        QuestionEvaluationError,
    ) as exc:
        raise Http404 from exc
    if created:
        _dispatch_question_evaluation(run)
    return redirect("console:question_evaluation_detail", public_id=run.public_id)


def _scoped_question_run(request: HttpRequest, public_id: uuid.UUID) -> QuestionEvaluationRun:
    queryset = QuestionEvaluationRun.objects.select_related(
        "organization",
        "question_set_version__question_set",
        "document_set_version__document_set",
        "index_version",
        "release__scenario__project",
    ).filter(public_id=public_id)
    organization_ids = allowed_organization_ids(request.user)
    if organization_ids is not None:
        queryset = queryset.filter(organization_id__in=organization_ids)
    run = queryset.first()
    if run is None:
        raise Http404
    request.session[console_context.SESSION_KEY] = run.organization_id
    return run


def _run_content_access(request: HttpRequest, run: QuestionEvaluationRun) -> bool:
    if run.kind == QuestionEvaluationKind.RETRIEVAL and run.document_set_version:
        return authorize_operator(
            user=request.user,
            capability=OperatorCapability.DOCUMENT_SET_CONTENT_READ,
            organization=run.organization,
            document_set=run.document_set_version.document_set,
        ).allowed
    if run.kind == QuestionEvaluationKind.ANSWER and run.release:
        return authorize_operator(
            user=request.user,
            capability=OperatorCapability.SCENARIO_TEST,
            organization=run.organization,
            project=run.release.scenario.project,
            scenario=run.release.scenario,
        ).allowed
    return False


@login_required
def question_evaluation_detail(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    run = _scoped_question_run(request, public_id)
    can_view_content = _run_content_access(request, run)
    evidence_status = request.GET.get("evidence_status", "")
    allowed_evidence_statuses = {
        QuestionEvaluationEvidenceStatus.FAILED,
        QuestionEvaluationEvidenceStatus.UNSCORED,
        QuestionEvaluationEvidenceStatus.ERROR,
    }
    evidence_queryset = run.case_evidence.select_related("question_case").order_by("ordinal")
    if evidence_status in allowed_evidence_statuses:
        evidence_queryset = evidence_queryset.filter(status=evidence_status)
    else:
        evidence_status = ""
    evidence_rows = list(evidence_queryset)
    for evidence in evidence_rows:
        evidence.resolved_chunks = []  # type: ignore[attr-defined]
        if (
            can_view_content
            and run.kind == QuestionEvaluationKind.RETRIEVAL
            and run.index_version is not None
        ):
            for item in evidence.retrieval_evidence:
                text = None
                document_version_id = item.get("document_version_id")
                ordinal = item.get("ordinal")
                if isinstance(document_version_id, int) and isinstance(ordinal, int):
                    try:
                        text = exact_chunk_text(run.index_version, document_version_id, ordinal)
                    except VectorStoreError:
                        text = None
                evidence.resolved_chunks.append(  # type: ignore[attr-defined]
                    {"evidence": item, "text": text}
                )
    return render(
        request,
        "console/question_evaluation_detail.html",
        {
            "title": "Değerlendirme sonucu",
            "run": run,
            "evidence_rows": evidence_rows,
            "can_view_content": can_view_content,
            "evidence_status": evidence_status,
        },
    )


@login_required
@require_POST
def question_evaluation_cancel(request: HttpRequest, public_id: uuid.UUID) -> HttpResponse:
    run = _scoped_question_run(request, public_id)
    try:
        request_evaluation_cancellation(run=run, user=request.user, request_id=_request_id(request))
    except QuestionEvaluationError as exc:
        raise Http404 from exc
    messages.success(request, "Değerlendirme iptal isteği kaydedildi.")
    return redirect("console:question_evaluation_detail", public_id=run.public_id)


@login_required
@require_POST
def document_set_ask(request: HttpRequest, public_id: object) -> HttpResponse:
    document_set = _scoped_document_set(request.user, None, public_id)
    form = OneOffQuestionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Soru geçerli değil.")
        return redirect("console:document_set_detail_public", public_id=document_set.public_id)
    set_version = (
        document_set.versions.select_related("built_index_version__retrieval_profile")
        .filter(status=DocumentSetVersionStatus.ACTIVE)
        .order_by("-version")
        .first()
    )
    index = set_version.built_index_version if set_version else None
    profile = index.retrieval_profile if index else None
    if set_version is None or index is None or profile is None:
        messages.error(request, "Aktif exact index/retrieval profili bulunamadı.")
        return redirect("console:document_set_detail_public", public_id=document_set.public_id)
    try:
        result = ask_document_set_once(
            user=request.user,
            document_set_version=set_version,
            index_version=index,
            retrieval_profile=profile,
            question=form.cleaned_data["question"],
        )
    except QuestionEvaluationError as exc:
        raise Http404 from exc
    return render(
        request,
        "console/one_off_question_result.html",
        {
            "title": "Belge retrieval sonucu",
            "question": form.cleaned_data["question"],
            "result": result,
            "back_url": reverse(
                "console:document_set_detail_public", args=[document_set.public_id]
            ),
        },
    )


@login_required
@require_POST
def scenario_ask(request: HttpRequest, public_id: object) -> HttpResponse:
    scenario = _scoped_scenario(request.user, None, public_id)
    form = OneOffQuestionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Soru geçerli değil.")
        return redirect("console:scenario_detail_public", public_id=scenario.public_id)
    release = ScenarioRelease.objects.filter(scenario=scenario, status=ReleaseStatus.ACTIVE).first()
    if release is None:
        messages.error(request, "Aktif release bulunamadı.")
        return redirect("console:scenario_detail_public", public_id=scenario.public_id)
    try:
        result = ask_scenario_once(
            user=request.user,
            release=release,
            question=form.cleaned_data["question"],
        )
    except QuestionEvaluationError as exc:
        raise Http404 from exc
    return render(
        request,
        "console/one_off_question_result.html",
        {
            "title": "Senaryo cevabı",
            "question": form.cleaned_data["question"],
            "result": result,
            "back_url": reverse("console:scenario_detail_public", args=[scenario.public_id]),
        },
    )
