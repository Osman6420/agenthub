"""Exact-authorized, bounded and audited reads of immutable document bytes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.audit.services import record_event
from apps.documents.models import Document, DocumentSet, DocumentSetMembership, DocumentVersion
from apps.documents.storage import StorageError, get_object_store
from apps.identity.authorization import Capability, authorize


class DocumentContentError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DocumentContent:
    data: bytes
    text: str | None = None


def _actor_id(actor: Any) -> str:
    return str(getattr(actor, "pk", "anonymous"))


def _audit(
    *,
    actor: Any,
    document_set: DocumentSet,
    version: DocumentVersion,
    operation: str,
    outcome: str,
    reason: str = "",
    request_id: str = "",
    trace_id: str = "",
) -> None:
    record_event(
        actor_type="user",
        actor_id=_actor_id(actor),
        action=f"document_content.{operation}",
        outcome=outcome,
        organization_id=document_set.organization_id,
        resource_type="document_version",
        resource_id=str(version.pk),
        reason=reason,
        request_id=request_id,
        trace_id=trace_id,
        after={
            "document_set_id": document_set.pk,
            "byte_size": version.byte_size,
            "mime_type": version.mime_type,
        },
    )


def read_document_version_content(
    *,
    actor: Any,
    document_set: DocumentSet,
    document: Document,
    version: DocumentVersion,
    operation: str,
    max_bytes: int,
    allowed_mime_types: frozenset[str] | None = None,
    require_utf8: bool = False,
    request_id: str = "",
    trace_id: str = "",
) -> DocumentContent:
    """Return one exact version only after scope, capability, bounds and audit succeed."""

    if operation not in {"preview", "download"} or max_bytes <= 0:
        raise DocumentContentError("CONTENT_READ_CONTRACT_INVALID")
    decision = authorize(
        user=actor,
        capability=Capability.DOCUMENT_SET_CONTENT_READ,
        organization=document_set.organization,
        document_set=document_set,
    )
    in_scope = (
        document.organization_id == document_set.organization_id
        and version.organization_id == document_set.organization_id
        and version.document_id == document.pk
        and DocumentSetMembership.objects.filter(
            document_set_version__document_set=document_set,
            document_version=version,
        ).exists()
    )
    if not decision.allowed or not in_scope:
        _audit(
            actor=actor,
            document_set=document_set,
            version=version,
            operation=operation,
            outcome="deny",
            reason=(
                "DOCUMENT_CONTENT_FORBIDDEN"
                if not decision.allowed
                else "DOCUMENT_SCOPE_MISMATCH"
            ),
            request_id=request_id,
            trace_id=trace_id,
        )
        raise DocumentContentError("DOCUMENT_CONTENT_FORBIDDEN")
    if allowed_mime_types is not None and version.mime_type.lower() not in allowed_mime_types:
        _audit(
            actor=actor,
            document_set=document_set,
            version=version,
            operation=operation,
            outcome="failure",
            reason="CONTENT_PREVIEW_TYPE_UNSUPPORTED",
            request_id=request_id,
            trace_id=trace_id,
        )
        raise DocumentContentError("CONTENT_PREVIEW_TYPE_UNSUPPORTED")
    if version.byte_size > max_bytes:
        _audit(
            actor=actor,
            document_set=document_set,
            version=version,
            operation=operation,
            outcome="failure",
            reason="CONTENT_TOO_LARGE",
            request_id=request_id,
            trace_id=trace_id,
        )
        raise DocumentContentError("CONTENT_TOO_LARGE")
    try:
        data = get_object_store().get(version.object_key)
    except StorageError as exc:
        _audit(
            actor=actor,
            document_set=document_set,
            version=version,
            operation=operation,
            outcome="failure",
            reason=exc.code,
            request_id=request_id,
            trace_id=trace_id,
        )
        raise DocumentContentError("CONTENT_STORAGE_UNAVAILABLE") from exc
    if len(data) != version.byte_size or len(data) > max_bytes:
        _audit(
            actor=actor,
            document_set=document_set,
            version=version,
            operation=operation,
            outcome="failure",
            reason="CONTENT_SIZE_MISMATCH",
            request_id=request_id,
            trace_id=trace_id,
        )
        raise DocumentContentError("CONTENT_SIZE_MISMATCH")
    text: str | None = None
    if require_utf8:
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            _audit(
                actor=actor,
                document_set=document_set,
                version=version,
                operation=operation,
                outcome="failure",
                reason="CONTENT_PREVIEW_ENCODING_INVALID",
                request_id=request_id,
                trace_id=trace_id,
            )
            raise DocumentContentError("CONTENT_PREVIEW_ENCODING_INVALID") from exc
    _audit(
        actor=actor,
        document_set=document_set,
        version=version,
        operation=operation,
        outcome="success",
        request_id=request_id,
        trace_id=trace_id,
    )
    return DocumentContent(data=data, text=text)
