# Verification: sprint-8-workflow-core

## Status

Verified on SQLite and PostgreSQL.

## Commands and evidence

- Focused artifact/compiler foundation: `16 passed`.
- Focused gateway/runtime/release/artifact integration: `46 passed`.
- Expanded workflow/evaluation/gateway/release integration: `66 passed`, then `89 passed`.
- Final workflow policy/custom-node focused suite: `19 passed`.
- Repository-wide `ruff format --check .`: passed for 184 files.
- Repository-wide `ruff check .`: passed.
- Repository-wide `mypy .`: passed for 184 source files.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `python manage.py check`: no issues.
- Full SQLite suite: `161 passed, 2 skipped`; skips are PostgreSQL-only pgvector and
  advisory-lock tests.
- Full PostgreSQL/pgvector + Redis suite: `163 passed`.
- Additive migrations: `artifacts.0002_alter_artifactversion_type` and
  `workflows.0001_initial`; both applied through clean test database creation.
- Local PostgreSQL migration smoke: `manage.py migrate --noinput` applied
  `artifacts.0002`, `evaluations.0001`, `releases.0002`, and `workflows.0001` cleanly.
- Local web smoke after restart: Uvicorn PID `2064`; `/v1/health/live` returned `200`,
  `/v1/health/ready` returned `200` with database/migrations/Redis `ok`, and
  `/console/` returned the expected unauthenticated `302` redirect.

## Unavailable checks

- A standalone local worker connected and consumed a stale broker message, but a full
  successful non-eager workflow execution, soak/load test, and deliberate broker
  redelivery fault injection were not run.
- No external custom-node package/image registry exists; tests use a synthetic
  pre-installed executor registry and exact package-version checks.
- No live provider calls are made; retrieve/generate nodes use deterministic governed
  behavior consistent with the repository's current provider baseline.

## Residual risks

- In-process custom nodes share worker OS privileges; only reviewed pre-installed code
  is allowed, but stronger process isolation remains future hardening.
- The redacted durable input preserves numeric/boolean structure but replaces strings;
  workflows requiring raw confidential text need a separately approved encrypted or
  short-lived payload design rather than weakening redaction.
- Cancellation is cooperative between nodes; an already-running provider/custom-node
  call cannot be forcibly rolled back.
- Concurrent starts rely on the database unique constraint; an insert race is caught
  and resolved to the winning identical run, while a different checksum fails closed.
- A live local worker exposed a stale Redis message referencing a deleted pytest run;
  missing-run delivery is now an explicit logged no-op and has regression coverage.
- Deterministic retrieve/generate nodes prove governance and orchestration, not real
  model quality or provider behavior.
