# Verification: phase-2-p7-parsers-ocr-connectors

## Status

**P7.1 + P7.2 Verified 2026-07-13.** Automated evidence only. P7.1 parsers are pure-stdlib; P7.2
pdf/docx/xlsx parsing is **local and in-process** (owner-approved libraries), so no socket is opened
and no live endpoint is called. P7.3 (OCR egress) and P7.4 (Confluence/REST connectors) are **not
implemented** — deferred by the owner, blocked on their environment-specific egress sign-off.

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

## Acceptance criteria mapping (P7.2)

- **Local binary parsers on the same interface:** `PdfParser`/`DocxParser`/`XlsxParser` register
  `application/pdf` / docx / xlsx MIME types and extract text in-process (deferred imports). Covered by
  `test_pdf_text_is_extracted`, `test_docx_paragraphs_and_tables_are_extracted`,
  `test_xlsx_cells_become_pipe_joined_rows`.
- **Fail-closed on malformed input, content-free codes:** `test_pdf_malformed_fails_closed`,
  `test_docx_malformed_fails_closed`, `test_xlsx_malformed_fails_closed` (each asserts a stable code
  and that the error message is the code only).
- **End-to-end through the build:** `test_docx_document_parses_and_is_searchable` (PG) uploads a real
  `.docx`, builds a staged index, and retrieves it; `test_non_text_mime_fails_closed` (PG) proves an
  operator-allowed-but-unparsed MIME (`image/png` → OCR is deferred P7.3) still fails closed.
- **Approved dependency, no egress:** deps added to `pyproject.toml`, `requirements.lock` regenerated,
  `pip check` clean; parsing opens no socket (CI hermetic).

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Format | `ruff format --check .` | Pass — 303 files |
| Lint | `ruff check .` | Pass |
| Type | `mypy apps config` | Pass — 302 files |
| Django check | `manage.py check` | Pass — 0 issues |
| Migration drift | `makemigrations --check --dry-run` | Pass — no changes (no migration) |
| Dependency tree | `pip check` | Pass — no broken requirements |
| Targeted P7.1 parsers | `pytest apps/ingestion/tests/test_parsers.py` | 12 passed |
| Targeted P7.2 binary | `pytest apps/ingestion/tests/test_binary_parsers.py` | 6 passed |
| Final SQLite | `pytest -q` (`config.settings.test`) | 492 passed, 20 skipped (pgvector) |
| Final PostgreSQL | `pytest -q --create-db` (`config.settings.local` + MCP/metrics flags) | 510 passed, 2 skipped (off-PG guards) |

Baseline before P7 (P6): SQLite 474 passed / 18 skipped; PostgreSQL 490 passed / 2 skipped.
Cumulative P7 delta: +12 stdlib-parser + 6 binary-parser unit tests, +1 CSV and +1 DOCX
PostgreSQL-only end-to-end build test (18 new unit + 2 new PG e2e).

## Checks not run

- No live endpoint exercised — P7.1/P7.2 open no egress. P7.2 added local, owner-approved parsing
  libraries only.
- OCR egress and Confluence/REST connectors are **not implemented** (P7.3–P7.4, deferred); their
  SSRF/redirect/size/timeout and secret-handling verification will accompany those increments after
  the egress sign-off.
- No headless/live-server smoke of an uploaded PDF/DOCX/XLSX through the operator API + a real object
  store; parsing is proven by unit round-trips and the PostgreSQL end-to-end staged-build tests.

## Final reviews

- Staff engineer: one parser module + a small, localized seam change in `staged_build`; no migration;
  the legacy Sprint-5 source pipeline (`pipeline.PARSERS`) is untouched; existing text/markdown builds
  behave identically. P7.2 adds three parsers with deferred imports so the module stays stdlib-only to
  import; MIMEs with no parser (image/*) still fail closed.
- Application security: documents are treated as untrusted data; parsers execute nothing and fetch
  nothing (local, in-process; `openpyxl` reads values not formulas/macros); output and elements are
  bounded; failures carry stable codes only; telemetry is counts-only; no change to tenant isolation,
  the serving guardrail, or the tool/decision authorization gates.
- SRE: the only new surface is three owner-approved, permissive-licensed local libraries (no egress);
  `pip check` clean and `requirements.lock` regenerated; deterministic + hermetic in CI; reverting is
  removing the three `PARSERS` entries (and, if desired, the pins).
