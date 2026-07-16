"""One-off local smoke. Run through ``manage.py shell``; never persist the printed token."""

import json
import time
import urllib.request

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias, ScenarioType
from apps.documents import services as document_services
from apps.documents.models import DocumentSet, GrantPrincipalType
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.tokens import create_token
from apps.ingestion.embedding_services import grant_embedding_profile, register_embedding_profile
from apps.ingestion.models import EmbeddingProfile, IndexStatus, IndexVersion
from apps.ingestion.staged_build import promote_staged_index
from apps.ingestion.tasks import build_document_set_index_task
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.tenancy.models import Organization

TAG = "smoke-doc-20260716-c"
ACTOR = "admin"
TEXT = (
    "AgentHub smoke doğrulama bilgisi: Zümrüt Kütüphanesi hafta içi saat 09:17 ile 18:43 "
    "arasında açıktır. Bu sentetik metin yalnızca yerel embedding testi içindir."
)

org = Organization.objects.get(slug="demo")
project = AIProject.objects.filter(organization=org).order_by("id").first()
if project is None:
    raise RuntimeError("DEMO_PROJECT_NOT_FOUND")
admin = get_user_model().objects.get(username=ACTOR)

document_set, _ = DocumentSet.objects.get_or_create(
    organization=org,
    logical_id=TAG,
    defaults={"name": "Yerel doküman embedding smoke"},
)

# Exercise the actual authenticated console bulk-upload view and MinIO-backed storage.
client = Client()
client.force_login(admin)
upload = SimpleUploadedFile(f"{TAG}.txt", TEXT.encode("utf-8"), content_type="text/plain")
response = client.post(
    reverse("console:document_set_bulk_upload", args=[document_set.pk]),
    {"uploads": [upload]},
    HTTP_HOST="localhost",
)
if response.status_code != 302:
    raise RuntimeError(f"UPLOAD_HTTP_{response.status_code}")

draft = document_set.versions.filter(status="draft").order_by("-version").first()
if draft is None or not draft.memberships.exists():
    raise RuntimeError("UPLOAD_DRAFT_NOT_CREATED")
published = document_services.publish_document_set_version(set_version=draft, actor=ACTOR)

scenario, _ = Scenario.objects.get_or_create(
    project=project,
    slug=TAG,
    defaults={
        "name": "Yerel doküman embedding smoke",
        "type": ScenarioType.RAG,
        "status": LifecycleStatus.ACTIVE,
    },
)
ScenarioAlias.objects.get_or_create(organization=org, alias=TAG, defaults={"scenario": scenario})
if not scenario.document_set_bindings.filter(document_set=document_set).exists():
    document_services.bind_scenario_document_set(
        scenario=scenario, document_set=document_set, actor=ACTOR
    )

profile = EmbeddingProfile.objects.filter(logical_id=f"{TAG}-embed", revision=1).first()
if profile is None:
    profile = register_embedding_profile(
        actor=admin,
        logical_id=f"{TAG}-embed",
        revision=1,
        provider="openai_compatible",
        scheme="https",
        host="smoke.invalid",
        port=443,
        path="/v1/embeddings",
        model="deterministic-local-smoke",
        secret_ref="secret:local-smoke-unused",  # noqa: S106 - non-secret deterministic stub
        dimensions=64,
        index_type="vector",
        normalize=True,
        distance_metric="cosine",
        timeout_seconds=5,
        max_response_bytes=1000000,
        max_batch_size=16,
    )
grant_embedding_profile(actor=admin, organization=org, embedding_profile=profile)

build_document_set_index_task.apply_async(
    args=[published.pk, profile.pk, org.pk, ACTOR, None], queue="ingestion"
)
index = None
for _ in range(60):
    index = (
        IndexVersion.objects.filter(document_set_version=published, embedding_profile=profile)
        .order_by("-version")
        .first()
    )
    if index is not None and index.status in {IndexStatus.PROMOTABLE, IndexStatus.FAILED}:
        break
    time.sleep(1)
if index is None:
    raise RuntimeError("INDEX_NOT_CREATED")
if index.status != IndexStatus.PROMOTABLE:
    raise RuntimeError(f"INDEX_{index.status}:{index.failure_code}")
promote_staged_index(index, actor=ACTOR)

artifact = create_artifact_version(
    organization=org,
    artifact_type=ArtifactType.INPUT_CONTRACT,
    logical_id=f"{TAG}-input",
    body={
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
        "additionalProperties": True,
    },
    created_by=ACTOR,
)
release = compile_release(
    scenario=scenario,
    refs=[
        ArtifactRef(
            "input_contract", ArtifactType.INPUT_CONTRACT, artifact.logical_id, artifact.version
        )
    ],
    runtime_version="rag:local-smoke",
    created_by=ACTOR,
)
promote_release(release)

consumer, _ = Consumer.objects.get_or_create(
    organization=org,
    subject=f"{TAG}-consumer",
    defaults={"name": "Yerel doküman smoke consumer", "protocol": ConsumerProtocol.REST},
)
ConsumerBinding.objects.get_or_create(
    consumer=consumer, scenario=scenario, defaults={"capabilities": ["query"]}
)
document_services.grant_document_set(
    document_set=document_set,
    principal_type=GrantPrincipalType.CONSUMER,
    principal_ref=str(consumer.pk),
    actor=ACTOR,
)
_, raw_token = create_token(consumer, f"{TAG}-token")

request = urllib.request.Request(
    "http://127.0.0.1:8000/v1/query",
    data=json.dumps(
        {"scenario_alias": TAG, "query": "Zümrüt Kütüphanesi hangi saatlerde açık?"}
    ).encode("utf-8"),
    headers={"Authorization": f"Bearer {raw_token}", "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=20) as http_response:  # noqa: S310 - fixed localhost
    body = json.loads(http_response.read().decode("utf-8"))

print(
    json.dumps(
        {
            "upload_http_status": response.status_code,
            "document_set_id": document_set.pk,
            "document_set_version_id": published.pk,
            "index_version_id": index.pk,
            "index_status": IndexVersion.objects.get(pk=index.pk).status,
            "scenario_id": scenario.pk,
            "scenario_alias": TAG,
            "release_id": release.pk,
            "release_status": type(release).objects.get(pk=release.pk).status,
            "gateway_http_status": http_response.status,
            "gateway_status": body.get("status"),
            "fallback_used": body.get("output", {}).get("fallback_used"),
            "source_count": len(body.get("output", {}).get("sources", [])),
            "answer_mentions_marker": "Zümrüt" in body.get("output", {}).get("answer", ""),
        },
        ensure_ascii=False,
        indent=2,
    )
)
