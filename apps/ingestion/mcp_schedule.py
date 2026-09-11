"""Reviewed resource refresh policy on the shared schedule and preparation model."""

from collections.abc import Iterable
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils import timezone

from apps.catalog.models import Scenario
from apps.ingestion.connections import ConnectionError
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.mcp_services import _audited, _lock_org
from apps.ingestion.models import ConnectorSyncSchedule, EmbeddingProfile, OcrProfile, Source
from apps.ingestion.rest_services import (
    RestAuthorizationError,
    RestServiceError,
    configure_sync_schedule,
)
from apps.ingestion.rest_setup_schedule import setup_preparation_policy
from apps.tenancy.services import UserLike, can_manage_documents


def configure_mcp_schedule(
    *,
    actor: UserLike,
    source: Source,
    enabled: bool,
    interval_seconds: int,
    automation_mode: str,
    expected_policy: str = "",
    scenarios: Iterable[Scenario] = (),
) -> ConnectorSyncSchedule:
    def configure() -> ConnectorSyncSchedule:
        _lock_org(source.organization_id)
        if not getattr(settings, "INGESTION_DURABLE_CONNECTOR_JOBS", False):
            raise McpResourceError("MCP_RESOURCE_SCHEDULE_UNAVAILABLE")
        current = (
            Source.objects.select_related("document_set")
            .filter(
                pk=source.pk, organization_id=source.organization_id, connector_type="mcp_resource"
            )
            .first()
        )
        if (
            current is None
            or current.document_set is None
            or not can_manage_documents(
                actor, source.organization_id, document_set=current.document_set
            )
        ):
            raise McpResourceError("MCP_RESOURCE_SCHEDULE_FORBIDDEN")
        if (
            type(enabled) is not bool
            or type(interval_seconds) is not int
            or interval_seconds not in {900, 3600, 21600, 86400, 604800}
            or automation_mode not in {"draft_only", "stage_only", "promote_if_safe"}
        ):
            raise McpResourceError("MCP_RESOURCE_SCHEDULE_INVALID")
        embedding: EmbeddingProfile | None = None
        ocr: OcrProfile | None = None
        previous = ConnectorSyncSchedule.objects.filter(source=current).first()
        if automation_mode in {"stage_only", "promote_if_safe"}:
            if not enabled and previous is not None and previous.automation_mode == automation_mode:
                # Pausing must remain possible when a model grant has been revoked.
                embedding, ocr = previous.embedding_profile, previous.ocr_profile
            else:
                if not expected_policy:
                    raise McpResourceError("MCP_RESOURCE_PREPARATION_REVIEW_REQUIRED")
                policy = setup_preparation_policy(
                    current.document_set, expected=expected_policy, lock=True
                )
                embedding, ocr = policy.embedding_profile, policy.ocr_profile
        return configure_sync_schedule(
            actor=actor,
            source=current,
            enabled=enabled,
            interval_seconds=interval_seconds,
            next_run_at=timezone.now() + timedelta(seconds=interval_seconds),
            automation_mode=automation_mode,
            embedding_profile=embedding,
            ocr_profile=ocr,
            scenarios=scenarios,
        )

    def checked() -> ConnectorSyncSchedule:
        try:
            return configure()
        except (RestServiceError, ConnectionError) as exc:
            raise McpResourceError(exc.code) from exc
        except RestAuthorizationError as exc:
            raise McpResourceError("MCP_RESOURCE_SCHEDULE_FORBIDDEN") from exc
        except (ValidationError, ObjectDoesNotExist) as exc:
            raise McpResourceError("MCP_RESOURCE_SCHEDULE_INVALID") from exc

    return _audited(
        "mcp_resource.schedule.configured", actor, source.organization_id, checked, str(source.pk)
    )
