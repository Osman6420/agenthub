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

import hashlib
import json
from collections.abc import Callable

from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from apps.artifacts.governed_dsl import GovernedDSLValidationError, chunk_with_profile
from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.audit.services import record_event
from apps.documents.models import DocumentSetVersion, DocumentSetVersionStatus, DocumentVersion
from apps.documents.summary_services import SummaryError, generate_document_summary
from apps.ingestion.embedding import (
    EmbeddingError,
    EmbeddingOutcomeUnknown,
    get_embedding_provider,
)
from apps.ingestion.generation_lifecycle import GenerationFenced, lock_generation
from apps.ingestion.models import (
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IndexStatus,
    IndexVersion,
    OcrProfile,
    StagedIndexBuildJob,
    TenantEmbeddingProfileGrant,
)
from apps.ingestion.ocr import AsyncMarkdownOcrClient, OcrError, OcrOutcomeUnknown
from apps.ingestion.parsers import ParserError, parse_document
from apps.ingestion.pipeline import CHUNKERS, PipelineError
from apps.ingestion.vector_store import (
    VectorRow,
    VectorStoreError,
    chunk_counts_by_document,
    copy_chunks,
    drop_store,
    new_generation_layout,
    provision_store,
    write_chunks,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.context import set_tenant_context

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
    chunking_profile: ArtifactVersion | None = None,
    retrieval_profile: ArtifactVersion | None = None,
    summary_model_profile: ArtifactVersion | None = None,
    summary_prompt_contract: ArtifactVersion | None = None,
    request_id: str = "",
    ocr_profile: OcrProfile | None = None,
    ocr_client: AsyncMarkdownOcrClient | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    build_job: StagedIndexBuildJob | None = None,
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
    # Deny-by-default: the tenant must be granted this platform profile. The short transaction is
    # intentional; provider and object-store I/O below must not inherit a build-long transaction.
    with transaction.atomic():
        set_tenant_context(organization_id)
        if not TenantEmbeddingProfileGrant.objects.filter(
            organization_id=organization_id, embedding_profile=embedding_profile
        ).exists():
            raise StagedBuildError("EMBEDDING_PROFILE_NOT_GRANTED")
    _validate_artifact_profile(
        chunking_profile,
        organization_id=organization_id,
        expected_type=ArtifactType.CHUNKING_PROFILE,
        required=False,
    )
    _validate_artifact_profile(
        retrieval_profile,
        organization_id=organization_id,
        expected_type=ArtifactType.RETRIEVAL_PROFILE,
        required=False,
    )
    _validate_artifact_profile(
        summary_model_profile,
        organization_id=organization_id,
        expected_type=ArtifactType.MODEL_PROFILE,
        required=False,
    )
    _validate_artifact_profile(
        summary_prompt_contract,
        organization_id=organization_id,
        expected_type=ArtifactType.PROMPT_TEMPLATE,
        required=False,
    )
    if bool(summary_model_profile) != bool(summary_prompt_contract):
        raise StagedBuildError("SUMMARY_CONFIGURATION_INCOMPLETE")
    chunk_fn = CHUNKERS.get(chunker) if chunking_profile is None else None
    if chunking_profile is None and chunk_fn is None:
        raise StagedBuildError("CHUNKER_UNSUPPORTED")

    fingerprint = pipeline_fingerprint(
        embedding_profile=embedding_profile,
        chunker=chunker,
        ocr_profile=ocr_profile,
        chunking_profile=chunking_profile,
        retrieval_profile=retrieval_profile,
        summary_model_profile=summary_model_profile,
        summary_prompt_contract=summary_prompt_contract,
    )
    parent = _compatible_parent(
        document_set_version=document_set_version,
        pipeline_fingerprint=fingerprint,
    )
    index_version = _create_index_version(
        document_set_version,
        embedding_profile,
        pipeline_fingerprint=fingerprint,
        parent=parent,
        build_job=build_job,
        chunking_profile=chunking_profile,
        retrieval_profile=retrieval_profile,
        summary_model_profile=summary_model_profile,
        summary_prompt_contract=summary_prompt_contract,
    )
    try:
        provision_store(index_version)
        document_versions = _load_document_versions(document_set_version)
        member_ids = [version.pk for version in document_versions]
        reused_counts = chunk_counts_by_document(parent, member_ids) if parent is not None else {}
        reusable_ids = sorted(reused_counts)
        reused_chunks = (
            copy_chunks(parent, index_version, reusable_ids) if parent is not None else 0
        )
        if reused_chunks != sum(reused_counts.values()):
            raise StagedBuildError("VECTOR_REUSE_COUNT_MISMATCH")
        embedded_documents, embedded_chunks = _embed_into_store(
            index_version,
            document_set_version,
            embedding_profile,
            chunk_fn,
            document_versions=document_versions,
            chunking_profile=chunking_profile,
            summary_model_profile=summary_model_profile,
            summary_prompt_contract=summary_prompt_contract,
            actor=actor,
            request_id=request_id,
            ocr_profile=ocr_profile,
            ocr_client=ocr_client,
            only_document_version_ids=set(member_ids) - set(reusable_ids),
            progress_callback=progress_callback,
            initial_document_count=len(reusable_ids),
            initial_chunk_count=reused_chunks,
        )
        document_count = len(reusable_ids) + embedded_documents
        chunk_count = reused_chunks + embedded_chunks
        if document_count != len(member_ids):
            raise StagedBuildError("BUILD_DOCUMENT_COUNT_MISMATCH")
    except (EmbeddingOutcomeUnknown, OcrOutcomeUnknown):
        _fail(index_version, reason="provider_outcome_unknown")
        raise
    except StagedBuildError:
        _fail(index_version, reason="build_failed")
        raise
    except (VectorStoreError, EmbeddingError, OcrError, SummaryError) as exc:
        _fail(index_version, reason=exc.code)
        raise StagedBuildError(exc.code) from exc
    except PipelineError as exc:
        _fail(index_version, reason="PIPELINE_FAILED")
        raise StagedBuildError("PIPELINE_FAILED") from exc
    except GovernedDSLValidationError as exc:
        _fail(index_version, reason="GOVERNED_DSL_INVALID")
        raise StagedBuildError("GOVERNED_DSL_INVALID") from exc
    except Exception:
        _fail(index_version, reason="internal_error")
        raise

    with transaction.atomic():
        set_tenant_context(organization_id)
        try:
            locked = lock_generation(index_version)
        except GenerationFenced as exc:
            raise StagedBuildError(exc.code) from exc
        if locked.status != IndexStatus.BUILDING or (
            locked.storage_layout == "shared_v1" and locked.storage_state != "open"
        ):
            raise StagedBuildError("BUILD_GENERATION_FENCED")
        locked.status = IndexStatus.PROMOTABLE
        if locked.storage_layout == "shared_v1":
            locked.storage_state = "sealed"
        locked.store_ready = True
        locked.document_count = document_count
        locked.chunk_count = chunk_count
        locked.embedded_document_count = embedded_documents
        locked.embedded_chunk_count = embedded_chunks
        locked.reused_document_count = len(reusable_ids)
        locked.reused_chunk_count = reused_chunks
        locked.save(
            update_fields=[
                "status",
                "storage_state",
                "store_ready",
                "document_count",
                "chunk_count",
                "embedded_document_count",
                "embedded_chunk_count",
                "reused_document_count",
                "reused_chunk_count",
                "updated_at",
            ]
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
                "chunking_profile_ref": (
                    chunking_profile.ref if chunking_profile else "legacy-fixed"
                ),
                "retrieval_profile_ref": retrieval_profile.ref if retrieval_profile else None,
                "summary_enabled": summary_model_profile is not None,
                "documents": document_count,
                "chunks": chunk_count,
                "embedded_documents": embedded_documents,
                "embedded_chunks": embedded_chunks,
                "reused_documents": len(reusable_ids),
                "reused_chunks": reused_chunks,
            },
        )
    return locked


