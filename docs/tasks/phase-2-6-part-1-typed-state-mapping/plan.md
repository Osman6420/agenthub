# Task Plan: phase-2-6-part-1-typed-state-mapping

## Task summary

Implement P2.6.1: restricted typed workflow state paths, explicit input/output mappings and the
governed workflow `transform` node. This increment establishes the shared dataflow seam required by
parallel execution, durable waits, child composition and the advanced agent loop without adding an
expression language or allowing workflow data to alter server-owned authority.

## Background

The current workflow runtime passes a shared bounded state through a single-path DAG. Tool,
retrieval, generation and managed custom nodes have type-specific state behavior, but authors cannot
declaratively select prior outputs and map them into a later node contract. ADR-0010 accepted a
restricted absolute JSON Pointer subset and explicit `{from, to}` mappings. P2.6.1 turns that
contract into the canonical `agenthub/v1` authoring, compilation and runtime behavior.

This is the first runtime increment after P2.6.0. It owns path parsing, mapping validation,
protected-namespace policy and transform integration. It does not own branch state, wait records,
failure routing or child-run authority.

## Scope

- Define one shared restricted JSON Pointer parser/canonicalizer for authoring, compilation and
  runtime use.
- Add exact-schema `input_mapping` and `output_mapping` contracts to eligible workflow nodes.
- Define the safe business-state namespace and a deny-by-default protected namespace registry for
  tenant, actor, authorization, capability, release, execution, secret, budget and audit state.
- Resolve mappings from immutable pre-node state into a node-local input envelope; prevent a node
  from receiving ambient state it did not declare when a mapping is present.
- Validate node output against its declared/pinned output schema before mapping it into workflow
  state.
- Reject missing paths, incompatible known schemas, duplicate/conflicting destinations, unsafe
  array behavior, oversized expansion and protected writes with stable diagnostics.
- Reuse the existing closed `agenthub/transform/v1` operation registry through a workflow
  `transform` node. Decide and document whether its initial contract permits only a pinned
  `transform_profile` or also an exact bounded inline operation list before implementation.
- Preserve immutable artifact/release checksum behavior and bump the compiled workflow contract so
  incompatible checkpoints cannot be resumed under the new semantics.
- Update compiler-derived node-schema/Studio diagnostics, fixtures, demo data and authoring/current-
  behavior documentation at the atomic `agenthub/v1` cutover.
- Add unit, integration, property/boundary, authorization, redaction and runtime redelivery tests.

## Non-goals

- Parallel, join or `for_each` execution (P2.6.2).
- Human, timer or external-event waits (P2.6.3).
- Generic outcome routing, retries or compensation (P2.6.4).
- Sub-workflow or agent-call execution (P2.6.5).
- A general expression, query, template, scripting or Python language.
- Model-selected paths, transforms, schemas or authority fields.
- Runtime resolution of tenant-authored Python nodes.
- A dual workflow v1/v2 compiler or compatibility mode for disposable legacy dummy data.
- Any database reset; the separately confirmed non-production reset procedure remains outside this
  task.

## Acceptance criteria

1. Path parsing accepts only canonical restricted absolute JSON Pointers and rejects root/empty,
   fragment, wildcard, recursive, filter, append, negative-index, malformed escape and non-canonical
   forms with `WORKFLOW_PATH_INVALID`.
2. Compiler and runtime share the same path and protected-namespace policy; no client, model, tool,
   transform or node output can write or alias a protected namespace.
3. Eligible nodes accept only bounded exact mapping entries. Unknown keys, duplicate destinations,
   parent/child destination overlap and deterministic merge conflicts fail closed.
4. Known source and destination schemas are checked at author/compile time; all mapped node input,
   node output and resulting workflow state are checked again at runtime.
5. Missing paths, type mismatch, invalid array access, oversized values/state and protected writes
   terminate safely with stable content-free diagnostics and do not partially mutate run state.
6. Tool, retrieve, generate and managed custom-node paths can consume selected workflow fields and
   expose only schema-validated mapped output while preserving existing authorization, approval,
   retrieval ACL and tool-proxy boundaries.
7. The workflow `transform` node executes only the pinned/allowlisted governed transform contract;
   arbitrary expressions, templates, dynamic operation names and unpinned profiles are rejected.
8. Mapping evaluation is deterministic and side-effect free: retries/redelivery produce the same
   result and terminal runs cannot be resurrected.
9. Artifact validation, draft diagnostics, publish/release compilation and runtime use the same
   canonical contract and stable JSON Pointer diagnostic locations.
10. New grammar fixtures and examples compile; stale disposable grammar is rejected or replaced at
    the approved atomic cutover. No reset occurs without separate confirmation.
11. Audit/telemetry records contain safe identifiers, counts, sizes, stable codes and trace IDs only;
    mapped confidential values, secrets and raw schema/provider errors are not logged.
12. Required SQLite and PostgreSQL checks, migration drift checks and final architecture,
    application-security and SRE reviews have recorded evidence.

## Affected components

