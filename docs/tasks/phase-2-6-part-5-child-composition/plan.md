# Task Plan: phase-2-6-part-5-child-composition

## Task summary

Implement P2.6.5 as a disabled-by-default, pinned child-composition increment for `subworkflow` and
single `agent_call` nodes. A parent release may invoke only an exact child role pinned into its
immutable manifest. Runtime creates a separate tenant-scoped child run, maps only approved input,
recomputes attenuated authority server-side, enforces cumulative bounds and validates mapped output
before resuming the parent.

## Background

The current workflow runtime executes nodes inside one `WorkflowRun`; it does not provide a durable
parent/child execution boundary. P2.6.0 fixed the target DSL shape and accepted ADR-0009: parent
authority is not delegated to a child, model/client state is never authorization proof, and the
effective child capability set is the intersection of four server-owned sources.

P2.6.1 now provides canonical typed input/output mapping. P2.6.5 uses that seam without redesigning
mapping or the shared transition state machine. S07 contract review is the primary reference
scenario. Generic error recovery/compensation remains P2.6.4-owned and iterative multi-agent
supervision remains Phase 3.

## Scope

- Compile strict `subworkflow` and `agent_call` node contracts from release-manifest role names.
- Resolve each role at release compile time to an exact child kind, artifact revision, checksum,
  scenario/project/organization lineage and maximum capability/action envelope.
- Reject mutable/latest references, raw artifact IDs, endpoints, model-selected roles and
  cross-organization targets.
- Require P2.6.1 input/output mappings and validate them against parent and child schemas.
- Add a tenant-owned immutable parent/child link carrying parent run, call-site, child release/run,
  lineage/checksums, effective-capability checksum, status, deadlines, counters and safe reason
  metadata.
- Create a separate child run and freshly signed bounded execution context for every accepted call.
- Re-authenticate/re-authorize the boundary and compute effective child authority as the intersection
  of parent effective capabilities, compiled call-site envelope, child release/policy allowlists and
  current tenant/consumer authorization.
- Enforce same-organization lineage plus maximum depth, children per parent, cumulative calls,
  tokens/tool calls/state bytes and deadline.
- Detect statically knowable release-call cycles at compile/activation time and retain a runtime
  ancestry/depth guard for stale or independently compiled releases.
- Dispatch and consume child start/result commands idempotently; broker identifiers are locators,
  not authorization.
- Propagate cancellation as a bounded idempotent request and prevent late/duplicate child results
  from mutating a terminal parent.
- Emit safe parent/child trace and audit linkage without input/output, credentials, tokens or hidden
  policy details.
- Keep activation behind a capability/feature gate until compiler, runtime, migration, authorization,
  recovery and PostgreSQL non-owner evidence pass.

## Non-goals

- Multi-agent delegation, supervisor/peer negotiation, child-created children or capability
  delegation beyond the compiled call graph.
- Dynamic child selection by a model, client, workflow state, URL, artifact ID or “latest” lookup.
- Cross-organization composition.
- P2.6.4 generic retry classification, error edges, compensation or automatic handling of
  `outcome_unknown`.
- P2.6.6 observe-act-verify loops or planner-selected repeated actions.
- Parallel child fan-out/join semantics owned by P2.6.2.
- Human/timer/event waits owned by P2.6.3.
- A new workflow engine, broker or production dependency.
- Retrofitting composition rights into existing releases.

## Acceptance criteria

1. Compiler accepts only known `subworkflow`/`agent_call` keys, a pinned manifest role, mandatory
   typed mappings and bounded configuration; it emits stable diagnostics for missing, mutable,
   foreign, incompatible or cyclic child references.
2. Parent releases pin exact child kind/revision/checksum, schemas, lineage, maximum authority,
   allowed agent actions and resource bounds. Runtime cannot substitute or resolve a newer child.
3. Effective child capabilities equal the server-side intersection of all four ADR-0009 sources.
   Missing context, empty intersection or any authorization denial fails closed.
