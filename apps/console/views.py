"""Operator console views (server-rendered, tenant-scoped, login required).

Authentication is handled by Django's auth backends — LDAP in production (ADR-0001)
or the local model backend when LDAP is disabled. Authorization scope for every
screen comes from :mod:`apps.console.scoping`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import cast

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST

from apps.agents.models import AgentRun
from apps.agents.services import AgentRequestError, operator_cancel_agent_run
from apps.artifacts.models import ArtifactVersion
from apps.audit.services import record_event
from apps.builder.models import WorkflowDraft
from apps.catalog.models import AIProject, Scenario
from apps.catalog.services import ProjectOwnerError, create_console_project, create_console_scenario
from apps.console import scoping
from apps.console.forms import (
    BindingForm,
    CanaryForm,
    ConfluenceSourceForm,
    ConnectorScheduleForm,
    ConsumerForm,
    ConsumerTokenIssueForm,
    DocumentReplacementForm,
    DocumentSetBuildForm,
    DocumentSetBulkUploadForm,
    DocumentSetForm,
    DocumentUploadForm,
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
from apps.documents.services import DocumentError
from apps.documents.storage import StorageError
from apps.evaluations.services import EvalError, run_eval
from apps.identity.credentials import (
    ConsumerSubjectAllocationError,
    CredentialLifecycleError,
    create_console_consumer,
    issue_consumer_token,
    revoke_consumer_token,
    rotate_consumer_token,
)
from apps.identity.models import BindingStatus, Consumer, ConsumerBinding, ConsumerStatus
from apps.ingestion.confluence_services import (
    ConfluenceAuthorizationError,
    ConfluenceServiceError,
    create_confluence_source,
    create_confluence_sync_run,
    mark_confluence_dispatch_failed,
)
from apps.ingestion.models import (
    ConnectorType,
    IndexStatus,
    IndexVersion,
    ScheduleAutomationMode,
    Source,
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
from apps.ingestion.tasks import (
    build_document_set_index_task,
    sync_confluence_source,
    sync_rest_source,
)
from apps.ingestion.vector_store import set_tenant_context
from apps.releases.lifecycle import LifecycleError, promote, rollback, start_canary, stop_canary
from apps.releases.models import CanaryStatus, ReleaseCanary, ReleaseStatus, ScenarioRelease
from apps.tenancy.identifiers import IdentifierAllocationError
from apps.tenancy.models import Organization, OrganizationMembership, OrganizationStatus
from apps.tenancy.services import (
    UserLike,
    admin_organization_ids,
    allowed_organization_ids,
    author_organization_ids,
    can_admin_org,
    can_author_scenarios,
    can_create_organization,
    can_manage_releases,
    create_console_organization,
    is_platform_admin,
)
from apps.tools.approvals import ToolApprovalError, cancel_invocation, decide_approval
from apps.tools.authz import resolve_actor_roles
from apps.tools.models import ApprovalRequest, ApprovalStatus, ToolInvocation
from apps.workflows.compiler import BUILTIN_NODE_TYPES, MAX_EDGES, MAX_NODES

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


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    user = request.user
    organizations_qs = scoping.scoped_organizations(user).order_by("name", "slug")
    context = {
        "is_platform_admin": is_platform_admin(user),
        "organizations": organizations_qs,
        "counts": {
            "organizations": organizations_qs.count(),
            "projects": scoping.scoped_projects(user).count(),
            "scenarios": scoping.scoped_scenarios(user).count(),
            "consumers": scoping.scoped_consumers(user).count(),
            "artifacts": scoping.scoped_artifacts(user).count(),
            "releases": scoping.scoped_releases(user).count(),
        },
    }
    return render(request, "console/dashboard.html", context)


def _scoped_organization(user: UserLike, slug: str) -> Organization:
    try:
        organization = scoping.scoped_organizations(user).get(slug=slug)
    except Organization.DoesNotExist as exc:
        raise Http404 from exc
    set_tenant_context(organization.pk)
    return organization


@login_required
def organization_detail(request: HttpRequest, slug: str) -> HttpResponse:
    organization = _scoped_organization(request.user, slug)
    projects_qs = AIProject.objects.filter(organization=organization).order_by("name", "slug")
    scenarios_qs = Scenario.objects.filter(organization=organization).select_related("project")
    document_sets_qs = DocumentSet.objects.filter(organization=organization).order_by(
        "name", "logical_id"
    )
    consumers_qs = Consumer.objects.filter(organization=organization).order_by("name", "subject")
    artifacts_qs = ArtifactVersion.objects.filter(organization=organization).order_by(
        "type", "logical_id", "-version"
    )
    releases_qs = ScenarioRelease.objects.filter(organization=organization).select_related(
        "scenario", "scenario__project"
    )
    memberships_qs = OrganizationMembership.objects.filter(
        organization=organization
    ).select_related("user")
    runs_qs = AgentRun.objects.filter(organization=organization).select_related(
        "scenario", "consumer"
    )
    list_limit = 100
    inventories = {
        "projects": list(projects_qs[:list_limit]),
        "scenarios": list(scenarios_qs.order_by("project__name", "name")[:list_limit]),
        "document_sets": list(document_sets_qs[:list_limit]),
        "consumers": list(consumers_qs[:list_limit]),
        "artifacts": list(artifacts_qs[:list_limit]),
        "releases": list(releases_qs.order_by("-created_at", "-pk")[:list_limit]),
        "memberships": list(memberships_qs.order_by("user__username")[:list_limit]),
        "runs": list(runs_qs.order_by("-created_at")[:50]),
    }
    counts = {
        "projects": projects_qs.count(),
        "scenarios": scenarios_qs.count(),
        "document_sets": document_sets_qs.count(),
        "consumers": consumers_qs.count(),
        "artifacts": artifacts_qs.count(),
        "releases": releases_qs.count(),
        "memberships": memberships_qs.count(),
        "runs": runs_qs.count(),
    }
    return render(
        request,
        "console/organization_detail.html",
        {
            "organization": organization,
            "is_disabled": organization.status == OrganizationStatus.DISABLED,
            "inventories": inventories,
            "counts": counts,
            "list_limit": list_limit,
        },
    )


@login_required
def organizations(request: HttpRequest) -> HttpResponse:
    rows = [
        {
            "cols": [
                o.slug,
                {"text": o.name, "url": "console:organization_detail", "arg": o.slug},
                "Aktif" if o.status == OrganizationStatus.ACTIVE else "Pasif",
            ]
        }
        for o in scoping.scoped_organizations(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "Organizasyonlar",
            "headers": ["Slug", "Ad", "Durum"],
            "rows": rows,
            "create_links": (
                [{"url": "console:organization_create", "label": "Yeni organizasyon"}]
                if can_create_organization(request.user)
                else []
            ),
        },
    )


@login_required
def projects(request: HttpRequest) -> HttpResponse:
    rows = [
        {
            "cols": [
                p.organization.slug,
                p.slug,
                {"text": p.name, "url": "console:project_detail_public", "arg": p.public_id},
                p.risk_level,
                p.status,
            ]
        }
        for p in scoping.scoped_projects(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "AI projeleri",
            "headers": ["Organizasyon", "Slug", "Ad", "Risk", "Durum"],
            "rows": rows,
            "create_links": (
                [{"url": "console:project_create", "label": "Yeni proje"}]
                if admin_organization_ids(request.user) != set()
                else []
            ),
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
        },
    )


@login_required
def scenarios(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "console/scenarios.html",
        {
            "title": "Senaryolar",
            "scenarios": scoping.scoped_scenarios(request.user).order_by(
                "project__organization__name", "project__name", "name"
            ),
            "can_create": author_organization_ids(request.user) != set(),
        },
    )


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
    node_types = ", ".join(sorted(BUILTIN_NODE_TYPES))
    return (
        "AgentHub workflow DSL kuralları\n\n"
        "- Kök anahtarlar tam olarak: api_version, kind, metadata, spec.\n"
        "- api_version='agenthub/v1', kind='Workflow'; metadata yalnız id içerir.\n"
        "- spec tam olarak input_node, nodes ve edges içerir.\n"
        f"- En fazla {MAX_NODES} node ve {MAX_EDGES} edge kullanılabilir.\n"
        f"- İzinli built-in node türleri: {node_types}.\n"
        "- Node ID'leri benzersizdir; input_node bir input node'a işaret eder.\n"
        "- Grafik döngüsüz olmalı, tüm node'lar erişilebilir olmalı ve erişilebilir bir end "
        "node içermelidir.\n"
        "- end dışındaki her node'un çıkışı olmalı; end node'un çıkışı olamaz.\n"
        "- condition edge'lerinde when boolean'dır; koşul ifadeleri bounded ve güvenli AST "
        "altkümesiyle sınırlıdır.\n"
        "- URL, endpoint, secret, code, python, package ve entrypoint gibi yetki/çalıştırma "
        "alanları DSL config içinde kullanılamaz.\n"
        "- Bu metin yardımcı rehberdir; tek otorite backend canonical validator/compiler'dır. "
        "Üretilen aday her zaman validate edilmeden publish edilmemelidir."
    )


@login_required
def scenario_detail(
    request: HttpRequest, pk: int | None = None, public_id: object = None
) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk, public_id)
    organization_id = scenario.project.organization_id
    active_release = ScenarioRelease.objects.filter(
        scenario=scenario, status=ReleaseStatus.ACTIVE
    ).first()
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
            organization_id=organization_id, project=scenario.project
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
            "aliases": scenario.aliases.order_by("alias"),
            "active_release": active_release,
            "active_artifacts": active_artifacts,
            "release_rows": release_rows,
            "project_drafts": project_drafts,
            "dsl_guide": _workflow_dsl_guide(),
            "consumer_bindings": consumer_bindings,
            "relationship_rows": relationship_rows,
            "candidate_document_sets": scoping.scoped_document_sets(request.user)
            .filter(organization_id=organization_id, status="active")
            .exclude(id__in=bound_set_ids)
            .order_by("name", "logical_id"),
            "can_write": can_author_scenarios(request.user, organization_id),
        },
    )


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
    rows = [
        {
            "cols": [
                c.organization.slug,
                {"text": c.name, "url": "console:consumer_detail_public", "arg": c.public_id},
                c.subject,
                c.protocol,
                c.status,
            ]
        }
        for c in scoping.scoped_consumers(request.user)
    ]
    return render(
        request,
        "console/list.html",
        {
            "title": "İstemciler",
            "headers": ["Organizasyon", "Ad", "Subject", "Protokol", "Durum"],
            "rows": rows,
            "create_links": (
                [
                    {"url": "console:consumer_create", "label": "Yeni istemci"},
                    {"url": "console:binding_create", "label": "Yeni istemci bağı"},
                ]
                if admin_organization_ids(request.user) != set()
                else []
            ),
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
    binding_candidates = list(
        consumer.bindings.select_related("scenario", "scenario__project").order_by(
            "scenario__project__name", "scenario__name"
        )[:101]
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
def artifacts(request: HttpRequest) -> HttpResponse:
    rows = list(
        scoping.scoped_artifacts(request.user).order_by(
            "organization__slug", "type", "logical_id", "-version"
        )
    )
    return render(
        request,
        "console/artifacts.html",
        {
            "title": "Artifact'ler",
            "rows": rows,
        },
    )


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
def releases(request: HttpRequest) -> HttpResponse:
    user = request.user
    rows = []
    for r in scoping.scoped_releases(user).select_related("scenario__project__organization"):
        manageable = can_manage_releases(user, r.scenario.project.organization_id)
        pre_active = r.status in (ReleaseStatus.CANDIDATE, ReleaseStatus.CANARY)
        rows.append(
            {
                "id": r.pk,
                "scenario_id": r.scenario_id,
                "scenario_public_id": r.scenario.public_id,
                "org_slug": r.scenario.project.organization.slug,
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
        request,
        "console/releases.html",
        {"title": "Release'ler", "rows": rows, "canaries": canaries},
    )


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
            "can_manage": can_manage_releases(request.user, release.organization_id),
            "is_disabled": release.organization.status == OrganizationStatus.DISABLED,
        },
    )


def _manageable_release(user: UserLike, release_id: int) -> ScenarioRelease:
    release = _scoped_release(user, release_id)
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
    if not can_manage_releases(request.user, canary.scenario.project.organization_id):
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
    return render(
        request, "console/agent_runs.html", {"title": "Agent çalıştırmaları", "rows": rows}
    )


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
        "can_cancel": run.organization.status == OrganizationStatus.ACTIVE
        and run.status not in {"completed", "failed", "timed_out", "cancelled"},
    }
    return render(
        request,
        "console/agent_run_detail.html",
        {"title": f"Agent çalıştırması {public[:8]}", "run": summary, "events": events},
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
    initial: dict[str, object] = {}
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
        initial = {"organization": draft.organization.slug, "draft_id": draft.pk}
    elif requested_org:
        if requested_org not in organizations_by_slug:
            raise Http404
        initial = {"organization": requested_org}
    return render(
        request,
        "console/builder.html",
        {"title": "Workflow builder", "builder_orgs": orgs, "builder_initial": initial},
    )


@login_required
def documents(request: HttpRequest) -> HttpResponse:
    """List tenant-scoped document sets as the primary content workspace."""
    user = request.user
    sets = [
        {
            "id": s.id,
            "public_id": s.public_id,
            "org": s.organization.slug,
            "logical_id": s.logical_id,
            "name": s.name,
            "status": s.status,
            "versions": s.versions.count(),
        }
        for s in scoping.scoped_document_sets(user).order_by("organization_id", "logical_id")
    ]
    can_upload = author_organization_ids(user) != set()
    can_open_advanced_inventory = admin_organization_ids(user) != set()
    return render(
        request,
        "console/documents.html",
        {
            "title": "Doküman setleri",
            "sets": sets,
            "set_form": DocumentSetForm(user=user),
            "can_upload": can_upload,
            "can_open_advanced_inventory": can_open_advanced_inventory,
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
            "can_write": can_author_scenarios(request.user, document.organization_id),
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
    if not can_author_scenarios(request.user, organization.id):
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
    if not can_author_scenarios(request.user, document.organization_id):
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
    form = DocumentSetForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, "Create failed: check the form fields.")
        return redirect("console:documents")
    organization = form.cleaned_data["organization"]
    if not can_author_scenarios(request.user, organization.id):
        raise PermissionDenied
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
    can_write = can_author_scenarios(request.user, document_set.organization_id)
    can_promote_index = can_manage_releases(request.user, document_set.organization_id)
    versions = [
        {
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
        for v in document_set.versions.order_by("-version")
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
    latest_version = document_set.versions.order_by("-version").first()
    latest_members = (
        list(latest_version.memberships.select_related("document_version").all())
        if latest_version is not None
        else []
    )
    parsed_count = sum(
        item.document_version.parse_status == ParseStatus.PARSED for item in latest_members
    )
    staged_ready = IndexVersion.objects.filter(
        organization_id=document_set.organization_id,
        document_set_version__document_set=document_set,
        status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
    ).exists()
    lifecycle_steps = [
        {
            "label": "Yüklendi",
            "complete": bool(latest_members),
            "detail": f"{len(latest_members)} doküman sürümü"
            if latest_members
            else "Henüz içerik yok",
            "next": "Dosya yükleyin" if can_write and not latest_members else "",
        },
        {
            "label": "Ayrıştırıldı / normalize edildi",
            "complete": bool(latest_members) and parsed_count == len(latest_members),
            "detail": f"{parsed_count}/{len(latest_members)} hazır",
            "next": "İndeks oluşturma ayrıştırmayı çalıştırır"
            if latest_members and parsed_count != len(latest_members)
            else "",
        },
        {
            "label": "Set taslağı",
            "complete": latest_version is not None,
            "detail": latest_version.status if latest_version else "Taslak yok",
            "next": "Taslağı yayımlayın"
            if can_write
            and latest_version is not None
            and latest_version.status == DocumentSetVersionStatus.DRAFT
            else "",
        },
        {
            "label": "Set sürümü yayımlandı",
            "complete": latest_version is not None
            and latest_version.status != DocumentSetVersionStatus.DRAFT,
            "detail": "Yayımlandı"
            if latest_version is not None
            and latest_version.status != DocumentSetVersionStatus.DRAFT
            else "Taslak üyelik değişebilir",
            "next": "Önce taslağı yayımlayın"
            if latest_version is not None
            and latest_version.status == DocumentSetVersionStatus.DRAFT
            else "",
        },
        {
            "label": "Staged indeks hazır",
            "complete": staged_ready,
            "detail": "İndeks sürümü mevcut" if staged_ready else "Promotable indeks yok",
            "next": "Yayımlanmış set sürümünden staged indeks oluşturun"
            if can_write
            and latest_version is not None
            and latest_version.status != DocumentSetVersionStatus.DRAFT
            and not staged_ready
            else "",
        },
        {
            "label": "Aktif indeks",
            "complete": active_index is not None,
            "detail": f"İndeks v{active_index.version}" if active_index else "Serve edilmiyor",
            "next": "Değerlendirilen promotable indeksi aktif edin"
            if can_promote_index and active_index is None
            else "",
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
            "versions": versions,
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
            "can_promote_index": can_promote_index,
            "max_batch_files": int(getattr(settings, "DOCUMENTS_MAX_BATCH_UPLOAD_FILES", 20)),
        },
    )


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
            "can_write": can_author_scenarios(request.user, document.organization_id),
        },
    )


@login_required
@require_POST
def document_set_document_replace(
    request: HttpRequest, public_id: object, document_public_id: object
) -> HttpResponse:
    document_set = _scoped_document_set(request.user, public_id=public_id)
    document = _scoped_set_document(request.user, document_set, document_public_id)
    if not can_author_scenarios(request.user, document.organization_id):
        raise PermissionDenied
    form = DocumentReplacementForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Yeni sürüm yüklenemedi: bir dosya seçin.")
    else:
        upload = form.cleaned_data["file"]
        mime_type = _UPLOAD_MIME_BY_SUFFIX.get(Path(upload.name).suffix.lower(), "")
        try:
            version = document_services.upload_document(
                organization=document.organization,
                logical_id=document.logical_id,
                title=document.title or Path(upload.name).stem,
                mime_type=mime_type,
                data=upload.read(),
                actor=request.user.get_username(),
                source=document.source,
                request_id=_request_id(request),
            )
            draft = document_services.get_or_create_manual_draft(
                document_set=document_set,
                actor=request.user.get_username(),
                request_id=_request_id(request),
            )
            document_services.upsert_document_in_set_draft(
                set_version=draft,
                document_version=version,
                actor=request.user.get_username(),
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
    if not can_author_scenarios(request.user, set_version.organization_id):
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
    if not can_author_scenarios(request.user, document.organization_id):
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
    can_write = can_author_scenarios(request.user, document_set.organization_id)
    can_promote = can_manage_releases(request.user, document_set.organization_id)
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
    if not can_author_scenarios(request.user, document_set.organization_id):
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
    if not can_author_scenarios(request.user, document_set.organization_id):
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
    if not can_author_scenarios(request.user, document_set.organization_id):
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
    if not can_author_scenarios(request.user, document_set.organization_id):
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
@require_POST
def connector_source_run(request: HttpRequest, source_pk: int) -> HttpResponse:
    source = _scoped_connector_source(request.user, source_pk)
    document_set = source.document_set
    if document_set is None:
        raise Http404
    if not can_author_scenarios(request.user, source.organization_id):
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
    can_author = can_author_scenarios(request.user, source.organization_id)
    can_promote = can_manage_releases(request.user, source.organization_id)
    if not can_author and not can_promote:
        raise PermissionDenied
    requested_mode = request.POST.get(f"schedule-{source.pk}-automation_mode", "")
    if requested_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE and not can_promote:
        raise PermissionDenied
    if requested_mode != ScheduleAutomationMode.PROMOTE_IF_SAFE and not can_author:
        raise PermissionDenied
    document_set = source.document_set
    if document_set is None:
        raise Http404
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
    if not can_author_scenarios(request.user, document_set.organization_id):
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
            version = document_services.upload_document(
                organization=document_set.organization,
                logical_id=item["logical_id"],
                title=item["title"],
                mime_type=item["mime_type"],
                data=upload.read(),
                actor=request.user.get_username(),
            )
            uploaded += 1
            document_services.upsert_document_in_set_draft(
                set_version=draft,
                document_version=version,
                actor=request.user.get_username(),
            )
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
    if not can_author_scenarios(request.user, set_version.organization_id):
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
    if IndexVersion.objects.filter(
        document_set_version=set_version,
        embedding_profile=profile,
        status__in=[IndexStatus.BUILDING, IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
    ).exists():
        messages.error(request, "Bu sürüm ve profil için kullanılabilir bir indeks zaten var.")
        return redirect(
            "console:document_set_detail_public", public_id=set_version.document_set.public_id
        )
    try:
        record_event(
            actor_type="user",
            actor_id=request.user.get_username(),
            action="ingestion.staged_index.request_authorized",
            outcome="success",
            organization_id=set_version.organization_id,
            resource_type="document_set_version",
            resource_id=f"{set_version.document_set.logical_id}:v{set_version.version}",
            after={"embedding_profile_id": str(profile.public_id)},
        )
        build_document_set_index_task.apply_async(
            args=[
                set_version.pk,
                profile.pk,
                set_version.organization_id,
                request.user.get_username(),
                ocr_profile.pk if ocr_profile else None,
            ],
            queue="ingestion",
        )
        messages.success(request, "Staged indeks isteği ingestion kuyruğuna gönderildi.")
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
    if not can_manage_releases(request.user, index.organization_id):
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
    if not can_author_scenarios(request.user, document_set.organization_id):
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
    if not can_author_scenarios(request.user, set_version.organization_id):
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
    if not can_author_scenarios(request.user, binding.organization_id):
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
    if not can_author_scenarios(request.user, grant.organization_id):
        raise PermissionDenied
    document_set_public_id = grant.document_set.public_id
    document_services.revoke_document_set_grant(grant, actor=request.user.get_username())
    messages.success(request, "İstemci retrieval izni kaldırıldı.")
    return redirect("console:document_set_detail_public", public_id=document_set_public_id)


@login_required
@require_POST
def agent_run_cancel(request: HttpRequest, public_id: str) -> HttpResponse:
    run = _scoped_agent_run(request.user, public_id)
    if not _operator_can_mutate_org(request.user, run.organization_id):
        raise PermissionDenied
    try:
        operator_cancel_agent_run(
            run=run,
            organization_id=run.organization_id,
            actor=request.user.get_username(),
        )
        messages.success(request, f"Agent çalıştırması {run.public_id} iptal edildi.")
    except AgentRequestError as exc:
        messages.error(request, f"İptal reddedildi: {exc.code}")
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
    set_tenant_context(run.organization_id)
    return run


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
) -> HttpResponse:
    form = form_class(request.POST or None, user=request.user)
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
                        name=form.cleaned_data["name"], status=form.cleaned_data["status"]
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
                        type=form.cleaned_data["type"],
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
    return _create(
        request,
        form_class=ProjectForm,
        title="Yeni proje",
        resource_type="project",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:projects",
    )


@login_required
def scenario_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=ScenarioForm,
        title="Yeni senaryo",
        resource_type="scenario",
        permission=lambda org_id: org_id is not None and can_author_scenarios(request.user, org_id),
        success_url="console:scenarios",
    )


@login_required
def consumer_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=ConsumerForm,
        title="Yeni istemci",
        resource_type="consumer",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:consumers",
    )


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
