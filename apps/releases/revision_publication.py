"""Explicit revision selection through the existing prepared-publication gate."""

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.ingestion.models import (
    ConnectorSchedulePromotionTarget,
    ConnectorSyncSchedule,
    Source,
    StagedIndexBuildJob,
)
from apps.ingestion.rest_services import RestServiceError
from apps.ingestion.revision_schedule import validate_revision_schedule
from apps.ingestion.source_revisions import (
    _authorize,
    _publication_scenarios,
    configuration_token,
    current_source,
    revision_for,
)


@dataclass(frozen=True)
class RevisionSelection:
    actor_id: int
    source_id: int
    index_id: int
    expected: str


def revision_approval(job, selection):
    actor = get_user_model().objects.filter(pk=selection.actor_id, is_active=True).first()
    if actor is None or job.source_id != selection.source_id:
        raise RestServiceError("SOURCE_REVISION_PUBLICATION_DENIED")
    source = _authorize(actor, job.source, operate=True)
    revision = revision_for(source)
    if not revision or not revision.schedule_config:
        raise RestServiceError("SOURCE_REVISION_PUBLICATION_INVALID")
    config = revision.schedule_config
    validate_revision_schedule(config)
    if "publication_targets" not in config:
        raise RestServiceError("SOURCE_REVISION_PUBLICATION_INVALID")
    build = job.preparation_job
    if not build or build.result_index_version_id != selection.index_id:
        raise RestServiceError("SOURCE_REVISION_BUILD_REQUIRED")
    replay = (
        current_source(source).pk == source.pk and build.result_index_version.status == "active"
    )
    if not replay and selection.expected != configuration_token(source):
        raise RestServiceError("SOURCE_REVISION_CHANGED")
    if config["preparation"] != build.pipeline_fingerprint:
        raise RestServiceError("REST_SETUP_PREPARATION_CHANGED")
    scenarios = _publication_scenarios(actor, source, config)
    # These unsaved projections carry reviewed intent. No schedule is enabled before PASS.
    schedule = ConnectorSyncSchedule(
        source=source,
        organization_id=source.organization_id,
        promotion_approved_by=str(actor.pk),
        embedding_profile_id=build.embedding_profile_id,
        ocr_profile_id=build.ocr_profile_id,
    )
    targets = [
        ConnectorSchedulePromotionTarget(
            scenario=scenario,
            approved_by=str(actor.pk),
            organization_id=source.organization_id,
        )
        for scenario in scenarios
    ]
    return schedule, targets


def publish_revision(*, actor, source, expected, index_id):
    from apps.evaluations.services import EvalError
    from apps.releases.publication import PublicationError
    from apps.releases.source_publication import continue_source_publication

    if type(index_id) is not int or not 0 < index_id <= 9223372036854775807:
        raise RestServiceError("SOURCE_REVISION_SELECTION_INVALID")
    with transaction.atomic():
        source = _authorize(actor, source, operate=True)
        job = (
            StagedIndexBuildJob.objects.filter(
                source=source,
                organization_id=source.organization_id,
                status="succeeded",
                preparation_job__status="succeeded",
                preparation_job__result_index_version_id=index_id,
            )
            .order_by("pk")
            .first()
        )
        if job is None:
            raise RestServiceError("SOURCE_REVISION_BUILD_REQUIRED")
    selection = RevisionSelection(actor.pk, source.pk, index_id, expected)
    try:
        continue_source_publication(
            job_id=job.pk,
            organization_id=source.organization_id,
            selection=selection,
        )
    except (PublicationError, EvalError) as exc:
        raise RestServiceError(exc.code) from None
    return Source.objects.get(pk=source.pk, organization_id=source.organization_id)
