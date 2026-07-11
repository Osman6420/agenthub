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

As of 2026-07-11, Sprints 0–6 are implemented and verified (Sprint 4 adds the
`apps/retrieval` and `apps/orchestration` RAG runtime: provider interfaces with
deterministic default providers, a release-bundle resolver, grounding/citation/
fallback policy, and output-contract governance; the gateway now returns real
`completed`/fallback output with token usage. Embeddings and answer generation are
still deterministic stubs — no real LLM/embedding-model call is made yet; model and
retrieval providers plug in via `RUNTIME_MODEL_PROVIDER`/`RUNTIME_RETRIEVAL_PROVIDER`.)
The repository contains
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
(`UsageEvent`); the Sprint 4 runtime returns real grounded/fallback output. Sprint 5
adds `apps/ingestion` (tenant-scoped `Source`s, bounded allowlisted HTTPS/S3
connectors, parse/chunk/deterministic-embed pipeline, staged pgvector/HNSW
`IndexVersion`s, source advisory locks, retry/dead-letter with audit) and a real
pgvector cosine retriever (`PgvectorRetrievalProvider`, now the default
`RUNTIME_RETRIEVAL_PROVIDER`). Control-plane authoring adds role-gated, audited console
create forms and an idempotent GitOps `import_control_plane` for organizations/
projects/scenarios/aliases/consumers/bindings.

Sprint 6 is implemented and verified: governed evaluation plus a
fail-closed release lifecycle. An `eval_suite` artifact (bounded cases, allowlisted
deterministic assertions — data, not code) is validated at author time; `apps/
evaluations` runs a candidate release against its manifest-pinned suite *in isolation*
(`run_rag(require_active=False)`) and persists a redacted, audited report (assertion
type, boolean, stable reason code only). `apps/releases/lifecycle.promote` is
fail-closed — it requires a passing eval bound to the pinned suite checksum and ready,
tenant-owned pinned indexes — and `rollback` atomically restores a superseded release.
Releases can now pin `index_versions` in the manifest and the resolver feeds them to
the retriever, so a release pinning a ready index reaches the pgvector retriever
end-to-end (this closes the earlier always-empty `ReleaseBundle.index_versions` gap).
Consumer-scoped, time-bounded canary routing uses `select_release` only after binding
authorization; the gateway serves active/canary releases and rejects a raw candidate.
Role-protected operator-console lifecycle actions and the `run_eval`,
`promote_release`, `rollback_release`, `start_canary`, and `stop_canary` commands are
implemented. `compile_release --promote` is fail-closed. Management commands today:
`import_gitops`, `export_gitops`, `validate_artifacts`, `compile_release`, `run_eval`,
`promote_release`, `rollback_release`, `start_canary`, `stop_canary`,
`create_consumer_token`, `start_ingestion`, `retry_ingestion`, and
`import_control_plane`.
Tooling:
`pyproject.toml` (deps incl. DRF/jsonschema/PyYAML + `ldap` extra + ruff/mypy/pytest
config), `requirements.lock`, `deploy/` (Dockerfile + Docker Compose for
pgvector/Redis/MinIO and web/worker/beat), `.github/workflows/ci.yml`. The remaining
[target design](../../agenthub-v3-django-plan.md) (real model/embedding providers and
workflow/agent/tools) remains *planned, not implemented* and is delivered per later
sprints. Sprint 7 MCP/metrics/OpenShift assets are described below. Consumer auth
is bearer-token only (OIDC/JWT/mTLS later); LDAP is configured but not yet validated
against a live directory; local/CI/tests run with LDAP disabled. Repository-verified
commands include `ruff`, `mypy`, `pytest` (SQLite and — via `config.settings.local`
— real PostgreSQL), and the management commands above.

Repository-verified commands run from the repo root in the project virtualenv
(`.venv`, Python 3.13; `requires-python >= 3.13`). Re-run `pip install -e ".[dev]"`
after any dependency change — a venv created before Sprint 5 lacks `boto3`/`pgvector`
and cannot import `apps.ingestion`. Gates: `ruff format --check .`, `ruff check .`,
`mypy .`, `python manage.py makemigrations --check --dry-run`, `python manage.py
check`, and `pytest`. They pass both under `DJANGO_SETTINGS_MODULE=config.settings.test`
(isolated in-memory SQLite; no external services) and — via
`DJANGO_SETTINGS_MODULE=config.settings.local` with `pytest --create-db` against the
Compose PostgreSQL/pgvector — on real PostgreSQL, where the pgvector cosine-retrieval
and advisory-lock tests that SQLite skips also run. Redis and MinIO are not yet
exercised by the automated suite. Management/operational commands shown in the target
plan that are not listed above remain proposed future interfaces and must not be
reported as executable today.

