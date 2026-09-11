"""Gated resource source setup through the shared catalog and job services."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.mcp_services import create_mcp_resource_source
from apps.ingestion.models import McpResourceProfile, TenantMcpResourceGrant
from apps.tenancy.services import can_manage_documents

SALT = "console.mcp-resource-source/v1"


class ProfileChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.logical_id} · r{obj.revision}"


class ResourceSourceForm(forms.Form):
    name = forms.CharField(max_length=200, label="Kaynak adı")
    profile = ProfileChoice(
        queryset=McpResourceProfile.objects.none(),
        to_field_name="public_id",
        label="Onaylı bağlantı",
    )
    resource_prefixes = forms.CharField(
        required=False,
        max_length=105000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Alınacak kaynak alanları (isteğe bağlı)",
        help_text=(
            "Boş bırakırsanız bağlantı için onaylanan tüm alanlar alınır. "
            "Daraltmak için her satıra bir kaynak URI öneki yazın."
        ),
    )
    submission = forms.CharField(widget=forms.HiddenInput(), max_length=1024)

    def __init__(self, *args, document_set, actor, **kwargs):
        super().__init__(*args, **kwargs)
        ids = (
            TenantMcpResourceGrant.objects.filter(
                organization_id=document_set.organization_id,
                document_set=document_set,
                enabled=True,
                profile__status="active",
            )
            .order_by("profile__logical_id", "-profile__revision")
            .values("profile_id")[:200]
        )
        cast(
            forms.ModelChoiceField, self.fields["profile"]
        ).queryset = McpResourceProfile.objects.filter(pk__in=ids).order_by(
            "logical_id", "-revision"
        )
        if not self.is_bound:
            self.initial["submission"] = signing.dumps(
                {"actor": actor.pk, "set": document_set.pk, "slug": f"mcp-{uuid4().hex}"}, salt=SALT
            )


@login_required
@require_http_methods(["GET", "POST"])
def create_source(request, public_id):
    from apps.console.views import _scoped_document_set

    if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        raise Http404
    docset = _scoped_document_set(request.user, public_id=public_id)
    if not can_manage_documents(request.user, docset.organization_id, document_set=docset):
        raise PermissionDenied
    form = ResourceSourceForm(
        request.POST if request.method == "POST" else None, document_set=docset, actor=request.user
    )
    if request.method == "POST" and form.is_valid():
        try:
            intent = signing.loads(form.cleaned_data["submission"], salt=SALT, max_age=3600)
            if (
                not isinstance(intent, dict)
                or intent.get("actor") != request.user.pk
                or intent.get("set") != docset.pk
            ):
                raise signing.BadSignature()
            profile = form.cleaned_data["profile"]
            scopes = [
                line.strip()
                for line in form.cleaned_data["resource_prefixes"].splitlines()
                if line.strip()
            ]
            source = create_mcp_resource_source(
                actor=request.user,
                organization=docset.organization,
                document_set=docset,
                profile=profile,
                slug=intent["slug"],
                name=form.cleaned_data["name"],
                resource_prefixes=scopes or list(profile.resource_prefixes),
            )
        except signing.BadSignature:
            form.add_error(
                None, "Formun süresi doldu veya başka bir kullanıcıya ait. Sayfayı yeniden açın."
            )
        except (McpResourceError, ValidationError):
            form.add_error(
                None, "Kaynak kaydedilemedi. Bağlantı iznini ve kaynak alanlarını kontrol edin."
            )
        else:
            messages.success(
                request, "Kaynak kaydedildi. Hazır olduğunuzda belge yenilemeyi başlatabilirsiniz."
            )
            return redirect("console:connector_source_detail", source_pk=source.pk)
    return render(
        request,
        "console/mcp_source_form.html",
        {"set": docset, "form": form},
        status=400 if form.errors else 200,
    )


@login_required
@require_POST
def job_action(request, source_pk, public_id):
    from apps.console.views import _scoped_connector_source
    from apps.ingestion.confluence import ConfluenceError
    from apps.ingestion.connections import ConnectionError
    from apps.ingestion.connector_jobs import ConnectorJobError, change_connector_job
    from apps.ingestion.rest import RestPullError

    source = _scoped_connector_source(request.user, source_pk)
    if not can_manage_documents(
        request.user, source.organization_id, document_set=source.document_set
    ):
        raise PermissionDenied
    job = source.ingestion_jobs.filter(
        public_id=public_id, organization_id=source.organization_id
    ).first()
    if job is None:
        raise Http404
    action = request.POST.get("action", "")
    if action not in {"cancel", "retry"}:
        raise PermissionDenied
    try:
        change_connector_job(
            public_id=str(job.public_id),
            organization_id=source.organization_id,
            actor=request.user,
            action=action,
        )
    except (ConnectorJobError, ConnectionError, McpResourceError, RestPullError, ConfluenceError):
        messages.error(
            request, "İş güncellenemedi. Güncel durumunu ve bağlantı izinlerini kontrol edin."
        )
    else:
        messages.success(request, "İşlem kaydedildi. Güncel durumu aşağıda görebilirsiniz.")
    return redirect("console:connector_source_detail", source_pk=source.pk)
