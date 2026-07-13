"""Governed document parsers: blob bytes + MIME -> normalized text (Phase 2 · P7.1).

A ``DocumentParser`` turns an uploaded document's stored bytes into normalized plain text /
markdown that the existing chunker + embedder consume. Parsing is **deny-by-default by MIME**:
only a registered, allowlisted parser runs; an unknown MIME fails closed. Output is **bounded**
(``MAX_PARSED_CHARS``) so one pathological document cannot exhaust a build, and parse *telemetry*
is **counts only** (elements/pages) — never document content — matching
``DocumentVersion.element_count``/``page_count`` and the observability redaction rules.

This module ships the **dependency-free, deterministic** stdlib parsers (plain text, markdown,
CSV, JSON, HTML). Richer binary formats (pdf/docx/xlsx) and external OCR are opt-in adapters added
under their own supply-chain / egress approval (P7.2+); they plug into *this* interface and
registry without changing the build. Because the default parsers are pure-stdlib and
deterministic, CI stays hermetic and opens no socket.

Security notes:
- Parsers treat the document as **untrusted data**. The HTML parser drops ``<script>``/``<style>``
  and emits only visible text (no tag/attribute execution, no external fetch — stdlib
  ``html.parser`` never resolves URLs). No parser follows links, includes remote entities, or
  executes embedded content.
- No parser raises with document content in its message (stable code only), so parse failures are
  safe to log/audit.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol

# Bounds — a single document cannot produce unbounded normalized text or structural elements.
MAX_PARSED_CHARS = 5_000_000
MAX_ELEMENTS = 100_000
# Non-visible HTML containers whose character data is never document text.
_HTML_SKIP_TAGS = frozenset({"script", "style", "head", "title", "meta", "link", "noscript"})
# Block-level HTML tags that should introduce a line break in the normalized text.
_HTML_BLOCK_TAGS = frozenset(
    {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}
)


class ParserError(RuntimeError):
    """A parse failure carrying only a stable, content-free code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ParsedContent:
    """Normalized parser output. ``element_count``/``page_count`` are counts only (no content)."""

    text: str
    parser: str
    element_count: int = 0
    page_count: int = 1


class DocumentParser(Protocol):
    name: str

    def parse(self, blob: bytes) -> ParsedContent: ...


def _decode_utf8(blob: bytes) -> str:
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParserError("DOCUMENT_NOT_UTF8") from exc


def _bounded(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise ParserError("EMPTY_DOCUMENT")
    if len(stripped) > MAX_PARSED_CHARS:
        raise ParserError("PARSED_TOO_LARGE")
    return stripped


class PlainTextParser:
    name = "text"

    def parse(self, blob: bytes) -> ParsedContent:
        text = _bounded(_decode_utf8(blob))
        return ParsedContent(text=text, parser=self.name)


class MarkdownParser:
    """Markdown is already normalized text; pass it through (still bounded/validated)."""

    name = "markdown"

    def parse(self, blob: bytes) -> ParsedContent:
        text = _bounded(_decode_utf8(blob))
        return ParsedContent(text=text, parser=self.name)


class CsvParser:
    """Render CSV rows as deterministic pipe-joined lines (a stable, chunkable text form)."""

    name = "csv"

    def parse(self, blob: bytes) -> ParsedContent:
        raw = _decode_utf8(blob)
        lines: list[str] = []
        reader = csv.reader(io.StringIO(raw))
        for row in reader:
            if len(lines) > MAX_ELEMENTS:
                raise ParserError("TOO_MANY_ELEMENTS")
            cells = [cell.strip() for cell in row]
            if any(cells):
                lines.append(" | ".join(cells))
        text = _bounded("\n".join(lines))
        return ParsedContent(text=text, parser=self.name, element_count=len(lines))


class JsonParser:
    """Flatten a JSON document into deterministic ``path: value`` lines (order-preserving)."""

    name = "json"

    def parse(self, blob: bytes) -> ParsedContent:
        raw = _decode_utf8(blob)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ParserError("JSON_INVALID") from exc
        lines: list[str] = []
        self._flatten("", data, lines)
        text = _bounded("\n".join(lines))
        return ParsedContent(text=text, parser=self.name, element_count=len(lines))

    def _flatten(self, prefix: str, node: object, lines: list[str]) -> None:
        if len(lines) > MAX_ELEMENTS:
            raise ParserError("TOO_MANY_ELEMENTS")
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                self._flatten(child, value, lines)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                self._flatten(f"{prefix}[{i}]", value, lines)
        else:
            label = prefix or "value"
            lines.append(f"{label}: {node}")


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def to_text(self) -> str:
        # Collapse to single-spaced words per line, dropping empty lines.
        collapsed: list[str] = []
        for line in "".join(self._parts).splitlines():
            words = line.split()
            if words:
                collapsed.append(" ".join(words))
        return "\n".join(collapsed)


class HtmlParser:
    """Extract visible text from HTML via stdlib ``html.parser`` (no fetch, no script/style)."""

    name = "html"

    def parse(self, blob: bytes) -> ParsedContent:
        raw = _decode_utf8(blob)
        extractor = _HtmlTextExtractor()
        try:
            extractor.feed(raw)
            extractor.close()
        except Exception as exc:  # stdlib parser is lenient; guard anyway
            raise ParserError("HTML_PARSE_FAILED") from exc
        text = _bounded(extractor.to_text())
        return ParsedContent(text=text, parser=self.name)


# Deny-by-default MIME -> parser registry. Only these MIME types are embeddable in P7.1; binary
# formats (pdf/docx/xlsx) remain unsupported until their opt-in adapter + dependency land (P7.2+).
PARSERS: dict[str, DocumentParser] = {
    "text/plain": PlainTextParser(),
    "text/markdown": MarkdownParser(),
    "text/csv": CsvParser(),
    "application/json": JsonParser(),
    "text/html": HtmlParser(),
}


def get_parser(mime_type: str) -> DocumentParser:
    """Return the allowlisted parser for ``mime_type`` or fail closed."""
    parser = PARSERS.get(mime_type)
    if parser is None:
        raise ParserError("PARSER_UNSUPPORTED")
    return parser


def parse_document(mime_type: str, blob: bytes) -> ParsedContent:
    """Deny-by-default entry point: resolve the parser for ``mime_type`` and parse ``blob``."""
    return get_parser(mime_type).parse(blob)
