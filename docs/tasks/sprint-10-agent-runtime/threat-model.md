# Threat Model: sprint-10-agent-runtime

## Assets

Tenant data, model/provider budgets, agent definitions/releases, ExecutionContext,
checkpoints/state, tool authority, approvals, external side effects, trajectory/audit
integrity, output correctness, and runtime availability.

## Actors

Consumers, tenant operators, release managers, approvers, workers, model/retrieval/tool
providers, platform operators, malicious users, poisoned content, and compromised models.

## Entry points

Agent artifacts/config, invoke/status/cancel/trace endpoints, model prompts/responses,
retrieved content, tool outputs, worker messages, checkpoints, approval resume, eval
suites, and operator recovery actions.

## Trust boundaries

Consumer input to agent; retrieved/tool content to model; model decision to runtime
guards/proxy; queue to worker; checkpoint to resumed process; approval to tool attempt;
agent output to policy/contract; operator trace/recovery to tenant data.

## Data classifications

Inputs, state, retrieval, tool results, and checkpoints may contain confidential data
or PII. Credentials/secrets are restricted and excluded from state. Run IDs, usage,
limits, redacted events, and checksums are internal; audit is integrity-sensitive.

## Authentication

Existing consumer/operator authentication applies. Workers use approved workload
identity and re-resolve authoritative state. Approval/resume identities are revalidated;
model/provider identity or checkpoint content never authenticates an actor.

## Authorization

Server-side checks govern invoke/status/cancel/trace/recovery. Model tool selection is
not permission: the proxy rechecks capability, release binding, risk, and approval.
Administrative limit overrides and recovery require explicit scoped roles and audit.

## Tenant isolation

Run, release, checkpoint, events, indexes, tools, approvals, and evals remain within the
authenticated organization/scenario. Serialized state cannot select tenant context;
all persistence queries include authoritative scope.

## External systems

Model/retrieval providers, tool endpoints, Postgres, Redis/Celery, object store if used,
secret manager, and telemetry backend. Existing destination, timeout, retry, size,
redaction, and egress controls apply.

## Abuse cases

- Prompt/tool/retrieval injection induces forbidden calls, data disclosure, or policy bypass.
- Infinite/reflexive loops exhaust tokens, workers, database, or provider budgets.
- Forge or substitute checkpoint, release, limits, ExecutionContext, or tenant on resume.
- Replay tasks/resumes to duplicate tool side effects or corrupt trajectory.
- Read another tenant's trace/checkpoint or infer sensitive data from errors/events.
- Cancel/rollback/deploy during a step to create inconsistent or falsely successful state.
- Poison trajectory/eval evidence to promote an unsafe agent.

## Failure cases

Provider timeout/partial stream, worker crash, broker redelivery, checkpoint corruption,
database/audit outage, concurrent resume/cancel/expiry, deployment incompatibility,
stuck run, limit counter drift, and external side effect with lost response.

## Logging and audit risks

Agent trajectories can reveal prompts, PII, tool payloads, hidden instructions, or
sensitive reasoning. Persist allowlisted redacted summaries, decisions/outcomes,
checksums, counters, and stable reasons. Do not store raw chain-of-thought. Access to
debug traces is scoped and audited.

## Mitigations

Immutable signed/persisted pins; versioned checkpoints and integrity checks; explicit
state machine and row locks; idempotent claims/events; hard step/token/time/tool/state
limits; global kill switch; model-output tainting; central tool proxy and approvals;
contract/policy validation; tenant-scoped queries; redaction/retention; trajectory eval;
stuck-run reconciliation and safe uncertain outcomes.

## Residual risks

Models remain vulnerable to novel prompt injection and cannot be proven semantically
safe. Exactly-once external effects depend on providers. In-process framework/library
defects can affect all tenants. Redaction may remove forensic detail or miss novel
sensitive encodings.

## Required security tests

Prompt/retrieval/tool injection; unbound tool denial; cross-tenant run/checkpoint/trace/
approval denial; checkpoint/release/context/limit tampering; task/resume replay;
concurrent cancel/resume/timeout; every resource guard boundary; crash fault injection
around checkpoints and tool calls; output/trajectory gate bypass; redaction/no-chain-of-
thought; audit failure; retention/purge; and load/denial-of-wallet tests.

## Implementation status (2026-07-11)

Implemented and evidenced in [`verification.md`](verification.md):

- Immutable checksummed compiled agent + release pin (`agent_checksum`); the runtime
  reads only the pinned config, never the raw artifact.
- Versioned redacted checkpoint with an incompatible-version fail-closed guard; input
  redacted at ingress; events carry only allowlisted labels + checksums (no raw
  chain-of-thought) — the "no `hello` leaks" assertions verify this.
- Explicit state machine with `acks_late` claim-under-`select_for_update`, terminal-state
  idempotency, and stale/missing-message-safe no-op (task/resume replay defense).
- Hard step/tool-call/token/deadline/state-size caps, each failing closed with a stable
  code and no uncontrolled requeue.
- Model-output tainting: every planner decision is re-validated against the immutable
  compiled tool allowlist and decision-kind allowlist, so a compromised/novel planner
  (incl. LangGraph) cannot widen the tool surface or skip approval.
- Central Sprint 9 tool proxy + approval reused unchanged (capability/contract/field/risk/
  approval); required approval pauses and resumes; rejection fails closed; the Sprint 9
  idempotency key prevents double-execution.
- Output contract + policy validation on the final answer; tenant-scoped queries on every
  run/event/trace access; trajectory eval assertions.

Not yet implemented (tracked residual, operational follow-ups): the **global kill switch**,
the **checkpoint retention/purge** job (30/90-day policy recorded, not automated), and
**load / denial-of-wallet** tests. The "in-process framework/library defect" residual now
concretely includes LangGraph, which is confined to the planning-decision seam behind
`AGENT_PLANNER` (default deterministic) and cannot reach durable state, tenancy, or the
tool boundary except by proposing a decision the runtime independently re-validates.
