"""Live consumer/scenario/set authority shared by retrieval and ingestion status."""

from collections.abc import Iterable

from django.db.models import Exists, OuterRef, Q, QuerySet

from apps.catalog.models import ScenarioDataAccessMode
from apps.documents.models import DocumentSetGrant, ScenarioDocumentSetGrant
from apps.identity.models import Consumer

SHARED_DATA_CAPABILITIES = frozenset({"workflow_run", "retrieve_debug", "ingestion_read"})


def live_consumer_scenario_grants(
    *, consumer: Consumer, scenario_ids: Iterable[int]
) -> QuerySet[ScenarioDocumentSetGrant]:
    scope_ids = list(scenario_ids)
    grants = ScenarioDocumentSetGrant.objects.filter(
        organization_id=consumer.organization_id,
        scenario_id__in=scope_ids,
        scenario__organization_id=consumer.organization_id,
        scenario__project__organization_id=consumer.organization_id,
        document_set__organization_id=consumer.organization_id,
        permission="retrieve",
        status="granted",
        revoked_at__isnull=True,
    )
    if not Consumer.objects.filter(
        pk=consumer.pk,
        organization_id=consumer.organization_id,
        status="active",
        organization__status="active",
    ).exists():
        return grants.none()
    direct = DocumentSetGrant.objects.filter(
        organization_id=consumer.organization_id,
        document_set_id=OuterRef("document_set_id"),
        principal_type="consumer",
        principal_ref=str(consumer.pk),
        permission="retrieve",
    )
    # JSON capability containment is not portable to the SQLite browser profile.
    # Examine only this consumer's requested scenarios, never arbitrary client roles.
    shared_scenarios = [
        scenario_id
        for scenario_id, capabilities in consumer.bindings.filter(
            organization_id=consumer.organization_id,
            scenario_id__in=scope_ids,
            status="active",
            scenario__organization_id=consumer.organization_id,
        ).values_list("scenario_id", "capabilities")
        if SHARED_DATA_CAPABILITIES.intersection(capabilities)
    ]
    return grants.alias(has_consumer_grant=Exists(direct)).filter(
        Q(
            scenario__data_access_mode=ScenarioDataAccessMode.CONSUMER_SPECIFIC,
            has_consumer_grant=True,
        )
        | Q(
            scenario__data_access_mode=ScenarioDataAccessMode.SCENARIO_SHARED,
            scenario_id__in=shared_scenarios,
            shared_consumers=True,
            shared_approved_by__isnull=False,
            shared_approved_at__isnull=False,
        )
    )
