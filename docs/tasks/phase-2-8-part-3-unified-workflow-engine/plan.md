# Task Plan: Phase 2.8 Part 3 — RAG, Workflow and Agent on one workflow engine

## Task summary

Adopt one product and execution model: `Scenario` has no `rag`, `workflow`, `agent` or `adapter`
type; every executable scenario pins one `workflow_definition`; one compiler and state machine serve
synchronous and background execution; and one persistent Run/RunEvent model owns lifecycle,
authorization, usage and audit evidence.

RAG and agent are governed workflow presets/capabilities:

- Document Answer: `input → retrieve → generate → end`
- Agent Loop: `input → agent_loop → end`

This is a runtime replatforming and breaking API/schema cutover, not a refactor or UI rename.

## Background and impact inventory

`ScenarioType` currently selects gateway, evaluation, release compiler and child-composition paths.
RAG runs synchronously outside the durable WorkflowRun/AgentRun state machines. Agent policy lives in
`agent_definition`. Workflow and agent use different run/event tables, counters and recovery logic.
The concise workflow guide is read verbatim into AI authoring, so DSL, compiler, Studio schema,
model-facing instructions and human architecture documentation must change atomically.

Initial repository inspection indicates the dependency spans roughly 125 source/documentation files
and 45 test files. Implementation must refresh this inventory before work and use it as the removal
checklist; the estimates are not permission to perform broad unreviewed rewrites.

## Scope

### Unified DSL and compiler

- Remove `Scenario.type` and all four choices at the final cutover.
- Keep `api_version=agenthub/v1`, `kind=Workflow` and make `workflow_definition` the only executable
  artifact. Remove `agent_definition`; translate its governed policy into `agent_loop` node config.
- `agent_loop` contains a closed schema for allowed action kinds, exact tool-binding roles,
  retrieval/verification/escalation policy, repetition/no-progress policy, bounded system prompt,
  max steps/tool calls/input-output tokens/deadline and per-call timeouts.
- Preserve RAG invariants without a special RAG runtime: `retrieve` derives tenant/consumer ACL and
  grounding policy server-side; `generate` receives only authorized runtime context and emits no
  trusted citations; `end` applies runtime-generated citation metadata, fallback policy and output
  contract validation.
- Compiler emits an immutable `execution_mode_analysis` containing `supported_execution_modes` plus
  stable, content-free allow/deny reasons and relevant node IDs. `background` is always supported.
  `sync` is supported only if the whole compiled graph is bounded, has finite deadlines/timeouts and
  cannot enter a durable pause.
- `tool` and `agent_loop` are **not automatically background-only**. They may be sync-capable when
  every reachable action/tool/model call is bounded and timeout-controlled, no approval/escalation or
  other wait can occur, budgets are finite, and all child paths are sync-capable. Otherwise compiler
  emits background-only with specific blocker codes.
- Wait/event/timer/human/approval nodes and durable fan-out/child paths remain background-only unless
  a later contract explicitly proves they cannot pause; client declarations cannot override this.
- Runtime reloads the exact compiled analysis/checksum and independently validates requested mode and
  protected invariants. It never trusts `background`, node config or client-supplied tenant/actor/
  capability/tool/retrieval scope as authority.

### One runtime and persistent model

- Add UUID-identified Run with direct tenant lineage, scenario, exact release/workflow version,
  compiled checksum/version, status, requested execution mode, checkpoint/checkpoint version,
  awaiting kind/reference, deadline, sync lease, cancellation state, step/tool/token counters, input
  checksum, safe execution-context claims, redacted state, error/reason code and timestamps.
- Use one status set: `requested`, `queued`, `running`, `waiting_approval`, `waiting_event`,
  `waiting_human`, `waiting_timer`, `waiting_child`, `recovery_required`, `completed`, `failed`,
  `timed_out`, `cancelled`.
