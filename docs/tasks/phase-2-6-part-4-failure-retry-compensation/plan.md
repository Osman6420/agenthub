# Task Plan: P2.6.4 failure, retry and compensation

## Objective

Add deterministic, durable and tenant-safe workflow failure handling after P2.6.2/P2.6.3/P2.6.5:
stable failure classification, explicit error routes, bounded idempotent retry, compile-time pinned
compensation and audited operator recovery. Never blindly repeat or compensate an ambiguous external
side effect.

## Current baseline

- `WorkflowRuntimeError` carries a stable code, but failures currently terminate the run directly.
- Tool invocations already persist idempotency, terminal status and `outcome_unknown`; terminal
  invocations are never blindly executed again.
- Parallel branches, durable waits and child composition have terminal/late-result guards.
- The compiled workflow graph is immutable and versioned, but edges currently support only
  condition and parallel branch selectors.
- No durable workflow-node attempt/recovery record, retry scheduler, compensation stack or operator
  recovery decision exists.

## Decisions

### Failure taxonomy

The runtime maps stable reason codes to exactly one class:

- `validation`: contract/schema/mapping/input/output violations; never retry.
- `authorization`: capability, tenant, policy, approval and disabled-resource denials; never retry.
- `permanent`: unsupported configuration or deterministic business failure; never retry.
- `transient`: pre-dispatch infrastructure/provider availability failures that policy may retry.
- `outcome_unknown`: dispatch may have happened but outcome is unconfirmed; never automatically
  retry or compensate.

Unknown codes fail closed as `permanent`. Classification is server-owned; workflow authors cannot
relabel a code.

### DSL additions

- Node optional `retry_policy`:
  - `max_attempts`: integer `1..3`, including the first attempt.
  - `backoff_seconds`: bounded non-negative integer; server applies capped jitter.
  - `retry_on`: non-empty subset of `transient`; v1 does not permit author-controlled retry of
    other classes.
  - `idempotent`: must be `true`; compiler additionally rejects side-effecting tool retry unless the
    release-pinned tool contract declares a verified idempotency/reconciliation capability.
- Edge optional `on_error`: one of the five server failure classes or `any`. Error edges cannot also
  carry `when` or `branch`. At most one matching edge per source/class, with exact class preferred
  over `any`.
- Side-effecting nodes may declare `compensation` containing a compile-time node reference. The
  compensation node is not part of the normal success path, must be a governed tool/transform node,
  and must have an explicit input mapping from the bounded compensation snapshot.
- Compiler emits a pinned recovery section containing normalized retry policies, error routes and
  compensation references/checksum material; runtime never trusts author source after publication.

The compiled-workflow contract version must be bumped. Old compiled graphs remain rejected rather
than silently receiving new recovery semantics.

### Durable state

Add direct-tenant `WorkflowNodeAttempt` and `WorkflowCompensationEntry` records with FORCE RLS:

- Attempt: run, node id, ordinal, failure class/code, status, retry-not-before, safe checksums and
  timestamps. Unique `(run, node_id, ordinal)`.
- Compensation entry: run, source node, compensation node, reverse-order sequence, status, attempt,
  safe input checksum and terminal reason. Source payload/code/secrets are not persisted here.
- Broker tasks carry only organization id and durable record id.
- Row locks, terminal guards and idempotent transitions make duplicate/redelivered tasks safe.

The existing redacted workflow state remains the bounded checkpoint. Server-owned recovery metadata
is not writable through workflow mappings.

### Execution semantics

1. Before an eligible attempt, atomically claim/create its durable attempt record.
2. On success, mark the attempt complete and push a compensation entry only when the compiled node
   declares one.
3. On failure, classify the stable code server-side.
4. `outcome_unknown` pauses in explicit operator-required state; it is never automatically retried
   or compensated.
5. Eligible transient failure schedules a durable retry after bounded backoff. Cancellation and the
   run deadline always win.
6. Exhausted/non-retryable failure follows an exact error edge, then `any`, when present.
7. If no error route handles the failure, execute pending compensation entries in reverse completion
   order. Each compensation call has its own idempotency key and terminal record.
8. Compensation failure or ambiguity stops automatic recovery and requires operator action.
9. Late branch, wait, child, retry or compensation results cannot mutate a terminal parent.

### Approved operator recovery contract

Add a same-tenant console POST action over an exact system-created recovery revision. Organization
admins may decide cases only in their own organization; platform admins may decide across
organizations. High-risk compensation continuation requires two distinct organization/platform
admins. It supports only:

- `reconcile_confirmed_success`
- `reconcile_confirmed_failure`
- `resume_compensation`
- `terminate_failed`

The request requires a bounded reason code/text, optimistic revision/checksum and CSRF protection.
Scenario authors may view safe status but cannot decide ambiguous outcomes. Auditors remain
read-only. Every allow/deny/outcome is audited without payloads, code or secrets. No user, including
an admin, can create a recovery case, start an operation, directly repeat a tool call, choose a node,
edit state or request "retry anyway". Decisions only resolve a case the runtime already opened and
may continue only the release-pinned recovery policy.

The user explicitly approved this authorization and console-action scope on 2026-07-17.

## Implementation sequence

1. Freeze failure taxonomy, DSL schema and compiled-contract bump with compiler tests.
2. Add attempt/compensation models, linear migration, FORCE RLS and provisioning inventory.
3. Implement row-locked recovery transitions and bounded scheduler tasks.
4. Integrate runtime error routing, retry checkpointing and compensation-stack execution.
5. Add cancellation/late-result integration with parallel, wait and child state.
6. Add the approved bounded organization/platform-admin recovery console action and dual approval.
7. Add architecture/authoring documentation, scenario fixture and verification evidence.

## Test plan

- Compiler: closed schemas, duplicate/ambiguous routes, cycles, invalid compensation references,
  retry bounds and old compiled-version rejection.
- Runtime: every failure class, exact/any route selection, retry exhaustion, deadline/cancellation,
  duplicate task and restart checkpoint recovery.
- Side effects: no blind retry/compensation for `outcome_unknown`; verified reconciliation only;
  reverse compensation order and idempotent compensation redelivery.
- Authorization: anonymous/author/org-admin denial, platform-admin allow, auditor read-only,
  cross-tenant denial and stale revision denial.
- Security/audit: safe codes only, payload/code/secret redaction and audit persistence behavior.
- Database: migration forward/backward/forward, constraints and non-owner FORCE RLS proofs.
- Compatibility: existing v3 graphs/tests remain deterministic; feature-disabled behavior is explicit.

## Acceptance criteria

1. Retry occurs only for compiler-approved idempotent transient work and remains bounded/durable.
2. Ambiguous external outcomes never trigger blind retry or compensation.
3. Explicit error routes expose only stable class/code metadata in protected runtime state.
4. Compensation order and inputs are compile-time pinned, bounded, durable and idempotent.
5. Cancellation/deadline/terminal state wins over all late or duplicate recovery work.
6. Tenant, role and exact-revision authorization is enforced server-side and proven with denials.
7. PostgreSQL migration/RLS, crash/redelivery and complete regression evidence pass.

## Status

Implemented and verified on 2026-07-17. Evidence is recorded in
[`verification.md`](verification.md). Tool retry remains deliberately unavailable until a future
release-pinned idempotency/reconciliation contract can be verified server-side.
