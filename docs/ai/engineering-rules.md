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
default to deterministic stubs. Phase 2 P1 added an opt-in real chat provider with a
platform-managed profile catalog and shared SSRF-safe transport; no live endpoint is configured or
called in CI. Phase 2 P2 added the tenant-owned content plane `apps/documents`
(`Document→DocumentVersion` + `DocumentSet/Version/Membership`), object-store blob upload,
soft-delete tombstone, auditable physical purge, and a role/tenant-scoped operator JSON API under
`/console/api/documents/`; the Sprint 5 index-scoped `Document` was renamed to `IndexedDocument`
(rows/PKs/FKs preserved). Phase 2 P3 added real embeddings + staged indexing: a platform-managed
immutable `EmbeddingProfile` catalog + per-tenant grants and an opt-in `OpenAICompatibleEmbeddingClient`
over the shared SSRF-safe transport (profile-id-only, deterministic default, no `openai` dep — P3.1),
plus the ADR-0003 per-`IndexVersion` blue/green vector-store DAL (`apps/ingestion/vector_store.py`,
system-generated `chunk_iv_<pk>` names, `vector(D)`/`halfvec(D)`, PostgreSQL-only) and a staged
`build_staged_index` over managed documents that leaves a `promotable` (never served) index (P3.2).
`IndexVersion` was re-scoped (additive) to `(org, document_set_version, embedding_profile)`. Phase 2
P4 added the document-ACL retrieval security core: `ScenarioDocumentSetBinding` + forward-ready
`DocumentSetGrant` (`apps/documents`); the release compiler pins `document_set_versions` deny-by-
default from bindings, the resolver carries them, and `PgvectorRetrievalProvider._retrieve_acl`
serves `/v1/query` only from the pinned versions' **active** per-`IndexVersion` stores (tenant +
not-tombstoned scoped, no client filter); each store is provisioned with **`FORCE ROW LEVEL
SECURITY`** + a transaction-local `app.tenant_id` tenant policy (ADR-0004, proven fail-closed under a
non-superuser role); and `promote_staged_index`/`rollback_staged_index` do the metadata-only
pointer-flip. Legacy source-scoped retrieval is unchanged; no dependency or live egress added.
**Remaining P4 production hardening:** `FORCE` RLS on the Django-managed tenant tables + a dedicated
non-owner app role (CI/local run as the superuser owner, which bypasses RLS — the mechanism is
proven on the served stores). Phase 2 P5 wired the **same governed retrieve/generate seams** into the
workflow (`retrieve`/`generate` nodes) and agent (retrieve step + `_respond`) via
`apps/orchestration/rag_steps.py`, so agents/workflows now do real P4 ACL retrieval + P1 generation
(not stubs); the workflow `generate` node gained optional per-node `prompt_ref`/`model_profile_ref`
binding (multi-prompt/multi-model workflows). The agent still uses the user objective as its prompt —
an authored agent **system prompt** is **P6**. Deterministic providers remain default (CI hermetic);
providers plug in via
`RUNTIME_MODEL_PROVIDER`/`RUNTIME_EMBEDDING_PROVIDER`/`RUNTIME_RETRIEVAL_PROVIDER`.)
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
and advisory-lock tests that SQLite skips also run. When running under
`config.settings.local`, also export `MCP_ENABLED=true` and a non-empty
`METRICS_BEARER_TOKEN`: the Sprint 7 MCP/metrics tests are hard-enabled only in
`config.settings.test`, so without these ~8 MCP/metrics tests fail spuriously (the
disabled endpoints 404). On Windows, pass a writable `--basetemp` to avoid the shared
`pytest-of-*` permission error. Redis and MinIO are not yet exercised by the automated
suite. Management/operational commands shown in the target
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

