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
from apps.evaluations.models import EvalStatus
from apps.evaluations.services import run_eval
from apps.ingestion.models import (
    ConnectorAutomationStatus,
    ConnectorSchedulePromotionTarget,
    ConnectorSyncSchedule,
    IndexStatus,
    IndexVersion,
    ScheduleAutomationMode,
    TenantEmbeddingProfileGrant,
)
from apps.ingestion.staged_build import build_staged_index, promote_staged_index
from apps.ingestion.vector_store import set_tenant_context
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.lifecycle import promote
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.services import can_manage_releases


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
        targets = (
            list(schedule.promotion_targets.select_related("scenario__project").all())
            if schedule is not None
            else []
        )
    if schedule is None or candidate is None:
        raise ConnectorAutomationError("AUTOMATION_TARGET_NOT_FOUND")
    if not schedule.enabled or schedule.automation_mode == ScheduleAutomationMode.DRAFT_ONLY:
        return "draft_only"
    if schedule.source.document_set_id != candidate.document_set_id:
        raise ConnectorAutomationError("AUTOMATION_DOCUMENT_SET_MISMATCH")
    if schedule.automation_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE:
        _validate_promotion_authority(
            schedule=schedule,
            candidate=candidate,
            organization_id=organization_id,
            targets=targets,
        )
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
    if schedule.automation_mode == ScheduleAutomationMode.STAGE_ONLY:
        _audit(schedule, "connector_automation.staged", Outcome.SUCCESS, candidate, index)
        return "staged"

    manager = _validate_promotion_authority(
        schedule=schedule,
        candidate=candidate,
        organization_id=organization_id,
        targets=targets,
    )
    if index.status == IndexStatus.PROMOTABLE:
        index = promote_staged_index(index, actor=actor)
    promoted = 0
    for target in targets:
        scenario = target.scenario
        active = (
            ScenarioRelease.objects.filter(scenario=scenario, status=ReleaseStatus.ACTIVE)
            .order_by("-promoted_at", "-id")
            .first()
        )
        if active is None:
            _audit(
                schedule,
                "connector_automation.release_skipped",
                Outcome.DENY,
                candidate,
                index,
                reason="ACTIVE_RELEASE_REQUIRED",
            )
            continue
        refs = _artifact_refs(active, organization_id=organization_id)
        pinned_indexes = (
            active.manifest.get("index_versions", []) if isinstance(active.manifest, dict) else []
        )
        release = compile_release(
            scenario=scenario,
            refs=refs,
            runtime_version=active.runtime_version,
            created_by=actor,
            index_versions=[
                value
                for value in pinned_indexes
                if isinstance(value, int) and not isinstance(value, bool)
            ],
        )
        evaluation = run_eval(release=release, created_by=actor)
        if evaluation.status != EvalStatus.PASSED:
            _audit(
                schedule,
                "connector_automation.release_skipped",
                Outcome.DENY,
                candidate,
                index,
                reason="EVAL_NOT_PASSED",
            )
            continue
        promote(release=release, actor=str(getattr(manager, "username", manager.pk)))
        promoted += 1
    _audit(
        schedule,
        "connector_automation.completed",
        Outcome.SUCCESS,
        candidate,
        index,
        reason="promotion_gates_passed" if promoted else "no_release_promoted",
        promoted=promoted,
    )
    return "promoted" if promoted else "staged"


def _validate_promotion_authority(
    *,
    schedule: ConnectorSyncSchedule,
    candidate: DocumentSetVersion,
    organization_id: int,
    targets: list[ConnectorSchedulePromotionTarget],
) -> Any:
    manager = get_user_model().objects.filter(pk=schedule.promotion_approved_by).first()
    if manager is None or not can_manage_releases(manager, organization_id):
        raise ConnectorAutomationError("AUTOMATION_RELEASE_MANAGER_REVOKED")
    if not targets:
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
