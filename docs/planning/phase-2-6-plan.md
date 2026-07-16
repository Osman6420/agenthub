# AgentHub — Phase 2.6 Advanced Enterprise Orchestration Plan (PROPOSED)

> **Status: PROPOSED.** This plan turns the master-plan durable-orchestration backlog into a
> reviewable delivery sequence. Owner decisions recorded on 2026-07-16: keep and deliberately
> revise the unreleased `agenthub/v1` workflow contract instead of introducing workflow v2; local
> development/test data may be reset and repopulated for the new contract; keep governed MCP
> catalog synchronization in Phase 2.6; move optional multi-agent supervision to Phase 3. This plan
> does not itself execute or authorize an unbounded database reset, implementation, a public API change, a new
> production dependency, authentication/authorization changes, live egress, or production
> activation. Each increment requires its own task plan, proportional threat model and approval at
> the gates defined in `AGENTS.md`.

## Purpose

Extend the current secure, immutable, release-pinned workflow, RAG, tool/MCP and agent runtimes so
they can express complex enterprise processes without arbitrary code or tenant-authored executables.
The target is durable orchestration with explicit dataflow, bounded concurrency, human/event waits,
failure compensation and evidence-backed agent decisions while preserving the existing tenant,
authorization, approval, audit, evaluation and release boundaries.

Phase 2.6 follows Phase 2.5 product coherence. Phase 2.5 remains responsible for making current
capabilities coherent and operable; Phase 2.6 changes runtime and DSL semantics. Phase 3 remains the
authority for personal MCP identity/OBO, upload scanning and persistent conversation history.

## Outcomes

1. A typed, allowlisted way to map workflow state into node/tool inputs and outputs.
2. Durable bounded parallel execution and deterministic join behavior.
3. Generic durable wait/resume for human decisions, timers and authenticated events.
4. Explicit error routing, retry classification and compensation/saga behavior.
5. Governed sub-workflow and agent invocation with non-delegating authorization.
6. An observe–act–verify agent loop with schema-constrained tool arguments and bounded replanning.
7. Governed MCP catalog synchronization without runtime authority expansion.
8. Scenario Studio, evaluation, observability and operations support for every delivered primitive.
9. A verified enterprise scenario pack proving both successful and denied/failure paths.

## Design principles

- DSL remains declarative data, never Python, JavaScript, template evaluation or arbitrary code.
- Runtime executes only immutable, checksummed, release-pinned artifacts.
- Client, model, tool, event and child-run output are untrusted input.
- Planner output is a proposal; server-side policy remains the authority.
- Child workflows and agents receive explicitly attenuated capabilities, never ambient authority.
- Every wait, retry, resume, join and compensation transition is durable and idempotent.
- Resource bounds are explicit at compile time and enforced again at runtime.
- The product is unreleased and current workflow data is disposable. Phase 2.6 deliberately evolves
  `agenthub/v1` in place, updates all fixtures/examples and repopulates explicitly approved local/test
  databases. No dual v1/v2 compiler or runtime is introduced.
- A node is not exposed in Scenario Studio until compiler, runtime, recovery, authorization,
  evaluation, audit and compatibility contracts are implemented and verified.

## Scope

### Included

- Versioned workflow/agent DSL extensions and immutable compilation.
- State paths, typed mapping, allowlisted transforms and schema validation.
- Parallel split/join, bounded `for_each`, durable waits and authenticated resume.
- Error routes, retry policy, compensation and `outcome_unknown` handling.
- Sub-workflow and agent-call nodes pinned through the same release manifest.
- Structured agent tool arguments, observation summaries and bounded replanning.
- Governed MCP tool-catalog import/synchronization into reviewed definitions and bindings.
- Builder/Studio authoring, diagnostics and trace visualization.
- Eval assertions, operational controls, metrics, tracing, audit and retention.
- Reference scenarios and GitOps-ready artifact JSON after owner review.

### Non-goals

