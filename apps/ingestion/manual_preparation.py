"""Explicit source-snapshot preparation through the canonical build authority."""

from __future__ import annotations

import re
from uuid import UUID

from django.conf import settings
from django.db import transaction

from apps.audit.services import record_event
from apps.documents.models import DocumentSetVersion
from apps.documents.services import DocumentError
from apps.ingestion.confluence import ConfluenceError
from apps.ingestion.connections import ConnectionError
from apps.ingestion.connector_jobs import (
    ConnectorJobError,
    _load_run,
    _lock_organization,
    _validate_inputs,
)
from apps.ingestion.connector_preparation import ConnectorPreparationError, _link_preparation
from apps.ingestion.job_lifecycle import BuildJobError
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.models import Source, StagedIndexBuildJob
from apps.ingestion.rest import RestPullError
from apps.ingestion.rest_services import RestServiceError
from apps.ingestion.rest_setup_schedule import setup_preparation_policy
from apps.tenancy.context import set_tenant_context
from apps.tenancy.services import UserLike, can_manage_documents

PREPARATION_ERRORS = (
    ConnectorPreparationError,
    ConnectorJobError,
    ConnectionError,
    RestServiceError,
    RestPullError,
    ConfluenceError,
    McpResourceError,
    BuildJobError,
    DocumentError,
)


def prepare_source_snapshot(
    *, actor: UserLike, source: Source, job_public_id: UUID, expected_policy: str
) -> StagedIndexBuildJob:
    """Reauthorize every request, including replay; audit failure rolls back all writes."""
    try:
        with transaction.atomic():
            set_tenant_context(source.organization_id)
            _lock_organization(source.organization_id)
            if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
                raise ConnectorPreparationError("PREPARATION_UNAVAILABLE")
            job = (
                StagedIndexBuildJob.objects.select_for_update()
                .filter(
                    organization_id=source.organization_id,
                    source_id=source.pk,
                    public_id=job_public_id,
                )
                .first()
            )
            if job is None:
                raise ConnectorPreparationError("PREPARATION_SOURCE_JOB_NOT_FOUND")
            run = _load_run(job)
            docset = run.source.document_set
            if docset is None or not can_manage_documents(
                actor, source.organization_id, document_set=docset
            ):
                raise ConnectorPreparationError("PREPARATION_MANAGER_REQUIRED")
            _validate_inputs(job, run)
            if (
                job.status != "succeeded"
                or not run.snapshot_complete
                or run.candidate_set_version_id is None
            ):
                raise ConnectorPreparationError("PREPARATION_COMPLETE_SNAPSHOT_REQUIRED")
            if (
                not isinstance(expected_policy, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_policy) is None
            ):
                raise ConnectorPreparationError("PREPARATION_REVIEW_REQUIRED")
            if job.preparation_job is not None:
                # Replays never rebind the snapshot or cause a paid retry.
                if job.preparation_job.pipeline_fingerprint != expected_policy:
                    raise ConnectorPreparationError("PREPARATION_ALREADY_LINKED")
                return job.preparation_job
            candidate = DocumentSetVersion.objects.select_for_update(no_key=True).get(
                pk=run.candidate_set_version_id,
                organization_id=source.organization_id,
                document_set=docset,
            )
            policy = setup_preparation_policy(docset, expected=expected_policy, lock=True)
            return _link_preparation(
                source_job=job,
                candidate=candidate,
                policy=policy,
                embedding=policy.embedding_profile,
                ocr=policy.ocr_profile,
                actor=str(actor.pk),
                actor_type="user",
            )
    except PREPARATION_ERRORS as exc:
        with transaction.atomic():
            set_tenant_context(source.organization_id)
            record_event(
                actor_type="user",
                actor_id=str(getattr(actor, "pk", "anonymous")),
                organization_id=source.organization_id,
                action="ingestion.connector_job.preparation_denied",
                outcome="deny",
                resource_type="source",
                resource_id=str(source.pk),
                reason=exc.code,
            )
        raise
