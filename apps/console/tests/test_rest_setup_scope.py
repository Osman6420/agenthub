"""Scope entry cannot turn metadata visibility into content or connector authority."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.console.rest_setup_entry import ENTRY_KEY, ScopeStep
from apps.documents.models import DocumentSet
from apps.identity.models import (
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibilityAssignment,
)
from apps.ingestion.models import (
    RestSetupDraft,
    Source,
    StagedIndexBuildJob,
    TenantRestPullProfileGrant,
)
from apps.ingestion.rest_services import RestAuthorizationError, RestServiceError
from apps.ingestion.rest_setup_drafts import save_setup_draft
from apps.ingestion.rest_setup_scope import (
    begin_rest_setup,
    can_begin_new_set,
    manageable_setup_sets,
)
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tenancy.services import can_manage_documents

pytestmark = pytest.mark.django_db


@pytest.fixture
def scope_admin(governed_rest, settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    actor, org = governed_rest[1:3]
    membership = OrganizationMembership.objects.get(user=actor, organization=org)
    OrganizationResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        responsibility="organization_administrator",
        assigned_by=governed_rest[0],
    )
    return actor


def begin(setup, **kwargs):
    return begin_rest_setup(
        actor=kwargs.pop("actor", setup[1]),
        organization=kwargs.pop("organization", setup[2]),
        intent=kwargs.pop("intent", uuid4()),
        source_name=kwargs.pop("source_name", "Yeni REST"),
        **kwargs,
    )


def test_existing_manager_starts_private_checkpoint_without_new_authority(governed_rest):
    assert not can_begin_new_set(governed_rest[1], governed_rest[2])
    assert list(manageable_setup_sets(governed_rest[1], governed_rest[2])) == [governed_rest[3]]
    checkpoint = begin(governed_rest, document_set=governed_rest[3])
    assert checkpoint.payload == {"name": "Yeni REST", "step": 1, "mode": "visual"}
    assert DocumentSet.objects.count() == 1 and Source.objects.count() == 1
    assert not StagedIndexBuildJob.objects.exists()


def test_new_set_requires_explicit_management_and_leaves_connection_ungranted(
    governed_rest, scope_admin
):
    with pytest.raises(RestServiceError, match="SCOPE_INVALID"):
        begin(governed_rest, new_set_name="Yeni belgeler")
    intent = uuid4()
    checkpoint = begin(
        governed_rest, intent=intent, new_set_name="Yeni belgeler", manage_new_set=True
    )
    assert (
        begin(governed_rest, intent=intent, new_set_name="Yeni belgeler", manage_new_set=True).pk
        == checkpoint.pk
    )
    assert can_manage_documents(
        scope_admin, governed_rest[2].pk, document_set=checkpoint.document_set
    )
    assert DocumentSet.objects.count() == 2 and RestSetupDraft.objects.count() == 1
    assert (
        DocumentSetResponsibilityAssignment.objects.filter(
            document_set=checkpoint.document_set, responsibility="document_set_manager"
        ).count()
        == 1
    )
    assert not TenantRestPullProfileGrant.objects.filter(
        document_set=checkpoint.document_set
    ).exists()
    assert Source.objects.count() == 1 and not StagedIndexBuildJob.objects.exists()
    assert AuditEvent.objects.filter(
        action="responsibility.document_set.create", outcome="success"
    ).exists()


@pytest.mark.parametrize("actor_kind", ["manager", "metadata", "outsider"])
def test_new_set_denies_non_administrators(governed_rest, actor_kind):
    actor = governed_rest[1]
    if actor_kind != "manager":
        actor = get_user_model().objects.create_user(username=actor_kind)
        if actor_kind == "metadata":
            member = OrganizationMembership.objects.create(
                user=actor, organization=governed_rest[2]
            )
            DocumentSetResponsibilityAssignment.objects.create(
                organization=governed_rest[2],
                membership=member,
                document_set=governed_rest[3],
                responsibility="document_set_metadata_viewer",
                assigned_by=governed_rest[0],
            )
            with pytest.raises(RestAuthorizationError):
                begin(governed_rest, actor=actor, document_set=governed_rest[3])
    with pytest.raises(RestAuthorizationError):
        begin(governed_rest, actor=actor, new_set_name="Forbidden", manage_new_set=True)
    assert DocumentSet.objects.count() == 1 and not RestSetupDraft.objects.exists()


def test_existing_scope_rejects_foreign_disabled_and_revoked_targets(governed_rest):
    other = Organization.objects.create(slug="other-scope", name="Other")
    foreign = DocumentSet.objects.create(organization=other, logical_id="foreign", name="Foreign")
    with pytest.raises(RestAuthorizationError):
        begin(governed_rest, document_set=foreign)
    assignment = DocumentSetResponsibilityAssignment.objects.get(document_set=governed_rest[3])
    assignment.expires_at = timezone.now() - timedelta(seconds=1)
    assignment.save(update_fields=["expires_at"])
    assert not manageable_setup_sets(governed_rest[1], governed_rest[2]).exists()
    with pytest.raises(RestAuthorizationError):
        begin(governed_rest, document_set=governed_rest[3])
    assert not RestSetupDraft.objects.exists()


def test_new_set_and_assignment_rollback_when_private_checkpoint_limit_reached(
    governed_rest, scope_admin
):
    for i in range(5):
        save_setup_draft(
            actor=scope_admin,
            document_set=governed_rest[3],
            intent=uuid4(),
            payload={"name": f"Waiting {i}", "step": 1, "mode": "visual"},
        )
    original_assignments = DocumentSetResponsibilityAssignment.objects.count()
    with pytest.raises(RestServiceError, match="LIMIT"):
        begin(governed_rest, new_set_name="No orphan", manage_new_set=True)
    assert DocumentSet.objects.count() == 1
    assert DocumentSetResponsibilityAssignment.objects.count() == original_assignments
    assert RestSetupDraft.objects.count() == 5


def test_assignment_audit_failure_rolls_back_new_set(governed_rest, scope_admin, monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.identity.assignment_services.record_event", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        begin(governed_rest, new_set_name="No orphan", manage_new_set=True)
    assert DocumentSet.objects.count() == 1 and not RestSetupDraft.objects.exists()
    assert not AuditEvent.objects.filter(
        action="documents.set.create", resource_id__startswith="rest-set-"
    ).exists()


def test_scope_intent_cannot_be_rebound_or_consumed_by_another_user(governed_rest, scope_admin):
    intent = uuid4()
    created = begin(governed_rest, intent=intent, new_set_name="Fixed scope", manage_new_set=True)
    for options in (
        {"new_set_name": "Different", "manage_new_set": True},
        {"document_set": governed_rest[3]},
        {"document_set": created.document_set, "actor": governed_rest[0]},
    ):
        with pytest.raises(RestServiceError, match="SCOPE_CONFLICT"):
            begin(governed_rest, intent=intent, **options)
    assert DocumentSet.objects.count() == 2 and RestSetupDraft.objects.count() == 1


@pytest.fixture
def entry(client, governed_rest, settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    client.force_login(governed_rest[1])
    response = client.get(reverse("console:rest_setup_start"))
    assert response.status_code == 200
    return response.context["entry"], response.context["submission"]


def post(client, entry, values):
    return client.post(
        reverse("console:rest_setup_start"),
        {
            "entry": entry[0],
            "submission": entry[1],
            "source_name": "Yeni REST",
            **values,
        },
    )


def test_entry_existing_set_resumes_named_first_step(client, entry, governed_rest):
    result = post(
        client, entry, {"scope_mode": "existing", "document_set": str(governed_rest[3].public_id)}
    )
    assert result.status_code == 302
    assert client.get(result["Location"]).context["form"]["name"].value() == "Yeni REST"
    assert (
        post(
            client,
            entry,
            {"scope_mode": "existing", "document_set": str(governed_rest[3].public_id)},
        ).status_code
        == 302
    )
    assert RestSetupDraft.objects.count() == 1


def test_entry_new_set_waits_for_platform_grant_and_survives_new_session(
    client, scope_admin, entry
):
    values = {"scope_mode": "new", "new_set_name": "İzin beklenecek set", "manage_new_set": "on"}
    response = post(client, entry, values)
    assert response.status_code == 302
    page = client.get(response["Location"])
    assert "Henüz izin yoksa" in page.content.decode()
    assert not page.context["form"].fields["profile"].queryset.exists()
    checkpoint = RestSetupDraft.objects.get()
    fresh = Client()
    fresh.force_login(scope_admin)
    resumed = fresh.post(
        reverse(
            "console:rest_setup_resume",
            args=[checkpoint.document_set.public_id, checkpoint.public_id],
        )
    )
    assert fresh.get(resumed["Location"]).context["form"]["name"].value() == "Yeni REST"


def test_entry_token_expiry_tampering_cross_actor_and_csrf_are_rejected(
    client, entry, governed_rest
):
    values = {"scope_mode": "existing", "document_set": str(governed_rest[3].public_id)}
    assert post(client, (entry[0], "invalid"), values).status_code == 400
    session = client.session
    session[ENTRY_KEY][entry[0]]["created"] -= 3601
    session.save()
    assert post(client, entry, values).status_code == 400
    client.force_login(governed_rest[0])
    assert post(client, entry, values).status_code == 400
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(governed_rest[1])
    assert strict.post(reverse("console:rest_setup_start"), {}).status_code == 403
    assert not RestSetupDraft.objects.exists()


def test_entry_refuses_grant_fields_and_hides_new_set_from_manager(client, entry, governed_rest):
    page = client.get(reverse("console:rest_setup_start"))
    assert "new_set_name" not in page.context["form"].fields
    assert (
        post(
            client,
            entry,
            {
                "scope_mode": "existing",
                "document_set": str(governed_rest[3].public_id),
                "owner_id": governed_rest[0].pk,
            },
        ).status_code
        == 400
    )
    assert not RestSetupDraft.objects.exists()


def test_entry_choices_are_scoped_searchable_and_bounded(governed_rest):
    org = governed_rest[2]
    DocumentSet.objects.bulk_create(
        [
            DocumentSet(organization=org, logical_id=f"large-{i}", name=f"Set {i:03d}")
            for i in range(105)
        ]
    )
    other = Organization.objects.create(slug="foreign-choice", name="Foreign")
    DocumentSet.objects.create(organization=other, logical_id="foreign", name="Set 104")
    form = ScopeStep(actor=governed_rest[0], organization=org)
    field = form.fields["document_set"]
    assert isinstance(field, forms.ModelChoiceField) and field.queryset is not None
    assert field.queryset.count() == 100
    filtered = ScopeStep(actor=governed_rest[0], organization=org, search="Set 104")
    filtered_field = filtered.fields["document_set"]
    assert (
        isinstance(filtered_field, forms.ModelChoiceField) and filtered_field.queryset is not None
    )
    assert filtered_field.queryset.count() == 1
    assert filtered_field.queryset.get().organization_id == org.pk


def test_entry_direct_url_and_post_deny_metadata_only_actor(client, governed_rest, settings):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    user = get_user_model().objects.create_user(username="metadata-entry")
    member = OrganizationMembership.objects.create(user=user, organization=governed_rest[2])
    DocumentSetResponsibilityAssignment.objects.create(
        organization=governed_rest[2],
        membership=member,
        document_set=governed_rest[3],
        responsibility="document_set_metadata_viewer",
        assigned_by=governed_rest[0],
    )
    client.force_login(user)
    assert "REST belgelerini bağla" not in client.get(reverse("console:documents")).content.decode()
    assert client.get(reverse("console:rest_setup_start")).status_code == 403
    assert client.post(reverse("console:rest_setup_start"), {}).status_code == 403


def test_entry_token_cannot_follow_active_organization_switch(
    client, scope_admin, entry, governed_rest
):
    from apps.console.context import SESSION_KEY as ACTIVE_ORGANIZATION_KEY

    org = Organization.objects.create(slug="switched-entry", name="Switched")
    member = OrganizationMembership.objects.create(user=scope_admin, organization=org)
    OrganizationResponsibilityAssignment.objects.create(
        organization=org,
        membership=member,
        responsibility="organization_administrator",
        assigned_by=scope_admin,
    )
    session = client.session
    session[ACTIVE_ORGANIZATION_KEY] = org.pk
    session.save()
    assert (
        post(
            client,
            entry,
            {"scope_mode": "new", "new_set_name": "Wrong scope", "manage_new_set": "on"},
        ).status_code
        == 400
    )
    assert not RestSetupDraft.objects.exists()


@pytest.mark.parametrize("gate", ["feature", "session"])
def test_entry_link_and_route_require_supported_runtime(client, governed_rest, settings, gate):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = gate != "feature"
    if gate == "session":
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
    client.force_login(governed_rest[1])
    assert "REST belgelerini bağla" not in client.get(reverse("console:documents")).content.decode()
    assert client.get(reverse("console:rest_setup_start")).status_code == 404


def test_non_owner_runtime_creates_only_authorized_set_and_private_checkpoint(
    governed_rest, scope_admin
):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL FORCE RLS")
    from apps.ingestion.vector_store import set_tenant_context

    role = f"scope_entry_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        checkpoint = begin(governed_rest, new_set_name="Runtime scope", manage_new_set=True)
        assert RestSetupDraft.objects.filter(pk=checkpoint.pk).exists()
        assert DocumentSet.objects.filter(pk=checkpoint.document_set_id).exists()
        set_tenant_context(999999)
        assert not RestSetupDraft.objects.filter(pk=checkpoint.pk).exists()
        assert not DocumentSet.objects.filter(pk=checkpoint.document_set_id).exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")


@pytest.mark.django_db(transaction=True)
def test_concurrent_new_set_entry_creates_one_scope_and_checkpoint(governed_rest, scope_admin):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL organization serialization")
    intent = uuid4()

    def run():
        close_old_connections()
        try:
            return begin(
                governed_rest, intent=intent, new_set_name="One scope", manage_new_set=True
            ).pk
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        assert futures[0].result() == futures[1].result()
    assert DocumentSet.objects.count() == 2 and RestSetupDraft.objects.count() == 1
