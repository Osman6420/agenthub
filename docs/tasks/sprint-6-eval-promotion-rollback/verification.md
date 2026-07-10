# Verification: sprint-6-eval-promotion-rollback

Scope of this record: all of Sprint 6 — governed evaluation, the fail-closed
promotion/rollback lifecycle, manifest index-version pins (increment A), and
consumer-scoped canary routing, console lifecycle actions, and management commands
(increment B). The two increments landed as two commits.

## Cross-agent note

Sprint 7 (`apps/mcp`, observability metrics/tracing) was implemented by Codex in a
parallel session and is present, uncommitted, in the shared working tree. This Sprint 6
work does not modify any Sprint 7 file. On the full PostgreSQL run, 8 Sprint 7 tests
(`apps/mcp/tests`, `apps/observability/tests`) fail — they pass on SQLite and are
Codex's to resolve; every Sprint 6 test passes on both databases (see below). The
Sprint 6 commit stages only Sprint 6 files.

## Environment

- Interpreter: `.venv` (Python 3.13), dependencies from `requirements.lock`
  (`pip install -e ".[dev]"`). No new production dependency was added.
- SQLite gates: `DJANGO_SETTINGS_MODULE=config.settings.test` (in-memory).
- PostgreSQL/pgvector gates: `DJANGO_SETTINGS_MODULE=config.settings.local` against the
  Docker Compose `pgvector/pgvector:pg16` database, run with `pytest --create-db`.

## Commands and results

| Command | Result |
| --- | --- |
| `ruff format --check .` | Pass — 141 files formatted |
| `ruff check .` | Pass — all checks passed |
| `mypy .` | Pass — no issues in 141 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes detected |
| `pytest` (SQLite, `config.settings.test`) | Pass — 108 passed, 2 skipped (PostgreSQL-only) |
| `pytest --create-db` (real PostgreSQL/pgvector) | Pass — 110 passed |

New migration: `apps/evaluations/migrations/0001_initial.py` (additive — `EvalRun`,
`EvalCaseResult`, gate-lookup index, per-run/case unique constraint). No destructive
change; applied cleanly on SQLite and PostgreSQL via `--create-db`.

## Acceptance criteria evidence (this increment)

- A failed or missing required eval blocks promotion — `test_lifecycle.py::
  test_promotion_without_eval_is_denied_and_audited`,
  `test_promotion_without_pinned_suite_is_denied`.
- Candidate eval cannot change the active pointer — `test_evaluations.py::
  test_passing_eval_records_passed_run_without_touching_active_pointer`.
- Promotion atomically activates the candidate and supersedes the previous active —
  `test_lifecycle.py::test_passing_eval_allows_promotion_and_supersedes_previous`.
- Rollback atomically restores a superseded release — `test_rollback_restores_a_
  superseded_release`; non-superseded targets are rejected.
- Index-readiness gate + end-to-end pin — `test_promotion_blocked_when_pinned_index_
  not_ready`, `test_promotion_succeeds_with_ready_tenant_index` (asserts the pin
  resolves into `ReleaseBundle.index_versions`).
- Reports carry no raw content — `test_report_is_redacted_to_reason_codes_only`.
- Eval loader rejects unknown/oversized/malformed suites — `test_eval_suite.py` (10
  cases incl. unknown assertion type, empty value, bad count, boolean count, duplicate
  ids, too many cases, oversized input, unknown top-level key).
- Authorization helper — `test_can_manage_releases_requires_release_manager_role`.

## Increment B — canary routing, console actions, management commands

New migration: `apps/releases/migrations/0002_releasecanary.py` (additive —
`ReleaseCanary` with a partial-unique active canary per (scenario, consumer)). Applied
cleanly on SQLite and PostgreSQL.

Gates re-run after increment B (`.venv`, Python 3.13):

| Command | Result |
| --- | --- |
| `ruff format --check .` / `ruff check .` | Pass |
| `mypy .` | Pass — no issues in 170 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes |
| `pytest` (SQLite, full tree incl. Sprint 7) | 140 passed, 2 skipped |
| Sprint 6 subset on PostgreSQL (`--create-db`) | 62 passed |

The full PostgreSQL run shows 8 failures, all in Sprint 7 files
(`apps/mcp/tests`, `apps/observability/tests`) that pass on SQLite — Codex's Sprint 7
to resolve, unrelated to Sprint 6 (every Sprint 6 test passes on PostgreSQL).

Acceptance criteria evidence (increment B):

- A canary consumer routes to its eligible candidate; others stay active —
  `test_lifecycle.py::test_canary_routes_only_the_assigned_consumer`.
- Canary reuses the fail-closed eval gate — `test_canary_requires_passing_eval`.
- Cross-tenant canary is denied server-side — `test_canary_rejects_cross_tenant_consumer`.
- Time-bounding: an expired canary falls back to the active release —
  `test_expired_canary_falls_back_to_active`.
- Stop reverts an unused canary release to candidate — `test_stop_canary_reverts_release_to_candidate`.
- Commands enforce release-manager auth + resolve the CLI actor —
  `test_lifecycle_commands.py` (non-manager/unknown-actor denied; manager promotes).
- Console actions are role-gated, POST-only, and fail safely —
  `test_release_actions.py` (403 for non-manager; graceful 302 denial; 405 on GET).

## Residual risk

- Deterministic stub providers prove governance, not model/answer quality.
- Audit persistence for denied promotions is written before the raising path; a durable
  fail-closed audit sink is a later hardening step.
- Concurrent promote/rollback/canary correctness relies on `select_for_update` + the DB
  single-active / active-canary partial-unique constraints; a dedicated concurrency
  test remains a follow-up.
- Expired canaries are ignored at read time but not lazily flipped to `expired` status;
  a sweep/command can reconcile status later (no correctness impact on routing).
