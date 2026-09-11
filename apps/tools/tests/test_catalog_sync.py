from __future__ import annotations

from typing import Any

import pytest

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.tenancy.models import Organization
from apps.tools.catalog_sync import (
    MAX_CATALOG_TOOLS,
    CatalogSyncError,
    McpCatalogHttpClient,
    register_catalog_candidate,
    synchronize_catalog,
)
from apps.tools.models import (
    McpCatalogCandidate,
    McpCatalogCandidateStatus,
    McpCatalogSource,
    ToolBinding,
    ToolDefinition,
)


def _resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    return [(2, 1, 6, "", ("93.184.216.34", port))]


class FixtureClient:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self.tools = tools
        self.destination = None
        self.credential = None

    def list_tools(self, *, destination, credential):
        self.destination = destination
        self.credential = credential
        return {"tools": self.tools}


def _tool(name: str = "search", schema: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Synthetic search",
        "inputSchema": schema or {"type": "object", "properties": {"query": {"type": "string"}}},
    }


def _source(org: Organization, name: str = "approved") -> McpCatalogSource:
    return McpCatalogSource.objects.create(
        organization=org,
        name=name,
        destination={
            "scheme": "https",
            "host": "mcp.example.com",
            "path_prefix": "/mcp/search",
        },
        secret_ref="secret:mcp-catalog",  # noqa: S106 - reference marker, not a credential
    )


class SecretFixture:
    def resolve(self, reference: str) -> str:
        assert reference == "secret:mcp-catalog"
        return "synthetic-token"


class ResponseFixture:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, amount: int) -> bytes:
        return self.body


class ConnectionFixture:
    def __init__(self, response: ResponseFixture) -> None:
        self.response = response
        self.request_args: tuple[Any, Any, Any, Any] | None = None

    def request(self, method, url, body=None, headers=None) -> None:
        self.request_args = (method, url, body, headers)

    def getresponse(self):
        return self.response

    def close(self) -> None:
        pass


def test_http_client_uses_bounded_tools_list_envelope() -> None:
    response = ResponseFixture(
        b'{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"search","inputSchema":{"type":"object"}}]}}'
    )
    connection = ConnectionFixture(response)
    client = McpCatalogHttpClient(connection_factory=lambda *args: connection)
    from apps.tools.egress import ValidatedDestination

    result = client.list_tools(
        destination=ValidatedDestination(
            scheme="https",
            host="mcp.example.com",
            port=443,
            path_prefix="/mcp/search",
            ip_addresses=("93.184.216.34",),
        ),
        credential="synthetic-token",
    )
    assert result["tools"][0]["name"] == "search"
    assert connection.request_args is not None
    assert connection.request_args[0:2] == ("POST", "/mcp/search")
    assert b'"method":"tools/list"' in connection.request_args[2]


@pytest.mark.django_db
def test_discovery_only_quarantines_and_audit_is_redacted() -> None:
    org = Organization.objects.create(slug="one", name="One")
    source = _source(org)
    client = FixtureClient([_tool()])
    candidates = synchronize_catalog(
        organization_id=org.id,
        source_id=source.id,
        actor_id="operator",
        client=client,
        dns_resolver=_resolver,
        secret_resolver=SecretFixture(),
    )
    assert candidates[0].status == McpCatalogCandidateStatus.QUARANTINED
    assert client.destination is not None
    assert client.destination.ip_addresses == ("93.184.216.34",)
    assert client.credential == "synthetic-token"
    assert not ToolDefinition.objects.exists()
    assert not ToolBinding.objects.exists()
    assert not ArtifactVersion.objects.exists()
    audit = AuditEvent.objects.get(action="mcp.catalog.synchronized")
    serialized = f"{audit.before}{audit.after}{audit.reason}{audit.resource_id}"
    assert "mcp.example.com" not in serialized
    assert "synthetic-token" not in serialized
    assert "secret:mcp-catalog" not in serialized


@pytest.mark.django_db
def test_cross_tenant_source_and_review_are_hidden() -> None:
    one = Organization.objects.create(slug="one", name="One")
    two = Organization.objects.create(slug="two", name="Two")
    source = _source(one)
    with pytest.raises(CatalogSyncError, match="SOURCE_NOT_FOUND"):
        synchronize_catalog(
            organization_id=two.id,
            source_id=source.id,
            actor_id="operator",
            client=FixtureClient([]),
            dns_resolver=_resolver,
            secret_resolver=SecretFixture(),
        )


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["../escape", "bad name", "x" * 129])
def test_malicious_names_fail_closed(name: str) -> None:
    org = Organization.objects.create(slug="one", name="One")
    source = _source(org)
    with pytest.raises(CatalogSyncError, match="TOOL_NAME_INVALID"):
        synchronize_catalog(
            organization_id=org.id,
            source_id=source.id,
            actor_id="operator",
            client=FixtureClient([_tool(name)]),
            dns_resolver=_resolver,
            secret_resolver=SecretFixture(),
        )
    assert not McpCatalogCandidate.objects.exists()


