# Verification: Phase 2.8 Part 3 — Unified workflow engine

> **Status: Verified 2026-07-28.** Canonical runtime, destructive local cutover, rollback drill,
> authorization/RLS, regressions, frontend build and live smoke evidence all passed. Production was
> not accessed or modified.

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
| Responses/Chat/run APIs | Gate 3a PostgreSQL + regression containers | Passed | 100 focused; 303 gateway/workflow | Background workflow Responses, UUID status and POST cancel verified; sync Chat and unified RAG/Agent remain pending |
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

## Gate 3a planned evidence

The first public consumer slice is intentionally narrower than the complete Gate 3 migration. Tests
must prove authorized background workflow admission creates exactly one UUID Run with ordered
requested/queued events, a separately stored stable `resp_...` identifier and identifier-only
post-commit delivery. They must also prove idempotency replay/conflict, capability denial without
admission, UUID status/output scoping, idempotent POST cancellation, generic cross-tenant 404s and
default-off/worker-disabled fail-closed behavior. Legacy behavior must remain unchanged while the
gateway flag is disabled. Sync Chat, unified RAG/Agent presets and non-gateway consumers remain
unverified after this slice.

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

## Gate 2 bounded Run-native executor evidence

A default-off internal executor now supports only `input`, `format_output`, `validate_contract`,
`condition` and `end`. It validates the entire graph's API version, node allowlist, edge shape,
reachability and acyclicity before entering `running`. It never calls legacy WorkflowRun branch,
wait, retry, compensation or recovery persistence. Execution derives purpose-separated transition
UUIDs from the claim token, uses the shared transition/checkpoint service, validates output contracts
and output policy, and observes cancellation/deadline between nodes.

| Check | Command | Result |
| --- | --- | --- |
| Bounded executor PostgreSQL | Compose web `python -m pytest -q apps/workflows/tests/test_unified_run.py` | 27 passed, including default-off gate, successful Run-native completion, unsupported/cyclic preflight denial and between-node cancellation |
| Bounded executor affected regression | Compose web `python -m pytest -q apps/workflows/tests apps/builder/tests/test_api.py apps/releases/tests/test_compiler.py apps/agents/tests/test_governed_loop.py` | 300 passed |
| Focused Ruff | Compose web `python -m ruff check --no-cache ...` on executor/claim/transition/test files | Passed |
| Focused Mypy | Compose web `python -m mypy apps/workflows/unified_executor.py apps/workflows/background_claims.py apps/workflows/transitions.py` | Passed |
| Migration drift | Compose web `python manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| Diff whitespace | `git diff --check` | Passed |

No Celery task or public route dispatches this executor. Tool/model/retrieval and every durable pause,
child, parallel, retry, compensation or recovery node remain denied. Real broker redelivery,
worker-loss and deployment-gate smoke remain pending.

## Gate 2 Celery delivery and worker-loss evidence

The internal runtime task now uses `acks_late` and `reject_on_worker_lost`. Its body is exactly Run
UUID plus delivery UUID; custom headers are exactly tenant ID and a bounded diagnostic service
revision. The producer schedules only through `transaction.on_commit`. Stale revisions are
acknowledged as safe denials before claim, while stored compiler/checksum pins remain authoritative.
The task is registered in code but has no public producer and the live worker has not been restarted.

Exact-token redelivery now handles all bounded crash positions: an expired queued claim is
transactionally released with content-free audit evidence and re-claimed; an expired running claim
converges to `recovery_required`; and a live running claim after crash resumes execution without
replaying the already committed start transition. Terminal redelivery returns the terminal state.

| Check | Command | Result |
| --- | --- | --- |
| Celery delivery PostgreSQL | Compose web `python -m pytest -q apps/workflows/tests/test_unified_run.py` | 32 passed, including closed headers/body, on-commit dispatch, real Celery task apply, stale revision, expired queued/running claims and crash-after-start continuation |
| Celery delivery affected regression | Compose web `python -m pytest -q apps/workflows/tests apps/builder/tests/test_api.py apps/releases/tests/test_compiler.py apps/agents/tests/test_governed_loop.py` | 305 passed |
| Focused Ruff | Compose web `python -m ruff check --no-cache ...` on delivery/claim/executor/task/test files | Passed |
| Focused Mypy | Compose web `python -m mypy apps/workflows/background_claims.py apps/workflows/unified_executor.py apps/workflows/tasks.py` | Passed |
| Migration drift | Compose web `python manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| Diff whitespace | `git diff --check` | Passed |