Sprint 7 is implemented and verified:
`apps.mcp` provides authenticated stateless MCP JSON-RPC/Streamable HTTP operations and
delegates invoke/query to the existing gateway policy/routing seam; observability adds
bounded Prometheus metrics and W3C/OTLP HTTP+Celery tracing; readiness includes migration
state; and deployment/monitoring/runbook drafts are present. The approved production
dependencies are `opentelemetry-api`, `opentelemetry-sdk`, the OTLP HTTP exporter, and
`prometheus-client`. The completed Sprint 6 canary contract is covered by MCP/REST
parity tests. Live OTel/Prometheus/Grafana/OpenShift checks remain an operational
follow-up; do not describe the draft manifests as deployed infrastructure.

Sprint 8 is implemented and verified. `apps.workflows` provides strict artifact
validation, deterministic immutable DAG compilation, additive workflow/custom-node/run
models, bounded asynchronous Celery execution, redacted durable state/events,
idempotency, tenant-scoped status/cancel, contract/policy enforcement, and workflow
eval assertions. `POST /v1/invoke` returns `202` plus `run_id` for an authorized
workflow scenario and requires `workflow_run` plus an `Idempotency-Key`; `GET`/`DELETE
/v1/runs/{id}` are consumer/tenant scoped. Custom nodes are platform-preinstalled,
organization-allowlisted, exact-version matched, schema-checked, and receive only a
narrow execution context. No workflow-engine dependency was added.

Sprint 9 (tool registry + approval) is *in progress*, delivered as verified increments.
Increment A is implemented and verified (SQLite + PostgreSQL): `apps.tools` adds
`tool_definition` / `tool_binding` artifact validation (bounded, allowlisted,
https-only destinations with IP/private/`.internal`/`localhost` hosts rejected,
`critical` risk disabled, credentials only as `secret:<name>` references), the
tenant-scoped immutable `ToolDefinition` / `ToolBinding` registry models (write-once
body, status-only mutation), registration services enforcing the high-risk
side-effecting approval invariant, and fail-closed release pinning of active,
checksum-matched bindings into the manifest. Increment B adds the central default-deny
`apps.tools.proxy.invoke_tool` (capability, input/output contracts, field allowlists,
risk/approval gate), SSRF-safe destination validation (`apps.tools.egress`:
public-unicast-only with resolved-IP checks defeating DNS rebinding), and the
transport-adapter and least-privilege `secret:<name>` resolver seams, plus
`resolve_release_tool` that reads the pinned binding/definition/contracts. **The default
adapter performs no network I/O and the proxy has no production caller yet — the
platform still performs no live tool egress**, and a high-risk side-effecting tool
raises `ToolApprovalRequired` rather than executing. No production dependency was added.
Increments C–D (the real HTTP/MCP adapter + its network dependency, requiring explicit
approval; approval lifecycle + idempotent durable resume + workflow pause/resume;
console/API/MCP surfaces, audit, metrics) remain planned and require explicit approval
for authorization, public API, secret, dependency, and network changes.

This "Repository-specific verified state" section is `@`-imported by `CLAUDE.md` into
every agent's context: it is the always-loaded, canonical statement of what is
implemented/verified and how to run the gates. Update it in the same change that lands
or verifies an implementation increment — not only `docs/planning/master-plan.md` — so
the next Codex/Claude handoff starts from accurate ground truth. Re-inspect manifests
and CI whenever implementation is added.

## Review and evidence

Review the final diff for scope, layering, compatibility, authorization, privacy, failure modes, concurrency, operability, and accidental files. Record every executed command and result in task verification. State checks that could not run and the risk this leaves; never infer success from an agent assertion.

## Recommended enforcement (not implemented)

When code and CI arrive, evaluate pre-commit formatting/linting, secret and static-analysis scans, dependency/lockfile and container scans, migration drift checks, protected branches, required CI checks, network/MCP allowlists, isolated production credentials, Codex sandbox/approval rules, and Claude `PreToolUse` restrictions. Adopt them through reviewed changes; do not describe them as active until verified.
