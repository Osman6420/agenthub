"""Staged, blue/green real-embedding index build over a managed document-set version (P3.2).

Builds a **staged** ``IndexVersion`` (its own immutable per-version vector store) from the exact
``DocumentVersion``s pinned into a published ``DocumentSetVersion``, using a tenant-granted
``EmbeddingProfile``. The result is left ``promotable`` — it is **not served to consumers**: the
serving guardrail holds real corpora back until P4 wires deny-by-default binding + RLS and the
pointer-flip promotion. Text extraction runs through the deny-by-default ``apps.ingestion.parsers``
seam (P7.1: text/markdown/csv/json/html via stdlib parsers); richer binary formats (pdf/docx/xlsx
via opt-in adapters, external OCR) plug into that same seam under their P7.2+ dependency/egress
approval.

The embedder is the deterministic default unless ``RUNTIME_EMBEDDING_PROVIDER`` selects the real
opt-in client; either way the vector dimension must equal the profile's declared dimension (no
silent truncation, ADR-0003). A post-send embedding failure surfaces as ``OUTCOME_UNKNOWN`` and the
build fails closed for controlled re-drive — the partial store is dropped, never a silent re-send.
"""

from __future__ import annotations

from django.db import connection, transaction
from django.db.models import Max

from apps.audit.services import record_event
from apps.documents.models import DocumentSetVersion, DocumentSetVersionStatus
from apps.ingestion.embedding import (
    EmbeddingError,
    EmbeddingOutcomeUnknown,
    get_embedding_provider,
)
from apps.ingestion.models import (
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IndexStatus,
    IndexVersion,
    OcrProfile,
    TenantEmbeddingProfileGrant,
)
from apps.ingestion.ocr import AsyncMarkdownOcrClient, OcrError
from apps.ingestion.parsers import ParserError, parse_document
from apps.ingestion.pipeline import CHUNKERS, PipelineError
from apps.ingestion.vector_store import (
    VectorRow,
    VectorStoreError,
    drop_store,
    provision_store,
    write_chunks,
)

# Bounds so one build cannot exhaust resources.
_MAX_DOCUMENTS = 5_000
_MAX_CHUNKS = 200_000


class StagedBuildError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_staged_index(
    *,
    document_set_version: DocumentSetVersion,
    embedding_profile: EmbeddingProfile,
    actor: str,
    chunker: str = "fixed",
    request_id: str = "",
    ocr_profile: OcrProfile | None = None,
    ocr_client: AsyncMarkdownOcrClient | None = None,
) -> IndexVersion:
    if connection.vendor != "postgresql":
        # The per-IndexVersion store is a pgvector-only path (ADR-0003).
        raise StagedBuildError("VECTOR_STORE_REQUIRES_POSTGRES")

    organization_id = document_set_version.organization_id
    if document_set_version.status not in (
        DocumentSetVersionStatus.PROMOTABLE,
        DocumentSetVersionStatus.ACTIVE,
    ):
        raise StagedBuildError("SET_VERSION_NOT_PUBLISHED")
    if embedding_profile.status != EmbeddingProfileStatus.ACTIVE:
        raise StagedBuildError("EMBEDDING_PROFILE_DISABLED")
    # Deny-by-default: the tenant must be granted this platform profile.
    if not TenantEmbeddingProfileGrant.objects.filter(
        organization_id=organization_id, embedding_profile=embedding_profile
    ).exists():
        raise StagedBuildError("EMBEDDING_PROFILE_NOT_GRANTED")
    chunk_fn = CHUNKERS.get(chunker)
    if chunk_fn is None:
        raise StagedBuildError("CHUNKER_UNSUPPORTED")

    index_version = _create_index_version(document_set_version, embedding_profile)
    try:
        provision_store(index_version)
        document_count, chunk_count = _embed_into_store(
            index_version,
            document_set_version,
            embedding_profile,
            chunk_fn,
            actor=actor,
            request_id=request_id,
            ocr_profile=ocr_profile,
            ocr_client=ocr_client,
        )
    except (StagedBuildError, VectorStoreError, EmbeddingError, PipelineError, OcrError):
        _fail(index_version, reason="build_failed")
        raise
    except Exception:
        _fail(index_version, reason="internal_error")
        raise

    with transaction.atomic():
        locked = IndexVersion.objects.select_for_update().get(pk=index_version.pk)
        locked.status = IndexStatus.PROMOTABLE
        locked.store_ready = True
        locked.document_count = document_count
        locked.chunk_count = chunk_count
        locked.save(
            update_fields=["status", "store_ready", "document_count", "chunk_count", "updated_at"]
        )
        record_event(
            actor_type="user",
            actor_id=actor,
            action="ingestion.staged_index.built",
            outcome="success",
            organization_id=organization_id,
            resource_type="index_version",
            resource_id=str(locked.pk),
            request_id=request_id,
            after={
                "document_set_version_id": document_set_version.pk,
                "embedding_profile_id": str(embedding_profile.public_id),
                "documents": document_count,
                "chunks": chunk_count,
            },
        )
    index_version.refresh_from_db()
    return index_version