4. Parent/client/model state cannot set organization, project, scenario, consumer, release,
   capability, action, budget or authorization context for the child.
5. Child receives only schema-approved mapped input and a fresh bounded execution context. It never
   receives full parent state, parent token, credentials or hidden policy data.
6. Parent and child use separate durable runs connected by a direct-organization-scoped immutable
   link with checksum/version/idempotency constraints and auditable lifecycle transitions.
7. Maximum depth, child count, cumulative calls/tokens/tool calls/state bytes and deadline are
   enforced transactionally. Static and runtime cycle guards deny recursion and budget amplification.
8. Duplicate dispatch/result delivery is idempotent. Cancellation prevents new child admission,
   propagates once and ensures late results cannot reopen or mutate a terminal parent.
9. Child output is untrusted, size/schema/redaction validated and applied only through the compiled
   P2.6.1 output mapping.
10. Child failure/timeout/`outcome_unknown` produces a stable safe outcome for the parent seam; it is
    not automatically retried or compensated before P2.6.4.
11. Tenant context, object/action authorization and FORCE RLS deny foreign link/run/release
    substitution under PostgreSQL non-owner coverage.
12. S07 proves pinned clause-extraction subworkflow and contract-risk agent calls, including
    capability attenuation, mapped state, depth/call limits and denial cases.
13. Applicable formatter, lint, type, Django, migration, SQLite, PostgreSQL and Celery recovery
    checks pass and staff-engineering, application-security and SRE reviews are recorded.

## Affected components

- release compiler/manifest resolver: child-role pinning, schema compatibility and call-graph checks
- `apps/workflows/compiler.py`: strict node config, mappings and budget validation
- workflow transition/runtime/task services: child admission, dispatch, completion and cancellation
- workflow models plus additive migration: parent/child link and bounded lineage/budget metadata
- agent runtime entry seam for a pinned single `agent_call`
- gateway execution-context service: fresh child-bound context, without changing public invoke routes
- tenant RLS provisioning and non-owner tests for new tenant-owned records
- evaluations, S07 fixtures, Studio diagnostics/catalog and authorized trace/status presentation
- observability/audit events and bounded operational reconciliation

## Interfaces affected

The unreleased canonical `agenthub/v1` graph gains the P2.6.0-defined `subworkflow` and `agent_call`
node types. Their configs name manifest roles only:

- `subworkflow`: `workflow_role` plus bounded `max_depth`
- `agent_call`: `agent_role`, bounded `max_decisions` and a closed `allowed_actions` subset

Both require `input_mapping` and `output_mapping`. Compiled manifests and resumable transition
records gain a versioned child-authority contract. Existing consumer invoke/status/cancel endpoints
remain compatible; no new public endpoint is planned.

Stable diagnostics should include invalid child role, incompatible child contract, composition
cycle, authority denied and composition budget exceeded without exposing policy internals.

## Data impact

Add an append-preserving tenant-owned parent/child link with direct organization lineage, immutable
parent and child run/release/checksum association, call-site identity, expected transition revision,
effective-capability checksum, bounded counters/deadlines, safe statuses/reasons and timestamps.
Prefer references and hashes over duplicated payloads.

Mapped parent input and child output may contain confidential tenant data. Persist them only in the
existing bounded run-state locations required for execution; do not duplicate them into link,
audit, trace or usage records. Define retention with existing run evidence.

## Security impact

Composition introduces confused-deputy, capability amplification, recursion and over-disclosure
risks. The boundary is deny-by-default, same-organization, exact-release-pinned and schema-mapped.
All authority and lineage are resolved from server-owned records. See [threat-model.md](threat-model.md).

## Authorization impact

The child does not inherit parent authorization. Effective authority is recomputed as:

1. parent run effective capabilities,
2. compiled call-site maximum envelope,
3. child release and policy allowlists,
4. current server-side tenant/consumer authorization.

