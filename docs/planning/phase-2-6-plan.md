# AgentHub — Phase 2.6 Advanced Enterprise Orchestration Plan (IN PROGRESS)

> **Status: IN PROGRESS.** This plan turns the master-plan durable-orchestration backlog into a
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
they can express complex enterprise processes without arbitrary code in trusted application
processes. Phase 2.6 may admit reviewed tenant-authored Python only through an approved isolated
runner boundary; source code is never workflow DSL and never executes in web/runtime workers.
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
8. A reviewed lifecycle for scenario-author Python nodes executed only in an isolated runner.
9. Context-aware AI planning embedded in Scenario Studio with transient candidates and
   server-generated identifiers.
10. Durable, tenant-scoped staged-index build jobs with worker/config readiness, progress,
    reconciliation and actionable recovery instead of dispatch-only feedback.
11. Scenario Studio, evaluation, observability and operations support for every delivered primitive.
12. A verified enterprise scenario pack proving both successful and denied/failure paths.

## Design principles

- Workflow DSL remains declarative data, never Python, JavaScript, template evaluation or arbitrary
  code. Approved Python source has its own draft/review/revision lifecycle outside workflow bodies.
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
- Scenario-scoped Python-node drafts, exact-checksum platform review, immutable approved revisions,
  disable lifecycle and isolated test/runtime execution.
- A bounded tenant/scenario authoring-context snapshot and Studio-embedded AI planner that can use
  only server-provided active capabilities.
- Builder/Studio authoring, diagnostics and trace visualization.
- Persistent ingestion build lifecycle, ingestion-queue readiness, host/Compose configuration parity,
  bounded progress reporting and stale-job reconciliation.
- Eval assertions, operational controls, metrics, tracing, audit and retention.
- Reference scenarios and GitOps-ready artifact JSON after owner review.

### Non-goals

- Unreviewed code, tenant-uploaded packages/binaries, dynamic dependencies, arbitrary expressions or
  scripts, and any tenant code execution inside Django/Celery application processes.
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
| Custom nodes | Platform-preinstalled package executors only | Preserve managed nodes; add reviewed `python_node` revisions in an isolated runner |
| AI authoring | Static guide + free text, separate accept form requiring name/logical ID | Bounded live scenario context, transient Studio candidate, server IDs and capability-missing result |
| Staged ingestion | Console confirms broker dispatch; build state begins only after a worker claims the task | Persistent request-to-result job, compatible-worker readiness, safe progress/failure and reconciliation |

## Delivery sequence

Each part is independently reviewable. P2.6.0 freezes shared contracts; P2.6.1 provides the common
state-mapping seam. After that seam is stable, the parallel/join, wait/event, composition and MCP
catalog workstreams may be developed by separate branches/owners. The Python-node isolation spike
and context-snapshot contract may begin after P2.6.0 in two additional lanes; runtime integration of
Python nodes waits for P2.6.1, while Studio AI can progress independently and consume the Python-node
catalog only after its safe metadata contract is stable. All lanes must share contract tests
and avoid editing the same runtime state-machine core concurrently. P2.6.4 and P2.6.6 are integration
layers and start only when their required lower seams are verified. The ingestion operational lane
may begin after P2.6.0 without changing workflow grammar and shares only the final operations seam.
P2.6.11 continuously integrates
completed parts and performs final acceptance; it is not a late UI-only batch.

### Execution waves and branch integration

Implementation follows the dependency waves below. A later wave starts only after the required
contracts and verification evidence from the preceding wave have been merged into the designated
Phase 2.6 integration branch:

```text
P2.6.0
  -> P2.6.1 + P2.6.10 + P2.6.8 isolation spike/review contract
     + P2.6.9 context/transient-candidate contract + P2.6.7
  -> P2.6.2 + P2.6.3 + P2.6.5 + P2.6.8 isolated-runtime integration
  -> P2.6.4
  -> P2.6.7/P2.6.8/P2.6.9/P2.6.10 integration and activation closure
  -> P2.6.6
  -> P2.6.11 final acceptance
```

- P2.6.0 is a single contract-owning workstream. It fixes shared grammar, state-machine boundaries,
  scenario fixtures, migration allocation and ownership before implementation branches diverge.
