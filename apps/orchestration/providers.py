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


def get_model_provider() -> ModelProvider:
    path = getattr(settings, "RUNTIME_MODEL_PROVIDER", "")
    if path:
        return import_string(path)()
    return StubModelProvider()