The intersection cannot add authority. Child organization/project/scenario/release/action access is
then re-authorized against live server state. IDs, checksums, workflow state and broker payloads are
not proof. This implements accepted ADR-0009; any broader delegation or new public/operator action
requires separate approval.

## Observability impact

Add stable events for child admission denied/accepted, dispatch, start, completion, failure,
cancellation request/acknowledgement, late result and budget/cycle denial. Trace parent and child
with safe opaque linkage. Metrics use bounded child kind/status/reason labels; tenant, run, artifact
and capability-set identifiers are not metric labels. Audit capability and lineage checksums, never
raw capabilities when sensitive, tokens, mapped state, policy internals or provider errors.

Required authorization/admission audit failure is fail closed. Optional telemetry failure must not
change the transition result.

## Migration impact

A forward-only additive migration is expected for the parent/child link and supporting constraints/
indexes. It must include direct organization lineage, tenant-consistent foreign-key validation where
the repository pattern permits, idempotent call-site identity and FORCE RLS provisioning. The live
migration graph must be inspected immediately before allocation. No destructive migration or reset
is authorized.

## Dependencies

- Merged and verified P2.6.0, ADR-0008, ADR-0009 and target DSL corpus
- Merged and verified P2.6.1 typed state mapping
- Existing immutable artifact/release compiler and role-binding conventions
- Existing workflow and agent run entry points, signed execution context and tenant authorization
- Integration-owner allocation of shared transition commands and migration number
- P2.6.4 before activation of generic error/recovery behavior; P2.6.6 before advanced agent-loop use

## Implementation steps

1. Reinspect merged compiler, release bundle, workflow/agent runtime, execution context, policy,
   transition and migration seams; update this plan if implementation reality differs.
2. Freeze initial hard limits, link lifecycle, budget accounting, child failure result and
   cancellation semantics. Add an ADR only if ADR-0009 must materially change.
3. Add compiler/manifest tests for strict configs, exact role pinning, child schema compatibility,
   closed actions, call-graph cycles and cumulative bounds.
4. Extend release compilation to pin exact child metadata and authority envelopes; preserve
   compatibility for releases without composition nodes.
5. Add the tenant-owned parent/child link, constraints, indexes, RLS provisioning and migration
   tests through the integration-allocated additive migration.
6. Implement one typed composition service that resolves server-owned lineage, locks the parent,
   re-authorizes all four sources, computes the effective set/checksum and atomically admits or
   denies the child under cumulative budgets.
7. Issue a fresh bounded child execution context and create a separate child run using only mapped,
   schema-valid input. Keep broker tasks minimal and untrusted.
8. Implement idempotent dispatch/start/completion consumption, output validation/mapping, terminal
   guards and bounded reconciliation for committed-but-undispatched/stale internal work.
9. Implement cancellation propagation, late-result evidence and safe failure/timeout/
   `outcome_unknown` mapping without generic retry or compensation.
10. Wire pinned single `agent_call` through the same authority and budget boundary; do not add an
    iterative planner loop.
11. Add S07 fixtures/evals, safe trace/audit/operator diagnostics and keep activation disabled.
12. Run focused/full SQLite and PostgreSQL non-owner tests plus real Celery redelivery/restart smoke;
    record evidence in `verification.md`.
13. Review the final diff for capability amplification, tenant/RLS escape, lock ordering,
    idempotency, cancellation races, data over-disclosure, migration rollout and operational recovery.

## Test plan

- Compiler tests: unknown keys, missing role, raw/latest reference, wrong child kind, incompatible
  schemas, invalid mappings/actions/bounds, direct/indirect cycle and deterministic manifest output.
- Authorization tests: each of the four authority sources independently removes a capability;
  empty/missing context, disabled release/grant and unauthorized action all fail closed.
- Tenant tests: cross-organization role/run/link substitution, missing tenant scope, forged broker
  lineage and PostgreSQL non-owner/FORCE RLS denial.
