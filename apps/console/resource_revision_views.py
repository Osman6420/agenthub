"""Review and save a typed source revision without changing the current writer."""

from copy import deepcopy
from uuid import UUID, uuid4

from django import forms
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render

from apps.console.forms import ConfluenceSourceForm, ConnectorScheduleForm
from apps.console.mcp_source_views import ProfileChoice, ResourceSourceForm
from apps.ingestion.job_lifecycle import _canonical_checksum
from apps.ingestion.models import ConfluenceProfile
from apps.ingestion.resource_revisions import (
    RESOURCE_REVISION_ERRORS,
    create_resource_revision,
    reviewed_configuration,
)
from apps.ingestion.rest_setup_schedule import preparation_fingerprint, setup_preparation_policy
from apps.ingestion.source_revisions import (
    configuration_token,
    revision_for,
    revision_schedule_label,
    schedule_for_edit,
)

SALT = "console.resource-revision/v1"


class ConfluenceRevisionForm(ConfluenceSourceForm):
    confluence_profile = ProfileChoice(
        queryset=ConfluenceProfile.objects.none(), label="Onaylı bağlantı"
    )


def _form(request, source, initial):
    data = request.POST if request.method == "POST" else None
    form: forms.Form
    if source.connector_type == "mcp_resource":
        form = ResourceSourceForm(data, actor=request.user, document_set=source.document_set)
    else:
        form = ConfluenceRevisionForm(data, document_set=source.document_set)
        del form.fields["slug"]
    form.fields.update(
        {
            "submission": forms.CharField(max_length=8192, widget=forms.HiddenInput),
            "review": forms.CharField(required=False, max_length=16384, widget=forms.HiddenInput),
            "sync_mode": forms.ChoiceField(
                label="Yenileme planı",
                choices=[
                    ("manual", "Elle başlat"),
                    ("draft", "Periyodik al; belgeleri taslakta tut"),
                    ("prepare", "Periyodik al ve aramaya hazırla"),
                    ("publish", "Testlerden sonra mevcut onaylı senaryolarda yayınla"),
                ],
            ),
            "interval_seconds": deepcopy(ConnectorScheduleForm.base_fields["interval_seconds"]),
        }
    )
    form.fields[
        "interval_seconds"
    ].help_text = "Yalnızca periyodik yenileme seçildiğinde uygulanır."
    form.initial.update(initial)
    return form


def _values(form, intent, source):
    data = form.cleaned_data
    if source.connector_type == "mcp_resource":
        profile = data["profile"]
        prefixes = [line.strip() for line in data["resource_prefixes"].splitlines() if line.strip()]
        config = {"resource_prefixes": prefixes or list(profile.resource_prefixes)}
    else:
        profile = data["confluence_profile"]
        config = {key: data[key] for key in ("root_page_ids", "excluded_page_ids", "include_root")}
    _, normalized, _ = reviewed_configuration(source, profile.public_id, config)
    schedule = None
    if data["sync_mode"] != "manual":
        schedule = {"interval_seconds": data["interval_seconds"]}
        if data["sync_mode"] in {"prepare", "publish"}:
            if not intent["policy"]:
                raise signing.BadSignature("Preparation review required")
            setup_preparation_policy(source.document_set, expected=intent["policy"])
            schedule["preparation"] = intent["policy"]
            if data["sync_mode"] == "publish":
                if not intent.get("publication_targets"):
                    raise signing.BadSignature("Publication review required")
                schedule["publication_targets"] = intent["publication_targets"]
    return {
        "name": data["name"],
        "profile_id": str(profile.public_id),
        "config": normalized,
        "schedule": schedule,
    }


