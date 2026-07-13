# Threat Model — P7 Parsers + OCR + Connectors

Scope of this record: **P7.1 (dependency-free stdlib parsers)** and **P7.2 (local pdf/docx/xlsx
parsers)**. P7.3–P7.4 (OCR egress, connectors) extend this model when they are approved and
implemented.

## Assets & trust boundary

- **Asset:** tenant document *content* (bytes in the object store) and the normalized text embedded
  into per-`IndexVersion` vector stores.
- **Trust boundary:** an uploaded document is **untrusted attacker-controlled data**. It crosses into
  the build when `staged_build` reads the blob and calls `parse_document(mime, blob)`.
- **Actor:** the ingestion/build worker (system actor), operating within a single tenant
  (`organization_id` carried on every document/version/membership row).

## Threats & mitigations (P7.1)

| # | Threat | Mitigation |
| --- | --- | --- |
| T1 | Malicious markup executes / exfiltrates (e.g. HTML `<script>`, external entity, SSRF via a document) | Stdlib `html.parser` never resolves URLs or executes; `<script>`/`<style>`/`<head>` bodies are dropped; no parser fetches remote content or expands entities. Parsing produces **data only**. |
| T2 | Resource exhaustion (billion-laughs / huge document / unbounded elements) | Bounded output `MAX_PARSED_CHARS`; bounded structural elements `MAX_ELEMENTS`; JSON/CSV element caps; the build's existing `_MAX_DOCUMENTS`/`_MAX_CHUNKS` still apply. |
| T3 | Content leakage via logs/errors/telemetry | `ParserError` carries a **stable code only** (`DOCUMENT_NOT_UTF8`, `JSON_INVALID`, `PARSER_UNSUPPORTED`, `PARSED_TOO_LARGE`, `EMPTY_DOCUMENT`, …), never document bytes; parse telemetry is **counts only** (elements/pages). |
| T4 | Type confusion / unexpected format served as another | Deny-by-default MIME registry: only an allowlisted parser runs; unknown/unsupported MIME (incl. pdf/docx/xlsx pre-P7.2) fails closed as `UNSUPPORTED_MIME_FOR_EMBEDDING`; a parse failure fails closed as `DOCUMENT_PARSE_FAILED` — the build drops the partial store (existing `_fail`). |
| T5 | Cross-tenant contamination through parsing | Parsing is pure per-blob text transformation with no shared state and no tenant crossing; the caller reads only same-tenant memberships and writes to the tenant-scoped, RLS-forced store (P4). Unchanged by P7.1. |
| T6 | Prompt injection via document text reaching the model | Out of scope for the parser (it produces retrieved *data*). The existing boundary holds: retrieved text is untrusted data, system instructions are server-side, tool calls are never authorized by model output, citation/policy run after the model (ADR-0002, Sprint 9/10). |

## Additional threats & mitigations (P7.2 — local binary parsers)

| # | Threat | Mitigation |
| --- | --- | --- |
| T7 | A malicious pdf/docx/xlsx triggers code execution or network fetch in the parser library | Parsing is **local and in-process** — pdfplumber/python-docx/openpyxl do text extraction only and open no socket. `openpyxl.load_workbook(read_only=True, data_only=True)` reads values, not formulas/macros; docx/xlsx are ZIP/XML read with the library's own bounded parser. No parser resolves external references. |
| T8 | Malformed/crafted binary crashes or hangs the worker | Every binary parser wraps the library call in `try/except` → a content-free `*_PARSE_FAILED`; the existing build `_fail` drops the partial store; output and element counts are bounded (`MAX_PARSED_CHARS`/`MAX_ELEMENTS`). |
| T9 | Supply-chain risk from the new dependencies | Owner-approved (2026-07-13) permissive-licensed libraries only; pins in `pyproject.toml`; `requirements.lock` regenerated with `pip check` clean; the langgraph trio pin is unchanged; no `openai`/network dependency added. |
| T10 | Image-only PDF silently yields empty content (false "parsed") | Fails closed as `EMPTY_DOCUMENT` (never a silent empty index); OCR of image content is the deferred, separately-approved P7.3 egress path. |

## Residual risk (P7.1 + P7.2)

- Parser correctness for adversarial-but-valid inputs (e.g. deeply nested JSON within the element
  cap, pathological CSV quoting) is bounded but not exhaustively fuzzed; caps make the failure mode
  a controlled error, not a crash or unbounded work.
- Parser-library correctness on adversarial binaries is bounded (caps + fail-closed), not
  exhaustively fuzzed; the failure mode is a controlled error, not a crash or unbounded work.
- OCR egress and new connectors (P7.3–P7.4) are **not** covered here and remain blocked on their
  egress sign-off; each adds its own SSRF/redirect/size/timeout/secret-handling threat rows when
  implemented.