def _create_index_version(
    document_set_version: DocumentSetVersion, embedding_profile: EmbeddingProfile
) -> IndexVersion:
    with transaction.atomic():
        latest = (
            IndexVersion.objects.select_for_update()
            .filter(document_set_version=document_set_version, embedding_profile=embedding_profile)
            .aggregate(value=Max("version"))["value"]
            or 0
        )
        return IndexVersion.objects.create(
            organization_id=document_set_version.organization_id,
            document_set_version=document_set_version,
            embedding_profile=embedding_profile,
            dimensions=embedding_profile.dimensions,
            index_type=embedding_profile.index_type,
            version=latest + 1,
            status=IndexStatus.BUILDING,
        )


def _embed_into_store(
    index_version: IndexVersion,
    document_set_version: DocumentSetVersion,
    embedding_profile: EmbeddingProfile,
    chunk_fn: object,
    *,
    actor: str,
    request_id: str,
    ocr_profile: OcrProfile | None,
    ocr_client: AsyncMarkdownOcrClient | None,
) -> tuple[int, int]:
    from apps.documents.storage import get_object_store

    provider = get_embedding_provider()
    store = get_object_store()
    profile_id = str(embedding_profile.public_id)
    organization_id = document_set_version.organization_id
    batch_size = max(1, int(embedding_profile.max_batch_size))

    document_count = 0
    chunk_count = 0
    for membership in document_set_version.memberships.select_related("document_version").order_by(
        "ordinal", "id"
    ):
        version = membership.document_version
        # Deny-by-default parse: only an allowlisted MIME parser runs; the document is untrusted
        # data. Unsupported MIME (e.g. pdf/docx/xlsx before their P7.2 adapter) fails closed.
        blob = store.get(version.object_key)
        try:
            parsed = parse_document(version.mime_type, blob)
        except ParserError as exc:
            if (
                exc.code in {"EMPTY_DOCUMENT", "PDF_OCR_REQUIRED"}
                and version.mime_type == "application/pdf"
                and ocr_profile is not None
            ):
                from apps.ingestion.ocr_pipeline import parse_image_only_pdf

                parsed = parse_image_only_pdf(
                    document_version=version,
                    pdf=blob,
                    ocr_profile=ocr_profile,
                    actor=actor,
                    client=ocr_client,
                    request_id=request_id,
                )
            elif exc.code == "PARSER_UNSUPPORTED":
                raise StagedBuildError("UNSUPPORTED_MIME_FOR_EMBEDDING") from exc
            else:
                raise StagedBuildError("DOCUMENT_PARSE_FAILED") from exc
        chunks = chunk_fn(parsed.text)  # type: ignore[operator]
        rows: list[VectorRow] = []
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            try:
                result = provider.embed(batch, profile_id=profile_id)
            except EmbeddingOutcomeUnknown:
                # Post-send unknown: never re-send; fail the build for controlled re-drive.
                raise
            if result.dimensions and result.dimensions != embedding_profile.dimensions:
                raise StagedBuildError("EMBEDDING_DIMENSION_MISMATCH")
            for offset, (chunk_text, vector) in enumerate(zip(batch, result.vectors, strict=True)):
                rows.append(
                    VectorRow(
                        organization_id=organization_id,
                        document_version_id=version.pk,
                        ordinal=start + offset,
                        text=chunk_text,
                        embedding=vector,
                    )
                )
        chunk_count += write_chunks(index_version, rows)
        document_count += 1
        if document_count > _MAX_DOCUMENTS or chunk_count > _MAX_CHUNKS:
            raise StagedBuildError("BUILD_TOO_LARGE")
    return document_count, chunk_count


