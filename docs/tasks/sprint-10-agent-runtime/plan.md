# Task Plan: sprint-10-agent-runtime

## Task summary

Add a durable, bounded agent runtime with immutable release/checkpoint state, guarded
tool use, trajectory evaluation, approval resume, and redacted operator traces.

## Background

Sprint 8 supplies compiled workflows and durable runs; Sprint 9 supplies the only
approved tool/approval boundary. Sprint 10 adds controlled stateful decision loops.
Planning is independent, but implementation must use the verified workflow, proxy,
approval, and operational contracts rather than anticipating them.

## Scope

- An agent runtime adapter (target design proposes LangGraph) behind an internal facade.
- `AgentRun`, immutable start snapshot, durable checkpoint, and append-only `RunEvent`.
- Requested/queued/running/waiting-approval/completed/failed/timed-out/cancelled state
  machine with transactional claims and resume.
- Step, token, duration, recursion/loop, tool-call, output, and state-size guards.
- Retrieval/model/tool/approval integration through existing governed services.
- Trajectory and safety assertions integrated with eval/promotion.
- Tenant-scoped redacted trace/status/cancel views and operational metrics/alerts.

## Non-goals

Unrestricted autonomous agents, arbitrary code/tools, user long-term memory, agent-
created credentials/bindings, runtime graph mutation, silent release upgrades during a
run, or unrestricted multi-agent delegation.

## Acceptance criteria

- A run remains pinned to its scenario release, graph/agent version, ExecutionContext,
  limits, and checkpoint across retry and approval resume.
- The agent cannot call an unbound tool or bypass proxy capability/risk/approval policy.
- Step/token/time/tool/state limits terminate deterministically with safe output/status,
  audit, usage, and no uncontrolled requeue.
- Worker crash/redelivery and concurrent resume/cancel preserve one valid state-machine
  transition and do not silently duplicate side effects.
- Final output passes contract and policy; trajectory assertions can block promotion.
- Operator/consumer trace and status access is tenant/action scoped and redacted.

## Affected components

New agent models/runtime adapter; workflows/orchestration, releases, evaluations,
tools/approval, gateway/MCP, console, Celery, audit, observability, migrations, settings,
tests, and docs.

## Interfaces affected

Agent artifact/config contract, async invoke/status/cancel semantics, checkpoint adapter,
trajectory assertion types, redacted trace view, and approval resume integration.
Backward-compatible public contract changes require explicit approval.

## Data impact

Add durable agent runs, checkpoints, and run events. Store only policy-approved redacted
state plus integrity checksums and immutable identifiers. Define TTL/retention, purge,
legal/audit holds, and indexing before rollout; long-term user memory remains disabled.

## Security impact

Model-directed loops amplify prompt injection, privilege misuse, data exfiltration,
denial of wallet/service, and tool side effects. Model decisions are proposals, never
authorization; every boundary revalidates policy and immutable pins.

## Authorization impact

Invoke/status/cancel/trace and resume are scoped to authenticated consumer/operator,
organization, scenario, run, and action. Tool selection is constrained by release
bindings and proxy policy. Worker/checkpoint payloads cannot grant permissions.

## Observability impact

Emit redacted lifecycle/decision/retrieval/tool/approval/limit/output events, counters,
durations, and trace links. Separate debug trajectory from append-only security/business
audit and canonical usage. Alert on loops, timeouts, stuck runs, tool denial, and cost.

## Migration impact

Additive run/checkpoint/event schema with state and uniqueness constraints. Rolling
deploy compatibility and checkpoint schema/version handling require explicit tests.

## Dependencies

Verified Sprints 8–9 runtime/checkpoint, tool proxy, approval resume, and telemetry
contracts and provider integration. LangGraph is approved as a production dependency
behind an internal adapter; implementation still requires version selection,
provenance/license/maintenance review, lockfile consistency, and operational evidence.

## Implementation steps

1. Approve adapter/framework decision, state machine, limits, retention, and schemas.
2. Add models, constraints, checkpoint versioning, and additive migrations.
3. Implement transactional claim/step/checkpoint/event and deterministic guard engine.
4. Integrate model/retrieval and the existing tool/approval proxy without alternate paths.
5. Add retry, redelivery, cancellation, deadline, resume, and uncertain-side-effect handling.
6. Add trajectory/safety assertions, trace/status views, metrics, alerts, and runbooks.
7. Add authorization, concurrency, fault-injection, load, migration, and end-to-end tests;
   update current-state documentation after verification.

## Test plan

- State-machine transitions, invalid transitions, immutable pins, checkpoint versioning,
  checksum corruption, and release rollback during an active run.
- Cross-tenant invoke/status/cancel/trace/resume and unauthorized tool denial.
- Step/token/time/tool/state/loop limits at boundaries and cost accounting.
- Crash before/after checkpoint/event/tool result, worker redelivery, concurrent resume/
  cancel/timeout, and approval expiry.
- Prompt injection/tool selection/output-contract/policy and trajectory eval failures.
- Redaction, retention/purge, audit failure, metrics cardinality, and stuck-run alerts.
- PostgreSQL integration and production-like bounded load/soak tests.

## Rollout plan

Deploy schema and read-only views, then enable deterministic no-tool agents for an
internal tenant. Gradually enable retrieval, read-only tools, then approved side-effect
tools with strict low limits and monitored cohorts. Keep a global start/resume kill switch.

