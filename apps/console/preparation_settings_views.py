"""Collection preparation settings available before the first document version."""

from uuid import UUID

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.artifacts.models import ArtifactVersion
from apps.console.forms import DocumentSetBuildForm
from apps.console.profile_fields import profile_defaults
from apps.ingestion.models import EmbeddingProfile, OcrProfile
from apps.ingestion.preparation_settings import (
    PreparationSettingsError,
    configuration_token,
    current_preparation,
    save_preparation_settings,
)
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError
from apps.ingestion.rest_setup_drafts import load_setup_draft
from apps.tenancy.services import can_manage_documents


class GovernedProfileChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.logical_id} · r{obj.revision}"


class ChunkingChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{(obj.logical_description or obj.logical_id)[:100]} · v{obj.version}"


class PreparationSettingsForm(DocumentSetBuildForm):
    embedding_profile = GovernedProfileChoice(
        queryset=EmbeddingProfile.objects.none(),
        label="Arama modeli",
        empty_label="Arama modeli seçin",
    )
    ocr_profile = GovernedProfileChoice(
        queryset=OcrProfile.objects.none(),
        required=False,
        label="Görsellerden metin okuma",
        empty_label="Kapalı",
    )
    chunking_profile = ChunkingChoice(
        queryset=ArtifactVersion.objects.none(),
        required=False,
        empty_label="Standart parçalama",
        label="Belge parçalama",
    )
    expected = forms.CharField(max_length=64, widget=forms.HiddenInput)
    setup = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("retrieval_profile", "summary_model_profile", "summary_prompt_contract"):
            self.fields.pop(name)
        self.fields["auto_prepare"].label = "Bundan sonra yayımlanan belgeleri otomatik hazırla"


@login_required
@require_http_methods(["GET", "POST"])
def configure(request, public_id):
    from apps.console.rest_setup_views import resume
    from apps.console.views import _scoped_document_set

    docset = _scoped_document_set(request.user, public_id=public_id)
    if not can_manage_documents(request.user, docset.organization_id, document_set=docset):
        raise PermissionDenied
    raw_setup = (
        request.POST.get("setup", "") if request.method == "POST" else request.GET.get("setup", "")
    )
    setup_id = None
    if raw_setup:
        if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
            raise Http404
        try:
            setup_id = UUID(raw_setup)
            draft = load_setup_draft(actor=request.user, document_set=docset, intent=setup_id)
            if draft.completed_source_id or draft.payload.get("step") != 3:
                raise Http404
        except (ValueError, RestServiceError, RestAuthorizationError):
            raise Http404 from None
    policy = current_preparation(docset)
    form = PreparationSettingsForm(
        request.POST if request.method == "POST" else None,
        organization_id=docset.organization_id,
        initial={
            "embedding_profile": policy.embedding_profile_id if policy else None,
            "ocr_profile": policy.ocr_profile_id if policy else None,
            "chunking_profile": policy.chunking_profile_id if policy else None,
            "auto_prepare": policy.auto_prepare if policy else False,
            "expected": configuration_token(policy),
            "setup": setup_id or "",
        },
    )
    if request.method == "POST":
        form.is_valid()
        if (
            request.FILES
            or set(request.POST) - {*form.fields, "csrfmiddlewaretoken"}
            or any(len(values) != 1 for _, values in request.POST.lists())
        ):
            form.add_error(None, "İsteği yalnız sayfadaki alanlarla gönderin.")
        if not form.errors:
            data = form.cleaned_data
            try:
                save_preparation_settings(
                    actor=request.user,
                    document_set=docset,
                    expected=data["expected"],
                    embedding_profile_id=data["embedding_profile"].pk,
                    ocr_profile_id=data["ocr_profile"].pk if data["ocr_profile"] else None,
                    chunking_profile_id=data["chunking_profile"].pk
                    if data["chunking_profile"]
                    else None,
                    standard_chunking=profile_defaults("chunking_profile"),
                    auto_prepare=data["auto_prepare"],
                )
            except PreparationSettingsError as exc:
                if exc.code == "PREPARATION_SETTINGS_FORBIDDEN":
                    raise PermissionDenied from exc
                form.add_error(
                    None,
                    "Ayarlar başka bir işlemle değişti. Sayfayı yeniden açıp "
                    "güncel değerleri inceleyin."
                    if exc.code == "PREPARATION_SETTINGS_CHANGED"
                    else "Ayarlar kaydedilemedi. Doküman setini ve model bağlantılarının "
                    "izinlerini kontrol edin.",
                )
            else:
                messages.success(
                    request,
                    "Hazırlama ayarları kaydedildi. Bu işlem belge alma veya hazırlama başlatmadı.",
                )
                if setup_id is not None:
                    return resume(request, public_id=docset.public_id, draft_id=setup_id)
                return redirect("console:document_set_detail_public", public_id=docset.public_id)
    return render(
        request,
        "console/preparation_settings.html",
        {
            "set": docset,
            "form": form,
            "setup_id": setup_id,
            "standard_chunking": profile_defaults("chunking_profile"),
        },
        status=400 if form.errors else 200,
    )
