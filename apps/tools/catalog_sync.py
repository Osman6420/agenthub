"""Bounded, quarantine-first MCP catalog discovery and exact review."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import jsonschema
from django.db import transaction

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import canonical_json, compute_checksum
from apps.audit.models import ActorType, Outcome
from apps.audit.services import record_event
from apps.tools.adapters import ToolAdapterRequest
from apps.tools.egress import DnsResolver, ValidatedDestination, validate_destination
from apps.tools.http_adapter import ConnectionFactory, perform_https_post
from apps.tools.models import (
    McpCatalogCandidate,
    McpCatalogCandidateStatus,
    McpCatalogSource,
    McpCatalogSourceStatus,
)
from apps.tools.secrets_resolver import SecretResolver
from apps.tools.services import register_tool_definition

MAX_CATALOG_TOOLS = 100
MAX_CATALOG_BYTES = 512_000
MAX_SCHEMA_BYTES = 64_000
MAX_SCHEMA_NODES = 2_000
MAX_SCHEMA_DEPTH = 24
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CatalogSyncError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CatalogClient(Protocol):
    def list_tools(
        self, *, destination: ValidatedDestination, credential: str | None
    ) -> dict[str, Any]: ...


class McpCatalogHttpClient:
    """Redirect-free, pinned-IP JSON-RPC `tools/list` client."""

    def __init__(self, *, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def list_tools(
        self, *, destination: ValidatedDestination, credential: str | None
    ) -> dict[str, Any]:
        headers = {
            "Host": destination.host,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        request = ToolAdapterRequest(
            protocol="mcp",
            method="POST",
            destination=destination,
            payload={},
            credential=None,
            timeout_seconds=15,
            max_response_bytes=MAX_CATALOG_BYTES,
        )
        envelope = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        try:
            raw = perform_https_post(
                self._factory,
                request,
                path=destination.path_prefix or "/",
                headers=headers,
                body=json.dumps(envelope, separators=(",", ":")).encode(),
            )
            payload = json.loads(raw.decode())
        except Exception as exc:
            raise CatalogSyncError(getattr(exc, "code", "CATALOG_UPSTREAM_FAILED")) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("jsonrpc") != "2.0"
            or payload.get("id") != 1
            or "error" in payload
            or not isinstance(payload.get("result"), dict)
        ):
            raise CatalogSyncError("CATALOG_RPC_INVALID")
        return payload["result"]


@transaction.atomic
def synchronize_catalog(
    *,
    organization_id: int,
    source_id: int,
    actor_id: str,
    client: CatalogClient,
    dns_resolver: DnsResolver | None = None,
    secret_resolver: SecretResolver | None = None,
) -> tuple[McpCatalogCandidate, ...]:
    source = (
        McpCatalogSource.objects.select_for_update()
        .filter(id=source_id, organization_id=organization_id)
        .first()
    )
    if source is None:
        raise CatalogSyncError("SOURCE_NOT_FOUND")
    if source.status != McpCatalogSourceStatus.ACTIVE:
        raise CatalogSyncError("SOURCE_DISABLED")
    try:
        destination = validate_destination(source.destination, resolver=dns_resolver)
    except Exception as exc:
        raise CatalogSyncError(getattr(exc, "code", "DESTINATION_DENIED")) from exc
    credential = None
    if source.secret_ref:
        if secret_resolver is None:
            raise CatalogSyncError("SECRET_RESOLVER_REQUIRED")
        try:
            credential = secret_resolver.resolve(source.secret_ref)
        except Exception as exc:
            raise CatalogSyncError(getattr(exc, "code", "SECRET_RESOLUTION_FAILED")) from exc
    payload = client.list_tools(destination=destination, credential=credential)
    tools = _validate_catalog(payload)
    generation = source.generation + 1
    observed_names: set[str] = set()
    created: list[McpCatalogCandidate] = []
    for tool in tools:
        name = tool["name"]
        observed_names.add(name)
        metadata = {
            "name": name,
            "description": tool.get("description", ""),
            "inputSchema": tool["inputSchema"],
        }
        checksum = compute_checksum(metadata)
        previous = (
            McpCatalogCandidate.objects.filter(source=source, remote_name=name)
            .order_by("-generation", "-id")
            .first()
        )
        candidate, _ = McpCatalogCandidate.objects.get_or_create(
            source=source,
            remote_name=name,
            metadata_checksum=checksum,
            defaults={
                "organization_id": organization_id,
                "description": metadata["description"],
                "input_schema": metadata["inputSchema"],
                "source_destination_checksum": compute_checksum(source.destination),
                "generation": generation,
            },
        )
        if previous is not None and previous.metadata_checksum != checksum:
            previous.status = McpCatalogCandidateStatus.DRIFTED
            previous.save(update_fields=["status", "updated_at"])
            _audit(source, actor_id, "mcp.catalog.drift", previous.id, "METADATA_CHANGED")
        created.append(candidate)
    stale = McpCatalogCandidate.objects.filter(
        source=source,
        status__in=[
            McpCatalogCandidateStatus.QUARANTINED,
            McpCatalogCandidateStatus.REGISTERED,
        ],
    ).exclude(remote_name__in=observed_names)
    for candidate in stale:
        candidate.status = McpCatalogCandidateStatus.MISSING
        candidate.save(update_fields=["status", "updated_at"])
        _audit(source, actor_id, "mcp.catalog.missing", candidate.id, "TOOL_DISAPPEARED")
    source.generation = generation
    source.save(update_fields=["generation", "updated_at"])
    _audit(source, actor_id, "mcp.catalog.synchronized", source.id, "QUARANTINED")
    return tuple(created)


@transaction.atomic
def register_catalog_candidate(
    *,
    organization_id: int,
    candidate_id: int,
    expected_checksum: str,
    definition_logical_id: str,
    definition_body: dict[str, Any],
    actor_id: str,
):
    candidate = (
        McpCatalogCandidate.objects.select_for_update()
        .select_related("source", "organization")
        .filter(id=candidate_id, organization_id=organization_id)
        .first()
    )
    if candidate is None:
        raise CatalogSyncError("CANDIDATE_NOT_FOUND")
    if candidate.status != McpCatalogCandidateStatus.QUARANTINED:
        raise CatalogSyncError("CANDIDATE_NOT_REVIEWABLE")
    if candidate.metadata_checksum != expected_checksum:
        raise CatalogSyncError("CANDIDATE_STALE")
    if candidate.source_destination_checksum != compute_checksum(candidate.source.destination):
        raise CatalogSyncError("SOURCE_DRIFTED")
    spec = definition_body.get("spec")
    if not isinstance(spec, dict) or spec.get("protocol") != "mcp":
        raise CatalogSyncError("DEFINITION_NOT_MCP")
    destination = spec.get("destination")
    if destination != candidate.source.destination:
        raise CatalogSyncError("DESTINATION_MISMATCH")
    path = destination.get("path_prefix", "") if isinstance(destination, dict) else ""
    if path.rstrip("/").rsplit("/", 1)[-1] != candidate.remote_name:
        raise CatalogSyncError("REMOTE_NAME_MISMATCH")
    input_ref = spec.get("input_contract_ref")
    contract = _resolve_contract_body(organization_id, input_ref)
    if contract != candidate.input_schema:
        raise CatalogSyncError("INPUT_SCHEMA_MISMATCH")
    artifact = create_artifact_version(
        organization=candidate.organization,
        artifact_type=ArtifactType.TOOL_DEFINITION,
        logical_id=definition_logical_id,
        body=definition_body,
        created_by=actor_id,
    )
    definition = register_tool_definition(artifact=artifact)
    candidate.status = McpCatalogCandidateStatus.REGISTERED
    candidate.registered_definition = definition
    candidate.reviewed_by = actor_id
    candidate.save(update_fields=["status", "registered_definition", "reviewed_by", "updated_at"])
    _audit(candidate.source, actor_id, "mcp.catalog.registered", candidate.id, "EXACT_REVIEW")
    return definition


def _resolve_contract_body(organization_id: int, ref: Any) -> dict[str, Any]:
    from apps.artifacts.models import ArtifactVersion

    if not isinstance(ref, str) or ":v" not in ref:
        raise CatalogSyncError("INPUT_CONTRACT_UNRESOLVED")
    logical_id, _, version = ref.rpartition(":v")
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type=ArtifactType.INPUT_CONTRACT,
        logical_id=logical_id,
        version=int(version) if version.isdigit() else -1,
    ).first()
    if artifact is None or not isinstance(artifact.body, dict):
        raise CatalogSyncError("INPUT_CONTRACT_UNRESOLVED")
    return artifact.body


def _validate_catalog(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"tools"}:
        raise CatalogSyncError("CATALOG_INVALID")
    if len(canonical_json(payload).encode()) > MAX_CATALOG_BYTES:
        raise CatalogSyncError("CATALOG_TOO_LARGE")
    tools = payload["tools"]
    if not isinstance(tools, list) or len(tools) > MAX_CATALOG_TOOLS:
        raise CatalogSyncError("CATALOG_EXPLOSION")
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict) or set(tool) - {"name", "description", "inputSchema"}:
            raise CatalogSyncError("TOOL_METADATA_INVALID")
        name = tool.get("name")
        description = tool.get("description", "")
        schema = tool.get("inputSchema")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in names:
            raise CatalogSyncError("TOOL_NAME_INVALID")
        if not isinstance(description, str) or len(description) > 1000:
            raise CatalogSyncError("TOOL_DESCRIPTION_INVALID")
        _validate_schema(schema)
        names.add(name)
    return tools


def _validate_schema(schema: Any) -> None:
    if not isinstance(schema, dict) or len(canonical_json(schema).encode()) > MAX_SCHEMA_BYTES:
        raise CatalogSyncError("TOOL_SCHEMA_INVALID")
    nodes = 0
    stack: list[tuple[Any, int]] = [(schema, 1)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_SCHEMA_NODES or depth > MAX_SCHEMA_DEPTH:
            raise CatalogSyncError("TOOL_SCHEMA_TOO_COMPLEX")
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise CatalogSyncError("TOOL_SCHEMA_INVALID") from exc


def _audit(
    source: McpCatalogSource, actor_id: str, action: str, resource_id: int, reason: str
) -> None:
    record_event(
        actor_type=ActorType.USER,
        actor_id=actor_id,
        action=action,
        outcome=Outcome.SUCCESS,
        organization_id=source.organization_id,
        resource_type="mcp_catalog",
        resource_id=str(resource_id),
        reason=reason,
    )