- Arbitrary tenant-uploaded code, packages, expressions or scripts.
- Unbounded recursion, loops, concurrency, dynamic graph mutation or model-selected endpoints.
- Model-created tool definitions, credentials, approvals, roles, grants or release pins.
- Automatic execution of newly discovered MCP tools.
- Shared mutable memory between tenants or persistent user conversation history.
- Multi-agent supervisor/delegation; it is a Phase 3 discovery workstream.
- Personal-user/OBO MCP identity; that remains Phase 3.
- Autonomous production remediation without explicit policy and approval.
- Distributed microservice extraction or replacement of the Django/Celery architecture.

## Capability baseline and gaps

| Capability | Current state | Phase 2.6 target |
| --- | --- | --- |
| RAG | Release/document-set pinned, ACL scoped | Reusable in branches, child runs and verified loops |
| Workflow | Bounded acyclic single-path DAG | Typed dataflow, bounded parallel/join, waits and compensation |
| Tool use | HTTP/MCP, binding allowlists, durable approval | Typed argument mapping and chained evidence with unchanged proxy authority |
| Agent loop | Retrieve/tool/respond decisions with hard caps | Observe–act–verify, structured arguments and bounded replanning |
| MCP | Governed ingress and fixed outbound definitions | Reviewed catalog synchronization; no automatic authority widening |
| Human action | Tool approval pause/resume | Generic human task and separation-of-duties policy |
| Failure handling | Fail-closed terminal behavior | Explicit retry, error routing, compensation and manual recovery |
| Composition | One workflow or one agent per scenario release | Pinned child workflow/agent calls with depth and capability attenuation |

## Delivery sequence

Each part is independently reviewable. P2.6.0 freezes shared contracts; P2.6.1 provides the common
state-mapping seam. After that seam is stable, the parallel/join, wait/event, composition and MCP
catalog workstreams may be developed by separate branches/owners. They must share contract tests
and avoid editing the same runtime state-machine core concurrently. P2.6.4 and P2.6.6 are integration
layers and start only when their required lower seams are verified. P2.6.8 continuously integrates
completed parts and performs final acceptance; it is not a late UI-only batch.

| Part | Outcome | Depends on | Primary gates |
| --- | --- | --- | --- |
| P2.6.0 | Architecture contract, ADRs and executable scenario corpus | Phase 2.5 Parts 6–7 | Owner scope; DSL compatibility and threat-model approval |
| P2.6.1 | Typed state paths, mapping and governed workflow transform node | P2.6.0, existing transform DSL | Injection/exfiltration review; no arbitrary evaluation |
| P2.6.2 | Durable bounded parallel split/join and `for_each` | P2.6.1; parallel lane A | Concurrency, tenant scope, idempotency and state-budget proof |
| P2.6.3 | Human task, timer and authenticated event wait/resume | P2.6.1; parallel lane B | Authentication/public API approval; replay and forged-event defenses |
| P2.6.4 | Error routes, retry classification, compensation and recovery | P2.6.2–P2.6.3 | Side-effect/idempotency and `outcome_unknown` safety review |
| P2.6.5 | Pinned sub-workflow and agent-call composition | P2.6.1; parallel lane C, integration with P2.6.4 before activation | Authorization attenuation, recursion and tenant-isolation proof |
| P2.6.6 | Observe–act–verify agent loop and structured tool arguments | P2.6.1, P2.6.4–P2.6.5 | Prompt-injection, cost, approval and planner-conformance review |
| P2.6.7 | Governed MCP catalog synchronization | P2.6.0 + tool registry; parallel lane D | Live egress/secret/network approval; review-before-activation invariant |
| P2.6.8 | Incremental Studio/eval/operations integration and enterprise acceptance pack | Each delivered part | Full regression, PostgreSQL recovery, Turkish journey and owner sign-off |

## P2.6.0 — Contract and scenario foundation

- Create ADRs for the durable orchestration state machine and child-run authority.
- Freeze representative scenarios before implementation:
  - regulatory evidence and exception decision;
  - human-approved infrastructure change with post-change verification and rollback;
  - procurement exception with separation of duties;
  - AML/fraud evidence fan-out and deterministic synthesis;
  - data-governance/PII remediation pipeline;
  - incident observe–act–verify loop;
  - contract-review supervisor with bounded specialist agents.