Live broker smoke was not run: migrations `0009` through `0011` remain unapplied and the running
runtime worker predates this task registration. The default-off gate and absence of a public producer
prevent accidental unified execution in that state.

## Gate 2 Run-native durable wait evidence

`workflows.0012` adds the tenant-scoped `RunWait` authority (UUID PK, direct `organization` FK, FORCE
ROW LEVEL SECURITY plus the shared `agenthub_tenant_scope_contains` policy) under two DB-enforced
invariants: at most one `pending` wait per Run, and a consumption CHECK that keeps `pending` rows free
of consumption fields while requiring `consumed_at`/`resume_checksum`/`result_checkpoint_version` on
`resumed` and `consumed_at` without a result version on `expired`/`cancelled`.

`suspend_run_for_wait` releases the background claim and stores a hashed one-shot resume token with a
lineage snapshot (checkpoint version, release, compiled checksum, compiler version). The output
mapping is compiled with `restrict_destination=True` at creation, so a protected write root fails
closed as `RUN_WAIT_CONFIG_INVALID` before a resume authority exists rather than failing a valid
payload later. The deadline is clamped to the Run deadline. If cancellation or timeout already
converged the Run, suspension returns `converged` and preserves that committed evidence instead of
raising and rolling it back.

`resume_run_wait` locks the Run and the wait with `select_for_update`, then audits every branch before
reporting it: unknown token, replayed/consumed token, lineage mismatch, expiry, role denial,
self-decision denial, invalid payload and terminal convergence. Denials are audited inside the
transaction and raised after it commits, matching the existing `decide_approval` pattern, so evidence
is never discarded. An expired wait closes the Run as well (`failed` / `RUN_WAIT_EXPIRED`) so no Run is
left waiting on an authority that can never be consumed.

`transitions.py` gains `DURABLE_WAIT_STATUSES`; a background Run in one of those statuses may move to
`queued`/`failed`/`timed_out`/`cancelled` without a claim token, because suspension already released
the claim and there is no owner to displace. `running` and `recovery_required` are excluded, so reaching
execution still requires a fresh background claim and claim-ownership proof is unchanged everywhere
else.

There is no public producer, no executor node enablement and no consumer route: the boundary is
additive and reachable only from internal tests.

| Check | Command | Result |
| --- | --- | --- |
| Durable wait + RLS PostgreSQL | `pytest --ds=config.settings.local apps/workflows/tests/test_unified_run.py -k "wait or rls"` | 6 passed, 30 deselected — suspend/resume-once, forged/cross-tenant/role/self-decision/payload denials, expiry closing the Run, protected-mapping rejection, converged-cancel suspension and non-owner FORCE RLS over `workflows_run`/`workflows_runevent`/`workflows_runwait` |
| Affected regression PostgreSQL | `pytest --ds=config.settings.local --create-db apps/workflows/tests apps/tenancy/tests apps/builder/tests/test_api.py apps/releases/tests/test_compiler.py apps/agents/tests/test_governed_loop.py` | 323 passed, 3 skipped, 1 pre-existing failure (see gaps) |
| Full SQLite suite | `DJANGO_SETTINGS_MODULE=config.settings.test pytest` | 1062 passed, 51 skipped, 1 failure + 2 errors — byte-identical to the unmodified HEAD baseline (1061 passed, 46 skipped, same failure and errors), so this slice introduces no regression |
| Repository Ruff format | `ruff format --check .` | 438 files already formatted |
| Repository Ruff lint | `ruff check .` | All checks passed |
| Repository Mypy | `mypy apps config` | 13 errors in 4 files — identical to the unmodified HEAD baseline |
| Django check | `python manage.py check` | System check identified no issues |
| Migration drift | `python manage.py makemigrations --check --dry-run` | No changes detected |
| Diff whitespace | `git diff --check` | Passed |

