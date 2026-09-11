"""Publish one prepared source across its approved scenarios, all or nothing."""

import re
from uuid import uuid5

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.catalog.lifecycle import _assert_release_indexes_served, activate_scenario
from apps.catalog.models import Scenario, ScenarioAlias
from apps.documents.models import DocumentSet, DocumentSetVersion, ScenarioDocumentSetBinding
from apps.evaluations.models import EvalDataGeneration, EvalStatus
from apps.evaluations.prepared import (
    _source_proof,
    admit_prepared_evaluation,
    validate_prepared_admission,
)
from apps.evaluations.services import evaluation_consumer_for_organization, resume_eval
from apps.identity.scenario_actions import authorize_scenario_action
from apps.ingestion.automation import _artifact_refs, _validate_promotion_authority
from apps.ingestion.connector_jobs import _load_run
from apps.ingestion.models import ConnectorSyncSchedule, StagedIndexBuildJob
from apps.ingestion.staged_build import promote_staged_index
from apps.orchestration.resolver import resolve_bundle
from apps.releases.compiler import compile_release
from apps.releases.lifecycle import promote
from apps.releases.models import ScenarioPublication, ScenarioRelease
from apps.releases.publication import PublicationError
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization

MAX_TARGETS = 200


def _state(job_id, organization_id, selection=None):
    """Caller owns the organization mutex; reload current approval and exact source proof."""
    job = StagedIndexBuildJob.objects.select_related("source", "preparation_job").get(
        pk=job_id,
        organization_id=organization_id,
    )
    protocol = _load_run(job)
    schedule_id, source_id, build = protocol.schedule_id, job.source_id, job.preparation_job
    source = job.source
    if source is None or source_id is None or build is None:
        raise PublicationError("SOURCE_PUBLICATION_PREPARATION_REQUIRED")
    candidate, index = _source_proof(job)
    schedule: ConnectorSyncSchedule
    if selection is not None:
        from apps.releases.revision_publication import revision_approval

        schedule, targets = revision_approval(job, selection)
    else:
        from apps.ingestion.source_revisions import assert_revision_sync

        if schedule_id is None:
            raise PublicationError("SOURCE_PUBLICATION_PREPARATION_REQUIRED")
        scheduled = ConnectorSyncSchedule.objects.filter(
            pk=schedule_id,
            organization_id=organization_id,
            source_id=source_id,
            enabled=True,
            automation_mode="promote_if_safe",
        ).first()
        if scheduled is None:
            raise PublicationError("SOURCE_PUBLICATION_APPROVAL_CHANGED")
        schedule = scheduled
        targets = list(
            schedule.promotion_targets.select_related("scenario__project").order_by("scenario_id")[
                : MAX_TARGETS + 1
            ]
        )
        assert_revision_sync(source, scheduled=True)
    if not targets or len(targets) > MAX_TARGETS:
        raise PublicationError("SOURCE_PUBLICATION_TARGETS_INVALID")
    actor = _validate_promotion_authority(
        schedule=schedule,
        candidate=candidate,
        organization_id=organization_id,
        targets=targets,
    )
    if not actor.is_active or (schedule.embedding_profile_id, schedule.ocr_profile_id) != (
        build.embedding_profile_id,
        build.ocr_profile_id,
    ):
        raise PublicationError("SOURCE_PUBLICATION_APPROVAL_CHANGED")
    target_ids = {t.scenario_id for t in targets}
    scenarios = list(
        Scenario.objects.select_for_update(no_key=True)
        .filter(
            pk__in=target_ids,
            organization_id=organization_id,
        )
        .select_related("organization", "project")
        .order_by("pk")
    )
    if len(scenarios) != len(target_ids) or any(
        not all(
            authorize_scenario_action(user=actor, scenario=s, action=a).allowed
            for a in ("test", "release")
        )
        for s in scenarios
    ):
        raise PublicationError("SOURCE_PUBLICATION_DENIED")
    # Replacing an index also stops legacy releases pinned to the old active version.
    # Every affected live scenario must be an explicitly approved target.
    active_versions = list(
        DocumentSetVersion.objects.filter(
            document_set_id=candidate.document_set_id,
            organization_id=organization_id,
            status="active",
        ).values_list("pk", flat=True)[: MAX_TARGETS + 1]
    )
    if len(active_versions) > MAX_TARGETS:
        raise PublicationError("SOURCE_PUBLICATION_SCOPE_TOO_LARGE")
    affected = Q(
        execution_revision__snapshot__data__selection="active_generation",
        execution_revision__snapshot__data__document_set_ids__contains=[candidate.document_set_id],
    )
    for version_id in active_versions:
        affected |= Q(manifest__document_set_versions__contains=[version_id])
    if (
        ScenarioRelease.objects.filter(affected, organization_id=organization_id, status="active")
        .exclude(scenario_id__in=target_ids)
        .exists()
    ):
        raise PublicationError("SOURCE_PUBLICATION_UNAPPROVED_IMPACT")
    state = {
        "job": str(job.public_id),
        "config": job.source_config_checksum,
        "pipeline": build.pipeline_fingerprint,
        "index": index.pk,
        "schedule": schedule.pk,
        "actor": actor.pk,
        "targets": [[t.scenario_id, t.approved_by] for t in targets],
    }
    if selection is not None:
        state["revision_selection"] = {
            "source": selection.source_id,
            "index": selection.index_id,
            "actor": selection.actor_id,
            "expected": selection.expected,
        }
    return job, actor, scenarios, candidate, index, state


