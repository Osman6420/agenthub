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
from django.views.decorators.http import require_POST

from apps.agents.models import AgentRun
from apps.agents.services import AgentRequestError, operator_cancel_agent_run
from apps.artifacts.models import ArtifactVersion
from apps.audit.services import record_event
from apps.builder.models import WorkflowDraft
from apps.catalog.models import Scenario, ScenarioAlias
from apps.console import scoping
from apps.console.forms import (
    BindingForm,
    CanaryForm,
    ConfluenceSourceForm,
    ConnectorScheduleForm,
    ConsumerForm,
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
    DocumentSetVersion,
    DocumentSetVersionStatus,
    DocumentVersion,
    GrantPrincipalType,
    ScenarioDocumentSetBinding,
)
from apps.documents.services import DocumentError
from apps.documents.storage import StorageError
from apps.evaluations.services import EvalError, run_eval
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
        {"cols": [p.organization.slug, p.slug, p.name, p.risk_level, p.status]}
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


def _scoped_scenario(user: UserLike, pk: int) -> Scenario:
    try:
        return scoping.scoped_scenarios(user).get(pk=pk)
    except Scenario.DoesNotExist as exc:
        raise Http404 from exc


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
def scenario_detail(request: HttpRequest, pk: int) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk)
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
def scenario_bind_document_set(request: HttpRequest, pk: int) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk)
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
    return redirect("console:scenario_detail", pk=scenario.pk)


@login_required
@require_POST
def scenario_unbind_document_set(request: HttpRequest, pk: int, binding_pk: int) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk)
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
    return redirect("console:scenario_detail", pk=scenario.pk)


@login_required
@require_POST
def scenario_grant_consumer(request: HttpRequest, pk: int, document_set_pk: int) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk)
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
        messages.error(request, "Erişim verilemedi: consumer bu senaryoya bağlı değil.")
    else:
        try:
            document_services.grant_document_set(
                document_set=document_set,
                principal_type=GrantPrincipalType.CONSUMER,
                principal_ref=str(consumer.id),
                actor=request.user.get_username(),
            )
            messages.success(request, "Consumer için doküman erişimi verildi.")
        except DocumentError as exc:
            messages.error(request, f"Erişim verilemedi: {exc.code}")
    return redirect("console:scenario_detail", pk=scenario.pk)


