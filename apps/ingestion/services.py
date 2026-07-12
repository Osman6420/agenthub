"""Ingestion run state machine, source lock, and staged index writer."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_event
from apps.ingestion.connectors import ConnectorError, get_connector
from apps.ingestion.models import (
    Chunk,
    IndexedDocument,
    IndexStatus,
    IndexVersion,
    IngestionRun,
    RunStatus,
    Source,
)
from apps.ingestion.pipeline import CHUNKERS, EMBEDDERS, PARSERS, PipelineError


class IngestionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def create_run(*, source: Source, max_attempts: int = 3) -> IngestionRun:
    if not source.is_active:
        raise IngestionError("SOURCE_DISABLED")
    run = IngestionRun(
        organization_id=source.organization_id,
        source=source,
        max_attempts=max_attempts,
    )
    run.full_clean()
    run.save()
    return run


def claim_run(run_id: int) -> IngestionRun | None:
    with transaction.atomic():
        run = IngestionRun.objects.select_for_update().select_related("source").get(pk=run_id)
        if run.status not in {RunStatus.QUEUED, RunStatus.RETRY}:
            return None
        run.status = RunStatus.RUNNING
        run.attempt += 1
        run.started_at = timezone.now()
        run.finished_at = None
        run.error_code = ""
        run.save(
            update_fields=[
                "status",
                "attempt",
                "started_at",
                "finished_at",
                "error_code",
                "updated_at",
            ]
        )
        return run


@contextmanager
def source_lock(source_id: int) -> Iterator[bool]:
    if connection.vendor != "postgresql":
        yield True
        return
    acquired = False
    lock_name = f"agenthub:ingestion-source:{source_id}"
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [lock_name])
        acquired = bool(cursor.fetchone()[0])
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [lock_name])


def _build_index(run: IngestionRun) -> IndexVersion:
    source = run.source
    if not source.is_active:
        raise IngestionError("SOURCE_DISABLED")
    parser = PARSERS.get(source.parser)
    chunker = CHUNKERS.get(source.chunker)
    embedder = EMBEDDERS.get(source.embedder)
    if parser is None or chunker is None or embedder is None:
        raise IngestionError("PIPELINE_UNSUPPORTED")
    raw_documents = get_connector(source.connector_type).fetch(source)
    if not raw_documents:
        raise IngestionError("NO_DOCUMENTS")

    with transaction.atomic():
        latest = (
            IndexVersion.objects.select_for_update()
            .filter(source=source)
            .aggregate(value=Max("version"))["value"]
            or 0
        )
        index = IndexVersion.objects.create(
            organization_id=source.organization_id,
            source=source,
            version=latest + 1,
            status=IndexStatus.BUILDING,
        )
        chunk_count = 0
        for raw in raw_documents:
            parsed = parser(raw)
            document = IndexedDocument.objects.create(
                organization_id=source.organization_id,
                index_version=index,
                source_uri=parsed.uri,
                title=parsed.title,
                checksum=hashlib.sha256(raw.content).hexdigest(),
            )
            chunks = chunker(parsed.text)
            Chunk.objects.bulk_create(
                [
                    Chunk(
                        organization_id=source.organization_id,
                        index_version=index,
                        document=document,
                        ordinal=ordinal,
                        text=text,
                        embedding=embedder(text),
                    )
                    for ordinal, text in enumerate(chunks)
                ]
            )
            chunk_count += len(chunks)
        index.status = IndexStatus.PROMOTABLE
        index.document_count = len(raw_documents)
        index.chunk_count = chunk_count
        index.save(update_fields=["status", "document_count", "chunk_count", "updated_at"])
        return index


def _fail_run(run_id: int, code: str) -> str:
    with transaction.atomic():
        run = IngestionRun.objects.select_for_update().get(pk=run_id)
        terminal = run.attempt >= run.max_attempts
        run.status = RunStatus.DEAD_LETTER if terminal else RunStatus.RETRY
        run.error_code = code
        run.finished_at = timezone.now() if terminal else None
        run.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
        if terminal:
            record_event(
                actor_type="system",
                actor_id="ingestion-worker",
                action="ingestion.dead_letter",
                outcome="failure",
                organization_id=run.organization_id,
                resource_type="ingestion_run",
                resource_id=str(run.pk),
                reason=code,
            )
        else:
            record_event(
                actor_type="system",
                actor_id="ingestion-worker",
                action="ingestion.retry_scheduled",
                outcome="failure",
                organization_id=run.organization_id,
                resource_type="ingestion_run",
                resource_id=str(run.pk),
                reason=code,
            )
        return run.status


def execute_run(run_id: int) -> str:
    run = claim_run(run_id)
    if run is None:
        return "not_claimed"
    try:
        with source_lock(run.source_id) as acquired:
            if not acquired:
                return _fail_run(run.pk, "SOURCE_BUSY")
            index = _build_index(run)
    except (ConnectorError, PipelineError, IngestionError) as exc:
        code = exc.code if isinstance(exc, IngestionError) else str(exc)
        return _fail_run(run.pk, code)
    except Exception:
        return _fail_run(run.pk, "INTERNAL_ERROR")

    with transaction.atomic():
        current = IngestionRun.objects.select_for_update().get(pk=run.pk)
        current.status = RunStatus.SUCCEEDED
        current.index_version = index
        current.finished_at = timezone.now()
        current.save(update_fields=["status", "index_version", "finished_at", "updated_at"])
        record_event(
            actor_type="system",
            actor_id="ingestion-worker",
            action="ingestion.succeeded",
            outcome="success",
            organization_id=current.organization_id,
            resource_type="ingestion_run",
            resource_id=str(current.pk),
            after={"index_version_id": index.pk, "chunks": index.chunk_count},
        )
    return RunStatus.SUCCEEDED