- State/privacy tests: minimum mapped input only, protected context cannot be mapped, oversized/deep
  child input/output denied and full parent state never reaches the child.
- Budget tests: exact/over max depth, children, calls, decisions, tokens, tools, state and deadline;
  nested totals cannot reset at a child boundary.
- Concurrency/idempotency tests: duplicate admission/dispatch/result, simultaneous cancel/result,
  parent terminal transition and stale child completion.
- Failure tests: child validation/auth/permanent/transient/timeout/`outcome_unknown`, worker loss,
  broker failure and committed-undispatched reconciliation without unsafe external retry.
- Compatibility tests: existing workflows/agents/releases and public invoke/status/cancel behavior
  remain unchanged when composition is absent or disabled.
- Observability/audit tests: complete boundary decisions, safe checksums/reason codes, redaction,
  required-audit failure and bounded metric labels.
- S07 executable happy/denial/budget/cancellation scenarios.
- Repository gates: formatting, Ruff, mypy, Django check, migration drift, focused/full SQLite,
  PostgreSQL RLS/non-owner/concurrency and real Celery restart/redelivery as applicable.

## Rollout plan

- Keep composition compile/activation and runtime admission disabled by default.
- Apply additive schema/RLS before matching web/workers; reject incompatible checkpoint/contract
  versions fail closed.
- Enable first for deterministic non-production S07 with conservative depth/count/budget caps.
- Observe admission denials, child age, cancellation lag, stale links, reconciliation outcomes,
  cumulative budget usage and database contention before organization canaries.
- Do not enable P2.6.4 recovery or P2.6.6 advanced agent behavior until their gates pass.

## Rollback plan

- Disable new composition admission globally/per organization while preserving status and bounded
  cancellation for existing children.
- Preserve additive tables and parent/child evidence. Drain/cancel with matching workers or
  forward-fix; do not let older workers reinterpret incompatible checkpoints.
- Roll code back only when no incompatible active child links remain. Never delete link/audit/run
  history as rollback.

## Risks

- A parent capability or signed context may accidentally be copied rather than attenuated.
- Role resolution may drift to a newer child revision after parent compilation.
- Child budget counters may reset at nesting boundaries and amplify cost/state.
- Concurrent admission can exceed child/depth budgets without transactional locking.
- Cancellation/result races can resume a terminal parent or apply output twice.
- Call-graph cycle checks can miss cycles across independently promoted releases.
- Schema mappings can disclose full parent state or write protected parent keys.
- Broker payloads may be trusted for tenant/release/capability lineage.
- Parent/child trace or audit output may leak mapped content or policy details.
- Shared runtime changes can conflict with P2.6.2/P2.6.3 branches during wave integration.

## Open questions

1. What conservative initial maxima apply to depth, direct children, cumulative child calls,
   decisions, tokens, tool calls, mapped bytes and elapsed time?
2. Does the first increment permit a child release that itself contains composition nodes, or keep
   runtime nesting disabled while still implementing ancestry guards?
3. Which existing release-manifest role structure should own exact child artifact pins without
   creating a second binding mechanism?
4. What safe parent outcome represents child failure before P2.6.4 error routes are available?
5. Is composition dispatch represented by the existing transition intent, a small child-link
   outbox field, or the integration-owned reusable dispatch seam?
6. Which current tenant tables can support database-level tenant-consistent foreign keys, and where
   must service validation plus FORCE RLS provide the invariant?
7. What retention window applies to completed parent/child links relative to workflow run evidence?

## Resolved decisions (2026-07-17)

The pre-implementation open questions are closed as follows against the merged P2.6.1 baseline.