- Every item shown with `+` is developed on a separate short-lived feature branch with its own task
  plan, threat model, migrations and verification record. Parallel branches must not be stacked on
  unmerged sibling branches.
- At the end of each wave, completed branches are merged one at a time into the designated Phase 2.6
  integration branch, contract tests and migration checks are rerun after every merge, and the full
  wave gate is verified before the next dependent wave starts. A calendar date or code completion
  alone does not open the next wave.
- Shared compiler schemas, runtime transition primitives and migration numbering have one named
  integration owner. Parallel branches extend those seams through agreed interfaces; they do not
  independently redesign or merge competing versions of the same core contract.
- P2.6.7 may start in the first parallel wave; its live integration/activation closes only after its
  security and operations gates pass. P2.6.8 runtime work waits for the isolation ADR and P2.6.1.
  P2.6.9 may build context/transient Studio behavior early but consumes Python-node catalog metadata
  only after that public metadata contract is merged.
- P2.6.11 product, diagnostics, evaluation, audit and operations work accompanies every delivered
  part. Only its cross-part enterprise acceptance and closure gate is last.

Detailed P2.6.0 execution record:
[`phase-2-6-contract-and-scenario-foundation`](../tasks/phase-2-6-contract-and-scenario-foundation/plan.md).

Detailed P2.6.1 plan and threat model:
[`phase-2-6-part-1-typed-state-mapping`](../tasks/phase-2-6-part-1-typed-state-mapping/plan.md).

Detailed P2.6.2 plan and threat model:
[`phase-2-6-part-2-parallel-join`](../tasks/phase-2-6-part-2-parallel-join/plan.md).

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
| P2.6.8 | Reviewed scenario-author Python nodes and isolated execution | P2.6.0 spike/ADR; authoring lane E, runtime integration after P2.6.1 | Explicit authz + production dependency/runtime approval; sandbox escape and resource-isolation proof |
| P2.6.9 | Context-aware AI planner embedded in Scenario Studio | P2.6.0; lane F, safe Python-node catalog integration after P2.6.8 contract | Tenant-context non-disclosure, reference-conformance and no-auto-persist proof |
| P2.6.10 | Durable ingestion job lifecycle and worker/config readiness | P2.6.0; operational lane G | Additive schema/authz approval; queue outage, crash/restart, tenant isolation and real-service smoke |
| P2.6.11 | Incremental Studio/eval/operations integration and enterprise acceptance pack | Each delivered part | Full regression, PostgreSQL recovery, Turkish journey and owner sign-off |

Detailed P2.6.8–P2.6.9 plan and threat model:
[`phase-2-6-authoring-and-python-nodes`](../tasks/phase-2-6-authoring-and-python-nodes/plan.md).

Dedicated P2.6.9 implementation plan and threat model:
[`phase-2-6-part-9-studio-authoring-context`](../tasks/phase-2-6-part-9-studio-authoring-context/plan.md).

Detailed P2.6.10 plan and threat model:
[`phase-2-6-ingestion-operational-lifecycle`](../tasks/phase-2-6-ingestion-operational-lifecycle/plan.md).

## P2.6.0 — Contract and scenario foundation

- Create ADRs for the durable orchestration state machine and child-run authority.
- Freeze representative scenarios before implementation:
  - regulatory evidence and exception decision;
  - human-approved infrastructure change with post-change verification and rollback;
  - procurement exception with separation of duties;
  - AML/fraud evidence fan-out and deterministic synthesis;
  - data-governance/PII remediation pipeline;
  - incident observe–act–verify loop;
  - contract-review composition with bounded child workflows/agent calls; multi-agent supervision
    remains Phase 3 scope.
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

## P2.6.8 — Reviewed scenario-author Python nodes

- Keep the current preinstalled package-backed node as the **managed node** execution class. Preserve
  its existing artifact/registry/runtime compatibility and label it clearly in Studio.
- Add a distinct **Python node** authoring class for scenario authors. Drafts contain display name,
  purpose, bounded source, requested standard-library modules, config/input/output JSON Schemas and
  server-owned organization/project/scenario lineage. Users never supply logical ID, slug or
  revision.
- Treat requested modules as a subset of a platform-owned closed allowlist. Review cannot grant a
  module or permission absent from runner policy.
