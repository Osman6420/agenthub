"""Recoverable OCR orchestration with durable-result-before-ACK ordering."""

from __future__ import annotations

import hashlib
import io

from django.db import transaction

from apps.audit.services import record_event
from apps.documents.models import DocumentVersion
from apps.documents.storage import build_object_key, get_object_store
from apps.ingestion.models import (
    DocumentOcrJob,
    OcrJobStatus,
    OcrProfile,
    OcrProfileStatus,
    TenantOcrProfileGrant,
)
from apps.ingestion.ocr import AsyncMarkdownOcrClient, OcrError, OcrOutcomeUnknown
from apps.ingestion.parsers import ParsedContent, parse_document


def parse_image_only_pdf(
    *,
    document_version: DocumentVersion,
    pdf: bytes,
    ocr_profile: OcrProfile,
    actor: str,
    client: AsyncMarkdownOcrClient | None = None,
    request_id: str = "",
) -> ParsedContent:
    if ocr_profile.status != OcrProfileStatus.ACTIVE:
        raise OcrError("OCR_PROFILE_DISABLED")
    if not TenantOcrProfileGrant.objects.filter(
        organization_id=document_version.organization_id, ocr_profile=ocr_profile
    ).exists():
        raise OcrError("OCR_PROFILE_NOT_GRANTED")
    if document_version.mime_type != "application/pdf":
        raise OcrError("OCR_PDF_REQUIRED")
    if len(pdf) > ocr_profile.max_upload_bytes:
        raise OcrError("OCR_UPLOAD_TOO_LARGE")
    page_count = _page_count(pdf)
    if page_count > ocr_profile.max_pages:
        raise OcrError("OCR_PAGE_LIMIT_EXCEEDED")

    ocr_client = client or AsyncMarkdownOcrClient()
    job, created = DocumentOcrJob.objects.get_or_create(
        document_version=document_version,
        ocr_profile=ocr_profile,
        defaults={
            "organization_id": document_version.organization_id,
            "status": OcrJobStatus.SUBMITTING,
        },
    )
    if created:
        try:
            submitted_job_id = ocr_client.submit(ocr_profile, pdf)
        except OcrOutcomeUnknown:
            job.status = OcrJobStatus.OUTCOME_UNKNOWN
            job.error_code = "OCR_SUBMIT_OUTCOME_UNKNOWN"
            job.save(update_fields=["status", "error_code", "updated_at"])
            raise
        job.job_id = submitted_job_id
        job.status = OcrJobStatus.SUBMITTED
        job.save(update_fields=["job_id", "status", "updated_at"])
        record_event(
            actor_type="system",
            actor_id=actor,
            action="ingestion.ocr.submitted",
            outcome="success",
            organization_id=job.organization_id,
            resource_type="document_ocr_job",
            resource_id=str(job.pk),
            request_id=request_id,
        )
    elif job.status in {OcrJobStatus.SUBMITTING, OcrJobStatus.OUTCOME_UNKNOWN}:
        raise OcrOutcomeUnknown("OCR_SUBMIT_OUTCOME_UNKNOWN")
    elif job.status == OcrJobStatus.FAILED:
        raise OcrError(job.error_code or "OCR_JOB_FAILED")

    job_id = job.job_id
    if job_id is None:
        raise OcrOutcomeUnknown("OCR_SUBMIT_OUTCOME_UNKNOWN")
    if not job.result_object_key:
        try:
            ocr_client.wait_for_success(ocr_profile, job_id)
            markdown = ocr_client.download(ocr_profile, job_id)
        except OcrError as exc:
            if exc.code in {
                "OCR_JOB_FAILED",
                "OCR_JOB_ACKNOWLEDGED",
                "OCR_JOB_EXPIRED",
                "OCR_RESULT_GONE",
            }:
                job.status = OcrJobStatus.FAILED
                job.error_code = exc.upstream_code or exc.code
                job.save(update_fields=["status", "error_code", "updated_at"])
                record_event(
                    actor_type="system",
                    actor_id=actor,
                    action="ingestion.ocr.failed",
                    outcome="failure",
                    organization_id=job.organization_id,
                    resource_type="document_ocr_job",
                    resource_id=str(job.pk),
                    reason=job.error_code,
                    request_id=request_id,
                )
            raise
        object_key = build_object_key(
            organization_id=document_version.organization_id,
            document_logical_id=document_version.document.logical_id,
        )
        get_object_store().put(object_key, markdown, content_type="text/markdown; charset=utf-8")
        checksum = hashlib.sha256(markdown).hexdigest()
        with transaction.atomic():
            locked = DocumentOcrJob.objects.select_for_update().get(pk=job.pk)
            locked.result_object_key = object_key
            locked.result_checksum = checksum
            locked.status = OcrJobStatus.RESULT_PERSISTED
            locked.save(
                update_fields=[
                    "result_object_key",
                    "result_checksum",
                    "status",
                    "updated_at",
                ]
            )
            record_event(
                actor_type="system",
                actor_id=actor,
                action="ingestion.ocr.result_persisted",
                outcome="success",
                organization_id=locked.organization_id,
                resource_type="document_ocr_job",
                resource_id=str(locked.pk),
                request_id=request_id,
                after={"byte_size": len(markdown), "checksum": checksum},
            )
        job = locked

    markdown = get_object_store().get(job.result_object_key)
    if hashlib.sha256(markdown).hexdigest() != job.result_checksum:
        raise OcrError("OCR_RESULT_CHECKSUM_MISMATCH")
    if job.status != OcrJobStatus.ACKNOWLEDGED:
        ocr_client.acknowledge(ocr_profile, job_id)
        job.status = OcrJobStatus.ACKNOWLEDGED
        job.save(update_fields=["status", "updated_at"])
        record_event(
            actor_type="system",
            actor_id=actor,
            action="ingestion.ocr.acknowledged",
            outcome="success",
            organization_id=job.organization_id,
            resource_type="document_ocr_job",
            resource_id=str(job.pk),
            request_id=request_id,
        )
    parsed = parse_document("text/markdown", markdown)
    return ParsedContent(
        text=parsed.text,
        parser="external_ocr",
        element_count=parsed.element_count,
        page_count=page_count,
    )


def _page_count(pdf: bytes) -> int:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(pdf)) as document:
            count = len(document.pages)
    except Exception as exc:
        raise OcrError("OCR_PDF_INVALID") from exc
    if count < 1:
        raise OcrError("OCR_PDF_INVALID")
    return count
