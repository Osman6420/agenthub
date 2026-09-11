# Verification — console-org-nav-status-dashboard

Presentation-layer console UX overhaul (Scopes A–H). No schema change, no migration, no
new dependency. The active organization is a display filter only; every action remains
server-authorized.

## Commands and results (2026-07-21)

Run from repo root in `.venv` (Python 3.13).

| Gate | Command | Result |
| --- | --- | --- |
| Format | `ruff format --check apps` | **Pass** — 402 files already formatted |
| Lint | `ruff check apps` | **Pass** — All checks passed |
| Types | `mypy apps` | **Pass** — no issues in 402 source files |
| System check | `manage.py check` (test settings) | **Pass** — 0 issues |
| Migration drift | `manage.py makemigrations --check --dry-run` | **Pass** — No changes detected |
| Bytecode | `python -m compileall apps config` | **Pass** |
| Static resolve | `manage.py findstatic console/console.js` | **Pass** — resolves in `apps/console/static/` |
| Unit/integration (SQLite) | `pytest` (`config.settings.test`) | **Pass** — 966 passed, 37 skipped (skips are PostgreSQL-only) |
| Console (PostgreSQL) | `pytest apps/console --create-db` (`config.settings.local`) | **Pass** — 138 passed (incl. the 19 new UX tests) |
| Vector-store chunk preview (PostgreSQL) | `pytest apps/ingestion/tests/test_vector_store.py -k chunk_preview` | **Pass** — 1 passed |

PostgreSQL profile ran against the Compose `pgvector/pgvector:pg16` service (healthy),
`MCP_ENABLED=true`, `METRICS_BEARER_TOKEN` set, writable `--basetemp` (Windows).

### New tests

- `apps/console/tests/test_console_ux_overhaul.py` (20 tests): switch-organization
  non-member 403 / set / clear / GET-405; forged session id cleared; active-org list
  narrowing; single-org default/static label vs platform-admin all-org default and multi-org
  dropdown; kill-switch banner; dashboard
  operational sections; auditor disabled-Studio-with-reason vs author active link;
  row-clickable rows with a kept anchor; documents advanced-card removed + org-admin
  relocated entry; document-set current-version + "Geçmiş sürümler"; chunk view `None`
  off-PostgreSQL and gated off for a read-only role; workflow-run status/bucket filters,
  tenant-scope-safe filtering, and pagination.
- `apps/ingestion/tests/test_vector_store.py::test_chunk_preview_is_bounded_and_ordered`
  (PostgreSQL): `chunk_counts_by_document` + the new `chunk_preview_for_document` return
  correct counts and an ordered, `max_chunks`-capped, `max_chars`-truncated preview.

### Adjusted existing tests (intent preserved, not weakened)

- `test_phase_2_5_part_1.py::test_disabled_organization_is_not_offered_by_creation_forms`
  — assertion narrowed to the project-creation form's `organization` `<select>` because
  the new sidebar switcher legitimately lists disabled orgs (viewable read-only). The
  invariant (disabled org not offered for creation) is unchanged.
- `test_scenario_artifact_console.py::test_scenario_shows_exact_active_artifact_release_and_project_draft`
  — logs in as `scenario_editor` (was `auditor`) so the now role-gated draft graph link
  renders; the test's data-surfacing intent is preserved.

## Known environmental failures (pre-existing, not from this change)

The affected-app PostgreSQL run also surfaced 2 failures + 7 errors, all in
`apps/ingestion/tests/test_job_lifecycle.py`, which this change does not touch (confirmed
via `git status`):

- 7 errors: `S3ObjectStore.put` → `STORAGE_PUT_FAILED` (MinIO bucket/credential setup for
  the local blob store; the automated suite does not normally exercise MinIO).
- 2 failures: `test_postgres_partial_unique_constraint_is_concurrency_backstop` and
  `test_job_and_outbox_force_rls_under_non_owner` — require the provisioned non-owner app
  role / concurrency setup (CLAUDE.md records that CI/local run as the RLS-bypassing owner).

These are independent of the presentation-layer changes here (no `job_lifecycle`,
`storage`, `outbox`, or role-provisioning files were modified).

## Not run / residual

- Headless-browser drive of the row-click and org-switch JS (progressive enhancement;
  the server-rendered flows are covered by the client-based tests, and no-JS paths keep a
  real anchor + submit button).
- Live display of the chunk preview against a fully built managed-document index (the
  DAL read path is proven on PostgreSQL; building a full staged index in-test is out of
  scope — covered by the existing staged-build PostgreSQL tests plus the new preview test).
- Dark theme was **not** added in this change (listed as a later console improvement).

## 2026-07-22 review correction

- Aligned the single-organization default with the plan: a non-platform user with one
  visible organization now persists that organization as the active workspace; a platform
  admin still defaults to all organizations.
- Clarified that authorized GET deep-links do not mutate the session and that operation-specific
  capability decisions remain in their owning views/services rather than the context processor.
- Targeted SQLite regression: **38 passed, 5 PostgreSQL-only skipped** across the console UX,
  adjusted console regression, and vector-store suites.
- `ruff format --check`, `ruff check`, `manage.py check`, and
  `makemigrations --check --dry-run` all passed for the corrected tree.
