# Task Plan: sprint-8-workflow-core

## Task summary

Add a compiled, immutable workflow DSL and bounded runtime for governed AI DAGs,
including approved custom-node versions and evaluation-gate integration.

## Background

The existing runtime executes pinned RAG releases. Sprint 8 generalizes execution to
versioned workflows without executing authored YAML or arbitrary code directly.
Planning does not require Sprint 7 completion; implementation depends on the verified
release/runtime contracts from Sprint 6 and operational async/trace seams from Sprint
7.

## Scope

- Workflow artifact schema, `WorkflowVersion`, node registry, deterministic compiler,
  checksums, and release pins.
- Input, retrieve, generate, condition, formatter, validator, and end nodes.
- A transport-independent runtime facade, durable async run/status records,
  idempotency, cancellation, deadlines, and bounded state.
- `CustomNodeDefinition` manifest validation, organization/scenario allowlists,
  immutable versions, package availability checks, and restricted execution context.
- Workflow assertions and Sprint 6 evaluation/promotion gate integration.

## Non-goals

Arbitrary Python, expressions with general code execution, user-supplied endpoints or
packages, tool calls/approval (Sprint 9), stateful agent loops (Sprint 10), visual
authoring (Sprint 11), or long-term memory.

## Acceptance criteria

- Invalid, cyclic, unreachable, unbounded, contract-incompatible, or unknown-node
  graphs do not compile.
- Runtime executes only an immutable compiled graph pinned by the release.
- Every terminal output passes scenario output-contract and policy validation.
- Custom nodes are pre-installed approved versions, allowed for the scenario, schema
  checked before/after execution, and receive no raw secrets/request/DB access.
- Async duplicate requests do not create duplicate runs; terminal and cancellation
  behavior is deterministic and tenant-scoped.
- Workflow eval failures block release promotion through the existing gate.

## Affected components

New workflow/orchestration models and services; artifacts, releases, gateway, runtime,
evaluations, console/status views, Celery, migrations, audit, observability, and docs.

## Interfaces affected

New Workflow/CustomNode artifact contracts, compiler diagnostics, runtime facade, and
async workflow run/status behavior. Existing invoke/query contracts remain compatible;
unsupported workload/capability combinations return stable safe errors.

## Data impact

Add immutable workflow/custom-node versions and durable run/node-event records.
Persist bounded redacted state/checksums, not raw prompts, secrets, or unrestricted
model/retrieval content. Define retention and purge linkage before rollout.

## Security impact

The DSL/compiler is a code-like input boundary. It must prevent expression, template,
package, endpoint, deserialization, and resource-exhaustion attacks. Custom code is
platform-built and reviewed, never uploaded or selected by raw entrypoint.

## Authorization impact

Artifact authoring, compilation, release pinning, invocation, run status/cancel, and
custom-node selection are server-side tenant/action scoped. Editors may select only
active versions explicitly allowed for their organization/scenario.

## Observability impact

Emit redacted per-run/node events, durations, retries, terminal reason, and trace links
with bounded node-type dimensions. Audit compile/publish and security-sensitive run
decisions; do not treat verbose traces as audit.

## Migration impact

Additive tables, enums, indexes, and constraints. Stage writes/reads compatibly and
test representative forward migration. Removal or state reshaping is out of scope.

## Dependencies

Verified Sprints 6–7 release gates, runtime facade, async worker/trace conventions,
and approved custom-node packaging/scan process. A workflow engine dependency or new
package requires explicit approval; a minimal in-repo DAG executor is preferred until
requirements justify otherwise.

## Implementation steps

1. Define workflow/custom-node schemas, models, constraints, and migrations.
2. Build the allowlisted node registry and deterministic compiler/diagnostics.
3. Implement bounded core nodes and contract-validated state transitions.
4. Add durable async execution, idempotency, cancellation, retries, and status.
5. Add restricted custom-node resolution/execution and package-image checks.
6. Add workflow eval assertions and release compiler/promotion integration.
7. Add authorization, isolation, migration, concurrency, load, and end-to-end tests;
   update current-state and operational documentation after verification.

## Test plan

- Compiler graph/schema/reference/checksum determinism and adversarial size/depth tests.
- Node unit tests for valid, invalid, timeout, retry, and contract/policy failures.
- Cross-tenant artifact/version/run/status/cancel/custom-node denial.
- Idempotent concurrent start, worker redelivery, cancellation races, and terminal-state
  invariants on PostgreSQL.
- Custom-node missing/inactive/unallowed/package-mismatch and input/output schema denial.
- Candidate workflow eval, promotion, gateway execution, and rollback end-to-end.
- Migration forward/compatibility checks and bounded-state/load tests.

## Rollout plan

Apply additive migrations, deploy compiler/read paths, register only built-in nodes,
then enable async execution for allowlisted scenarios. Introduce custom nodes one
reviewed version at a time after package and image verification.

## Rollback plan

Disable new workflow compilation/invocation while retaining run/version records and
existing RAG paths. Drain or safely terminate queued work pinned to the deployed image.
Keep additive schema until a separately approved cleanup.

## Risks

- DSL features can become an accidental programming language or injection surface.
- Worker retries/cancellation can duplicate model calls or inconsistent state.
- Custom nodes share process privileges unless stronger isolation is adopted.
- Unbounded graphs/state/events can exhaust database, workers, or telemetry.

## Open questions

- Custom-node ownership, signing/provenance, scan gates, and deployment compatibility
  policy.
- Run/checkpoint retention and cancellation semantics for in-flight provider calls.

## Approved decisions

- Conditions use a type-safe, allowlisted expression subset supporting field access,
  comparisons such as `==` and `>=`, and boolean `and`/`or`. Python, Jinja, arbitrary
  function calls, and general code execution are prohibited.
- The initial workflow runtime is fully asynchronous through Celery. Invocation returns
  a `run_id`; a separate synchronous execution threshold is not introduced.
- Custom nodes must be reviewed, tested, and pre-installed in the platform image.
  Tenant users cannot upload packages or supply Python entrypoints.
- Initial hard limits are 50 nodes, 100 edges, 1 MiB of workflow state, 30 seconds per
  node, and 5 minutes per workflow run. Lower tenant/scenario policy limits may apply;
  raising the hard limits requires review and load evidence.
- These decisions were approved by the project owner on 2026-07-10.

## Status

Verified on SQLite and PostgreSQL as of 2026-07-11. Delivered scope includes strict
workflow/custom-node artifacts, deterministic immutable compilation, the bounded
built-in DAG runtime, pre-installed schema-checked custom nodes, fully asynchronous
Celery execution, durable redacted runs/events, idempotent start/redelivery,
tenant-scoped status/cancel, output contract and policy enforcement, release pins, and
workflow eval assertions using the Sprint 6 promotion gate. No workflow-engine
production dependency was added. Public gateway behavior changes were implemented with
the project owner's approved async and authorization model.

## Completion criteria

Definition of Done evidence covers compiler determinism, contracts/policy,
authorization/tenant denial, custom-node restrictions, async concurrency/idempotency,
migrations, evaluation/promotion, rollback, operability, and residual-risk review.
