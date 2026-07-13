# Verification: phase-2-p7-parsers-ocr-connectors

## Status

**P7.1 Verified 2026-07-13.** Automated evidence only; pure-stdlib deterministic parsers, so no
socket is opened and no live endpoint is called. P7.2 (binary parsers), P7.3 (OCR egress), and P7.4
(connectors) are **not implemented** — they remain blocked on the owner's dependency + egress
approvals.

## Acceptance criteria mapping (P7.1)

- **`DocumentParser` interface + registry:** `apps/ingestion/parsers.py` defines the `DocumentParser`
  protocol, `ParsedContent`, `ParserError`, a deny-by-default MIME registry, and `get_parser` /
  `parse_document`. Covered by `test_get_parser_returns_registered_parser`,
  `test_unsupported_mime_denies_by_default`.
- **Dependency-free parsers (text/markdown/csv/json/html):** happy-path + normalization tests
  (`test_plain_text_parses_and_strips`, `test_markdown_passthrough`,
  `test_csv_becomes_pipe_joined_rows`, `test_csv_skips_blank_rows`,
  `test_json_is_flattened_deterministically`, `test_html_extracts_visible_text_and_drops_script_style`).
- **Wired into the build:** `staged_build._embed_into_store` parses through the seam; a `text/csv`
  document builds and is retrievable end-to-end (`test_csv_document_parses_and_is_searchable`, PG);
  unsupported `application/pdf` still fails closed (`test_non_text_mime_fails_closed`).
- **Bounded + fail-closed + content-free:** `test_oversize_output_is_bounded`,
  `test_empty_document_fails_closed`, `test_non_utf8_fails_closed_without_content` (asserts the error
  message is the stable code only), `test_json_invalid_fails_closed`.
- **Security (untrusted data):** HTML `<script>`/`<style>` bodies never reach extracted text; no
  parser fetches remote content or executes embedded markup (threat model T1–T4).

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Format | `ruff format --check .` | Pass — 302 files |
| Lint | `ruff check .` | Pass |
| Type | `mypy apps config` | Pass — 301 files |
| Django check | `manage.py check` | Pass — 0 issues |
| Migration drift | `makemigrations --check --dry-run` | Pass — no changes (no migration) |
| Targeted parsers | `pytest apps/ingestion/tests/test_parsers.py` | 12 passed |
| Final SQLite | `pytest -q` (`config.settings.test`) | 486 passed, 19 skipped (pgvector) |
| Final PostgreSQL | `pytest -q --create-db` (`config.settings.local` + MCP/metrics flags) | 503 passed, 2 skipped (off-PG guards) |

Baseline before this change (P6): SQLite 474 passed / 18 skipped; PostgreSQL 490 passed / 2 skipped.
Delta: +12 parser unit tests (all layers) and +1 PostgreSQL-only CSV end-to-end build test.

## Checks not run

- No live endpoint exercised — P7.1 opens no egress and adds no dependency.
- Binary-format parsing (pdf/docx/xlsx), OCR egress, and Confluence/REST connectors are **not
  implemented** (P7.2–P7.4); their dependency provenance, SSRF/redirect/size/timeout, and
  secret-handling verification will accompany those increments after approval.

## Final reviews

- Staff engineer: one new pure-stdlib module + a small, localized seam change in `staged_build`;
  no migration; the legacy Sprint-5 source pipeline (`pipeline.PARSERS`) is untouched; existing
  text/markdown builds behave identically and previously-unsupported binary MIME still fails closed.
- Application security: documents are treated as untrusted data; parsers execute nothing, fetch
  nothing, and bound output; failures carry stable codes only; telemetry is counts-only; no change to
  tenant isolation, the serving guardrail, or the tool/decision authorization gates.
- SRE: no dependency, no egress, deterministic and hermetic in CI; the change is trivially
  reversible (drop the parser call back to a direct decode).
