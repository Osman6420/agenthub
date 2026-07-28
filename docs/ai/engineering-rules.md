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
serves canonical workflow retrieval only from the pinned versions' **active** per-`IndexVersion` stores (tenant +
not-tombstoned scoped, no client filter); each store is provisioned with **`FORCE ROW LEVEL
SECURITY`** + a transaction-local `app.tenant_scope` tenant policy (ADR-0004, proven fail-closed under a
non-superuser role); and `promote_staged_index`/`rollback_staged_index` do the metadata-only
pointer-flip. Legacy source-scoped retrieval is unchanged; no dependency or live egress added.
**Remaining P4 production hardening:** `FORCE` RLS on the Django-managed tenant tables + a dedicated
non-owner app role (CI/local run as the superuser owner, which bypasses RLS — the mechanism is
proven on the served stores). Phase 2 P5 wired the **same governed retrieve/generate seams** into the
workflow (`retrieve`/`generate` nodes) and agent (retrieve step + `_respond`) via
`apps/orchestration/rag_steps.py`, so agents/workflows now do real P4 ACL retrieval + P1 generation
(not stubs); the workflow `generate` node gained optional per-node `prompt_ref`/`model_profile_ref`
binding (multi-prompt/multi-model workflows). Phase 2 P6 added an authored, governed bounded system prompt. ADR-0014 now carries it inside
the checksummed closed `agent_loop` node config; it remains input, never authorization, and tool,
decision and output-contract gates are unchanged. Phase 2 P7.1–P7.2 added bounded local parsers; P7.3 added
profile-only async OCR with durable result-before-ACK lineage; and P7.4a added governed Confluence
Data Center snapshot ingestion under ADR-0006's connector-only private-corporate policy. Confluence
is verified offline only; live network/CA/secret/service-account inputs remain deployment-gated and
P7.4b generic REST remains contract-gated. P8.1–P8.4 completed the role/tenant-scoped document
console, effective consumer grants, and elevated purge. Deterministic providers remain default (CI hermetic);
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
canonical `POST /v1/responses`, synchronous Chat compatibility, UUID Run status/cancel — plus `apps/observability`
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
and cannot import `apps.ingestion`; a venv created before Phase 2 P7.2 lacks
`pdfplumber`/`python-docx`/`openpyxl` and cannot run the pdf/docx/xlsx parser tests (the
default text parsers still import, since the binary libs load lazily). Gates:
`ruff format --check .`, `ruff check .`,
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

Sprint 8 established strict workflow compilation and durable execution. ADR-0014 supersedes
its separate run surface: every executable scenario now pins one workflow definition and uses the
canonical UUID `Run`/`RunEvent` lifecycle through Responses, Chat and MCP. Custom-node package,
allowlist, version and schema controls remain unchanged. No workflow-engine dependency was added.

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