def _create_index_version(
    document_set_version: DocumentSetVersion,
    embedding_profile: EmbeddingProfile,
    *,
    pipeline_fingerprint: str,
    parent: IndexVersion | None,
    build_job: StagedIndexBuildJob | None,
    chunking_profile: ArtifactVersion | None,
    retrieval_profile: ArtifactVersion | None,
    summary_model_profile: ArtifactVersion | None,
    summary_prompt_contract: ArtifactVersion | None,
) -> IndexVersion:
    with transaction.atomic():
        set_tenant_context(document_set_version.organization_id)
        if build_job is not None:
            current_job = StagedIndexBuildJob.objects.select_for_update().get(
                pk=build_job.pk,
                organization_id=document_set_version.organization_id,
            )
            if (
                current_job.status != "running"
                or current_job.attempt != build_job.attempt
                or current_job.document_set_version_id != document_set_version.pk
                or current_job.embedding_profile_id != embedding_profile.pk
                or current_job.pipeline_fingerprint != pipeline_fingerprint
            ):
                raise StagedBuildError("BUILD_GENERATION_FENCED")
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
            chunking_profile=chunking_profile,
            retrieval_profile=retrieval_profile,
            summary_model_profile=summary_model_profile,
            summary_prompt_contract=summary_prompt_contract,
            dimensions=embedding_profile.dimensions,
            index_type=embedding_profile.index_type,
            version=latest + 1,
            status=IndexStatus.BUILDING,
            storage_layout=new_generation_layout(),
            build_request=build_job,
            build_attempt=build_job.attempt if build_job else None,
            pipeline_fingerprint=pipeline_fingerprint,
            parent_index_version=parent,
        )


