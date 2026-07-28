"""Governed document-summary generation with exact, content-free provenance."""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.audit.services import record_event
from apps.documents.models import DocumentVersion, DocumentVersionSummary, SummaryStatus
from apps.ingestion.vector_store import set_tenant_context
from apps.orchestration.providers import ModelProviderError, get_model_provider
from apps.retrieval.types import RetrievedChunk


class SummaryError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _validate_artifact(
    artifact: ArtifactVersion, *, organization_id: int, expected_type: str
) -> None:
    if artifact.organization_id != organization_id or artifact.type != expected_type:
        raise SummaryError("SUMMARY_PROFILE_INVALID")


def generate_document_summary(
    *,
    document_version: DocumentVersion,
    parsed_text: str,
    model_profile: ArtifactVersion,
    prompt_contract: ArtifactVersion,
    actor: str,
    request_id: str = "",
) -> DocumentVersionSummary:
    """Generate or reuse one exact-provenance summary; content never enters audit/log data."""
    organization_id = document_version.organization_id
    _validate_artifact(
        model_profile,
        organization_id=organization_id,
        expected_type=ArtifactType.MODEL_PROFILE,
    )
    _validate_artifact(
        prompt_contract,
        organization_id=organization_id,
        expected_type=ArtifactType.PROMPT_TEMPLATE,
    )
    maximum_input = int(getattr(settings, "DOCUMENT_SUMMARY_MAX_INPUT_CHARS", 200_000))
    maximum_output = int(getattr(settings, "DOCUMENT_SUMMARY_MAX_OUTPUT_CHARS", 8_000))
    if not parsed_text or len(parsed_text) > maximum_input:
        raise SummaryError("SUMMARY_INPUT_LIMIT_EXCEEDED")
    prompt = prompt_contract.body.get("template")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000:
        raise SummaryError("SUMMARY_PROMPT_INVALID")
    input_checksum = hashlib.sha256(parsed_text.encode()).hexdigest()

    with transaction.atomic():
        set_tenant_context(organization_id)
        summary, _ = DocumentVersionSummary.objects.select_for_update().get_or_create(
            organization_id=organization_id,
            document_version=document_version,
            model_profile=model_profile,
            prompt_contract=prompt_contract,
            defaults={"input_checksum": input_checksum},
        )
        if (
            summary.status == SummaryStatus.READY
            and summary.input_checksum == input_checksum
            and summary.content
        ):
            return summary
        summary.status = SummaryStatus.PENDING
        summary.content = ""
        summary.checksum = ""
        summary.error_code = ""
        summary.input_checksum = input_checksum
        summary.full_clean()
        summary.save()

    try:
        response = get_model_provider().generate(
            prompt=prompt,
            context=[
                RetrievedChunk(
                    text=parsed_text,
                    source_id=f"document-version:{document_version.pk}",
                    source_uri=document_version.document.logical_id,
                    title=document_version.document.title,
                )
            ],
            model_profile=model_profile.body,
        )
        content = response.text.strip()
        if not content or len(content) > maximum_output:
            raise SummaryError("SUMMARY_OUTPUT_INVALID")
    except ModelProviderError as exc:
        # Provider error strings are outside the audit trust boundary and may contain endpoint or
        # response detail. Persist and audit only our stable content-free contract code.
        _mark_failed(summary, code="SUMMARY_PROVIDER_FAILED")
        raise SummaryError("SUMMARY_PROVIDER_FAILED") from exc
    except SummaryError:
        _mark_failed(summary, code="SUMMARY_OUTPUT_INVALID")
        raise

    checksum = hashlib.sha256(content.encode()).hexdigest()
    with transaction.atomic():
        set_tenant_context(organization_id)
        locked = DocumentVersionSummary.objects.select_for_update().get(pk=summary.pk)
        locked.status = SummaryStatus.READY
        locked.content = content
        locked.checksum = checksum
        locked.error_code = ""
        locked.save(update_fields=["status", "content", "checksum", "error_code", "updated_at"])
        record_event(
            actor_type="user",
            actor_id=actor,
            action="documents.document_version.summary_generated",
            outcome="success",
            organization_id=organization_id,
            resource_type="document_version_summary",
            resource_id=str(locked.pk),
            reason=checksum,
            request_id=request_id,
            after={
                "document_version_id": document_version.pk,
                "model_profile_ref": model_profile.ref,
                "prompt_contract_ref": prompt_contract.ref,
            },
        )
    return locked


def _mark_failed(summary: DocumentVersionSummary, *, code: str) -> None:
    safe_code = code[:64] if code else "SUMMARY_FAILED"
    with transaction.atomic():
        set_tenant_context(summary.organization_id)
        locked = DocumentVersionSummary.objects.select_for_update().get(pk=summary.pk)
        locked.status = SummaryStatus.FAILED
        locked.content = ""
        locked.checksum = ""
        locked.error_code = safe_code
        locked.save(update_fields=["status", "content", "checksum", "error_code", "updated_at"])
        record_event(
            actor_type="system",
            actor_id="document-summary",
            action="documents.document_version.summary_failed",
            outcome="failure",
            organization_id=summary.organization_id,
            resource_type="document_version_summary",
            resource_id=str(summary.pk),
            reason=safe_code,
        )