- For every scenario, define happy, denial, timeout, cancellation, replay, partial failure,
  cross-tenant and recovery trajectories.
- Define JSON Schema examples as target fixtures, not importable artifacts, until the owning part is
  implemented.
- Record the accepted in-place `agenthub/v1` break: there is no released compatibility promise,
  existing workflows are dummy data, and every fixture/example/demo artifact will move atomically to
  the new canonical grammar.
- Inventory every database before any reset. Only explicitly named local/development/test databases
  may be cleared and repopulated; production-like or unknown targets fail closed. Reset remains a
  separately confirmed operational action, not an implicit migration step.

### Exit criteria

- ADRs approved; scenario inputs/outputs and threat cases reviewed.
- Contract migration matrix covers code, fixtures, docs, demo seed and database repopulation; no
  stale workflow artifact or compiled release remains after the approved reset.
- Every later primitive has an owner, task boundary and explicit acceptance criteria.

## P2.6.1 — Typed state mapping and governed transforms

- Add exact-schema state-path references using a restricted JSON Pointer subset.
- Add `input_mapping` and `output_mapping` contracts for tool/custom/child nodes.
- Reuse the closed transform operation registry; do not embed expressions or templates.
- Add a workflow `transform` node that applies a pinned `transform_profile` or an exact bounded
  inline operation list if an ADR explicitly chooses that contract.
- Validate source/target schemas at author and compile time where possible, then at runtime.
- Prevent protected runtime keys, tenant/actor/capability fields and authorization context from
  being written through mappings.

### Exit criteria

- A tool can consume selected input/retrieval/prior-tool fields without a custom Python node.
- Unknown paths, type mismatches, oversized expansion, secret-like fields and protected-key writes
  fail closed with stable diagnostics.

## P2.6.2 — Parallel split, join and bounded collection processing

- Add explicit `parallel`/`join` semantics with compile-time branch ownership.
- Add bounded `for_each` over a typed array with hard item, concurrency, duration and state budgets.
- Define deterministic join ordering and merge-conflict behavior; implicit last-writer-wins is
  forbidden.
- Persist branch state independently and install tenant scope in every worker transaction.
- Cancellation propagates to undispatched work; late results cannot resurrect a terminal run.

### Exit criteria

- AML/fraud reference scenario can query independent evidence sources concurrently and synthesize
  only after an all/threshold/fail-fast join policy completes.
- Redelivery and worker loss tests prove exactly-once state transitions over at-least-once tasks.

## P2.6.3 — Durable human, timer and event waits

- Generalize the existing tool-approval checkpoint without weakening its invariants.
- Add typed human-task assignments with allowed decision roles, separation of duties, expiry and
  escalation policy.
- Add bounded timers using durable deadlines, not sleeping workers.
- Add authenticated event correlation with opaque public IDs, one-time/replay-safe tokens or an
  equivalent approved mechanism.
- Resume events carry data only through an explicit schema/allowlist and cannot replace tenant,
  actor, release, capabilities or pending action checksum.

### Exit criteria

- Forged, expired, replayed, cross-tenant and wrong-state resume attempts are denied and audited.
- Cancellation, timeout and deploy/restart recovery are verified on PostgreSQL/Celery.

## P2.6.4 — Failure, retry and compensation

- Classify node failures as validation, authorization, permanent, transient or outcome unknown.
- Permit bounded retry only for explicitly idempotent operations with capped backoff/jitter.
- Add explicit error edges; error payloads expose stable codes, not raw sensitive messages.
- Add compensation stacks for completed side effects, pinned at compile time.
- Never compensate an `outcome_unknown` action automatically unless a verified reconciliation
  contract proves the external outcome.
- Provide operator recovery actions with role checks, reason capture and audit.

### Exit criteria

- Infrastructure-change scenario performs verify-or-compensate safely across crash, duplicate task,
  timeout and ambiguous external outcome cases.

## P2.6.5 — Sub-workflow and agent composition