def _baseline(scenario):
    active = ScenarioRelease.objects.filter(
        organization_id=scenario.organization_id,
        scenario=scenario,
        status="active",
    ).first()
    if active is None:
        raise PublicationError("SOURCE_PUBLICATION_BASELINE_REQUIRED")
    bundle = resolve_bundle(active)
    if (
        scenario.execution_contract != active.execution_contract
        or scenario.data_selection != bundle.data_selection
    ):
        raise PublicationError("SOURCE_PUBLICATION_SETTINGS_CHANGED")
    if bundle.index_versions:
        raise PublicationError("SOURCE_PUBLICATION_DATA_UNSUPPORTED")
    if not ScenarioAlias.objects.filter(scenario=scenario, status="active").exists():
        raise PublicationError("ACTIVE_ALIAS_REQUIRED")
    bindings = list(
        ScenarioDocumentSetBinding.objects.filter(
            scenario=scenario,
            organization_id=scenario.organization_id,
        )
        .order_by("document_set_id")
        .values_list("document_set_id", flat=True)[: MAX_TARGETS + 1]
    )
    if len(bindings) > MAX_TARGETS:
        raise PublicationError("SOURCE_PUBLICATION_SCOPE_TOO_LARGE")
    if bundle.data_selection == "active_generation" and set(bindings) != set(
        bundle.document_set_ids
    ):
        raise PublicationError("SOURCE_PUBLICATION_SETTINGS_CHANGED")
    return active, bindings


def _token(state, baseline, bindings):
    return compute_checksum(
        state
        | {
            "baseline": baseline.pk,
            "manifest": baseline.artifact_manifest_sha256,
            "execution": baseline.execution_contract,
            "bindings": bindings,
        }
    )


def _audit(receipt, actor, action):
    record_event(
        actor_type="user",
        actor_id=str(actor.pk),
        organization_id=receipt.organization_id,
        action=f"scenario.publication.{action}",
        outcome="success",
        resource_type="scenario_publication",
        resource_id=str(receipt.public_id),
        reason="PREPARED_SOURCE",
        after={
            "source_job_id": receipt.source_job_id,
            "release_id": receipt.release_id,
            "evaluation_id": receipt.evaluation_id,
        },
    )


@transaction.atomic
def _prepare(job_id, organization_id, selection=None):
    set_tenant_context(organization_id)
    Organization.objects.select_for_update(no_key=True).get(pk=organization_id)
    job, actor, scenarios, candidate, _, state = _state(job_id, organization_id, selection)
    existing = list(
        ScenarioPublication.objects.filter(source_job=job)
        .select_related("release", "evaluation")
        .order_by("scenario_id")
    )
    if existing:
        if {r.scenario_id for r in existing} != {s.pk for s in scenarios}:
            raise PublicationError("SOURCE_PUBLICATION_APPROVAL_CHANGED")
        if all(r.completed_at is not None for r in existing):
            return existing
        if any(r.completed_at is not None for r in existing):
            raise PublicationError("SOURCE_PUBLICATION_RECEIPTS_INCONSISTENT")
        for scenario, receipt in zip(scenarios, existing, strict=True):
            baseline, bindings = _baseline(scenario)
            if receipt.created_by != str(actor.pk) or receipt.request_checksum != _token(
                state, baseline, bindings
            ):
                raise PublicationError("SOURCE_PUBLICATION_BASELINE_CHANGED")
        return existing
    receipts = []
    for scenario in scenarios:
        baseline, bindings = _baseline(scenario)
        if candidate.document_set_id not in bindings:
            raise PublicationError("SOURCE_PUBLICATION_SCOPE_INVALID")
        refs = _artifact_refs(baseline, organization_id=organization_id)
        # Legacy catalogue mutations must not change the artifacts that were approved.
        for role, pin in baseline.manifest["artifacts"].items():
            ref = next(r for r in refs if r.role == role)
            artifact = ArtifactVersion.objects.get(
                organization_id=organization_id,
                type=ref.type,
                logical_id=ref.logical_id,
                version=ref.version,
            )
            if (
                artifact.checksum != pin.get("checksum")
                or compute_checksum(artifact.body) != artifact.checksum
            ):
                raise PublicationError("SOURCE_PUBLICATION_ARTIFACT_CHANGED")
        release = compile_release(
            scenario=scenario,
            refs=refs,
            runtime_version=baseline.runtime_version,
            created_by=str(actor.pk),
            prepared_source_job=job if selection is not None else None,
        )
        if release.manifest["artifacts"] != baseline.manifest["artifacts"]:
            raise PublicationError("SOURCE_PUBLICATION_ARTIFACT_CHANGED")
        evaluation = admit_prepared_evaluation(actor=actor, release=release, source_job=job)
        token = _token(state, baseline, bindings)
        receipt = ScenarioPublication.objects.create(
            public_id=uuid5(job.public_id, f"source-publication:{scenario.pk}"),
            organization_id=organization_id,
            scenario=scenario,
            source_job=job,
            baseline_release=baseline,
            release=release,
            evaluation=evaluation,
            request_checksum=token,
            prepared_checksum=token,
            created_by=str(actor.pk),
        )
        _audit(receipt, actor, "prepared")
        receipts.append(receipt)
    return receipts


