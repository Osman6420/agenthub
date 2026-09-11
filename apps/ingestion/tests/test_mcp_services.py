"""Resource catalog grants, immutable lineage and live source authorization."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, ProgrammingError, connection, transaction

from apps.audit.models import AuditEvent
from apps.documents.models import DocumentSet
from apps.ingestion.connections import verify_connection
from apps.ingestion.mcp_resources import McpResourceError
from apps.ingestion.mcp_services import (
    create_mcp_resource_source,
    disable_mcp_resource_profile,
    register_mcp_resource_profile,
    set_mcp_resource_grant,
    validate_mcp_source,
)
from apps.ingestion.models import Connection, McpResourceProfile, Source, TenantMcpResourceGrant
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.context import set_tenant_context, set_tenant_scope
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


def profile_fields():
    return {
        "logical_id": "mcp-knowledge",
        "revision": 1,
        "protocol_version": "2025-06-18",
        "destination": {
            "scheme": "https",
            "host": "mcp.example.com",
            "path_prefix": "/mcp",
            "port": 443,
        },
        "resource_prefixes": ["file:///kb/"],
        "mime_types": ["text/plain"],
        "limits": {},
        "secret_ref": "secret:synthetic-resource-reader",
    }


@pytest.fixture
def setup(governed_rest):
    platform, author, org, docset, _ = governed_rest
    profile = register_mcp_resource_profile(actor=platform, **profile_fields())
    grant = set_mcp_resource_grant(
        actor=platform, organization=org, document_set=docset, profile=profile, enabled=True
    )
    return platform, author, org, docset, profile, grant


def create(setup, **overrides):
    _, author, org, docset, profile, _ = setup
    return create_mcp_resource_source(
        **(
            {
                "actor": author,
                "organization": org,
                "document_set": docset,
                "profile": profile,
                "slug": "mcp-source",
                "name": "Resource documents",
                "resource_prefixes": ["file:///kb/manuals/"],
            }
            | overrides
        )
    )


def test_exact_resource_identity_source_and_scope(setup):
    *_, profile, grant = setup
    source = create(setup)
    current, resolved = validate_mcp_source(source)
    assert resolved.pk == profile.pk and current.pk == source.pk
    assert source.connection.mcp_resource_profile_id == profile.pk
    assert source.rest_profile_id is None and source.confluence_profile_id is None
    assert verify_connection(source.connection).pk == profile.pk
    assert grant.enabled
    event = AuditEvent.objects.get(action="mcp_resource.source.created")
    assert event.resource_id == str(source.pk)
    assert "mcp.example.com" not in str(event.after) and "secret:" not in str(event.after)


def test_source_creation_never_infers_resource_permission_from_other_connector_grants(setup):
    platform, _, org, docset, profile, _ = setup
    set_mcp_resource_grant(
        actor=platform, organization=org, document_set=docset, profile=profile, enabled=False
    )
    with pytest.raises(McpResourceError, match="NOT_GRANTED"):
        create(setup)
    assert not Source.objects.filter(connector_type="mcp_resource").exists()
    assert AuditEvent.objects.get(action="mcp_resource.source.created").outcome == "deny"


def test_resource_grant_and_profile_revocation_apply_to_previously_loaded_source(setup):
    platform, _, org, docset, profile, grant = setup
    source = create(setup)
    set_mcp_resource_grant(
        actor=platform, organization=org, document_set=docset, profile=profile, enabled=False
    )
    with pytest.raises(McpResourceError, match="NOT_GRANTED"):
        validate_mcp_source(source)
    renewed = set_mcp_resource_grant(
        actor=platform, organization=org, document_set=docset, profile=profile, enabled=True
    )
    assert renewed.pk == grant.pk and renewed.created_by == grant.created_by
    disable_mcp_resource_profile(actor=platform, profile=profile)
    with pytest.raises(McpResourceError, match="PROFILE_DISABLED"):
        validate_mcp_source(source)


@pytest.mark.parametrize(
    "prefixes", [["file:///private/"], ["file:///kb/../private/"], ["file:///kb"]]
)
def test_source_cannot_expand_platform_scope(setup, prefixes):
    with pytest.raises(McpResourceError):
        create(setup, resource_prefixes=prefixes)
    assert not Source.objects.filter(connector_type="mcp_resource").exists()


def test_platform_admin_and_exact_data_manager_are_separate_checks(setup):
    _, author, org, docset, profile, _ = setup
    with pytest.raises(McpResourceError, match="PLATFORM_ADMIN_REQUIRED"):
        register_mcp_resource_profile(actor=author, **(profile_fields() | {"revision": 2}))
    with pytest.raises(McpResourceError, match="PLATFORM_ADMIN_REQUIRED"):
        set_mcp_resource_grant(
            actor=author, organization=org, document_set=docset, profile=profile, enabled=False
        )
    stranger = get_user_model().objects.create_user("resource-stranger")
    with pytest.raises(McpResourceError, match="SOURCE_FORBIDDEN"):
        create(setup, actor=stranger)
    assert TenantMcpResourceGrant.objects.get(pk=setup[-1].pk).enabled
    assert (
        AuditEvent.objects.filter(action__startswith="mcp_resource.", outcome="deny").count() == 3
    )


def test_cross_tenant_and_other_collection_are_rejected(setup):
    platform, _, org, _, profile, _ = setup
    other = Organization.objects.create(slug="other-mcp", name="Other")
    docset = DocumentSet.objects.create(organization=other, logical_id="other", name="Other")
    with pytest.raises(McpResourceError, match="GRANT_SCOPE_INVALID"):
        set_mcp_resource_grant(
            actor=platform, organization=org, document_set=docset, profile=profile, enabled=True
        )
    with pytest.raises(McpResourceError, match="SOURCE_FORBIDDEN"):
        create(setup, document_set=docset)
    same_org = DocumentSet.objects.create(organization=org, logical_id="other", name="Other")
    with pytest.raises(McpResourceError, match="SOURCE_FORBIDDEN"):
        create(setup, document_set=same_org)


def test_required_audit_failure_rolls_back_catalog_and_source(setup, monkeypatch):
    platform = setup[0]

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.ingestion.mcp_services.record_event", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        register_mcp_resource_profile(actor=platform, **(profile_fields() | {"revision": 2}))
    assert not McpResourceProfile.objects.filter(revision=2).exists()
    assert not Connection.objects.filter(kind="mcp_resource", revision=2).exists()
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create(setup)
    assert not Source.objects.filter(connector_type="mcp_resource").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"tools": True},
        {"secret_ref": "raw-credential"},
        {"limits": {"retry": 3}},
        {"limits": {"max_items": True}},
        {"protocol_version": "future"},
        {"destination": {"scheme": "https", "host": "127.0.0.1"}},
        {"destination": {"scheme": "https", "host": "mcp.example.com", "port": True}},
        {"mime_types": [["text/plain"]]},
    ],
)
def test_closed_profile_rejects_unreviewed_authority_and_invalid_limits(governed_rest, change):
    with pytest.raises(McpResourceError):
        register_mcp_resource_profile(actor=governed_rest[0], **(profile_fields() | change))
    assert not McpResourceProfile.objects.exists()


def test_sql_rejects_catalog_grant_and_source_lineage_mutation(setup):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL immutable lineage guards")
    source = create(setup)
    *_, profile, grant = setup
    with pytest.raises(OperationalError, match="PROFILE_IMMUTABLE"), transaction.atomic():
        McpResourceProfile.objects.filter(pk=profile.pk).update(destination={})
    with pytest.raises(OperationalError, match="GRANT_IMMUTABLE"), transaction.atomic():
        TenantMcpResourceGrant.objects.filter(pk=grant.pk).update(created_by="other")
    with pytest.raises(OperationalError, match="BINDING_IMMUTABLE"), transaction.atomic():
        Source.objects.filter(pk=source.pk).update(connection=None)
    other = Organization.objects.create(slug="foreign-mcp", name="Foreign")
    foreign = DocumentSet.objects.create(organization=other, logical_id="foreign", name="Foreign")
    with pytest.raises(IntegrityError, match="GRANT_SCOPE_INVALID"), transaction.atomic():
        TenantMcpResourceGrant.objects.create(
            organization=setup[2], document_set=foreign, profile=profile, created_by="test"
        )


def test_non_owner_runtime_reads_catalog_and_exact_rls_grant_without_catalog_write(setup):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL RLS and least-privilege role")
    role = f"mcp_reader_{uuid4().hex[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS NOLOGIN')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(
            f'GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO "{role}"'
        )
        cursor.execute(
            "REVOKE INSERT, UPDATE ON ingestion_mcpresourceprofile, ingestion_connection, "
            f'ingestion_tenantmcpresourcegrant FROM "{role}"'
        )
        cursor.execute(f'SET LOCAL ROLE "{role}"')
    try:
        set_tenant_context(setup[2].pk)
        source = create(setup)
        assert validate_mcp_source(source)[1].pk == setup[-2].pk
        with pytest.raises(ProgrammingError, match="permission denied"), transaction.atomic():
            TenantMcpResourceGrant.objects.filter(pk=setup[-1].pk).update(enabled=False)
        set_tenant_context(999999)
        assert not TenantMcpResourceGrant.objects.exists()
        assert not Source.objects.filter(pk=source.pk).exists()
        set_tenant_scope(())
        assert not TenantMcpResourceGrant.objects.exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
