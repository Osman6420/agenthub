# Threat Model — P7 Parsers + OCR + Connectors

Scope of this record: **P7.1 (dependency-free stdlib parsers)**. P7.2–P7.4 (binary parsers, OCR
egress, connectors) extend this model when they are approved and implemented.

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

## Residual risk (P7.1)

- Parser correctness for adversarial-but-valid inputs (e.g. deeply nested JSON within the element
  cap, pathological CSV quoting) is bounded but not exhaustively fuzzed; caps make the failure mode
  a controlled error, not a crash or unbounded work.
- Binary-format parsing, OCR egress, and new connectors (P7.2–P7.4) are **not** covered here and
  remain blocked on their approval gates; each adds its own threat rows (dependency provenance for
  parsers; SSRF/redirect/size/timeout/secret-handling for OCR + connectors) when implemented.
