# Threat Model: phase-2-6-part-6-governed-agent-loop

## Assets

- Tool execution authority (release-pinned binding roles, side-effecting external actions).
- Tenant documents/retrieval results and tool outputs (confidential business data).
- Approval integrity: separation of duties, request-checksum binding, expiry.
- Compute/cost budgets: model tokens, tool calls, Celery capacity, checkpoint storage.
- Durable run state, decision trail and audit evidence (integrity and confidentiality).
- Signed execution context, capability sets and `secret:<name>` references (must never reach the
  planner or persisted observations).

## Actors

- Consumer principals invoking agent scenarios through the gateway (authenticated, tenant-scoped).
- The planner (deterministic, LangGraph adapter, or a future model-backed adapter): untrusted
  proposal source by design.
- Content authors of retrieved documents and external tool responders: untrusted, possibly hostile
  (prompt-injection vector).
- Scenario authors writing agent definitions/action policies (tenant-trusted, platform-bounded).
- Platform operators (kill switch, approvals) and hostile cross-tenant actors.

## Entry points

- `POST /v1/invoke` (existing gateway auth/capability path; unchanged surface).
- Planner adapter boundary (`AGENT_PLANNER`) returning structured decisions.
- Observation content entering planner input from retrieval and tool outputs.
- Celery task delivery (at-least-once, forgeable ordering/duplication, not authorization).
- Approval decision signal resuming a paused run.
- Kill-switch operator surface (audited management commands now, console action in P2.6.11) and
  the DB control record it writes.

## Trust boundaries

- Planner ↔ runtime: every decision is untrusted; kind/role/argument/schema-version validation and
  budget checks happen server-side before any effect.
- Runtime ↔ tool proxy: unchanged Sprint 9 boundary; runtime pre-validation is additive, the proxy
  remains authoritative (capability, contract, field allowlist, risk/approval, egress).
- Observation content ↔ planner: data, never instruction with authority; summaries are bounded and
  redacted before crossing.
- Execution context/composition claim: server-signed; planner and state cannot alter it.
- Operator kill switch ↔ runtime: fail-closed control plane, audited.

## Data classifications

- Observation summaries and arguments: confidential tenant data; bounded, checkpoint-only, redacted
  in events/audit (checksums + reason codes).
- Decision metadata (kinds, roles, codes, checksums): internal-safe, auditable.
- Execution context, capabilities, secrets: restricted; excluded from planner input and all
  persistence added by this part.
- Escalation envelope: bounded platform-owned schema, safe for operator display.

## Authentication

Unchanged: gateway bearer-token consumer auth; operator actions use the existing console/management
paths. The kill switch is flipped only through authenticated, role-gated operator surfaces
(management commands in this part, console action in P2.6.11), never anonymously or via settings
alone.

## Authorization

Deny by default. The compiled agent config is the only tool/verification allowlist; per-role caps
and decision kinds are compiled and immutable; `agent_call` `allowed_actions` intersects the new
kinds (old envelopes deny `verify`/`escalate`). The proxy re-authorizes every tool action
(object/action/tenant/field). Planner text, observation content, workflow state and broker payloads
are never authorization inputs.

## Tenant isolation

Runs, checkpoints, events and tool invocations stay organization-scoped with existing FORCE
RLS/tenant-scope mechanisms; no new tenant-owned table is planned. Retrieval remains pinned to the
release's document-set versions (P4 ACL). Cross-tenant run access, foreign roles and foreign
approval decisions must stay denied under PostgreSQL non-owner coverage.

## External systems

Tool egress only through the existing SSRF-safe adapters behind the proxy; retrieval only through
the pinned provider seam. This part adds no live egress, no new destination class and no new
dependency; CI stays deterministic (no socket).

## Abuse cases

- Prompt injection in a retrieved document or tool output instructs the planner to call an
  unpinned tool, repeat a payment-like action, exfiltrate state via arguments, or self-approve.
- Malicious/compromised planner emits schema-valid but hostile decisions: protected-namespace
  writes, oversized arguments, unbounded repeats, forced escalation loops.