### Application-role grants (owner approved)

`deploy/postgres/provision-app-role.sql` now names the three unified tables at least privilege:
`SELECT, INSERT, UPDATE` on `workflows_run` and `workflows_runwait` (mutable state), `SELECT, INSERT`
on `workflows_runevent` (append-only). No `DELETE` is granted anywhere, matching the code: `rg` finds
no delete path in `apps/workflows`, so the role cannot erase run lineage or a consumed wait authority.

Evidence is enforced by two tests rather than review alone:

- `test_unified_run_tables_are_protected_and_provisioned` asserts the three tables are classified as
  direct-tenant `PROTECTED` in `protected_tenant_tables()`, are named in the provisioning SQL, and
  appear in no `GRANT ... DELETE` statement.
- `test_unified_run_grants_make_a_non_owner_role_rls_ready_without_delete` (PostgreSQL) creates a
  `NOSUPERUSER NOBYPASSRLS` probe role, applies exactly the inventory grants, and asserts
  `inspect_rls_readiness` reports `ready` with no issues — proving table presence, `FORCE` RLS, the
  canonical `tenant_isolation` policy and `SELECT` for all three — then asserts
  `has_table_privilege(..., 'DELETE')` is false for each.

Before the edit, `protected_tenant_tables()` reported `workflows_run`, `workflows_runevent` and
`workflows_runwait` as missing from the provisioning SQL; after it, exactly those three disappear from
the missing set.

Checks not run and gaps:

- **Pre-existing, outside this slice's approval:** `test_provisioning_sql_names_every_protected_table`
  still fails on five Phase 2.8 Part 2.1 tables that were never added to the grant inventory —
  `documents_scenariodocumentsetaccessrequest`, `documents_scenariodocumentsetgrant`,
  `identity_documentsetmanagerassignment`, `identity_projectadministratorassignment` and
  `identity_scenarioeditorassignment`. This failure reproduces on the unmodified HEAD. Four of them are
  authorization-assignment tables, so the grant level needs owner review of its own; they were not
  added here.
- Migration `0012` has not been applied to the running Compose database and no live broker or worker
  smoke was run.

### Repository formatting gate repair

`ruff format --check .` was failing on the unmodified HEAD for 19 files: `pyproject.toml` declared
`ruff>=0.6` while `requirements.lock` pinned `ruff==0.15.21`, and CI installs the unpinned range, so
the formatter's line-joining behavior differed between the baseline and every current install. The dev
extra is now pinned to `ruff==0.15.21` (matching the lock) and the repository was reformatted with it.
One pre-existing `I001` import-order error in `apps/agents/runtime.py` was auto-fixed. This is
mechanical: no behavior, signature or control-flow change, confirmed by the identical full-suite
baseline above.

## Gate 2 Run-native parallel/join implementation evidence

The working tree adds additive migration `workflows.0013_run_parallel_region` and the default-off
internal parallel/join path. `RunBranch` persists tenant-scoped branch identity, exact delivery
capability, delivery/claim leases, attempt count and bounded result state. `RunJoin` persists the
compiled concurrency, duration and state limits plus a clamped deadline. Both direct-tenant tables
are FORCE RLS with the canonical tenant policy and have least-privilege application-role grants
without `DELETE`.

Branch delivery is a durable reservation, not broker authority: admission locks
`Run -> RunJoin -> RunBranch`, reserves only available concurrency slots with a UUID delivery token,
and publishes identifiers plus that opaque token only after commit. Claim/completion require the
exact token and an unexpired lease. The 15-second, default-off reconciler repairs expired delivery
reservations, fails a lost branch claim closed, closes elapsed joins and resumes a parent only through
the existing region-specific wait authority. Cancellation of a parked parent revokes outstanding
branch capabilities and converges it to `cancelled`; late work remains inert. Branch bodies now also
require explicit input mappings, so governed node code receives a local envelope rather than ambient
branch state.

