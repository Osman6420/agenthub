"""Authorization and configuration services for governed REST pull connectors."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.documents.models import DocumentSet, DocumentSetStatus, ScenarioDocumentSetBinding
from apps.ingestion.models import (
    ConnectorSchedulePromotionTarget,
    ConnectorSyncSchedule,
    ConnectorType,
    EmbeddingProfile,
    EmbeddingProfileStatus,
    RestPullAuthMode,
    RestPullContract,
    RestPullContractStatus,
    RestPullMethod,
    RestPullProfile,
    RestPullProfileStatus,
    RestSyncRun,
    RestSyncStatus,
    ScheduleAutomationMode,
    Source,
    SourceStatus,
    TenantEmbeddingProfileGrant,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest_schema import (
    RestContractError,
    canonical_contract_json,
    validate_contract,
    validate_source_inputs,
)
from apps.ingestion.vector_store import set_tenant_context
from apps.tenancy.models import Organization
from apps.tenancy.services import (
    UserLike,
    can_manage_document_set_operations,
    can_manage_documents,
    is_platform_admin,
)
from apps.tools.secrets_resolver import _secret_name
from apps.tools.tool_schema import ToolArtifactError, _validate_public_hostname


class RestAuthorizationError(PermissionError):
    pass


class RestServiceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def register_rest_profile(
    *, actor: UserLike, base_url: str, path_prefix: str, **fields: Any
) -> RestPullProfile:
    actor_id = _actor_id(actor)
    if not is_platform_admin(actor):
        _audit("rest_profile.create", actor_id, Outcome.DENY, reason="PLATFORM_ADMIN_REQUIRED")
        raise RestAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    scheme, host, port, prefix = _canonical_destination(base_url, path_prefix)
    payload = {**fields, "scheme": scheme, "host": host, "port": port, "path_prefix": prefix}
    _validate_profile_fields(payload)
    try:
        with transaction.atomic():
            profile = RestPullProfile.objects.create(created_by=actor_id, **payload)
            _audit(
                "rest_profile.create",
                actor_id,
                Outcome.SUCCESS,
                resource_id=str(profile.public_id),
                after={
                    "logical_id": profile.logical_id,
                    "revision": profile.revision,
                    "method": profile.method,
                    "status": profile.status,
                },
            )
    except IntegrityError as exc:
        raise RestServiceError("REST_PROFILE_CONFLICT") from exc
    return profile


@transaction.atomic
def disable_rest_profile(*, actor: UserLike, rest_profile: RestPullProfile) -> RestPullProfile:
    actor_id = _actor_id(actor)
    if not is_platform_admin(actor):
        _audit(
            "rest_profile.disable",
            actor_id,
            Outcome.DENY,
            resource_id=str(rest_profile.public_id),
            reason="PLATFORM_ADMIN_REQUIRED",
        )
        raise RestAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    locked = RestPullProfile.objects.select_for_update().get(pk=rest_profile.pk)
    if locked.status != RestPullProfileStatus.DISABLED:
        locked.status = RestPullProfileStatus.DISABLED
        locked.save(update_fields=["status"])
        _audit(
            "rest_profile.disable",
            actor_id,
            Outcome.SUCCESS,
            resource_id=str(locked.public_id),
        )
    return locked


def grant_rest_profile(
    *,
    actor: UserLike,
    organization: Organization,
    document_set: DocumentSet,
    rest_profile: RestPullProfile,
) -> TenantRestPullProfileGrant:
    actor_id = _actor_id(actor)
    if not is_platform_admin(actor):
        _audit(
            "rest_profile.grant",
            actor_id,
            Outcome.DENY,
            organization_id=organization.id,
            resource_id=str(rest_profile.public_id),
            reason="PLATFORM_ADMIN_REQUIRED",
        )
        raise RestAuthorizationError("PLATFORM_ADMIN_REQUIRED")
    if document_set.organization_id != organization.id:
        raise RestServiceError("REST_DOCUMENT_SET_TENANT_MISMATCH")
    if rest_profile.status != RestPullProfileStatus.ACTIVE:
        raise RestServiceError("REST_PROFILE_DISABLED")
    with transaction.atomic():
        set_tenant_context(organization.id)
        grant, _ = TenantRestPullProfileGrant.objects.get_or_create(
            organization=organization,
            document_set=document_set,
            rest_profile=rest_profile,
            defaults={"created_by": actor_id},
        )
        _audit(
            "rest_profile.grant",
            actor_id,
            Outcome.SUCCESS,
            organization_id=organization.id,
            resource_id=str(rest_profile.public_id),
            after={"document_set_id": document_set.pk},
        )
    return grant


def create_rest_contract(
    *,
    actor: UserLike,
    organization: Organization,
    document_set: DocumentSet,
    logical_id: str,
    revision: int,
    definition: dict[str, Any],
) -> RestPullContract:
    actor_id = _actor_id(actor)
    if (
        document_set.organization_id != organization.id
        or not can_manage_documents(
            actor, organization.id, document_set=document_set
        )
    ):
        _audit(
            "rest_contract.create",
            actor_id,
            Outcome.DENY,
            organization_id=organization.id,
            reason="SCENARIO_AUTHOR_REQUIRED",
        )
        raise RestAuthorizationError("SCENARIO_AUTHOR_REQUIRED")
    try:
        validate_contract(definition)
    except RestContractError as exc:
        raise RestServiceError(exc.code) from exc
    if not logical_id or len(logical_id) > 128 or revision < 1:
        raise RestServiceError("REST_CONTRACT_IDENTITY_INVALID")
    checksum = hashlib.sha256(canonical_contract_json(definition).encode()).hexdigest()
    try:
        with transaction.atomic():
            set_tenant_context(organization.id)
            contract = RestPullContract.objects.create(
                organization=organization,
                logical_id=logical_id,
                revision=revision,
                definition=definition,
                checksum=checksum,
                created_by=actor_id,
            )
            _audit(
                "rest_contract.create",
                actor_id,
                Outcome.SUCCESS,
                organization_id=organization.id,
                resource_id=str(contract.public_id),
                after={"logical_id": logical_id, "revision": revision, "checksum": checksum},
            )
    except IntegrityError as exc:
        raise RestServiceError("REST_CONTRACT_CONFLICT") from exc
    return contract


def create_rest_source(
    *,
    actor: UserLike,
    organization: Organization,
    document_set: DocumentSet,
    rest_profile: RestPullProfile,
    rest_contract: RestPullContract,
    slug: str,
    name: str,
    inputs: dict[str, Any],
) -> Source:
    actor_id = _actor_id(actor)
    if not can_manage_documents(actor, organization.id, document_set=document_set):
        raise RestAuthorizationError("SCENARIO_AUTHOR_REQUIRED")
    if (
        document_set.organization_id != organization.id
        or rest_contract.organization_id != organization.id
    ):
        raise RestServiceError("REST_SOURCE_TENANT_MISMATCH")
    if document_set.status != DocumentSetStatus.ACTIVE:
        raise RestServiceError("REST_DOCUMENT_SET_DISABLED")
    if rest_profile.status != RestPullProfileStatus.ACTIVE:
        raise RestServiceError("REST_PROFILE_DISABLED")
    try:
        normalized = validate_source_inputs(rest_contract.definition, inputs)
    except RestContractError as exc:
        raise RestServiceError(exc.code) from exc
    with transaction.atomic():
        set_tenant_context(organization.id)
        if not TenantRestPullProfileGrant.objects.filter(
            organization=organization, document_set=document_set, rest_profile=rest_profile
        ).exists():
            raise RestAuthorizationError("REST_PROFILE_NOT_GRANTED")
        source = Source(
            organization=organization,
            slug=slug,
            name=name,
            connector_type=ConnectorType.GENERIC_REST,
            connector_config={"inputs": normalized},
            rest_profile=rest_profile,
            rest_contract=rest_contract,
            document_set=document_set,
            status=SourceStatus.ACTIVE,
        )
        source.full_clean(validate_unique=False, validate_constraints=False)
        try:
            source.save()
        except IntegrityError as exc:
            raise RestServiceError("REST_SOURCE_CONFLICT") from exc
        _audit(
            "rest_source.create",
            actor_id,
            Outcome.SUCCESS,
            organization_id=organization.id,
            resource_id=str(source.pk),
            after={
                "document_set_id": document_set.pk,
                "profile_id": str(rest_profile.public_id),
                "contract_id": str(rest_contract.public_id),
            },
        )
    return source


def create_rest_sync_run(
    *, actor: UserLike, source: Source, max_attempts: int = 3, request_id: str = ""
) -> RestSyncRun:
    actor_id = _actor_id(actor)
    if source.document_set is None or not can_manage_documents(
        actor, source.organization_id, document_set=source.document_set
    ):
        raise RestAuthorizationError("SCENARIO_AUTHOR_REQUIRED")
    if source.connector_type != ConnectorType.GENERIC_REST:
        raise RestServiceError("REST_SOURCE_REQUIRED")
    if not source.is_active or not source.rest_profile_id or not source.rest_contract_id:
        raise RestServiceError("REST_SOURCE_DISABLED_OR_INVALID")
    if source.document_set is None or source.document_set.status != DocumentSetStatus.ACTIVE:
        raise RestServiceError("DOCUMENT_SET_QUARANTINED")
    with transaction.atomic():
        set_tenant_context(source.organization_id)
        if not RestPullProfile.objects.filter(
            pk=source.rest_profile_id, status=RestPullProfileStatus.ACTIVE
        ).exists():
            raise RestServiceError("REST_PROFILE_DISABLED")
        if not RestPullContract.objects.filter(
            pk=source.rest_contract_id, status=RestPullContractStatus.ACTIVE
        ).exists():
            raise RestServiceError("REST_CONTRACT_DISABLED")
        run = RestSyncRun(
            organization_id=source.organization_id,
            source=source,
            rest_profile_id=source.rest_profile_id,
            rest_contract_id=source.rest_contract_id,
            max_attempts=max_attempts,
        )
        run.full_clean()
        run.save()
        _audit(
            "rest_sync.queue",
            actor_id,
            Outcome.SUCCESS,
            organization_id=source.organization_id,
            resource_id=str(run.pk),
            request_id=request_id,
        )
    return run


@transaction.atomic
def mark_rest_dispatch_failed(
    *, run: RestSyncRun, actor: UserLike, request_id: str = ""
) -> RestSyncRun:
    """Close a manual run whose broker dispatch failed; never leave it queued forever."""
    set_tenant_context(run.organization_id)
    locked = RestSyncRun.objects.select_for_update().get(
        pk=run.pk, organization_id=run.organization_id
    )
    if locked.status == RestSyncStatus.QUEUED:
        locked.status = RestSyncStatus.DEAD_LETTER
        locked.error_code = "BROKER_UNAVAILABLE"
        locked.finished_at = timezone.now()
        locked.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
        _audit(
            "rest_sync.dispatch_failed",
            _actor_id(actor),
            Outcome.FAILURE,
            organization_id=locked.organization_id,
            resource_id=str(locked.pk),
            reason="BROKER_UNAVAILABLE",
            request_id=request_id,
        )
    return locked


def configure_sync_schedule(
    *,
    actor: UserLike,
    source: Source,
    interval_seconds: int,
    enabled: bool,
    next_run_at: Any,
    automation_mode: str = ScheduleAutomationMode.DRAFT_ONLY,
    embedding_profile: EmbeddingProfile | None = None,
    scenarios: Iterable[Scenario] = (),
) -> ConnectorSyncSchedule:
    actor_id = _actor_id(actor)
    organization_id = source.organization_id
    targets = list(scenarios)
    if automation_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE:
        if source.document_set is None or not can_manage_document_set_operations(
            actor, source.document_set
        ):
            raise RestAuthorizationError("RELEASE_MANAGER_REQUIRED")
        if not targets:
            raise RestServiceError("PROMOTION_TARGET_REQUIRED")
    else:
        if source.document_set is None or not can_manage_documents(
            actor, organization_id, document_set=source.document_set
        ):
            raise RestAuthorizationError("SCENARIO_AUTHOR_REQUIRED")
        if targets:
            raise RestServiceError("PROMOTION_TARGETS_NOT_ALLOWED")
    if embedding_profile is not None:
        if embedding_profile.status != EmbeddingProfileStatus.ACTIVE:
            raise RestServiceError("EMBEDDING_PROFILE_DISABLED")
        with transaction.atomic():
            set_tenant_context(organization_id)
            if not TenantEmbeddingProfileGrant.objects.filter(
                organization_id=organization_id, embedding_profile=embedding_profile
            ).exists():
                raise RestAuthorizationError("EMBEDDING_PROFILE_NOT_GRANTED")
    for scenario in targets:
        if scenario.project.organization_id != organization_id:
            raise RestServiceError("PROMOTION_TARGET_TENANT_MISMATCH")
        if (
            not source.document_set_id
            or not ScenarioDocumentSetBinding.objects.filter(
                scenario=scenario, document_set_id=source.document_set_id
            ).exists()
        ):
            raise RestServiceError("PROMOTION_TARGET_NOT_BOUND")
    with transaction.atomic():
        set_tenant_context(organization_id)
        schedule, _ = ConnectorSyncSchedule.objects.select_for_update().get_or_create(
            source=source,
            defaults={
                "organization_id": organization_id,
                "next_run_at": next_run_at,
                "configured_by": actor_id,
            },
        )
        schedule.organization_id = organization_id
        schedule.interval_seconds = interval_seconds
        schedule.enabled = enabled
        schedule.next_run_at = next_run_at
        schedule.automation_mode = automation_mode
        schedule.embedding_profile = embedding_profile
        schedule.configured_by = actor_id
        schedule.promotion_approved_by = (
            actor_id if automation_mode == ScheduleAutomationMode.PROMOTE_IF_SAFE else ""
        )
        schedule.full_clean(validate_unique=False, validate_constraints=False)
        schedule.save()
        schedule.promotion_targets.all().delete()
        for scenario in targets:
            target = ConnectorSchedulePromotionTarget(
                organization_id=organization_id,
                schedule=schedule,
                scenario=scenario,
                approved_by=actor_id,
            )
            target.full_clean(validate_unique=False, validate_constraints=False)
            target.save()
        _audit(
            "connector_schedule.configure",
            actor_id,
            Outcome.SUCCESS,
            organization_id=organization_id,
            resource_id=str(schedule.pk),
            after={
                "enabled": enabled,
                "interval_seconds": interval_seconds,
                "automation_mode": automation_mode,
                "target_count": len(targets),
            },
        )
    return schedule


def _canonical_destination(base_url: str, path_prefix: str) -> tuple[str, str, int, str]:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RestServiceError("REST_BASE_URL_INVALID")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RestServiceError("REST_BASE_URL_INVALID")
    try:
        _validate_public_hostname(parsed.hostname)
    except ToolArtifactError as exc:
        raise RestServiceError("REST_HOST_INVALID") from exc
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise RestServiceError("REST_BASE_URL_INVALID") from exc
    if not isinstance(path_prefix, str):
        raise RestServiceError("REST_PATH_PREFIX_INVALID")
    prefix = path_prefix.rstrip("/") or "/"
    if (
        not prefix.startswith("/")
        or len(prefix) > 512
        or "//" in prefix
        or any(char in prefix for char in "\\%?#")
        or any(segment in {".", ".."} for segment in prefix.split("/"))
    ):
        raise RestServiceError("REST_PATH_PREFIX_INVALID")
    return "https", parsed.hostname.lower(), port, prefix


def _validate_profile_fields(fields: dict[str, Any]) -> None:
    logical_id = fields.get("logical_id")
    revision = fields.get("revision")
    if (
        not isinstance(logical_id, str)
        or not logical_id
        or len(logical_id) > 128
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
    ):
        raise RestServiceError("REST_PROFILE_IDENTITY_INVALID")
    if fields.get("method") not in RestPullMethod.values:
        raise RestServiceError("REST_METHOD_INVALID")
    auth_mode = fields.get("auth_mode")
    if auth_mode not in RestPullAuthMode.values:
        raise RestServiceError("REST_AUTH_MODE_INVALID")
    secret_ref = fields.get("secret_ref", "")
    header = fields.get("api_key_header_name", "")
    if auth_mode == RestPullAuthMode.NONE:
        if secret_ref or header:
            raise RestServiceError("REST_AUTH_CONFIG_INVALID")
    else:
        try:
            _secret_name(secret_ref)
        except Exception as exc:
            raise RestServiceError("REST_SECRET_REF_INVALID") from exc
        if auth_mode == RestPullAuthMode.API_KEY_HEADER:
            forbidden = {"authorization", "host", "content-type", "accept", "cookie"}
            if (
                not isinstance(header, str)
                or not header
                or len(header) > 64
                or header.lower() in forbidden
                or not all(c.isalnum() or c == "-" for c in header)
            ):
                raise RestServiceError("REST_API_KEY_HEADER_INVALID")
        elif header:
            raise RestServiceError("REST_AUTH_CONFIG_INVALID")
    bounds = {
        "timeout_seconds": (1, 120),
        "max_response_bytes": (1, 25_000_000),
        "max_total_bytes": (1, 1_000_000_000),
        "max_requests": (1, 10_000),
        "max_items": (1, 100_000),
        "max_pages": (1, 10_000),
        "max_retries": (0, 5),
        "max_decoded_item_bytes": (1, 25_000_000),
    }
    for name, (low, high) in bounds.items():
        value = fields.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise RestServiceError(f"REST_PROFILE_{name.upper()}_INVALID")


def _actor_id(actor: UserLike) -> str:
    return str(getattr(actor, "pk", "anonymous"))


def _audit(
    action: str,
    actor_id: str,
    outcome: str,
    *,
    organization_id: int | None = None,
    resource_id: str = "",
    reason: str = "",
    request_id: str = "",
    after: dict[str, Any] | None = None,
) -> None:
    record_event(
        actor_type=ActorType.USER,
        actor_id=actor_id,
        action=action,
        outcome=outcome,
        organization_id=organization_id,
        resource_type=action.split(".")[0],
        resource_id=resource_id,
        reason=reason,
        request_id=request_id,
        after=after,
    )
