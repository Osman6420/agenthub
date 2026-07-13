# Phase 2 · P7 — Parsers + OCR + Connectors

Authority for scope: [`runtime-and-document-plane-sequence.md`](../../planning/components/runtime-and-document-plane-sequence.md)
§ "P7 — Parsers + OCR + connectors" and [`document-plane-plan.md`](../../planning/components/document-plane-plan.md)
decision (E). Egress governance: [ADR-0002](../../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md)
/ [ADR-0005](../../adr/0005-shared-ssrf-safe-egress-adapter.md).

## Goal

Turn richer document formats into normalized text for the existing chunk + embed + index build,
behind a single `DocumentParser` interface, and add the remaining ingestion connectors — **without
weakening tenant isolation, the serving guardrail, or the no-blind-retry / SSRF-safe egress
contracts**, and honoring the per-phase dependency/egress approval gates.

## Decomposition (each increment additive-migration-safe; deterministic stays default)

### P7.1 — `DocumentParser` interface + dependency-free stdlib parsers — **IMPLEMENTED (this change)**

- New `apps/ingestion/parsers.py`: a deny-by-default, MIME-keyed `DocumentParser` registry
  (`ParsedContent`, `ParserError`, `get_parser`, `parse_document`) with **stdlib-only, deterministic**
  parsers: `text/plain`, `text/markdown`, `text/csv`, `application/json`, `text/html`.
- Wire the parser seam into `apps/ingestion/staged_build._embed_into_store`, replacing the hardcoded
  `text/plain|text/markdown` UTF-8-only path. Unsupported MIME (pdf/docx/xlsx before P7.2) fails
  closed as `UNSUPPORTED_MIME_FOR_EMBEDDING`; a parse failure fails closed as `DOCUMENT_PARSE_FAILED`.
- Governance: bounded output (`MAX_PARSED_CHARS`, `MAX_ELEMENTS`); parse telemetry is **counts only**
  (elements/pages), never content; HTML drops `<script>`/`<style>` and never fetches remote content;
  parse errors carry a **stable code only**, never document bytes.
- **No new dependency, no egress, no migration.** CI stays hermetic (pure stdlib, deterministic).

### P7.2 — Real binary-format parsers (pdf/docx/xlsx → markdown) — **GATED: dependency approval**

- Opt-in adapters implementing the same `DocumentParser` interface, selected like the other opt-in
  real providers (deterministic/stdlib default; the binary adapter is enabled only when its
  dependency is installed and its MIME is registered). Follows the established
  `RUNTIME_*_PROVIDER` opt-in pattern (default keeps CI hermetic).
- **Approval gate — document-parser dependency (supply-chain review).** Owner preference recorded in
  the component plan: permissive-licensed, air-gap-installable, format-specific baseline
  **pypdf / pdfplumber (pdf) + python-docx (docx) + openpyxl (xlsx)**; **OCR is NOT in-app**. A
  comparison table is produced for the owner **before** any dependency is added to `pyproject`.

### P7.3 — External OCR for image-only pages/embedded images — **GATED: OCR egress sign-off**

- Image-only PDF pages and embedded images are sent to the **owner's external OCR endpoint** over the
  shared SSRF-safe egress adapter (ADR-0005), profile-ID-only (ADR-0002), no blind retry. Returned
  text re-enters the same parser output.
- **Approval gate — OCR endpoint/profile + secret (environment-specific).**

### P7.4 — Connectors (upload + Confluence + generic REST) — **GATED: connector egress sign-off**

- Upload already exists (`apps/documents` upload service). Add a Confluence connector and a generic
  REST connector reusing the existing bounded, allowlisted, redirect-denying SSRF-safe pattern in
  `apps/ingestion/connectors.py` (host allowlist empty by default → unreachable until an endpoint is
  allowlisted and signed off).
- **Approval gate — Confluence/REST connector endpoints (allowlist + secret).**

## Non-negotiable constraints (unchanged from prior phases)

- Additive migrations only; never weaken a control; deterministic providers remain the default.
- Documents are **untrusted data**: parsers never execute embedded content, follow links, or resolve
  external entities. Tool/decision/authorization gates are unaffected — parsing produces data.
- Serving guardrail intact: parsing changes *what text* an index build embeds, not *who* is served;
  P4 ACL + RLS remain the serving authority.
- Egress (P7.3/P7.4) is profile-ID-only over the shared SSRF-safe adapter; no `openai` or other
  network dependency; no blind retry (post-send failure = unknown outcome).

## Status

- **P7.1: Implemented + verified (this change).**
- **P7.2/P7.3/P7.4: Planned — blocked on the owner's dependency + egress approvals** (see the
  approvals summary in the sequence doc). No code, dependency, or egress for these yet.
