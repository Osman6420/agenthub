# Verification: phase-2-5-part-4-document-set-lifecycle

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Baseline and scope inspection | Serena symbol overviews/lookups plus targeted `rg` | Passed | Existing set upload/publish/index and storage/purge boundaries mapped | 2026-07-15 |
| Focused Part 4 and compatibility suite (SQLite) | `pytest apps/console/tests/test_phase_2_5_part_4.py apps/console/tests/test_documents_console.py apps/console/tests/test_phase_2_5_part_2.py apps/console/tests/test_document_workspace_console.py apps/documents/tests/test_services.py` | Passed | 41 passed | Full pytest output; no `-q`; timeout-free background process |
| Full repository (SQLite) | `pytest --basetemp=.pytest-tmp-part4-sqlite-final` | Passed | 673 passed, 29 skipped | PostgreSQL/pgvector-only skips; full output; timeout-free process |
| Static and schema gates | `ruff format --check apps`; `ruff check apps`; `mypy .`; `manage.py check`; `makemigrations --check --dry-run`; `compileall`; `git diff --check` | Passed | Ruff clean; mypy clean across 367 files; Django/schema/compile/diff checks clean | No dependency or schema files changed |
| Full repository (PostgreSQL) | `pytest --ds=config.settings.local --basetemp=.pytest-tmp-part4-pg-final` with MCP/metrics test profile | Passed | 697 passed, 5 skipped in 295.16s | Full output; no `-q`; timeout-free process; PostgreSQL/pgvector/RLS paths ran |
| Runtime preflight/restart | Compose `ps`, health endpoint, canonical host-mode restart | Passed | PostgreSQL/Redis/MinIO healthy; web health HTTP 200 after restart | No migration or database reset applied |
| Browser render | In-app browser to `/console/documents/` | Partial | Turkish login page rendered; authenticated page redirected to login | No credential requested or test user written |

## Acceptance criteria mapping

All criteria are implemented and automated-verified on SQLite and PostgreSQL. Authenticated Turkish
owner browser acceptance remains the only completion item.

## Security requirement mapping

Cross-tenant set/document lookup, role-gated advanced inventory, frozen snapshot protection,
tombstone/purge preservation, bounded upload validation, and audit rollback are covered.

## Authorization tests

Reader/author/org-admin separation passed in the focused suite.

## Cross-tenant tests

Cross-tenant set detail, replacement, tombstone and draft removal returned 404 without mutation.

## Logging and redaction tests

Document detail excludes object keys, checksums and raw content. Dedicated secret scanner remains
unavailable in this repository.

## Audit event tests

Upload, upsert, draft removal and tombstone audit events were asserted; removal rolls back when audit
persistence raises.

## Migration verification

No migration was required; `makemigrations --check --dry-run` reported no changes.

## Behavior comparison with base branch

Primary content navigation is set-first; legacy internal service/public console routes remain
compatible. Final architecture/AppSec/SRE diff review found no unmitigated release blocker.

## Checks not run

Authenticated Turkish browser journey and dedicated secret scanning were not run. The repository has
no dedicated secret-scanner command; Ruff security checks and targeted response-redaction assertions
passed.

## Remaining risks

See `threat-model.md`; Turkish browser owner review will remain after automated verification.

## Human review required

Turkish document-set lifecycle, advanced inventory discoverability, blocker wording, confirmation
copy, responsive behavior, and accessibility.

## Final status

Verified. Automated Definition of Done checks passed; authenticated Turkish owner browser review is
required before `Completed`.
