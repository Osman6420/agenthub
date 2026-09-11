"""One reviewed scenario publication with scoped, durable resumption."""

from uuid import UUID, uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.builder.services import BuilderError
from apps.catalog.lifecycle import ScenarioLifecycleError
from apps.console import scoping
from apps.evaluations.services import EvalError
from apps.releases.compiler import CompileError
from apps.releases.lifecycle import LifecycleError
from apps.releases.models import ScenarioPublication
from apps.releases.publication import PublicationError, publication_token, publish_scenario
from apps.tenancy.context import operator_transaction, set_tenant_context
from apps.tenancy.middleware import durable_operator_view
from apps.workflows.compiler import WorkflowCompileError

MESSAGES = {
    "PUBLICATION_REQUEST_INVALID": "Yayın isteği geçersiz. Sayfayı yenileyip tekrar deneyin.",
    "PUBLICATION_SETTINGS_CHANGED": (
        "Ayarlar veya yayındaki sürüm değişti. Güncel durumu inceleyip yeni bir yayın başlatın."
    ),
    "PUBLICATION_INTENT_CONFLICT": "Bu işlem başka ayarlarla başlatılmış. Sayfayı yenileyin.",
    "PUBLICATION_SINGLE_WORKFLOW_REQUIRED": "Yayınlamak için senaryoya tek bir akış bağlayın.",
    "PUBLICATION_CONFIGURATION_INCOMPLETE": (
        "Akışın ayarları tamamlanmamış. Akış ve test sorularını kontrol edin."
    ),
    "PUBLICATION_SCOPE_TOO_LARGE": "Bu senaryonun ayarları tek işlemde yayınlama sınırını aşıyor.",
    "PUBLICATION_EVALUATION_NOT_PASSED": (
        "Testler geçmedi. Sonucu inceleyip ayarları düzeltin. Mevcut yayın korundu."
    ),
    "EVALUATION_ALREADY_RUNNING": (
        "Bu yayının testleri zaten çalışıyor. Sonucu görmek için sayfayı yenileyin."
    ),
    "ACTIVE_ALIAS_REQUIRED": "Senaryonun etkin bir API adı olmalı. Mevcut yayın korundu.",
    "MODEL_PROVIDER_NOT_CONFIGURED": "Yayın için gerçek bir model bağlantısı yapılandırılmalı.",
    "INDEX_NOT_READY": "Belgeler henüz kullanıma hazır değil. Mevcut yayın korundu.",
    "RELEASE_NOT_PROMOTABLE": "Bu adayın durumu değişmiş. Güncel sürümleri inceleyin.",
}


def publication_context(*, scenario, actor, allowed_actions):
    permitted = all(allowed_actions[name] for name in ("compile", "test", "release"))
    rows = list(
        ScenarioPublication.objects.filter(
            organization_id=scenario.organization_id, scenario=scenario
        ).select_related("release", "evaluation")[:10]
    )
    token = ""
    reason = "Yayın için senaryonun düzenleme, test ve yayın yetkileri birlikte gerekir."
    if permitted:
        try:
            token = publication_token(scenario)
            reason = ""
        except (PublicationError, CompileError, WorkflowCompileError):
            reason = "Akışın ayarlarını tamamlayıp tekrar deneyin."
    resumable = next(
        (
            row
            for row in rows
            if token
            and row.source_job_id is None
            and row.created_by == str(actor.pk)
            and row.completed_at is None
            and row.evaluation.status in {"pending", "passed"}
            and row.prepared_checksum == token
        ),
        None,
    )
    return {
        "publication": {
            "enabled": permitted and bool(token),
            "reason": reason,
            "intent": resumable.public_id if resumable else uuid4(),
            "expected": resumable.request_checksum if resumable else token,
            "resuming": resumable is not None,
            "rows": rows,
        }
    }


@durable_operator_view
@login_required
@require_POST
def publish(request, public_id):
    from django.shortcuts import get_object_or_404

    with operator_transaction(request.user):
        scenario = get_object_or_404(scoping.scoped_scenarios(request.user), public_id=public_id)
        set_tenant_context(scenario.organization_id)
    try:
        if any(len(request.POST.getlist(name)) != 1 for name in ("intent", "expected")):
            raise PublicationError("PUBLICATION_REQUEST_INVALID")
        try:
            intent = UUID(request.POST["intent"])
        except (ValueError, TypeError) as exc:
            raise PublicationError("PUBLICATION_REQUEST_INVALID") from exc
        publish_scenario(
            actor=request.user,
            scenario=scenario,
            intent=intent,
            expected=request.POST["expected"],
            request_id=getattr(request, "request_id", ""),
        )
    except PermissionDenied:
        raise
    except (
        PublicationError,
        BuilderError,
        CompileError,
        EvalError,
        LifecycleError,
        ScenarioLifecycleError,
        WorkflowCompileError,
    ) as exc:
        messages.error(
            request,
            MESSAGES.get(
                getattr(exc, "code", "PUBLICATION_CONFIGURATION_INCOMPLETE"),
                "Yayın tamamlanamadı. Akış, test sonuçları ve belge hazırlığını kontrol edin.",
            ),
        )
    else:
        messages.success(request, "Testler geçti; senaryo yayına alındı.")
    return redirect("console:scenario_detail_public", public_id=scenario.public_id)
