"""Allowlisted parser/chunker/embedder pipeline."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from apps.ingestion.connectors import RawDocument


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedDocument:
    uri: str
    text: str
    title: str = ""


def parse_text(raw: RawDocument) -> ParsedDocument:
    try:
        text = raw.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PipelineError("PARSE_FAILED") from exc
    text = text.strip()
    if not text:
        raise PipelineError("EMPTY_DOCUMENT")
    return ParsedDocument(uri=raw.uri, text=text, title=raw.title)


def chunk_fixed(text: str, *, size: int = 1000, overlap: int = 100) -> list[str]:
    if size < 100 or overlap < 0 or overlap >= size:
        raise PipelineError("CHUNK_CONFIG_INVALID")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunk = text[start : start + size].strip()
        if chunk:
            chunks.append(chunk)
        if len(chunks) > 10_000:
            raise PipelineError("TOO_MANY_CHUNKS")
        start += size - overlap
    return chunks


def embed_deterministic(text: str, dimensions: int = 64) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        values.extend((byte - 127.5) / 127.5 for byte in digest)
        counter += 1
    vector = values[:dimensions]
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


PARSERS = {"text": parse_text}
CHUNKERS = {"fixed": chunk_fixed}
EMBEDDERS = {"deterministic": embed_deterministic}
