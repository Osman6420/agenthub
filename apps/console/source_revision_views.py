"""Configuration editing and explicit prepared-source selection."""

import copy
import time
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.console.rest_setup_forms import visual_initial
from apps.console.rest_setup_views import (
    MAX_AGE,
    MAX_DRAFTS,
    SERVER_SESSION_ENGINES,
    SESSION_KEY,
    _store,
)
from apps.ingestion.models import SourceConfigurationRevision
from apps.ingestion.rest_schema import RestContractError
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError
from apps.ingestion.source_revisions import (
    REVISION_ERRORS,
    REVISION_SOURCE_TYPES,
    configuration_token,
    current_source,
    revision_for,
    revision_schedule_label,
    schedule_for_edit,
    select_source_revision,
)
from apps.ingestion.staged_build import StagedBuildError
from apps.tenancy.services import can_manage_documents


def revision_context(source, *, can_write, can_operate, preparation_job):
    revision = revision_for(source)
    context = {
        "can_edit_source": can_write
        and source.connector_type in REVISION_SOURCE_TYPES
        and source.connection_id is not None
        and getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False),
        "configuration_revision": revision,
    }
    if revision is None:
        return context
    context["revision_schedule_label"] = revision_schedule_label(revision.schedule_config)
    context["configuration_history"] = (
        SourceConfigurationRevision.objects.select_related("source")
        .filter(
            root_source_id=revision.root_source_id,
            organization_id=source.organization_id,
        )
        .order_by("-number")[:20]
    )
    if can_operate and not revision.is_current and preparation_job is not None:
        build = preparation_job.preparation_job
        if (
            build is not None
            and build.status == "succeeded"
            and build.result_index_version is not None
        ):
            context["selection_index"] = build.result_index_version
            context["selection_token"] = configuration_token(source)
    return context


@login_required
@require_http_methods(["GET", "POST"])
def edit(request, source_pk):
    from apps.console.views import _scoped_connector_source, connector_source_detail

    if (
        not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False)
        or settings.SESSION_ENGINE not in SERVER_SESSION_ENGINES
    ):
        raise Http404
    source = _scoped_connector_source(request.user, source_pk)
    if not can_manage_documents(
        request.user, source.organization_id, document_set=source.document_set
    ):
        raise PermissionDenied
    if source.connector_type in {"mcp_resource", "confluence_dc"}:
        from apps.console.resource_revision_views import edit_resource

        return edit_resource(request, source)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    if (
        source.connector_type != "generic_rest"
        or source.rest_contract is None
        or source.rest_profile is None
        or source.document_set is None
    ):
        raise Http404
    try:
        selected = current_source(source)
        schedule = schedule_for_edit(source)
        expected = configuration_token(selected)
    except RestServiceError:
        messages.error(
            request, "Önce kaynak planını ve doküman setinin hazırlama ayarlarını kontrol edin."
        )
        response = connector_source_detail(request, source_pk)
        response.status_code = 400
        return response
    now = time.time()
    drafts = {
        key: copy.deepcopy(state)
        for key, state in request.session.get(SESSION_KEY, {}).items()
        if state.get("actor") == request.user.pk and now - state.get("created", 0) < MAX_AGE
    }
    while len(drafts) >= MAX_DRAFTS:
        drafts.pop(min(drafts, key=lambda key: drafts[key]["created"]))
    intent = uuid4()
    definition = source.rest_contract.definition
    try:
        visual_initial(definition)
        mode = "visual"
    except RestContractError:
        mode = "advanced"
    _store(
        request,
        drafts,
        intent,
        {
            "actor": request.user.pk,
            "set": source.document_set_id,
            "created": now,
            "step": 1,
            "mode": mode,
            "name": source.name,
            "profile": str(source.rest_profile.public_id),
            "definition": copy.deepcopy(definition),
            "inputs": copy.deepcopy(source.connector_config["inputs"]),
            "schedule": schedule,
            "base_source": selected.pk,
            "base_token": expected,
        },
    )
    return redirect(
        "console:rest_setup_draft", public_id=source.document_set.public_id, draft_id=intent
    )


class SelectionForm(forms.Form):
    expected = forms.RegexField(r"^[0-9a-f]{64}$", max_length=64)
    index_id = forms.IntegerField(min_value=1, max_value=9223372036854775807)
    confirm_active_release_impact = forms.BooleanField(required=False)


@login_required
@require_POST
def select(request, source_pk):
    from apps.console.views import _scoped_connector_source, connector_source_detail

    if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        raise Http404
    source = _scoped_connector_source(request.user, source_pk)
    form = SelectionForm(request.POST)
    if (
        request.FILES
        or set(request.POST) - {*form.fields, "csrfmiddlewaretoken"}
        or any(len(values) != 1 for _, values in request.POST.lists())
        or not form.is_valid()
    ):
        return HttpResponseBadRequest("Geçiş isteğini güncel sayfadan yeniden gönderin.")
    try:
        select_source_revision(actor=request.user, source=source, **form.cleaned_data)
    except RestAuthorizationError as exc:
        raise PermissionDenied from exc
    except (*REVISION_ERRORS, StagedBuildError) as exc:
        messages.error(
            request,
            {
                "SOURCE_REVISION_CHANGED": "Kaynak ayarları değişti. Sayfayı yenileyip inceleyin.",
                "SOURCE_REVISION_BASELINE_CHANGED": (
                    "Diğer kaynakların belgeleri değişti. "
                    "Bu ayarlarla belgeleri yeniden alıp hazırlayın."
                ),
                "SOURCE_REVISION_BUSY": "Kaynağın devam eden işleminin tamamlanmasını bekleyin.",
                "ACTIVE_RELEASES_AFFECTED": (
                    "Bu geçiş mevcut yayını etkiliyor. "
                    "Etkiyi inceleyip aşağıdaki onayı işaretleyin."
                ),
            }.get(
                getattr(exc, "code", "SOURCE_REVISION_DENIED"),
                "Geçiş tamamlanamadı. Hazırlamanın tamamlandığını "
                "ve güncel bağlantı/model izinlerini kontrol edin.",
            ),
        )
        response = connector_source_detail(request, source_pk)
        response.status_code = 400
        return response
    messages.success(
        request,
        "Bu ayarlar ve hazırlanan belgeler kullanıma alındı. Eski ayarlar geçmişte korundu.",
    )
    return redirect("console:connector_source_detail", source_pk=source.pk)
