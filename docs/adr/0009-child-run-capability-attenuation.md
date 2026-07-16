# ADR 0009: Child-Run Capability Attenuation

- **Status:** Accepted
- **Date:** 2026-07-16

## Context

Phase 2.6 introduces pinned sub-workflow and agent-call composition. A parent run may have access to
tools, retrieval roles and data that a child must not inherit automatically. Treating parent
authorization as delegated authority would create a confused-deputy path and allow nesting to
amplify capabilities, budgets or tenant access.

## Decision drivers

- Deny-by-default object/action/tenant authorization
- Immutable release pinning and reproducible evaluation
- Capability attenuation across every nesting boundary
- Bounded recursion, child count and cumulative cost/state
- Auditable parent/child lineage without sharing ambient mutable authority

## Considered options

1. Child inherits the parent execution context and all capabilities.
2. Parent delegates an arbitrary capability list declared in workflow state.
3. Compiler pins an allowed child role and maximum capability envelope; runtime intersects it with
   the caller's live authorized capabilities and the child's own policy.
4. Defer all composition to the Phase 3 multi-agent supervisor.

## Decision

Choose option 3 for Phase 2.6 sub-workflow and single-agent calls.

- A parent release manifest pins the exact child workflow/agent artifact role, revision/checksum and
  permitted input/output mapping. Runtime never resolves a child by model text, endpoint or latest
  mutable version.
- The effective child capability set is the intersection of: parent run effective capabilities,
  the compiled call-site maximum envelope, child release/policy allowlists and current server-side
  tenant/consumer authorization. No source may add a capability absent from another required set.
- The parent proposal and persisted state are requests, not authorization proof. The child boundary
  re-authenticates the caller/service identity and re-authorizes organization, scenario, release,
  consumer, tool, retrieval and action access.
- Organization/project/scenario lineage is server-resolved. Cross-organization child calls are
  denied in Phase 2.6. Client/model-supplied lineage is ignored.
- Child execution receives a newly issued bounded execution context referencing the parent/child
  lineage and effective capability checksum. It receives only schema-mapped input, never the full
  parent state or hidden authorization context.
- Parent and child have separate durable runs, status, deadlines and audit trails connected by an
  immutable tenant-scoped link. Child output is untrusted and schema-validated before mapping into
  parent state.
- Compiler and runtime enforce maximum nesting depth, child count, cumulative calls/tokens/state,
  deadline and cancellation policy. Cycle checks cover immutable call graphs where statically
  knowable; runtime guards remain mandatory.
- Cancellation propagates as a bounded idempotent request. A late child result cannot resurrect or
  mutate a terminal parent.
- Child failure, timeout and `outcome_unknown` map only through compiled error/recovery contracts.
  The model cannot invent a recovery child or widen the envelope during replanning.
- Phase 2.6 composition is not an authority-delegating multi-agent supervisor. Multi-agent
  delegation remains Phase 3.

## Security consequences

Capability amplification, confused deputy, cross-tenant invocation and state over-disclosure are
explicit denial cases. Effective capability and lineage checksums may be logged/audited; raw tokens,
credentials, retrieved content and hidden policy data may not.

## Operational consequences

Parent/child traces require linkage and separate budgets. Operators need safe visibility into which
boundary denied or exhausted a call without seeing confidential payloads.

## Data and privacy consequences

Parent/child link records require direct organization lineage and retention. Child receives the
minimum schema-mapped input; output is size/schema/redaction checked before persistence or parent
mapping.

## Positive consequences

- Composition cannot silently expand authority
- Releases remain reproducible and evaluation can exercise exact child revisions
- Parent and child failure/recovery remain independently observable

## Negative consequences

- Additional compile-time dependency resolution and runtime authorization checks
- Some desired compositions will be rejected until explicit roles/grants are configured
- Cumulative budget accounting adds transaction and observability complexity

## Migration impact

A later P2.6.5 migration adds tenant-scoped parent/child links and any required effective-capability
checksum/budget fields. Existing releases are not retroactively granted composition roles.

## Rollback considerations

Disable new composition calls with a capability gate. Preserve parent/child evidence. Old runtimes
must not resume checkpoints carrying an incompatible child-authority contract version.

## References

- [Phase 2.6 plan](../planning/phase-2-6-plan.md)
- [P2.6.0 plan](../tasks/phase-2-6-contract-and-scenario-foundation/plan.md)
- [ADR 0008](0008-durable-workflow-transition-state-machine.md)
- [ADR 0004](0004-tenant-isolation-postgres-rls-connection-context.md)
