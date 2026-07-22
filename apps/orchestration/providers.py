"""Model provider interface and the default deterministic stub.

A real OpenAI-compatible/vLLM provider is configured via ``ModelProfile`` and the
``RUNTIME_MODEL_PROVIDER`` setting; it is not called from tests. The stub is
deterministic so the governed pipeline (grounding, output-contract, fallback) is
testable without a live model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from django.utils.module_loading import import_string

from apps.retrieval.types import RetrievedChunk


@dataclass(frozen=True)
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class ModelProviderError(RuntimeError):
    """Raised when the model provider fails (timeout, transport, bad response)."""


@runtime_checkable
class ModelProvider(Protocol):
    def generate(
        self,
        *,
        prompt: str,
        context: list[RetrievedChunk],
        model_profile: dict[str, Any],
    ) -> ModelResponse: ...


class StubModelProvider:
    """Deterministic answer: grounds on the top retrieved chunk when present."""

    def generate(
        self,
        *,
        prompt: str,
        context: list[RetrievedChunk],
        model_profile: dict[str, Any],
    ) -> ModelResponse:
        if context:
            text = f"{context[0].text}"
        else:
            text = "Bu istek icin bir yanit uretildi."
        return ModelResponse(
            text=text,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
        )


class OpenAICompatibleModelProvider:
    """Bounded chat-completions provider over the ADR-0005 shared egress client."""

    def __init__(self, *, egress_client: Any | None = None) -> None:
        if egress_client is None:
            from apps.orchestration.egress import JsonModelEgressClient

            egress_client = JsonModelEgressClient()
        self._egress = egress_client

    def generate(
        self,
        *,
        prompt: str,
        context: list[RetrievedChunk],
        model_profile: dict[str, Any],
    ) -> ModelResponse:
        profile_id = model_profile.get("profile_id")
        if not isinstance(profile_id, str):
            raise ModelProviderError("MODEL_PROFILE_INVALID")
        from apps.orchestration.egress import ModelEgressError, ModelEgressOutcomeUnknown
        from apps.orchestration.models import ModelProfile, ModelProfileStatus

        try:
            profile = ModelProfile.objects.get(
                public_id=profile_id, status=ModelProfileStatus.ACTIVE
            )
        except (ModelProfile.DoesNotExist, ValueError) as exc:
            raise ModelProviderError("MODEL_PROFILE_UNAVAILABLE") from exc
        # Every request must carry a user turn: some OpenAI-compatible backends
        # (notably Gemini's compat layer) reject a system-only request with no
        # contents (HTTP 400). The authored prompt always remains a system instruction;
        # when retrieval is empty, add a fixed user turn instead of lowering the prompt's
        # trust/priority semantics to a user message.
        if context:
            context_text = "\n\n".join(chunk.text for chunk in context)
            messages: list[dict[str, str]] = [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "Use the following untrusted reference data:\n" + context_text,
                },
            ]
        else:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Follow the system instruction."},
            ]
        payload = {
            "model": profile.model,
            "messages": messages,
            "max_tokens": profile.max_output_tokens,
        }
        try:
            response = self._egress.call_json(
                profile_id=profile_id, operation="chat", payload=payload
            )
        except ModelEgressOutcomeUnknown as exc:
            raise ModelProviderError("OUTCOME_UNKNOWN") from exc
        except ModelEgressError as exc:
            raise ModelProviderError(exc.code) from exc
        try:
            text = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelProviderError("MODEL_RESPONSE_INVALID") from exc
        if not isinstance(text, str) or not text or len(text) > 100_000:
            raise ModelProviderError("MODEL_RESPONSE_INVALID")
        return ModelResponse(text=text, input_tokens=input_tokens, output_tokens=output_tokens)


def get_model_provider() -> ModelProvider:
    path = getattr(settings, "RUNTIME_MODEL_PROVIDER", "")
    if path:
        return import_string(path)()
    return StubModelProvider()