def _fail(index_version: IndexVersion, *, reason: str) -> None:
    # Drop the partial store and mark the version failed; never leave a half-written store ready.
    try:
        drop_store(index_version)
    except VectorStoreError:
        pass
    with transaction.atomic():
        locked = IndexVersion.objects.select_for_update().get(pk=index_version.pk)
        locked.status = IndexStatus.FAILED
        locked.store_ready = False
        locked.save(update_fields=["status", "store_ready", "updated_at"])
        record_event(
            actor_type="system",
            actor_id="ingestion-worker",
            action="ingestion.staged_index.failed",
            outcome="failure",
            organization_id=locked.organization_id,
            resource_type="index_version",
            resource_id=str(locked.pk),
            reason=reason,
        )


@transaction.atomic
def promote_staged_index(
    index_version: IndexVersion, *, actor: str, request_id: str = ""
) -> IndexVersion:
    """Pointer-flip a promotable staged index to ``active`` for its document-set version (ADR-0003).

    Metadata-only and atomic: it moves the previously-active index version for the same document-set
    version to ``superseded`` and this one to ``active`` in one transaction — **no rename, copy, or
    index rebuild**. At most one active index version per document-set version (the retrieval
    pointer). The superseded store is left intact for instant rollback.
    """
    locked = IndexVersion.objects.select_for_update().get(pk=index_version.pk)
    if not locked.store_ready or locked.status != IndexStatus.PROMOTABLE:
        raise StagedBuildError("INDEX_NOT_PROMOTABLE")
    if locked.document_set_version_id is None:
        raise StagedBuildError("INDEX_NOT_DOCSET_SCOPED")
    superseded = list(
        IndexVersion.objects.select_for_update()
        .filter(document_set_version_id=locked.document_set_version_id, status=IndexStatus.ACTIVE)
        .exclude(pk=locked.pk)
        .values_list("id", flat=True)
    )
    IndexVersion.objects.filter(id__in=superseded).update(status=IndexStatus.SUPERSEDED)
    locked.status = IndexStatus.ACTIVE
    locked.save(update_fields=["status", "updated_at"])
    record_event(
        actor_type="user",
        actor_id=actor,
        action="ingestion.staged_index.promoted",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="index_version",
        resource_id=str(locked.pk),
        request_id=request_id,
        after={"document_set_version_id": locked.document_set_version_id, "superseded": superseded},
    )
    return locked


@transaction.atomic
def rollback_staged_index(
    index_version: IndexVersion, *, actor: str, request_id: str = ""
) -> IndexVersion:
    """Restore a superseded index version as the active one (the inverse pointer flip)."""
    locked = IndexVersion.objects.select_for_update().get(pk=index_version.pk)
    if locked.status != IndexStatus.SUPERSEDED:
        raise StagedBuildError("INDEX_NOT_ROLLBACKABLE")
    if locked.document_set_version_id is None:
        raise StagedBuildError("INDEX_NOT_DOCSET_SCOPED")
    demoted = list(
        IndexVersion.objects.select_for_update()
        .filter(document_set_version_id=locked.document_set_version_id, status=IndexStatus.ACTIVE)
        .exclude(pk=locked.pk)
        .values_list("id", flat=True)
    )
    IndexVersion.objects.filter(id__in=demoted).update(status=IndexStatus.SUPERSEDED)
    locked.status = IndexStatus.ACTIVE
    locked.save(update_fields=["status", "updated_at"])
    record_event(
        actor_type="user",
        actor_id=actor,
        action="ingestion.staged_index.rolled_back",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="index_version",
        resource_id=str(locked.pk),
        request_id=request_id,
        after={"document_set_version_id": locked.document_set_version_id, "demoted": demoted},
    )
    return locked


def retire_staged_index(index_version: IndexVersion, *, actor: str, request_id: str = "") -> None:
    """Drop a staged/superseded store's physical relation (retention/purge), audited.

    Refuses an active index: an active store is only retired after a P4 pointer-flip supersedes it.
    """
    if index_version.status == IndexStatus.ACTIVE:
        raise StagedBuildError("INDEX_ACTIVE")
    drop_store(index_version)
    with transaction.atomic():
        locked = IndexVersion.objects.select_for_update().get(pk=index_version.pk)
        locked.store_ready = False
        locked.save(update_fields=["store_ready", "updated_at"])
        record_event(
            actor_type="user",
            actor_id=actor,
            action="ingestion.staged_index.retired",
            outcome="success",
            organization_id=locked.organization_id,
            resource_type="index_version",
            resource_id=str(locked.pk),
            request_id=request_id,
        )
