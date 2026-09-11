"""Reviewed source configuration changes, isolated staging and atomic writer selection."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.audit.services import record_event
from apps.documents.models import DocumentSet, DocumentSetVersion
from apps.ingestion.confluence import ConfluenceError
from apps.ingestion.connections import ConnectionError
from apps.ingestion.connector_jobs import (
    ConnectorJobError,
    _load_run,
    _validate_inputs,
    source_checksum,
)
from apps.ingestion.job_lifecycle import ACTIVE_STATES, _canonical_checksum
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.models import (
    ConfluenceSyncRun,
    ConnectorSyncSchedule,
    IndexVersion,
    RestPullProfile,
    RestSetupDraft,
    RestSyncRun,
    Source,
    SourceConfigurationRevision,
    StagedIndexBuildJob,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest import RestPullError
from apps.ingestion.rest_schema import RestContractError, validate_contract, validate_source_inputs
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    configure_sync_schedule,
    create_rest_contract,
    create_rest_source,
)
from apps.ingestion.rest_setup_drafts import (
    complete_setup_draft,
    load_setup_draft,
    lock_setup_draft,
)
from apps.ingestion.rest_setup_schedule import (
    preparation_fingerprint,
    setup_preparation_policy,
)
from apps.ingestion.revision_schedule import validate_revision_schedule
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import UserLike, can_manage_document_set_operations, can_manage_documents

REVISION_ERRORS = (
    RestServiceError,
    RestAuthorizationError,
    RestPullError,
    RestContractError,
    ConnectorJobError,
    ConnectionError,
    ConfluenceError,
    McpResourceError,
)

REVISION_SOURCE_TYPES = {"generic_rest", "confluence_dc", "mcp_resource"}


def revision_for(source: Source) -> SourceConfigurationRevision | None:
    return SourceConfigurationRevision.objects.filter(
        organization_id=source.organization_id, source=source
    ).first()


def family_source_ids(source: Source):
    revision = revision_for(source)
    if revision is None:
        return [source.pk]
    return list(
        SourceConfigurationRevision.objects.filter(
            organization_id=source.organization_id, root_source_id=revision.root_source_id
        ).values_list("source_id", flat=True)
    )


def current_source(source: Source) -> Source:
    revision = revision_for(source)
    if revision is None:
        return source
    return (
        SourceConfigurationRevision.objects.select_related("source")
        .get(
            organization_id=source.organization_id,
            root_source_id=revision.root_source_id,
            is_current=True,
        )
        .source
    )


def configuration_token(source: Source) -> str:
    current = current_source(source)
    revision = revision_for(current)
    latest = (
        SourceConfigurationRevision.objects.filter(
            root_source_id=revision.root_source_id if revision else current.pk
        ).aggregate(value=Max("number"))["value"]
        or 1
    )
    schedule = ConnectorSyncSchedule.objects.filter(source=current).first()
    return _canonical_checksum(
        {
            "source": source_checksum(current),
            "status": current.status,
            "name": current.name,
            "latest": latest,
            "schedule": None
            if schedule is None
            else {
                "id": schedule.pk,
                "enabled": schedule.enabled,
                "interval": schedule.interval_seconds,
                "mode": schedule.automation_mode,
                "embedding": schedule.embedding_profile_id,
                "ocr": schedule.ocr_profile_id,
                "targets": list(
                    schedule.promotion_targets.order_by("pk").values_list("scenario_id", flat=True)
                ),
            },
        }
    )


def schedule_for_edit(source: Source) -> dict[str, Any] | None:
    schedule = ConnectorSyncSchedule.objects.filter(source=source).first()
    if schedule is None or not schedule.enabled:
        return None
    if schedule.automation_mode not in {"draft_only", "stage_only", "promote_if_safe"}:
        raise RestServiceError("SOURCE_REVISION_LEGACY_PROMOTION")
    result: dict[str, Any] = {"interval_seconds": schedule.interval_seconds}
    if schedule.automation_mode in {"stage_only", "promote_if_safe"}:
        if source.document_set is None:
            raise RestServiceError("REST_DOCUMENT_SET_DISABLED")
        policy = setup_preparation_policy(source.document_set)
        if (schedule.embedding_profile_id, schedule.ocr_profile_id) != (
            policy.embedding_profile_id,
            policy.ocr_profile_id,
        ):
            raise RestServiceError("REST_SETUP_PREPARATION_CHANGED")
        result["preparation"] = preparation_fingerprint(policy)
    if schedule.automation_mode == "promote_if_safe":
        result["publication_targets"] = list(
            schedule.promotion_targets.order_by("scenario_id").values_list("scenario_id", flat=True)
        )
    validate_revision_schedule(result)
    return result


def _authorize(actor: UserLike, source: Source, *, operate: bool = False) -> Source:
    if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
        raise RestServiceError("SOURCE_REVISION_UNAVAILABLE")
    set_tenant_context(source.organization_id)
    org = Organization.objects.select_for_update(no_key=True).get(pk=source.organization_id)
    source = (
        Source.objects.select_for_update(of=("self",))
        .select_related("document_set", "rest_contract", "rest_profile")
        .get(pk=source.pk, organization_id=org.pk)
    )
    docset = source.document_set
    if docset is None or not can_manage_documents(actor, org.pk, document_set=docset):
        raise RestAuthorizationError("DOCUMENT_SET_MANAGER_REQUIRED")
    if operate and not can_manage_document_set_operations(actor, docset):
        raise RestAuthorizationError("RELEASE_MANAGER_REQUIRED")
    if (
        not org.is_active
        or docset.status != "active"
        or source.connector_type not in REVISION_SOURCE_TYPES
    ):
        raise RestServiceError("SOURCE_REVISION_UNAVAILABLE")
    return source


def _audit(actor, source, action, *, outcome="success", reason="", after=None):
    record_event(
        actor_type="user",
        actor_id=str(getattr(actor, "pk", "anonymous")),
        organization_id=source.organization_id,
        action=f"ingestion.source_revision.{action}",
        outcome=outcome,
        reason=reason,
        resource_type="source",
        resource_id=str(source.pk),
        after=after or {},
    )


def create_rest_revision(
    *,
    actor: UserLike,
    document_set: DocumentSet,
    base_source_id: int,
    expected: str,
    profile_id: UUID,
    intent: UUID,
    name: str,
    definition: dict[str, Any],
    inputs: dict[str, Any],
    schedule: dict[str, Any] | None = None,
    draft_revision: int | None = None,
) -> Source:
    try:
        with transaction.atomic():
            set_tenant_context(document_set.organization_id)
            source = Source.objects.filter(pk=base_source_id, document_set=document_set).first()
            if source is None:
                raise RestServiceError("SOURCE_REVISION_NOT_FOUND")
            source = _authorize(actor, source)
            if source.connector_type != "generic_rest":
                raise RestServiceError("SOURCE_REVISION_UNAVAILABLE")
            if (
                not isinstance(intent, UUID)
                or not isinstance(name, str)
                or not 1 <= len(name) <= 200
            ):
                raise RestServiceError("REST_SETUP_INVALID")
            definition = validate_contract(definition)
            normalized = validate_source_inputs(definition, inputs)
            validate_revision_schedule(schedule)
            if schedule and "preparation" in schedule:
                setup_preparation_policy(document_set, expected=schedule["preparation"], lock=True)
            profile = RestPullProfile.objects.filter(public_id=profile_id, status="active").first()
            if (
                profile is None
                or not TenantRestPullProfileGrant.objects.filter(
                    organization_id=source.organization_id,
                    document_set=document_set,
                    rest_profile=profile,
                ).exists()
            ):
                raise RestAuthorizationError("REST_PROFILE_NOT_GRANTED")
            if definition["request"]["method"] != profile.method:
                raise RestServiceError("REST_PROFILE_METHOD_MISMATCH")
            root_revision = revision_for(source)
            root_id = root_revision.root_source_id if root_revision else source.pk
            existing = (
                SourceConfigurationRevision.objects.select_related("source__rest_contract")
                .filter(root_source_id=root_id, source__slug=f"rest-{intent.hex}")
                .first()
            )
            if existing is not None:
                saved = existing.source
                if (
                    existing.base_token != expected
                    or saved.name != name
                    or saved.rest_profile_id != profile.pk
                    or saved.rest_contract is None
                    or saved.rest_contract.definition != definition
                    or saved.connector_config != {"inputs": normalized}
                    or existing.schedule_config != schedule
                ):
                    raise RestServiceError("REST_SETUP_INTENT_CONFLICT")
                if RestSetupDraft.objects.filter(public_id=intent).exists():
                    receipt = load_setup_draft(
                        actor=actor, document_set=document_set, intent=intent
                    )
                    if receipt.completed_source_id is not None:
                        if receipt.completed_source_id != saved.pk:
                            raise RestServiceError("REST_SETUP_INTENT_CONFLICT")
                        return saved
                draft = lock_setup_draft(
                    actor=actor,
                    document_set=document_set,
                    intent=intent,
                    expected_revision=draft_revision,
                )
                complete_setup_draft(draft, saved, actor)
                return saved
            draft = lock_setup_draft(
                actor=actor,
                document_set=document_set,
                intent=intent,
                expected_revision=draft_revision,
            )
            if expected != configuration_token(source):
                raise RestServiceError("SOURCE_REVISION_CHANGED")
            if root_revision is None:
                root_revision = SourceConfigurationRevision.objects.create(
                    organization_id=source.organization_id,
                    root_source=source,
                    source=source,
                    number=1,
                    checksum=source_checksum(source),
                    is_current=True,
                    schedule_config=schedule_for_edit(source),
                    created_by=str(actor.pk),
                )
            number = (
                SourceConfigurationRevision.objects.filter(root_source_id=root_id).aggregate(
                    value=Max("number")
                )["value"]
                or 1
            ) + 1
            contract = create_rest_contract(
                actor=actor,
                organization=source.organization,
                document_set=document_set,
                logical_id=f"source-{root_id}-configuration",
                revision=number,
                definition=definition,
            )
            candidate = create_rest_source(
                actor=actor,
                organization=source.organization,
                document_set=document_set,
                rest_profile=profile,
                rest_contract=contract,
                slug=f"rest-{intent.hex}",
                name=name,
                inputs=normalized,
            )
            revision = SourceConfigurationRevision.objects.create(
                organization_id=source.organization_id,
                root_source_id=root_id,
                source=candidate,
                number=number,
                checksum=source_checksum(candidate),
                base_token=expected,
                schedule_config=schedule,
                created_by=str(actor.pk),
            )
            complete_setup_draft(draft, candidate, actor)
            _audit(actor, candidate, "created", after={"number": revision.number, "root": root_id})
            return candidate
    except REVISION_ERRORS as exc:
        with transaction.atomic():
            set_tenant_context(document_set.organization_id)
            record_event(
                actor_type="user",
                actor_id=str(getattr(actor, "pk", "anonymous")),
                organization_id=document_set.organization_id,
                action="ingestion.source_revision.created",
                outcome="deny",
                reason=getattr(exc, "code", "SOURCE_REVISION_DENIED"),
                resource_type="document_set",
                resource_id=str(document_set.public_id),
            )
        raise


def assert_revision_sync(source: Source, *, scheduled: bool = False) -> None:
    revision = revision_for(source)
    if revision is not None and revision.checksum != source_checksum(source):
        raise RestServiceError("SOURCE_REVISION_CHECKSUM_CHANGED")
    if revision is not None and (
        not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False)
        or (scheduled and not revision.is_current)
    ):
        raise RestServiceError("SOURCE_REVISION_NOT_CURRENT")


def visible_sources(query):
    return query.filter(
        Q(configuration_revision__isnull=True) | Q(configuration_revision__is_current=True)
    )


def trusted_versions(query, *, allow_source_id: int | None = None):
    inactive = SourceConfigurationRevision.objects.filter(is_current=False)
    if allow_source_id is not None:
        inactive = inactive.exclude(source_id=allow_source_id)
    return query.exclude(
        memberships__document_version__document__source_id__in=inactive.values("source_id")
    )


def assert_serving_revision(set_version: DocumentSetVersion) -> None:
    if not trusted_versions(DocumentSetVersion.objects.filter(pk=set_version.pk)).exists():
        from apps.ingestion.staged_build import StagedBuildError

        raise StagedBuildError("SOURCE_REVISION_NOT_CURRENT")


def revision_diff(source: Source, state: dict[str, Any]) -> list[dict[str, str]]:
    """Bounded, escaped by the template, shown only to the set manager."""
    if source.rest_profile is None or source.rest_contract is None:
        raise RestServiceError("SOURCE_REVISION_UNAVAILABLE")
    before = {
        "Kaynak adı": source.name,
        "Bağlantı": str(source.rest_profile.public_id),
        "Belge alanları": source.rest_contract.definition,
        "Değişkenler": source.connector_config["inputs"],
        "Yenileme planı": schedule_for_edit(source),
    }
    after = dict(
        zip(
            before,
            (
                state.get("name"),
                state.get("profile"),
                state.get("definition"),
                state.get("inputs"),
                state.get("schedule"),
            ),
            strict=True,
        )
    )

    def display(key, value):
        if key == "Yenileme planı":
            label = revision_schedule_label(value)
            previous = before[key] or {}
            proposed = after[key] or {}
            if (
                value is after[key]
                and "preparation" in proposed
                and previous.get("preparation") != proposed["preparation"]
            ):
                label += " · Güncel hazırlama ayarları uygulanır"
            return label
        if key == "Bağlantı":
            profile = RestPullProfile.objects.filter(public_id=value).first()
            return (
                f"{profile.logical_id} · r{profile.revision}"
                if profile
                else "Bağlantı kullanılamıyor"
            )
        if key == "Değişkenler":
            rendered = "\n".join(f"{name}: {item}" for name, item in sorted(value.items()))
        else:
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return rendered if len(rendered) <= 2000 else rendered[:2000] + " … (kısaltıldı)"

    return [
        {
            "field": key,
            "before": display(key, value),
            "after": display(key, after[key]),
        }
        for key, value in before.items()
        if value != after[key]
    ]


def revision_schedule_label(config: dict[str, Any] | None) -> str:
    if config is None:
        return "Elle başlatılır"
    return f"{config['interval_seconds'] // 60} dakikada bir · " + (
        "Testlerden sonra onaylı senaryolarda yayınlanır"
        if "publication_targets" in config
        else "Aramaya hazırlanır"
        if "preparation" in config
        else "Belgeler taslakta tutulur"
    )


def _select_source_revision(
    *,
    actor: UserLike,
    source: Source,
    expected: str,
    index_id: int,
    confirm_active_release_impact: bool = False,
) -> Source:
    """Select the reviewed writer and its exact prepared generation, or change nothing."""
    from apps.ingestion.staged_build import (
        StagedBuildError,
        promote_staged_index,
        rollback_staged_index,
    )

    try:
        with transaction.atomic():
            source = _authorize(actor, source, operate=True)
            if (
                type(index_id) is not int
                or not 0 < index_id <= 9223372036854775807
                or type(confirm_active_release_impact) is not bool
            ):
                raise RestServiceError("SOURCE_REVISION_SELECTION_INVALID")
            if source.document_set is None:
                raise RestServiceError("SOURCE_REVISION_UNAVAILABLE")
            DocumentSet.objects.select_for_update(no_key=True).get(pk=source.document_set.pk)
            revision = revision_for(source)
            if revision is None:
                raise RestServiceError("SOURCE_REVISION_NOT_FOUND")
            current = current_source(source)
            index = IndexVersion.objects.filter(
                pk=index_id,
                organization_id=source.organization_id,
                document_set_version__document_set_id=source.document_set_id,
            ).first()
            if index is None:
                raise RestServiceError("SOURCE_REVISION_BUILD_REQUIRED")
            replay = current.pk == source.pk and index.status == "active"
            if not replay and expected != configuration_token(source):
                raise RestServiceError("SOURCE_REVISION_CHANGED")
            family = family_source_ids(source)
            if (
                StagedIndexBuildJob.objects.filter(
                    Q(source_id__in=family) | Q(source_jobs__source_id__in=family),
                    status__in=ACTIVE_STATES,
                ).exists()
                or RestSyncRun.objects.filter(
                    source_id__in=family, status__in=["queued", "running", "retry"]
                ).exists()
                or ConfluenceSyncRun.objects.filter(
                    source_id__in=family, status__in=["queued", "running", "retry"]
                ).exists()
            ):
                raise RestServiceError("SOURCE_REVISION_BUSY")
            job = (
                StagedIndexBuildJob.objects.select_related("preparation_job")
                .filter(
                    source=source,
                    status="succeeded",
                    preparation_job__status="succeeded",
                    preparation_job__result_index_version=index,
                    preparation_job__document_set_version_id=index.document_set_version_id,
                )
                .first()
            )
            if job is None or job.preparation_job is None:
                raise RestServiceError("SOURCE_REVISION_BUILD_REQUIRED")
            run = _load_run(job)
            _validate_inputs(job, run)
            candidate = run.candidate_set_version
            if (
                not run.snapshot_complete
                or candidate is None
                or candidate.pk != index.document_set_version_id
                or candidate.memberships.filter(
                    document_version__document__deleted_at__isnull=False
                ).exists()
            ):
                raise RestServiceError("SOURCE_REVISION_SNAPSHOT_INVALID")
            policy = setup_preparation_policy(
                source.document_set, expected=job.preparation_job.pipeline_fingerprint, lock=True
            )
            if revision.schedule_config and "preparation" in revision.schedule_config:
                setup_preparation_policy(
                    source.document_set, expected=revision.schedule_config["preparation"], lock=True
                )
            from apps.ingestion.snapshot import latest_trusted_candidate

            baseline = latest_trusted_candidate(source.document_set)
            if baseline is not None and not replay:

                def retained(version):
                    return set(
                        version.memberships.exclude(
                            document_version__document__source_id__in=family
                        ).values_list("document_version_id", flat=True)
                    )

                if retained(baseline) != retained(candidate):
                    raise RestServiceError("SOURCE_REVISION_BASELINE_CHANGED")
            if replay:
                return source
            SourceConfigurationRevision.objects.filter(
                organization_id=source.organization_id,
                root_source_id=revision.root_source_id,
                is_current=True,
            ).update(is_current=False)
            SourceConfigurationRevision.objects.filter(pk=revision.pk).update(is_current=True)
            if index.status == "superseded":
                rollback_staged_index(index, actor=str(actor.pk))
            else:
                promote_staged_index(
                    index,
                    actor=str(actor.pk),
                    confirm_active_release_impact=confirm_active_release_impact,
                )
            # Historical schedule identity/slots remain attached to their source.
            for previous in ConnectorSyncSchedule.objects.filter(source_id__in=family).exclude(
                source=source
            ):
                previous.enabled = False
                previous.save(update_fields=["enabled", "updated_at"])
            config = revision.schedule_config
            if config:
                configure_sync_schedule(
                    actor=actor,
                    source=source,
                    interval_seconds=config["interval_seconds"],
                    enabled=True,
                    next_run_at=timezone.now() + timedelta(seconds=config["interval_seconds"]),
                    automation_mode="promote_if_safe"
                    if "publication_targets" in config
                    else "stage_only"
                    if "preparation" in config
                    else "draft_only",
                    embedding_profile=policy.embedding_profile if "preparation" in config else None,
                    ocr_profile=policy.ocr_profile if "preparation" in config else None,
                    scenarios=_publication_scenarios(actor, source, config),
                )
            else:
                ConnectorSyncSchedule.objects.filter(source=source).update(enabled=False)
            _audit(
                actor,
                source,
                "selected",
                after={
                    "previous_source": current.pk,
                    "number": revision.number,
                    "index": index.pk,
                },
            )
            return source
    except (*REVISION_ERRORS, StagedBuildError) as exc:
        with transaction.atomic():
            set_tenant_context(source.organization_id)
            _audit(
                actor,
                source,
                "selected",
                outcome="deny",
                reason=getattr(exc, "code", "SOURCE_REVISION_DENIED"),
            )
        raise


def _publication_scenarios(actor, source, config):
    from apps.catalog.models import Scenario
    from apps.identity.scenario_actions import authorize_scenario_action

    ids = config.get("publication_targets", [])
    scenarios = list(
        Scenario.objects.filter(pk__in=ids, organization_id=source.organization_id)
        .select_related("project", "organization")
        .order_by("pk")
    )
    if len(scenarios) != len(ids) or any(
        not all(
            authorize_scenario_action(user=actor, scenario=s, action=a).allowed
            for a in ("test", "release")
        )
        for s in scenarios
    ):
        raise RestServiceError("SOURCE_REVISION_PUBLICATION_DENIED")
    return scenarios


def select_source_revision(
    *, actor, source, expected, index_id, confirm_active_release_impact=False
):
    from apps.releases.revision_publication import publish_revision

    revision = revision_for(source)
    if revision and revision.schedule_config and "publication_targets" in revision.schedule_config:
        return publish_revision(actor=actor, source=source, expected=expected, index_id=index_id)
    return _select_source_revision(
        actor=actor,
        source=source,
        expected=expected,
        index_id=index_id,
        confirm_active_release_impact=confirm_active_release_impact,
    )