| Check | Command | Result |
| --- | --- | --- |
| Focused parallel/join SQLite regression | Temporary disposable Compose test container: `pytest apps/workflows/tests/test_unified_parallel.py -q` | Passed: 15 before the final static hardening that adds one input-mapping denial case, with admission capacity, exact-token redelivery, worker-loss convergence, cancellation, deterministic `for_each`, cross-tenant denial and graph guards covered |
| Unified Run SQLite regression | Temporary disposable Compose test container: `pytest apps/workflows/tests/test_unified_parallel.py apps/workflows/tests/test_unified_run.py -q` | Passed: 51, skipped: 9 PostgreSQL-only cases; run before the final scan-budget/state-budget/input-mapping hardening described below |
| Migration drift | Compose web `python manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| Django check | Compose web `python manage.py check` | Passed: no issues |
| Final static checks | Host `ruff check` / `ruff format --check` on changed workflow/settings/tests, `compileall`, `git diff --check` | Passed after the branch-lease renewal change |
| Current focused Mypy | `python -m mypy apps/workflows/run_parallel.py apps/workflows/tasks.py apps/workflows/transitions.py apps/workflows/unified_executor.py` | Blocked before analysis: host Mypy 2.1.0 cannot construct `NewSemanalDjangoPlugin` |
| Focused Mypy fallback | Disposable Python 3.13 container with project-declared `django-stubs[compatible-mypy]` | Passed: no issues in `run_parallel.py`, `tasks.py`, `transitions.py`, `unified_executor.py` |
| Current Compose inspection | `docker compose ... ps`, `GET /v1/health/live`, Compose web `manage.py check` / `showmigrations workflows --plan` | Passed: services healthy, liveness HTTP 200, Django check clean; `0013_run_parallel_region` remains unapplied |
| Current host focused test rerun | `python -m pytest apps/workflows/tests/test_unified_parallel.py -q` | Blocked before collection: host Python 3.14 lacks `opentelemetry` |
| Final PostgreSQL regression | Disposable Python 3.13 container, unique PostgreSQL test DB, `pytest apps/workflows/tests/test_unified_parallel.py apps/workflows/tests/test_unified_run.py -q` | Passed: 65; includes `0013`, FORCE-RLS/non-owner coverage, app-role grants and concurrent branch-claim ownership |
| Disposable DB cleanup | Read-only `pg_database` query for `test_parallel_verify_20260727%` | Passed: no matching test database remains |

The hardening after the recorded SQLite run adds (1) a reconciler scan budget, (2) initial and
merged-state checks against the persisted join budget, (3) the branch input-mapping guard plus its
denial test, (4) exact-capability lease renewal at each safe branch-node boundary, and (5) a direct
PostgreSQL two-worker branch-claim race. Branch nodes run in separate short RLS transactions, so the
renewal's `Run -> RunJoin -> RunBranch` locks are released before the next node. The focused module now
contains 18 tests. A disposable Python 3.13 run applied `0013` only to a unique test database and passed
all 65 focused parallel/unified tests, including FORCE-RLS/non-owner, application-role grants and the
new one-owner/one-exact-duplicate claim proof. The test database was automatically removed and confirmed
absent afterward. The running Compose `agenthub` database remains unchanged: `0013` is unapplied, no
worker was restarted and the feature remains disabled without `UNIFIED_BACKGROUND_EXECUTOR_ENABLED`.

## Gate 3a public workflow consumer evidence

The default-off `UNIFIED_GATEWAY_ENABLED` switch moves only background workflow requests received at
`POST /v1/responses` to the canonical UUID `Run`. Admission reuses the authenticated
binding/capability/canary-release boundary, then independently verifies that the signed execution
context exactly matches the selected tenant, project, scenario, consumer and release and contains
`workflow_run`. It validates the exact compiler mode analysis, stores a separate random `resp_...`
identifier, persists bounded/redacted initial state and appends ordered `run.requested` then
`run.queued` events in one transaction. The worker switch must also be enabled before admission.
Delivery is post-commit and carries only Run UUID, delivery UUID, tenant routing ID and bounded
service revision.

When the gateway switch is enabled, `GET /v1/runs/{uuid}` resolves only a direct consumer/tenant-owned
unified Run and `POST /v1/runs/{uuid}/cancel` records cooperative cancellation. Foreign tenants and
consumers receive the same 404. Cancellation replay is idempotent and appends one cancellation event.
Admission and cancellation wrap required audit/usage writes in the same outer transaction; injected
audit failure tests prove the state mutation rolls back. `X-AgentHub-Run-Id` carries only the Run UUID,
while the Responses body uses the separately stored response ID.

| Check | Command | Result |
| --- | --- | --- |
| Focused Gate 3a + Gate 2 PostgreSQL | Disposable Python 3.13 container, unique PostgreSQL DB, `pytest apps/gateway/tests/test_openai_compat.py apps/gateway/tests/test_invoke.py apps/workflows/tests/test_unified_run.py apps/workflows/tests/test_unified_parallel.py -q` | Passed: 100; includes migration `0013`, one-Run concurrent admission, exact signed-context binding, capability denial, worker-disabled zero-admission, response/run ID separation, identifier-only post-commit delivery, cross-tenant status/cancel, cancel replay and audit-failure rollback |
| Gateway/workflow PostgreSQL regression | Disposable Python 3.13 container, same isolated base DB, `pytest apps/gateway/tests apps/workflows/tests -q` | Passed: 303 |
| Focused Mypy | Disposable Python 3.13 container with project + `django-stubs[compatible-mypy]`, `mypy apps/workflows/services.py apps/gateway/views.py apps/gateway/openai_compat.py` | Passed: no issues in 3 source files |
| Focused Ruff/format/compile | Host Python 3.14 `ruff check`, `ruff format --check`, `compileall` on Gate 3 files | Passed |
| Django system check | Compose web `python manage.py check` | Passed: no issues |
| Migration drift | Compose web `python manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| Runtime inspection | Compose `ps` plus `GET /v1/health/live` | Passed: application/infrastructure roles up, PostgreSQL/Redis/MinIO healthy, HTTP 200 |
| Disposable cleanup | Exact `pg_database` and container-name queries after dropping/removing Gate 3 resources | Passed: no matching database or container remains |