Sprint 10 established the governed agent policy and planner safety boundary. ADR-0014 removes
its separate artifact/version/run/event persistence and exposes the policy only as a closed
`agent_loop` workflow node. The canonical executor preserves exact tool-role pins, action and
argument allowlists, step/tool/token/deadline/state caps, approval pause/resume, deterministic
no-progress termination, output validation, kill-switch checks and optional LangGraph planner
isolation. All lifecycle, cancellation, retry, recovery, usage and audit evidence is now owned by
UUID `Run` and ordered `RunEvent`; the public surface is Responses/Chat plus UUID Run status and
POST cancellation.

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
under `docs/planning/archive/`. Phase 2 is active at
`docs/planning/phase-2-plan.md` (governed document plane, Turkish UI, AI-assisted authoring,
production closure hardening, and the foundational live-model runtime). Personal end-user MCP moved
to Phase 3 discovery. Phase 2 kickoff is approved and
P1–P6, P7.1–P7.4b, P8.1–P8.4, P9.1–P9.5, and P10.1/P10.2 are implemented and verified for their
offline scopes. P10.1 adds disabled-by-default, profile-only AI workflow candidates with bounded
untrusted parsing, canonical diagnostics, exact-project explicit draft transfer, fail-closed rate
limiting and redacted audit; it never auto-publishes or changes release/runtime state.
P10.2 adds allowlisted input/output JSON Schema candidates, immutable checksummed prompt contracts
and tenant/project-scoped mutable `ArtifactDraft` editing without a generic publish route. Additive
migration `builder.0002`. P11 broader Django-table RLS/non-owner hardening is implemented and
staging-equivalent verified. Phase 2 closure requires live connector/embedding/OCR/AI profiles and
concrete smoke/rollback evidence. The owner-added Phase 2.5 product-coherence milestone must first
deliver the active organization workspace, navigable domain graph, system-generated console IDs,
document/source UX, scenario studio, governed transform DSL and OpenAI-compatible adapters.
Phase 2.5 Part 2 is completed, owner-accepted, and verified: console
creation generates immutable slugs/logical IDs and atomic initial scenario aliases
server-side; project/scenario/document/document-set/consumer console navigation uses
tenant-scoped UUID public locators while legacy integer routes remain compatible.
The additive expand/backfill/constrain migrations passed SQLite and affected PostgreSQL
coverage. The repository-wide PostgreSQL run passed after observability tests declared
the database access required by transaction-opening tenant middleware (670 passed,
5 skipped). The owner accepted closure without requiring a separate browser recording.
Governed upload malware/type scanning and persistent server-side conversation history moved to
Phase 3. P7.4a provides
immutable Confluence profiles, exact tenant+document-set grants,
bounded private-DNS Data Center
reads, recoverable incremental snapshots, draft candidates, and FORCE-RLS lineage; it adds no
dependency and makes no default/live egress. Its actual corporate endpoint, CIDRs/DNS, CA, firewall,
PAT and service-account permissions still require manual rollout review. **P7.4b generic REST is
implemented and offline-verified but live profiles remain disabled and deployment-gated.** M0
architecture decisions are
accepted as ADR-0002–0006, with environment-specific egress approvals still enforced. See
`docs/ai/agent-handoff.md` for the start checklist and live-state revalidation steps.

This "Repository-specific verified state" section is `@`-imported by `CLAUDE.md` into
every agent's context: it is the always-loaded, canonical statement of what is
implemented/verified and how to run the gates. Update it in the same change that lands
or verifies an implementation increment — not only `docs/planning/master-plan.md` — so
the next Codex/Claude handoff starts from accurate ground truth. Re-inspect manifests
and CI whenever implementation is added.

## Review and evidence

Phase 2.6 P2.6.8 isolated-runtime integration adds a dependency-free AST/static policy, exact
tenant/revision/source/schema/module checksum runner contract, compiler/runtime seam, double
active-pin resolution, schema plus P2.6.1 safe-patch validation and a bounded separate-process test
harness. `PYTHON_NODE_RUNTIME_ENABLED` defaults false; empty resolver/runner settings fail closed and
the bundled subprocess harness is rejected as a production adapter. No production sandbox backend,
source persistence/control-plane model, dependency, Docker/OpenShift activation or egress was added.
Production remains blocked on ADR-0011 target-runtime isolation evidence and security/platform/SRE
approval.

The Phase 2.6 activation-closure wave (P2.6.7/P2.6.8/P2.6.9/P2.6.10) is merged and gate-verified on
the Phase 2.6 integration head. P2.6.7 adds the governed MCP catalog quarantine registry
(`tools.0003`: tenant-scoped `McpCatalogSource`/`McpCatalogCandidate` under FORCE RLS;
quarantine → exact operator review → immutable registration; drift/disappearance audited; no live
egress by default) and both catalog tables are in the owner-approved application-role grant
inventory (SELECT + INSERT/UPDATE, no DELETE) in `deploy/postgres/provision-app-role.sql`; live MCP
endpoints/credentials remain deployment-gated. P2.6.8 adds the fixed four-pod OpenShift runner
adapter, credentials-free runner image and `deploy/openshift/` manifests behind a separate
`PYTHON_NODE_RUNNER_ATTESTED` gate that the repository never sets — scenario-author Python execution
stays disabled pending ADR-0011 target attestation. P2.6.9 activates context-aware Studio AI
authoring over an exact, bounded, tenant/scenario-scoped capability snapshot with fail-closed
reference validation and a transient capability-missing scaffold (no auto-persist, no lifecycle
bypass). P2.6.10 closes ingestion activation with real-service preflight, worker-absence/restart,
duplicate/redelivery and reconciliation drills. Wave gate evidence (static + full SQLite +
PostgreSQL + frontend runs) is in `docs/tasks/phase-2-6-wave-3-integration/verification.md`; the
integrated head lands on `feat/foundation-sprint-0-1`.

