# P2.6.0 Migration, Ownership and Merge Matrix

This matrix allocates seams, not final migration numbers. Exact numbers are assigned after current
branch migrations are merged and immediately before each lane begins; branches must not guess or
reuse sibling migration numbers.

| Lane | Owns | May consume | Must not redefine | Merge prerequisite |
| --- | --- | --- | --- | --- |
| P2.6.0 integration | source/compiled grammar contract, transition command interface, migration allocation, contract corpus | current compiler/runtime/release behavior | feature implementation | ADR and corpus review |
| P2.6.1 mapping | typed paths, mapping schemas, protected-key policy, transform integration | transition interface | run statuses, wait/branch/child records | P2.6.0 merged |
| P2.6.2 parallel | branch attempts/results, join ownership, collection bounds | mapping and transition interfaces | wait, child authority, generic retry classification | P2.6.1 merged |
| P2.6.3 waits | typed wait/task/correlation records and resume commands | mapping and transition interfaces | tool approval internals, branch merge policy | P2.6.1 merged plus ingress decision |
| P2.6.4 recovery | failure classes, retry scheduling, compensation records/operator recovery | branch/wait/child outcomes | primitive-specific execution | P2.6.2 and P2.6.3 merged; P2.6.5 contract stable |
| P2.6.5 composition | parent/child links, pinned child resolution, effective capability envelope | mapping, transition and release manifest | parent authorization or tenant lineage | P2.6.1 merged; ADR 0009 accepted |
| P2.6.6 agent loop | decision/observation schema, convergence/budget guards | recovery and composition | tool proxy authority, approvals | P2.6.4 and P2.6.5 verified |
| P2.6.7 MCP sync | catalog source/candidate/drift records | governed tool registry/egress | active bindings, grants or releases | P2.6.0 merged; network/security gate |
| P2.6.8 Python node | draft/revision/review records and isolated runner adapter | mapping, catalog metadata, transition result contract | managed-node compatibility, application-process execution | spike ADR; runtime waits for P2.6.1 |
| P2.6.9 Studio AI | bounded authoring context and transient candidate UI/server validation | compiler diagnostics, safe catalogs, identifier service | authorization, automatic persistence/activation | P2.6.0 merged; Python metadata contract before integration |
| P2.6.10 ingestion | build job/outbox/heartbeat records and reconciliation | shared tenancy/audit/operations conventions | workflow grammar/state machine | P2.6.0 merged |
| P2.6.11 closure | cross-part Studio/eval/trace/operations acceptance | every merged lane | primitive semantics | continuous integration; final gate last |

## Branch and merge protocol

- Baseline/integration branch name is selected by the repository owner before the first parallel
  wave. Suggested naming is `integration/phase-2-6`; this document does not create or publish it.
- Feature branches use `phase-2-6/<part>-<short-scope>` and start from the merged integration head.
- Each branch contains its own task plan, threat model, migration, tests and verification evidence.
- A branch never depends on an unmerged sibling. Shared-contract changes return to the integration
  owner instead of being independently redefined in multiple branches.
- At wave close, merge one branch at a time. After every merge run migration graph/drift checks and
  shared compiler/transition contract tests. Run the full wave suite before opening the next wave.
- Conflicting migration numbers are resolved by rebasing/renumbering the unmerged feature migration;
  never edit an already deployed/merged migration to hide a conflict.

## Atomic in-place grammar cutover consumers

| Consumer | Current authority | Required cutover evidence |
| --- | --- | --- |
| Workflow source validation | `apps/workflows/compiler.py` | new canonical fixtures accepted; stale grammar rejected |
| Compiled graph | compiler plus `WorkflowVersion.compiler_version` | incompatible checkpoint/version rejection |
| Mutable drafts/diagnostics | `apps/builder` | round-trip and optimistic concurrency tests |
| Publish/release compile | builder/artifact and `apps/releases/compiler.py` | exact checksum/pin and no bypass tests |
| Runtime/tasks | `apps/workflows/runtime.py`, `tasks.py`, transition service | redelivery/crash/terminal-state tests |
| Node catalog/Studio | builder schema and console | compiler-derived config/diagnostics parity |
| Demo/test data | `seed_demo.py`, workflow/builder/console fixtures | deterministic repopulation from new grammar |
| Documentation | architecture/LLM/manual/user guides | examples compile against merged contract |

## Database safety gate

Before any reset, record the resolved database host/name/user, environment classification, backup or
repopulation source and explicit owner confirmation. Only an explicitly named local/development/test
database may proceed. Unknown, shared, production-like or mismatched targets fail closed. Reset is
never a migration side effect and is not authorized by this matrix.