def pipeline_fingerprint(
    *,
    embedding_profile: EmbeddingProfile,
    chunker: str,
    ocr_profile: OcrProfile | None,
    chunking_profile: ArtifactVersion | None = None,
    retrieval_profile: ArtifactVersion | None = None,
    summary_model_profile: ArtifactVersion | None = None,
    summary_prompt_contract: ArtifactVersion | None = None,
) -> str:
    payload = {
        "schema": 2,
        "embedding_profile": str(embedding_profile.public_id),
        "embedding_revision": embedding_profile.revision,
        "dimensions": embedding_profile.dimensions,
        "index_type": embedding_profile.index_type,
        "normalize": embedding_profile.normalize,
        "distance_metric": embedding_profile.distance_metric,
        "parser_pipeline": "allowlisted-parsers-v2",
        "chunker": chunking_profile.ref if chunking_profile else chunker,
        "chunker_checksum": chunking_profile.checksum if chunking_profile else None,
        "chunker_config": chunking_profile.body
        if chunking_profile
        else {"size": 1000, "overlap": 100},
        "retrieval_profile": retrieval_profile.ref if retrieval_profile else None,
        "retrieval_checksum": retrieval_profile.checksum if retrieval_profile else None,
        "summary_model_profile": summary_model_profile.ref if summary_model_profile else None,
        "summary_model_checksum": summary_model_profile.checksum if summary_model_profile else None,
        "summary_prompt_contract": summary_prompt_contract.ref if summary_prompt_contract else None,
        "summary_prompt_checksum": summary_prompt_contract.checksum
        if summary_prompt_contract
        else None,
        "ocr_profile": str(ocr_profile.public_id) if ocr_profile else None,
        "ocr_revision": ocr_profile.revision if ocr_profile else None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _compatible_parent(
    *, document_set_version: DocumentSetVersion, pipeline_fingerprint: str
) -> IndexVersion | None:
    with transaction.atomic():
        set_tenant_context(document_set_version.organization_id)
        return (
            IndexVersion.objects.select_related("document_set_version")
            .filter(
                organization_id=document_set_version.organization_id,
                document_set_version__document_set_id=document_set_version.document_set_id,
                pipeline_fingerprint=pipeline_fingerprint,
                store_ready=True,
                status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE, IndexStatus.SUPERSEDED],
            )
            .order_by("-created_at", "-id")
            .first()
        )


def _load_document_versions(document_set_version: DocumentSetVersion) -> list[DocumentVersion]:
    """Materialize exact immutable members under RLS before any external I/O begins."""

    with transaction.atomic():
        set_tenant_context(document_set_version.organization_id)
        document_version_ids = list(
            document_set_version.memberships.order_by("ordinal", "id").values_list(
                "document_version_id", flat=True
            )[: _MAX_DOCUMENTS + 1]
        )
        if len(document_version_ids) > _MAX_DOCUMENTS:
            raise StagedBuildError("BUILD_TOO_LARGE")
        versions_by_id = {
            version.pk: version
            for version in DocumentVersion.objects.select_related("document").filter(
                pk__in=document_version_ids,
                organization_id=document_set_version.organization_id,
            )
        }
        if len(versions_by_id) != len(document_version_ids):
            raise StagedBuildError("DOCUMENT_VERSION_LINEAGE_INVALID")
    return [versions_by_id[version_id] for version_id in document_version_ids]