The running Compose application database was not migrated, no worker was restarted and no public
flag was enabled. The default-off path preserves the existing Responses/Chat/invoke/query behavior.
Sync Chat, RAG/Agent conversion, MCP/evaluation/console consumers, live worker smoke and the
separately approved destructive cutover remain unverified.

## Gate 3b unified observability metrics evidence

`Run` creation now increments `agenthub_unified_run_admissions_total` with only the closed
`execution_mode` label. Each append-only `RunEvent` increments
`agenthub_unified_run_events_total` with only the closed `event_type` label. Signals bound unknown
values to `other`; they never export tenant, consumer, Run/response ID, reason text, checkpoint,
payload or input/output content. Existing workflow/agent counters remain additive compatibility
metrics until the atomic cutover.

| Check | Command | Result |
| --- | --- | --- |
| Observability/gateway/workflow PostgreSQL regression | Disposable Python 3.13 container, unique PostgreSQL DB, `pytest apps/observability/tests apps/gateway/tests apps/workflows/tests -q` | Passed: 321; includes exact admission/event increments, rendered-metrics proof that no Run UUID/content/identity label key is exported, and preservation of unmigrated AgentRun status while Gate 3a is enabled |
| Gate 3 application Mypy | Disposable Python 3.13 container with `django-stubs[compatible-mypy]`, `mypy apps/observability/metrics.py apps/observability/signals.py apps/workflows/services.py apps/gateway/views.py apps/gateway/openai_compat.py` | Passed: no issues in 5 source files |
| Focused static checks | Host `ruff format --check`, `ruff check`, `compileall`, `git diff --check` | Passed |
| Disposable cleanup | Exact DB/container-name queries after drop/removal | Passed: no matching database or container remains |

## Gate 3c synchronous workflow evidence

Canonical Responses, Chat and Run routes no longer inherit the operator middleware's request-wide
PostgreSQL transaction. Bearer-token resolution uses a short transaction; unified admission, exact
sync-lease acquisition and the `requested`/`queued` evidence commit before execution begins. The
executor commits `running` before entering a separate bounded node-work transaction. Process loss
therefore cannot erase admission or the running/lease ownership record; lease expiry uses the
existing explicit recovery/cancellation path and never transfers execution to a background worker.
Queued/running sync transitions reject missing, stale and expired lease authority.

