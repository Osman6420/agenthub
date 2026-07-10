# Engineering Rules

## Operating standard

Work as a senior enterprise engineer. Understand the affected path before editing. Prefer small, local, reversible changes that fully meet acceptance criteria. Preserve repository conventions and architectural layers; do not route around domain services, policy enforcement, audit, or validation.

Separate domain rules from HTTP/MCP transport, framework/UI concerns, persistence, queues, and providers. Add abstractions only for a demonstrated boundary or repeated need. Do not add a framework or production dependency without explicit approval and a supply-chain/operational review.

## Compatibility and failures

Preserve public API, persisted data, event, and configuration compatibility unless an approved plan states otherwise. Use stable, documented error codes; return safe client messages and retain diagnosable internal context without sensitive data. Never swallow failures or treat partial success as success.

External calls require explicit timeouts, bounded response sizes, controlled destinations, and classified retry behavior. Retry only transient/idempotent work with bounded exponential backoff and jitter. Use idempotency keys for repeatable state changes.

## Data and configuration

Define transaction boundaries around business invariants. Document consistency expectations and concurrency behavior. Migrations must be backward-compatible and staged where possible, with rollout, validation, and rollback/forward-fix plans. Destructive migrations require approval. Detect N+1 access, unbounded reads, missing pagination, and unsafe bulk operations.

Configuration must be validated, environment-neutral, and fail safely. Secrets never belong in source-controlled configuration.

## Repository-specific verified state

As of 2026-07-10, Sprints 0–1 are implemented and verified. The repository contains
a bootable Django modular monolith: `config/` (settings split base/local/test/
production, `celery.py`, `asgi.py`, `wsgi.py`, `urls.py`); `apps/gateway`
(unauthenticated health probes); and the Sprint 1 control-plane apps `apps/tenancy`,
`apps/identity`, `apps/catalog`, `apps/audit`, and the LDAP-authenticated
`apps/console` (the management surface; Django Admin is removed except a local-dev
opt-in — see [ADR-0001](../adr/0001-custom-console-ldap-auth.md)). Tooling:
`pyproject.toml` (deps + `ldap` extra + ruff/mypy/pytest config), `requirements.lock`,
`deploy/` (Dockerfile + Docker Compose for pgvector/Redis/MinIO and web/worker/beat),
`.github/workflows/ci.yml`. The broader [target design](../../agenthub-v3-django-plan.md)
(gateway/ExecutionContext, RAG runtime, ingestion, workflow/agent/tools, evaluation/
release, MCP, metrics, OpenShift manifests) remains *planned, not implemented* and is
delivered per later sprints. LDAP is configured but not yet validated against a live
directory; local/CI/tests run with LDAP disabled (Django model backend).

Repository-verified commands (run from the repo root, in a Python 3.13 venv with
`pip install -e ".[dev]"`): `ruff format --check .`, `ruff check .`, `mypy .`,
`python manage.py makemigrations --check --dry-run`, `python manage.py check`, and
`pytest` — all pass under `DJANGO_SETTINGS_MODULE=config.settings.test` (isolated
SQLite; no external services). Management/operational commands shown in the target
plan that are not in the list above remain proposed future interfaces and must not
be reported as executable today. Integration against real PostgreSQL/pgvector,
Redis, and MinIO (via `deploy/compose/docker-compose.yml`) is not yet part of the
automated verification. Re-inspect manifests and CI whenever implementation is
added, then update this section.

## Review and evidence

Review the final diff for scope, layering, compatibility, authorization, privacy, failure modes, concurrency, operability, and accidental files. Record every executed command and result in task verification. State checks that could not run and the risk this leaves; never infer success from an agent assertion.

## Recommended enforcement (not implemented)

When code and CI arrive, evaluate pre-commit formatting/linting, secret and static-analysis scans, dependency/lockfile and container scans, migration drift checks, protected branches, required CI checks, network/MCP allowlists, isolated production credentials, Codex sandbox/approval rules, and Claude `PreToolUse` restrictions. Adopt them through reviewed changes; do not describe them as active until verified.