def _embed_into_store(
    index_version: IndexVersion,
    document_set_version: DocumentSetVersion,
    embedding_profile: EmbeddingProfile,
    chunk_fn: object,
    *,
    document_versions: list[DocumentVersion],
    chunking_profile: ArtifactVersion | None,
    summary_model_profile: ArtifactVersion | None,
    summary_prompt_contract: ArtifactVersion | None,
    actor: str,
    request_id: str,
    ocr_profile: OcrProfile | None,
    ocr_client: AsyncMarkdownOcrClient | None,
    only_document_version_ids: set[int] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    initial_document_count: int = 0,
    initial_chunk_count: int = 0,
) -> tuple[int, int]:
    from apps.documents.storage import get_object_store

    provider = get_embedding_provider()
    store = get_object_store()
    profile_id = str(embedding_profile.public_id)
    organization_id = document_set_version.organization_id
    batch_size = max(1, int(embedding_profile.max_batch_size))

    document_count = 0
    chunk_count = 0
    for version in document_versions:
        if only_document_version_ids is not None and version.pk not in only_document_version_ids:
            continue
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
        with transaction.atomic():
            set_tenant_context(organization_id)
            updated = DocumentVersion.objects.filter(
                pk=version.pk, organization_id=organization_id
            ).update(
                parser=parsed.parser,
                parse_status="parsed",
                element_count=parsed.element_count,
                page_count=parsed.page_count,
                updated_at=timezone.now(),
            )
            if updated != 1:
                raise StagedBuildError("DOCUMENT_VERSION_NOT_FOUND")
        version.parser = parsed.parser
        version.parse_status = "parsed"
        version.element_count = parsed.element_count
        version.page_count = parsed.page_count
        if chunking_profile is None:
            chunks = [("content", text) for text in chunk_fn(parsed.text)]  # type: ignore[operator]
        else:
            chunks = [
                ("content", text)
                for text in _chunk_with_compatibility(
                    parsed.text,
                    mime_type=version.mime_type,
                    profile=chunking_profile,
                )
            ]
        if summary_model_profile is not None and summary_prompt_contract is not None:
            try:
                summary = generate_document_summary(
                    document_version=version,
                    parsed_text=parsed.text,
                    model_profile=summary_model_profile,
                    prompt_contract=summary_prompt_contract,
                    actor=actor,
                    request_id=request_id,
                )
            except SummaryError as exc:
                raise StagedBuildError(exc.code) from exc
            chunks.append(("summary", summary.content))
        rows: list[VectorRow] = []
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            try:
                result = provider.embed([text for _, text in batch], profile_id=profile_id)
            except EmbeddingOutcomeUnknown:
                # Post-send unknown: never re-send; fail the build for controlled re-drive.
                raise
            if result.dimensions and result.dimensions != embedding_profile.dimensions:
                raise StagedBuildError("EMBEDDING_DIMENSION_MISMATCH")
            for offset, ((chunk_kind, chunk_text), vector) in enumerate(
                zip(batch, result.vectors, strict=True)
            ):
                rows.append(
                    VectorRow(
                        organization_id=organization_id,
                        document_version_id=version.pk,
                        ordinal=start + offset,
                        text=chunk_text,
                        embedding=vector,
                        chunk_kind=chunk_kind,
                    )
                )
        chunk_count += write_chunks(index_version, rows)
        document_count += 1
        if document_count > _MAX_DOCUMENTS or chunk_count > _MAX_CHUNKS:
            raise StagedBuildError("BUILD_TOO_LARGE")
        if progress_callback is not None:
            progress_callback(
                initial_document_count + document_count,
                initial_chunk_count + chunk_count,
            )
    return document_count, chunk_count


def _validate_artifact_profile(
    artifact: ArtifactVersion | None,
    *,
    organization_id: int,
    expected_type: str,
    required: bool,
) -> None:
    if artifact is None:
        if required:
            raise StagedBuildError("PROFILE_REQUIRED")
        return
    if artifact.organization_id != organization_id or artifact.type != expected_type:
        raise StagedBuildError("PROFILE_INVALID")