- Resolve child definitions only from immutable roles pinned into the parent release.
- Pass a reduced input schema and an attenuated capability set.
- Re-evaluate tenant, consumer, scenario and tool authorization in the child; parent authorization
  is not transferable proof.
- Enforce maximum depth, child count, cumulative deadline/token/tool/state budgets and cycle checks.
- Define cancellation, child failure, trace linkage and output mapping.

### Exit criteria

- Parent/child cross-tenant, unauthorized-tool, recursive-call and budget-amplification tests deny by
  default.

## P2.6.6 — Advanced governed agent loop

- Expand planner proposals to a versioned structured decision schema containing action kind,
  pinned role and schema-constrained arguments.
- Give the planner bounded summaries of retrieval/tool observations; never raw secrets, hidden
  authorization state or chain of thought.
- Support explicit `retrieve`, `tool`, `verify`, `respond` and safe terminal/escalation decisions.
- Permit bounded repeat retrieval/tool use only when policy and per-role call caps allow it.
- Revalidate every argument against tool contracts, field allowlists and policy at the proxy.
- Preserve approval pause/resume and request-checksum binding.
- Add loop/convergence guards, repeated-action detection, per-role budgets and global kill switches.

### Exit criteria

- Incident scenario can observe, select a governed action, wait for approval, verify the result and
  escalate or compensate without widening authority.
- Prompt/tool injection, malicious planner, budget exhaustion and replay tests fail closed.

## P2.6.7 — Governed MCP catalog synchronization

- A platform-managed connector may fetch bounded `tools/list` metadata from an approved MCP server.
- Discovery creates quarantined candidates; it never creates an active definition/binding, changes
  a release or grants a capability.
- Operators review destination, schemas, risk, side effects, redaction and approval policy before
  immutable registration.
- Catalog drift is detected and audited; incompatible changes require a new version and release.
- Runtime continues using exact pinned definitions and `tools/call` through the existing proxy.

### Exit criteria

- Malicious names/schemas, catalog explosion, DNS rebinding, redirects, drift and disappearing tools
  are handled without automatic authority expansion.

## P2.6.8 — Product, evaluation and operational closure

- Add Studio palette/config/diagnostics only for verified node families.
- Render parallel branches, waits, child runs, retries and compensation in redacted traces.
- Extend eval assertions for branch/join, wait/resume, retry, compensation, child runs, structured
  tool arguments, verification and escalation.
- Add bounded-cardinality metrics and trace linkage for parent/child/branch activity.
- Add queue saturation, stuck-wait, retry storm, compensation failure and budget alerts.
- Define retention/purge for branch state, wait tokens, planner observations and child runs.
- Publish reviewed DSL JSON/GitOps scenario examples only after compiler validation and owner review.

## Artifact and DSL impact

Candidate artifacts or contracts:

- revised canonical `agenthub/v1` `workflow_definition` graph semantics;
- versioned state-mapping profile if mappings are reusable;
- existing `transform_profile` reused by workflow runtime;
- human-task/event policy profile;
- agent decision/observation schema version in compiled `agent_definition`;
- optional MCP catalog source artifact or platform-managed profile.

No artifact body may contain a raw endpoint, credential, tenant authority, executable expression or
unbounded template. Endpoint/secret material remains in platform-managed profiles and the governed
tool registry.

## Data and state model impact

Likely additive durable records include branch attempts/results, join state, external wait
correlations, human tasks, compensation entries and parent/child run links. Exact tables are deferred
to part task plans. Every tenant-owned row requires direct organization lineage, FORCE RLS where
applicable, non-owner-role verification and bounded retention.

## Security and authorization requirements

- Deny unknown node/action/version/state paths and unknown planner decisions.
- Re-run authorization at every tool, retrieval, child-run, resume and operator action boundary.
- Treat model/tool/event/child output as injection-capable untrusted data.
- Enforce capability attenuation and cumulative budgets across nested execution.
- Protect resume/approval/compensation decisions against replay, substitution and self-approval.
- Keep secrets out of DSL, state, observations, logs, traces, metrics and eval reports.
- Bound graph size, fan-out, nesting, collection items, calls, tokens, elapsed time and persisted
  bytes at compile and runtime.