- `apps/workflows/compiler.py`: canonical node/mapping validation and compiled representation
- `apps/workflows/runtime.py`, `services.py`, `tasks.py`: node-local input, output mapping and
  idempotent state transition
- `apps/artifacts/governed_dsl.py`: reuse of the closed transform operation registry/profile
- `apps/releases`: exact transform-profile pin resolution if the selected contract requires it
- `apps/builder/node_schema.py` and diagnostics/publish services: compiler-derived authoring contract
- workflow, builder, release, console and evaluation tests/fixtures
- demo seed/GitOps examples and workflow authoring/current-behavior documentation

## Interfaces affected

The unreleased canonical `agenthub/v1` workflow node shape gains optional bounded `input_mapping`
and `output_mapping`; the node catalog gains `transform`. Compiled workflow/checkpoint contract
versions change atomically. Consumer invoke/status APIs and existing authorization contracts do not
gain new authority or endpoints.

Stable diagnostic codes include `WORKFLOW_PATH_INVALID`, `WORKFLOW_PATH_PROTECTED`,
`WORKFLOW_MAPPING_TYPE_MISMATCH`, `WORKFLOW_MAPPING_CONFLICT` and
`WORKFLOW_BUDGET_EXCEEDED`.

## Data impact

Mappings may move confidential tenant workflow data between approved business-state locations.
Runtime must avoid unnecessary copies, enforce per-value and total-state byte/depth/item limits and
persist only the canonical bounded state already authorized for the run. The compiled graph stores
canonical paths and transform references, never secrets, credentials or runtime authority.

No new durable model is expected. If implementation discovery requires schema changes, update this
plan and obtain the applicable migration/authorization review before adding them.

## Security impact

This task creates a mass-assignment and data-exfiltration boundary. Paths, transforms and output are
untrusted data. Validation must be allowlist-based, deterministic and free of evaluation. Protected
namespace denial applies after canonical decoding and normalization so escape/case/alias tricks
cannot bypass it. Mapping must not broaden tool field allowlists, retrieval ACLs, secret resolution
or output redaction.

See [threat-model.md](threat-model.md).

## Authorization impact

Mappings carry data only; they never carry or create permission. Server-owned organization, actor,
consumer, scenario, release, capability, approval and execution context remains outside writable
workflow state. Every node continues to authorize through its existing boundary using server-owned
context, and mapped identifiers are re-resolved tenant-scoped rather than trusted as ownership.

No authentication/authorization contract change is authorized by this plan. Any discovered need to
change one requires owner approval and a plan update before implementation.

## Observability impact

Emit stable bounded events for mapping validation/execution outcome with run/node/trace references,
entry count and byte totals. Do not place paths containing sensitive field names, mapped values,
schema bodies, provider output, secrets or tenant/run identifiers in metric labels. Required
security/business audit remains fail closed where a mapped transition is itself auditable; optional
logs/metrics/traces fail open and cannot affect authorization or transition outcome.

## Migration impact

Expected database impact is none. The compiled workflow/checkpoint version and disposable fixture
cutover are compatibility changes, not database migrations. Before implementation starts, the
integration owner assigns any unexpectedly required migration number from the P2.6.0 merge matrix.
Dummy local/test data reset or repopulation is a separate explicit operation and is not authorized
by this task plan.

## Dependencies

- P2.6.0 merged foundation and accepted ADR-0008/ADR-0010 contracts
- Existing `agenthub/transform/v1` validation/execution contract
- Current workflow compiler/runtime, builder diagnostics and immutable release compilation
- Integration owner confirmation of the compiled contract version and cutover branch
- Owner decision on pinned-profile-only versus bounded inline operations for the initial transform
  node

## Implementation steps

1. Revalidate the P2.6.0 inventory against live compiler/runtime/builder/release code and record the
   exact affected symbols, fixtures and current state-size/schema limits.
2. Close the transform-node contract decision and document the selected profile/reference,
   pinning, checksum and operation-budget semantics; use an ADR if the choice changes a durable
   architecture boundary.
3. Specify canonical path syntax, decoded segment handling, protected roots/aliases, mapping entry
   limits, conflict rules and stable diagnostics as executable contract tests.
4. Implement the shared pure path/mapping module and property/boundary tests before integrating it
   with the compiler or runtime.
5. Extend author validation and compilation to canonicalize mappings, infer/check schemas where
   possible, pin transform dependencies and reject ambiguous/unsafe graphs.
6. Implement node-local input construction, output validation and atomic output-to-state mapping in
   the runtime transition boundary; keep server-owned context separate.
7. Adapt tool, retrieve, generate and managed custom nodes without bypassing their existing
   authorization, proxy, ACL, schema, approval or redaction seams.
8. Add the governed transform executor adapter and prove it cannot select operations/profiles outside
   the compiled release.
9. Update builder node schema, diagnostics, fixtures, demo/GitOps data and authoring/current-behavior
   docs; keep UI logic non-authoritative.
10. Perform the approved atomic disposable-fixture cutover only after compiler/runtime/authoring
    contract tests pass. Do not perform a database reset in this step.
