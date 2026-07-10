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
