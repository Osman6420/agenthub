"""Closed REST setup schedule and exact existing preparation-policy selection."""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError

from apps.documents.models import DocumentSet
from apps.ingestion.models import DocumentSetPreparationProfile
from apps.ingestion.rest_services import RestServiceError
from apps.ingestion.staged_build import pipeline_fingerprint


def validate_setup_schedule(schedule: Any) -> None:
    # The historical interval-only shape always means draft-only.
    if schedule is None:
        return
    if (
        not isinstance(schedule, dict)
        or set(schedule) not in ({"interval_seconds"}, {"interval_seconds", "preparation"})
        or type(schedule.get("interval_seconds")) is not int
        or schedule["interval_seconds"] not in {900, 3600, 21600, 86400, 604800}
        or (
            "preparation" in schedule
            and (
                not isinstance(schedule["preparation"], str)
                or re.fullmatch(r"[0-9a-f]{64}", schedule["preparation"]) is None
            )
        )
    ):
        raise RestServiceError("REST_SETUP_SCHEDULE_INVALID")


def preparation_fingerprint(policy: DocumentSetPreparationProfile) -> str:
    return pipeline_fingerprint(
        embedding_profile=policy.embedding_profile,
        ocr_profile=policy.ocr_profile,
        chunker="fixed",
        chunking_profile=policy.chunking_profile,
        retrieval_profile=policy.retrieval_profile,
        summary_model_profile=policy.summary_model_profile,
        summary_prompt_contract=policy.summary_prompt_contract,
    )


def setup_preparation_policy(
    document_set: DocumentSet, *, expected: str | None = None, lock: bool = False
) -> DocumentSetPreparationProfile:
    """Read scoped configuration; this selector grants no actor or provider authority."""
    query = DocumentSetPreparationProfile.objects.filter(
        organization_id=document_set.organization_id, document_set=document_set
    ).select_related(
        "embedding_profile",
        "ocr_profile",
        "chunking_profile",
        "retrieval_profile",
        "summary_model_profile",
        "summary_prompt_contract",
    )
    if lock:
        query = query.select_for_update(of=("self",))
    policy = query.first()
    if policy is None:
        raise RestServiceError("REST_SETUP_PREPARATION_REQUIRED")
    try:
        policy.full_clean()
    except ValidationError as exc:
        raise RestServiceError("REST_SETUP_PREPARATION_UNAVAILABLE") from exc
    if policy.embedding_profile.status != "active" or (
        policy.ocr_profile is not None and policy.ocr_profile.status != "active"
    ):
        raise RestServiceError("REST_SETUP_PREPARATION_UNAVAILABLE")
    if expected is not None and preparation_fingerprint(policy) != expected:
        raise RestServiceError("REST_SETUP_PREPARATION_CHANGED")
    return policy
