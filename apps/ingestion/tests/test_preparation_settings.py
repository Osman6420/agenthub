"""Initial settings, reviewed edits and REST detours without hidden build work."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.audit.models import AuditEvent
from apps.console.profile_fields import profile_defaults
from apps.console.rest_setup_forms import visual_initial
from apps.console.tests.test_rest_setup import advance
from apps.console.tests.test_rest_setup import wizard as wizard
from apps.documents.models import DocumentSet
from apps.documents.tests.test_phase_2_8_part_5 import _profiles
from apps.identity.models import DocumentSetResponsibility, DocumentSetResponsibilityAssignment
from apps.ingestion.models import (
    DocumentSetPreparationProfile,
    EmbeddingProfile,
    OcrProfile,
    RestSetupDraft,
    StagedIndexBuildJob,
    TenantEmbeddingProfileGrant,
    TenantOcrProfileGrant,
)
from apps.ingestion.preparation import configure_preparation
from apps.ingestion.preparation_settings import (
    PreparationSettingsError,
    configuration_token,
    save_preparation_settings,
)
from apps.ingestion.rest_setup_drafts import save_setup_draft
from apps.ingestion.tests.test_rest_pull import _definition
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.context import set_tenant_scope
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def profiles(governed_rest):
    return _profiles(governed_rest[2])


def save(setup, profiles, **overrides):
    return save_preparation_settings(
        **{
            "actor": setup[1],
            "document_set": setup[3],
            "expected": "new",
            "embedding_profile_id": profiles[0].pk,
            "ocr_profile_id": None,
            "chunking_profile_id": None,
            "standard_chunking": profile_defaults("chunking_profile"),
            "auto_prepare": False,
        }
        | overrides
    )


def test_empty_set_can_save_standard_policy_without_versions_jobs_or_grants(
    governed_rest, profiles
):
    setup = governed_rest
    grant_count = TenantEmbeddingProfileGrant.objects.count()
    assert not setup[3].versions.exists()
    policy = save(setup, profiles)
    assert policy.chunking_profile.body == profile_defaults("chunking_profile")
    assert not policy.auto_prepare and policy.retrieval_profile_id is None
    assert not setup[3].versions.exists() and not StagedIndexBuildJob.objects.exists()
    assert TenantEmbeddingProfileGrant.objects.count() == grant_count
    assert AuditEvent.objects.filter(
        action="ingestion.document_set.preparation_configured", outcome="success"
    ).exists()
    same = save(setup, profiles, expected=configuration_token(policy), auto_prepare=True)
    assert same.pk == policy.pk and same.chunking_profile_id == policy.chunking_profile_id
    assert same.auto_prepare and not StagedIndexBuildJob.objects.exists()
    assert (
        ArtifactVersion.objects.filter(logical_id=policy.chunking_profile.logical_id).count() == 1
    )


def test_old_retrieval_reference_is_preserved_and_auto_flag_participates_in_stale_check(
    governed_rest, profiles
):
    embedding, chunking, retrieval = profiles
    old = configure_preparation(
        document_set=governed_rest[3],
        embedding_profile=embedding,
        chunking_profile=chunking,
        retrieval_profile=retrieval,
        ocr_profile=None,
        summary_model_profile=None,
        summary_prompt_contract=None,
        auto_prepare=False,
        actor="fixture",
    )
    expected = configuration_token(old)
    changed = save(
        governed_rest,
        profiles,
        expected=expected,
        auto_prepare=True,
        chunking_profile_id=chunking.pk,
    )
    assert changed.retrieval_profile_id == retrieval.pk
    with pytest.raises(PreparationSettingsError, match="CHANGED"):
        save(governed_rest, profiles, expected=expected, auto_prepare=False)
    changed.refresh_from_db()
    assert changed.auto_prepare


@pytest.mark.parametrize(
    "blocker", ["disabled_model", "grant", "quarantine", "foreign_chunking", "bool"]
)
def test_denied_settings_are_atomic_and_audited(governed_rest, profiles, blocker):
    kwargs: dict[str, object] = {}
    if blocker == "disabled_model":
        EmbeddingProfile.objects.filter(pk=profiles[0].pk).update(status="disabled")
    elif blocker == "grant":
        TenantEmbeddingProfileGrant.objects.filter(embedding_profile=profiles[0]).delete()
    elif blocker == "quarantine":
        DocumentSet.objects.filter(pk=governed_rest[3].pk).update(status="quarantined")
    elif blocker == "foreign_chunking":
        other = Organization.objects.create(slug="foreign-preparation", name="Foreign")
        kwargs["chunking_profile_id"] = _profiles(other)[1].pk
    else:
        kwargs["auto_prepare"] = "true"
    count = ArtifactVersion.objects.count()
    with pytest.raises(PreparationSettingsError):
        save(governed_rest, profiles, **kwargs)
    assert not DocumentSetPreparationProfile.objects.exists()
    assert ArtifactVersion.objects.count() == count and not StagedIndexBuildJob.objects.exists()
    assert AuditEvent.objects.filter(
        action="ingestion.document_set.preparation_configured", outcome="deny"
    ).exists()


def test_success_audit_failure_rolls_back_generated_artifact_and_policy(
    governed_rest, profiles, monkeypatch
):
    count = ArtifactVersion.objects.count()

    def fail(**kwargs):
        raise RuntimeError("synthetic audit persistence failure")

    monkeypatch.setattr("apps.ingestion.preparation.record_event", fail)
    with pytest.raises(RuntimeError, match="audit persistence"):
        save(governed_rest, profiles)
    assert not DocumentSetPreparationProfile.objects.exists()
    assert ArtifactVersion.objects.count() == count


def test_ocr_grant_and_status_rechecked_and_previous_policy_survives_denial(
    governed_rest, profiles
):
    ocr = OcrProfile.objects.create(
        logical_id="initial-ocr",
        revision=1,
        host="ocr.example.com",
        secret_ref=f"secret:synthetic-ocr-{uuid4().hex}",
        created_by="platform",
    )
    with pytest.raises(PreparationSettingsError, match="NOT_GRANTED"):
        save(governed_rest, profiles, ocr_profile_id=ocr.pk)
    grant = TenantOcrProfileGrant.objects.create(
        organization=governed_rest[2],
        ocr_profile=ocr,
        created_by="platform",
    )
    policy = save(governed_rest, profiles, ocr_profile_id=ocr.pk)
    expected = configuration_token(policy)
    OcrProfile.objects.filter(pk=ocr.pk).update(status="disabled")
    with pytest.raises(PreparationSettingsError):
        save(governed_rest, profiles, expected=expected, ocr_profile_id=ocr.pk)
    OcrProfile.objects.filter(pk=ocr.pk).update(status="active")
    grant.delete()
    with pytest.raises(PreparationSettingsError, match="NOT_GRANTED"):
        save(governed_rest, profiles, expected=expected, ocr_profile_id=ocr.pk)
    policy.refresh_from_db()
    assert policy.ocr_profile_id == ocr.pk
    changed = save(governed_rest, profiles, expected=expected, ocr_profile_id=None)
    assert changed.ocr_profile_id is None


def test_nonowner_can_save_scoped_settings_without_catalog_writes(governed_rest, profiles):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL FORCE RLS")
    role = f"initial_prep_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_embeddingprofile, "
            f'ingestion_tenantembeddingprofilegrant FROM "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        policy = save(governed_rest, profiles)
        assert policy.chunking_profile_id
        set_tenant_scope(())
        assert not DocumentSetPreparationProfile.objects.exists()
        assert not ArtifactVersion.objects.filter(pk=policy.chunking_profile_id).exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


def test_settings_form_works_before_first_document_and_requires_csrf(governed_rest, profiles):
    client = Client(enforce_csrf_checks=True)
    client.force_login(governed_rest[1])
    url = reverse("console:document_set_preparation_settings", args=[governed_rest[3].public_id])
    assert client.post(url, {}).status_code == 403
    page = client.get(url)
    assert page.status_code == 200 and page.context["navigation_section"] == "documents"
    assert "Henüz belge eklemeniz gerekmez" in page.content.decode()
    assert page.context["form"]["auto_prepare"].value() is False
    payload = {
        "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        "expected": page.context["form"]["expected"].value(),
        "embedding_profile": str(profiles[0].pk),
    }
    assert client.post(url, payload | {"summary_model_profile": "1"}).status_code == 400
    assert client.post(url, payload).status_code == 302
    assert not StagedIndexBuildJob.objects.exists() and not governed_rest[3].versions.exists()


def test_metadata_and_foreign_members_cannot_configure_or_view_choices(
    client, governed_rest, profiles
):
    actor = get_user_model().objects.create_user("preparation-metadata")
    membership = OrganizationMembership.objects.create(organization=governed_rest[2], user=actor)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=governed_rest[2],
        membership=membership,
        document_set=governed_rest[3],
        responsibility=DocumentSetResponsibility.METADATA_VIEWER,
        assigned_by=governed_rest[1],
    )
    url = reverse("console:document_set_preparation_settings", args=[governed_rest[3].public_id])
    client.force_login(actor)
    assert client.get(url).status_code == client.post(url, {}).status_code == 403
    with pytest.raises(PreparationSettingsError, match="FORBIDDEN"):
        save(governed_rest, profiles, actor=actor)
    detail = client.get(
        reverse("console:document_set_detail_public", args=[governed_rest[3].public_id])
    )
    assert detail.status_code == 200 and url not in detail.content.decode()
    stranger = get_user_model().objects.create_user("preparation-stranger")
    client.force_login(stranger)
    assert client.get(url).status_code == client.post(url, {}).status_code == 404


def test_rest_detour_checkpoints_inputs_and_resumes_same_step(
    client, wizard, governed_rest, profiles
):
    setup = governed_rest
    assert (
        advance(
            client,
            wizard,
            {"name": "Initial prep source", "profile": str(setup[4].rest_profile.public_id)},
        ).status_code
        == 302
    )
    assert advance(client, wizard, visual_initial(_definition())).status_code == 302
    response = advance(
        client,
        wizard,
        {
            "input_dataset": "preserved-value",
            "sync_mode": "periodic",
            "interval_seconds": "3600",
            "preparation_mode": "stage_only",
        },
        action="configure_preparation",
    )
    assert response.status_code == 302
    draft = RestSetupDraft.objects.get(owner=setup[1], document_set=setup[3])
    assert draft.payload["inputs"] == {"dataset": "preserved-value"}
    assert draft.payload["schedule"] == {"interval_seconds": 3600} and draft.payload["step"] == 3
    page = client.get(response.url)
    assert page.status_code == 200
    saved = client.post(
        response.url,
        {
            "embedding_profile": profiles[0].pk,
            "expected": page.context["form"]["expected"].value(),
            "setup": str(draft.public_id),
        },
    )
    assert saved.status_code == 302 and saved.url == wizard
    resumed = client.get(wizard)
    assert resumed.context["step"] == 3 and resumed.context["preparation_policy"] is not None
    assert resumed.context["form"]["input_dataset"].value() == "preserved-value"
    assert resumed.context["form"]["interval_seconds"].value() == 3600
    assert resumed.context["form"]["preparation_mode"].value() == "draft_only"
    assert not StagedIndexBuildJob.objects.exists()


def test_settings_never_accepts_unknown_return_or_other_owners_draft(
    client, wizard, governed_rest, profiles
):
    url = reverse("console:document_set_preparation_settings", args=[governed_rest[3].public_id])
    foreign = save_setup_draft(
        actor=governed_rest[0],
        document_set=governed_rest[3],
        intent=uuid4(),
        expected_revision=0,
        payload={
            "name": "Another owner's setup",
            "step": 3,
            "mode": "visual",
            "profile": str(governed_rest[4].rest_profile.public_id),
            "definition": _definition(),
            "inputs": {"dataset": "docs"},
        },
    )
    assert client.get(url + f"?setup={foreign.public_id}").status_code == 404
    assert client.get(url + f"?setup={uuid4()}").status_code == 404
    assert client.get(url + "?setup=https://example.com").status_code == 404
    assert (
        client.post(
            url,
            {
                "embedding_profile": profiles[0].pk,
                "expected": "new",
                "return_url": "https://example.com",
            },
        ).status_code
        == 400
    )
    assert not DocumentSetPreparationProfile.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_settings_has_one_winner_and_no_partial_artifacts(governed_rest, profiles):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks")

    def attempt():
        close_old_connections()
        try:
            try:
                save(governed_rest, profiles)
                return "saved"
            except PreparationSettingsError as exc:
                return exc.code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result() for future in [pool.submit(attempt), pool.submit(attempt)]]
    assert sorted(outcomes) == ["PREPARATION_SETTINGS_CHANGED", "saved"]
    assert DocumentSetPreparationProfile.objects.count() == 1
    policy = DocumentSetPreparationProfile.objects.get()
    assert (
        ArtifactVersion.objects.filter(logical_id=policy.chunking_profile.logical_id).count() == 1
    )
