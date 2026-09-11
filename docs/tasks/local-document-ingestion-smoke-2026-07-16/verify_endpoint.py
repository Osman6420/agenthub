"""Inspect the completed smoke and retry the live gateway without printing its token."""

import json
import urllib.error
import urllib.request

from apps.catalog.models import ScenarioAlias
from apps.documents.models import DocumentSet, DocumentSetVersion
from apps.identity.models import Consumer
from apps.identity.tokens import create_token
from apps.ingestion.models import IndexVersion
from apps.releases.models import ScenarioRelease

TAG = "smoke-doc-20260716-c"
document_set = DocumentSet.objects.get(logical_id=TAG)
set_version = (
    DocumentSetVersion.objects.filter(document_set=document_set).order_by("-version").first()
)
index = IndexVersion.objects.filter(document_set_version=set_version).order_by("-version").first()
scenario = ScenarioAlias.objects.get(alias=TAG).scenario
release = ScenarioRelease.objects.filter(scenario=scenario).order_by("-id").first()
if set_version is None or index is None or release is None:
    raise RuntimeError("SMOKE_LINEAGE_INCOMPLETE")
consumer = Consumer.objects.get(subject=f"{TAG}-consumer")
_, raw_token = create_token(consumer, f"{TAG}-retry")

request = urllib.request.Request(
    "http://127.0.0.1:8000/v1/query",
    data=json.dumps(
        {"scenario_alias": TAG, "query": "Zümrüt Kütüphanesi hangi saatlerde açık?"}
    ).encode(),
    headers={"Authorization": f"Bearer {raw_token}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed localhost
        status = response.status
        body = json.loads(response.read().decode())
except urllib.error.HTTPError as exc:
    status = exc.code
    body = json.loads(exc.read().decode())

print(
    json.dumps(
        {
            "document_set_id": document_set.pk,
            "document_set_version_id": set_version.pk,
            "set_version_status": set_version.status,
            "index_version_id": index.pk,
            "index_status": index.status,
            "chunk_count": index.chunk_count,
            "scenario_id": scenario.pk,
            "release_id": release.pk,
            "release_status": release.status,
            "manifest_document_set_versions": release.manifest.get("document_set_versions", []),
            "gateway_http_status": status,
            "gateway_error": body.get("error"),
            "gateway_status": body.get("status"),
            "source_count": len(body.get("output", {}).get("sources", [])),
            "fallback_used": body.get("output", {}).get("fallback_used"),
            "answer_mentions_marker": "Zümrüt" in body.get("output", {}).get("answer", ""),
        },
        ensure_ascii=False,
        indent=2,
    )
)