Phase 2.6 P2.6.6's advanced governed agent-loop policy remains implemented: structured
server-validated decisions, exact role allowlists, bounded retrieval/tool/verify/respond/escalate
actions, repeated-action/no-progress guards, redacted observations, versioned internal checkpoints
and the global/tenant `AgentRuntimeControl` kill switch. ADR-0014 embeds that policy in the canonical
workflow `agent_loop` node and canonical Run checkpoint; historical verification remains in
`docs/tasks/phase-2-6-part-6-governed-agent-loop/verification.md`.

Phase 2.6 P2.6.11 (product/operational closure) increments A–D are implemented and verified;
E/F remain environment/owner-gated. A: Scenario Studio now exposes every verified workflow node
family — `parallel`/`for_each`/`join`/`subworkflow`/`agent_loop` plus node-level `retry_policy`/
`compensation` — via the backend-authoritative `apps/builder/node_schema.py` (Turkish-first
labels, compiler-accurate bounds, `branch_owner`/`composition`/gate metadata) and additive
React authoring (new field kinds, node input/output mappings, retry/compensation editors,
`branch`/`on_error` edges; frontend stays non-authoritative); and a role-gated, tenant-scoped
redacted **workflow run trace** view (`console:workflow_run_detail`) renders branches/joins/
waits/retries/compensation/child links at code/checksum/count level only (cross-tenant + payload
redaction tested). B: the closed eval assertion allowlist gains 12 data-only kinds
(`workflow_branch_completed`/`join_completed`/`wait_*`/`retry_within`/`compensation_*`/
`child_completed`, `agent_verified`/`arguments_valid`/`escalated`) with a redacted candidate
evidence-metadata contract — agent trajectory assertions run today, but the async
workflow-structure candidate exercise is **routed back** to P2.6.2–P2.6.5 (the isolated
`run_workflow_candidate` seam cannot execute async parallel/wait structures). C: six
bounded-label Prometheus series (`agenthub_workflow_branches/joins/waits/retries/compensations/
children_total`) via `post_save` receivers plus five alert rules (queue saturation, stuck waits,
retry storm, compensation failure, budget/kill-switch) and runbook sections. D: an owner-approved
**90-day, report-mode-default, fail-closed, audited, idempotent** retention/purge for bulky
working state only (`agent_checkpoint`/`branch_state`/`wait_correlation`; rows, lineage, audit and
eval evidence retained) via `apps/observability/retention.py`, the platform-admin
`purge_retention` command + console page, and a report-only Celery-beat entry. Additive only — no
migration, no new dependency, no public API change. Evidence (full SQLite 940 passed/37 skipped;
PostgreSQL affected 93 + workflows/agents FORCE-RLS 290; frontend tsc/24 vitest/build; static +
mypy clean) in `docs/tasks/phase-2-6-part-11-product-operational-closure/verification.md`.
Remaining for phase completion: publish the owner-reviewed S01–S07 GitOps pack + approved
demo-seed reset (E), and real-broker recovery drills, live Grafana/Prometheus verification, the
recorded Turkish browser journey and owner sign-off (F).

Review the final diff for scope, layering, compatibility, authorization, privacy, failure modes, concurrency, operability, and accidental files. Record every executed command and result in task verification. State checks that could not run and the risk this leaves; never infer success from an agent assertion.

## Recommended enforcement (not implemented)

When code and CI arrive, evaluate pre-commit formatting/linting, secret and static-analysis scans, dependency/lockfile and container scans, migration drift checks, protected branches, required CI checks, network/MCP allowlists, isolated production credentials, Codex sandbox/approval rules, and Claude `PreToolUse` restrictions. Adopt them through reviewed changes; do not describe them as active until verified.