- Replace WorkflowRunEvent/AgentRunEvent with direct-tenant RunEvent. Event types use a closed schema
  registry. Payloads are allowlisted/redacted, maximum 16 KiB serialized, maximum depth 8, and cannot
  contain prompts, document chunks, model/tool bodies, secrets, credentials or chain-of-thought.
- Guarantee per-run event ordering at database level: lock the Run row, allocate the next monotonic
  sequence from a Run counter and insert event plus state transition in one transaction; retain a
  unique `(run, sequence)` constraint. Workers cannot choose sequence numbers.
- Sync execution runs the same transition functions in the request process; background execution
  runs them through workers. Admission, authorization, release pinning, idempotency, transition,
  event, usage, audit, cancellation, terminal guards and kill-switch checks are shared.
- Late or duplicate tool/model/worker results re-lock the Run, verify expected state/version and are
  discarded/audited when the run is terminal or the transition token is stale. A terminal run can
  never be reopened.

### Explicit synchronous disconnect and cancellation semantics

- A sync request owns a bounded renewable sync lease. Normal completion commits terminal state
  before returning the response.
- Client disconnect requests cooperative cancellation. The run is **not** silently transferred to a
  background worker and execution mode never changes. The engine stops at the next safe transition
  boundary.
- An already in-flight model/tool call cannot be assumed cancellable. It remains bounded by its
  timeout; its result is discarded if cancellation/terminal state won. Ambiguous external side
  effects use the existing safe `outcome_unknown`/`recovery_required` policy rather than replay.
- If the request process disappears before recording disconnect, sync-lease expiry moves the run to
  the defined recovery/cancellation path; no worker automatically takes ownership. Recovery tooling
  must make the final state explicit.
- Cancellation is an idempotent `POST /v1/runs/{uuid}/cancel`, not DELETE. Under a completion/cancel
  race the first committed terminal transition wins; later cancel returns the current terminal state
  without reopening or rewriting it.

### Public API and user-facing behavior

- `POST /v1/responses` is canonical. `background:false` returns final output only for sync-supported
  graphs. `background:true` returns `202`, internal Run UUID/status and the Responses envelope.
  Unsupported mode returns safe `400 unsupported_execution_mode` plus compiler-derived safe reason
  codes; there is no silent mode change.
- Responses `id` is a distinct externally compatible opaque `resp_...` identifier, generated and
  stored separately from the Run UUID. It is not an authorization key and is not accepted by run
  endpoints. `X-AgentHub-Run-Id` returns the Run UUID; background response data also identifies the
  Run UUID explicitly.
- `POST /v1/chat/completions` remains a synchronous compatibility adapter. It preserves the Chat
  Completions body contract, returns `X-AgentHub-Run-Id`, and rejects background-only scenarios with
  explicit validation.
- `GET /v1/runs/{uuid}` is status/trace summary; `POST /v1/runs/{uuid}/cancel` is cancellation.
  `/v1/query`, `/v1/invoke` and DELETE cancellation are absent after the atomic cutover.
- Studio offers Empty Workflow, Document Answer and Agent Loop starters; they are templates, not
  scenario types. Console trace, evaluation and metrics consume Run/node/action semantics.

### Documentation and fixtures

- Update the concise DSL guide sent to AI, detailed artifact/DSL guide, authoring contract/context,
  Studio node schema/descriptions and compiler diagnostics together.
- Convert demo seed, workflow/agent/RAG fixtures, evaluation corpora, manual journeys, GitOps and
  architecture/user/engineering documents to workflow presets and new APIs.
- Add a static removal inventory for old endpoint/type/artifact/model imports and textual references.

## Non-goals

- New production dependencies, arbitrary code/dynamic graph mutation, chain-of-thought storage,
  tenant-selected endpoints/secrets, trusting client/node authority fields, automatic background
  takeover after disconnect or a mixed old/new runtime fleet after cutover.
- Preserving old data/API compatibility. The approved assumption is that protected real data and old
  API consumers do not exist; that assumption must be verified immediately before deletion.
- Implementing the Part 4 polished scenario UX or Part 7 cross-job operations page beyond the
  minimum surfaces required to migrate runtime consumers.

