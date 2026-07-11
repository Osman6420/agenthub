"""Central tool execution proxy: the single default-deny policy + egress boundary.

Every tool call is authorized here against the release-pinned binding: capability,
input/output contracts, field allowlists, risk/approval, egress (SSRF), bounded size,
and least-privilege secret resolution. A high-risk side-effecting tool is never
executed here — it raises :class:`ToolApprovalRequired` so the caller can open an
approval request (increment C). Tool output is treated as untrusted data, never as
instructions. Credentials are resolved ephemerally and never persisted or logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jsonschema

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import canonical_json
from apps.identity.capabilities import Capability
from apps.releases.models import ScenarioRelease
from apps.releases.services import get_artifact_body_for_role, get_manifest_role
from apps.tools.adapters import (
    DeterministicToolAdapter,
    ToolAdapter,
    ToolAdapterError,
    ToolAdapterRequest,
    ToolAdapterUncertain,
)
from apps.tools.egress import DnsResolver, EgressDenied, validate_destination
from apps.tools.secrets_resolver import EnvSecretResolver, SecretResolutionError, SecretResolver


class ToolExecutionError(RuntimeError):
    """Raised for a denied or failed tool invocation with a stable, safe code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ToolApprovalRequired(Exception):
    """Raised instead of executing a tool that requires human approval."""

    def __init__(self, *, role: str, risk: str) -> None:
        self.role = role
        self.risk = risk
        self.code = "APPROVAL_REQUIRED"
        super().__init__(self.code)


class ToolOutcomeUnknown(RuntimeError):
    """Raised when a dispatched call's outcome cannot be confirmed; never retried."""

    def __init__(self, code: str = "OUTCOME_UNKNOWN") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResolvedTool:
    role: str
    definition_ref: str
    binding_checksum: str
    protocol: str
    method: str | None
    destination: dict[str, Any]
    input_contract: dict[str, Any] | None
    output_contract: dict[str, Any] | None
    secret_ref: str | None
    risk: str
    side_effecting: bool
    approval_required: bool
    approver_roles: tuple[str, ...]
    timeout_seconds: int
    max_response_bytes: int
    allowed_input_fields: tuple[str, ...]
    allowed_output_fields: tuple[str, ...]


@dataclass(frozen=True)
class ToolCallResult:
    outcome: str
    reason_code: str
    output: dict[str, Any] | None


def resolve_release_tool(release: ScenarioRelease, role: str) -> ResolvedTool:
    """Resolve a release-pinned tool binding into an executable, contract-bound view.

    Fails closed unless the manifest pins a tool binding for ``role`` and the binding,
    its definition (checksum-matched to the pin), and both contracts resolve within the
    release's organization.
    """
    entry = get_manifest_role(release, role)
    if entry is None or entry.get("type") != ArtifactType.TOOL_BINDING:
        raise ToolExecutionError("TOOL_NOT_PINNED")
    pin = entry.get("tool")
    if not isinstance(pin, dict):
        raise ToolExecutionError("TOOL_NOT_PINNED")
    binding_body = get_artifact_body_for_role(release, role)
    if not isinstance(binding_body, dict):
        raise ToolExecutionError("TOOL_BINDING_UNRESOLVED")
    binding_spec = binding_body.get("spec", {})

    organization_id = release.scenario.project.organization_id
    definition_spec = _resolve_definition_spec(
        organization_id=organization_id,
        tool_ref=str(binding_spec.get("tool_ref", "")),
        expected_checksum=str(pin.get("definition_checksum", "")),
    )
    input_contract = _resolve_contract(
        organization_id,
        str(definition_spec.get("input_contract_ref", "")),
        ArtifactType.INPUT_CONTRACT,
    )
    output_contract = _resolve_contract(
        organization_id,
        str(definition_spec.get("output_contract_ref", "")),
        ArtifactType.OUTPUT_CONTRACT,
    )
    approval = binding_spec.get("approval", {})
    return ResolvedTool(
        role=role,
        definition_ref=str(pin.get("definition_ref", "")),
        binding_checksum=str(pin.get("binding_checksum", "")),
        protocol=str(definition_spec["protocol"]),
        method=definition_spec.get("method"),
        destination=dict(definition_spec["destination"]),
        input_contract=input_contract,
        output_contract=output_contract,
        secret_ref=definition_spec.get("secret_ref"),
        risk=str(definition_spec["risk"]),
        side_effecting=bool(definition_spec["side_effecting"]),
        approval_required=bool(pin.get("approval_required", approval.get("required", False))),
        approver_roles=tuple(approval.get("approver_roles", [])),
        timeout_seconds=int(definition_spec["timeout_seconds"]),
        max_response_bytes=int(definition_spec["max_response_bytes"]),
        allowed_input_fields=tuple(binding_spec.get("allowed_input_fields", [])),
        allowed_output_fields=tuple(binding_spec.get("allowed_output_fields", [])),
    )