Sprint 9 (tool registry + approval) is implemented and verified (SQLite + PostgreSQL),
delivered across increments A–D. `apps.tools` adds `tool_definition` / `tool_binding`
artifact validation (bounded, allowlisted, https-only destinations with
IP/private/`.internal`/`localhost` hosts rejected, `critical` risk disabled, credentials
only as `secret:<name>` references), the tenant-scoped immutable `ToolDefinition` /
`ToolBinding` registry (write-once body, status-only mutation), registration enforcing
the high-risk side-effecting approval invariant, and fail-closed release pinning of
active, checksum-matched bindings. The central default-deny `apps.tools.proxy.invoke_tool`
enforces capability, input/output contracts, field allowlists (mass-assignment +
exfiltration defense), risk/approval, bounded size, and least-privilege `secret:<name>`
resolution; `apps.tools.egress` is SSRF-safe (public-unicast-only with resolved-IP checks
defeating DNS rebinding). The durable lifecycle (`ToolInvocation` / `ApprovalRequest`,
`request_tool_invocation` / `decide_approval` / `execute_invocation` /
`cancel_invocation`) provides separation-of-duties, a request-checksum binding
(input-swap-after-approval defense), a 30-minute approval expiry, idempotent resume that
never double-executes, `outcome_unknown` for dispatched-but-unconfirmed calls (never
retried), and redacted fail-closed audit. Real egress (project-owner approved) is the
SSRF-safe stdlib-only `HttpToolAdapter` plus `McpToolAdapter` (JSON-RPC `tools/call`),
selected by `TOOL_ADAPTER=http`/`real` and protocol-dispatched; **the default
`TOOL_ADAPTER` is `deterministic` and opens no socket, so tests/CI perform no live
egress**. A workflow `tool` node calls the governed flow and pauses the run
(`waiting_approval` + durable `awaiting_node` checkpoint), auto-resuming on the
post-commit decision signal and failing closed on rejection; `GET /v1/runs/{id}` surfaces
`waiting_approval`. Operator surfaces: the role-gated, tenant-scoped console approval
view and the management commands `decide_tool_approval` / `list_tool_approvals` /
`cancel_tool_invocation`, with bounded Prometheus counters
`agenthub_tool_invocations_total` / `agenthub_tool_approvals_total`. No new production
dependency was added (the real client is stdlib). Additive migrations only
(`tools.0001`, `tools.0002`, `workflows.0002`). Approval decisions are operator actions
(not consumer actions), so no public consumer "decide" endpoint exists.

Sprint 10 (agent runtime) is implemented and verified (SQLite 337 passed / 2 skipped;
PostgreSQL affected-app run 142 passed). `apps.agents` adds the `agent_definition`
artifact (data, not code: bounded, allowlisted tool *binding roles*, retrieval flag,
limit overrides that may only lower the hard caps) with author-time validation and a
deterministic checksummed compiler; the release compiler pins the compiled agent
(`agent_checksum`) and fails closed unless every declared tool resolves to a pinned
`tool_binding` role. Durable state is the immutable `AgentVersion`, the tenant-scoped
`AgentRun` (addressed externally by an opaque `public_id` UUID so agent and workflow run
ids never collide on `/v1/runs/{id}`) with an immutable redacted start snapshot, a
versioned redacted checkpoint, bounded resource counters, and an append-only
`AgentRunEvent` trail. The Celery task (`queue="runtime"`, `acks_late`) claims the run
under `select_for_update`, is terminal-state idempotent, and treats a stale/missing
message as a safe no-op; the bounded loop re-checks cancellation, deadline, and the step
cap each iteration, enforces step/tool-call/token/state-size/checkpoint-schema-version
caps (each terminates deterministically with a stable code — never an uncontrolled
requeue), and re-validates every planner decision against the immutable compiled tool
allowlist and decision-kind allowlist. Tool use flows only through the Sprint 9
proxy/approval boundary (idempotency key `agent:<run_id>:<step>`); a required approval
pauses the run (`waiting_approval` + durable checkpoint) and auto-resumes on the
post-commit decision signal, failing closed on rejection. Final output must pass the
release output contract and policy. **LangGraph (`langgraph==1.2.9`, the one approved new
production dependency — exact pin, transitive tree captured in `requirements.lock`, `pip
check` clean, and a CI step fails closed on lock drift) is integrated only as an
`AgentPlanner` adapter selected via `AGENT_PLANNER`; the default is the deterministic
planner, so CI/tests run no graph code and open no socket.** LangGraph owns only the
planning loop/transitions/tool-selection/agent-local checkpointing; the durable run state
machine, tenant isolation, tool proxy, approval, audit, retry, cancellation, and
idempotency remain AgentHub's. No LangSmith / LangGraph Cloud / hosted service / new
public endpoint was added (`langsmith` is a dormant transitive dep — no API key, no
tracing). Gateway `POST /v1/invoke` returns `202` + `run_id` (the UUID `public_id`) for an
authorized AGENT scenario, requiring `agent_invoke` + `Idempotency-Key`; `GET`/`DELETE
/v1/runs/{id}` dual-dispatch (numeric→workflow, UUID→agent) and stay consumer/tenant
scoped. Governed eval adds trajectory assertions (`agent_completed`, `agent_tool_invoked`,
`agent_no_tools`, `agent_max_steps`) over the isolated candidate seam. Operator surfaces:
the role-gated, tenant-scoped console agent-run list + redacted trace view + cancel, the
`list_agent_runs` / `cancel_agent_run` management commands, and bounded Prometheus
counters `agenthub_agent_runs_total` / `agenthub_agent_steps_total`. Additive migrations
only (`agents.0001`, `artifacts.0003`). Management commands today additionally include
`list_agent_runs` and `cancel_agent_run`. Not yet delivered (operational follow-ups): a
global start/resume kill switch, the checkpoint retention/purge job (the 30/90-day policy
is recorded but not automated), and production-like load/soak tests; no live-egress or
live-server smoke was run (default deterministic model provider + no-egress tool adapter).