1. **Conservative initial maxima** (`apps/workflows/composition.py`):
   `MAX_COMPOSITION_DEPTH = 3` (a call-site `max_depth`/`agent_call` may only *lower* it),
   `MAX_CHILDREN_PER_PARENT = 8`, `MAX_CUMULATIVE_CHILD_CALLS = 16`,
   `MAX_COMPOSITION_TOKENS = 64_000`, `MAX_COMPOSITION_TOOL_CALLS = 20`. Mapped child input/output
   reuse the existing per-run `MAX_STATE_BYTES = 1 MiB` ceiling. A child deadline is
   `min(parent_remaining, child_default)` so elapsed time cannot reset at a boundary.
2. **Nested composition policy:** nesting is permitted up to `MAX_COMPOSITION_DEPTH` and bounded by a
   runtime **ancestry/depth guard** carried in the child execution-context composition claim. A child
   whose scenario already appears in the ancestry chain is denied (`COMPOSITION_CYCLE`). Static
   analysis rejects a node whose pinned child resolves to the parent's own scenario; cross-release
   cycles are caught only by the runtime guard (documented residual risk).
3. **Manifest-role ownership:** no second binding mechanism. Child pins reuse the release manifest via
   the existing type-prefixed role namespace: `child_workflow.<name>` pins a `workflow_definition`
   and `child_agent.<name>` pins an `agent_definition`. `role_accepts_artifact_type` is extended
   (additive) to accept those prefixes; the parent's own runtime role stays the singleton
   `workflow_definition`/`agent_definition`. The compiler derives the child scenario + its **active**
   release from the pinned child artifact and records `{kind, ref, checksum, child_scenario_id,
   child_release_id, child_release_checksum}`; admission re-resolves the child's active release and
   fails closed (`COMPOSITION_CHILD_STALE`) on any drift.
4. **Child failure parent outcome (pre-P2.6.4):** child `failed`/`timed_out`/`cancelled`/
   `outcome_unknown` produce a single stable terminal parent failure `COMPOSITION_CHILD_FAILED`
   (timeout → `COMPOSITION_CHILD_TIMED_OUT`). No automatic retry or compensation; P2.6.4 owns error
   routes. An ambiguous child effect is never retried.
5. **Dispatch/reconciliation seam:** composition reuses the proven tool-approval pause/resume seam
   rather than redesigning the ADR-0008 transition core. The parent node atomically admits the child
   (creates the immutable `WorkflowChildLink` + child run under `select_for_update` on the parent),
   pauses the parent (`waiting_child`), and dispatches the child run through its existing Celery task
   on commit. The child's terminal transition emits a post-commit signal that re-dispatches the parent
   task, which validates the child link/output and resumes. Duplicate admission is idempotent on the
   link's `(parent_run, call_site)` unique constraint; a late/duplicate child result cannot mutate a
   terminal parent (terminal-status guards).
6. **Tenant FK invariants:** `WorkflowChildLink` carries a non-null `organization` FK (direct lineage)
   and is provisioned with `FORCE ROW LEVEL SECURITY` by the additive migration, matching the
   ADR-0004 pattern. Cross-scenario/child references are validated in `clean()` and re-validated
   server-side at admission; database-level cross-table tenant FKs are not added (repository pattern
   uses service + RLS, as with existing run tables).
7. **Retention:** links share the workflow-run evidence retention window (no separate purge job in
   this increment; recorded as an operational follow-up alongside the ADR-0008 checkpoint purge).

## Status

Planned → Implemented (disabled by default). Initial numeric limits, nested composition policy,
child-failure parent outcome, manifest-role ownership and dispatch seam are closed above.

## Completion criteria

This task is `Implemented` when compiler pinning, additive link persistence, server-side authority
attenuation, separate child execution, bounds, cancellation, diagnostics and S07 coverage form a
disabled-by-default complete increment. It is `Verified` only after recorded SQLite, PostgreSQL
non-owner/RLS/concurrency and Celery redelivery/restart evidence plus security/SRE review. It is
`Completed` after current-behavior docs, Phase 2.6/master-plan evidence and integration-owner
acceptance are updated.