## Canonical server-owned authority

Tenant, actor, consumer binding, capabilities, tool permissions, retrieval ACL/grants/index scope,
release/artifact pins, secrets, execution budgets, audit identity and kill-switch state are derived
from authenticated server state. The DSL compiler rejects protected authority fields and mappings;
the runtime derives/revalidates them for every admission and transition. Client mode requests may
select only a mode already allowed by the exact compiled release.

## Acceptance criteria

- Scenario, release and execution paths contain no live type dispatch after cutover.
- Document Answer preserves current grounding threshold, fallback, citation redaction, ACL and
  output-contract semantics.
- Agent Loop preserves action/tool schemas and allowlists, repeat/no-progress, budgets, approval,
  escalation, cancellation and prompt-injection denial.
- Mode analysis contains stable reasons. Bounded non-pausing tool/agent graphs can run sync; any
  reachable pause/unbounded operation makes sync unavailable and runtime independently rechecks it.
- Sync and background executions use the same transition, authorization, event and output-contract
  semantics. Generated model text need not be byte-identical.
- Every accepted sync/background call leaves Run, ordered events, usage and audit evidence.
- Disconnect never causes implicit background takeover; cancellation, lease expiry and ambiguous
  external side effects follow the documented state transitions.
- Concurrent events remain monotonic/unique; terminal late results cannot reopen a run.
- Responses external `resp_...` ID is distinct from Run UUID; only the UUID appears in
  `X-AgentHub-Run-Id` and run endpoints.
- Cross-tenant run/get/cancel, retrieval, tool, child and approval access fails closed with PostgreSQL
  non-owner RLS.
- Pre-cutover evidence proves zero protected data and zero old API consumers; otherwise the
  destructive gate stops and the plan must be revised.
- Static scans find no live `/query`, `/invoke`, ScenarioType, `agent_definition`, AgentRun or
  WorkflowRun references after cutover.

## ADR, data and migration policy

Before implementation, write an ADR for the single product model, in-place DSL change, mode-analysis
contract, sync disconnect/cancel semantics, Responses/run identifiers, no-dual-runtime rule,
destructive cutover and rollback.

Gates 1–3 add the unified tables and migrate code without deleting old structures. Every new direct
tenant table receives constraints, indexes, FORCE RLS and non-owner grants/tests. Immediately before
Gate 4, record exact counts and references for scenarios/releases/manifests, agent/workflow versions,
runs/events, idempotency, approvals, child links and pending work; inspect access/configuration/docs
for `/query`/`/invoke` consumers. Any protected row, resumable job or consumer blocks deletion.

After a separately approved migration diff, Gate 4 removes old runtime tables, artifacts/type fields
and endpoints. The accepted rollback is explicitly **previous application code plus recreation of an
empty database, migrations and approved seed/configuration**. It is not an in-place downgrade and
does not promise preservation of post-cutover runs. The full empty-database rebuild/rollback drill
must pass before destructive apply.

## Security, privacy, observability and audit

Run state stores only bounded safe execution-context claims and redacted state. Prompts, chunks,
model/tool bodies, credentials and secrets are excluded from RunEvent, logs, audit and metric labels.
Use stable reason codes, checksums, counts and Run UUID in trace fields. Audit admission, completion,
cancellation, approval and security decisions. Required audit/usage failure follows the existing
fail-closed operation contract. Route metrics and dashboards migrate from old endpoints without
retaining them as active contracts.

## Dependencies

Phase 2.6 workflow/agent safety contracts; release/compiler, tool/approval, retrieval, gateway/MCP,
evaluation, observability and PostgreSQL RLS foundations; Part 1 shell. Parts 4 and 7 depend on the
verified output of this part.

## Implementation gates and delivery order

1. **Inventory and contract:** refresh dependency/data/API inventory; write ADR; add `agent_loop`,
   RAG invariants, execution-mode analysis/reasons, protected-field rules, guides and compiler tests.
