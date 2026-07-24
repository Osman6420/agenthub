# Verification: Phase 2.8 Part 3 — Unified workflow engine

> **Status: Not yet verified.** Evidence is recorded independently for every delivery gate. This
> record does not authorize the destructive migration.

## 2026-07-24 refreshed baseline

| Check | Result |
| --- | --- |
| Codebase Memory architecture | 10,000 nodes, 43,610 edges; workflow, gateway, agents, releases, tools, orchestration and evaluation are direct impact areas |
| Type-dispatch inventory | 101 exact `ScenarioType`/scenario-type matches across 89 application files |
| Broad removal inventory | 87 application/config/frontend files contain old endpoint/type/artifact/run vocabulary |
| Compose state | postgres/redis/minio healthy; web/runtime/ingestion/eval/beat running |
| Liveness | `GET /v1/health/live` → HTTP 200 `{"status":"ok"}` |
| Applied runtime migrations | workflows through `0008`; agents through `0004`; gateway `0002`; releases `0003` |
| Live disposable data | 17 scenarios; 11 executable artifacts; 9 compiled versions; 18 runs; 70 events; 20 idempotency rows; 2 approvals; 0 child links |
| Pending work | one workflow run is `running`; destructive gate must drain it |

The owner stated that existing workflow and run records are not material real data and need neither
compatibility nor conversion. This evidence authorizes planning that discards those rows, not the
unreviewed execution of a destructive migration.

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

## Gate 1 implementation evidence

| Check | Command | Result |
| --- | --- | --- |
| Compiler v5 execution-mode slice | `python -m pytest apps/workflows/tests/test_compiler.py apps/workflows/tests/test_recovery.py apps/workflows/tests/test_waits.py apps/workflows/tests/test_parallel_transitions.py apps/console/tests/test_workflow_trace_console.py -q` in Compose web | 39 passed |
| Diff whitespace | `git diff --check` | Passed |
| Focused Ruff/Mypy | Compose web `ruff` / `mypy` | Unavailable: production image does not contain dev executables |
| Host test/tool runner | `.venv\Scripts\python.exe` | Unavailable: documented Windows “logon session does not exist” launcher failure |
| Gated `agent_loop` backend regression | `python -m pytest apps/workflows/tests apps/builder/tests apps/orchestration/tests/test_authoring_guide.py -q` in Compose web | 254 passed |
| Studio focused tests | `npm --prefix frontend run test -- --run src/__tests__/node_config_panel.test.tsx src/__tests__/schema.test.ts` | 5 passed |
| Studio typecheck | `npm --prefix frontend run typecheck` | Passed |
| Release/workflow pin regression | `python -m pytest apps/releases/tests apps/workflows/tests -q` in Compose web | 211 passed |
| Shared policy + tool-free runtime regression | `python -m pytest apps/agents/tests apps/workflows/tests -q` in Compose web | 297 passed |
| Unified Run focused model/event checks | `.venv\Scripts\python.exe -m pytest -q apps/workflows/tests/test_unified_run.py` | 4 passed; PostgreSQL-only RLS test skipped |
| Unified Run PostgreSQL/RLS checks | `.venv\Scripts\python.exe -m pytest -q --ds=config.settings.local apps/workflows/tests/test_unified_run.py` with local Compose PostgreSQL | 5 passed, including non-owner cross-tenant denial |
| Gate 2 affected regression | `.venv\Scripts\python.exe -m pytest -q apps/workflows/tests apps/builder/tests/test_api.py apps/releases/tests/test_compiler.py` | 243 passed; 3 PostgreSQL-only tests skipped |
| Migration drift | `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| Gate 2 focused Ruff | `.venv\Scripts\python.exe -m ruff check ...` on unified persistence files | Passed |
| Gate 2 focused Mypy | `.venv\Scripts\python.exe -m mypy apps/workflows/run_events.py` | Passed |
| Unified transition PostgreSQL concurrency | `.venv\Scripts\python.exe -m pytest -q --ds=config.settings.local apps/workflows/tests/test_unified_run.py` | 8 passed; concurrent same-version writers produced one commit and one stale result |
| Transition affected regression | `.venv\Scripts\python.exe -m pytest -q apps/workflows/tests apps/builder/tests/test_api.py apps/releases/tests/test_compiler.py` | 245 passed; 4 PostgreSQL-only tests skipped |
| Transition Ruff/Mypy | Focused `ruff check` and `mypy apps/workflows/run_events.py apps/workflows/transitions.py` | Passed |
| Transition idempotency/cancel/lease PostgreSQL | Compose web `python -m pytest -q apps/workflows/tests/test_unified_run.py` | 13 passed, including concurrent duplicate-token replay, cooperative cancel and lease-expiry recovery |
| Gate 2 idempotency affected regression | Compose web `python -m pytest -q apps/workflows/tests apps/builder/tests/test_api.py apps/releases/tests/test_compiler.py` | 253 passed |
| Migration drift | Compose web `python manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| Idempotency slice Ruff/Mypy | Compose web focused `ruff check --no-cache` and `mypy apps/workflows/run_events.py apps/workflows/transitions.py` | Passed |

