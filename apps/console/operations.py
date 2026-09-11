"""Bounded, tenant-first operational projection for the console."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSet
from apps.evaluations.models import EvalRun, QuestionEvaluationRun
from apps.ingestion.models import (
    ConfluenceSyncRun,
    IngestionRun,
    RestSyncRun,
    StagedIndexBuildJob,
)
from apps.tenancy.models import Organization
from apps.workflows.models import Run

PAGE_SIZE = 50
MAX_PAGE = 10
MAX_DAYS = 90


class OperationKind(StrEnum):
    EXECUTION = "execution"
    EVALUATION = "evaluation"
    QUESTION_EVALUATION = "question_evaluation"
    INGESTION = "ingestion"
    INDEX_BUILD = "index_build"
    CONFLUENCE_SYNC = "confluence_sync"
    REST_SYNC = "rest_sync"


class OperationStatusGroup(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    ATTENTION = "attention"
    SUCCEEDED = "succeeded"
    STOPPED = "stopped"


KIND_LABELS = {
    OperationKind.EXECUTION: "Senaryo çalıştırması",
    OperationKind.EVALUATION: "Release değerlendirmesi",
    OperationKind.QUESTION_EVALUATION: "Soru seti değerlendirmesi",
    OperationKind.INGESTION: "İçerik hazırlama",
    OperationKind.INDEX_BUILD: "İndeks oluşturma",
    OperationKind.CONFLUENCE_SYNC: "Confluence eşitleme",
    OperationKind.REST_SYNC: "REST eşitleme",
}
STATUS_LABELS = {
    OperationStatusGroup.ACTIVE: "Aktif",
    OperationStatusGroup.WAITING: "Bekliyor",
    OperationStatusGroup.ATTENTION: "Dikkat gerekli",
    OperationStatusGroup.SUCCEEDED: "Tamamlandı",
    OperationStatusGroup.STOPPED: "Durduruldu",
}

_WAITING = frozenset(
    {
        "waiting_approval",
        "waiting_event",
        "waiting_human",
        "waiting_timer",
        "waiting_child",
        "retry",
        "retry_wait",
    }
)
_ATTENTION = frozenset(
    {
        "failed",
        "error",
        "timed_out",
        "dead_letter",
        "recovery_required",
        "reconciliation_required",
    }
)
_SUCCEEDED = frozenset({"completed", "succeeded", "passed"})
_STOPPED = frozenset({"cancelled", "canceled"})
_ACTIVE = frozenset({"dispatch_pending", "pending", "queued", "requested", "running"})
_EXECUTION_BUCKETS = {
    "active": frozenset(
        {
            "requested",
            "queued",
            "running",
            "waiting_approval",
            "waiting_event",
            "waiting_human",
            "waiting_timer",
            "waiting_child",
        }
    ),
    "attention": frozenset({"failed", "timed_out", "recovery_required"}),
    "done": frozenset({"completed", "cancelled"}),
}


class OperationFilterError(ValueError):
    """Closed-filter validation failure with a stable safe code."""


@dataclass(frozen=True)
class OperationFilters:
    kind: OperationKind | None
    status: OperationStatusGroup | None
    bucket: str | None
    project_id: int | None
    scenario_id: int | None
    document_set_id: int | None
    days: int
    page: int


@dataclass(frozen=True)
class OperationRow:
    operation_id: str
    kind: str
    kind_label: str
    native_status: str
    status_group: str
    status_label: str
    name: str
    context: str
    actor_label: str
    reason_code: str
    started_at: datetime | None
    created_at: datetime
    updated_at: datetime
    duration_seconds: int | None
    href: str


@dataclass(frozen=True)
class OperationPage:
    rows: tuple[OperationRow, ...]
    filters: OperationFilters
    has_previous: bool
    has_next: bool


def _uuid(value: str, code: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise OperationFilterError(code) from None


def parse_operation_filters(
    params: Any,
    *,
    organization: Organization,
) -> OperationFilters:
    raw_kind = str(params.get("kind", "")).strip()
    raw_status = str(params.get("status", "")).strip()
    raw_bucket = str(params.get("bucket", "")).strip()
    try:
        kind = OperationKind(raw_kind) if raw_kind else None
        status = OperationStatusGroup(raw_status) if raw_status else None
    except ValueError:
        raise OperationFilterError("OPERATIONS_FILTER_INVALID") from None
    if raw_bucket and raw_bucket not in _EXECUTION_BUCKETS:
        raise OperationFilterError("OPERATIONS_FILTER_INVALID")
    if raw_bucket and (status is not None or kind not in {None, OperationKind.EXECUTION}):
        raise OperationFilterError("OPERATIONS_FILTER_INVALID")
    if raw_bucket:
        kind = OperationKind.EXECUTION
    try:
        days = int(params.get("days", 30))
        page = int(params.get("page", 1))
    except (TypeError, ValueError):
        raise OperationFilterError("OPERATIONS_FILTER_INVALID") from None
    if not 1 <= days <= MAX_DAYS or not 1 <= page <= MAX_PAGE:
        raise OperationFilterError("OPERATIONS_FILTER_OUT_OF_BOUNDS")

    project_id = None
    scenario_id = None
    document_set_id = None
    if value := str(params.get("project", "")).strip():
        project_id = (
            AIProject.objects.filter(
                organization=organization,
                public_id=_uuid(value, "OPERATIONS_PROJECT_INVALID"),
            )
            .values_list("pk", flat=True)
            .first()
        )
        if project_id is None:
            raise OperationFilterError("OPERATIONS_PROJECT_INVALID")
    if value := str(params.get("scenario", "")).strip():
        scenario = (
            Scenario.objects.filter(
                organization=organization,
                public_id=_uuid(value, "OPERATIONS_SCENARIO_INVALID"),
            )
            .values("pk", "project_id")
            .first()
        )
        if scenario is None or (project_id is not None and scenario["project_id"] != project_id):
            raise OperationFilterError("OPERATIONS_SCENARIO_INVALID")
        scenario_id = int(scenario["pk"])
    if value := str(params.get("document_set", "")).strip():
        document_set_id = (
            DocumentSet.objects.filter(
                organization=organization,
                public_id=_uuid(value, "OPERATIONS_DOCUMENT_SET_INVALID"),
            )
            .values_list("pk", flat=True)
            .first()
        )
        if document_set_id is None:
            raise OperationFilterError("OPERATIONS_DOCUMENT_SET_INVALID")
    return OperationFilters(
        kind=kind,
        status=status,
        bucket=raw_bucket or None,
        project_id=project_id,
        scenario_id=scenario_id,
        document_set_id=document_set_id,
        days=days,
        page=page,
    )


def normalize_status(status: str) -> OperationStatusGroup:
    if status in _WAITING:
        return OperationStatusGroup.WAITING
    if status in _ATTENTION:
        return OperationStatusGroup.ATTENTION
    if status in _SUCCEEDED:
        return OperationStatusGroup.SUCCEEDED
    if status in _STOPPED:
        return OperationStatusGroup.STOPPED
    return OperationStatusGroup.ACTIVE


def _with_status(queryset: Any, filters: OperationFilters) -> Any:
    if filters.bucket is not None:
        return queryset.filter(status__in=_EXECUTION_BUCKETS[filters.bucket])
    if filters.status is None:
        return queryset
    values = {
        OperationStatusGroup.ACTIVE: _ACTIVE,
        OperationStatusGroup.WAITING: _WAITING,
        OperationStatusGroup.ATTENTION: _ATTENTION,
        OperationStatusGroup.SUCCEEDED: _SUCCEEDED,
        OperationStatusGroup.STOPPED: _STOPPED,
    }[filters.status]
    return queryset.filter(status__in=values)


def _opaque_id(kind: OperationKind, pk: object) -> str:
    return salted_hmac("console.operation", f"{kind.value}:{pk}").hexdigest()[:16]


def _duration(
    started_at: datetime | None,
    finished_at: datetime | None,
    updated_at: datetime,
) -> int | None:
    if started_at is None:
        return None
    end = finished_at or updated_at
    return max(0, int((end - started_at).total_seconds()))


def _row(
    *,
    kind: OperationKind,
    obj: Any,
    name: str,
    context: str,
    actor_label: str,
    reason_code: str,
    started_at: datetime | None,
    finished_at: datetime | None,
    href: str,
) -> OperationRow:
    group = normalize_status(str(obj.status))
    return OperationRow(
        operation_id=_opaque_id(kind, obj.pk),
        kind=kind.value,
        kind_label=KIND_LABELS[kind],
        native_status=str(obj.status),
        status_group=group.value,
        status_label=STATUS_LABELS[group],
        name=name[:200],
        context=context[:240],
        actor_label=actor_label,
        reason_code=reason_code[:64],
        started_at=started_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        duration_seconds=_duration(started_at, finished_at, obj.updated_at),
        href=href,
    )


def _limited(queryset: Any, limit: int) -> Iterable[Any]:
    return queryset.order_by("-created_at", "-pk")[:limit]


def project_operations(
    *,
    organization: Organization,
    filters: OperationFilters,
    execution_queryset: QuerySet[Run],
) -> OperationPage:
    """Merge bounded native prefixes and return one stable page.

    The caller must supply the already-authorized execution queryset. Organization and request
    filters only narrow that scope; they never establish run visibility.
    """

    prefix = filters.page * PAGE_SIZE + 1
    since = timezone.now() - timedelta(days=filters.days)
    rows: list[OperationRow] = []
    selected = {filters.kind} if filters.kind is not None else set(OperationKind)

    if OperationKind.EXECUTION in selected and filters.document_set_id is None:
        queryset = _with_status(
            execution_queryset.filter(
                organization=organization,
                created_at__gte=since,
            ),
            filters,
        ).select_related("scenario", "scenario__project", "consumer")
        if filters.project_id is not None:
            queryset = queryset.filter(scenario__project_id=filters.project_id)
        if filters.scenario_id is not None:
            queryset = queryset.filter(scenario_id=filters.scenario_id)
        for run in _limited(queryset, prefix):
            rows.append(
                _row(
                    kind=OperationKind.EXECUTION,
                    obj=run,
                    name=run.scenario.name,
                    context=run.scenario.project.name,
                    actor_label=run.consumer.name,
                    reason_code=run.reason_code or run.error_code,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    href=reverse("console:workflow_run_detail", args=[run.pk]),
                )
            )

    if OperationKind.EVALUATION in selected and filters.document_set_id is None:
        queryset = _with_status(
            EvalRun.objects.filter(
                organization=organization,
                created_at__gte=since,
            ),
            filters,
        ).select_related("release", "release__scenario", "release__scenario__project")
        if filters.project_id is not None:
            queryset = queryset.filter(release__scenario__project_id=filters.project_id)
        if filters.scenario_id is not None:
            queryset = queryset.filter(release__scenario_id=filters.scenario_id)
        for run in _limited(queryset, prefix):
            rows.append(
                _row(
                    kind=OperationKind.EVALUATION,
                    obj=run,
                    name=run.release.scenario.name,
                    context=run.release.scenario.project.name,
                    actor_label="Operatör",
                    reason_code=run.error_code,
                    started_at=run.created_at,
                    finished_at=run.finished_at,
                    href=reverse(
                        "console:scenario_detail_public",
                        args=[run.release.scenario.public_id],
                    ),
                )
            )

    if OperationKind.QUESTION_EVALUATION in selected:
        queryset = _with_status(
            QuestionEvaluationRun.objects.filter(
                organization=organization,
                created_at__gte=since,
            ),
            filters,
        ).select_related(
            "question_set_version",
            "question_set_version__question_set",
            "release",
            "release__scenario",
            "release__scenario__project",
            "document_set_version",
            "document_set_version__document_set",
        )
        if filters.project_id is not None:
            queryset = queryset.filter(release__scenario__project_id=filters.project_id)
        if filters.scenario_id is not None:
            queryset = queryset.filter(release__scenario_id=filters.scenario_id)
        if filters.document_set_id is not None:
            queryset = queryset.filter(
                document_set_version__document_set_id=filters.document_set_id
            )
        for run in _limited(queryset, prefix):
            if run.release_id:
                context = run.release.scenario.name
            elif run.document_set_version_id:
                context = run.document_set_version.document_set.name
            else:
                context = "-"
            rows.append(
                _row(
                    kind=OperationKind.QUESTION_EVALUATION,
                    obj=run,
                    name=run.question_set_version.question_set.name,
                    context=context,
                    actor_label="Operatör",
                    reason_code=run.error_code,
                    started_at=run.created_at,
                    finished_at=run.finished_at,
                    href=reverse("console:question_evaluation_detail", args=[run.public_id]),
                )
            )

    source_families_allowed = filters.project_id is None and filters.scenario_id is None
    if OperationKind.INGESTION in selected and source_families_allowed:
        queryset = _with_status(
            IngestionRun.objects.filter(
                organization=organization,
                created_at__gte=since,
            ),
            filters,
        ).select_related("source", "source__document_set")
        if filters.document_set_id is not None:
            queryset = queryset.filter(source__document_set_id=filters.document_set_id)
        for run in _limited(queryset, prefix):
            rows.append(
                _row(
                    kind=OperationKind.INGESTION,
                    obj=run,
                    name=run.source.name,
                    context=(
                        run.source.document_set.name if run.source.document_set_id else "Kaynak"
                    ),
                    actor_label="Sistem",
                    reason_code=run.error_code,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    href=reverse("console:connector_source_detail", args=[run.source_id]),
                )
            )

    if OperationKind.INDEX_BUILD in selected and source_families_allowed:
        queryset = _with_status(
            StagedIndexBuildJob.objects.filter(
                organization=organization,
                kind="index_build",
                created_at__gte=since,
            ),
            filters,
        ).select_related(
            "document_set_version",
            "document_set_version__document_set",
        )
        if filters.document_set_id is not None:
            queryset = queryset.filter(
                document_set_version__document_set_id=filters.document_set_id
            )
        for job in _limited(queryset, prefix):
            if job.document_set_version is None:
                continue
            document_set = job.document_set_version.document_set
            rows.append(
                _row(
                    kind=OperationKind.INDEX_BUILD,
                    obj=job,
                    name=document_set.name,
                    context=f"Sürüm {job.document_set_version.version}",
                    actor_label="Operatör",
                    reason_code=job.error_code,
                    started_at=job.claimed_at or job.queued_at,
                    finished_at=job.finished_at,
                    href=reverse(
                        "console:document_set_detail_public",
                        args=[document_set.public_id],
                    ),
                )
            )

    for kind, model in (
        (OperationKind.CONFLUENCE_SYNC, ConfluenceSyncRun),
        (OperationKind.REST_SYNC, RestSyncRun),
    ):
        if kind not in selected or not source_families_allowed:
            continue
        queryset = _with_status(
            model.objects.filter(
                organization=organization,
                created_at__gte=since,
            ),
            filters,
        ).select_related("source", "source__document_set")
        if filters.document_set_id is not None:
            queryset = queryset.filter(source__document_set_id=filters.document_set_id)
        for run in _limited(queryset, prefix):
            rows.append(
                _row(
                    kind=kind,
                    obj=run,
                    name=run.source.name,
                    context=run.source.document_set.name,
                    actor_label="Sistem",
                    reason_code=run.error_code,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    href=reverse("console:connector_source_detail", args=[run.source_id]),
                )
            )

    if filters.status is not None:
        rows = [row for row in rows if row.status_group == filters.status.value]
    rows.sort(key=lambda row: (row.created_at, row.operation_id), reverse=True)
    start = (filters.page - 1) * PAGE_SIZE
    visible = tuple(rows[start : start + PAGE_SIZE])
    return OperationPage(
        rows=visible,
        filters=filters,
        has_previous=filters.page > 1,
        has_next=len(rows) > start + PAGE_SIZE,
    )