Sprint 11 (visual workflow builder) is implemented and verified (SQLite 364 passed / 2
skipped; PostgreSQL `apps/builder`+`apps/console` run 46 passed; frontend 11 vitest tests +
`vite build`). `apps.builder` adds the tenant-scoped **mutable** `WorkflowDraft` (author
working state — not a runtime graph, not an immutable artifact; unique per
`(organization, logical_id)`; additive migration `builder.0001`) and an **operator** JSON
API under `/console/api/builder/` (session/LDAP authenticated, CSRF-enforced, 401/403 JSON —
**not** the consumer gateway; no bearer path, no CORS): draft list/create/retrieve/update/
delete, `POST diagnostics`, `POST publish`, and `GET node-schema`. Read is membership-scoped
(`allowed_organization_ids`); create/update/delete/publish require
`can_author_scenarios`. `diagnose()` runs the same `validate_body`
(inline-secret rejection + Sprint 8 workflow compiler) as publish and returns the compiled
checksum without persisting; `publish_draft` routes through the shared
`create_artifact_version`, producing an immutable `workflow_definition` artifact — the
builder grants no capability GitOps does not. `node-schema` exposes only builtin node types,
org-active custom-node refs, and tool **binding roles** + approval flag (never tool
endpoints, manifests, or `secret:<name>` values). All draft state changes are audited
(`console.builder.draft.create/update/delete/publish`). The console gains a role-gated
`/console/builder/` page (`@ensure_csrf_cookie`, tenant-scoped mount config) + nav link. The
**React Flow SPA** lives in `frontend/` (Vite + React 18.3.1 + TypeScript + `@xyflow/react`
12.3.5; pinned `frontend/package-lock.json`) and is served **same-origin** as Django static
assets built to `apps/builder/static/builder/` (**gitignored** — regenerate with
`npm --prefix frontend run build`; the Python runtime/gates never depend on the bundle
existing). The client is **non-authoritative**: no validation/authorization/lifecycle/
promotion/execution logic — draft save/compile/validate/publish are backend round-trips,
read-only mode is driven by the server `can_write` flag, and DSL serialization is
deterministic (canonical, sorted). Five approved new **production frontend** dependencies
(Node/npm toolchain, Vite, React, React DOM, `@xyflow/react`) were added with a Node CI job
(`npm ci` fails closed on lockfile drift → `tsc --noEmit` → `vitest` → `vite build`); **no
new Python runtime dependency**. Frontend gates run on Node v20 / npm 10. Not delivered: no
headless-browser/live-server smoke (the SPA is verified by vitest+jsdom and the build;
Django static resolution by `findstatic`); in-app (non-unload) navigation away from a dirty
editor is not additionally guarded. Several originally-planned builder enhancements
(optimistic concurrency/ETag conflict, autosave, soft-delete, GitOps draft export, artifact
preview view, CSP, a distinct `project_editor` permission) are **deferred to Phase 2** — the
builder is being repurposed toward AI-assisted authoring. The single canonical Sprint 11
record is `docs/tasks/sprint-11-workflow-builder/`; the earlier duplicate plan is archived
under `docs/planning/archive/`. Phase 2 is a discussion draft at
`docs/planning/phase-2-plan.md` (governed document plane, Turkish UI, AI-assisted authoring,
personal end-user MCP, and the foundational live-model runtime). Phase 2 kickoff is approved and P1
(live chat), P2 (content plane & storage), P3 (real embeddings + staged blue/green indexing), and P4
(document-ACL retrieval + FORCE RLS + pointer-flip promotion — the security core that unlocks
serving real, ACL-scoped tenant corpora), and P5 (real retrieve/generate wired into the agent loop
and workflow generate/retrieve nodes + per-node prompt/model binding) are verified; continue at P6
(authored, governed agent system-prompt artifact). Its M0 architecture decisions are accepted as
ADR-0002–0005, with the
remaining environment-specific egress and dependency approvals still enforced. See
`docs/ai/agent-handoff.md` for the start checklist and live-state revalidation steps.

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
