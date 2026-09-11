"""Separate scenario data policy from data-owner consent."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.catalog.models import ScenarioDataAccessMode
from apps.console.scoping import scoped_document_sets
from apps.documents.access_services import ScenarioDocumentSetAccessError
from apps.documents.models import ScenarioDocumentSetGrant
from apps.documents.shared_access import set_scenario_data_access_mode, set_shared_consumer_consent
from apps.identity.authorization import AuthoritySource, Capability, authorize, authorized_scenarios
from apps.tenancy.context import set_tenant_context

_ERRORS = {
    "DATA_ACCESS_MODE_STALE": "Veri erişim düzeni değişti. Sayfayı yenileyip yeniden inceleyin.",
    "DOCUMENT_SET_MANAGER_REQUIRED": "Bu işlem için bu doküman setinin yöneticisi olmalısınız.",
    "SHARED_FUTURE_CONSUMERS_ACK_REQUIRED": (
        "Mevcut ve gelecekteki izinli istemcileri kapsayan onayı işaretleyin."
    ),
    "LIVE_SCENARIO_GRANT_REQUIRED": "Önce bu senaryoya doküman seti kullanım izni verilmelidir.",
    "INVALID_DATA_ACCESS_MODE": "Geçerli bir veri erişimi düzeni seçin.",
    "SCENARIO_EDIT_REQUIRED": "Senaryoyu düzenleme yetkiniz artık yok.",
}

_MODE_SALT = "agenthub.console.data-access.v1"


@login_required
@require_http_methods(["GET", "POST"])
def scenario_data_access(request: HttpRequest, public_id: object) -> HttpResponse:
    scenario = get_object_or_404(
        authorized_scenarios(request.user, Capability.SCENARIO_VIEW), public_id=public_id
    )
    set_tenant_context(scenario.organization_id)
    can_edit = authorize(
        user=request.user, capability=Capability.SCENARIO_EDIT, scenario=scenario
    ).allowed
    error = ""
    if request.method == "POST":
        if not can_edit:
            raise Http404
        if request.POST.get("confirm") != "yes":
            error = "Veri erişim düzeni değişikliğini onaylayın."
        else:
            try:
                token = request.POST.get("mode_token", "")
                if len(token) > 4096:
                    raise signing.BadSignature()
                state = signing.loads(token, salt=_MODE_SALT, max_age=600)
                if state.get("actor") != request.user.pk or state.get("scenario") != scenario.pk:
                    raise signing.BadSignature()
                set_scenario_data_access_mode(
                    scenario=scenario,
                    actor=request.user,
                    mode=request.POST.get("mode", ""),
                    expected_mode=state["mode"],
                    request_id=str(getattr(request, "request_id", ""))[:64],
                    trace_id=str(getattr(request, "trace_id", ""))[:64],
                )
                messages.success(request, "Veri erişim düzeni güncellendi.")
                return redirect("console:scenario_data_access", public_id=scenario.public_id)
            except ScenarioDocumentSetAccessError as exc:
                error = _ERRORS.get(exc.code, "Veri erişimi güncellenemedi. Sayfayı yenileyin.")
            except (signing.BadSignature, KeyError, TypeError):
                error = "Erişim formunun süresi dolmuş veya geçersiz. Sayfayı yenileyin."
    bindings = list(
        scenario.document_set_bindings.select_related("document_set").order_by("pk")[:501]
    )
    grants = {
        grant.document_set_id: grant
        for grant in ScenarioDocumentSetGrant.objects.filter(
            organization_id=scenario.organization_id,
            scenario=scenario,
            permission="retrieve",
            status="granted",
            revoked_at__isnull=True,
            document_set_id__in=[binding.document_set_id for binding in bindings],
        )
    }
    rows = [
        {
            "name": binding.document_set.name,
            "shared": bool(
                grants.get(binding.document_set_id)
                and grants[binding.document_set_id].shared_consumers
            ),
        }
        for binding in bindings[:500]
    ]
    return render(
        request,
        "console/scenario_data_access.html",
        {
            "scenario": scenario,
            "mode_token": signing.dumps(
                {
                    "actor": request.user.pk,
                    "scenario": scenario.pk,
                    "mode": scenario.data_access_mode,
                },
                salt=_MODE_SALT,
            ),
            "can_edit": can_edit,
            "modes": ScenarioDataAccessMode.choices,
            "rows": rows,
            "limited": len(bindings) > 500,
            "error": error,
        },
        status=400 if error else 200,
    )


@login_required
@require_http_methods(["GET", "POST"])
def document_shared_access(request: HttpRequest, public_id: object) -> HttpResponse:
    document_set = get_object_or_404(scoped_document_sets(request.user), public_id=public_id)
    decision = authorize(
        user=request.user,
        capability=Capability.DOCUMENT_SET_RETRIEVE_GRANT,
        document_set=document_set,
    )
    if not decision.allowed or decision.source != AuthoritySource.DOCUMENT_SET_RESPONSIBILITY:
        raise Http404
    set_tenant_context(document_set.organization_id)
    grants = (
        ScenarioDocumentSetGrant.objects.filter(
            document_set=document_set,
            organization_id=document_set.organization_id,
            scenario__organization_id=document_set.organization_id,
            permission="retrieve",
            status="granted",
            revoked_at__isnull=True,
        )
        .select_related("scenario", "shared_approved_by")
        .order_by("scenario__name", "pk")
    )
    error = ""
    if request.method == "POST":
        grant = get_object_or_404(
            grants,
            pk=request.POST.get("grant_id", "0")
            if request.POST.get("grant_id", "").isdigit()
            and len(request.POST.get("grant_id", "")) <= 18
            else 0,
        )
        action = request.POST.get("action")
        if action not in {"approve", "revoke"}:
            error = "Geçerli bir işlem seçin."
        else:
            try:
                set_shared_consumer_consent(
                    grant=grant,
                    actor=request.user,
                    enabled=action == "approve",
                    acknowledge_future_consumers=request.POST.get("acknowledge") == "yes",
                    request_id=str(getattr(request, "request_id", ""))[:64],
                    trace_id=str(getattr(request, "trace_id", ""))[:64],
                )
                messages.success(request, "Ortak veri kullanım izni güncellendi.")
                return redirect("console:document_shared_access", public_id=document_set.public_id)
            except ScenarioDocumentSetAccessError as exc:
                error = _ERRORS.get(exc.code, "Ortak veri izni güncellenemedi. Sayfayı yenileyin.")
    items = list(grants[:201])
    return render(
        request,
        "console/document_shared_access.html",
        {
            "document_set": document_set,
            "grants": items[:200],
            "limited": len(items) > 200,
            "error": error,
        },
        status=400 if error else 200,
    )