- Implement immutable content-addressed revisions and a review state machine: draft → submitted →
  changes requested/rejected/approved → active/disabled. A decision binds the exact revision and
  checksum; any content/schema/module change creates a new revision and invalidates prior approval.
- Restrict approval/activation/rejection/disable to platform admin. Scenario authors manage and test
  authorized drafts; organization admins see organization metadata/status; auditors see safe
  metadata and history only.
- Store source outside workflow JSON, release manifests, node-schema responses, logs and audit
  payloads. Workflow/release references contain only an opaque node ref, exact revision/checksum and
  public schemas/description.
- Require a focused isolation spike and ADR before runtime implementation. The minimum accepted
  first-release boundary is a separate non-root, credentials-free, network-denied, resource-limited
  runner container/service. Stronger gVisor/Kata/microVM isolation is optional hardening selected
  only if the spike, deployment platform or risk review justifies its operational cost. Python
  AST/import filtering alone is not an isolation boundary.
- Run mandatory automated security review before human review: syntax/AST and closed-import checks,
  forbidden builtin/reflection checks, source/schema bounds, static security rules, schema fixtures,
  timeout/memory/output probes and a versioned rule-set report. Critical findings block submission or
  approval; warnings require an explicit platform-admin rationale.
- Execute test and runtime calls outside web/runtime/worker processes with no application database
  credential, secret store, ambient service token, network, writable host filesystem or process
  capability; enforce wall/CPU/memory/PID/output limits and terminate on breach.
- Allow workflows to select only active, organization-allowed exact revisions. Pending/rejected/
  disabled revisions may appear as authoring status but cannot pass canonical save/publish/release
  gates. Disabling prevents new runs/releases while preserving historical run and review lineage;
  in-flight policy must be decided in the ADR.

### Exit criteria

- Minimum-runner spike and ADR are approved before any tenant-source execution implementation;
  stronger sandbox technology is not a first-release prerequisite unless the spike requires it.
- Automated review is reproducible, checksum/rule-set bound and cannot be bypassed for critical
  findings.
- Exact-revision review, separation of duties, cross-tenant denial, stale-approval invalidation,
  disable, timeout/OOM/output-limit and sandbox-escape negative tests pass.
- Existing managed nodes and releases remain compatible and visibly distinct from Python nodes.

## P2.6.9 — Context-aware AI planning inside Scenario Studio

- Make Scenario Studio the single scenario-authoring surface: AI planner, graph/JSON editor,
  diagnostics, node catalog, Python-node lifecycle/status, artifact/release relationships and the
  save/publish/eval/promotion journey.
- Build a deterministic, bounded, tenant/scenario-scoped authoring-context snapshot server-side.
  Include safe scenario/project/organization metadata, current DSL/node contracts and limits,
  active managed/Python node public schemas, active tool-binding roles plus approval flag, available
  prompt/model/retrieval roles, document-set capability summary, input/output contracts and safe
  draft/candidate/active lifecycle metadata.
- Exclude secrets, credentials, endpoints, Python source, document contents, foreign-tenant data and
  unnecessary actor/operational data. Stable-order and checksum the context; audit only identifiers,
  counts, byte/token totals and checksums.
- Send three separated model inputs: immutable server system contract, server authoring context and
  untrusted user description. Neither context nor user text grants authority.
- Require a structured union result: `workflow_candidate` or `capability_missing`. Generated refs
  must be members of the supplied snapshot. Missing capability returns a bounded suggested
  Python-node description and may open an unsaved Python-node draft scaffold; AI never reviews,
  approves, activates, publishes, releases or promotes it.
- Keep the AI result as transient in-memory Studio state. Generation creates no database row. Initial
  delivery does not use `localStorage`/`sessionStorage` for model output or Python source; use dirty
  navigation warnings. Revisit short-lived browser recovery only through a separate privacy/XSS
  decision.
- Normalize a transient workflow with a server-owned placeholder metadata ID for diagnostics. On
  explicit save, allocate the collision-safe logical ID through the existing identifier service,
  replace the placeholder server-side, re-authorize lineage and re-run canonical validation. The
  user may edit only the display name before first save.
- If a scenario already has drafts, require explicit update-existing versus create-copy selection.
  Updating uses the exact revision read; copying allocates a new logical ID. Never silently
  overwrite.