def _chunk_with_compatibility(text: str, *, mime_type: str, profile: ArtifactVersion) -> list[str]:
    strategy = str(profile.body.get("strategy", ""))
    supported = {
        "pages": {"application/pdf"},
        "tables": {
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
        "headings": {
            "text/markdown",
            "text/html",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    }
    if strategy in supported and mime_type not in supported[strategy]:
        raise StagedBuildError("CHUNKING_STRATEGY_INCOMPATIBLE")
    return chunk_with_profile(text, profile.body)


def _fail(index_version: IndexVersion, *, reason: str) -> None:
    # Drop the partial store and mark the version failed; never leave a half-written store ready.
    try:
        drop_store(index_version)
    except VectorStoreError:
        pass
    with transaction.atomic():
        set_tenant_context(index_version.organization_id)
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


def active_releases_pinning_document_set_version(
    *, organization_id: int, document_set_version_id: int
) -> list[ScenarioRelease]:
    """Active ``ScenarioRelease``s whose compiled manifest still pins this exact set version.

    Used to warn an operator, before a routine "update the document" promote silently
    supersedes it (BUG-010), which already-serving scenarios would go ungrounded.
    """
    return [
        release
        for release in ScenarioRelease.objects.filter(
            organization_id=organization_id, status=ReleaseStatus.ACTIVE
        ).select_related("scenario")
        if document_set_version_id in (release.manifest.get("document_set_versions") or [])
    ]


def promote_staged_index(
    index_version: IndexVersion,
    *,
    actor: str,
    request_id: str = "",
    confirm_active_release_impact: bool = False,
) -> IndexVersion:
    """Atomically make this exact set-version/index pair the retrieval serving pointer.

    Raises ``StagedBuildError("ACTIVE_RELEASES_AFFECTED")`` instead of superseding an older
    served version when an already-active ``ScenarioRelease`` still pins it, unless the caller
    passes ``confirm_active_release_impact=True`` (BUG-010) -- the console view resurfaces this
    as an explicit confirmation step rather than silently ungrounding a live scenario.
    """
    return _serve_index(
        index_version,
        actor=actor,
        request_id=request_id,
        action="ingestion.staged_index.promoted",
        allowed_index_statuses={IndexStatus.PROMOTABLE, IndexStatus.ACTIVE},
        allowed_set_statuses={
            DocumentSetVersionStatus.PROMOTABLE,
            DocumentSetVersionStatus.ACTIVE,
        },
        invalid_code="INDEX_NOT_PROMOTABLE",
        require_active_release_confirmation=True,
        confirm_active_release_impact=confirm_active_release_impact,
    )


def rollback_staged_index(
    index_version: IndexVersion, *, actor: str, request_id: str = ""
) -> IndexVersion:
    """Atomically restore a superseded set-version/index pair as the serving pointer."""
    return _serve_index(
        index_version,
        actor=actor,
        request_id=request_id,
        action="ingestion.staged_index.rolled_back",
        allowed_index_statuses={IndexStatus.SUPERSEDED, IndexStatus.ACTIVE},
        allowed_set_statuses={
            DocumentSetVersionStatus.SUPERSEDED,
            DocumentSetVersionStatus.ACTIVE,
        },
        invalid_code="INDEX_NOT_ROLLBACKABLE",
    )


def _serve_index(
    index_version: IndexVersion,
    *,
    actor: str,
    request_id: str,
    action: str,
    allowed_index_statuses: set[str],
    allowed_set_statuses: set[str],
    invalid_code: str,
    require_active_release_confirmation: bool = False,
    confirm_active_release_impact: bool = False,
) -> IndexVersion:
    """Own every metadata field consulted by retrieval in one locked transaction."""
    try:
        with transaction.atomic():
            # Resolve immutable lineage first, then take the document-set mutex before any
            # candidate row. Competing promotions for different versions of the same set thereby
            # acquire locks in one order instead of deadlocking candidate-index -> set.
            locked = IndexVersion.objects.get(pk=index_version.pk)
            if locked.document_set_version_id is None:
                raise StagedBuildError("INDEX_NOT_DOCSET_SCOPED")
            set_version = DocumentSetVersion.objects.select_related("document_set").get(
                pk=locked.document_set_version_id
            )
            document_set = set_version.document_set
            if (
                locked.organization_id != set_version.organization_id
                or set_version.organization_id != document_set.organization_id
            ):
                raise StagedBuildError("INDEX_SET_LINEAGE_INVALID")

            # Serialize all served-pointer changes for one set and hold every affected row.
            type(document_set).objects.select_for_update().get(pk=document_set.pk)
            from apps.ingestion.source_revisions import assert_serving_revision

            assert_serving_revision(set_version)
            versions = list(
                DocumentSetVersion.objects.select_for_update()
                .filter(document_set_id=document_set.pk)
                .order_by("pk")
            )
            version_ids = [version.pk for version in versions]
            indexes = list(
                IndexVersion.objects.select_for_update()
                .filter(document_set_version_id__in=version_ids)
                .order_by("pk")
            )
            locked = next(item for item in indexes if item.pk == locked.pk)
            set_version = next(item for item in versions if item.pk == set_version.pk)

            other_active_versions = [
                item.pk
                for item in versions
                if item.pk != set_version.pk and item.status == DocumentSetVersionStatus.ACTIVE
            ]
            other_active_indexes = [
                item.pk
                for item in indexes
                if item.pk != locked.pk and item.status == IndexStatus.ACTIVE
            ]
            coherent_replay = (
                set_version.status == DocumentSetVersionStatus.ACTIVE
                and set_version.built_index_version_id == locked.pk
                and locked.status == IndexStatus.ACTIVE
                and not other_active_versions
                and not other_active_indexes
            )
            if coherent_replay:
                record_event(
                    actor_type="user",
                    actor_id=actor,
                    action=action,
                    outcome="success",
                    organization_id=locked.organization_id,
                    resource_type="index_version",
                    resource_id=str(locked.pk),
                    reason="ALREADY_SERVED",
                    request_id=request_id,
                    after={"document_set_version_id": set_version.pk},
                )
                return locked

            if not locked.store_ready or locked.status not in allowed_index_statuses:
                raise StagedBuildError(invalid_code)
            if locked.storage_layout == "shared_v1" and locked.storage_state != "sealed":
                raise StagedBuildError("INDEX_NOT_SEALED")
            if locked.build_request_id and (
                locked.build_attempt is None
                or not StagedIndexBuildJob.objects.filter(
                    pk=locked.build_request_id,
                    organization_id=locked.organization_id,
                    attempt=locked.build_attempt,
                    status="succeeded",
                    result_index_version_id=locked.pk,
                ).exists()
            ):
                raise StagedBuildError("INDEX_BUILD_NOT_COMMITTED")
            if set_version.status not in allowed_set_statuses:
                raise StagedBuildError("SET_VERSION_NOT_PROMOTABLE")
            if (
                require_active_release_confirmation
                and not confirm_active_release_impact
                and other_active_versions
                and any(
                    active_releases_pinning_document_set_version(
                        organization_id=locked.organization_id,
                        document_set_version_id=version_id,
                    )
                    for version_id in other_active_versions
                )
            ):
                raise StagedBuildError("ACTIVE_RELEASES_AFFECTED")
            if other_active_indexes:
                IndexVersion.objects.filter(pk__in=other_active_indexes).update(
                    status=IndexStatus.SUPERSEDED
                )
            if other_active_versions:
                DocumentSetVersion.objects.filter(pk__in=other_active_versions).update(
                    status=DocumentSetVersionStatus.SUPERSEDED
                )
            locked.status = IndexStatus.ACTIVE
            locked.save(update_fields=["status", "updated_at"])
            set_version.status = DocumentSetVersionStatus.ACTIVE
            set_version.built_index_version_id = locked.pk
            set_version.save(update_fields=["status", "built_index_version", "updated_at"])
            record_event(
                actor_type="user",
                actor_id=actor,
                action=action,
                outcome="success",
                organization_id=locked.organization_id,
                resource_type="index_version",
                resource_id=str(locked.pk),
                reason="SERVED_POINTER_CHANGED",
                request_id=request_id,
                before={
                    "active_document_set_version_ids": other_active_versions,
                    "active_index_version_ids": other_active_indexes,
                },
                after={"document_set_version_id": set_version.pk},
            )
            return locked
    except StagedBuildError as exc:
        record_event(
            actor_type="user",
            actor_id=actor,
            action=action,
            outcome="failure",
            organization_id=index_version.organization_id,
            resource_type="index_version",
            resource_id=str(index_version.pk),
            reason=exc.code,
            request_id=request_id,
        )
        raise


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
