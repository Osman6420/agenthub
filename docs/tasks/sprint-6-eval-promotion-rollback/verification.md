# Verification: sprint-6-eval-promotion-rollback

Scope of this record: the first Sprint 6 increment — governed evaluation, the
fail-closed promotion/rollback lifecycle, and manifest index-version pins. Canary
routing, console lifecycle actions, and management commands are **not** in this
increment and are not claimed here.

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

## Not verified in this increment / residual risk

- Consumer-scoped canary routing, console lifecycle actions, and management commands
  are unimplemented; the gateway public path is unchanged (no candidate is reachable
  publicly). Public canary routing requires explicit approval before implementation.
- Deterministic stub providers prove governance, not model/answer quality.
- Audit persistence for denied promotions is written before the raising path; a
  durable fail-closed audit sink is a later hardening step.
- Concurrent promote/rollback correctness relies on `select_for_update` + the DB
  single-active partial-unique constraint; a dedicated concurrency test is deferred to
  the canary/console increment.