The v5 compiler now emits deterministic `execution_mode_analysis`. Background is always present;
sync is present only when the graph has no known durable/unproven blocker. Tool/custom nodes fail
closed until release-pinned bounds can be proven; waits, fan-out and child calls are background-only.
No endpoint, authorization rule, database schema or production dependency changed in this slice.
The follow-up closed `agent_loop` contract is disabled by default through
`WORKFLOW_AGENT_LOOP_ENABLED`; compiler, Studio and AI authoring all expose the same gate. It reuses
the existing agent-definition validation and hard-limit normalization, requires typed input/output
mappings, rejects protected/unknown fields and remains background-only until runtime and
release-pinned pause analysis are implemented.
Release compilation additionally checks every embedded agent tool/verification role against exact
same-release tool-binding pins and includes the compiler mode analysis in the release manifest
checksum. Approval-required or side-effecting verification tools fail closed. Positive sync
eligibility is deliberately not granted because current tool pins do not yet carry sufficient
transport-timeout evidence.

The persistence-independent `resolve_runtime_policy` now owns compiled limits, verification roles,
repeat/escalation flags and composition attenuation for both AgentRun and the workflow adapter.
Tool-free embedded execution reuses the existing governed planner/retrieve/respond/output-contract
path, while the workflow runtime independently rechecks `WORKFLOW_AGENT_LOOP_ENABLED` and persists
only the outer node transition. Embedded tools fail closed with
`AGENT_EMBEDDED_TOOLS_UNAVAILABLE`; durable approval/checkpoint/counter integration is not claimed.

## Gate 2 persistence evidence

An additive UUID `Run` aggregate and direct-tenant `RunEvent` now exist; no current route or worker
writes them. The model pins scenario/release/workflow/compiler identity and owns checkpoint version,
next event sequence, mode/lease, cancellation and usage counters. Event allocation locks the Run
row, assigns sequence server-side and increments the counter in the same transaction. Event types
are database-constrained to a closed registry. The allocation boundary rejects payloads over 16
KiB, depth over eight, non-JSON/non-finite values and sensitive body, prompt, document, credential,
secret and token fields. PostgreSQL verification proved FORCE RLS visibility for the active tenant
and denial for another tenant scope under a non-owner role.

The locked transition service derives legal edges and event types server-side. Every committed
transition increments the checkpoint version; stale status/version results leave state unchanged
and append safe `run.late_result_discarded` evidence. Terminal results cannot reopen a Run. Waiting
states require a typed reference, checkpoint JSON is capped at 1 MiB, counters are non-negative and
bounded by the database integer range, and terminal transitions clear sync leases. A real
PostgreSQL two-writer testing proved the row lock/CAS behavior. Every transition now requires a UUID
token. `RunEvent` stores the token with a canonical request checksum under a per-run conditional
unique constraint. Exact sequential or concurrent replay returns the original result without
another event or counter mutation; reuse with changed transition content fails closed. This
intentionally reuses the direct-tenant RLS-protected event authority rather than adding a second
receipt table.

