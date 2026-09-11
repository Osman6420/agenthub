"""Reviewed collection settings without requiring or starting a document build."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.documents.models import DocumentSet
from apps.documents.profile_authoring import (
    DocumentProfileAuthoringError,
    publish_document_profile_artifact,
)
from apps.ingestion.models import DocumentSetPreparationProfile, EmbeddingProfile, OcrProfile
from apps.ingestion.preparation import configure_preparation
from apps.ingestion.rest_setup_schedule import preparation_fingerprint
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import UserLike, can_manage_documents


class PreparationSettingsError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def current_preparation(document_set: DocumentSet, *, lock: bool = False):
    query = DocumentSetPreparationProfile.objects.select_related(
        "embedding_profile",
        "ocr_profile",
        "chunking_profile",
        "retrieval_profile",
        "summary_model_profile",
        "summary_prompt_contract",
    ).filter(organization_id=document_set.organization_id, document_set=document_set)
    if lock:
        query = query.select_for_update(of=("self",))
    return query.first()


def configuration_token(policy: DocumentSetPreparationProfile | None) -> str:
    if policy is None:
        return "new"
    return hashlib.sha256(
        json.dumps(
            {
                "pipeline": preparation_fingerprint(policy),
                "auto_prepare": policy.auto_prepare,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def save_preparation_settings(
    *,
    actor: UserLike,
    document_set: DocumentSet,
    expected: str,
    embedding_profile_id: int,
    ocr_profile_id: int | None,
    chunking_profile_id: int | None,
    standard_chunking: dict[str, Any] | None,
    auto_prepare: bool,
) -> DocumentSetPreparationProfile:
    org_id = document_set.organization_id
    try:
        with transaction.atomic():
            set_tenant_context(org_id)
            org = Organization.objects.select_for_update(no_key=True).get(pk=org_id)
            docset = DocumentSet.objects.get(pk=document_set.pk, organization_id=org_id)
            if not can_manage_documents(actor, org_id, document_set=docset):
                raise PreparationSettingsError("PREPARATION_SETTINGS_FORBIDDEN")
            if org.status != "active" or docset.status != "active":
                raise PreparationSettingsError("PREPARATION_SETTINGS_UNAVAILABLE")
            policy = current_preparation(docset, lock=True)
            if expected != configuration_token(policy):
                raise PreparationSettingsError("PREPARATION_SETTINGS_CHANGED")
            if type(auto_prepare) is not bool:
                raise PreparationSettingsError("PREPARATION_SETTINGS_INVALID")
            embedding = EmbeddingProfile.objects.get(pk=embedding_profile_id, status="active")
            ocr = (
                OcrProfile.objects.get(pk=ocr_profile_id, status="active")
                if ocr_profile_id
                else None
            )
            if not embedding.tenant_grants.filter(organization_id=org_id).exists() or (
                ocr and not ocr.tenant_grants.filter(organization_id=org_id).exists()
            ):
                raise PreparationSettingsError("PREPARATION_SETTINGS_PROFILE_NOT_GRANTED")
            if chunking_profile_id is not None:
                chunking = ArtifactVersion.objects.get(
                    pk=chunking_profile_id, organization_id=org_id, type="chunking_profile"
                )
            else:
                if not isinstance(standard_chunking, dict):
                    raise PreparationSettingsError("PREPARATION_SETTINGS_CHUNKING_REQUIRED")
                checksum = compute_checksum(standard_chunking)
                logical_id = f"set_{docset.public_id.hex}_{checksum}"
                existing_chunking = (
                    ArtifactVersion.objects.filter(
                        organization_id=org_id, type="chunking_profile", logical_id=logical_id
                    )
                    .order_by("version")
                    .first()
                )
                if existing_chunking is not None and existing_chunking.checksum != checksum:
                    raise PreparationSettingsError("PREPARATION_SETTINGS_CHUNKING_CONFLICT")
                if existing_chunking is None:
                    chunking = publish_document_profile_artifact(
                        user=actor,
                        document_set=docset,
                        artifact_type="chunking_profile",
                        logical_id=logical_id,
                        logical_description=f"{docset.name} · Standart belge parçalama",
                        version_description="İlk hazırlama ayarları için standart parçalama",
                        body=standard_chunking,
                    )
                else:
                    chunking = existing_chunking
            return configure_preparation(
                document_set=docset,
                embedding_profile=embedding,
                ocr_profile=ocr,
                chunking_profile=chunking,
                auto_prepare=auto_prepare,
                retrieval_profile=policy.retrieval_profile if policy else None,
                summary_model_profile=policy.summary_model_profile if policy else None,
                summary_prompt_contract=policy.summary_prompt_contract if policy else None,
                actor=str(getattr(actor, "pk", "anonymous")),
            )
    except (
        PreparationSettingsError,
        ValidationError,
        ObjectDoesNotExist,
        DocumentProfileAuthoringError,
    ) as exc:
        code = (
            exc.code
            if isinstance(exc, PreparationSettingsError)
            else "PREPARATION_SETTINGS_INVALID"
        )
        with transaction.atomic():
            set_tenant_context(org_id)
            record_event(
                actor_type="user",
                actor_id=str(getattr(actor, "pk", "anonymous")),
                action="ingestion.document_set.preparation_configured",
                outcome="deny",
                organization_id=org_id,
                resource_type="document_set",
                resource_id=str(document_set.public_id),
                reason=code,
            )
        raise PreparationSettingsError(code) from exc
