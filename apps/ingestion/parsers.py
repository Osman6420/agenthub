"""Governed document parsers: blob bytes + MIME -> normalized text (Phase 2 · P7.1).

A ``DocumentParser`` turns an uploaded document's stored bytes into normalized plain text /
markdown that the existing chunker + embedder consume. Parsing is **deny-by-default by MIME**:
only a registered, allowlisted parser runs; an unknown MIME fails closed. Output is **bounded**
(``MAX_PARSED_CHARS``) so one pathological document cannot exhaust a build, and parse *telemetry*
is **counts only** (elements/pages) — never document content — matching
``DocumentVersion.element_count``/``page_count`` and the observability redaction rules.

This module ships the **deterministic** stdlib parsers (plain text, markdown, CSV, JSON, HTML) and
— from P7.2 (owner-approved 2026-07-13) — the **local binary-format** parsers pdf/docx/xlsx built on
``pdfplumber``/``python-docx``/``openpyxl``. All parsing is **in-process and opens no socket**: the
binary libraries do local text extraction only (no network). Their heavy imports are **deferred**
into the parse method, so importing this module needs only the stdlib and a text-only deployment
never loads them. External OCR (P7.3) and the Confluence/generic-REST connectors (P7.4) remain
deferred behind their egress sign-off; they plug into *this* same interface without changing the
build. CI stays hermetic — no parser opens a socket.

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


class PdfParser:
    """Extract text (and simple tables) from a PDF via ``pdfplumber`` (local, no network).

    An image-only page yields no extractable text here; OCR of image content is P7.3 (deferred), so
    a fully image-only PDF fails closed as ``EMPTY_DOCUMENT`` for now.
    """

    name = "pdf"

    def parse(self, blob: bytes) -> ParsedContent:
        import pdfplumber  # deferred: heavy optional dep, loaded only to parse a PDF

        pages: list[str] = []
        page_count = 0
        try:
            with pdfplumber.open(io.BytesIO(blob)) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    if len(pages) > MAX_ELEMENTS:
                        raise ParserError("TOO_MANY_ELEMENTS")
                    extracted = (page.extract_text() or "").strip()
                    if extracted:
                        pages.append(extracted)
        except ParserError:
            raise
        except Exception as exc:  # pdfminer/pdfplumber raise a wide range on malformed input
            raise ParserError("PDF_PARSE_FAILED") from exc
        text = _bounded("\n\n".join(pages))
        return ParsedContent(
            text=text, parser=self.name, page_count=page_count, element_count=len(pages)
        )


class DocxParser:
    """Extract paragraph + table text from a DOCX via ``python-docx`` (local, no network)."""

    name = "docx"

    def parse(self, blob: bytes) -> ParsedContent:
        import docx  # python-docx, deferred

        try:
            document = docx.Document(io.BytesIO(blob))
        except Exception as exc:
            raise ParserError("DOCX_PARSE_FAILED") from exc
        lines: list[str] = []
        try:
            for paragraph in document.paragraphs:
                if len(lines) > MAX_ELEMENTS:
                    raise ParserError("TOO_MANY_ELEMENTS")
                para_text = paragraph.text.strip()
                if para_text:
                    lines.append(para_text)
            for table in document.tables:
                for row in table.rows:
                    if len(lines) > MAX_ELEMENTS:
                        raise ParserError("TOO_MANY_ELEMENTS")
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        lines.append(" | ".join(cells))
        except ParserError:
            raise
        except Exception as exc:
            raise ParserError("DOCX_PARSE_FAILED") from exc
        text = _bounded("\n".join(lines))
        return ParsedContent(text=text, parser=self.name, element_count=len(lines))


class XlsxParser:
    """Flatten XLSX cells to deterministic pipe-joined rows via ``openpyxl`` (local, no network)."""

    name = "xlsx"

    def parse(self, blob: bytes) -> ParsedContent:
        import openpyxl  # deferred

        try:
            workbook = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
        except Exception as exc:
            raise ParserError("XLSX_PARSE_FAILED") from exc
        lines: list[str] = []
        try:
            for worksheet in workbook.worksheets:
                for row in worksheet.iter_rows(values_only=True):
                    if len(lines) > MAX_ELEMENTS:
                        raise ParserError("TOO_MANY_ELEMENTS")
                    cells = ["" if value is None else str(value).strip() for value in row]
                    if any(cells):
                        lines.append(" | ".join(cells))
        except ParserError:
            raise
        except Exception as exc:
            raise ParserError("XLSX_PARSE_FAILED") from exc
        finally:
            workbook.close()
        text = _bounded("\n".join(lines))
        return ParsedContent(text=text, parser=self.name, element_count=len(lines))


# Deny-by-default MIME -> parser registry. Text formats use stdlib parsers; the pdf/docx/xlsx
# entries use the owner-approved (P7.2) local binary libraries via deferred imports. Any MIME not
# listed here (e.g. image/* — OCR is P7.3) fails closed at the build.
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PARSERS: dict[str, DocumentParser] = {
    "text/plain": PlainTextParser(),
    "text/markdown": MarkdownParser(),
    "text/csv": CsvParser(),
    "application/json": JsonParser(),
    "text/html": HtmlParser(),
    "application/pdf": PdfParser(),
    _DOCX_MIME: DocxParser(),
    _XLSX_MIME: XlsxParser(),
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
