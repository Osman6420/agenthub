"""Shared immutable document-set candidate assembly for connector snapshots."""

from __future__ import annotations

from collections.abc import Iterable

from apps.documents.models import DocumentSet, DocumentSetVersion, DocumentSetVersionStatus
from apps.documents.services import add_document_to_set_version, create_document_set_version


def create_material_candidate(
    *,
    document_set: DocumentSet,
    source_id: int,
    source_document_version_ids: Iterable[int],
    actor: str,
) -> DocumentSetVersion | None:
    """Merge one source slice into the newest trusted snapshot; return None for a no-op.

    Trusted baselines are published versions and connector-created successful candidates.  An
    unrelated author draft is deliberately not consumed by an automated connector.
    """
    from apps.ingestion.models import ConfluenceSyncRun, RestSyncRun

    published = (
        DocumentSetVersion.objects.filter(
            document_set=document_set,
            status__in=[
                DocumentSetVersionStatus.PROMOTABLE,
                DocumentSetVersionStatus.ACTIVE,
                DocumentSetVersionStatus.SUPERSEDED,
            ],
        )
        .order_by("-version")
        .first()
    )
    candidate_ids = list(
        ConfluenceSyncRun.objects.filter(
            source__document_set=document_set,
            status="succeeded",
            snapshot_complete=True,
            candidate_set_version__isnull=False,
        ).values_list("candidate_set_version_id", flat=True)
    ) + list(
        RestSyncRun.objects.filter(
            source__document_set=document_set,
            status="succeeded",
            snapshot_complete=True,
            candidate_set_version__isnull=False,
        ).values_list("candidate_set_version_id", flat=True)
    )
    baselines = DocumentSetVersion.objects.filter(document_set=document_set)
    if published is not None:
        candidate_ids.append(published.pk)
    baseline = baselines.filter(pk__in=candidate_ids).order_by("-version").first()

    retained: list[int] = []
    if baseline is not None:
        retained = list(
            baseline.memberships.exclude(document_version__document__source_id=source_id)
            .order_by("ordinal", "id")
            .values_list("document_version_id", flat=True)
        )
    source_versions = sorted({int(pk) for pk in source_document_version_ids})
    target = retained + source_versions
    if baseline is not None:
        current = list(
            baseline.memberships.order_by("ordinal", "id").values_list(
                "document_version_id", flat=True
            )
        )
        if current == target:
            return None

    candidate = create_document_set_version(document_set=document_set, actor=actor)
    from apps.documents.models import DocumentVersion

    versions = {
        item.pk: item
        for item in DocumentVersion.objects.filter(
            organization_id=document_set.organization_id, pk__in=target
        )
    }
    if len(versions) != len(target):
        raise ValueError("CONNECTOR_CANDIDATE_VERSION_MISMATCH")
    for ordinal, version_id in enumerate(target):
        add_document_to_set_version(
            set_version=candidate,
            document_version=versions[version_id],
            ordinal=ordinal,
            actor=actor,
        )
    return candidate
