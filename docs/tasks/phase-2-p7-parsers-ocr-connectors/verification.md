# Verification: phase-2-p7-parsers-ocr-connectors

## Status

**P7.1–P7.3 Verified 2026-07-13.** P7.3 implements the owner-approved async Markdown OCR contract
behind an opt-in platform profile. Tests use an injected offline transport; no live OCR hostname,
credential or socket was configured/called. P7.4 connectors remain contract/egress-gated.

The detailed service contract and OpenAPI document received on 2026-07-13 are retained under
[`docs/ocr_api`](../../ocr_api/API_CONTRACT.md). A compatibility review found one semantic mismatch:
ACK `410 RESULT_GONE` was treated as success. The client now accepts only `204` as ACK success and
tests `ACKNOWLEDGED`/`EXPIRED`, `503` retry, `410` terminal handling, and service-URL non-following.

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

## Acceptance criteria mapping (P7.3)

- **Platform-only endpoint governance:** immutable revisioned `OcrProfile`, platform-admin create,
  per-tenant grant and `OCR_SECRET_*` resolution. Audit excludes host/secret values.
- **Exact API contract:** multipart field is exactly `file`, PDF content type, `202` job UUID,
  catalog-derived GET poll/result paths, raw UTF-8 `text/markdown`, bodyless idempotent ACK. Only
  HTTP `204` records ACK success; `410 RESULT_GONE` is terminal.
- **SSRF/transport:** public-IP validation/pinning, TLS hostname, redirect denial, response caps;
  service-supplied URLs are never followed. Private DNS and redirect tests fail closed.
- **Retry semantics:** submit timeout is `OCR_SUBMIT_OUTCOME_UNKNOWN` and is not retried; polling is
  bounded; ACK alone has a safe retry because the approved service contract makes it idempotent.
- **Durable-before-ACK:** `DocumentOcrJob` reserves lineage before submit, persists job id, writes
  checksumed Markdown to tenant object storage and commits its reference before ACK. Retry reuses
  the result; purge removes both original and derived blobs.
- **Complete PDF text:** fully image-only and mixed text/image PDFs go through whole-PDF OCR when a
  profile is supplied; otherwise the build fails closed. PostgreSQL e2e proves OCR Markdown → chunk
  → deterministic embedding → per-index pgvector search.

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Format | `ruff format --check .` | Pass — 314 files |
| Lint | `ruff check .` | Pass |
| Type | `mypy apps config` | Pass — 313 files |
| Django check | `manage.py check` | Pass — 0 issues |
| Migration drift | `makemigrations --check --dry-run` | Pass — migration `ingestion.0006` is current |
| Dependency tree | `pip check` | Pass — no broken requirements |
| Targeted P7.1 parsers | `pytest apps/ingestion/tests/test_parsers.py` | 12 passed |
| Targeted P7.2 binary | `pytest apps/ingestion/tests/test_binary_parsers.py` | 7 passed |
| Targeted P7.3 + shared transport/lifecycle | `pytest test_ocr.py test_http_adapter.py test_binary_parsers.py test_services.py` | 35 passed |
| Detailed OCR contract review | `pytest test_ocr.py test_http_adapter.py` | Pass — 21 passed; ACK `410`, terminal statuses, `503` retry, URL non-following covered |
| Supplied OpenAPI parse/surface | `yaml.safe_load(docs/ocr_api/openapi.yaml)` + exact expected path assertion | Pass — OpenAPI 3.1.0, six expected paths |
| PostgreSQL OCR e2e | `pytest ...::test_image_only_pdf_ocr_is_persisted_embedded_and_searchable --create-db` | 1 passed |
| Final SQLite | `pytest -q --basetemp=.tmp/pytest-p7-3-final` (`config.settings.test`) | 519 passed, 22 skipped |
| Final PostgreSQL | `pytest -q --create-db --basetemp=.tmp/pytest-p7-3-pg-release` (`config.settings.local` + MCP/metrics flags) | 539 passed, 2 skipped |

Baseline before P7 (P6): SQLite 474 passed / 18 skipped; PostgreSQL 490 passed / 2 skipped.
Cumulative P7.3 delta from P8 baseline: +7 offline OCR/profile/persistence tests, +1 mixed-PDF
fail-closed test and +1 PostgreSQL OCR-to-index e2e, plus migration coverage.

## Checks not run

- No live OCR endpoint exercised; concrete host, platform profile registration, allowlist DNS and
  injected bearer secret remain deployment verification.
- Confluence/REST connectors are not implemented (P7.4); their contracts and egress sign-off remain.
- No headless/live-server smoke of an uploaded PDF/DOCX/XLSX through the operator API + a real object
  store; parsing is proven by unit round-trips and the PostgreSQL end-to-end staged-build tests.

## Final reviews

- Staff engineer: P7.3 adds an explicit OCR catalog/client/orchestration seam and one additive
  migration. Legacy source ingestion remains untouched; staged builds opt in via `--ocr-profile-id`.
- Application security: documents are treated as untrusted data; parsers execute nothing and fetch
  nothing (local, in-process; `openpyxl` reads values not formulas/macros); output and elements are
  bounded; failures carry stable codes only; telemetry is counts-only; no change to tenant isolation,
  the serving guardrail, or the tool/decision authorization gates.
- SRE: recoverable job lineage prevents routine worker retry from resubmitting paid OCR; polling and
  payloads are bounded. `outcome_unknown` submit needs manual reconciliation. No new dependency;
  migration is additive; CI remains offline/hermetic.
