from django.db import transaction

from apps.catalog.models import ScenarioAlias
from apps.identity.models import Consumer
from apps.retrieval.providers import PgvectorRetrievalProvider
from apps.tenancy.context import set_tenant_context

tag = "smoke-doc-20260716-c"
scenario = ScenarioAlias.objects.get(alias=tag).scenario
release = scenario.releases.get(status="active")
consumer = Consumer.objects.get(subject=f"{tag}-consumer")
with transaction.atomic():
    set_tenant_context(scenario.project.organization_id)
    hits = PgvectorRetrievalProvider().retrieve(
        query="Zümrüt Kütüphanesi hangi saatlerde açık?",
        profile={},
        organization_id=scenario.project.organization_id,
        index_versions=[],
        document_set_version_ids=release.manifest["document_set_versions"],
        consumer_id=consumer.pk,
    )
print({"hit_count": len(hits), "marker_found": any("Zümrüt" in hit.text for hit in hits)})