- Return bounded raw model text plus JSON-pointer diagnostics when parsing fails so an invalid
  candidate can be repaired transiently. It cannot be saved until canonical validation passes.
- Provide Turkish-first statuses for generating, timeout, rate limit, invalid JSON, missing
  capability, `outcome_unknown`, stale revision and server-validation drift.
- Revalidate every node/tool/prompt/model/retrieval/schema reference against live authorized state on
  generation response, explicit save, publish and release compile to close snapshot-to-use races.

### Exit criteria

- AI candidate generation creates no `WorkflowDraft`, artifact, release or custom-node record.
- Cross-tenant context/reference tests, secret/source/endpoint non-disclosure tests, invented-ref
  rejection, context-size limits and stale-capability races pass.
- Save allocates identifiers server-side and preserves scenario/project/organization lineage;
  update/copy choices and optimistic concurrency are verified.
- Capability-missing suggestions enter only the normal Python-node draft/review path.

## P2.6.10 — Durable ingestion job lifecycle and worker/config readiness

- Add a tenant-owned staged-index build job before broker dispatch, carrying immutable request
  checksum and lineage, attempt, bounded progress, timestamps, safe error code and result index.
- Use server-owned states `dispatch_pending`, `queued`, `running`, `retry_wait`, `succeeded`,
  `failed`, `cancelled` and `reconciliation_required`; expose delay/stall initially as derived health.
- Use a durable outbox/reconciler so a crash between database commit and broker publish cannot lose
  work. Claim transactionally and enforce one active build per tenant/set/profile/fingerprint.
- Preserve at-least-once Celery delivery while making duplicate delivery, late acknowledgement and
  worker loss converge without duplicate index creation or automatic promotion.
- Publish safe queue-role heartbeats with service/contract revision and a non-secret configuration
  fingerprint. Only recent compatible ingestion consumers count as ready; multiple are healthy,
  while stale/mismatched workers are operator-visible.
- Keep `/health/live` as process liveness and `/health/ready` as coarse web dependency readiness.
  Add authenticated component readiness, worker-local probes and metrics without exposing topology
  or making query serving unavailable solely because ingestion is degraded.
- Establish one Compose/host environment contract. Preflight verifies code/contract, broker and
  non-secret object-store identity across web/runtime/ingestion roles; credentials are checked for
  usability but never displayed or fingerprinted.
- Reconcile unsent, old-unclaimed and stale-running jobs in bounded batches. An exact committed
  promotable index may close a lost final update; ambiguous provider outcomes are never blindly
  retried and require explicit reconciliation.
- Show Turkish-first durable status, timestamps, safe failure guidance and monotonic progress with
  bounded polling/manual refresh. Retry/cancel are authorized, audited transitions. Promotion stays
  a separate existing release-management action.
- Emit low-cardinality status/age/latency/heartbeat/duration/failure metrics. Tenant, job and worker
  instance identifiers belong in redacted logs/traces/audit, never metric labels.

### Exit criteria

- Requests remain visible and recoverable with no worker, broker failure, web crash after commit,
  worker death during build or a lost final success update.
- Console distinguishes dispatch-pending, queued/no-compatible-worker, running, retry-wait,
  succeeded/promotable, failed and reconciliation-required without exposing secrets/topology.
- Authorization denial and cross-tenant read/retry tests pass; promotion authority is unchanged.
- SQLite lifecycle tests, PostgreSQL concurrency/RLS tests and a real Redis/Celery/MinIO `.txt`
  upload-to-authenticated-query smoke pass with restart and unavailable-worker cases.
- Host-mode and Compose preflight start equivalent queue roles/configuration and detect stale or
  mismatched processes before reporting component readiness.

## P2.6.11 — Product, evaluation and operational closure

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
- mutable `PythonNodeDraft`, immutable content-addressed Python-node revision and exact-checksum
  review/activation records; source storage remains separate from public artifact/manifest bodies;
- versioned bounded authoring-context and structured AI result contracts.

No artifact body may contain a raw endpoint, credential, tenant authority, executable expression or
unbounded template. Endpoint/secret material remains in platform-managed profiles and the governed
tool registry.

## Data and state model impact