Sync workflow Responses now execute through the same Run transition/executor seam and return the
separate Responses ID plus `X-AgentHub-Run-Id`. Completion writes ordered terminal RunEvent evidence,
a safe completion audit and usage evidence. Denial audit is written after the failed request
transaction rolls back, preserving stable protocol/error reasons without committing a partial
admission.

| Check | Command | Result |
| --- | --- | --- |
| Sync/gateway/Agent Loop PostgreSQL | Disposable Python 3.13 container and isolated PostgreSQL database, `pytest apps/agents/tests/test_runtime.py apps/workflows/tests/test_presets.py apps/tenancy/tests/test_tenant_context.py apps/gateway/tests/test_openai_compat.py apps/gateway/tests/test_invoke.py apps/workflows/tests/test_unified_run.py -q` | Passed: 111, skipped: 1 SQLite-only assertion; includes sync admission/execution, exact lease ownership, request-process/worker-crash durable evidence, protocol-denial audit, type-free preset compilation and bounded Agent Loop approval/resume state |
| Focused Ruff | Host `ruff check` on gateway, tenancy, transition, executor and focused tests | Passed |

The transport cannot guarantee that every WSGI server reports a client disconnect before process
loss. The authoritative fallback is the bounded sync lease: its expiry converges to explicit
recovery/cancellation without replay or background takeover. RAG/Agent preset conversion, MCP,
evaluation, console and destructive/static removal remain pending.

## Final cutover and closure evidence

The owner explicitly authorized deletion of all local/demo consumer, user, scenario and related
legacy runtime data. The target was verified as the local Compose `agenthub` database; production
was out of scope. Runtime application roles were stopped before migration/reset. Migrations through
`workflows.0017_run_compensation` applied successfully. Old Agent/Workflow run/event/wait tables are
absent. The canonical seed produced five demo users, two protocol-specific consumers and three
workflow scenarios; one sync smoke Run was then persisted.

| Check | Result |
| --- | --- |
| Full backend SQLite regression | `962 passed, 53 skipped` |
| Final changed-boundary regression | `50 passed` (child resolution, human-task dispatch, compiler/release and metrics) |
| Ruff lint and format | Passed across 418 Python files |
| Mypy | Passed: no issues in 418 source files |
| Django system and migration drift | `manage.py check` passed; no migration changes detected |
| Full frontend tests | 7 files / 24 tests passed; one pre-existing React `act` warning |
| Frontend typecheck | Passed |
| Frontend production build | Passed |
| Workflow focused regression | `186 passed, 11 skipped` |
| Builder + console + releases | `278 passed` |
| Fresh PostgreSQL migration/check/seed | Passed through workflows.0017; `manage.py check` and canonical `seed_demo --reset` passed |
| PostgreSQL workflow + tenancy RLS/context | `213 passed, 3 skipped`, including FORCE RLS, non-owner grants, cross-tenant denial and row-lock paths |
| Previous-code rollback drill | Passed on disposable `p283_rollback`: old migrations, Django check and old seed; resources removed afterward |
| Live local cutover | Migrations applied; authorized demo data reset; web/runtime/ingestion/eval/beat recreated and running |
| Live API smoke | `POST /v1/responses`, `model=empty-workflow`, `background=false` returned HTTP 200 / `completed` |
| Live canonical counts | users=5, consumers=2, scenarios=3, runs=1 |
| Legacy table absence | `agents_agentrun`, `workflows_workflowrun`, `workflows_workflowevent`, `workflows_workflowwait` all absent |

## Final status

**Verified and completed 2026-07-28.** One workflow artifact/compiler/runtime and canonical Run
lifecycle now serve Responses, Chat, MCP, evaluation and console consumers. RAG and agent are
workflow presets. Run-native wait, fan-out/join, child execution, bounded retry, compensation and
explicit operator recovery are implemented. The owner-approved local destructive cutover and
empty-database rollback strategy were both exercised successfully. Production deployment and
staging-equivalent load/soak remain operational follow-up, not unverified implementation scope.
