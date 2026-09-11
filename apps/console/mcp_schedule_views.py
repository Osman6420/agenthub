"""Collection-manager refresh plans, using the existing shared schedule service."""

from typing import cast

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.catalog.models import Scenario
from apps.console.forms import ConnectorScheduleForm
from apps.documents.models import ScenarioDocumentSetBinding
from apps.identity.authorization import Capability, authorized_scenarios
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.mcp_schedule import configure_mcp_schedule
from apps.ingestion.rest_services import RestServiceError
from apps.ingestion.rest_setup_schedule import preparation_fingerprint, setup_preparation_policy
from apps.tenancy.services import can_manage_documents


class McpScheduleForm(forms.Form):
    interval_seconds = ConnectorScheduleForm.base_fields["interval_seconds"]
    enabled = forms.BooleanField(required=False, label="Periyodik yenilemeyi etkinleştir")
    automation_mode = forms.ChoiceField(
        choices=[("draft_only", "Belgeleri taslakta tut"), ("stage_only", "Aramaya hazırla")],
        label="Yeni belgeler alındığında",
    )
    policy = forms.CharField(required=False, max_length=64, widget=forms.HiddenInput)
    scenarios = forms.ModelMultipleChoiceField(
        queryset=Scenario.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Kontrollerden sonra yayınlanacak senaryolar",
        help_text=(
            "Bu doküman setine bağlı, test ve yayın yetkiniz olan senaryolar listelenir. "
            "Liste boşsa önce senaryoya doküman setini bağlayın ve yetkilerinizi kontrol edin."
        ),
    )

    def __init__(self, *args, actor, document_set, **kwargs):
        super().__init__(*args, **kwargs)
        bound = ScenarioDocumentSetBinding.objects.filter(
            organization_id=document_set.organization_id,
            document_set=document_set,
        ).values_list("scenario_id", flat=True)
        targets = (
            authorized_scenarios(actor, Capability.SCENARIO_RELEASE)
            .filter(
                organization_id=document_set.organization_id,
                pk__in=bound,
            )
            .filter(pk__in=authorized_scenarios(actor, Capability.SCENARIO_TEST).values("pk"))
        )
        cast(forms.ModelMultipleChoiceField, self.fields["scenarios"]).queryset = targets.order_by(
            "name", "pk"
        )
        cast(forms.ChoiceField, self.fields["automation_mode"]).choices = [
            ("draft_only", "Belgeleri taslakta tut"),
            ("stage_only", "Aramaya hazırla"),
            ("promote_if_safe", "Hazırla, dene ve kontroller geçerse yayınla"),
        ]

    def clean(self):
        cleaned = super().clean() or {}
        if cleaned.get("automation_mode") == "promote_if_safe":
            if not cleaned.get("scenarios"):
                self.add_error("scenarios", "En az bir yayın hedefi seçin.")
        elif cleaned.get("scenarios"):
            self.add_error("scenarios", "Senaryo seçimini yalnız otomatik yayın için kullanın.")
        return cleaned


@login_required
@require_http_methods(["GET", "POST"])
def configure(request, source_pk):
    from apps.console.views import _scoped_connector_source

    if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        raise Http404
    source = _scoped_connector_source(request.user, source_pk)
    if source.connector_type != "mcp_resource" or source.document_set is None:
        raise Http404
    if not can_manage_documents(
        request.user, source.organization_id, document_set=source.document_set
    ):
        raise PermissionDenied
    schedule = getattr(source, "sync_schedule", None)
    try:
        policy = setup_preparation_policy(source.document_set)
    except RestServiceError:
        policy = None
    form = McpScheduleForm(
        request.POST if request.method == "POST" else None,
        actor=request.user,
        document_set=source.document_set,
        initial={
            "interval_seconds": schedule.interval_seconds if schedule else 86400,
            "enabled": schedule.enabled if schedule else False,
            "automation_mode": schedule.automation_mode if schedule else "draft_only",
            "policy": preparation_fingerprint(policy) if policy else "",
            "scenarios": list(schedule.promotion_targets.values_list("scenario_id", flat=True))
            if schedule
            else [],
        },
    )
    if request.method == "POST":
        form.is_valid()
        if (
            request.FILES
            or set(request.POST) - {*form.fields, "csrfmiddlewaretoken"}
            or any(len(values) != 1 for key, values in request.POST.lists() if key != "scenarios")
            or len(request.POST.getlist("scenarios")) > 200
        ):
            form.add_error(None, "İsteği sayfadaki alanlarla yeniden gönderin.")
        if not form.errors:
            try:
                configure_mcp_schedule(
                    actor=request.user,
                    source=source,
                    enabled=form.cleaned_data["enabled"],
                    interval_seconds=form.cleaned_data["interval_seconds"],
                    automation_mode=form.cleaned_data["automation_mode"],
                    expected_policy=form.cleaned_data["policy"],
                    scenarios=form.cleaned_data["scenarios"],
                )
            except McpResourceError as exc:
                form.add_error(
                    None,
                    {
                        "REST_SETUP_PREPARATION_CHANGED": (
                            "Hazırlama ayarları değişti. Sayfayı yeniden açıp "
                            "güncel ayarları inceleyin."
                        ),
                        "MCP_RESOURCE_PREPARATION_REVIEW_REQUIRED": (
                            "Önce doküman setinin hazırlama ayarlarını tamamlayın "
                            "ve bu sayfayı yeniden açın."
                        ),
                    }.get(
                        exc.code,
                        "Plan kaydedilemedi. Kaynak ve hazırlama bağlantılarının "
                        "izinlerini kontrol edin.",
                    ),
                )
            else:
                messages.success(
                    request,
                    "Yenileme planı kaydedildi."
                    if form.cleaned_data["enabled"]
                    else "Periyodik yenileme kapatıldı. Başlamış işler kaynak sayfasından "
                    "ayrıca yönetilir.",
                )
                return redirect("console:connector_source_detail", source_pk=source.pk)
    return render(
        request,
        "console/mcp_schedule_form.html",
        {
            "source": source,
            "set": source.document_set,
            "form": form,
            "preparation_policy": policy,
        },
        status=400 if form.errors else 200,
    )
