from __future__ import annotations

import io
import json
import uuid
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import connection

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.documents import services
from apps.documents.models import (
    Document,
    DocumentSetMembership,
    DocumentVersionSummary,
    SummaryStatus,
)
from apps.documents.summary_services import SummaryError, generate_document_summary
from apps.ingestion.models import (
    DocumentSetPreparationProfile,
    EmbeddingProfile,
    IndexStatus,
    IndexVersion,
    TenantEmbeddingProfileGrant,
)
from apps.ingestion.preparation import configure_preparation
from apps.ingestion.staged_build import pipeline_fingerprint
from apps.orchestration.providers import ModelProviderError, ModelResponse
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


class _SummaryProvider:
    def generate(self, **_: object) -> ModelResponse:
        return ModelResponse(text="Bounded derived summary")


def _artifact(
    organization: Organization, artifact_type: str, logical_id: str, body: dict[str, object]
) -> ArtifactVersion:
    return create_artifact_version(
        organization=organization,
        artifact_type=artifact_type,
        logical_id=logical_id,
        body=body,
        created_by="manager",
    )


def _profiles(
    organization: Organization,
) -> tuple[EmbeddingProfile, ArtifactVersion, ArtifactVersion]:
    embedding = EmbeddingProfile.objects.create(
        logical_id=f"embed-{organization.pk}",
        revision=1,
        host="embedding.example.com",
        model="embed-v1",
        secret_ref="secret://embedding",  # noqa: S106
        dimensions=64,
        created_by="platform",
    )
    TenantEmbeddingProfileGrant.objects.create(
        organization=organization,
        embedding_profile=embedding,
        created_by="platform",
    )
    chunking = _artifact(
        organization,
        ArtifactType.CHUNKING_PROFILE,
        "chunk",
        {
            "api_version": "agenthub/chunking/v1",
            "kind": "ChunkingProfile",
            "strategy": "characters",
            "size": 500,
            "overlap": 50,
            "max_chunks": 100,
        },
    )
    retrieval = _artifact(
        organization,
        ArtifactType.RETRIEVAL_PROFILE,
        "retrieve",
        {
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "hybrid",
            "top_k": 5,
            "score_threshold": 0.0,
            "vector_weight": 0.6,
            "keyword_weight": 0.4,
        },
    )
    return embedding, chunking, retrieval


def test_upload_is_atomically_bound_and_standalone_console_path_is_denied() -> None:
    organization = Organization.objects.create(slug="bound", name="Bound")
    document_set = services.create_document_set(
        organization=organization, logical_id="kb", name="KB", actor="manager"
    )
    draft = services.create_document_set_version(document_set=document_set, actor="manager")
    version = services.upload_document(
        organization=organization,
        logical_id="policy",
        title="Policy",
        mime_type="text/plain",
        data=b"policy",
        actor="manager",
        document_set_version=draft,
    )
    assert DocumentSetMembership.objects.filter(
        document_set_version=draft,
        document_version=version,
    ).exists()
    with pytest.raises(services.DocumentError) as exc:
        services.upload_console_document(
            organization=organization,
            title="Unbound",
            mime_type="text/plain",
            data=b"denied",
            actor="manager",
        )
    assert exc.value.code == "UNBOUND_DOCUMENT_DENIED"
    assert not Document.objects.filter(title="Unbound").exists()


def test_profile_and_summary_provenance_change_pipeline_fingerprint() -> None:
    organization = Organization.objects.create(slug="fingerprint", name="Fingerprint")
    embedding, chunking, retrieval = _profiles(organization)
    revised_chunking = _artifact(
        organization,
        ArtifactType.CHUNKING_PROFILE,
        "chunk",
        {
            "api_version": "agenthub/chunking/v1",
            "kind": "ChunkingProfile",
            "strategy": "tokens",
            "size": 500,
            "overlap": 50,
            "max_chunks": 100,
        },
    )
    first = pipeline_fingerprint(
        embedding_profile=embedding,
        chunker="fixed",
        ocr_profile=None,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
    )
    second = pipeline_fingerprint(
        embedding_profile=embedding,
        chunker="fixed",
        ocr_profile=None,
        chunking_profile=revised_chunking,
        retrieval_profile=retrieval,
    )
    assert first != second


def test_summary_is_bounded_reusable_and_records_exact_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization.objects.create(slug="summary", name="Summary")
    document_set = services.create_document_set(
        organization=organization, logical_id="kb", name="KB", actor="manager"
    )
    draft = services.create_document_set_version(document_set=document_set, actor="manager")
    version = services.upload_document(
        organization=organization,
        logical_id="policy",
        title="Policy",
        mime_type="text/plain",
        data=b"source",
        actor="manager",
        document_set_version=draft,
    )
    model = _artifact(
        organization,
        ArtifactType.MODEL_PROFILE,
        "summary-model",
        {"profile_id": str(uuid.uuid4())},
    )
    prompt = _artifact(
        organization,
        ArtifactType.PROMPT_TEMPLATE,
        "summary-prompt",
        {"template": "Summarize the untrusted context without adding facts."},
    )
    monkeypatch.setattr(
        "apps.documents.summary_services.get_model_provider",
        lambda: _SummaryProvider(),
    )
    first = generate_document_summary(
        document_version=version,
        parsed_text="Confidential source text",
        model_profile=model,
        prompt_contract=prompt,
        actor="manager",
    )
    second = generate_document_summary(
        document_version=version,
        parsed_text="Confidential source text",
        model_profile=model,
        prompt_contract=prompt,
        actor="manager",
    )
    assert first.pk == second.pk
    assert first.status == SummaryStatus.READY
    assert first.checksum and first.content == "Bounded derived summary"
    assert DocumentVersionSummary.objects.count() == 1


