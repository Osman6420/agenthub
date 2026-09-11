"""Bounded scope selection before the existing four-step REST setup."""

from __future__ import annotations

import time
from typing import cast
from uuid import UUID, uuid4

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.console.context import resolve_active_organization
from apps.console.rest_setup_views import (
    MAX_AGE,
    MAX_DRAFTS,
    SERVER_SESSION_ENGINES,
    _oversized,
    resume,
)
from apps.documents.models import DocumentSet
from apps.documents.services import DocumentError
from apps.identity.assignment_services import AssignmentError
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError
from apps.ingestion.rest_setup_scope import (
    begin_rest_setup,
    can_begin_new_set,
    manageable_setup_sets,
)

ENTRY_KEY = "rest_setup_entry_v1"
ENTRY_SALT = "console.rest-setup-entry/v1"


class SetChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class ScopeStep(forms.Form):
    source_name = forms.CharField(max_length=200, label="Kaynak adı")
    scope_mode = forms.ChoiceField(
        label="Belgeler nerede toplansın?",
        initial="existing",
        choices=[("existing", "Mevcut doküman seti"), ("new", "Yeni doküman seti")],
    )
    document_set = SetChoice(
        queryset=DocumentSet.objects.none(),
        to_field_name="public_id",
        required=False,
        label="Doküman seti",
    )
    new_set_name = forms.CharField(max_length=200, required=False, label="Yeni doküman setinin adı")
    manage_new_set = forms.BooleanField(
        required=False,
        label="Oluşturduğum yeni doküman setinin yöneticiliğini üstleniyorum.",
    )

    def __init__(self, *args, actor, organization, search="", **kwargs):
        super().__init__(*args, **kwargs)
        self.can_create = can_begin_new_set(actor, organization)
        choices = manageable_setup_sets(actor, organization).filter(name__icontains=search)
        selected = choices.order_by("name", "pk").values("pk")[:100]
        cast(
            forms.ModelChoiceField, self.fields["document_set"]
        ).queryset = DocumentSet.objects.filter(pk__in=selected).order_by("name", "pk")
        if not self.can_create:
            self.fields["scope_mode"] = forms.ChoiceField(
                choices=[("existing", "Mevcut doküman seti")], label="Belgeler nerede toplansın?"
            )
            self.fields.pop("new_set_name")
            self.fields.pop("manage_new_set")

    def clean(self):
        values = super().clean() or {}
        if values.get("scope_mode") == "new":
            if values.get("document_set") is not None:
                self.add_error("document_set", "Yeni set oluştururken mevcut set seçmeyin.")
            if not values.get("new_set_name"):
                self.add_error("new_set_name", "Yeni doküman setinin adını yazın.")
            if not values.get("manage_new_set"):
                self.add_error("manage_new_set", "Yeni setin yöneticiliğini açıkça seçin.")
        elif values.get("scope_mode") == "existing":
            if values.get("document_set") is None:
                self.add_error("document_set", "Yönetebildiğiniz bir doküman seti seçin.")
            if values.get("new_set_name") or values.get("manage_new_set"):
                self.add_error(None, "Mevcut seti kullanmak için yeni set alanlarını boş bırakın.")
        return values


@login_required
@require_http_methods(["GET", "POST"])
def start(request):
    if (
        not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False)
        or settings.SESSION_ENGINE not in SERVER_SESSION_ENGINES
    ):
        raise Http404
    organization = resolve_active_organization(request)
    if organization is None or not organization.is_active:
        raise PermissionDenied
    if not (
        can_begin_new_set(request.user, organization)
        or manageable_setup_sets(request.user, organization).exists()
    ):
        raise PermissionDenied
    if _oversized(request, 6000):
        return HttpResponseBadRequest("Form boyutu sınırı aşıldı.")
    now = time.time()
    entries = {
        key: value
        for key, value in request.session.get(ENTRY_KEY, {}).items()
        if value.get("actor") == request.user.pk and now - value.get("created", 0) < MAX_AGE
    }
    supplied = request.POST.get("entry") if request.method == "POST" else request.GET.get("entry")
    entry_id = str(uuid4()) if not supplied and request.method == "GET" else supplied
    if supplied:
        state = entries.get(supplied)
        if state is None or state.get("organization") != organization.pk:
            return HttpResponseBadRequest(
                "Bu kurulum başlangıcının süresi doldu. Dokümanlar ekranından yeniden başlayın."
            )
    else:
        if request.method == "POST":
            return HttpResponseBadRequest("Kurulum başlangıcı bulunamadı.")
        while len(entries) >= MAX_DRAFTS:
            entries.pop(min(entries, key=lambda key: entries[key]["created"]))
        state = {"actor": request.user.pk, "organization": organization.pk, "created": now}
        entries[entry_id] = state
    binding = {"id": entry_id, **state}
    if request.method == "POST":
        try:
            if (
                signing.loads(request.POST.get("submission", ""), salt=ENTRY_SALT, max_age=MAX_AGE)
                != binding
            ):
                raise signing.BadSignature
        except signing.BadSignature:
            return HttpResponseBadRequest("Form doğrulanamadı. Sayfayı yeniden açın.")
    request.session[ENTRY_KEY] = entries
    search = request.GET.get("q", "").strip()
    if len(search) > 80:
        return HttpResponseBadRequest("Arama metni en çok 80 karakter olabilir.")
    form = ScopeStep(
        request.POST if request.method == "POST" else None,
        actor=request.user,
        organization=organization,
        search=search,
    )
    if request.method == "POST":
        if set(request.POST) - (set(form.fields) | {"entry", "submission", "csrfmiddlewaretoken"}):
            return HttpResponseBadRequest("Formda tanınmayan alan var.")
        if form.is_valid():
            try:
                saved = begin_rest_setup(
                    actor=request.user,
                    organization=organization,
                    intent=UUID(entry_id),
                    source_name=form.cleaned_data["source_name"],
                    document_set=form.cleaned_data.get("document_set"),
                    new_set_name=form.cleaned_data.get("new_set_name", ""),
                    manage_new_set=form.cleaned_data.get("manage_new_set", False),
                )
            except (
                RestAuthorizationError,
                RestServiceError,
                DocumentError,
                AssignmentError,
                ValidationError,
                IntegrityError,
            ):
                form.add_error(
                    None,
                    "Kurulum kaydedilemedi. Yetkiniz değişmiş veya beş açık kurulum sınırına "
                    "ulaşmış olabilirsiniz. Kaydettiğiniz kurulumları ve set seçimini "
                    "kontrol edin.",
                )
            else:
                # Use the existing owner/scope reauthorization and session restoration.
                response = resume(
                    request, public_id=saved.document_set.public_id, draft_id=saved.public_id
                )
                messages.success(
                    request,
                    "Kurulum taslağı kaydedildi. Bağlantı izni henüz yoksa daha sonra "
                    "kaynaklar ekranından devam edebilirsiniz.",
                )
                return response
    return render(
        request,
        "console/rest_setup_scope.html",
        {
            "form": form,
            "organization": organization,
            "entry": entry_id,
            "search": search,
            "submission": signing.dumps(binding, salt=ENTRY_SALT),
        },
        status=400 if form.errors else 200,
    )
