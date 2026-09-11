"""Exact document-set preparation policy and publish-triggered staged automation."""

from __future__ import annotations

from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.audit.services import record_event
from apps.documents.models import DocumentSet, DocumentSetVersion
from apps.ingestion.job_lifecycle import ACTIVE_STATES, create_build_job
from apps.ingestion.models import (
    DocumentSetPreparationProfile,
    EmbeddingProfile,
    OcrProfile,
    StagedIndexBuildJob,
)
from apps.ingestion.vector_store import set_tenant_context


@transaction.atomic
def configure_preparation(
    *,
    document_set: DocumentSet,
    embedding_profile: EmbeddingProfile,
    chunking_profile: ArtifactVersion,
    retrieval_profile: ArtifactVersion | None,
    ocr_profile: OcrProfile | None,
    summary_model_profile: ArtifactVersion | None,
    summary_prompt_contract: ArtifactVersion | None,
    auto_prepare: bool,
    actor: str,
    request_id: str = "",
) -> DocumentSetPreparationProfile:
    set_tenant_context(document_set.organization_id)
    policy, _ = DocumentSetPreparationProfile.objects.select_for_update().get_or_create(
        organization_id=document_set.organization_id,
        document_set=document_set,
        defaults={
            "embedding_profile": embedding_profile,
            "chunking_profile": chunking_profile,
            "retrieval_profile": retrieval_profile,
        },
    )
    policy.embedding_profile = embedding_profile
    policy.chunking_profile = chunking_profile
    policy.retrieval_profile = retrieval_profile
    policy.ocr_profile = ocr_profile
    policy.summary_model_profile = summary_model_profile
    policy.summary_prompt_contract = summary_prompt_contract
    policy.auto_prepare = auto_prepare
    policy.full_clean()
    policy.save()
    record_event(
        actor_type="user",
        actor_id=actor,
        action="ingestion.document_set.preparation_configured",
        outcome="success",
        organization_id=document_set.organization_id,
        resource_type="document_set",
        resource_id=str(document_set.public_id),
        request_id=request_id,
        after={
            "embedding_profile_id": str(embedding_profile.public_id),
            "chunking_profile_ref": chunking_profile.ref,
            "retrieval_profile_ref": retrieval_profile.ref if retrieval_profile else None,
            "summary_enabled": summary_model_profile is not None,
            "auto_prepare": auto_prepare,
        },
    )
    return policy


def enqueue_auto_preparation(
    *, document_set_version_id: int, organization_id: int
) -> StagedIndexBuildJob | None:
    """Persist the exact staged intent in the caller's publication transaction."""
    with transaction.atomic():
        set_tenant_context(organization_id)
        set_version = (
            DocumentSetVersion.objects.filter(
                pk=document_set_version_id,
                organization_id=organization_id,
            )
            .select_related("document_set")
            .select_for_update(of=("self",), no_key=True)
            .first()
        )
        if set_version is None:
            return None
        policy = (
            DocumentSetPreparationProfile.objects.select_for_update(of=("self",))
            .filter(
                organization_id=organization_id,
                document_set_id=set_version.document_set_id,
                auto_prepare=True,
            )
            .select_related(
                "embedding_profile",
                "chunking_profile",
                "retrieval_profile",
                "ocr_profile",
                "summary_model_profile",
                "summary_prompt_contract",
            )
            .first()
        )
        if policy is None:
            return None
        return automatic_preparation_job(
            document_set_version=set_version,
            embedding_profile=policy.embedding_profile,
            ocr_profile=policy.ocr_profile,
            policy=policy,
            actor="document-preparation-automation",
        )


@transaction.atomic
def automatic_preparation_job(
    *,
    document_set_version: DocumentSetVersion,
    embedding_profile: EmbeddingProfile,
    ocr_profile: OcrProfile | None,
    policy: DocumentSetPreparationProfile | None,
    actor: str,
) -> StagedIndexBuildJob:
    """Reuse exact automatic work, including terminal failures awaiting explicit retry.

    The version lock serializes automatic callers without changing manual build
    admission. Every profile FK and the canonical pipeline fingerprint must match.
    No provider or broker work happens before the caller commits.
    """
    from apps.ingestion.staged_build import pipeline_fingerprint

    set_tenant_context(document_set_version.organization_id)
    DocumentSetVersion.objects.select_for_update(no_key=True).get(
        pk=document_set_version.pk, organization_id=document_set_version.organization_id
    )
    chunking = policy.chunking_profile if policy else None
    retrieval = policy.retrieval_profile if policy else None
    summary_model = policy.summary_model_profile if policy else None
    summary_prompt = policy.summary_prompt_contract if policy else None
    pipeline = pipeline_fingerprint(
        embedding_profile=embedding_profile,
        ocr_profile=ocr_profile,
        chunker="fixed",
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        summary_model_profile=summary_model,
        summary_prompt_contract=summary_prompt,
    )
    query = StagedIndexBuildJob.objects.select_for_update().filter(
        organization_id=document_set_version.organization_id,
        kind="index_build",
        document_set_version=document_set_version,
        embedding_profile=embedding_profile,
        ocr_profile=ocr_profile,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        summary_model_profile=summary_model,
        summary_prompt_contract=summary_prompt,
        pipeline_fingerprint=pipeline,
    )
    existing = query.filter(status__in=ACTIVE_STATES).first() or query.order_by("-pk").first()
    if existing is not None:
        return existing
    job, _ = create_build_job(
        document_set_version=document_set_version,
        embedding_profile=embedding_profile,
        ocr_profile=ocr_profile,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        summary_model_profile=summary_model,
        summary_prompt_contract=summary_prompt,
        actor=actor,
    )
    return job
