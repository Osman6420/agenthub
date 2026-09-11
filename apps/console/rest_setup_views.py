"""Bounded server-side REST setup using the existing ingestion services."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.console.forms import BoundedJsonField
from apps.console.rest_setup_forms import (
    AdvancedMappingStep,
    ConnectionStep,
    InputStep,
    MappingStep,
    visual_initial,
)
from apps.ingestion.connections import ConnectionError
from apps.ingestion.models import Source
from apps.ingestion.rest import RestPullError, preview_rest_response
from apps.ingestion.rest_probe import probe_rest_connection
from apps.ingestion.rest_schema import RestContractError
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError
from apps.ingestion.rest_setup import create_rest_setup
from apps.ingestion.rest_setup_drafts import (
    PAYLOAD_KEYS,
    load_setup_draft,
    save_setup_draft,
)
from apps.ingestion.rest_setup_schedule import setup_preparation_policy
from apps.tenancy.context import operator_transaction
from apps.tenancy.middleware import durable_operator_view
from apps.tenancy.services import can_manage_documents

SESSION_KEY = "rest_setup_v1"
SALT = "console.rest-setup/v1"
MAX_DRAFTS = 5
MAX_AGE = 3600
MAX_STATE_BYTES = 160000
SERVER_SESSION_ENGINES = {
    "django.contrib.sessions.backends.db",
    "django.contrib.sessions.backends.cached_db",
    "django.contrib.sessions.backends.cache",
}


def _oversized(request, limit):
    # CSRF middleware may have consumed a multipart body already; do not reread it.
    try:
        return not 0 <= int(request.META.get("CONTENT_LENGTH") or 0) <= limit
    except (ValueError, TypeError):
        return True


def _digest(state):
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _token(state, draft_id):
    return signing.dumps({"id": str(draft_id), "digest": _digest(state)}, salt=SALT)


def _store(request, drafts, draft_id, state):
    if len(json.dumps(state).encode()) > MAX_STATE_BYTES:
        raise RestServiceError("REST_SETUP_STATE_LIMIT")
    drafts[str(draft_id)] = state
    request.session[SESSION_KEY] = drafts


def _input_initial(state):
    values = {
        f"input_{key}": str(value).lower() if isinstance(value, bool) else value
        for key, value in state.get("inputs", {}).items()
    }
    values.update(
        sync_mode="periodic" if state.get("schedule") else "manual",
        interval_seconds=state.get("schedule", {}).get("interval_seconds", 86400)
        if state.get("schedule")
        else 86400,
        preparation_mode="promote_if_safe"
        if (state.get("schedule") or {}).get("publication_targets")
        else "stage_only"
        if (state.get("schedule") or {}).get("preparation")
        else "draft_only",
    )
    return values


def _save_checkpoint(request, docset, draft_id, drafts, state):
    try:
        saved = save_setup_draft(
            actor=request.user,
            document_set=docset,
            intent=draft_id,
            payload={key: value for key, value in state.items() if key in PAYLOAD_KEYS},
            expected_revision=state.get("saved_revision", 0),
        )
    except (RestAuthorizationError, RestServiceError, RestContractError):
        return render(
            request,
            "console/rest_setup_waiting.html",
            {
                "set": docset,
                "source_name": state.get("name", ""),
                "error": (
                    "Taslak kaydedilemedi. Başka bir sekmede değişmiş, süresi dolmuş veya "
                    "beş kayıt sınırına ulaşmış olabilir. Kaynaklar ekranındaki kaydı yeniden açın."
                ),
            },
            status=400,
        )
    state["saved_revision"] = saved.revision
    _store(request, drafts, draft_id, state)
    messages.success(
        request,
        f"Kurulum taslağı kaydedildi. {saved.expires_at:%d.%m.%Y} tarihine kadar "
        "kaynaklar ekranından devam edebilirsiniz. "
        "Bağlantı çalıştırılmadı.",
    )
    return redirect("console:document_set_connectors_public", public_id=docset.public_id)


@login_required
@require_POST
def resume(request, public_id, draft_id):
    from apps.console.views import _scoped_connector_source, _scoped_document_set

    if (
        not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False)
        or settings.SESSION_ENGINE not in SERVER_SESSION_ENGINES
    ):
        raise Http404
    docset = _scoped_document_set(request.user, public_id=public_id)
    try:
        saved = load_setup_draft(actor=request.user, document_set=docset, intent=draft_id)
    except (RestAuthorizationError, RestServiceError):
        raise Http404 from None
    if saved.completed_source_id:
        source = _scoped_connector_source(request.user, saved.completed_source_id)
        return redirect("console:connector_source_detail", source_pk=source.pk)
    now = time.time()
    drafts = {
        key: copy.deepcopy(value)
        for key, value in request.session.get(SESSION_KEY, {}).items()
        if value.get("actor") == request.user.pk
        and now - value.get("created", 0) < MAX_AGE
        and key != str(draft_id)
    }
    while len(drafts) >= MAX_DRAFTS:
        drafts.pop(min(drafts, key=lambda key: drafts[key]["created"]))
    state = copy.deepcopy(saved.payload) | {
        "actor": request.user.pk,
        "set": docset.pk,
        "created": now,
        "saved_revision": saved.revision,
    }
    _store(request, drafts, draft_id, state)
    return redirect("console:rest_setup_draft", public_id=public_id, draft_id=draft_id)


@login_required
@require_http_methods(["GET", "POST"])
def setup(request, public_id, draft_id=None):
    from apps.console.views import _scoped_document_set

    if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        raise Http404
    if settings.SESSION_ENGINE not in SERVER_SESSION_ENGINES:
        # Configuration and inputs must never be serialized into a session cookie.
        raise Http404
    docset = _scoped_document_set(request.user, public_id=public_id)
    if not can_manage_documents(request.user, docset.organization_id, document_set=docset):
        raise PermissionDenied
    if request.method == "POST" and _oversized(request, 250000):
        return HttpResponseBadRequest("Form boyutu sınırı aşıldı.")
    now = time.time()
    drafts = {
        key: copy.deepcopy(state)
        for key, state in request.session.get(SESSION_KEY, {}).items()
        if state.get("actor") == request.user.pk and now - state.get("created", 0) < MAX_AGE
    }
    if draft_id is None:
        if request.method != "GET":
            return HttpResponseBadRequest("Kaynak formunu yeniden açın.")
        while len(drafts) >= MAX_DRAFTS:
            oldest = min(drafts, key=lambda key: drafts[key]["created"])
            drafts.pop(oldest)
        draft_id = uuid4()
        _store(
            request,
            drafts,
            draft_id,
            {
                "actor": request.user.pk,
                "set": docset.pk,
                "created": now,
                "step": 1,
                "mode": "visual",
            },
        )
        return redirect("console:rest_setup_draft", public_id=public_id, draft_id=draft_id)
    state = drafts.get(str(draft_id))
    if state is None or state.get("set") != docset.pk:
        return render(request, "console/rest_setup_expired.html", {"set": docset}, status=400)
    edit_source = None
    if "base_source" in state:
        from apps.console.views import _scoped_connector_source

        edit_source = _scoped_connector_source(request.user, state["base_source"])
        if edit_source.document_set_id != docset.pk:
            raise Http404
    if "saved_source" in state:
        from apps.console.views import _scoped_connector_source

        saved = _scoped_connector_source(request.user, state["saved_source"])
        if saved.document_set_id != docset.pk:
            raise Http404
        return redirect("console:connector_source_detail", source_pk=saved.pk)
    step = state["step"]
    original_state = copy.deepcopy(state)
    data = request.POST if request.method == "POST" else None
    error = ""
    preview_count = None
    if data is not None:
        try:
            submitted = signing.loads(data.get("submission", ""), salt=SALT, max_age=MAX_AGE)
            if submitted != {"id": str(draft_id), "digest": _digest(state)}:
                raise signing.BadSignature
        except signing.BadSignature:
            return render(request, "console/rest_setup_expired.html", {"set": docset}, status=400)
    if data is not None and data.get("action") == "back" and step > 1:
        state["step"] -= 1
        _store(request, drafts, draft_id, state)
        return redirect("console:rest_setup_draft", public_id=public_id, draft_id=draft_id)
    # Revalidate the selected connection on every page, including final submission.
    connection = ConnectionStep(
        {"name": state.get("name", ""), "profile": state.get("profile", "")}, document_set=docset
    )
    if step > 1 and not connection.is_valid():
        if data is not None and data.get("action") == "save_draft":
            return _save_checkpoint(request, docset, draft_id, drafts, state)
        return render(
            request,
            "console/rest_setup_waiting.html",
            {
                "set": docset,
                "source_name": state.get("name", ""),
                "submission": _token(state, draft_id),
                "step": step,
            },
        )
    profile = connection.cleaned_data.get("profile") if step > 1 else None
    profile_method = profile.method if profile else ""
    preparation_policy = None
    preparation_error = ""
    preparation_selected = bool((state.get("schedule") or {}).get("preparation"))
    if step >= 3:
        try:
            preparation_policy = setup_preparation_policy(
                docset,
                expected=(state.get("schedule") or {}).get("preparation") if step == 4 else None,
            )
        except RestServiceError:
            preparation_error = (
                "Hazırlama ayarları veya model izinleri değişmiş olabilir. "
                "Önceki adıma dönüp hazırlama seçimini yeniden kontrol edin."
                if step == 4 and preparation_selected
                else "Otomatik hazırlama için bu doküman setinde geçerli hazırlama ayarları "
                "ve model izinleri gerekiyor. Kurulumu taslak seçimiyle kaydedebilirsiniz."
            )
    form: ConnectionStep | MappingStep | AdvancedMappingStep | InputStep | None
    if step == 1:
        form = ConnectionStep(
            data,
            document_set=docset,
            initial=state,
            allow_unselected=data is not None and data.get("action") == "save_draft",
        )
    elif step == 2:
        if state["mode"] == "advanced":
            form = AdvancedMappingStep(
                data,
                initial={
                    "definition": json.dumps(
                        state.get("definition", {}), ensure_ascii=False, indent=2
                    )
                },
            )
        else:
            initial = visual_initial(state["definition"]) if "definition" in state else None
            form = MappingStep(data, method=profile_method, initial=initial)
    elif step == 3:
        if data is not None and data.get("action") == "configure_preparation":
            # This detour saves inputs and frequency first. Preparation is chosen
            # again on return, after the new policy can actually be reviewed.
            data = data.copy()
            data["preparation_mode"] = "draft_only"
        form = InputStep(
            data,
            definition=state["definition"],
            initial=_input_initial(state),
            preparation_policy=preparation_policy,
            publication_targets=(state.get("schedule") or {}).get("publication_targets")
            if state.get("base_source")
            else None,
        )
    else:
        form = None
    if data is not None:
        action = data.get("action")
        if action not in {
            "next",
            "save",
            "save_draft",
            "advanced",
            "visual",
            "preview",
            "configure_preparation",
        }:
            return HttpResponseBadRequest("İşlem tanınmadı.")
        if form is not None and form.is_valid():
            if step == 1 and action in {"next", "save_draft"}:
                selected = form.cleaned_data["profile"]
                selected_id = str(selected.public_id) if selected else None
                if state.get("profile") != selected_id:
                    if (
                        edit_source is None
                        or selected is None
                        or state.get("definition", {}).get("request", {}).get("method")
                        != selected.method
                    ):
                        state.pop("definition", None)
                        state.pop("inputs", None)
                        state.pop("schedule", None)
                        state["mode"] = "visual"
                    state.pop("profile", None)
                state.update(name=form.cleaned_data["name"], step=2 if selected else 1)
                if selected_id:
                    state["profile"] = selected_id
            elif step == 2 and action in {"next", "save_draft", "advanced", "visual", "preview"}:
                if not isinstance(form, (MappingStep, AdvancedMappingStep)):
                    raise Http404
                definition = (
                    form.cleaned_data["definition"]
                    if isinstance(form, AdvancedMappingStep)
                    else form.definition
                )
                if definition["request"]["method"] != profile_method:
                    error = "İstek yöntemi onaylı bağlantıyla aynı olmalıdır."
                elif action == "preview":
                    try:
                        sample = BoundedJsonField(max_length=100000, max_depth=16).clean(
                            data.get("sample", "")
                        )
                        preview_count = len(preview_rest_response(definition, sample, max_items=20))
                    except (ValidationError, RestContractError, RestPullError, RecursionError):
                        error = (
                            "Örnek yanıt eşlemeyle uyuşmuyor. En çok 20 belge içeren "
                            "sentetik bir JSON kullanın."
                        )
                else:
                    try:
                        if action == "visual":
                            visual_initial(definition)
                    except RestContractError:
                        error = (
                            "Bu eşlemenin tüm ayrıntıları alan görünümünde temsil edilemiyor. "
                            "JSON görünümünde devam edin."
                        )
                    else:
                        if state.get("definition") != definition:
                            state.pop("inputs", None)
                            state.pop("schedule", None)
                        state["definition"] = definition
                        if action == "next":
                            state["step"] = 3
                        elif action != "save_draft":
                            state["mode"] = action
            elif step == 3 and action in {"next", "save_draft", "configure_preparation"}:
                if not isinstance(form, InputStep):
                    raise Http404
                state.update(
                    inputs=form.inputs, schedule=form.schedule, step=4 if action == "next" else 3
                )
            else:
                return HttpResponseBadRequest("Bu adımda işlem kullanılamıyor.")
            if not error and action != "preview":
                if action == "configure_preparation":
                    checkpoint = _save_checkpoint(request, docset, draft_id, drafts, state)
                    if checkpoint.status_code != 302:
                        return checkpoint
                    target = reverse("console:document_set_preparation_settings", args=[public_id])
                    return redirect(f"{target}?setup={draft_id}")
                if action == "save_draft":
                    return _save_checkpoint(request, docset, draft_id, drafts, state)
                try:
                    _store(request, drafts, draft_id, state)
                except RestServiceError:
                    error = "Eşleme boyutu sınırı aşıldı. Tanımları küçültün."
                else:
                    return redirect(
                        "console:rest_setup_draft", public_id=public_id, draft_id=draft_id
                    )
        elif step == 4 and action == "save_draft":
            return _save_checkpoint(request, docset, draft_id, drafts, state)
        elif step == 4 and action == "save":
            try:
                create_setup: Callable[..., Source] = create_rest_setup
                extra = {}
                if edit_source is not None:
                    from apps.ingestion.source_revisions import create_rest_revision

                    create_setup = create_rest_revision
                    extra = {"base_source_id": edit_source.pk, "expected": state["base_token"]}
                source = create_setup(
                    actor=request.user,
                    document_set=docset,
                    profile_id=UUID(state["profile"]),
                    intent=draft_id,
                    name=state["name"],
                    definition=state["definition"],
                    inputs=state["inputs"],
                    schedule=state.get("schedule"),
                    draft_revision=state.get("saved_revision"),
                    **extra,
                )
            except (
                RestAuthorizationError,
                RestServiceError,
                RestContractError,
                ConnectionError,
                ValidationError,
            ) as exc:
                error = (
                    "Hazırlama ayarları değişmiş veya kullanılamıyor. "
                    "Önceki adıma dönüp seçiminizi yeniden kontrol edin."
                    if getattr(exc, "code", "").startswith("REST_SETUP_PREPARATION_")
                    else "Kaynak kaydedilemedi. Doküman setinin durumunu, bağlantı iznini "
                    "ve eşlemeyi kontrol edin."
                )
            else:
                # A completed form becomes a locator; configuration/input values no
                # longer need to remain in the session. Replays redirect to the source.
                _store(
                    request,
                    drafts,
                    draft_id,
                    {
                        "actor": state["actor"],
                        "set": state["set"],
                        "created": state["created"],
                        "saved_source": source.pk,
                    },
                )
                messages.success(
                    request,
                    "Kaynak kaydedildi. Belge yenilemeyi kaynak ekranından başlatabilirsiniz.",
                )
                return redirect("console:connector_source_detail", source_pk=source.pk)
        elif form is None:
            return HttpResponseBadRequest("Bu adımda işlem kullanılamıyor.")
    if error:
        state = original_state
    differences = []
    if edit_source is not None and state["step"] == 4:
        from apps.ingestion.source_revisions import revision_diff

        try:
            differences = revision_diff(edit_source, state)
        except RestServiceError:
            error = "Mevcut plan veya hazırlama ayarları değişti. Kaynak ekranından yeniden açın."
    return render(
        request,
        "console/rest_setup.html",
        {
            "set": docset,
            "form": form,
            "editing_source": edit_source,
            "configuration_diff": differences,
            "step": step,
            "submission": _token(state, draft_id),
            "error": error,
            "preview_count": preview_count,
            "mode": state["mode"],
            "source_name": state.get("name", ""),
            "profile_label": f"{profile.logical_id} · r{profile.revision} · {profile.method}"
            if profile
            else "",
            "pagination": state.get("definition", {}).get("pagination", {}).get("mode", ""),
            "preparation_policy": preparation_policy,
            "preparation_selected": preparation_selected,
            "publication_selected": bool((state.get("schedule") or {}).get("publication_targets")),
            "preparation_error": preparation_error,
            "input_count": len(state.get("inputs", {})),
            "schedule_interval": state.get("schedule", {}).get("interval_seconds")
            if state.get("schedule")
            else None,
            "probe_url": reverse("console:rest_setup_probe", args=[public_id, draft_id]),
            "cancel_url": reverse("console:document_set_connectors_public", args=[public_id]),
        },
        status=400 if error or (form is not None and form.errors) else 200,
    )


@login_required
@durable_operator_view
@require_POST
def probe(request, public_id, draft_id):
    from apps.console.views import _scoped_document_set

    if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        raise Http404
    if settings.SESSION_ENGINE not in SERVER_SESSION_ENGINES:
        raise Http404
    if _oversized(request, 5000):
        return HttpResponseBadRequest("Form boyutu sınırı aşıldı.")
    with operator_transaction(request.user):
        docset = _scoped_document_set(request.user, public_id=public_id)
        if not can_manage_documents(request.user, docset.organization_id, document_set=docset):
            raise PermissionDenied
        state = copy.deepcopy(request.session.get(SESSION_KEY, {}).get(str(draft_id)))
        if (
            state is None
            or state.get("actor") != request.user.pk
            or state.get("set") != docset.pk
            or state.get("step") != 4
            or time.time() - state.get("created", 0) >= MAX_AGE
        ):
            return render(request, "console/rest_setup_expired.html", {"set": docset}, status=400)
        try:
            submitted = signing.loads(
                request.POST.get("submission", ""), salt=SALT, max_age=MAX_AGE
            )
            if submitted != {"id": str(draft_id), "digest": _digest(state)}:
                raise signing.BadSignature
        except signing.BadSignature:
            return render(request, "console/rest_setup_expired.html", {"set": docset}, status=400)
    try:
        result = probe_rest_connection(
            actor=request.user,
            organization_id=docset.organization_id,
            document_set_id=docset.pk,
            profile_id=UUID(state["profile"]),
            definition=state["definition"],
            inputs=state["inputs"],
            request_id=str(getattr(request, "request_id", "")),
        )
    except (
        RestAuthorizationError,
        RestServiceError,
        RestContractError,
        RestPullError,
        ConnectionError,
    ) as exc:
        message = "Bağlantı kontrolü tamamlanamadı. Onaylı bağlantıyı ve eşlemeyi kontrol edin."
        if getattr(exc, "code", "") == "REST_PROBE_RATE_LIMITED":
            message = "Bağlantı yakın zamanda kontrol edildi. Biraz bekleyip yeniden deneyin."
        messages.error(request, message)
    else:
        messages.success(
            request,
            f"Bağlantının ilk yanıtında {result.mapped_count} belge eşlendi. "
            "Bu kontrol belge veya kaynak kaydetmez.",
        )
    return redirect("console:rest_setup_draft", public_id=public_id, draft_id=draft_id)
