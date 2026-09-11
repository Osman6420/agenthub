"""Safe resource-job metadata projection; transport and document content stay out."""

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

from apps.ingestion.models import ResourceSnapshot, Source, StagedIndexBuildJob


def connector_state_label(value: str) -> str:
    return {
        "active": "Etkin",
        "disabled": "Devre dışı",
        "dispatch_pending": "Sıraya alınıyor",
        "queued": "Sırada",
        "running": "Çalışıyor",
        "retry_wait": "Yeniden denemeyi bekliyor",
        "retry": "Yeniden denemeyi bekliyor",
        "succeeded": "Tamamlandı",
        "failed": "Başarısız",
        "dead_letter": "İnceleme gerekiyor",
        "cancelled": "İptal edildi",
        "reconciliation_required": "Sonucun doğrulanması gerekiyor",
        "building": "Hazırlanıyor",
        "promotable": "Kullanıma alınmaya hazır",
        "idle": "Bekliyor",
    }.get(value, "Durum doğrulanmalı")


def source_preparation(job: StagedIndexBuildJob | None) -> dict[str, object] | None:
    """Show exact linked preparation without confusing fetch success with readiness."""
    if job is None:
        return None
    build = job.preparation_job
    run = job.rest_sync_run or job.confluence_sync_run
    if job.kind == "mcp_resource_sync":
        run = getattr(job, "resource_snapshot", None)
    publication = ""
    if (
        run is not None
        and run.schedule is not None
        and run.schedule.automation_mode == "promote_if_safe"
    ):
        outbox = getattr(job, "outbox", None)
        code = outbox.completion_error_code if outbox else ""
        if outbox and outbox.completion_published_at:
            from apps.releases.models import ScenarioPublication

            completed = ScenarioPublication.objects.filter(
                source_job=job, organization_id=job.organization_id, completed_at__isnull=False
            ).exists()
            publication = (
                "Belgeler ve onaylı senaryo yayınları birlikte kullanıma alındı."
                if completed
                else (
                    "Bu yenileme için otomatik yayın kaydı yok. "
                    "Plan sonraki yenilemelere uygulanır."
                )
            )
        elif not run.schedule.enabled:
            publication = "Yayın planı kapalı. Mevcut yayınlar korundu."
        elif code == "PUBLICATION_EVALUATION_NOT_PASSED":
            publication = (
                "Testler geçmedi. Mevcut belgeler ve yayınlar korundu. "
                "Sonuçları senaryo sayfasından inceleyin."
            )
        elif code and code != "PUBLICATION_PREPARATION_PENDING":
            publication = (
                "Yayın bekliyor. Kaynak, hazırlama ayarları veya senaryo onayları "
                "değişmiş olabilir. Mevcut yayınlar korundu."
            )
        else:
            publication = (
                "Hazırlık ve bütün senaryoların kontrolleri tamamlanınca birlikte yayınlanacak."
            )
    if build is not None:
        return {
            "job": build,
            "label": connector_state_label(build.status),
            "blocker": "",
            "publication": publication,
        }
    if (
        job.status != "succeeded"
        or run is None
        or run.schedule is None
        or run.schedule.automation_mode not in {"stage_only", "promote_if_safe"}
    ):
        return None
    if not run.schedule.enabled:
        return {"job": None, "label": "Hazırlama planı kapalı", "blocker": ""}
    outbox = getattr(job, "outbox", None)
    code = outbox.completion_error_code if outbox else ""
    blocker = {
        "PREPARATION_POLICY_CONFLICT": (
            "Yenileme planı ile doküman setinin hazırlama ayarları uyuşmuyor. Ayarları eşleştirin."
        ),
        "PREPARATION_EMBEDDING_NOT_GRANTED": (
            "Hazırlama için gereken model bağlantısı kullanılamıyor. "
            "Platform yöneticisi izni kontrol etmeli."
        ),
        "PREPARATION_OCR_NOT_GRANTED": (
            "Metin okuma bağlantısı kullanılamıyor. Platform yöneticisi izni kontrol etmeli."
        ),
    }.get(
        code,
        "Hazırlama başlatılamadı. Kaynak iznini ve doküman setinin "
        "hazırlama ayarlarını kontrol edin."
        if code
        else "",
    )
    return {
        "job": None,
        "label": "Hazırlama bekliyor",
        "blocker": blocker,
        "publication": publication,
    }


def latest_source_job(source: Source) -> StagedIndexBuildJob | None:
    return (
        source.ingestion_jobs.select_related(
            "preparation_job",
            "outbox",
            "rest_sync_run__schedule",
            "confluence_sync_run__schedule",
            "resource_snapshot__schedule",
        )
        .order_by("-created_at", "-pk")
        .first()
    )


def latest_preparable_job(source: Source) -> StagedIndexBuildJob | None:
    """Later no-change or failed refreshes do not hide the exact earlier candidate."""
    return (
        source.ingestion_jobs.select_related(
            "preparation_job",
            "outbox",
            "rest_sync_run__schedule",
            "confluence_sync_run__schedule",
            "resource_snapshot__schedule",
        )
        .filter(
            Q(
                rest_sync_run__snapshot_complete=True,
                rest_sync_run__candidate_set_version__isnull=False,
            )
            | Q(
                confluence_sync_run__snapshot_complete=True,
                confluence_sync_run__candidate_set_version__isnull=False,
            )
            | Q(
                resource_snapshot__snapshot_complete=True,
                resource_snapshot__candidate_set_version__isnull=False,
            ),
            status="succeeded",
        )
        .order_by("-created_at", "-pk")
        .first()
    )


