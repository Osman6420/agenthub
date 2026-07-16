# ADR 0010: Workflow Dataflow, Join, Wait and Human-Task Contract

- **Status:** Accepted
- **Date:** 2026-07-16

## Context

Phase 2.6 needs a fixed declarative vocabulary for state mapping, deterministic parallel joins,
external event resume and human decisions before compiler/runtime branches can work independently.
The current workflow grammar has condition-only boolean edges and one tool-approval-specific pause.

## Decision drivers

- No arbitrary expression/template evaluation
- Deterministic results independent of branch completion order
- Replay-safe durable waits without sleeping workers
- Separation of duties for business decisions
- Backward-compatible treatment of existing tool approval and managed nodes
- A small contract that fits the current Django/PostgreSQL/Celery architecture

## Considered options

- Dot-paths versus unrestricted query languages versus a restricted JSON Pointer subset
- Implicit last-writer-wins versus explicit branch result ownership and merge mappings
- HTTP event resume versus a mandatory message-stream dependency
- Reusing tool approval for every human decision versus a typed human-task primitive

## Decision

### State paths and mappings

- Use an RFC 6901-style restricted absolute JSON Pointer subset such as `/input/customer_id`.
- Empty/root pointers, URI fragments, wildcards, recursive descent, filters, array append and
  negative indexes are forbidden. Escapes are limited to canonical `~0` and `~1`.
- Mapping entries are explicit `{from, to}` with an optional allowlisted `transform_ref`; they do
  not evaluate code, templates or model expressions.
- Compiler/runtime deny writes to server-owned tenant, actor, release, authorization, capability,
  secret, execution-context and orchestration-control namespaces.
- Source and target schema compatibility is checked at author/compile time where possible and again
  at runtime. Missing/type-invalid/oversized mappings fail with stable diagnostics.

### Parallel and join

- Initial join modes are `all`, `threshold` and `fail_fast`.
- A compiled parallel region owns a closed named branch set and one explicit join. Maximum branches,
  concurrency, duration and state bytes are hard bounded.
- Each branch writes only its branch-owned result namespace. Join output uses explicit ordered merge
  mappings. Implicit last-writer-wins and completion-order merge are forbidden.
- `threshold` declares an integer `required` count. A compiler rejects impossible thresholds,
  duplicate branch ownership, conflicting targets and ambiguous terminal paths.
- Join ordering is the compiled branch-name order, never task completion order.

### External event wait/resume

- Initial ingress is an authenticated bounded HTTP endpoint. Additional transports require their
  own adapter/ADR and produce the same internal resume command.
- A wait stores a typed expected event role/schema, opaque random correlation, expiry and one-time
  state. Only a hash of the public correlation secret is stored.
- Resume re-authorizes tenant/action, binds the exact wait/run/release/checksum and validates an
  allowlisted payload. Forged, expired, replayed, wrong-state and cross-tenant requests are denied
  and audited.
- Correlation never carries or replaces tenant, actor, release, capability or authorization data.

### Human task

- Add a workflow `human_task` primitive distinct from tool approval. It declares allowed decision
  roles, decision schema, separation-of-duties/self-approval rule, expiry and explicit timeout route.
- Human task and tool approval share lower-level decision security invariants (exact request
  checksum, role validation, expiry, one decision, audit) but retain separate domain records and UI.
- A human decision is untrusted input and maps into workflow state only through its declared schema.

### Audit and telemetry failure

- Security/business state changes including approval/decision, resume, activation/disable,
  promotion and operator recovery fail closed if their required audit evidence cannot commit.
- Optional application logs, metrics and traces fail open; their failure cannot authorize, repeat or
  roll back a successfully committed transition.

### Non-production reset

- Incompatible dummy workflow data may be reset only for an explicitly named local/development/test
  database after resolved host/name/user/environment display, production-like target denial,
  repopulation-source verification and separate owner confirmation.
- Reset is never implicit in a migration and is not authorized merely by this ADR.

## Security consequences

The closed path/mapping grammar reduces mass assignment and expression injection. One-time hashed
event correlations, exact checksum binding and server-side authorization reduce replay and confused
deputy risk. Human-task separation of duties is explicit rather than inferred from UI roles.

## Operational consequences

HTTP ingress avoids a mandatory new streaming dependency. Expired/stuck waits and join progress need
reconciliation, safe operator views and bounded-cardinality metrics.

## Data and privacy consequences

Wait/human-task records contain safe metadata and direct tenant lineage. Resume payloads and
decisions are schema/size bounded and redacted by classification; correlation secrets are never
stored or logged in plaintext.

## Positive consequences

- Parallel implementation lanes share exact semantics
- Deterministic joins are reproducible in eval and recovery
- Business decisions are modeled directly without pretending to be tool calls
- Initial transport/deployment remains simple

## Negative consequences

- Restricted pointers and explicit mappings are more verbose than general expressions
- A separate human-task lifecycle adds models and UI
- HTTP event producers need credential and token lifecycle integration

## Migration impact

P2.6.2 and P2.6.3 add typed branch/join/wait/human-task records with direct organization lineage.
P2.6.0 performs no migration or reset.

## Rollback considerations

Capability gates block new parallel/wait/human-task starts. Existing durable records remain evidence
and are not reinterpreted by an incompatible runtime. Forward-fix or matching-code recovery applies.

## References

- [ADR 0008](0008-durable-workflow-transition-state-machine.md)
- [Phase 2.6 plan](../planning/phase-2-6-plan.md)
- [P2.6.0 decisions](../tasks/phase-2-6-contract-and-scenario-foundation/decisions.md)
