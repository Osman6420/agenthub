"""Exact document-set scoped authoring for immutable preparation artifacts."""

from __future__ import annotations

import re
from typing import Any

from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import ArtifactValidationError, compute_checksum
from apps.audit.services import record_event
from apps.documents.models import DocumentSet
from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.tenancy.services import can_manage_document_set_operations

AUTHORABLE_TYPES = frozenset(
    {
        ArtifactType.CHUNKING_PROFILE,
        ArtifactType.RETRIEVAL_PROFILE,
        ArtifactType.PROMPT_TEMPLATE,
        ArtifactType.MODEL_PROFILE,
    }
)
_LOGICAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class DocumentProfileAuthoringError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _bounded_text(value: Any, *, code: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise DocumentProfileAuthoringError(code)
    normalized = " ".join(value.split())
    if required and not normalized:
        raise DocumentProfileAuthoringError(code)
    if len(normalized) > maximum:
        raise DocumentProfileAuthoringError(code)
    return normalized


def _validated_body(artifact_type: str, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise DocumentProfileAuthoringError("artifact_body_invalid")
    if artifact_type == ArtifactType.MODEL_PROFILE:
        profile_id = body.get("profile_id")
        if (
            not isinstance(profile_id, str)
            or not ModelProfile.objects.filter(
                public_id=profile_id,
                status=ModelProfileStatus.ACTIVE,
            ).exists()
        ):
            raise DocumentProfileAuthoringError("model_profile_unavailable")
    return body


def publish_document_profile_artifact(
    *,
    user: Any,
    document_set: DocumentSet,
    source_artifact_id: Any = None,
    artifact_type: Any = None,
    logical_id: Any = None,
    logical_description: Any = None,
    version_description: Any = None,
    body: Any = None,
    request_id: str = "",
) -> ArtifactVersion:
    """Create an immutable preparation artifact under exact document-set authority."""

    actor = str(user.get_username())[:200]
    if not can_manage_document_set_operations(user, document_set):
        record_event(
            actor_type="user",
            actor_id=actor,
            action="document_set.profile_artifact.publish",
            outcome="failure",
            organization_id=document_set.organization_id,
            resource_type="document_set",
            resource_id=str(document_set.public_id),
            reason="not_allowed",
            request_id=request_id,
        )
        raise DocumentProfileAuthoringError("not_allowed")

    return _publish_authorized(
        document_set=document_set,
        actor=actor,
        source_artifact_id=source_artifact_id,
        artifact_type=artifact_type,
        logical_id=logical_id,
        logical_description=logical_description,
        version_description=version_description,
        body=body,
        request_id=request_id,
    )


@transaction.atomic
def _publish_authorized(
    *,
    document_set: DocumentSet,
    actor: str,
    source_artifact_id: Any,
    artifact_type: Any,
    logical_id: Any,
    logical_description: Any,
    version_description: Any,
    body: Any,
    request_id: str,
) -> ArtifactVersion:

    source: ArtifactVersion | None = None
    if source_artifact_id is not None:
        if (
            isinstance(source_artifact_id, bool)
            or not isinstance(source_artifact_id, int)
            or source_artifact_id < 1
        ):
            raise DocumentProfileAuthoringError("source_artifact_invalid")
        source = ArtifactVersion.objects.filter(
            pk=source_artifact_id,
            organization_id=document_set.organization_id,
            type__in=AUTHORABLE_TYPES,
        ).first()
        if source is None:
            raise DocumentProfileAuthoringError("source_artifact_unavailable")
        resolved_type = source.type
        resolved_logical_id = source.logical_id
        resolved_logical_description = source.logical_description
    else:
        if artifact_type not in AUTHORABLE_TYPES:
            raise DocumentProfileAuthoringError("artifact_type_unsupported")
        resolved_type = str(artifact_type)
        resolved_logical_id = _bounded_text(logical_id, code="logical_id_invalid", maximum=128)
        if not _LOGICAL_ID.fullmatch(resolved_logical_id):
            raise DocumentProfileAuthoringError("logical_id_invalid")
        if ArtifactVersion.objects.filter(
            organization_id=document_set.organization_id,
            type=resolved_type,
            logical_id=resolved_logical_id,
        ).exists():
            raise DocumentProfileAuthoringError("logical_id_exists")
        resolved_logical_description = _bounded_text(
            logical_description,
            code="logical_description_invalid",
            maximum=1000,
        )

    resolved_version_description = _bounded_text(
        version_description,
        code="version_description_required",
        maximum=1000,
    )
    resolved_body = _validated_body(resolved_type, body)
    if source is not None and compute_checksum(resolved_body) == source.checksum:
        raise DocumentProfileAuthoringError("artifact_unchanged")
    try:
        artifact = create_artifact_version(
            organization=document_set.organization,
            artifact_type=resolved_type,
            logical_id=resolved_logical_id,
            logical_description=resolved_logical_description,
            version_description=resolved_version_description,
            body=resolved_body,
            created_by=actor,
        )
    except (ArtifactValidationError, ValueError) as exc:
        raise DocumentProfileAuthoringError("artifact_invalid") from exc
    record_event(
        actor_type="user",
        actor_id=actor,
        action="document_set.profile_artifact.publish",
        outcome="success",
        organization_id=document_set.organization_id,
        resource_type=artifact.type,
        resource_id=artifact.ref,
        reason=artifact.checksum,
        request_id=request_id,
        after={"document_set_id": str(document_set.public_id)},
    )
    return artifact
