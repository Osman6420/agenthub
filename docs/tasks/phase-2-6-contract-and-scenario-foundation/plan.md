# Task Plan: phase-2-6-contract-and-scenario-foundation

## Task summary

Establish the reviewed contracts, executable scenario corpus, ownership boundaries and integration
gates that open the parallel Phase 2.6 implementation waves. This is P2.6.0; it does not implement
the later runtime primitives.

## Background

Phase 2.6 deliberately revises the unreleased `agenthub/v1` workflow grammar in place. The planned
parallel, wait/resume, recovery, composition, Python-node and agent-loop work shares compiler and
runtime seams. Parallel implementation before those seams and their negative-path fixtures are
fixed would create incompatible state machines and unsafe merge-time decisions.

## Scope

- Inventory the current `agenthub/v1` schema, compiler, runtime transitions, persisted checkpoints,
  fixtures, demo seeds, authoring documentation and release compilation path.
- Define the canonical Phase 2.6 graph/state contract and a migration matrix from current dummy
  workflows; no dual v1/v2 contract is introduced.
- Propose ADRs for durable orchestration state transitions and child-run authority attenuation.
- Define representative enterprise scenario fixtures and happy, denial, timeout, cancellation,
  replay, partial-failure, cross-tenant and recovery trajectories.
- Allocate ownership for shared compiler/runtime seams and database migration numbering.
- Define branch/wave merge gates, compatibility checks and deterministic non-production
  reset/repopulation prerequisites.
- Produce target JSON Schema examples as non-importable fixtures until their owning primitives are
  implemented and verified.

## Non-goals

- Runtime implementation of P2.6.1 through P2.6.11.
- Resetting any database or deleting existing records.
- Accepting ADRs without owner/security/operations review.
- Publishing target fixtures as usable workflow artifacts.
- Changing production dependencies, authentication, authorization or live network behavior.

## Acceptance criteria

1. The current grammar, compiler/runtime persistence seams and all fixture/seed consumers are
   inventoried with repository links.
2. Proposed ADRs specify state-transition ownership, idempotency/recovery invariants and child-run
   authority without silently granting capabilities.
3. Every reference scenario has typed input/output intent and the required negative/recovery paths.
4. A contract migration matrix accounts for code, schemas, fixtures, docs, seeds, compiled releases
   and explicitly authorized local/test repopulation.
5. Parallel branch ownership, migration allocation and per-wave merge/verification gates are named.
6. Target fixtures cannot be mistaken for currently supported/importable artifacts.
7. Owner, application-security and operations review decisions are recorded before P2.6.1 or other
   contract-dependent runtime implementation starts.

## Affected components

- `apps/builder` workflow schema and diagnostics
- `apps/orchestration` authoring/compiler boundaries
- runtime workflow execution and persisted run/checkpoint models
- artifact/release compilation and manifest pinning
- scenario fixtures, demo seed data and authoring documentation
- Phase 2.6 task, ADR and verification records

## Interfaces affected

This task defines proposed interfaces but does not change a public or executable interface. Later
parts will revise the canonical `agenthub/v1` contract only after the P2.6.0 gates are accepted.

## Data impact

The inventory must identify persisted workflow drafts, artifacts, compiled releases, runs and demo
fixtures affected by the in-place grammar change. No data mutation is authorized in P2.6.0.

## Security impact

The foundation must preserve declarative DSL, immutable release pins, bounded resources,
deny-by-default transitions and untrusted model/tool/event outputs. Threat cases must be fixtures,
not prose-only requirements.

## Authorization impact

Child runs, resume actions, human decisions, tools and retrieval must re-authorize at their own
boundaries. Parent authorization and model proposals are never transferable authorization proof.

## Observability impact

Define stable transition and recovery event vocabulary, trace linkage requirements and separation
between application telemetry and security/business audit. Do not record secrets, Python source,
document content or hidden model reasoning.

## Migration impact

P2.6.0 creates a migration matrix and allocation scheme only. Any database reset is a separately
confirmed operation limited to an explicitly named local/development/test database.

## Dependencies

- Phase 2.5 Parts 6-7 product and artifact coherence
- Current workflow schema, compiler, runtime, artifact and release behavior
- Owner decisions already recorded in the Phase 2.6 plan

## Implementation steps

1. Inventory current contracts, persistence seams, fixtures/seeds and current-behavior documents.
2. Build the old-to-target contract migration matrix and identify all atomic cutover consumers.
3. Draft the durable state-machine and child-authority ADRs with explicit alternatives.
4. Create the enterprise scenario corpus and negative/recovery trajectory matrix.
5. Define executable fixture format and mark unsupported target fixtures non-importable.
6. Record shared-core ownership, migration ranges, branch naming and wave merge gates.
7. Review the complete foundation as architecture, application security and SRE; resolve or record
   every blocking decision.
8. Merge P2.6.0, rerun documentation/schema checks, then authorize the first parallel wave.

## Test plan

- Validate proposed JSON/JSON Schema fixtures syntactically.
- Prove target fixtures are excluded from normal import/seed discovery until supported.
- Map every scenario to happy, invalid, authn, authz, cross-tenant, replay, timeout, cancellation,
  partial-failure and recovery cases.
- Check the migration matrix against repository searches for workflow versions and fixture loaders.
- Run documentation link, encoding and diff checks.

## Rollout plan

P2.6.0 is merged as documentation, proposed ADRs and inert fixtures. The first parallel wave starts
from that merged baseline. No runtime feature flag or database rollout occurs in this task.

## Rollback plan

Revert the unaccepted planning/fixture changes. Proposed ADRs may be rejected or superseded through
the ADR process. There is no runtime/data rollback because P2.6.0 performs no activation or reset.

## Risks

- An incomplete inventory can leave stale dummy artifacts or mixed grammar at cutover.
- Parallel branches can redefine shared state transitions or collide on migrations.
- Fixtures can create false confidence if they omit denial, replay and crash recovery.
- A target example placed in a normal seed/import path could be treated as supported prematurely.
- Child authority can accidentally become ambient or transferable if attenuation is underspecified.

## Open questions

1. Exact restricted state-path and mapping grammar.
2. Deterministic join and state-merge semantics.
3. Durable wait correlation and authenticated event transport.
4. Shared runtime transition owner and per-lane migration number allocation.
5. Exact explicitly named local/test reset and repopulation command/procedure.

## Status

Completed. The execution-wave contract, current-contract inventory, Accepted ADR-0008/0009/0010,
target DSL contract, role-based ownership/migration allocation, inert target scenario corpus and
verification evidence are recorded. No runtime implementation, migration or reset was performed.

## Completion criteria

All P2.6.0 documentation and fixture criteria are verified. The first parallel wave must still start
from a dedicated committed/merged integration baseline; completion of this task does not authorize
public API/authentication changes, database reset, live egress or production activation.