def edit_resource(request, source):
    # Entry route has already checked login, feature, server session and set manager.
    if source.document_set is None or source.connection_id is None:
        raise Http404
    initial = {}
    if request.method == "GET":
        try:
            revision = revision_for(source)
            schedule = (
                revision.schedule_config
                if revision and not revision.is_current
                else schedule_for_edit(source)
            )
            token = configuration_token(source)
        except RESOURCE_REVISION_ERRORS:
            return HttpResponseBadRequest(
                "Önce kaynak bağlantısını ve yenileme planını kontrol edin."
            )
        try:
            policy = preparation_fingerprint(setup_preparation_policy(source.document_set))
        except RESOURCE_REVISION_ERRORS:
            policy = ""
        initial = {
            "name": source.name,
            "interval_seconds": schedule["interval_seconds"] if schedule else 3600,
            "sync_mode": "publish"
            if schedule and "publication_targets" in schedule
            else "prepare"
            if schedule and "preparation" in schedule
            else "draft"
            if schedule
            else "manual",
            "submission": signing.dumps(
                {
                    "actor": request.user.pk,
                    "source": source.pk,
                    "expected": token,
                    "intent": str(uuid4()),
                    "policy": policy,
                    "publication_targets": (schedule or {}).get("publication_targets", []),
                },
                salt=SALT,
            ),
        }
        if source.connector_type == "mcp_resource":
            initial.update(
                profile=str(source.connection.mcp_resource_profile.public_id),
                resource_prefixes="\n".join(source.connector_config["resource_prefixes"]),
            )
        else:
            initial.update(
                confluence_profile=source.confluence_profile_id,
                root_page_ids="\n".join(source.connector_config["root_page_ids"]),
                excluded_page_ids="\n".join(source.connector_config["excluded_page_ids"]),
                include_root=source.connector_config["include_root"],
            )
    form = _form(request, source, initial)
    review = None
    reviewed_policy = None
    if request.method == "POST":
        if (
            request.FILES
            or set(request.POST) - {*form.fields, "action", "csrfmiddlewaretoken"}
            or any(len(values) != 1 for _, values in request.POST.lists())
            or request.POST.get("action") not in {"review", "save"}
        ):
            return HttpResponseBadRequest("İsteği güncel formdan yeniden gönderin.")
        if form.is_valid():
            try:
                intent = signing.loads(form.cleaned_data["submission"], salt=SALT, max_age=3600)
                if (
                    not isinstance(intent, dict)
                    or intent.get("actor") != request.user.pk
                    or intent.get("source") != source.pk
                ):
                    raise signing.BadSignature()
                values = _values(form, intent, source)
                proof = {
                    "submission": form.cleaned_data["submission"],
                    "checksum": _canonical_checksum(values),
                }
                if request.POST["action"] == "save":
                    if (
                        signing.loads(
                            form.cleaned_data["review"], salt=SALT + "/review", max_age=3600
                        )
                        != proof
                    ):
                        raise signing.BadSignature()
                    candidate = create_resource_revision(
                        actor=request.user,
                        source=source,
                        expected=intent["expected"],
                        intent=UUID(intent["intent"]),
                        profile_id=UUID(values["profile_id"]),
                        name=values["name"],
                        config=values["config"],
                        schedule=values["schedule"],
                    )
                    messages.success(
                        request,
                        "Yeni ayarlar kaydedildi. Belgeleri alıp hazırladıktan sonra "
                        "bu sürüme geçebilirsiniz.",
                    )
                    return redirect("console:connector_source_detail", source_pk=candidate.pk)
                if configuration_token(source) != intent["expected"]:
                    raise signing.BadSignature()
                review = values | {"plan": revision_schedule_label(values["schedule"])}
                if values["schedule"] and "preparation" in values["schedule"]:
                    reviewed_policy = setup_preparation_policy(
                        source.document_set, expected=values["schedule"]["preparation"]
                    )
                review["profile"] = (
                    form.cleaned_data.get("profile") or form.cleaned_data["confluence_profile"]
                )
                form.data = form.data.copy()
                form.data["review"] = signing.dumps(proof, salt=SALT + "/review")
            except (signing.BadSignature, *RESOURCE_REVISION_ERRORS, ValidationError):
                form.add_error(
                    None,
                    "Ayarlar kaydedilemedi. Sayfayı yeniden açıp güncel kaynak, "
                    "hazırlama ayarları ve bağlantı iznini kontrol edin.",
                )
    return render(
        request,
        "console/resource_revision_form.html",
        {
            "source": source,
            "set": source.document_set,
            "form": form,
            "review": review,
            "preparation_policy": reviewed_policy,
        },
        status=400 if form.errors else 200,
    )
