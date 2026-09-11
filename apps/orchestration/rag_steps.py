"""Shared governed retrieve/generate steps for the workflow and agent runtimes (P5).

Both the workflow ``retrieve``/``generate`` nodes and the agent loop's retrieve/respond steps run
the governed seams the unified Document Answer workflow uses: the release-pinned retrieval provider
(P4 document-ACL retrieval) and the model provider (P1 chat), resolved from the release bundle.
Chunks are carried through the durable, redacted run state as plain JSON dicts and rebuilt into
``RetrievedChunk`` objects for the model context, so nothing but JSON-safe metadata is persisted.

Defaults stay deterministic (``RUNTIME_RETRIEVAL_PROVIDER``/``RUNTIME_MODEL_PROVIDER`` /
``RUNTIME_EMBEDDING_PROVIDER`` unset) so CI is hermetic; the real providers light up by config.
"""

from __future__ import annotations

import inspect
from typing import Any

from apps.orchestration.providers import ModelResponse, get_model_provider
from apps.orchestration.resolver import resolve_bundle
from apps.retrieval.providers import get_retrieval_provider
from apps.retrieval.types import RetrievedChunk

DEFAULT_FALLBACK_ANSWER = (
    "Bu soru icin guvenilir bir yanit uretemedim; lutfen destek ekibine basvurun."
)

CITATION_FIELDS = ("source_id", "source_uri", "title", "score")

#: Numeric-only chunk provenance. An operator console can resolve a chunk's text from the
#: vector store with these, under its own document-content authorization -- so they must stay
#: free of any field that could carry text. Every value is validated as a number below.
POINTER_FIELDS = (
    "document_version_id",
    "document_set_version_id",
    "index_version_id",
    "ordinal",
    "score",
    "vector_score",
    "keyword_score",
    "fused_score",
)


