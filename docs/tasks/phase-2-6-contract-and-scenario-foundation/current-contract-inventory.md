# P2.6.0 Current Workflow Contract Inventory

This is the initial repository inventory for the unreleased workflow contract. It records current
authoritative touchpoints; it is not the target Phase 2.6 grammar and does not authorize runtime or
data changes.

## Authoring and mutable state

- `apps/builder/models.py`: tenant/project/scenario-scoped mutable `WorkflowDraft`, revision and
  author lineage.
- `apps/builder/services.py`: draft validation, canonical diagnostics, publish and audit seams;
  `MAX_DRAFT_BODY_BYTES` is the current authoring body bound.
- `apps/builder/api.py`: scoped author APIs, optimistic revision handling, AI candidate acceptance,
  diagnostics and publish endpoints.
- `apps/builder/node_schema.py`: Studio-visible node/config catalog derived from current compiler
  capabilities.
- `apps/console/views.py` and Scenario Studio templates/tests: scenario-scoped authoring and release
  presentation consumers.

## Source and compiled grammar

- `apps/workflows/compiler.py` is the canonical strict compiler. Source workflows require
  `api_version=agenthub/v1`, `kind=Workflow`, exact top-level keys, one input node, at least one
  reachable end node, an acyclic graph, at most 50 nodes and 100 edges.
- Current built-in node types are `input`, `retrieve`, `generate`, `condition`, `format_output`,
  `validate_contract`, `end`, `custom` and `tool`.
- Current edges support only optional boolean `when` values from a `condition` node; there is no
  parallel/join, generic wait, error edge or compensation grammar.
- The compiler emits `agenthub/compiled-workflow/v1`, deterministically sorts nodes/edges and
  checksums the compiled graph.
- `apps/workflows/services.py::compile_workflow_version` resolves allowed managed custom-node refs
  and persists an immutable `WorkflowVersion`.

## Runtime and persisted transitions

- `apps/workflows/models.py`: immutable `WorkflowVersion`; tenant/scenario/release/consumer-scoped
  `WorkflowRun`; append-style sequenced `WorkflowRunEvent`.
- Current run states are `requested`, `queued`, `running`, `waiting_approval`, `completed`, `failed`,
  `timed_out` and `cancelled`.
- `apps/workflows/services.py` owns run request/idempotency, cancellation, state-size enforcement,
  redaction and event sequencing.
- `apps/workflows/tasks.py` owns Celery claim/terminal transitions and invokes the runtime. It accepts
  redelivery from queued/requested/waiting-approval states and guards terminal states.
- `apps/workflows/runtime.py` executes one node path synchronously, persists tool-approval pause
  state through `awaiting_node`, enforces deadline/node/state bounds and validates final output.
- The present runtime keeps redacted mutable state on `WorkflowRun`; it has no independent branch,
  join, generic wait, compensation or parent/child run records.

## Managed custom nodes and tool/release seams

- `apps/workflows/models.py::CustomNodeDefinition` represents the existing immutable package-backed
  managed-node registration; this is distinct from the planned reviewed tenant-authored Python node.
- `apps/workflows/custom_nodes.py` and `apps/workflows/services.py` resolve/execute the current
  managed-node contract.
- Tool nodes use a release-pinned binding role and the governed tool approval/proxy path; workflow
  config does not carry endpoints or credentials.
- `apps/releases/compiler.py` requires a `workflow_definition` artifact in its reserved manifest role
  and compiles it through the shared workflow service. Promotion remains a separate release action.

## Persistence and migrations

- `apps/builder/migrations/0001_initial.py`: current mutable workflow draft storage.
- `apps/workflows/migrations/0001_initial.py`: current compiled workflow, run, event and managed-node
  storage baseline.
- Later parts are expected to add durable branch/join/wait/compensation/child-link records. Migration
  ranges and model ownership remain a P2.6.0 open decision; no migration is allocated by this
  inventory.
- `apps/tenancy/migrations/0002_force_tenant_rls.py` dynamically includes managed models with a
  required direct `organization` field, enables and forces PostgreSQL RLS, and depends on
  `workflows/0003`. Every new tenant-owned orchestration record must retain direct non-null lineage
  and receive PostgreSQL non-owner verification; relying only on a parent foreign key is insufficient.

## Runtime API, resume and observability consumers

- `apps/gateway/urls.py` exposes authenticated invoke/query/run status and cancellation. Numeric run
  IDs resolve workflow runs; scoped lookup requires both consumer and organization.
- `apps/gateway/views.py` issues a server-owned execution context, creates the workflow run and
  dispatches Celery only after commit. The current DB-commit-to-broker-publish window has no durable
  workflow dispatch record and is an explicit P2.6 transition/outbox design concern.
- `apps/workflows/signals.py` resumes only decided tool approvals, derives the run from the governed
  invocation idempotency key and dispatches after commit. Generic waits require typed correlations;
  they must not parse arbitrary client-owned identifiers this way.
- `apps/audit/services.py` appends immutable audit events but requires already-redacted caller input.
  The transition design must specify which operations fail closed if audit persistence fails.
- `apps/observability/signals.py` projects low-cardinality workflow run/node metrics. New states and
  primitives require explicit bounded label allowlists; tenant/run/node identifiers stay out of
  metric labels.

## Fixtures, seeds and documentation consumers

- `apps/workflows/tests/` covers compiler, runtime, tool and managed custom-node behavior.
- `apps/builder/tests/` supplies minimal source DSL fixtures and authoring/publish behavior.
- `apps/console/management/commands/seed_demo.py` creates current demo workflow drafts/artifacts and
  is an atomic cutover consumer for the in-place grammar change.
- `docs/architecture/artifacts-and-dsl-authoring-guide.md` and
  `docs/architecture/workflow-dsl-llm-guide.md` describe/generate current authoring guidance.
- `docs/manual-testing-guide.md`, `docs/user-guide.md` and Scenario Studio console tests contain
  current `agenthub/v1` authoring journeys.
- `apps/catalog/tests/test_control_plane_gitops.py` and artifact GitOps code share the broad
  `agenthub/v1` label. The Phase 2.6 workflow change must not accidentally reinterpret unrelated
  artifact/control-plane kinds that use the same API-version string.

## Initial cutover and ownership findings

1. `agenthub/v1` is shared across artifact kinds, so migration detection must use both API version
   and `kind=Workflow`, not the version string alone.
2. Source and compiled workflow identifiers are distinct; an atomic cutover must account for both
   `agenthub/v1` and `agenthub/compiled-workflow/v1` consumers.
3. Compiler, runtime, tasks and workflow models form the shared state-machine core. They require one
   integration owner during the P2.6.2/P2.6.3/P2.6.5/P2.6.8 parallel wave.
4. Builder/node-schema/Studio work can consume the accepted compiler contract but must not become an
   alternate validator.
5. Existing tool approval is the only durable pause precedent; generic human/event waits must reuse
   its invariants without overloading `awaiting_node` into an untyped catch-all.
6. Demo seed, builder/workflow tests, authoring guides and compiled releases must move together at
   the approved non-production reset/cutover boundary.

## Inventory still required

- Exact release/run records and seed/import discovery paths affected by a reset
- PostgreSQL non-owner runtime evidence for every current workflow table
- Audit persistence failure policy for each proposed transition/operator action
- Exact external event ingress contract; current public runtime has no generic event-resume endpoint
- Exact migration ranges and named owners for every Phase 2.6 lane