## Rollback plan

Stop new agent starts, pause resume queues, preserve checkpoints/audit, and let safe
in-flight steps reach a checkpoint or cancel cooperatively. Do not resume a checkpoint
on incompatible code. Existing RAG/workflow paths remain available.

## Risks

- Framework checkpoint semantics may not match transaction/idempotency requirements.
- Crash after external success remains an uncertain side-effect risk.
- Long loops can create cost, load, and data-retention incidents.
- Redacted traces may impede diagnosis; verbose traces may leak sensitive reasoning/data.

## Open questions

- LangGraph version and checkpoint compatibility policy.
- Lower tenant/scenario limits, cancellation deadline, and operator override authority.
- Checkpoint/event purge, encryption, legal hold, and restricted trace visibility.
- Recovery policy for stuck/uncertain runs and deployment upgrades.

## Approved decisions

- LangGraph is approved as a production dependency only behind an internal AgentHub
  adapter. Domain services and persisted contracts must not depend directly on its API.
- Initial hard limits are 20 steps, 32,000 total tokens, 10 tool calls, 10 minutes per
  run, and a 2 MiB checkpoint. Lower tenant/scenario limits may apply; increases require
  review, cost analysis, and load evidence.
- Completed-run checkpoints are retained for 30 days. Failed runs or runs explicitly
  marked for investigation are retained for 90 days. Audit retention remains governed
  independently by the corporate policy; legal hold and purge details remain open.
- Raw chain-of-thought is never persisted. Only a policy-approved redacted decision
  summary, selected action, outcome code, counters, identifiers, and integrity checksum
  may be stored.
- Rollout proceeds from internal agents without tools, to read-only tools, and finally
  to approval-gated side-effecting tools. A global kill switch independently disables
  new starts and resumes.
- These decisions, including production use of LangGraph subject to supply-chain review,
  were approved by the project owner on 2026-07-10.

## Status

Implemented and Verified (2026-07-11). The `apps.agents` app delivers the bounded,
guarded agent runtime on the verified Sprints 8–9 contracts:

- `agent_definition` artifact (data, not code) with author-time validation and a
  deterministic checksummed compiler; releases pin the compiled agent and fail closed
  unless every declared tool resolves to a pinned `tool_binding` role.
- Durable `AgentVersion` / `AgentRun` (opaque `public_id` UUID) / append-only
  `AgentRunEvent`, immutable redacted start snapshot, versioned redacted checkpoint,
  and the requested→queued→running→waiting_approval→completed/failed/timed_out/cancelled
  state machine with `acks_late` claim-under-`select_for_update`, terminal-state
  idempotency, and stale/missing-message-safe no-op.
- Deterministic guard engine: step, tool-call, token, deadline, checkpoint-size, and
  checkpoint-schema-version caps terminate deterministically with a stable code and no
  uncontrolled requeue. Every planner decision is re-validated against the immutable
  compiled tool allowlist and the decision-kind allowlist (untrusted-planner defense).
- Tool use flows only through the Sprint 9 proxy/approval boundary; a required approval
  pauses the run (`waiting_approval` + durable checkpoint) and auto-resumes on the
  post-commit decision signal, failing closed on rejection.
- LangGraph is integrated **only** as an `AgentPlanner` adapter selected via
  `AGENT_PLANNER` (default is the deterministic planner, so CI/tests run no graph code).
  LangGraph owns only the planning loop/transitions/tool-selection/agent-local
  checkpointing; the durable run state machine, tenant isolation, tool proxy, approval,
  audit, retry, cancellation, and idempotency remain AgentHub's. No LangSmith / LangGraph
  Cloud / hosted service / new public endpoint was added.
- Gateway `POST /v1/invoke` returns `202` + `run_id` (the UUID `public_id`) for an
  authorized AGENT scenario, requiring `agent_invoke` + `Idempotency-Key`; `GET`/`DELETE
  /v1/runs/{id}` dual-dispatch (numeric→workflow, UUID→agent) and are consumer/tenant
  scoped.
- Trajectory eval assertions (`agent_completed`, `agent_tool_invoked`, `agent_no_tools`,
  `agent_max_steps`) run against the isolated candidate seam and can block promotion.
- Operator surfaces: role-gated, tenant-scoped console agent-run list + redacted trace
  view + cancel, and the `list_agent_runs` / `cancel_agent_run` management commands.
  Bounded Prometheus counters `agenthub_agent_runs_total` / `agenthub_agent_steps_total`.

Additive migrations only (`agents.0001`, `artifacts.0003`). One approved production
dependency added: `langgraph==1.2.9` (exact pin; transitive tree captured in
`requirements.lock`, `pip check` clean, and a CI step fails closed on lock drift).
`langsmith` is a dormant transitive dependency — no API key is set and no tracing is
enabled. See [`verification.md`](verification.md) for command evidence.

Residual / not implemented in this increment: a global start/resume kill switch, the
checkpoint retention/purge job (30/90-day policy is recorded but not automated), and
production-like load/soak tests remain operational follow-ups.

## Completion criteria

Definition of Done evidence covers immutable pins, state/checkpoint correctness,
authorization/isolation, all resource guards, tool/approval enforcement, retry and
fault behavior, redaction/retention, evaluation gates, migrations, load, rollback, and
manual application-security/SRE review.
