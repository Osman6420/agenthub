# Verification: Phase 2.8 Part 3 — Unified workflow engine

> **Status: Not yet verified.** Evidence is recorded independently for every delivery gate. This
> record does not authorize the destructive migration.

| Gate/check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Dependency/data/API inventory | To be recorded | Not run | — | Refresh source/test counts; zero-state/consumer proof later repeated |
| ADR and contract review | To be recorded | Not run | — | DSL, mode reasons, IDs, disconnect, cancel, rollback |
| RAG/Agent preset semantics | To be recorded | Not run | — | Security/output semantics, not byte-identical model text |
| Execution-mode analysis | To be recorded | Not run | — | Reasons and bounded sync tool/agent cases |
| Unified Run/state machine | To be recorded | Not run | — | Shared request/worker transitions |
| RunEvent ordering/schema | To be recorded | Not run | — | Concurrent writers, DB sequence, 16 KiB/redaction |
| Disconnect/cancellation races | To be recorded | Not run | — | Lease, no takeover, completion/late results |
| Responses/Chat/run APIs | To be recorded | Not run | — | `resp_...` vs UUID, header, POST cancel |
| Gateway/MCP/evaluation/console/metrics | To be recorded | Not run | — | All consumers on unified engine |
| PostgreSQL non-owner/RLS | To be recorded | Not run | — | Run/event/child/approval/retrieval/tool |
| Worker restart/idempotency/load | To be recorded | Not run | — | Duplicate, stale, recovery and soak |
| Pre-delete zero-state/consumer proof | To be recorded immediately before cutover | Not run | — | Any protected row/consumer blocks deletion |
| Destructive migration approval/apply | Separate manual approval required | Not run | — | Exact migration diff only |
| Previous-code + empty-DB rollback drill | To be recorded before apply | Not run | — | Recreate, migrate, seed/configure, health/smoke |
| Static removed-reference scan | To be recorded | Not run | — | Routes, types, artifacts, models, fixtures/docs |
| Full repository quality/security checks | To be recorded | Not run | — | Ruff, mypy, Django, migrations, tests, secrets |

## Acceptance criteria mapping

Record evidence for type-free scenarios; one executable artifact/compiler/runtime; RAG and Agent Loop
semantic parity; compiler reason codes; bounded sync tool/agent eligibility; runtime revalidation;
per-call persistence; database event ordering; disconnect/no-takeover; idempotent POST cancellation;
terminal late-result guards; identifier separation; cross-tenant denial; and absence of old references.

## Sync/background comparison

Compare the same deterministic fixture through both modes for transition/state graph, authorization
decisions, event type/order/schema, usage/audit, output-contract and terminal semantics. Do not require
byte-identical generated output from nondeterministic providers. Record any provider seed/stub used.

## Disconnect, cancellation and concurrency evidence

Exercise disconnect before work, during model/tool call and before response write; sync lease expiry;
explicit proof that no background takeover occurs; cancel/completion ordering; cancel replay; late
tool/model/worker results; concurrent event allocation; duplicate/stale transition tokens and terminal
immutability.

## Security and authorization evidence

Attach protected-authority injection denials and PostgreSQL non-owner results for run/event/child/
approval/retrieval/tool scope. Record prompt-injection/tool invention, budget/timeout, kill-switch,
audit/usage failure, event redaction/size and external/internal ID-confusion tests.

## Migration and rollback verification

Record exact zero counts/references for protected data and pending work, old API source/config/access
inventory, stopped/drained worker proof, migration diff review and manual apply approval. Before apply,
demonstrate the documented rollback: deploy previous code against a recreated empty database, apply
previous migrations and approved seed/configuration, then pass health and endpoint smoke. If zero-state
or disposability is false, stop and revise the plan.

## Behavior comparison with base branch

Compare RAG ACL/grounding/fallback/citations/output contracts and agent action/approval/escalation/
budget behavior on pinned fixtures. List intentional breaking changes: scenario type/artifact/run
models, `/query`, `/invoke`, DELETE cancellation and identifier semantics.

## Checks not run, remaining risks and human review

Not evaluated yet. Staff engineer reviews architecture/concurrency/migrations; AppSec reviews policy
convergence, protected authority, RLS and redaction; SRE reviews disconnect, recovery, load, cutover and
empty rollback; API owner reviews Responses/Chat/run compatibility. Record every unavailable check
and residual risk before Verified.

## Final status

**Planned / not verified.**