@transaction.atomic
def _finish(job_id, organization_id, selection=None):
    set_tenant_context(organization_id)
    Organization.objects.select_for_update(no_key=True).get(pk=organization_id)
    job, actor, scenarios, candidate, index, state = _state(job_id, organization_id, selection)
    receipts = list(
        ScenarioPublication.objects.select_for_update(of=("self",))
        .filter(
            source_job=job,
            organization_id=organization_id,
        )
        .select_related("evaluation", "release")
        .order_by("scenario_id")
    )
    if not receipts or {r.scenario_id for r in receipts} != {s.pk for s in scenarios}:
        raise PublicationError("SOURCE_PUBLICATION_RECEIPTS_INCONSISTENT")
    if all(r.completed_at is not None for r in receipts):
        return
    pinned_sets = EvalDataGeneration.objects.filter(
        organization_id=organization_id,
        evaluation_id__in=[r.evaluation_id for r in receipts],
    ).values_list("document_set_id", flat=True)
    # Stabilize every evaluated generation, including unchanged shared data sets,
    # before revalidating and switching any live pointer.
    list(
        DocumentSet.objects.select_for_update()
        .filter(organization_id=organization_id, pk__in=pinned_sets)
        .order_by("pk")
    )
    for scenario, receipt in zip(scenarios, receipts, strict=True):
        baseline, bindings = _baseline(scenario)
        if receipt.completed_at is not None or receipt.request_checksum != _token(
            state, baseline, bindings
        ):
            raise PublicationError("SOURCE_PUBLICATION_BASELINE_CHANGED")
        evaluation = receipt.evaluation
        if (
            evaluation.status != EvalStatus.PASSED
            or evaluation.total_cases < 1
            or evaluation.passed_cases != evaluation.total_cases
            or evaluation.case_results.filter(passed=True).count() != evaluation.total_cases
        ):
            raise PublicationError("PUBLICATION_EVALUATION_NOT_PASSED")
        validate_prepared_admission(
            evaluation,
            release=receipt.release,
            consumer=evaluation_consumer_for_organization(organization_id),
            _status=EvalStatus.PASSED,
        )
    # _state has reauthorized every impacted release; all replacements commit below.
    if selection is not None:
        from apps.ingestion.source_revisions import _select_source_revision

        _select_source_revision(
            actor=actor,
            source=job.source,
            expected=selection.expected,
            index_id=selection.index_id,
            confirm_active_release_impact=True,
        )
    else:
        promote_staged_index(index, actor=str(actor.pk), confirm_active_release_impact=True)
    for scenario, receipt in zip(scenarios, receipts, strict=True):
        release = promote(release=receipt.release, actor=actor.get_username())
        _assert_release_indexes_served(release)
        activate_scenario(scenario, actor=actor)
        receipt.completed_at = timezone.now()
        receipt.save(update_fields=["completed_at"])
        _audit(receipt, actor, "completed")


def continue_source_publication(*, job_id: int, organization_id: int, selection=None) -> str:
    """Retry one durable intent; completed/failed evaluations never repeat provider work."""
    try:
        receipts = _prepare(job_id, organization_id, selection)
        if all(r.completed_at is not None for r in receipts):
            return "promoted"
        for receipt in receipts:
            evaluation = resume_eval(
                eval_run_id=receipt.evaluation_id, organization_id=organization_id
            )
            if evaluation.status != EvalStatus.PASSED:
                raise PublicationError("PUBLICATION_EVALUATION_NOT_PASSED")
        _finish(job_id, organization_id, selection)
        return "promoted"
    except Exception as exc:
        with transaction.atomic():
            set_tenant_context(organization_id)
            job = StagedIndexBuildJob.objects.filter(
                pk=job_id, organization_id=organization_id
            ).first()
            code = getattr(exc, "code", "PUBLICATION_FAILED")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9_]{1,64}", code):
                code = "PUBLICATION_FAILED"
            record_event(
                actor_type="system",
                actor_id="source-publication",
                organization_id=organization_id,
                action="scenario.publication.blocked",
                outcome="deny",
                reason=code,
                resource_type="ingestion_job",
                resource_id=str(job.public_id) if job else "",
                request_id=job.request_id if job else "",
            )
        raise
