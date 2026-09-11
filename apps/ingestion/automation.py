"""Optional post-sync staging and existing-gate release promotion orchestration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.documents.models import (
    DocumentSetVersion,
    DocumentSetVersionStatus,
    ScenarioDocumentSetBinding,
)
from apps.documents.services import publish_document_set_version
from apps.ingestion.models import (
    ConnectorAutomationStatus,
    ConnectorSchedulePromotionTarget,
    ConnectorSyncSchedule,
    IndexStatus,
    IndexVersion,
    ScheduleAutomationMode,
    TenantEmbeddingProfileGrant,
)
from apps.ingestion.staged_build import build_staged_index
from apps.ingestion.vector_store import set_tenant_context
from apps.releases.compiler import ArtifactRef
from apps.releases.models import ScenarioRelease
from apps.tenancy.services import can_manage_document_set_operations


class ConnectorAutomationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_AUTOMATION_CLAIM_LEASE = timedelta(minutes=35)


def claim_connector_automation(
    *, schedule_id: int, candidate_set_version_id: int, organization_id: int
) -> bool:
    """Atomically suppress concurrent/redelivered work; failed work remains explicitly retryable."""
    with transaction.atomic():
        set_tenant_context(organization_id)
        schedule = (
            ConnectorSyncSchedule.objects.select_for_update()
            .filter(pk=schedule_id, organization_id=organization_id)
            .first()
        )
        if schedule is None:
            raise ConnectorAutomationError("AUTOMATION_TARGET_NOT_FOUND")
        if (
            schedule.last_automation_candidate_id == candidate_set_version_id
            and schedule.automation_status == ConnectorAutomationStatus.SUCCEEDED
        ):
            return False
        if (
            schedule.last_automation_candidate_id == candidate_set_version_id
            and schedule.automation_status == ConnectorAutomationStatus.RUNNING
            and schedule.updated_at > timezone.now() - _AUTOMATION_CLAIM_LEASE
        ):
            raise ConnectorAutomationError("AUTOMATION_ALREADY_RUNNING")
        reclaimed = (
            schedule.last_automation_candidate_id == candidate_set_version_id
            and schedule.automation_status == ConnectorAutomationStatus.RUNNING
        )
        schedule.last_automation_candidate_id = candidate_set_version_id
        schedule.automation_status = ConnectorAutomationStatus.RUNNING
        schedule.automation_error_code = ""
        schedule.save(
            update_fields=[
                "last_automation_candidate",
                "automation_status",
                "automation_error_code",
                "updated_at",
            ]
        )
        if reclaimed:
            record_event(
                actor_type=ActorType.SYSTEM,
                actor_id="connector-automation",
                action="connector_automation.reclaimed",
                outcome=Outcome.SUCCESS,
                organization_id=organization_id,
                resource_type="connector_sync_schedule",
                resource_id=str(schedule.pk),
                after={"candidate_set_version_id": candidate_set_version_id},
            )
        return True


def finish_connector_automation(
    *,
    schedule_id: int,
    candidate_set_version_id: int,
    organization_id: int,
    succeeded: bool,
    error_code: str = "",
) -> None:
    with transaction.atomic():
        set_tenant_context(organization_id)
        schedule = ConnectorSyncSchedule.objects.select_for_update().get(
            pk=schedule_id,
            organization_id=organization_id,
            last_automation_candidate_id=candidate_set_version_id,
        )
        schedule.automation_status = (
            ConnectorAutomationStatus.SUCCEEDED if succeeded else ConnectorAutomationStatus.FAILED
        )
        schedule.automation_error_code = "" if succeeded else error_code[:64]
        schedule.save(update_fields=["automation_status", "automation_error_code", "updated_at"])
        record_event(
            actor_type=ActorType.SYSTEM,
            actor_id="connector-automation",
            action="connector_automation.finished",
            outcome=Outcome.SUCCESS if succeeded else Outcome.FAILURE,
            organization_id=organization_id,
            resource_type="connector_sync_schedule",
            resource_id=str(schedule.pk),
            reason="" if succeeded else schedule.automation_error_code,
            after={"candidate_set_version_id": candidate_set_version_id},
        )


def apply_connector_automation(
    *, schedule_id: int, candidate_set_version_id: int, organization_id: int
) -> str:
    from apps.ingestion.connector_preparation import continue_scheduled_publication

    publication = continue_scheduled_publication(
        schedule_id=schedule_id,
        candidate_set_version_id=candidate_set_version_id,
        organization_id=organization_id,
    )
    if publication is not None:
        return publication
    from apps.ingestion.connector_preparation import preparation_result, prepare_scheduled_candidate

    handled, preparation = prepare_scheduled_candidate(
        schedule_id=schedule_id,
        candidate_set_version_id=candidate_set_version_id,
        organization_id=organization_id,
    )
    if handled:
        return preparation_result(preparation)
    with transaction.atomic():
        set_tenant_context(organization_id)
        schedule = (
            ConnectorSyncSchedule.objects.select_related(
                "embedding_profile", "ocr_profile", "source"
            )
            .filter(pk=schedule_id, organization_id=organization_id)
            .first()
        )
        candidate = (
            DocumentSetVersion.objects.select_related("document_set")
            .filter(pk=candidate_set_version_id, organization_id=organization_id)
            .first()
        )
    if schedule is None or candidate is None:
        raise ConnectorAutomationError("AUTOMATION_TARGET_NOT_FOUND")
    if not schedule.enabled or schedule.automation_mode == ScheduleAutomationMode.DRAFT_ONLY:
        return "draft_only"
    if schedule.source.document_set_id != candidate.document_set_id:
        raise ConnectorAutomationError("AUTOMATION_DOCUMENT_SET_MISMATCH")
    if schedule.automation_mode != ScheduleAutomationMode.STAGE_ONLY:
        raise ConnectorAutomationError("AUTOMATION_DURABLE_SOURCE_JOB_REQUIRED")
    profile = schedule.embedding_profile
    if profile is None:
        raise ConnectorAutomationError("AUTOMATION_EMBEDDING_PROFILE_REQUIRED")
    with transaction.atomic():
        set_tenant_context(organization_id)
        if not TenantEmbeddingProfileGrant.objects.filter(
            organization_id=organization_id, embedding_profile=profile
        ).exists():
            raise ConnectorAutomationError("AUTOMATION_EMBEDDING_PROFILE_NOT_GRANTED")
    actor = f"connector-automation:{schedule.pk}"
    if candidate.status == DocumentSetVersionStatus.DRAFT:
        publish_document_set_version(set_version=candidate, actor=actor)
        candidate.refresh_from_db()
    index = (
        IndexVersion.objects.filter(
            document_set_version=candidate,
            embedding_profile=profile,
            store_ready=True,
            status__in=[IndexStatus.PROMOTABLE, IndexStatus.ACTIVE],
        )
        .order_by("-version")
        .first()
    )
    if index is None:
        index = build_staged_index(
            document_set_version=candidate,
            embedding_profile=profile,
            ocr_profile=schedule.ocr_profile,
            actor=actor,
        )
    _audit(schedule, "connector_automation.staged", Outcome.SUCCESS, candidate, index)
    return "staged"


def _validate_promotion_authority(
    *,
    schedule: ConnectorSyncSchedule,
    candidate: DocumentSetVersion,
    organization_id: int,
    targets: list[ConnectorSchedulePromotionTarget],
) -> Any:
    from apps.identity.scenario_actions import authorize_scenario_action

    manager = get_user_model().objects.filter(pk=schedule.promotion_approved_by).first()
    if (
        manager is None
        or not manager.is_active
        or not can_manage_document_set_operations(manager, candidate.document_set)
    ):
        raise ConnectorAutomationError("AUTOMATION_RELEASE_MANAGER_REVOKED")
    if not targets or len(targets) > 200:
        raise ConnectorAutomationError("AUTOMATION_PROMOTION_TARGET_REQUIRED")
    for raw_target in targets:
        target = raw_target
        if target.approved_by != schedule.promotion_approved_by:
            raise ConnectorAutomationError("AUTOMATION_TARGET_APPROVAL_MISMATCH")
        scenario = target.scenario
        target_is_bound = ScenarioDocumentSetBinding.objects.filter(
            scenario=scenario, document_set_id=candidate.document_set_id
        ).exists()
        if scenario.project.organization_id != organization_id or not target_is_bound:
            raise ConnectorAutomationError("AUTOMATION_TARGET_NO_LONGER_AUTHORIZED")
        if not all(
            authorize_scenario_action(user=manager, scenario=scenario, action=action).allowed
            for action in ("test", "release")
        ):
            raise ConnectorAutomationError("AUTOMATION_SCENARIO_AUTHORITY_REQUIRED")
    return manager


def _artifact_refs(release: ScenarioRelease, *, organization_id: int) -> list[ArtifactRef]:
    manifest = release.manifest if isinstance(release.manifest, dict) else {}
    artifacts = manifest.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise ConnectorAutomationError("ACTIVE_RELEASE_MANIFEST_INVALID")
    refs: list[ArtifactRef] = []
    for role, entry in artifacts.items():
        if not isinstance(role, str) or not isinstance(entry, dict):
            raise ConnectorAutomationError("ACTIVE_RELEASE_MANIFEST_INVALID")
        ref = entry.get("ref")
        artifact_type = entry.get("type")
        if not isinstance(ref, str) or ":v" not in ref or not isinstance(artifact_type, str):
            raise ConnectorAutomationError("ACTIVE_RELEASE_MANIFEST_INVALID")
        logical_id, _, version_text = ref.rpartition(":v")
        if not version_text.isdigit():
            raise ConnectorAutomationError("ACTIVE_RELEASE_MANIFEST_INVALID")
        if not ArtifactVersion.objects.filter(
            organization_id=organization_id,
            type=artifact_type,
            logical_id=logical_id,
            version=int(version_text),
        ).exists():
            raise ConnectorAutomationError("ACTIVE_RELEASE_ARTIFACT_MISSING")
        refs.append(ArtifactRef(role, artifact_type, logical_id, int(version_text)))
    return refs


def _audit(
    schedule: ConnectorSyncSchedule,
    action: str,
    outcome: str,
    candidate: DocumentSetVersion,
    index: IndexVersion,
    *,
    reason: str = "",
    promoted: int = 0,
) -> None:
    record_event(
        actor_type=ActorType.SYSTEM,
        actor_id="connector-automation",
        action=action,
        outcome=outcome,
        organization_id=schedule.organization_id,
        resource_type="connector_sync_schedule",
        resource_id=str(schedule.pk),
        reason=reason,
        after={
            "document_set_version_id": candidate.pk,
            "index_version_id": index.pk,
            "automation_mode": schedule.automation_mode,
            "promoted_scenarios": promoted,
        },
    )