Cancellation requests are bounded to closed reason codes, recorded once, and remain cooperative
until the next locked transition boundary, where cancellation wins over ordinary completion.
Bounded sync leases require the exact UUID owner, cannot extend beyond 60 seconds or the run
deadline, and cannot renew after cancellation. Expiry resolution verifies the exact expired token
under the Run lock, then enters `recovery_required`, or `cancelled` if disconnect/cancellation was
already recorded. It clears ownership and never queues or changes execution mode. Transport
disconnect hooks, lease scanning/recovery tooling and API/worker integration remain unimplemented.

## Gate 2 background claim/delivery evidence

The additive `0011` migration adds one complete-or-null background claim tuple to `Run`: UUID token,
bounded expiry and checkpoint-version snapshot. An identifier-only delivery parser rejects extra
task-body/header authority and uses the tenant header only to establish PostgreSQL RLS context before
reloading the Run. Claim acquisition uses `select_for_update`; same-token redelivery is inert,
competing live delivery is busy, and an expired queued claim can be replaced before work starts.
Every background transition after queue admission proves the exact claim token and checkpoint
snapshot. An expired running claim converges to `recovery_required` without takeover; cancellation
and deadline guards converge to `cancelled`/`timed_out`. Claim audit is content-free and transactional:
an audit persistence failure rolls back ownership.

| Check | Command | Result |
| --- | --- | --- |
| Codebase Memory availability/architecture | `get_architecture(overview)` for path-matched project `C-Users-kuzuc-Desktop-agenthub` | Passed: 10,263 nodes, 44,684 edges; semantic/similarity edges available; freshness endpoint not exposed |
| Unified background claim PostgreSQL | Compose web `python -m pytest -q apps/workflows/tests/test_unified_run.py` | 20 passed, including two-writer single-owner claim, duplicate/competing delivery, stale owner, queued reclaim, running crash recovery, cancellation, deadline, tenant scoping, identifier-only delivery and audit rollback |
| Background claim affected regression | Compose web `python -m pytest -q apps/workflows/tests apps/builder/tests/test_api.py apps/releases/tests/test_compiler.py` | 261 passed |
| Migration drift | Compose web `python manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| Focused Ruff | Compose web `python -m ruff check --no-cache ...` on claim/model/transition/test/migration files | Passed |
| Focused Mypy | Compose web `python -m mypy apps/workflows/background_claims.py apps/workflows/transitions.py` | Passed |
| Diff whitespace | `git diff --check` | Passed |

No public route, authorization policy, tenant-isolation rule, production dependency or old worker
path changed. Migrations `0009` through `0011` were not applied to the live development database. No
Celery task is registered yet, so broker redelivery/crash integration and full graph execution remain
pending despite the verified persistence boundary.

## Gate 2 worker-admission evidence

Worker admission now verifies that the Run and WorkflowVersion both use the locally supported
`workflow-compiler/v5`, that their checksums match, and that the release manifest pins the same
workflow checksum. Delivery-carried revision metadata is not authority. The existing global/tenant
runtime kill switch is checked after tenant context is installed and before claim ownership; it is
also rechecked at every ordinary claimed transition. Suspension preserves queued state and allows an
already-running owner only to converge to recovery, cancellation or timeout.

| Check | Command | Result |
| --- | --- | --- |
| Worker-admission PostgreSQL | Compose web `python -m pytest -q apps/workflows/tests/test_unified_run.py` | 23 passed, including compiler/checksum drift and claim/transition kill-switch races |
| Admission affected regression | Compose web `python -m pytest -q apps/workflows/tests apps/builder/tests/test_api.py apps/releases/tests/test_compiler.py apps/agents/tests/test_governed_loop.py` | 296 passed |
| Migration drift | Compose web `python manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| Focused Ruff/Mypy | Compose web focused `ruff check --no-cache` and `mypy` on background claims/transitions | Passed |
| Diff whitespace | `git diff --check` | Passed |

Codebase Memory data-flow tracing confirmed that the legacy `execute_graph` writes
WorkflowRun-specific branch/wait/recovery tables. It is therefore not registered as the unified Run
executor. A Run-native node-step adapter and fleet-revision-safe Celery task remain pending.

## Final status

**In progress — Gate 2 persistence, background claim/delivery and worker admission verified;
Run-native Celery execution, shared consumers and cutover remain pending.**
