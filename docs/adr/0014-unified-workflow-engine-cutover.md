# ADR-0014: Unified workflow engine and destructive cutover

## Status

Accepted on 2026-07-28 after the approved local/disposable destructive cutover.

## Context

AgentHub currently exposes one product concept through three execution implementations:

- RAG runs synchronously through orchestration.
- Workflow scenarios compile `workflow_definition` into `WorkflowVersion` and persist
  `WorkflowRun`/`WorkflowRunEvent`.
- Agent scenarios compile `agent_definition` into `AgentVersion` and persist
  `AgentRun`/`AgentRunEvent`.

`Scenario.type` selects gateway, release, evaluation and child-composition behavior. Responses and
Chat Completions already exist, but gateway dispatch remains type-based; `/v1/query` and
`/v1/invoke` are still active. Workflow supports governed retrieve/generate/tool/custom/transform,
durable waits, human tasks, timers, parallel/for-each/join, subworkflow and agent-call nodes. Agent
has a separate planner, checkpoint, approval and recovery loop. Keeping both state machines makes
authorization, cancellation, event ordering, usage, recovery and operator control diverge.

The local database contains old scenarios, artifacts, versions, runs and events, including one
currently running workflow. The owner confirmed that no material real workflow data exists and
explicitly declined compatibility or conversion for existing workflow/run records.

## Decision

Use `workflow_definition` as the only executable artifact and one compiled workflow/state machine
as the only runtime. RAG becomes a Document Answer preset (`input → retrieve → generate → end`).
Agent behavior becomes a closed-schema `agent_loop` node in the same graph. Presets are authoring
conveniences, never scenario types or alternate authority paths.

The compiler emits immutable `execution_mode_analysis` with `supported_execution_modes` and stable,
content-free blocker codes plus relevant node IDs. Background is always supported. Sync is supported
only when every reachable path is bounded and cannot durably pause. The runtime reloads the exact
compiled checksum/version and independently enforces the selected mode; client or DSL declarations
cannot widen eligibility.

One UUID `Run` and ordered `RunEvent` model owns both sync and background execution. Tenant, actor,
consumer, capabilities, release/artifact pins, retrieval grants, tool authority, secrets, budgets
and kill-switch state remain server-derived and are revalidated at admission and transitions.
Events are allocated under the locked Run row and are closed-schema, bounded and redacted.

`POST /v1/responses` is canonical. Chat Completions remains a synchronous compatibility adapter.
Run cancellation becomes idempotent `POST /v1/runs/{uuid}/cancel`. Responses IDs (`resp_...`) remain
distinct from Run UUIDs. `/v1/query`, `/v1/invoke`, DELETE cancellation, `Scenario.type`,
`agent_definition`, and the old Agent/Workflow run tables are removed in one fleet cutover; there is
no dual-write or mixed-runtime compatibility period.

Existing local workflow/agent data is discarded, not transformed. Gates 1–3 are additive and leave
old runtime structures available for code rollback. The final destructive gate requires:

1. proof that the target is the approved disposable/non-production environment;
2. exact row counts and confirmation that running/resumable work is drained;
3. a bounded search for configured `/v1/query` and `/v1/invoke` consumers;
4. stopped old workers and mixed-version startup denial;
5. review and explicit approval of the exact destructive migration/reset diff; and
6. a successful empty-database rebuild and rollback drill.

After destructive cutover, rollback is previous application code plus recreation of an empty
database, application of the previous migration set, and approved seed/configuration. It is not an
in-place schema downgrade and preserves neither old nor new runs.

## Why this option

A shared façade over two runtimes would retain the most dangerous duplication: authorization,
checkpoint, approval, cancellation, late-result and recovery semantics. Dual-write migration would
add reconciliation and split-brain failure modes without business value because existing data is
disposable. Converting agent policy into a governed node preserves its closed contracts while
letting the established workflow compiler, durable waits, child composition and recovery machinery
become the single extension point.

## Rejected alternatives

- **Keep three scenario types behind one UI:** hides rather than removes divergent authority and
  lifecycle paths.
- **Wrap AgentRun inside WorkflowRun:** leaves two checkpoints, event streams and terminal-state
  owners and makes cancellation/approval races ambiguous.
- **Dual-run or dual-write migration:** creates mixed-version and reconciliation hazards with no
  data-preservation requirement.
- **Convert old rows:** adds a one-off semantic mapping for disposable data and risks implying
  compatibility that the new contract intentionally does not provide.
- **Automatic sync-to-background takeover:** changes requested execution semantics and can replay
  ambiguous side effects after disconnect.

## Consequences

The cutover is intentionally breaking and operationally concentrated. Compiler and runtime changes
must preserve RAG ACL/grounding/citation behavior and agent action/tool/budget/approval defenses.
One engine becomes a larger security boundary, so exact checksum/version validation, FORCE RLS,
terminal guards, bounded events and parity tests are mandatory.

Before the destructive gate, rollback is ordinary code rollback because old tables and paths remain.
After it, rollback costs an empty rebuild and loses run history by design. Any production target,
undrained work, configured old consumer, failed rollback drill or unapproved migration diff stops
the cutover.

## Implementation outcome

The decision is implemented by migrations through `workflows.0017`: one direct-tenant UUID `Run`,
ordered `RunEvent`, Run-native waits, parallel regions, child links and compensation entries. The
canonical executor supports sync/background execution, bounded retry, durable compensation and
explicit operator recovery. Child workflows run as separately authorized, capability-attenuated
Runs. RAG and agent behavior are workflow presets; agent policy is a closed `agent_loop` node.

The local Compose target was confirmed non-production, old workers were stopped, the migrations
were applied, and the owner-authorized demo consumer/user/scenario/runtime rows were removed.
Canonical demo data was reseeded and `/v1/responses` completed an end-to-end smoke call. The old
runtime tables and routes are absent. A previous-code plus empty-database migration/seed rollback
drill passed before cutover; in-place downgrade remains intentionally unsupported.

## References

- [Phase 2.8 Part 3 plan](../planning/archive/phase-2-8-part-3-unified-workflow-engine-2026-07-28/plan.md)
- [Phase 2.8 Part 3 threat model](../planning/archive/phase-2-8-part-3-unified-workflow-engine-2026-07-28/threat-model.md)
- [ADR-0008: durable workflow transition state machine](0008-durable-workflow-transition-state-machine.md)
- [ADR-0009: child-run capability attenuation](0009-child-run-capability-attenuation.md)
- [ADR-0010: workflow dataflow, join, wait and human-task contract](0010-workflow-dataflow-join-wait-and-human-task-contract.md)
