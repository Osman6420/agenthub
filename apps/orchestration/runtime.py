"""Synchronous RAG runtime (v3 plan §13).

Pipeline: verify context -> ensure the release is active -> resolve the pinned
bundle -> retrieve -> grounding gate -> generate -> build runtime citations ->
validate against the output contract -> citation policy -> return. Any governance
failure yields a server-controlled fallback rather than leaking model output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import jsonschema

from apps.orchestration.providers import (
    ModelProvider,
    ModelProviderError,
    get_model_provider,
)
from apps.orchestration.resolver import ReleaseBundle, resolve_bundle
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.retrieval.providers import RetrievalProvider, get_retrieval_provider
from apps.retrieval.types import RetrievedChunk

_DEFAULT_FALLBACK = "Bu soru icin guvenilir bir yanit uretemedim; lutfen destek ekibine basvurun."


class RuntimeReleaseError(RuntimeError):
    """Raised when the release backing a request is not active."""


class RetrievalError(RuntimeError):
    """Raised when the retrieval provider fails."""


@dataclass(frozen=True)
class RunResult:
    status: str  # "completed"
    output: dict[str, Any]
    usage: dict[str, int]
    fallback_used: bool
    metadata: dict[str, Any] = field(default_factory=dict)


def _citations(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    # Citations are produced only here, from retrieved chunks — never by the model.
    return [
        {
            "source_id": c.source_id,
            "source_uri": c.source_uri,
            "title": c.title,
            "score": c.score,
        }
        for c in chunks
    ]


def _fallback_output(bundle: ReleaseBundle) -> dict[str, Any]:
    fallback = bundle.policy.get("fallback", {}) if isinstance(bundle.policy, dict) else {}
    answer = fallback.get("answer") if isinstance(fallback, dict) else None
    return {
        "answer": answer or _DEFAULT_FALLBACK,
        "sources": [],
        "fallback_used": True,
    }


def _result(output: dict[str, Any], usage: dict[str, int], fallback: bool) -> RunResult:
    return RunResult(status="completed", output=output, usage=usage, fallback_used=fallback)


def run_rag(
    *,
    execution_context: dict[str, Any],
    validated_input: dict[str, Any],
    release: ScenarioRelease,
    model_provider: ModelProvider | None = None,
    retrieval_provider: RetrievalProvider | None = None,
    require_active: bool = True,
) -> RunResult:
    # A servable release is either the active one or a canary (the gateway only routes
    # a canary release to a consumer that holds a valid canary assignment). The internal
    # evaluation runner passes ``require_active=False`` to exercise a raw candidate in
    # isolation; that path is never reachable from the public gateway (Sprint 6 threat
    # model).
    if require_active and release.status not in (ReleaseStatus.ACTIVE, ReleaseStatus.CANARY):
        raise RuntimeReleaseError("release is not servable")

    bundle = resolve_bundle(release)
    model_provider = model_provider or get_model_provider()
    retrieval_provider = retrieval_provider or get_retrieval_provider()

    query = str(validated_input.get("query", ""))
    zero_usage = {"input_tokens": 0, "output_tokens": 0}

    # Retrieval.
    try:
        chunks = retrieval_provider.retrieve(
            query=query,
            profile=bundle.retrieval_profile,
            organization_id=bundle.organization_id,
            index_versions=bundle.index_versions,
        )
    except Exception as exc:  # provider-opaque failure
        raise RetrievalError(str(exc)) from exc

    grounding = bundle.policy.get("grounding", {}) if isinstance(bundle.policy, dict) else {}
    top_score = max((c.score for c in chunks), default=0.0)
    if grounding.get("required"):
        min_top = float(grounding.get("min_top_score", 0.0))
        if not chunks or top_score < min_top:
            return _result(_fallback_output(bundle), zero_usage, fallback=True)

    # Generation.
    try:
        model_response = model_provider.generate(
            prompt=bundle.prompt_text, context=chunks, model_profile=bundle.model_profile
        )
    except ModelProviderError:
        raise
    except Exception as exc:
        raise ModelProviderError(str(exc)) from exc

    usage = {
        "input_tokens": model_response.input_tokens,
        "output_tokens": model_response.output_tokens,
    }
    output = {
        "answer": model_response.text,
        "sources": _citations(chunks),
        "fallback_used": False,
    }

    # Output-contract governance: invalid model output is replaced by a fallback.
    if bundle.output_contract is not None:
        try:
            jsonschema.validate(instance=output, schema=bundle.output_contract)
        except jsonschema.ValidationError:
            return _result(_fallback_output(bundle), usage, fallback=True)

    # Citation policy.
    output_policy = bundle.policy.get("output", {}) if isinstance(bundle.policy, dict) else {}
    if output_policy.get("citations") == "required" and not output["sources"]:
        return _result(_fallback_output(bundle), usage, fallback=True)

    return _result(output, usage, fallback=False)
