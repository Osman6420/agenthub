"""Profile-only AI authoring provider with immutable prompt contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from django.conf import settings
from django.utils.module_loading import import_string

from apps.artifacts.types import ArtifactType
from apps.orchestration.egress import ModelEgressError, ModelEgressOutcomeUnknown
from apps.orchestration.models import ModelProfile, ModelProfileStatus

WORKFLOW_SYSTEM_INSTRUCTIONS = """You generate AgentHub workflow DSL as JSON data only.
Return exactly one JSON object with api_version agenthub/v1, kind Workflow, metadata.id,
and spec containing input_node, nodes and edges. Use only the supplied platform DSL rules.
Never emit credentials, endpoints, headers, executable code, markdown, or explanations."""

INPUT_CONTRACT_SYSTEM_INSTRUCTIONS = """You generate an AgentHub input contract as JSON data only.
Return exactly one JSON object that is a valid JSON Schema Draft 2020-12 document describing the
requested input. Use explicit object properties and required fields when applicable. Never emit
credentials, endpoints, headers, executable code, markdown, or explanations."""

OUTPUT_CONTRACT_SYSTEM_INSTRUCTIONS = """You generate an AgentHub output contract as JSON data only.
Return exactly one JSON object that is a valid JSON Schema Draft 2020-12 document describing the
requested output. Use explicit object properties and required fields when applicable. Never emit
credentials, endpoints, headers, executable code, markdown, or explanations."""


class AuthoringProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AuthoringResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class AuthoringContract:
    contract_id: str
    revision: int
    artifact_type: str
    system_instructions: str
    checksum: str


def _contract(
    contract_id: str, revision: int, artifact_type: str, system_instructions: str
) -> AuthoringContract:
    canonical = json.dumps(
        {
            "artifact_type": artifact_type,
            "contract_id": contract_id,
            "revision": revision,
            "system_instructions": system_instructions,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return AuthoringContract(contract_id, revision, artifact_type, system_instructions, checksum)


AUTHORING_CONTRACTS: Mapping[tuple[str, int], AuthoringContract] = MappingProxyType(
    {
        (ArtifactType.WORKFLOW_DEFINITION, 1): _contract(
            "agenthub.workflow-authoring",
            1,
            ArtifactType.WORKFLOW_DEFINITION,
            WORKFLOW_SYSTEM_INSTRUCTIONS,
        ),
        (ArtifactType.INPUT_CONTRACT, 1): _contract(
            "agenthub.input-contract-authoring",
            1,
            ArtifactType.INPUT_CONTRACT,
            INPUT_CONTRACT_SYSTEM_INSTRUCTIONS,
        ),
        (ArtifactType.OUTPUT_CONTRACT, 1): _contract(
            "agenthub.output-contract-authoring",
            1,
            ArtifactType.OUTPUT_CONTRACT,
            OUTPUT_CONTRACT_SYSTEM_INSTRUCTIONS,
        ),
    }
)


def get_authoring_contract(artifact_type: str) -> AuthoringContract:
    """Resolve only a server-owned, reviewed contract revision."""
    try:
        revision = int(getattr(settings, "AI_AUTHORING_CONTRACT_REVISION", 1))
    except (TypeError, ValueError) as exc:
        raise AuthoringProviderError("AUTHORING_CONTRACT_UNAVAILABLE") from exc
    contract = AUTHORING_CONTRACTS.get((artifact_type, revision))
    if contract is None:
        code = (
            "UNSUPPORTED_ARTIFACT_TYPE"
            if not any(key[0] == artifact_type for key in AUTHORING_CONTRACTS)
            else "AUTHORING_CONTRACT_UNAVAILABLE"
        )
        raise AuthoringProviderError(code)
    return contract


class AuthoringProvider(Protocol):
    def generate(
        self, *, profile_id: str, description: str, contract: AuthoringContract
    ) -> AuthoringResponse: ...


class OpenAICompatibleAuthoringProvider:
    def __init__(self, *, egress_client: Any | None = None) -> None:
        if egress_client is None:
            from apps.orchestration.egress import JsonModelEgressClient

            egress_client = JsonModelEgressClient()
        self._egress = egress_client

    def generate(
        self, *, profile_id: str, description: str, contract: AuthoringContract
    ) -> AuthoringResponse:
        try:
            profile = ModelProfile.objects.get(
                public_id=profile_id, status=ModelProfileStatus.ACTIVE
            )
        except (ModelProfile.DoesNotExist, ValueError, TypeError) as exc:
            raise AuthoringProviderError("MODEL_PROFILE_UNAVAILABLE") from exc
        payload = {
            "model": profile.model,
            "messages": [
                {"role": "system", "content": contract.system_instructions},
                {"role": "user", "content": description},
            ],
            "max_tokens": profile.max_output_tokens,
        }
        try:
            response = self._egress.call_json(
                profile_id=profile_id, operation="chat", payload=payload
            )
        except ModelEgressOutcomeUnknown as exc:
            raise AuthoringProviderError("OUTCOME_UNKNOWN") from exc
        except ModelEgressError as exc:
            raise AuthoringProviderError(exc.code) from exc
        try:
            text = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AuthoringProviderError("MODEL_RESPONSE_INVALID") from exc
        if not isinstance(text, str) or not text:
            raise AuthoringProviderError("MODEL_RESPONSE_INVALID")
        return AuthoringResponse(text, input_tokens, output_tokens)


def get_authoring_provider() -> AuthoringProvider:
    path = getattr(settings, "AI_AUTHORING_PROVIDER", "")
    if path:
        return import_string(path)()
    return OpenAICompatibleAuthoringProvider()
