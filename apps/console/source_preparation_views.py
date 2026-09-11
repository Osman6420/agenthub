"""Explicit preparation of a completed source refresh with reviewed set settings."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.ingestion.connector_jobs import _load_run, _validate_inputs
from apps.ingestion.manual_preparation import PREPARATION_ERRORS, prepare_source_snapshot
from apps.ingestion.rest_setup_schedule import preparation_fingerprint, setup_preparation_policy


def preparation_review(job):
    """Presentation only; the POST service repeats authority and exact-input checks."""
    if (
        job is None
        or job.status != "succeeded"
        or job.preparation_job_id is not None
        or not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False)
    ):
        return None
    try:
        run = _load_run(job)
        if not run.snapshot_complete or run.candidate_set_version_id is None:
            return None
        _validate_inputs(job, run)
        docset = run.source.document_set
        candidate = run.candidate_set_version
        if docset is None or candidate is None:
            return None
        policy = setup_preparation_policy(docset)
    except PREPARATION_ERRORS:
        return {
            "job": job,
            "blocker": "Hazırlama ayarları veya bağlantı izinleri kullanıma uygun değil. "
            "Doküman setinin ayarlarını ve platform bağlantı izinlerini kontrol edin.",
        }
    if not candidate.memberships.exists():
        return {"job": job, "blocker": "Bu yenilemede hazırlanabilecek belge bulunmuyor."}
    return {"job": job, "policy": policy, "fingerprint": preparation_fingerprint(policy)}


@login_required
@require_POST
def prepare(request, source_pk, job_public_id):
    from apps.console.views import _scoped_connector_source, connector_source_detail

    if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        raise Http404
    source = _scoped_connector_source(request.user, source_pk)
    # CSRF middleware may already have consumed a multipart request body.
    if (
        request.FILES
        or set(request.POST) - {"csrfmiddlewaretoken", "policy"}
        or any(len(values) != 1 for _, values in request.POST.lists())
        or sum(len(key.encode()) + len(value.encode()) for key, value in request.POST.items())
        > 4096
    ):
        messages.error(request, "Hazırlama isteğini sayfadaki güncel ayarlarla yeniden gönderin.")
        response = connector_source_detail(request, source_pk)
        response.status_code = 400
        return response
    try:
        build = prepare_source_snapshot(
            actor=request.user,
            source=source,
            job_public_id=job_public_id,
            expected_policy=request.POST.get("policy", ""),
        )
    except PREPARATION_ERRORS as exc:
        if exc.code == "PREPARATION_MANAGER_REQUIRED":
            raise PermissionDenied from exc
        if exc.code == "PREPARATION_SOURCE_JOB_NOT_FOUND":
            raise Http404 from exc
        messages.error(
            request,
            {
                "REST_SETUP_PREPARATION_CHANGED": "Hazırlama ayarları değişti. Güncel ayarları "
                "inceleyip yeniden başlatın.",
                "PREPARATION_ALREADY_LINKED": "Bu yenileme bir hazırlama işine zaten bağlı. "
                "Durumunu aşağıdan izleyebilirsiniz.",
                "PREPARATION_COMPLETE_SNAPSHOT_REQUIRED": "Önce belge yenilemenin tamamlanması "
                "ve hazırlanabilecek bir belge sürümü oluşması gerekiyor.",
                "SET_VERSION_EMPTY": "Bu yenilemede hazırlanabilecek belge bulunmuyor.",
            }.get(
                exc.code,
                "Hazırlama başlatılamadı. Kaynak iznini ve doküman setinin güncel hazırlama "
                "ayarlarını kontrol edin.",
            ),
        )
        response = connector_source_detail(request, source_pk)
        response.status_code = 400
        return response
    if build.status in {"failed", "cancelled", "reconciliation_required"}:
        messages.info(
            request,
            "Mevcut hazırlama işi açıldı. Durumunu ve yeniden deneme "
            "seçeneklerini aşağıdan inceleyebilirsiniz.",
        )
    elif build.status == "succeeded":
        messages.success(request, "Bu belgeler için tamamlanmış hazırlama işi açıldı.")
    else:
        messages.success(
            request, "Hazırlama işi kaydedildi. İlerlemeyi bu sayfadan izleyebilirsiniz."
        )
    return redirect("console:connector_source_detail", source_pk=source.pk)
