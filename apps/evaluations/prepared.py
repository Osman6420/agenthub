"""Authorized, immutable candidate data selection without changing serving pointers."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q

from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.documents.models import DocumentSet, DocumentSetVersion
from apps.documents.retrieve_scope import live_consumer_scenario_grants
from apps.evaluations.models import EvalDataGeneration, EvalRun, EvalStatus
from apps.evaluations.services import EvalError, _admit_eval, evaluation_consumer_for_organization
from apps.identity.scenario_actions import authorize_scenario_action
from apps.ingestion.connector_jobs import _load_run, _validate_inputs
from apps.ingestion.manual_preparation import PREPARATION_ERRORS
from apps.ingestion.models import StagedIndexBuildJob, TenantEmbeddingProfileGrant
from apps.ingestion.rest_setup_schedule import setup_preparation_policy
from apps.ingestion.source_revisions import trusted_versions
from apps.ingestion.staged_build import StagedBuildError
from apps.orchestration.resolver import resolve_bundle
from apps.releases.models import ScenarioRelease
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import can_manage_document_set_operations
from apps.workflows.services import resolve_release_workflow

MAX_GENERATIONS = 200


def _source_proof(job):
    try:
        protocol = _load_run(job)
        _validate_inputs(job, protocol)
        build = job.preparation_job
        candidate = protocol.candidate_set_version
        if (
            job.status != "succeeded"
            or not protocol.snapshot_complete
            or candidate is None
            or build is None
            or build.kind != "index_build"
            or build.status != "succeeded"
            or build.organization_id != job.organization_id
            or build.document_set_version_id != candidate.pk
            or build.result_index_version_id is None
            or candidate.organization_id != job.organization_id
            or candidate.document_set_id != protocol.source.document_set_id
        ):
            raise EvalError("PREPARED_EVALUATION_BUILD_REQUIRED")
        setup_preparation_policy(candidate.document_set, expected=build.pipeline_fingerprint)
        if not TenantEmbeddingProfileGrant.objects.filter(
            organization_id=job.organization_id,
            embedding_profile_id=build.embedding_profile_id,
        ).exists():
            raise EvalError("PREPARED_EVALUATION_PROFILE_DENIED")
        # Only this job's exact candidate source may be non-current during evaluation.
        # Normal serving still requires current revisions; other inactive sources remain denied.
        if not trusted_versions(
            DocumentSetVersion.objects.filter(pk=candidate.pk), allow_source_id=job.source_id
        ).exists():
            raise EvalError("SOURCE_REVISION_NOT_CURRENT")
        return candidate, build.result_index_version
    except (*PREPARATION_ERRORS, StagedBuildError) as exc:
        raise EvalError(exc.code) from None


def _actor(actor_id, release, docset):
    actor = get_user_model().objects.filter(pk=actor_id, is_active=True).first()
    if (
        actor is None
        or not authorize_scenario_action(
            user=actor, scenario=release.scenario, action="test"
        ).allowed
        or not can_manage_document_set_operations(actor, docset)
    ):
        raise EvalError("PREPARED_EVALUATION_DENIED")
    return actor


def _scope(release):
    bundle = resolve_bundle(release)
    if bundle.index_versions:
        # Source-scoped legacy stores cannot be mixed with this document-ACL proof.
        raise EvalError("PREPARED_EVALUATION_DATA_UNSUPPORTED")
    if bundle.data_selection == "active_generation":
        ids = bundle.document_set_ids
        versions = None
    elif bundle.data_selection == "legacy_pinned":
        versions = bundle.document_set_version_ids
        ids = list(
            DocumentSetVersion.objects.filter(
                pk__in=versions,
                organization_id=release.organization_id,
            ).values_list("document_set_id", flat=True)
        )
        if len(ids) != len(versions) or len(set(ids)) != len(ids):
            raise EvalError("PREPARED_EVALUATION_SCOPE_INVALID")
    else:
        raise EvalError("PREPARED_EVALUATION_DATA_UNSUPPORTED")
    if not 1 <= len(ids) <= MAX_GENERATIONS:
        raise EvalError("PREPARED_EVALUATION_SCOPE_INVALID")
    return set(ids), versions


def _ready(version, index):
    if (
        index is None
        or index.document_set_version_id != version.pk
        or index.organization_id != version.organization_id
        or (
            version.built_index_version_id != index.pk
            and not (
                version.status == "promotable"
                and index.status == "promotable"
                and version.built_index_version_id is None
            )
        )
        or version.status not in {"promotable", "active", "superseded"}
        or index.status not in {"promotable", "active", "superseded"}
        or not index.store_ready
        or (index.storage_layout == "shared_v1" and index.storage_state != "sealed")
    ):
        raise EvalError("PREPARED_EVALUATION_GENERATION_NOT_READY")


def _assert_consumer_scope(consumer, release, set_ids):
    if (
        consumer.organization_id != release.organization_id
        or not consumer.is_active
        or consumer.subject != "system:evaluation"
        or not Organization.objects.filter(pk=release.organization_id, status="active").exists()
    ):
        raise EvalError("PREPARED_EVALUATION_CONSUMER_INVALID")
    allowed = set(
        live_consumer_scenario_grants(
            consumer=consumer,
            scenario_ids=[release.scenario_id],
        ).values_list("document_set_id", flat=True)
    )
    if not set_ids <= allowed:
        raise EvalError("PREPARED_EVALUATION_DATA_DENIED")


@transaction.atomic
def _admit_prepared_evaluation(*, actor, release: ScenarioRelease, source_job: StagedIndexBuildJob):
    """Pin exact prepared data and admission audit atomically; perform no provider I/O."""
    org_id = release.organization_id
    set_tenant_context(org_id)
    Organization.objects.select_for_update(no_key=True).get(pk=org_id)
    Scenario.objects.select_for_update(no_key=True).get(
        pk=release.scenario_id, organization_id=org_id
    )
    release = ScenarioRelease.objects.select_related("scenario__project").get(
        pk=release.pk, organization_id=org_id
    )
    job = (
        StagedIndexBuildJob.objects.select_related("preparation_job")
        .filter(
            pk=source_job.pk,
            organization_id=org_id,
        )
        .first()
    )
    if job is None:
        raise EvalError("PREPARED_EVALUATION_SOURCE_NOT_FOUND")
    candidate, candidate_index = _source_proof(job)
    actor = _actor(getattr(actor, "pk", None), release, candidate.document_set)
    graph = resolve_release_workflow(release).compiled_graph
    if any(n["type"] == "subworkflow" for n in graph.get("nodes", [])):
        raise EvalError("PREPARED_EVALUATION_CHILD_UNSUPPORTED")
    set_ids, version_ids = _scope(release)
    if candidate.document_set_id not in set_ids or (
        version_ids is not None and candidate.pk not in version_ids
    ):
        raise EvalError("PREPARED_EVALUATION_SCOPE_INVALID")
    consumer = evaluation_consumer_for_organization(org_id)
    _assert_consumer_scope(consumer, release, set_ids)
    sets = list(
        DocumentSet.objects.select_for_update()
        .filter(
            pk__in=set_ids,
            organization_id=org_id,
            status="active",
        )
        .order_by("pk")
    )
    if len(sets) != len(set_ids):
        raise EvalError("PREPARED_EVALUATION_DATA_DENIED")
    versions = DocumentSetVersion.objects.filter(
        organization_id=org_id,
        document_set_id__in=set_ids - {candidate.document_set_id},
        status="active",
    ).select_related("built_index_version")
    if version_ids is not None:
        versions = versions.filter(pk__in=version_ids)
    pins = [(v, v.built_index_version) for v in versions.order_by("document_set_id")]
    pins.append((candidate, candidate_index))
    if len(pins) != len(set_ids):
        raise EvalError("PREPARED_EVALUATION_GENERATION_NOT_READY")
    for version, index in pins:
        _ready(version, index)
    evaluation, cases = _admit_eval(
        release=release,
        created_by=str(actor.pk),
        prepared_actor=actor,
        prepared_source_job=job,
        generation_count=len(pins),
    )
    if not cases:
        raise EvalError("PREPARED_EVALUATION_CASES_REQUIRED")
    EvalDataGeneration.objects.bulk_create(
        [
            EvalDataGeneration(
                organization_id=org_id,
                evaluation=evaluation,
                document_set_id=v.document_set_id,
                document_set_version=v,
                index_version=i,
            )
            for v, i in pins
        ],
        batch_size=100,
    )
    record_event(
        actor_type="user",
        actor_id=str(actor.pk),
        organization_id=org_id,
        action="eval.prepared.admitted",
        outcome="success",
        resource_type="eval_run",
        resource_id=str(evaluation.pk),
        reason="PREPARED_GENERATIONS_PINNED",
        after={
            "source_job_id": str(job.public_id),
            "release_id": release.pk,
            "generation_count": len(pins),
        },
    )
    return evaluation


def admit_prepared_evaluation(*, actor, release: ScenarioRelease, source_job: StagedIndexBuildJob):
    """Audit admission denials separately; failed admission leaves no data pins."""
    try:
        return _admit_prepared_evaluation(actor=actor, release=release, source_job=source_job)
    except EvalError as exc:
        with transaction.atomic():
            set_tenant_context(release.organization_id)
            record_event(
                actor_type="user",
                actor_id=str(getattr(actor, "pk", "anonymous")),
                organization_id=release.organization_id,
                action="eval.prepared.denied",
                outcome="deny",
                resource_type="scenario_release",
                resource_id=str(release.pk),
                reason=exc.code,
            )
        raise


def validate_prepared_admission(evaluation, *, release, consumer, _status=EvalStatus.PENDING):
    """Re-read all authority; an object or synthetic consumer name alone grants nothing."""
    current = (
        EvalRun.objects.select_related("prepared_source_job__preparation_job")
        .filter(
            pk=evaluation.pk,
            organization_id=release.organization_id,
            release_id=release.pk,
            status=_status,
            prepared_source_job__isnull=False,
        )
        .first()
    )
    if current is None:
        raise EvalError("PREPARED_EVALUATION_UNAVAILABLE")
    candidate, index = _source_proof(current.prepared_source_job)
    _actor(current.prepared_actor_id, release, candidate.document_set)
    set_ids, version_ids = _scope(release)
    _assert_consumer_scope(consumer, release, set_ids)
    pins = list(
        current.data_generations.select_related(
            "document_set", "document_set_version", "index_version"
        ).order_by("document_set_id")[: MAX_GENERATIONS + 1]
    )
    if (
        len(pins) != current.generation_count
        or not pins
        or len(pins) > MAX_GENERATIONS
        or {p.document_set_id for p in pins} != set_ids
        or (
            version_ids is not None
            and {p.document_set_version_id for p in pins} != set(version_ids)
        )
        or not any(
            p.document_set_version_id == candidate.pk and p.index_version_id == index.pk
            for p in pins
        )
    ):
        raise EvalError("PREPARED_EVALUATION_INCOMPLETE")
    for pin in pins:
        if (
            pin.organization_id != release.organization_id
            or pin.document_set.organization_id != release.organization_id
            or pin.document_set.status != "active"
            or pin.document_set_version.document_set_id != pin.document_set_id
        ):
            raise EvalError("PREPARED_EVALUATION_SCOPE_INVALID")
        _ready(pin.document_set_version, pin.index_version)
    return pins


def prepared_run_generations(run):
    """Resolve only a stored Run FK; never accept index ids from workflow input."""
    from apps.workflows.models import Run

    current = (
        Run.objects.select_related("prepared_evaluation", "release__scenario__project", "consumer")
        .filter(
            pk=run.pk,
            organization_id=run.organization_id,
            release_id=run.release_id,
            consumer_id=run.consumer_id,
            prepared_evaluation__isnull=False,
        )
        .first()
    )
    if current is None:
        raise EvalError("PREPARED_EVALUATION_RUN_INVALID")
    return validate_prepared_admission(
        current.prepared_evaluation, release=current.release, consumer=current.consumer
    )


def serving_evaluations(query):
    """Prepared evidence qualifies only after every exact generation is serving."""
    inactive = EvalDataGeneration.objects.filter(evaluation_id=OuterRef("pk")).exclude(
        Q(
            document_set_version__status="active",
            index_version__status="active",
            document_set_version__built_index_version_id=F("index_version_id"),
            index_version__store_ready=True,
        )
        & (
            Q(index_version__storage_layout="legacy")
            | Q(index_version__storage_layout="shared_v1", index_version__storage_state="sealed")
        ),
    )
    return query.annotate(
        _prepared_inactive=Exists(inactive), _pin_count=Count("data_generations")
    ).filter(
        Q(prepared_source_job__isnull=True)
        | Q(
            _prepared_inactive=False,
            generation_count__gte=1,
            generation_count=F("_pin_count"),
            total_cases__gt=0,
            passed_cases=F("total_cases"),
        ),
    )