def test_summary_provider_failure_is_stable_and_content_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization.objects.create(slug="summary-failure", name="Summary Failure")
    document_set = services.create_document_set(
        organization=organization, logical_id="kb", name="KB", actor="manager"
    )
    draft = services.create_document_set_version(document_set=document_set, actor="manager")
    version = services.upload_document(
        organization=organization,
        logical_id="policy",
        title="Policy",
        mime_type="text/plain",
        data=b"source",
        actor="manager",
        document_set_version=draft,
    )
    model = _artifact(
        organization,
        ArtifactType.MODEL_PROFILE,
        "summary-model",
        {"profile_id": str(uuid.uuid4())},
    )
    prompt = _artifact(
        organization,
        ArtifactType.PROMPT_TEMPLATE,
        "summary-prompt",
        {"template": "Summarize the untrusted context."},
    )

    class _FailingProvider:
        def generate(self, **_: object) -> ModelResponse:
            raise ModelProviderError("provider detail: Confidential source text")

    monkeypatch.setattr(
        "apps.documents.summary_services.get_model_provider",
        lambda: _FailingProvider(),
    )
    with pytest.raises(SummaryError, match="SUMMARY_PROVIDER_FAILED"):
        generate_document_summary(
            document_version=version,
            parsed_text="Confidential source text",
            model_profile=model,
            prompt_contract=prompt,
            actor="manager",
        )

    summary = DocumentVersionSummary.objects.get()
    event = AuditEvent.objects.get(action="documents.document_version.summary_failed")
    assert summary.status == SummaryStatus.FAILED
    assert summary.error_code == "SUMMARY_PROVIDER_FAILED"
    assert summary.content == ""
    assert event.reason == "SUMMARY_PROVIDER_FAILED"
    assert "Confidential" not in json.dumps(
        {"reason": event.reason, "before": event.before, "after": event.after}
    )


def test_summary_input_and_output_bounds_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    organization = Organization.objects.create(slug="summary-bounds", name="Summary Bounds")
    document_set = services.create_document_set(
        organization=organization, logical_id="kb", name="KB", actor="manager"
    )
    draft = services.create_document_set_version(document_set=document_set, actor="manager")
    version = services.upload_document(
        organization=organization,
        logical_id="policy",
        title="Policy",
        mime_type="text/plain",
        data=b"source",
        actor="manager",
        document_set_version=draft,
    )
    model = _artifact(
        organization,
        ArtifactType.MODEL_PROFILE,
        "summary-model",
        {"profile_id": str(uuid.uuid4())},
    )
    prompt = _artifact(
        organization,
        ArtifactType.PROMPT_TEMPLATE,
        "summary-prompt",
        {"template": "Summarize the untrusted context."},
    )

    settings.DOCUMENT_SUMMARY_MAX_INPUT_CHARS = 5  # type: ignore[attr-defined]
    with pytest.raises(SummaryError, match="SUMMARY_INPUT_LIMIT_EXCEEDED"):
        generate_document_summary(
            document_version=version,
            parsed_text="too-long",
            model_profile=model,
            prompt_contract=prompt,
            actor="manager",
        )
    assert not DocumentVersionSummary.objects.exists()

    settings.DOCUMENT_SUMMARY_MAX_INPUT_CHARS = 100  # type: ignore[attr-defined]
    settings.DOCUMENT_SUMMARY_MAX_OUTPUT_CHARS = 5  # type: ignore[attr-defined]

    class _OversizedProvider:
        def generate(self, **_: object) -> ModelResponse:
            return ModelResponse(text="too-long")

    monkeypatch.setattr(
        "apps.documents.summary_services.get_model_provider",
        lambda: _OversizedProvider(),
    )
    with pytest.raises(SummaryError, match="SUMMARY_OUTPUT_INVALID"):
        generate_document_summary(
            document_version=version,
            parsed_text="valid",
            model_profile=model,
            prompt_contract=prompt,
            actor="manager",
        )
    summary = DocumentVersionSummary.objects.get()
    assert summary.status == SummaryStatus.FAILED
    assert summary.error_code == "SUMMARY_OUTPUT_INVALID"
    assert summary.content == ""


