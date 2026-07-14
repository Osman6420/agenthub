"""Profile-only AI workflow authoring provider (Phase 2 P10.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings
from django.utils.module_loading import import_string

from apps.orchestration.egress import ModelEgressError, ModelEgressOutcomeUnknown
from apps.orchestration.models import ModelProfile, ModelProfileStatus

SYSTEM_INSTRUCTIONS = """You generate AgentHub workflow DSL as JSON data only.
Return exactly one JSON object with api_version agenthub/v1, kind Workflow, metadata.id,
and spec containing input_node, nodes and edges. Use only the supplied platform DSL rules.
Never emit credentials, endpoints, headers, executable code, markdown, or explanations."""


class AuthoringProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AuthoringResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class AuthoringProvider(Protocol):
    def generate(self, *, profile_id: str, description: str) -> AuthoringResponse: ...


class OpenAICompatibleAuthoringProvider:
    def __init__(self, *, egress_client: Any | None = None) -> None:
        if egress_client is None:
            from apps.orchestration.egress import JsonModelEgressClient

            egress_client = JsonModelEgressClient()
        self._egress = egress_client

    def generate(self, *, profile_id: str, description: str) -> AuthoringResponse:
        try:
            profile = ModelProfile.objects.get(
                public_id=profile_id, status=ModelProfileStatus.ACTIVE
            )
        except (ModelProfile.DoesNotExist, ValueError, TypeError) as exc:
            raise AuthoringProviderError("MODEL_PROFILE_UNAVAILABLE") from exc
        payload = {
            "model": profile.model,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
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