def invoke_tool(
    *,
    tool: ResolvedTool,
    consumer_capabilities: list[str],
    tool_input: dict[str, Any],
    adapter: ToolAdapter | None = None,
    secret_resolver: SecretResolver | None = None,
    dns_resolver: DnsResolver | None = None,
    approval_granted: bool = False,
) -> ToolCallResult:
    required = Capability.TOOL_CALL_SIDE_EFFECT if tool.side_effecting else Capability.TOOL_CALL
    if required not in consumer_capabilities:
        raise ToolExecutionError("CAPABILITY_DENIED")

    # A tool that requires approval is never executed unless a valid approval was
    # recorded for this exact request (enforced by the approval service).
    if tool.approval_required and not approval_granted:
        raise ToolApprovalRequired(role=tool.role, risk=tool.risk)

    _validate_input(tool, tool_input)

    try:
        destination = validate_destination(tool.destination, resolver=dns_resolver)
    except EgressDenied as exc:
        raise ToolExecutionError(exc.code) from exc

    credential: str | None = None
    if tool.secret_ref:
        resolver = secret_resolver or EnvSecretResolver()
        try:
            credential = resolver.resolve(tool.secret_ref)
        except SecretResolutionError as exc:
            raise ToolExecutionError(exc.code) from exc

    active_adapter = adapter or DeterministicToolAdapter()
    request = ToolAdapterRequest(
        protocol=tool.protocol,
        method=tool.method,
        destination=destination,
        payload=tool_input,
        credential=credential,
        timeout_seconds=tool.timeout_seconds,
        max_response_bytes=tool.max_response_bytes,
    )
    try:
        response = active_adapter.call(request)
    except ToolAdapterUncertain as exc:
        # Dispatched, outcome unconfirmed: surface distinctly so the caller records it
        # as uncertain and does not retry a possible side effect.
        raise ToolOutcomeUnknown(exc.code) from exc
    except ToolAdapterError as exc:
        raise ToolExecutionError(exc.code) from exc

    output = _validate_output(tool, response.body)
    return ToolCallResult(outcome="completed", reason_code="OK", output=output)


def validate_tool_input(tool: ResolvedTool, tool_input: dict[str, Any]) -> None:
    """Public input check (field allowlist + input contract) for the request path."""
    _validate_input(tool, tool_input)


def _validate_input(tool: ResolvedTool, tool_input: Any) -> None:
    if not isinstance(tool_input, dict):
        raise ToolExecutionError("INPUT_INVALID")
    unknown = set(tool_input) - set(tool.allowed_input_fields)
    if unknown:
        raise ToolExecutionError("INPUT_FIELD_NOT_ALLOWED")
    if tool.input_contract is not None:
        try:
            jsonschema.validate(tool_input, tool.input_contract)
        except jsonschema.ValidationError as exc:
            raise ToolExecutionError("INPUT_CONTRACT_VIOLATION") from exc


def _validate_output(tool: ResolvedTool, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ToolExecutionError("OUTPUT_INVALID")
    if len(canonical_json(body).encode("utf-8")) > tool.max_response_bytes:
        raise ToolExecutionError("RESPONSE_TOO_LARGE")
    unknown = set(body) - set(tool.allowed_output_fields)
    if unknown:
        raise ToolExecutionError("OUTPUT_FIELD_NOT_ALLOWED")
    if tool.output_contract is not None:
        try:
            jsonschema.validate(body, tool.output_contract)
        except jsonschema.ValidationError as exc:
            raise ToolExecutionError("OUTPUT_CONTRACT_VIOLATION") from exc
    return body


def _resolve_definition_spec(
    *, organization_id: int, tool_ref: str, expected_checksum: str
) -> dict[str, Any]:
    logical_id, version = _split_ref(tool_ref)
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type=ArtifactType.TOOL_DEFINITION,
        logical_id=logical_id,
        version=version,
        checksum=expected_checksum,
    ).first()
    if artifact is None:
        raise ToolExecutionError("TOOL_DEFINITION_UNRESOLVED")
    spec = artifact.body.get("spec")
    if not isinstance(spec, dict):
        raise ToolExecutionError("TOOL_DEFINITION_UNRESOLVED")
    return spec


def _resolve_contract(organization_id: int, ref: str, artifact_type: str) -> dict[str, Any]:
    logical_id, version = _split_ref(ref)
    artifact = ArtifactVersion.objects.filter(
        organization_id=organization_id,
        type=artifact_type,
        logical_id=logical_id,
        version=version,
    ).first()
    if artifact is None or not isinstance(artifact.body, dict):
        raise ToolExecutionError("TOOL_CONTRACT_UNRESOLVED")
    return artifact.body


def _split_ref(ref: str) -> tuple[str, int]:
    if ":v" not in ref:
        raise ToolExecutionError("TOOL_REF_INVALID")
    logical_id, _, version_text = ref.rpartition(":v")
    if not logical_id or not version_text.isdigit():
        raise ToolExecutionError("TOOL_REF_INVALID")
    return logical_id, int(version_text)