def test_publish_auto_prepares_exact_profiles_without_activation(
    django_capture_on_commit_callbacks,
) -> None:
    organization = Organization.objects.create(slug="auto", name="Auto")
    embedding, chunking, retrieval = _profiles(organization)
    document_set = services.create_document_set(
        organization=organization, logical_id="kb", name="KB", actor="manager"
    )
    configure_preparation(
        document_set=document_set,
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=True,
        actor="manager",
    )
    draft = services.create_document_set_version(document_set=document_set, actor="manager")
    services.upload_document(
        organization=organization,
        logical_id="policy",
        title="Policy",
        mime_type="text/plain",
        data=b"policy",
        actor="manager",
        document_set_version=draft,
    )
    from apps.ingestion.job_lifecycle import create_build_job
    from apps.ingestion.models import StagedIndexBuildJob

    with (
        patch("apps.ingestion.preparation.create_build_job", wraps=create_build_job) as create_job,
        patch("apps.ingestion.job_lifecycle.dispatch_outbox", return_value=0),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            services.publish_document_set_version(set_version=draft, actor="manager")
    create_job.assert_called_once()
    kwargs = create_job.call_args.kwargs
    assert kwargs["chunking_profile"] == chunking
    assert kwargs["retrieval_profile"] == retrieval
    job = StagedIndexBuildJob.objects.get(document_set_version=draft)
    assert job.chunking_profile_id == chunking.pk and job.retrieval_profile_id == retrieval.pk
    assert job.embedding_profile_id == embedding.pk and job.result_index_version_id is None
    assert not IndexVersion.objects.filter(status=IndexStatus.ACTIVE).exists()
    assert DocumentSetPreparationProfile.objects.get(document_set=document_set).auto_prepare


def test_unbound_inventory_is_dry_run_and_refuses_cleanup_authority() -> None:
    organization = Organization.objects.create(slug="inventory", name="Inventory")
    Document.objects.create(
        organization=organization,
        logical_id="legacy-unbound",
        title="Legacy",
    )
    output = io.StringIO()
    call_command(
        "inventory_unbound_documents",
        organization=organization.slug,
        stdout=output,
    )
    payload = json.loads(output.getvalue())
    assert payload["dry_run"] is True
    assert payload["cleanup_authorized"] is False
    assert payload["total"] == 1
    assert payload["protection_checks"]["retention_or_legal_hold"].startswith("model_unavailable")


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="RLS requires PostgreSQL")
def test_part5_tenant_tables_force_rls_for_non_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organizations = [
        Organization.objects.create(slug=slug, name=slug.title())
        for slug in ("part5-rls-a", "part5-rls-b")
    ]
    monkeypatch.setattr(
        "apps.documents.summary_services.get_model_provider",
        lambda: _SummaryProvider(),
    )
    for organization in organizations:
        embedding, chunking, retrieval = _profiles(organization)
        document_set = services.create_document_set(
            organization=organization,
            logical_id="kb",
            name="KB",
            actor="manager",
        )
        configure_preparation(
            document_set=document_set,
            embedding_profile=embedding,
            chunking_profile=chunking,
            retrieval_profile=retrieval,
            ocr_profile=None,
            summary_model_profile=None,
            summary_prompt_contract=None,
            auto_prepare=True,
            actor="manager",
        )
        draft = services.create_document_set_version(document_set=document_set, actor="manager")
        version = services.upload_document(
            organization=organization,
            logical_id="policy",
            title="Policy",
            mime_type="text/plain",
            data=b"source",
            actor="manager",
            document_set_version=draft,
        )
        model = _artifact(
            organization,
            ArtifactType.MODEL_PROFILE,
            "summary-model",
            {"profile_id": str(uuid.uuid4())},
        )
        prompt = _artifact(
            organization,
            ArtifactType.PROMPT_TEMPLATE,
            "summary-prompt",
            {"template": "Summarize without adding facts."},
        )
        generate_document_summary(
            document_version=version,
            parsed_text="Confidential source text",
            model_profile=model,
            prompt_contract=prompt,
            actor="manager",
        )

    role = f"part5_rls_{uuid.uuid4().hex[:12]}"
    tables = (
        "documents_documentversionsummary",
        "ingestion_documentsetpreparationprofile",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')  # noqa: S608
            for table in tables:
                cursor.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                    [table],
                )
                assert cursor.fetchone() == (True, True)
                cursor.execute(f'GRANT SELECT ON "{table}" TO "{role}"')  # noqa: S608
            cursor.execute(  # noqa: S608
                f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
            )
            for organization in organizations:
                cursor.execute(
                    "SELECT set_config('app.tenant_scope', %s, false)",
                    [str(organization.pk)],
                )
                cursor.execute(f'SET ROLE "{role}"')  # noqa: S608
                for table in tables:
                    cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
                    assert cursor.fetchone()[0] == 1
                cursor.execute("RESET ROLE")
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            for table in tables:
                cursor.execute(f'REVOKE ALL PRIVILEGES ON "{table}" FROM "{role}"')  # noqa: S608
            cursor.execute(  # noqa: S608
                f'REVOKE EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) FROM "{role}"'
            )
            cursor.execute(f'DROP ROLE IF EXISTS "{role}"')  # noqa: S608