- Argument crafting for mass assignment or exfiltration through a tool contract gap.
- Cost amplification: repeat policy abused to burn tokens/tool calls; convergence never reached.
- Replay/duplication: duplicated Celery delivery or replayed approval resume re-executing a side
  effect; input swap after approval (defeated by request-checksum binding).
- Verification abuse: declaring a side-effecting tool as a verification role to execute unapproved
  effects under the `verify` label.
- Escalation channel abuse: smuggling raw sensitive content through the terminal envelope.
- Cross-tenant probing via invented roles/refs expecting differential errors.
- Kill-switch abuse: an unauthorized actor suspending the fleet (denial of service), one
  organization suspending another, or an operator resuming a deliberately suspended runtime
  without authority; every flip must be role-gated and audited.

## Failure cases

- Provider/tool timeout or `outcome_unknown` mid-loop: never blind-retried; existing dispatched-
  but-unconfirmed discipline holds.
- Worker crash between step persist and ACK: at-least-once redelivery converges idempotently.
- Checkpoint version mismatch after deploy: refuse resume (fail closed), no reinterpretation.
- Kill switch active during approval resume: denial preserved durably, resumable later.
- Observation budget exceeded: bounded truncation by rule, or fail closed — never unbounded
  persistence.
- Audit persistence failure on a security decision: fail closed (transaction bound).

## Logging and audit risks

- Observation bodies, arguments, prompts or chain of thought leaking into events, logs, traces or
  metric labels (must remain checksums/codes/counts).
- Escalation reasons carrying raw provider/content text.
- High-cardinality metric labels from roles/run IDs.
- Missing audit for repeat denial, suspension or argument rejection (security decisions are
  fail-closed audited).

## Mitigations

- Closed versioned decision schema with exact-key validation and stable content-free codes.
- Dual argument validation (runtime contract + protected namespaces, then unchanged proxy
  authority) — defense in depth proven by tests.
- Compiled-only allowlists: roles, verification subset, per-role caps, decision kinds; immutable
  and checksummed per release.
- Repeated-action checksum guard, per-role budgets, global caps, no-progress termination, deadline
  and checkpoint-size ceilings; composition attenuation intersects everything.
- Approval invariants preserved: request-checksum binding, expiry, exact-step resume exemption.
- Bounded redacted observation summarization; exclusion list tested (context, capabilities,
  secrets, CoT).
- Platform-owned closed escalation envelope.
- DB-backed fail-closed audited kill switch (global + per-organization) enforced at claim and
  resume; flipping is a role-gated audited platform-operator action with organization isolation
  and no restart dependency.
- Idempotency keys `agent:<run_id>:<step>` unchanged; terminal-state guards against late results.

## Residual risks

- A model-backed planner (when a deployment enables one) sees bounded tenant observation content by
  design; profile/egress governance for that provider is a deployment decision outside this part.
- Semantic injection cannot be fully eliminated: within its compiled allowlist and caps, a deceived
  planner can still choose a permitted-but-suboptimal governed action; bounds limit blast radius.
- The console button for the kill switch arrives only in P2.6.11; until then incident response
  uses the audited management-command path, which requires shell/deploy access to the environment.
- Repeat policy correctness depends on tool idempotency declarations authored in Sprint 9 bindings;
  a falsely-declared-idempotent external tool remains a tenant-authored risk surface.

## Required security tests

- Injection fixtures (retrieval + tool content) proving no allowlist/approval/budget bypass.
- Malicious-planner suite: every invalid decision class, protected-namespace writes, oversized
  arguments, invented roles/refs, forced-repeat and escalation-loop attempts.
- Proxy-layer re-rejection of runtime-passed hostile arguments.
- Replay/duplicate delivery, approval input-swap, expired/foreign approval, resume-wrong-step.
- Side-effecting verification-role rejection at author/compile time.
- Cross-tenant run/role/approval denial under PostgreSQL non-owner/FORCE RLS.
- Kill-switch tests: start/resume denial with audit assertions, unauthorized-actor flip denial,
  organization isolation and PostgreSQL non-owner/RLS coverage of the control rows.
- Redaction assertions over events, logs, checkpoints, metrics labels and escalation envelopes.
- Budget-exhaustion matrix (steps, tool calls, per-role, tokens, deadline, state size,
  `max_decisions`).