Likely additive durable records include branch attempts/results, join state, external wait
correlations, human tasks, compensation entries, parent/child run links, Python-node drafts/revisions,
review decisions, staged-index build jobs, dispatch outbox entries and safe worker-role heartbeats. Exact tables are deferred
to part task plans. Every tenant-owned row requires direct organization lineage, FORCE RLS where
applicable, non-owner-role verification and bounded retention.

## Security and authorization requirements

- Deny unknown node/action/version/state paths and unknown planner decisions.
- Re-run authorization at every tool, retrieval, child-run, resume and operator action boundary.
- Treat model/tool/event/child output as injection-capable untrusted data.
- Enforce capability attenuation and cumulative budgets across nested execution.
- Protect resume/approval/compensation decisions against replay, substitution and self-approval.
- Keep secrets out of DSL, state, observations, logs, traces, metrics and eval reports.
- Never execute tenant Python in a process or container carrying application DB, network or secret
  authority; source and test payload access is role-scoped and never copied to logs/audit.
- Build AI context from server-authorized queries, disclose only safe catalog metadata and reject
  every model-generated reference absent from the bounded snapshot and current live state.
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
- Python-node review checksum binding, sandbox resource/escape denials and managed-node compatibility;
- automated-review critical-block/warning-rationale behavior and rule-set revision lineage;
- AI context tenant isolation/non-disclosure, invented-ref rejection and transient no-write proof;
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
- Keep Python-node execution and context-aware AI authoring disabled independently until their
  threat models, runner/profile provisioning and rollback checks pass.

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
- Tenant Python is remote-code execution by design; a weak in-process or shared-credential sandbox
  would be a critical platform compromise.
- AI context assembly can leak cross-tenant catalog, endpoint, source or schema details and can
  become stale before save/release validation.
- Dispatch-only ingestion feedback can hide missing consumers; stale/config-mismatched workers can
  accept work they cannot finish, while unsafe retries can duplicate external effects.
- A large phase can become unreviewable unless each part remains independently gated.
- Parallel branches can conflict in shared compiler/runtime files; contract ownership and integration
  order must be assigned before concurrent implementation.

## Open decisions

Owner decisions closed on 2026-07-16:

- Revise `agenthub/v1` in place; do not add workflow v2.
- Keep MCP catalog synchronization in Phase 2.6.
- Move optional multi-agent supervision to Phase 3.

Additional owner decisions closed on 2026-07-16 in P2.6.0:

- Restricted absolute JSON Pointer paths and explicit mapping; protected namespaces fail closed.
- `all`, `threshold` and `fail_fast` joins with branch-owned state and explicit deterministic merge.
- Authenticated HTTP event ingress with opaque one-time correlations stored only as hashes.
- A distinct typed `human_task` primitive sharing approval security invariants.
- Fail-closed required audit for security/business decisions; fail-open optional telemetry.
- Explicitly named and separately confirmed local/development/test-only reset procedure.

Remaining decisions owned by later parts:

1. Confirm the minimum isolated-runner baseline and decide whether stronger sandbox hardening is
   justified through the P2.6.8 spike/ADR.
2. Decide source-at-rest encryption, retention and authorized source-view roles.
3. Decide whether disabling a Python-node revision cancels in-flight calls or only blocks new ones.
4. Approve the authoring-context section/byte/token budgets and initial memory-only transient policy.
5. Approve ingestion job states, timeout/heartbeat thresholds and PostgreSQL-versus-Redis heartbeat
    authority.
6. Decide shared versus ingestion-specific durable outbox and provider `outcome_unknown` retry
    ownership.

## Status

**In progress; P2.6.0 completed and committed.** The contract inventory, Accepted ADR-0008/0009/0010,
target DSL contract, migration/ownership/merge matrix and seven inert enterprise target workflows
are verified in the P2.6.0 task record. No runtime behavior or database was changed. The first
parallel implementation wave opens only from the committed/merged P2.6.0 integration baseline.

## Completion criteria

Phase 2.6 is complete only when all owner-selected parts are individually planned, threat-modeled,
implemented and verified; current-state documentation matches code; dummy legacy artifacts are
fully replaced with no stale grammar; enterprise scenario artifacts pass compiler/eval/promotion gates; recovery and rollback
are demonstrated; and the master plan records verification evidence and accepted residual risks.
