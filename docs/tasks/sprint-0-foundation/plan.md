# Task Plan: sprint-0-foundation

## Task summary

Establish the AgentHub Django modular-monolith foundation and an enforceable
local/CI toolchain, per Sprint 0 of the [v3 target plan](../../../agenthub-v3-django-plan.md#25-uygulama-asamalari)
and Milestone 2 of the [master plan](../../planning/master-plan.md). This is the
first executable code in a previously documentation-only repository.

## Background

The repository contained only architecture/planning Markdown. To implement the
target plan safely and verifiably, we first need a bootable Django project,
settings split, Celery process definitions, health endpoints, container/dev
environment, and a CI baseline that fails on lint/type/migration drift.

## Scope

- Django project skeleton: `config/` (settings split, urls, asgi, wsgi, celery).
- `apps/` package and the first app (`gateway`) hosting liveness/readiness probes.
- Dependency + tooling manifest (`pyproject.toml`): Django, Celery[redis], Redis,
  django-environ, psycopg; dev: pytest-django, ruff, mypy, django-stubs.
- Local dev environment via Docker Compose: PostgreSQL+pgvector, Redis, MinIO,
  and the `web`/`worker`/`beat` roles from the same image.
- CI workflow: lint (ruff), format check, type-check (mypy), migration drift
  check, and unit tests (pytest, isolated SQLite test settings).
- Structured-logging and configuration-validation scaffolding.

## Non-goals

- No domain models yet (tenancy/identity/catalog land in Sprint 1).
- No authentication/authorization, gateway API, RAG runtime, ingestion, tools,
  or agent runtime. Health endpoints are unauthenticated liveness/readiness only.
- No pgvector-backed models, DRF, MCP, metrics endpoint, or OpenShift manifests
  (added in their respective sprints).

## Acceptance criteria

From v3 plan Sprint 0:

- `migrate`, the web role, and all worker roles start in the local environment.
- Tests run under isolated test settings (no external services required).
- Migration drift fails CI (`makemigrations --check --dry-run`).

## Affected components

Platform foundation/control plane (new). No behavior change elsewhere; repo was
docs-only.

## Interfaces affected

New unauthenticated operational endpoints: `GET /v1/health/live`,
`GET /v1/health/ready`. No public product API in this task.

## Data impact

Django built-in migrations only (auth/contenttypes/sessions/admin) for local dev.
No custom domain tables; no PII; no tenant data.

## Security impact

- Health endpoints are unauthenticated by design and must not leak stack traces,
  connection strings, or secrets; readiness returns coarse ok/error per check.
- Secrets are read from the environment only; none are committed. `production.py`
  fails closed when `DJANGO_SECRET_KEY`/`ALLOWED_HOSTS` are unset.
- `DEBUG` defaults to False; production enables secure cookies, HSTS, SSL redirect.

## Authorization impact

None yet. No roles, tenants, or capabilities are introduced in Sprint 0.

## Observability impact

Structured logging config with a stable JSON-ish formatter is scaffolded.
Health readiness surfaces per-dependency status for operators. Metrics/tracing
arrive in Sprint 7.

## Migration impact

Only Django framework migrations are applied locally. `makemigrations --check`
must report no missing migrations for our apps (none have models yet).

## Dependencies

New production dependencies (require the approval captured by the user
instruction to implement the plan): Django, celery[redis], redis, django-environ,
psycopg. Dev: pytest, pytest-django, ruff, mypy, django-stubs. External dev
services: PostgreSQL+pgvector, Redis, MinIO (via Docker Compose only).

## Implementation steps

1. Add `pyproject.toml` with dependencies and tool config (ruff, mypy, pytest).
2. Create `manage.py` and `config/` (settings base/local/test/production, urls,
   asgi, wsgi, celery).
3. Create `apps/gateway` with liveness/readiness views, urls, and tests.
4. Add Docker Compose (pg+pgvector, redis, minio, web, workers, beat) and
   `deploy/Dockerfile`.
5. Add `.env.example`, `.gitignore`, `.dockerignore`, `.pre-commit-config.yaml`.
6. Add `.github/workflows/ci.yml` (lint, format, typecheck, migration-check, test).
7. Create venv, install, and run all checks; record evidence in `verification.md`.
8. Update master plan and engineering-rules verified-state section.

## Test plan

- Unit: `GET /v1/health/live` returns 200; `GET /v1/health/ready` reports per-check
  status and returns 503 when a dependency check fails (dependency access is
  faked so tests need no external services).
- Repository checks: `ruff check`, `ruff format --check`, `mypy`,
  `manage.py makemigrations --check --dry-run`, `pytest`.

## Rollout plan

Additive only; no existing behavior to preserve. Merge behind CI gates.

## Rollback plan

Revert the commit; repository returns to documentation-only state. No data or
external state is created outside ephemeral local Docker volumes.

## Risks

- Dependency versions may drift; mitigated by constraint ranges + recorded
  `pip freeze` evidence.
- SQLite test settings do not exercise Postgres/pgvector specifics; integration
  tests against Postgres arrive with the first pgvector models (Sprint 5).
- Health readiness check must stay non-leaky; covered by test and review.

## Open questions

- Exact pinned dependency versions and lockfile tooling (pip-tools vs uv) to be
  confirmed before first production build.

## Status

Verified — all repository checks (ruff format/lint, mypy, migration drift,
system check, pytest) and role smoke checks passed on 2026-07-10; evidence in
[`verification.md`](verification.md). Not yet `Completed`: Docker Compose
full-topology boot and human review remain.

## Completion criteria

Map to the [Definition of Done](../../ai/definition-of-done.md): formatter, linter,
type-check, unit tests, and migration drift check pass with recorded evidence;
health endpoints do not leak sensitive data; current-state docs updated.