11. Run repository gates and PostgreSQL tenant/runtime coverage; record evidence in
    `verification.md`.
12. Review the final diff as staff engineer, application-security engineer and SRE, resolving
    layering, compatibility, denial-path, redelivery, observability and rollback findings before
    marking implemented or verified.

## Test plan

- Parser table/property tests for valid escapes and every forbidden pointer feature, including
  canonical-equivalent bypass attempts, Unicode/confusable names and depth/length limits.
- Compiler tests for unknown mapping keys, duplicates, overlapping destinations, missing paths,
  schema mismatch, array bounds, protected roots/descendants/aliases and mapping/state budgets.
- Runtime tests for atomicity on failure, deterministic copy/transform behavior, redelivery,
  cancellation, stale task, terminal guard and incompatible checkpoint/compiler version.
- Node integration tests for retrieve/generate/tool/custom happy paths plus invalid input, authn,
  authz denial, cross-tenant identifiers, tool approval and output-contract failure.
- Transform tests for exact pinned profile/checksum, inactive/foreign/missing reference, unknown
  operation, bounded expansion, injection strings and deterministic output.
- Builder/release tests proving diagnostics/publish/compile parity, immutable checksum changes and no
  client-side validation bypass.
- Audit/log/trace tests proving stable reason codes and redaction; metric tests proving bounded label
  sets.
- Target fixture and demo/GitOps compilation tests plus stale grammar rejection/exclusion tests.
- Repository gates: formatter, lint, type check, Django checks, migration drift, focused suites,
  full SQLite suite and applicable PostgreSQL non-owner/RLS/runtime suite.

## Rollout plan

- Land behind a disabled-by-default mapping/transform capability gate while the Phase 2.6 wave is
  incomplete.
- Merge from the accepted P2.6.0 baseline into the designated integration branch; this part owns the
  shared mapping seam consumed by later lanes.
- Stop compatible runtime workers for the atomic compiled-contract/fixture cutover, verify no stale
  in-flight dummy checkpoints are interpreted, repopulate only if a separately approved local/test
  procedure is invoked, and restart matching workers.
- Enable first for deterministic reference scenarios and selected non-production organizations;
  observe validation failures, state-size pressure and runtime transition health before wider use.
- Do not open P2.6.2/P2.6.3/P2.6.5 runtime integration until the P2.6.1 contract and verification
  gate are merged.

## Rollback plan

- Disable new mapping/transform starts through the capability gate and stop matching workers.
- Roll back code and use only fixtures/releases compiled by the matching compiler contract.
- Do not reinterpret new checkpoints under old code or silently drop mappings.
- Preserve run/audit evidence; use forward-fix for any durable state already written.
- Any local/test repopulation rollback requires the same explicit database identity and owner
  confirmation as rollout.

## Risks

- Canonicalization differences between compiler and runtime can create validation bypasses.
- Mapping can become mass assignment, cross-tenant reference smuggling or confidential-data
  exfiltration if server-owned and node-visible state are not separated.
- Copying nested values can amplify memory, database state and broker payload size.
- Schema inference can be incomplete; treating unknown compatibility as safe could defer dangerous
  failures until after a side effect.
- Output mapping after an ambiguous external side effect can leave state and provider outcome
  divergent; P2.6.1 must not introduce retries or compensation to hide this.
- A transform adapter that resolves `latest` or trusts client operation names would break immutable
  release pinning.
- Atomic in-place `agenthub/v1` cutover can strand stale dummy checkpoints if worker/compiler
  versions are mixed.

## Open questions

1. Is the initial workflow `transform` node pinned-profile-only, or may it carry an exact bounded
   inline operation list? Owner/architecture approval is required before implementation.
2. What are the exact pointer length/segment/depth, mapping-entry, per-value expansion and total
   workflow-state byte limits? They must be fixed as constants and tests, not configuration-free
   behavior.
3. Which existing node types require explicit mappings at cutover versus retaining a compatibility
   default when mappings are absent? The answer must not expose ambient state to tools/custom nodes.
4. What compiled workflow/checkpoint contract version identifies the new semantics and what exact
   stale-run behavior is operator-visible?
5. Can schema compatibility be proven for every pinned custom/tool profile at compile time, or which
   unknown cases must be rejected versus runtime-validated before side effects?

## Status

Planned. P2.6.0 and ADR-0010 define the target grammar, but P2.6.0 merge/verification, the transform
contract choice, exact budgets and compiled-contract cutover identifier must close before
implementation begins.

## Completion criteria

This task reaches `Implemented` only when the smallest complete compiler, runtime, builder/release,
fixture and documentation change is present with tests. It reaches `Verified` only when all
acceptance criteria and applicable Definition of Done gates have recorded SQLite/PostgreSQL
evidence, security/SRE review is complete and no stale grammar is accepted. It reaches `Completed`
only after current-behavior documentation and the Phase 2.6/master plan link the verification
record and the integration owner opens dependent lanes.