def retrieval_pointers_from_state(state: dict[str, Any]) -> list[dict[str, float | int]]:
    """Project retrieved chunks down to numeric evidence pointers.

    Strings in a persisted run state are already redacted, and none are carried here anyway:
    a pointer says *which* chunk was used, never what it said.
    """

    retrieval = state.get("retrieval") if isinstance(state, dict) else None
    raw = retrieval.get("chunks") if isinstance(retrieval, dict) else None
    pointers: list[dict[str, float | int]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        pointer: dict[str, float | int] = {}
        for field in POINTER_FIELDS:
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            pointer[field] = value
        pointers.append(pointer)
    return pointers


def citations_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Project retrieved chunks down to citation provenance.

    Chunk text stays inside the run state and never reaches a caller: a citation carries where an
    answer came from, not what the document said.
    """
    retrieval = state.get("retrieval") if isinstance(state, dict) else None
    raw = retrieval.get("chunks") if isinstance(retrieval, dict) else None
    return [
        {field: item.get(field) for field in CITATION_FIELDS}
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict)
    ]


def grounding_fallback_answer(*, release: Any, state: dict[str, Any]) -> str | None:
    """Return the release fallback answer when the grounding gate refuses generation.

    When the pinned policy requires grounding and retrieval did not clear the
    score floor, the model is never called and a server-controlled answer is returned instead.
    """
    bundle = resolve_bundle(release)
    policy = bundle.policy if isinstance(bundle.policy, dict) else {}
    grounding = policy.get("grounding")
    if not isinstance(grounding, dict) or not grounding.get("required"):
        return None
    retrieval = state.get("retrieval") if isinstance(state, dict) else None
    chunks = retrieval.get("chunks") if isinstance(retrieval, dict) else None
    top_score = 0.0
    if isinstance(retrieval, dict):
        try:
            top_score = float(retrieval.get("top_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            top_score = 0.0
    if chunks and top_score >= float(grounding.get("min_top_score", 0.0)):
        return None
    fallback = policy.get("fallback")
    answer = fallback.get("answer") if isinstance(fallback, dict) else None
    return str(answer) if answer else DEFAULT_FALLBACK_ANSWER


def chunk_to_dict(chunk: RetrievedChunk) -> dict[str, Any]:
    return {
        "text": chunk.text,
        "source_id": chunk.source_id,
        "source_uri": chunk.source_uri,
        "title": chunk.title,
        "score": chunk.score,
        "chunk_kind": chunk.chunk_kind,
        "vector_rank": chunk.vector_rank,
        "vector_score": chunk.vector_score,
        "keyword_rank": chunk.keyword_rank,
        "keyword_score": chunk.keyword_score,
        "fused_score": chunk.fused_score,
        "document_routing_score": chunk.document_routing_score,
        "retrieval_stage": chunk.retrieval_stage,
        "document_version_id": chunk.document_version_id,
        "document_set_version_id": chunk.document_set_version_id,
        "index_version_id": chunk.index_version_id,
        "ordinal": chunk.ordinal,
    }


def chunks_from_state(state: dict[str, Any]) -> list[RetrievedChunk]:
    """Rebuild retrieved chunks from the redacted run state (JSON dicts -> objects)."""
    retrieval = state.get("retrieval") if isinstance(state, dict) else None
    raw = retrieval.get("chunks") if isinstance(retrieval, dict) else None
    chunks: list[RetrievedChunk] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            chunks.append(
                RetrievedChunk(
                    text=item["text"],
                    source_id=str(item.get("source_id", "")),
                    source_uri=str(item.get("source_uri", "")),
                    title=str(item.get("title", "")),
                    score=float(item.get("score", 0.0) or 0.0),
                    chunk_kind=str(item.get("chunk_kind", "content")),
                    vector_rank=(
                        int(item["vector_rank"])
                        if isinstance(item.get("vector_rank"), int)
                        else None
                    ),
                    vector_score=(
                        float(item["vector_score"])
                        if isinstance(item.get("vector_score"), (int, float))
                        else None
                    ),
                    keyword_rank=(
                        int(item["keyword_rank"])
                        if isinstance(item.get("keyword_rank"), int)
                        else None
                    ),
                    keyword_score=(
                        float(item["keyword_score"])
                        if isinstance(item.get("keyword_score"), (int, float))
                        else None
                    ),
                    fused_score=(
                        float(item["fused_score"])
                        if isinstance(item.get("fused_score"), (int, float))
                        else None
                    ),
                    document_routing_score=(
                        float(item["document_routing_score"])
                        if isinstance(item.get("document_routing_score"), (int, float))
                        else None
                    ),
                    retrieval_stage=str(item.get("retrieval_stage", "direct")),
                )
            )
    return chunks


def retrieve_for_release(
    *,
    release: Any,
    query: str,
    consumer_id: int | None = None,
    retrieval_profile: dict[str, Any] | None = None,
    workflow_run: Any | None = None,
    selection_id: int | None = None,
) -> dict[str, Any]:
    """Run governed, release-scoped retrieval and return a JSON-safe ``retrieval`` state block."""
    bundle = resolve_bundle(release)
    profile = retrieval_profile if retrieval_profile is not None else bundle.retrieval_profile
    provider = get_retrieval_provider()
    if workflow_run is not None and getattr(workflow_run, "prepared_evaluation_id", None):
        if (
            workflow_run.release_id != release.pk
            or workflow_run.organization_id != bundle.organization_id
            or workflow_run.consumer_id != consumer_id
            or (bundle.data_selection == "active_generation" and selection_id is None)
        ):
            raise ValueError("PREPARED_EVALUATION_RUN_INVALID")
        prepared_reader = getattr(provider, "retrieve_prepared", None)
        if not callable(prepared_reader):
            raise ValueError("PREPARED_EVALUATION_PROVIDER_UNSUPPORTED")
        chunks = prepared_reader(
            query=query,
            profile=profile,
            organization_id=bundle.organization_id,
            scenario_id=bundle.scenario_id,
            consumer_id=consumer_id,
            release_id=release.pk,
            run_id=workflow_run.pk,
            selection_id=selection_id,
        )
    elif bundle.data_selection == "active_generation":
        if (
            workflow_run is None
            or selection_id is None
            or workflow_run.release_id != release.pk
            or workflow_run.organization_id != bundle.organization_id
            or workflow_run.consumer_id != consumer_id
        ):
            raise ValueError("RETRIEVAL_SELECTION_REQUIRED")
        selected_reader = getattr(provider, "retrieve_selected", None)
        if not callable(selected_reader):
            raise ValueError("RETRIEVAL_SELECTION_PROVIDER_UNSUPPORTED")
        chunks = selected_reader(
            query=query,
            profile=profile,
            organization_id=bundle.organization_id,
            scenario_id=bundle.scenario_id,
            consumer_id=consumer_id,
            release_id=release.pk,
            run_id=workflow_run.pk,
            selection_id=selection_id,
        )
    elif bundle.data_selection == "legacy_pinned":
        chunks = provider.retrieve(
            query=query,
            profile=profile,
            organization_id=bundle.organization_id,
            scenario_id=getattr(bundle, "scenario_id", getattr(release, "scenario_id", None)),
            index_versions=bundle.index_versions,
            document_set_version_ids=bundle.document_set_version_ids,
            consumer_id=consumer_id,
        )
    else:
        raise ValueError("RETRIEVAL_SELECTION_MODE_UNSUPPORTED")
    return {
        "chunks": [chunk_to_dict(chunk) for chunk in chunks],
        "top_score": max((chunk.score for chunk in chunks), default=0.0),
    }


def generate_for_release(
    *,
    release: Any,
    context: list[RetrievedChunk],
    prompt: str | None = None,
    model_profile: dict[str, Any] | None = None,
    user_query: str = "",
) -> ModelResponse:
    """Generate over the governed model provider, defaulting to the release prompt/profile.

    ``prompt``/``model_profile`` overrides support per-node binding (P5.2); when omitted the
    release-level ``prompt``/``model_profile`` roles from the bundle are used.
    """
    bundle = resolve_bundle(release)
    arguments: dict[str, Any] = {
        "prompt": prompt if prompt is not None else bundle.prompt_text,
        "context": context,
        "model_profile": model_profile if model_profile is not None else bundle.model_profile,
    }
    provider = get_model_provider()
    parameters = inspect.signature(provider.generate).parameters.values()
    supports_user_query = any(
        parameter.name == "user_query" or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if user_query and supports_user_query:
        arguments["user_query"] = user_query
    return provider.generate(**arguments)