2. **Unified persistence/state machine:** add Run/RunEvent/RLS, database-ordered event allocation,
   shared transition/terminal guards, sync lease/disconnect/cancel and background worker executor.
3. **Consumer migration:** move Responses, Chat Completions, GET/cancel, MCP, evaluation, console,
   metrics, approvals, children, recovery and kill-switch checks to the unified engine; convert demo
   and fixtures; run semantic parity, concurrency, restart and load/soak tests.
4. **Destructive readiness:** prove zero protected data/resumable work/old API consumers; stop/drain
   old workers; run and record empty-database rollback drill; obtain manual migration-diff approval.
5. **Atomic cutover:** remove Agent/RAG runtimes, old tables/artifacts/type field/endpoints, apply one
   contract version, rebuild seed/configuration and run end-to-end/static acceptance.
6. **Documentation closure:** update master plan, ADR status, current architecture/user/manual docs
   and verification evidence only after behavior is proven.

## Test plan

- RAG semantic parity for ACL, grounding, fallback, citation redaction and output contract.
- Agent Loop action/tool argument schema, allowlist, repeat/no-progress, budgets, approval,
  escalation, cancellation and prompt-injection denial.
- Execution-mode reason matrix: bounded sync tool/agent cases, timeouts, reachable approval/wait,
  unbounded paths, child/fan-out paths and runtime rejection of forged client/node declarations.
- Sync/background comparison of transition sequence, authorization decisions, event schemas,
  terminal/output-contract semantics and usage/audit—not byte-identical nondeterministic model text.
- RunEvent concurrent writers, monotonic allocation, duplicate/stale token and database constraints.
- Request disconnect, sync lease expiry, cooperative cancellation, completion/cancel race, explicit
  absence of background takeover, in-flight timeout and terminal-state late model/tool results.
- Every sync call persists completed/failed/cancelled Run/Event/usage/audit as applicable.
- Responses external/internal ID separation, headers, background response, Chat compatibility,
  idempotent POST cancel and run authorization.
- Retry, duplicate delivery, idempotency conflict/replay, worker restart, timeout, approval/event/
  human/timer/child resume and recovery-required behavior.
- PostgreSQL non-owner RLS and cross-tenant run/cancel/retrieval/tool/child/approval denial.
- Pre-delete zero-data/API-consumer evidence, destructive migration, empty-database rollback/rebuild,
  static removed-reference scan and mixed-worker denial.
- Ruff format/lint, mypy, Django/migration checks, unit/integration/security, secret scan,
  staging-equivalent load/soak and manual end-to-end smoke.

## Rollout and rollback

No mixed runtime fleet. Gates 1–3 run without deleting old schema. At cutover, drain/stop old workers,
confirm zero protected state/consumers, approve migration, deploy one compiler/checkpoint version and
run acceptance. Before destructive apply, normal code rollback remains possible. After destructive
apply, rollback is only the tested procedure: stop new roles, deploy previous code, recreate an empty
database, apply previous migrations and approved seed/configuration, then verify health/smoke.

## Cost and risks

This is expected to take multiple staged reviews and roughly 6–10 engineer-weeks; schedule is an
estimate, not an acceptance shortcut. Highest risks are weakening agent security while generalizing,
RAG fallback/citation/ACL drift, sync/background transition divergence, disconnect/late-result races,
incorrect event ordering, stale workers, unknown old API consumers and irreversible deletion without
a proven empty rebuild.

## Open questions

None in the target contract. Environment inventory and destructive apply are evidence/approval gates,
not implementation choices left to the engineer.

## Status

**Planned.** Public API, authorization and destructive migration work requires the approvals and ADR
defined above.

## Completion criteria

All six delivery steps and acceptance criteria pass; ADR and breaking/destructive approvals are
recorded; PostgreSQL RLS, concurrency, disconnect, semantic parity, empty rollback and static-removal
evidence pass; current docs describe only verified behavior; staff engineer, AppSec, SRE and API-owner
reviews close before Verified/archive.