## Observability and audit requirements

- Stable events for branch dispatch/join, wait create/resume/expire, retry decision, compensation,
  child start/finish, planner proposal/authorization decision and operator recovery.
- Audit records include actor, tenant, parent/child/target references, action, authorization decision,
  outcome, safe reason code and trace ID.
- Persist decisions and bounded observations, never hidden reasoning or raw chain of thought.
- Metrics use bounded labels; scenario/run/tool IDs remain trace/audit fields rather than labels.

## Verification strategy

Every part must cover:

- compiler/schema/property/boundary tests;
- happy, invalid, authn failure, authz denial and cross-tenant paths;
- duplicate delivery, crash/restart, cancellation, timeout and stale-resume paths;
- state/token/concurrency/depth/call budget exhaustion;
- audit completeness, redaction and bounded-cardinality telemetry;
- complete replacement of dummy workflow artifacts/compiled releases and rejection of stale grammar;
- SQLite fast suite plus PostgreSQL non-owner/RLS and real Celery recovery evidence;
- deterministic provider/adapter default with no live network in CI;
- repository formatter, lint, type, migration drift, checks and full tests.

## Rollout strategy

- Deliver behind disabled-by-default capability gates while parts are incomplete.
- Update the single `agenthub/v1` compiler/runtime contract atomically at the integration boundary;
  do not ship a mixed old/new grammar.
- Stop workers, verify the explicitly named non-production database, apply schema changes, reset and
  repopulate demo/test artifacts, then restart compatible workers. Never infer reset authority from
  this plan.
- Canary per organization/scenario after eval and operator approval.
- Establish queue/budget/kill-switch dashboards before enabling concurrency or advanced agents.
- Live MCP/event endpoints and credentials require separate environment approval and smoke/rollback
  evidence.

## Rollback strategy

- Stop new starts with a global and per-capability kill switch.
- Because the application is unreleased and workflow data is disposable, stop/delete non-production
  in-flight dummy runs only in the separately approved reset procedure; never reinterpret old
  checkpoints under new code.
- Roll back code and repopulate the explicitly approved non-production database from the matching
  seed contract. Do not attempt to mix old artifacts with the revised runtime.
- Disable MCP catalog sync/event ingress without deleting definitions or durable run evidence.
- Use forward-fix migrations; no destructive rollback of referenced execution records.

## Risks

- Parallelism and nested runs can amplify cost, queue load and state size.
- Dynamic argument mapping can enable mass assignment or data exfiltration.
- Agent replanning can amplify prompt injection and repeat side effects.
- Resume/event APIs can become confused-deputy or replay surfaces.
- Compensation can worsen an incident when external outcome is ambiguous.
- MCP discovery can be mistaken for reviewed authorization.
- A large phase can become unreviewable unless each part remains independently gated.
- Parallel branches can conflict in shared compiler/runtime files; contract ownership and integration
  order must be assigned before concurrent implementation.

## Open decisions

Owner decisions closed on 2026-07-16:

- Revise `agenthub/v1` in place; do not add workflow v2.
- Keep MCP catalog synchronization in Phase 2.6.
- Move optional multi-agent supervision to Phase 3.

Remaining decisions:

1. Choose the exact restricted state-path/mapping grammar.
2. Decide join policies and deterministic merge semantics.
3. Decide authenticated event ingress transport and correlation-token design.
4. Decide whether human task is a workflow primitive or a generalized approval service.
5. Define the exact local/development database reset and deterministic repopulation procedure.

## Status

**Proposed.** Implementation has not started. P2.6.0 owner review and architecture decisions are the
next action.

## Completion criteria

Phase 2.6 is complete only when all owner-selected parts are individually planned, threat-modeled,
implemented and verified; current-state documentation matches code; dummy legacy artifacts are
fully replaced with no stale grammar; enterprise scenario artifacts pass compiler/eval/promotion gates; recovery and rollback
are demonstrated; and the master plan records verification evidence and accepted residual risks.