def source_run_history(source: Source):
    """A later failure never hides the most recent successful refresh."""
    if source.connector_type == "mcp_resource":
        history = source.ingestion_jobs.filter(organization_id=source.organization_id)
        return (
            history.filter(status="succeeded").order_by("-finished_at", "-pk").first(),
            history.exclude(error_code="").order_by("-updated_at", "-pk").first(),
        )
    sync_history = (
        source.rest_sync_runs
        if source.connector_type == "generic_rest"
        else source.confluence_sync_runs
    )
    return (
        sync_history.filter(status="succeeded").order_by("-finished_at", "-pk").first(),
        sync_history.exclude(error_code="").order_by("-updated_at", "-pk").first(),
    )


def source_readiness(source: Source) -> tuple[bool, str]:
    """Read-only presentation; command admission still reauthorizes every POST."""
    from apps.ingestion.confluence import ConfluenceError
    from apps.ingestion.confluence_sync import _validate_runtime_grant as validate_confluence
    from apps.ingestion.job_lifecycle import ACTIVE_STATES
    from apps.ingestion.models import ConfluenceSyncRun, RestSyncRun
    from apps.ingestion.rest import RestPullError
    from apps.ingestion.rest_sync import _validate_runtime_grant as validate_rest

    if source.connector_type == "mcp_resource":
        return resource_readiness(source)
    blocked = "Kaynak, doküman seti veya bağlantı izni kullanıma uygun değil."
    if (
        not source.is_active
        or source.document_set is None
        or source.document_set.status != "active"
        or source.organization.status != "active"
    ):
        return False, blocked
    try:
        if source.connector_type == "generic_rest":
            if source.rest_profile is None or source.rest_contract is None:
                return False, blocked
            validate_rest(
                RestSyncRun(
                    organization_id=source.organization_id,
                    source=source,
                    rest_profile=source.rest_profile,
                    rest_contract=source.rest_contract,
                )
            )
            busy = source.rest_sync_runs.filter(status__in=["queued", "running", "retry"]).exists()
        elif source.connector_type == "confluence_dc":
            if source.confluence_profile is None:
                return False, blocked
            validate_confluence(
                ConfluenceSyncRun(
                    organization_id=source.organization_id,
                    source=source,
                    confluence_profile=source.confluence_profile,
                )
            )
            busy = source.confluence_sync_runs.filter(
                status__in=["queued", "running", "retry"]
            ).exists()
        else:
            return False, blocked
    except (RestPullError, ConfluenceError):
        return False, blocked
    if source.ingestion_jobs.filter(status__in=ACTIVE_STATES).exists() or busy:
        return False, "Bu kaynak için bir yenileme işi zaten takip ediliyor."
    return True, ""


def resource_readiness(source: Source) -> tuple[bool, str]:
    from django.conf import settings

    from apps.ingestion.connections import ConnectionError
    from apps.ingestion.job_lifecycle import ACTIVE_STATES
    from apps.ingestion.mcp_resources import McpResourceError
    from apps.ingestion.mcp_services import validate_mcp_source

    if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        return False, "MCP belge yenileme henüz etkinleştirilmedi."
    try:
        validate_mcp_source(source)
    except (McpResourceError, ConnectionError):
        return False, "Kaynak, doküman seti veya bağlantı izni kullanıma uygun değil."
    if source.ingestion_jobs.filter(status__in=ACTIVE_STATES).exists():
        return False, "Bu kaynak için bir yenileme işi zaten takip ediliyor."
    return True, ""


@dataclass(frozen=True)
class ResourceRunSummary:
    id: int
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str
    snapshot_complete: bool
    discovered_count: int
    changed_count: int
    unchanged_count: int
    missing_count: int
    fetched_bytes: int


def latest_resource_run(source: Source) -> ResourceRunSummary | None:
    evidence = (
        ResourceSnapshot.objects.select_related("job")
        .filter(
            job__source=source,
            organization_id=source.organization_id,
        )
        .order_by("-job__created_at", "-pk")
        .first()
    )
    if evidence is None:
        return None
    job = evidence.job
    return ResourceRunSummary(
        id=job.pk,
        status=job.status,
        created_at=job.created_at,
        started_at=job.claimed_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        snapshot_complete=evidence.snapshot_complete,
        discovered_count=evidence.discovered_count,
        changed_count=evidence.changed_count,
        unchanged_count=evidence.unchanged_count,
        missing_count=evidence.missing_count,
        fetched_bytes=evidence.fetched_bytes,
    )


def resource_profile_label(source: Source) -> str:
    if source.connection is None or source.connection.mcp_resource_profile is None:
        return "Bağlantı kullanılamıyor"
    profile = source.connection.mcp_resource_profile
    return f"{profile.logical_id} · r{profile.revision}"
