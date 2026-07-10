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

As of 2026-07-10, Sprints 0–4 are implemented and verified (Sprint 4 adds the
`apps/retrieval` and `apps/orchestration` RAG runtime: provider interfaces with
deterministic default providers, a release-bundle resolver, grounding/citation/
fallback policy, and output-contract governance; the gateway now returns real
`completed`/fallback output with token usage. No real vector/LLM call is made yet —
providers plug in via `RUNTIME_MODEL_PROVIDER`/`RUNTIME_RETRIEVAL_PROVIDER`.) The
repository contains
a bootable Django modular monolith: `config/` (settings split base/local/test/
production, `celery.py`, `asgi.py`, `wsgi.py`, `urls.py`); the Sprint 1 control-plane
apps `apps/tenancy`, `apps/identity`, `apps/catalog`, `apps/audit`, and the
LDAP-authenticated `apps/console` (management surface; Django Admin removed except a
local-dev opt-in — see [ADR-0001](../adr/0001-custom-console-ldap-auth.md)); the
Sprint 2 apps `apps/artifacts` (immutable, checksummed, secret-safe versioned
definitions with GitOps import/export) and `apps/releases` (compiled
`ScenarioRelease` with a DB-enforced single-active invariant and a release compiler);
and the Sprint 3 public `apps/gateway` (DRF) — bearer-token consumer auth
(`ConsumerToken`, hashed), alias+capability authorization, per-consumer rate limiting,
idempotency, a standard error envelope, a signed short-lived `ExecutionContext`, and
`POST /v1/invoke` / `POST /v1/query` / `GET /v1/runs/{id}` — plus `apps/observability`
(`UsageEvent`). Answer generation is not yet wired (a runtime facade returns
`accepted`). Management commands: `import_gitops`, `export_gitops`,
`validate_artifacts`, `compile_release`, `create_consumer_token`. Tooling:
`pyproject.toml` (deps incl. DRF/jsonschema/PyYAML + `ldap` extra + ruff/mypy/pytest
config), `requirements.lock`, `deploy/` (Dockerfile + Docker Compose for
pgvector/Redis/MinIO and web/worker/beat), `.github/workflows/ci.yml`. The broader
[target design](../../agenthub-v3-django-plan.md) (RAG runtime, ingestion,
workflow/agent/tools, gated evaluation/release, MCP, metrics, OpenShift manifests)
remains *planned, not implemented* and is delivered per later sprints. Consumer auth
is bearer-token only (OIDC/JWT/mTLS later); LDAP is configured but not yet validated
against a live directory; local/CI/tests run with LDAP disabled. Repository-verified
commands include `ruff`, `mypy`, `pytest` (SQLite and — via `config.settings.local`
— real PostgreSQL), and the management commands above.

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
