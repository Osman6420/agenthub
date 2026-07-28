"""Retrieval value types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieved passage. Citations are built from these by the runtime."""

    text: str
    source_id: str
    source_uri: str
    title: str = ""
    score: float = 0.0
    chunk_kind: str = "content"
    vector_rank: int | None = None
    vector_score: float | None = None
    keyword_rank: int | None = None
    keyword_score: float | None = None
    fused_score: float | None = None
    document_routing_score: float | None = None
    retrieval_stage: str = "direct"
