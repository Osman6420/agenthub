"""Shared governed retrieve/generate steps for the workflow and agent runtimes (P5).

Both the workflow ``retrieve``/``generate`` nodes and the agent loop's retrieve/respond steps run
the **same** governed seams the standalone ``run_rag`` uses: the release-pinned retrieval provider
(P4 document-ACL retrieval) and the model provider (P1 chat), resolved from the release bundle.
Chunks are carried through the durable, redacted run state as plain JSON dicts and rebuilt into
``RetrievedChunk`` objects for the model context, so nothing but JSON-safe metadata is persisted.

Defaults stay deterministic (``RUNTIME_RETRIEVAL_PROVIDER``/``RUNTIME_MODEL_PROVIDER`` /
``RUNTIME_EMBEDDING_PROVIDER`` unset) so CI is hermetic; the real providers light up by config.
"""

from __future__ import annotations

from typing import Any

from apps.orchestration.providers import ModelResponse, get_model_provider
from apps.orchestration.resolver import resolve_bundle
from apps.retrieval.providers import get_retrieval_provider
from apps.retrieval.types import RetrievedChunk


def chunk_to_dict(chunk: RetrievedChunk) -> dict[str, Any]:
    return {
        "text": chunk.text,
        "source_id": chunk.source_id,
        "source_uri": chunk.source_uri,
        "title": chunk.title,
        "score": chunk.score,
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
                )
            )
    return chunks


def retrieve_for_release(*, release: Any, query: str) -> dict[str, Any]:
    """Run governed, release-scoped retrieval and return a JSON-safe ``retrieval`` state block."""
    bundle = resolve_bundle(release)
    chunks = get_retrieval_provider().retrieve(
        query=query,
        profile=bundle.retrieval_profile,
        organization_id=bundle.organization_id,
        index_versions=bundle.index_versions,
        document_set_version_ids=bundle.document_set_version_ids,
    )
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
) -> ModelResponse:
    """Generate over the governed model provider, defaulting to the release prompt/profile.

    ``prompt``/``model_profile`` overrides support per-node binding (P5.2); when omitted the
    release-level ``prompt``/``model_profile`` roles from the bundle are used.
    """
    bundle = resolve_bundle(release)
    return get_model_provider().generate(
        prompt=prompt if prompt is not None else bundle.prompt_text,
        context=context,
        model_profile=model_profile if model_profile is not None else bundle.model_profile,
    )