@pytest.mark.django_db
def test_catalog_explosion_and_dns_rebinding_fail_closed() -> None:
    org = Organization.objects.create(slug="one", name="One")
    source = _source(org)
    with pytest.raises(CatalogSyncError, match="CATALOG_EXPLOSION"):
        synchronize_catalog(
            organization_id=org.id,
            source_id=source.id,
            actor_id="operator",
            client=FixtureClient([_tool(f"t{index}") for index in range(MAX_CATALOG_TOOLS + 1)]),
            dns_resolver=_resolver,
            secret_resolver=SecretFixture(),
        )

    def rebinding(host: str, port: int) -> list[tuple[Any, ...]]:
        return [
            (2, 1, 6, "", ("93.184.216.34", port)),
            (2, 1, 6, "", ("127.0.0.1", port)),
        ]

    with pytest.raises(CatalogSyncError, match="DESTINATION_NOT_PUBLIC"):
        synchronize_catalog(
            organization_id=org.id,
            source_id=source.id,
            actor_id="operator",
            client=FixtureClient([]),
            dns_resolver=rebinding,
            secret_resolver=SecretFixture(),
        )


@pytest.mark.django_db
def test_drift_and_disappearing_tool_never_mutate_registry() -> None:
    org = Organization.objects.create(slug="one", name="One")
    source = _source(org)
    first = synchronize_catalog(
        organization_id=org.id,
        source_id=source.id,
        actor_id="operator",
        client=FixtureClient([_tool()]),
        dns_resolver=_resolver,
        secret_resolver=SecretFixture(),
    )[0]
    second = synchronize_catalog(
        organization_id=org.id,
        source_id=source.id,
        actor_id="operator",
        client=FixtureClient([_tool(schema={"type": "object", "required": ["query"]})]),
        dns_resolver=_resolver,
        secret_resolver=SecretFixture(),
    )[0]
    first.refresh_from_db()
    assert first.status == McpCatalogCandidateStatus.DRIFTED
    assert second.status == McpCatalogCandidateStatus.QUARANTINED
    synchronize_catalog(
        organization_id=org.id,
        source_id=source.id,
        actor_id="operator",
        client=FixtureClient([]),
        dns_resolver=_resolver,
        secret_resolver=SecretFixture(),
    )
    second.refresh_from_db()
    assert second.status == McpCatalogCandidateStatus.MISSING
    assert not ToolDefinition.objects.exists()


@pytest.mark.django_db
def test_exact_review_registers_definition_and_stale_review_denies() -> None:
    org = Organization.objects.create(slug="one", name="One")
    source = _source(org)
    candidate = synchronize_catalog(
        organization_id=org.id,
        source_id=source.id,
        actor_id="operator",
        client=FixtureClient([_tool()]),
        dns_resolver=_resolver,
        secret_resolver=SecretFixture(),
    )[0]
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="mcp_search_in",
        body=candidate.input_schema,
        created_by="reviewer",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="mcp_search_out",
        body={"type": "object"},
        created_by="reviewer",
    )
    definition_body = {
        "api_version": "agenthub/v1",
        "kind": "ToolDefinition",
        "metadata": {"id": "mcp.search", "owner": "platform"},
        "spec": {
            "protocol": "mcp",
            "destination": {
                "scheme": "https",
                "host": "mcp.example.com",
                "path_prefix": "/mcp/search",
            },
            "input_contract_ref": "mcp_search_in:v1",
            "output_contract_ref": "mcp_search_out:v1",
            "risk": "low",
            "side_effecting": False,
            "timeout_seconds": 10,
            "max_response_bytes": 65536,
            "rate_limit_per_minute": 60,
            "allowed_organizations": [org.slug],
        },
    }
    with pytest.raises(CatalogSyncError, match="CANDIDATE_STALE"):
        register_catalog_candidate(
            organization_id=org.id,
            candidate_id=candidate.id,
            expected_checksum="0" * 64,
            definition_logical_id="mcp_search",
            definition_body=definition_body,
            actor_id="reviewer",
        )
    definition = register_catalog_candidate(
        organization_id=org.id,
        candidate_id=candidate.id,
        expected_checksum=candidate.metadata_checksum,
        definition_logical_id="mcp_search",
        definition_body=definition_body,
        actor_id="reviewer",
    )
    assert definition.checksum
    assert not ToolBinding.objects.exists()
    candidate.refresh_from_db()
    assert candidate.registered_definition_id == definition.id