@login_required
@require_POST
def scenario_revoke_consumer(request: HttpRequest, pk: int, grant_pk: int) -> HttpResponse:
    scenario = _scoped_scenario(request.user, pk)
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
    messages.success(request, "Consumer doküman erişimi kaldırıldı.")
    return redirect("console:scenario_detail", pk=scenario.pk)


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
            "title": "Consumer'lar",
            "headers": ["Organizasyon", "Ad", "Subject", "Protokol", "Durum"],
            "rows": rows,
            "create_links": (
                [
                    {"url": "console:consumer_create", "label": "Yeni consumer"},
                    {"url": "console:binding_create", "label": "Yeni consumer bağı"},
                ]
                if admin_organization_ids(request.user) != set()
                else []
            ),
        },
    )


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
        return scoping.scoped_artifacts(user).get(pk=pk)
    except ArtifactVersion.DoesNotExist as exc:
        raise Http404 from exc


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
                "can_decide": bool(set(roles or []) & set(approval.approver_roles)),
            }
        )
    return render(request, "console/tool_approvals.html", {"title": "Tool onayları", "rows": rows})


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
    if not _operator_can_access_org(request.user, invocation.organization_id):
        raise PermissionDenied
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
        "can_cancel": run.status not in {"completed", "failed", "timed_out", "cancelled"},
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
            "latest_version": latest_version,
            "active_index": active_index,
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
def document_set_connectors(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
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
def rest_contract_preview(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
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
def rest_contract_create(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
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
            return redirect("console:document_set_connectors", pk=document_set.pk)
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
def confluence_source_create(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
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
    return redirect("console:document_set_connectors", pk=document_set.pk)


@login_required
@transaction.atomic
@require_POST
def rest_source_create(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
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
    return redirect("console:document_set_connectors", pk=document_set.pk)


def _scoped_connector_source(user: UserLike, source_pk: int) -> Source:
    source = scoping.scoped_connector_sources(user).filter(pk=source_pk).first()
    if source is None or source.document_set_id is None:
        raise Http404
    return source


@login_required
@require_POST
def connector_source_run(request: HttpRequest, source_pk: int) -> HttpResponse:
    source = _scoped_connector_source(request.user, source_pk)
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
    return redirect("console:document_set_connectors", pk=source.document_set_id)


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
    return redirect("console:document_set_connectors", pk=document_set.pk)


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
def document_set_bulk_upload(request: HttpRequest, pk: int) -> HttpResponse:
    document_set = _scoped_document_set(request.user, pk)
    if not can_author_scenarios(request.user, document_set.organization_id):
        raise PermissionDenied
    form = DocumentSetBulkUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Yükleme başarısız: en az bir dosya seçin.")
        return redirect("console:document_set_detail", pk=document_set.pk)
    files = list(form.cleaned_data["uploads"])
    max_files = int(getattr(settings, "DOCUMENTS_MAX_BATCH_UPLOAD_FILES", 20))
    max_file_bytes = int(getattr(settings, "DOCUMENTS_MAX_UPLOAD_BYTES", 25_000_000))
    max_batch_bytes = int(getattr(settings, "DOCUMENTS_MAX_BATCH_UPLOAD_BYTES", 100_000_000))
    sizes = [int(getattr(upload, "size", 0)) for upload in files]
    if len(files) > max_files:
        messages.error(request, f"Yükleme başarısız: en fazla {max_files} dosya seçilebilir.")
        return redirect("console:document_set_detail", pk=document_set.pk)
    if any(size <= 0 or size > max_file_bytes for size in sizes):
        messages.error(
            request, "Yükleme başarısız: boş veya dosya boyutu sınırını aşan içerik var."
        )
        return redirect("console:document_set_detail", pk=document_set.pk)
    if sum(sizes) > max_batch_bytes:
        messages.error(request, "Yükleme başarısız: toplam batch boyutu sınırı aşıldı.")
        return redirect("console:document_set_detail", pk=document_set.pk)
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
    return redirect("console:document_set_detail", pk=document_set.pk)


@login_required
@require_POST
def document_set_build_index(request: HttpRequest, version_pk: int) -> HttpResponse:
    set_version = _scoped_set_version(request.user, version_pk)
    if not can_author_scenarios(request.user, set_version.organization_id):
        raise PermissionDenied
    form = DocumentSetBuildForm(request.POST, organization_id=set_version.organization_id)
    if not form.is_valid():
        messages.error(request, "İndeks isteği reddedildi: tenant’a açık bir profil seçin.")
        return redirect("console:document_set_detail", pk=set_version.document_set_id)
    if set_version.status not in [
        DocumentSetVersionStatus.PROMOTABLE,
        DocumentSetVersionStatus.ACTIVE,
    ]:
        messages.error(request, "İndeks için önce taslak sürümü yayımlayın.")
        return redirect("console:document_set_detail", pk=set_version.document_set_id)
    profile = form.cleaned_data["embedding_profile"]
    ocr_profile = form.cleaned_data["ocr_profile"]
    if IndexVersion.objects.filter(
        document_set_version=set_version,
        embedding_profile=profile,
        status__in=[IndexStatus.BUILDING, IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
    ).exists():
        messages.error(request, "Bu sürüm ve profil için kullanılabilir bir indeks zaten var.")
        return redirect("console:document_set_detail", pk=set_version.document_set_id)
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
    return redirect("console:document_set_detail", pk=set_version.document_set_id)


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
    if not can_manage_releases(request.user, index.organization_id):
        raise PermissionDenied
    try:
        promote_staged_index(index, actor=request.user.get_username())
        messages.success(request, "Staged indeks aktif hale getirildi.")
    except StagedBuildError as exc:
        messages.error(request, f"Promotion başarısız: {exc.code}")
    return redirect("console:document_set_detail", pk=index.document_set_version.document_set_id)


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
        title="Yeni consumer",
        resource_type="consumer",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:consumers",
    )


@login_required
def binding_create(request: HttpRequest) -> HttpResponse:
    return _create(
        request,
        form_class=BindingForm,
        title="Yeni consumer bağı",
        resource_type="binding",
        permission=lambda org_id: org_id is not None and can_admin_org(request.user, org_id),
        success_url="console:consumers",
    )
