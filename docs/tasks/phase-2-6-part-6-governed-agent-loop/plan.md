# Task Plan: phase-2-6-part-6-governed-agent-loop

## Task summary

Implement P2.6.6, the advanced governed agent loop: a versioned structured decision schema (action
kind, pinned role, schema-constrained arguments), bounded redacted observation summaries for the
planner, explicit `verify` and safe terminal/escalation decisions, policy-bounded repeated
retrieval/tool use under per-role call caps, repeated-action and convergence guards, and a global
fail-closed runtime kill switch. Every planner proposal remains untrusted input; the runtime
re-validates kind, role, arguments, budgets and approval state server-side against the immutable
compiled agent config and the Sprint 9 tool proxy before anything executes.

## Background

The Sprint 10 agent runtime already provides the durable, bounded, deny-by-default loop this part
extends:

- `apps/agents/planner.py` defines the only pluggable intelligence seam: flat decision kinds
  `retrieve`/`tool`/`respond` (`AgentDecision(kind, role, reason_code)`), a minimal
  `AgentObservation(objective, retrieved, tools_called)`, the default `DeterministicPlanner`
  (retrieve once, each allowlisted role once, respond) and the optional `AGENT_PLANNER` LangGraph
  adapter. CI runs the deterministic planner only.
- `apps/agents/runtime.py` re-checks cancellation/deadline/step cap every iteration, validates every
  decision (`AGENT_DECISION_INVALID` for unknown kinds, allowlist check for tool roles), routes tool
  use exclusively through the Sprint 9 proxy/approval boundary (idempotency key
  `agent:<run_id>:<step>`, request-checksum binding, `waiting_approval` pause with durable
  checkpoint), counts tokens/tool calls against `apps/agents/limits.py` hard caps, bounds the
  checkpoint at 2 MiB, guards resume with `CHECKPOINT_SCHEMA_VERSION`, and honours the P2.6.5
  composition claim by lowering `max_steps` to the call-site `max_decisions`.
- `apps/agents/agent_schema.py` validates the `agent_definition` artifact (data, not code): `tools`
  binding-role allowlist plus optional `retrieval`, `limits`, `objective_key`, `output_key`,
  `system_prompt`.

Gaps this part closes (frozen by P2.6.0; S06 is the reference scenario): planner proposals carry no
schema-constrained arguments; there is no governed `verify` step or safe escalation terminal; a role
can never be legitimately repeated (and repetition is not detected as an attack signal either);
observation content given to the planner is neither versioned nor budgeted; and the Sprint 10
follow-up global start/resume kill switch is still missing. P2.6.4 supplies the failure
classification and `outcome_unknown` semantics that verification must respect; P2.6.5/ADR-0009
supply the `allowed_actions` attenuation that must extend to the new decision kinds.

## Scope

- Define `AGENT_DECISION_SCHEMA_VERSION = 2`: a structured decision object with exact keys
  `schema_version`, `kind`, optional `role`, optional bounded `arguments`, `reason_code`. Unknown
  keys, unknown kinds, missing/foreign roles and malformed arguments fail closed with stable codes.
- Extend the decision-kind allowlist to `retrieve`, `tool`, `verify`, `respond`, `escalate`. New
  kinds are reachable only when the authored agent opts in; existing definitions and already
  compiled releases keep byte-identical behavior and stable checksums.
- Validate `arguments` twice: at the runtime boundary against the pinned tool input contract,
  P2.6.1 protected-namespace rules and bounded size, then again inside the Sprint 9 proxy
  (contract, field allowlist, risk/approval, size). The runtime never builds authority from
  planner-supplied values.
- Restrict `verify` to explicitly declared no-side-effect observation actions: pinned retrieval or
  a compiled subset of tool roles whose pinned definitions declare no side effects. The compiler
  rejects a verification role with side effects or approval requirements that would make
  verification itself a side-effecting action.
- Add `escalate` as a safe terminal decision: the run ends in a distinct auditable outcome
  (`AGENT_ESCALATED`) carrying a bounded platform-owned escalation envelope (stable reason code plus
  bounded redacted summary), never an uncontrolled free-text channel.
- Add optional authored action policy (additive artifact keys): per-role call caps bounded by the
  global `MAX_TOOL_CALLS`, an explicit repeat-retrieval allowance and the verification-role subset.
  Defaults reproduce current single-use behavior.
- Compile the decision schema version, action policy, per-role caps and verification subset into the
  immutable checksummed agent config; the release compiler continues to fail closed on unresolved
  roles.
- Give the planner bounded, redacted, versioned observation summaries (retrieval/tool/verification
  results) under per-observation and total byte budgets. Signed execution context, capability sets,
  secret references, hidden authorization state and chain of thought are never included and never
  persisted.
- Add repeated-action detection using a canonical checksum of `(kind, role, arguments)`: an
  identical already-succeeded action is denied unless policy and the per-role cap admit repeats;
  approval resume of the same step is exempt. Bounded consecutive invalid/denied proposals terminate
  the run (`AGENT_NO_PROGRESS`).
- Enforce per-role call budgets transactionally alongside the existing global step/tool/token/
  deadline caps; composition (`agent_call`) attenuation intersects `allowed_actions` with the new
  kinds so an older compiled envelope denies `verify`/`escalate` by default.
- Add a durable DB-backed fail-closed runtime kill switch with global and per-organization scope,
  instantly effective without a deploy/restart, enforced at task claim and at approval resume: when
  suspended, no agent step executes, the denial is audited with a stable code (`AGENT_SUSPENDED`)
  and in-flight database state is preserved for later resume. This part ships the control record,
  enforcement and audited role-gated suspend/resume management commands; the console button for the
  same control is P2.6.11 scope.
- Bump `CHECKPOINT_SCHEMA_VERSION` to 2 for the extended durable trail (per-role counters, action
  checksums, bounded observation summaries, verification outcomes); v1 checkpoints are never
  resumed by new code (existing `AGENT_CHECKPOINT_INCOMPATIBLE` guard plus the separately approved
  reset procedure for disposable dummy runs).
- Update `DeterministicPlanner` and the LangGraph adapter to emit schema v2 and exercise
  observe–act–verify–escalate deterministically; the deterministic planner remains the default and
  CI stays hermetic.
- Persist the decision/verification trail redacted in existing `AgentRunEvent`/checkpoint
  structures so P2.6.11 eval assertions and trace rendering can consume it without new tables.
- Deliver executable S06 incident fixtures proving observe, governed action, approval wait, verify,
  escalate/conclude and every critical denial.

## Non-goals

- Multi-agent supervision, delegation or peer negotiation (Phase 3).
- Live model-backed planner activation: `AGENT_PLANNER` remains the deployment-gated selection seam;
  no live egress, provider credential or endpoint is added and CI keeps the deterministic planner.
- Any change to Sprint 9 tool proxy authority, approval semantics, request-checksum binding or
  separation of duties; P2.6.6 only adds earlier revalidation, never replaces the proxy's.
- Automatic compensation from agent verification: `verify` observes and reports; compensation
  semantics remain P2.6.4 workflow contracts, and an ambiguous external outcome is never retried.
- New eval assertion vocabulary, Studio palette/config UI and operations dashboards (P2.6.11 owns
  them; this part only persists the durable evidence they will read).
- New public API endpoints, response-shape changes to `/v1/invoke` / `/v1/runs/{id}`, or new
  consumer capabilities.
- New production dependencies, new workflow grammar, or model-created tools/roles/approvals.

## Acceptance criteria

1. Decision schema v2 is closed and versioned: unknown keys/kinds/roles, schema-version mismatch,
   oversized or non-contract arguments and protected-namespace writes fail closed with stable
   content-free codes.
2. Planner output remains proposal-only: every kind is allowlist-checked, every role must be inside
   the immutable compiled allowlist, and every argument set passes the pinned tool contract at the
   runtime boundary and again at the proxy. A planner cannot widen tools, skip approval, raise a
   cap or reach an unpinned destination.
3. `verify` executes only compiled no-side-effect observation actions; a side-effecting or
   approval-requiring role is rejected at author/compile time as a verification role.
4. `escalate` terminates the run in a distinct audited outcome with a bounded platform-owned
   envelope; it cannot bypass the output contract path for normal `respond` results and cannot leak
   raw observation or provider content.
5. Repeat retrieval/tool use executes only when authored policy and per-role caps admit it;
   per-role budgets, the global step/tool/token/deadline caps and composition `max_decisions`
   attenuation are all enforced; exhaustion terminates deterministically with the existing stable
   codes.
6. Repeated-action detection denies an identical already-succeeded `(kind, role, arguments)`
   checksum outside policy, approval resume is exempt, and bounded consecutive invalid proposals
   terminate as `AGENT_NO_PROGRESS`; late or duplicate Celery delivery cannot double-execute a side
   effect (existing idempotency preserved).
7. Approval pause/resume keeps its invariants under schema v2: request-checksum binding, expiry,
   rejection fail-closed, `waiting_approval` checkpoint durability and resume of the exact approved
   step only.
8. Planner-visible observations respect per-observation and total byte budgets and redaction; the
   signed execution context, capabilities, secret references and chain of thought never appear in
   planner input, checkpoints, events, logs or audit.
9. The kill switch takes effect without a restart at both global and organization scope: new
   starts and approval resumes are denied fail closed with audited `AGENT_SUSPENDED`, durable run
   state is preserved and clearing it allows normal resume; suspending one organization provably
   leaves others running, and flipping the switch is a role-gated audited platform-operator action
   denied to unauthorized actors.
10. Compatibility: existing agent definitions, compiled releases and workflow `agent_call`
    envelopes execute unchanged; recompiling an unchanged body yields an unchanged checksum; v1
    checkpoints are refused by the version guard rather than reinterpreted.
11. S06 fixtures prove the full observe–act–approve–verify–escalate/conclude journey plus the
    critical denials: invented tool/ref, prompt-injected instruction in retrieved/tool content,
    repeated side effect, budget exhaustion, forged/replayed resume and cross-tenant access.
12. Applicable formatter, lint, type, Django, migration-drift, SQLite, PostgreSQL non-owner/RLS and
    Celery redelivery/restart checks pass with recorded evidence, and staff-engineering,
    application-security and SRE reviews of the final diff are recorded.

## Affected components

- `apps/agents/planner.py`: schema v2 decision/observation contracts, deterministic planner update,
  planner protocol.
- `apps/agents/runtime.py`: decision validation, verify/escalate execution, repeat/convergence
  guards, per-role budgets, observation budgeting, kill-switch enforcement at resume.
- `apps/agents/tasks.py` / `apps/agents/services.py`: kill-switch enforcement at claim/start,
  terminal outcome handling.
- `apps/agents/models.py` + one additive migration and management commands: the platform/
  organization-scoped runtime control record with audited suspend/resume operations.
- `apps/agents/limits.py`: new bounded constants (observation budgets, per-role cap ceiling,
  no-progress threshold) and `CHECKPOINT_SCHEMA_VERSION = 2`.
- `apps/agents/agent_schema.py` + `apps/agents/compiler.py`: additive action-policy keys,
  verification-role validation, compiled schema-version/policy pinning.
- `apps/agents/langgraph_planner.py`: adapter parity with schema v2 (still optional, still no
  socket in CI).
- Release compiler seam (`apps/releases`): no contract change expected beyond compiled agent config
  content; fail-closed role resolution re-verified.
- `apps/tools` proxy: consumed unchanged; contract tests assert the second validation layer still
  holds.
- S06 fixtures/tests, `apps/agents/tests`, observability event emission and documentation.

## Interfaces affected

No public API surface changes. The unreleased `agent_definition` artifact gains optional additive
spec keys for action policy (per-role call caps, repeat-retrieval allowance, verification roles);
exact key names are frozen at implementation step 2 and validated with exact-key checking. Compiled
agent configs gain `decision_schema_version` and the compiled policy. New stable content-free codes
are added alongside the existing `AGENT_*` family: `AGENT_ARGUMENTS_INVALID`,
`AGENT_ROLE_BUDGET_EXCEEDED`, `AGENT_REPEATED_ACTION`, `AGENT_NO_PROGRESS`, `AGENT_ESCALATED`,
`AGENT_SUSPENDED` (final names confirmed against the existing code registry during implementation).
`GET /v1/runs/{id}` keeps its response shape; escalation surfaces through the existing safe
status/error-code fields. New role-gated audited management commands operate the kill switch
(indicative names `suspend_agent_runtime` / `resume_agent_runtime`; final names frozen at
implementation step 2); the console surface for the same control lands in P2.6.11.

## Data impact

One small additive table is expected for the DB-backed kill-switch control record (owner decision,
2026-07-17): a platform-owned global row plus per-organization rows carrying direct organization
lineage under the standard tenant provisioning pattern. The durable decision trail otherwise
extends existing JSON structures: the run checkpoint
(schema version 2, still capped at `MAX_CHECKPOINT_BYTES`) and append-only `AgentRunEvent` payloads
(bounded, redacted decision/verification metadata — kinds, roles, checksums, reason codes, byte
counts; never raw observation content, arguments containing sensitive data are stored as checksums
plus bounded redacted summaries). If implementation discovers a genuinely required durable field, it
is an additive migration allocated by the integration owner. Observation summaries
may contain confidential tenant data and live only in the bounded checkpoint/state locations already
classified for run state, with existing run-evidence retention (P2.6.11 owns retention closure).

## Security impact

The agent loop is the platform's largest prompt-injection and cost-amplification surface: planner
input now includes retrieval/tool content that may embed hostile instructions, and repetition policy
deliberately relaxes the single-use guarantee. The design keeps every authority decision
server-side, adds argument-level contract validation before the unchanged proxy boundary, makes
repetition an explicit bounded policy instead of an accident, and adds detection plus a kill switch
for runaway loops. See [threat-model.md](threat-model.md).

## Authorization impact

No authentication or consumer-capability change. Planner decisions remain proposals with zero
authority: tool/verify execution re-authorizes through the release-pinned binding, proxy capability,
field allowlists, risk/approval and tenant scope exactly as today. The `agent_call` composition
envelope's closed `allowed_actions` subset now intersects the expanded kind set, so a parent
compiled before P2.6.6 denies the new kinds by default (fail-closed, ADR-0009-consistent). The kill
switch is a role-gated platform-operator control (owner-approved 2026-07-17): flipping global or
per-organization suspension is an audited action restricted to platform-admin scope and denied by
default to scenario authors, organization admins and consumers; suspension of one organization is
provably isolated from others. This part delivers the management-command surface; the console
action lands in P2.6.11 under the same authorization.

## Observability impact

New stable events: decision validated/denied (kind, role, reason code), verification outcome
(verified/failed/inconclusive as codes), escalation, repeat-action denial, no-progress termination,
kill-switch denial. Existing counters `agenthub_agent_runs_total` / `agenthub_agent_steps_total`
gain only bounded label values (decision kind, stable outcome code); tenant/run/role identifiers
stay in logs/traces/audit, never metric labels. Security-relevant denials (repeat, suspension,
argument rejection, escalation) audit fail-closed with actor/tenant/run references, action,
decision, outcome and trace ID; optional telemetry stays fail-open. No prompt, observation body,
argument content or chain of thought is logged.

## Migration impact

One forward-only additive migration is planned for the kill-switch control record
(integration-owner allocation; organization-scoped rows follow the ADR-0004 FORCE RLS provisioning
pattern). `makemigrations --check --dry-run` must otherwise stay clean; any further late-discovered
additive migration goes through the same allocation. The checkpoint schema version bump is a code
constant, not a migration, and old-version checkpoints are refused rather than migrated (the
product is unreleased; dummy in-flight runs are handled only by the separately approved reset
procedure).

## Dependencies

- Merged and verified P2.6.0 contracts (S06 corpus, decision-kind list), ADR-0008/0009/0010.
- Merged and verified P2.6.1 (protected namespaces/pointer rules reused for argument validation),
  P2.6.4 (failure classes, `outcome_unknown` discipline) and P2.6.5 (composition attenuation seam).
- Sprint 9 tool proxy/approval invariants and Sprint 10 agent runtime (unchanged authority).
- Integration-owner coordination for shared `apps/agents` seams; no shared workflow state-machine
  file is edited concurrently with another open branch.

## Implementation steps

1. Re-inspect the merged agent runtime/planner/compiler/tool-proxy seams and the P2.6.5
   composition claim handling on the current integration head; update this plan if reality differs.
2. Freeze the exact artifact policy keys, decision schema v2 field set, observation byte budgets,
   per-role cap ceiling, no-progress threshold, escalation envelope schema and the kill-switch
   control-record/command shape; record them in this plan (or a short ADR only if ADR-0009/0010
   must materially change).
3. Implement schema v2 decision/observation contracts in `planner.py` with exhaustive validation
   tests (unknown keys/kinds, size bounds, version mismatch).
4. Extend `agent_schema.py` + `compiler.py` with additive action policy and verification-role
   validation; prove checksum stability for unchanged bodies and release-compile fail-closed
   behavior for unresolved verification roles.
5. Implement runtime argument validation against the pinned tool contract and protected-namespace
   rules before the proxy call; add negative tests proving the proxy still re-validates.
6. Implement `verify` execution over pinned retrieval/no-side-effect roles and the bounded
   verification outcome trail.
7. Implement `escalate` terminal handling, the platform-owned envelope and its audit/event path.
8. Implement per-role budgets, repeat policy, repeated-action checksum detection (approval-resume
   exempt) and the no-progress guard; bump the checkpoint schema version and extend `_persist_step`
   durability tests.
9. Implement observation summarization/budgeting with redaction tests (secret refs, context,
   capability fields never present).
10. Implement the DB-backed kill switch: additive migration (global + per-organization control
    rows with RLS provisioning), claim/resume enforcement with audited fail-closed denial, and the
    audited role-gated suspend/resume management commands.
11. Update the deterministic planner (default) and LangGraph adapter to schema v2, including an
    S06-shaped deterministic observe–act–verify–escalate trajectory; keep CI hermetic.
12. Add S06 executable fixtures and the full negative matrix (injection, invented refs, repeats,
    budgets, replay, cross-tenant, suspension).
13. Run the full gate set (format, ruff, mypy, Django checks, migration drift, SQLite full suite,
    PostgreSQL non-owner/RLS profile, Celery redelivery/restart smoke); record evidence in
    `verification.md`.
14. Review the final diff as staff engineer, application-security engineer and SRE; update
    AGENTS.md verified state and the phase plan status in the landing change.

## Test plan

- Schema/compiler: exact-key and bound enforcement for policy keys, verification-role side-effect
  rejection, checksum stability for unchanged bodies, deterministic compiled output.
- Decision validation: unknown kind/role/keys, schema-version mismatch, argument contract
  violations, protected-namespace writes, oversized arguments; each yields its stable code.
- Proxy layering: runtime-accepted arguments that violate the binding contract are still rejected
  by the proxy (defense in depth proven, not assumed).
- Verify/escalate: verification over retrieval and no-side-effect tool roles, inconclusive
  outcomes, escalation envelope bounds, audit content, and denial of side-effecting verification.
- Repeat/convergence: policy-admitted repeats within caps, denial beyond caps, identical-action
  checksum denial, approval-resume exemption, no-progress termination, exhaustion of every budget
  (steps, tool calls, per-role, tokens, deadline, checkpoint size, composition `max_decisions`).
- Approval invariants under v2: pause, durable checkpoint, request-checksum binding, expiry,
  rejection fail-closed, resume-exact-step, duplicate/late Celery delivery idempotency.
- Prompt injection: hostile instructions embedded in retrieval/tool observation fixtures cannot add
  roles, skip approval, alter budgets or reach unpinned destinations.
- Kill switch: instant start/resume denial without restart at global and organization scope, audit
  content, state preservation, recovery after clearing, organization isolation (suspending one
  organization leaves others running), unauthorized-actor and cross-tenant flip denial, and
  PostgreSQL non-owner/RLS coverage for the control rows.
- Checkpoint compatibility: v1 checkpoint refused (`AGENT_CHECKPOINT_INCOMPATIBLE`); terminal runs
  untouched.
- Cross-tenant/authorization: foreign-tenant run access, foreign binding roles and composition
  `allowed_actions` attenuation all deny; PostgreSQL non-owner/FORCE RLS coverage for touched
  tenant-owned rows.
- Compatibility: Sprint 10 regression suite unchanged for legacy definitions; LangGraph adapter
  parity tests without sockets.
- Observability/audit: event completeness, redaction, bounded metric labels, fail-closed required
  audit.
- Repository gates: `ruff format --check`, `ruff check`, `mypy`, `manage.py check`,
  `makemigrations --check --dry-run`, full SQLite pytest, PostgreSQL profile per the manual-testing
  guide, Celery restart/redelivery smoke.

## Rollout plan

- Land compatibility-default: new kinds/policies activate only for agents that author them; no
  existing release changes behavior and no capability gate flips by default.
- Keep the deterministic planner as default everywhere; any model-backed planner selection stays a
  deployment decision outside this task.
- Before enabling authored verify/escalate/repeat policies for a real organization: dashboards for
  step/tool/budget/kill-switch activity (P2.6.11), eval coverage over S06, and operator awareness of
  the kill switch.
- The kill-switch commands are documented in the runbook with their audit signatures before first
  production-like use.

## Rollback plan

- Behavioral rollback: suspend starts/resumes via the kill switch, then disable authored policies by
  reverting the artifacts/releases that opted in (immutable history preserved).
- Code rollback is safe at the runtime boundary: the checkpoint version guard prevents old code
  from resuming v2 checkpoints and new code from resuming v1; affected non-production dummy runs
  are handled by the separately approved reset procedure, never by reinterpreting checkpoints.
- No migration to roll back is planned; if one lands, it is additive and stays (forward-fix only).

## Risks

- Argument schemas widen the planner-to-tool channel; a validation gap could enable
  mass-assignment or exfiltration despite the proxy (mitigated by dual validation + tests).
- Repetition policy can amplify cost or repeat a side effect if per-role caps, idempotency keys or
  the repeated-action checksum are wrong.
- Observation summaries can leak secrets/authorization state if redaction misses a path.
- Escalation could become an unbounded free-text exfiltration channel without a closed envelope.
- Kill-switch enforcement gaps (e.g., resume path) would leave runs uncontrollable in an incident.
- Checkpoint schema bump can strand in-flight runs; acceptable only because data is disposable and
  the guard fails closed.
- Deterministic-planner changes can silently alter existing test expectations; Sprint 10 regression
  must stay green unmodified.
- Concurrent Phase 2.6 branches touching `apps/agents` would conflict; this part assumes exclusive
  ownership during its window.

## Open questions

1. Exact artifact policy key shape (`spec.actions` block versus extended `tools` entries) and the
   per-role cap ceiling relative to `MAX_TOOL_CALLS`.
2. Observation budgets: proposed ≤ 4 KiB per observation and ≤ 32 KiB total planner context —
   owner confirmation needed.
3. Escalation envelope: platform-owned closed schema (recommended) versus tenant output-contract
   validation, and how consumers/workflows route on `AGENT_ESCALATED` before P2.6.11 assertions.
4. Kill-switch mechanism: settings/env global switch (recommended minimum, no migration) versus an
   additional org-scoped audited console action (would need its own approval and possibly an
   additive table; may defer to P2.6.11 operations closure).
5. No-progress threshold (proposed 3 consecutive invalid/denied proposals) and whether verification
   `inconclusive` counts toward it.
6. Whether S06 needs a minimal new trajectory eval assertion in this part or all assertion
   vocabulary waits for P2.6.11 (recommended: pytest-only here).

## Resolved decisions (2026-07-17)

Owner review closed part of the open questions; numbering refers to the list above.

- **(2) Observation budgets — accepted.** ≤ 4 KiB per observation summary and ≤ 32 KiB total
  planner context become hard ceilings alongside the existing `limits.py` caps. Clarified with the
  owner that the consumer is the runtime agent decision planner (`apps/agents/planner.py`), not the
  P2.6.9 Studio scenario generator. Owner condition: the budget must carry enough context for the
  decision; if a bounded summary proves insufficient in practice, raising the ceiling is a normal
  reviewed limits change, not a contract redesign.
- **(3) Escalation envelope — option A accepted.** The escalation terminal uses a platform-owned
  closed schema (stable reason code plus bounded redacted summary). The tenant release output
  contract applies to `respond` only; consumers and P2.6.4 error routes dispatch on the stable
  `AGENT_ESCALATED` code.
- **(4) Kill switch — option B chosen by the owner (2026-07-17).** After the incident walkthrough,
  the owner selected the durable operator-actionable control over the env-only variant: a DB-backed
  switch with global and per-organization scope, instantly effective without a deploy/restart,
  flipped only by an audited role-gated platform-operator action. P2.6.6 delivers the control
  record (one additive migration), claim/resume enforcement and audited suspend/resume management
  commands; the console button for the same control moves to P2.6.11. Option A (settings/env) is
  rejected as too slow for incident response.
- Questions (1), (5) and (6) remain open with recommendations and are frozen at implementation
  step 2 per the plan.

## Frozen contract (implementation step 2, 2026-07-17)

Closes the remaining open questions and fixes the exact shapes the implementation binds to.

- **(1) Action-policy artifact shape — dedicated `spec.actions` block.** The `agent_definition`
  spec gains one optional, exact-key `actions` object (never extended `tools` entries):
  `{"verify_roles": [<role>], "repeat_retrieval": <bool>, "escalation_enabled": <bool>,
  "role_call_caps": {<role>: <int 1..MAX_ROLE_CALLS>}}`. Every key is optional; all four default to
  the current single-use behavior (`[]`, `false`, `false`, `{}`). `verify_roles` members must each be
  a declared `tools` role or the literal `"retrieval"` (allowed only when `retrieval.enabled`).
  `role_call_caps` keys must be declared `tools` roles. **Per-role cap ceiling `MAX_ROLE_CALLS =
  MAX_TOOL_CALLS = 10`**; a per-role cap can only lower, never raise, the global tool-call budget.
- **Checksum stability rule.** The compiler emits the compiled `actions` block **only when
  `spec.actions` is authored**. Agents without it keep a byte-identical compiled config and stable
  checksum. The decision schema version is a runtime/planner constant (`AGENT_DECISION_SCHEMA_VERSION
  = 2`) carried on each proposal and re-validated server-side; it is not written into legacy compiled
  configs (which would break unchanged-body checksums). The durable checkpoint version bump
  (`CHECKPOINT_SCHEMA_VERSION = 2`) handles resume compatibility.
- **Decision schema v2.** `AgentDecision(schema_version=2, kind, role="", arguments=None,
  reason_code="")`. `kind ∈ {retrieve, tool, verify, respond, escalate}`. `arguments` is an optional
  bounded mapping (≤ `MAX_ARGUMENTS_BYTES = 4 KiB`, no protected-namespace keys). A dict-form proposal
  from an adapter is parsed with exact-key validation. **Hard, immediate fail** (untrusted planner
  emitting garbage): unknown key/kind, `schema_version` mismatch, role not in the compiled allowlist,
  `verify`/`escalate` not policy-enabled, non-dict/oversized/protected-namespace `arguments`. **Soft,
  no-progress-counted denial** (bounded, planner may self-correct): repeated identical action outside
  policy, per-role budget exceeded.
- **(5) No-progress guard — `NO_PROGRESS_LIMIT = 3`.** After 3 consecutive soft-denied proposals the
  run terminates deterministically with `AGENT_NO_PROGRESS`. Any executed action resets the counter.
  A `verify` `inconclusive` outcome is a legitimate result and does **not** count toward no-progress.
- **(6) S06 coverage — pytest only in this part.** No new eval-assertion vocabulary or Studio/console
  UI here; P2.6.11 owns those. This part persists the durable decision/verification trail they read.
- **Observation summaries — code/count only.** Planner-visible summaries carry only bounded
  identifiers, stable codes and counts (`{"kind","role"?,"outcome"|"status"?,"count"|"bytes"}`),
  never raw retrieval/tool text, arguments, secret refs, execution context, capabilities or chain of
  thought. Budgets: `MAX_OBSERVATION_BYTES = 4 KiB` per summary, `MAX_OBSERVATION_CONTEXT_BYTES =
  32 KiB` total (oldest dropped past the ceiling). This makes redaction structural and deterministic;
  enriching summaries for a future model planner is a separate reviewed limits change.
- **Escalation envelope — closed, code/count only.** `{"reason_code": <stable id, ≤64 chars,
  identifier charset>, "steps": <int>}`. No free text. Surfaces as a terminal run with
  `status=failed` + `error_code=AGENT_ESCALATED` (migration-free; `/v1/runs/{id}` shape unchanged);
  consumers and P2.6.4 error routes dispatch on the `AGENT_ESCALATED` code, and a composed child
  propagates it as the `WorkflowChildLink` reason code.
- **(4) Kill switch — `AgentRuntimeControl`.** One additive table, `organization` **nullable**
  (`NULL` = global). Manual RLS: `USING (organization_id IS NULL OR
  agenthub_tenant_scope_contains(organization_id))`, same `WITH CHECK`. Enforcement queries filter
  explicitly (`organization IS NULL OR organization_id = <run org>`, `suspended=True`) so it is
  correct under both the RLS-bypassing owner (CI/local) and a non-owner production role. Enforced at
  Celery task claim and at approval resume; a suspended run stays durable and resumable. Flipped only
  by the role-gated audited management commands `suspend_agent_runtime` / `resume_agent_runtime`.
- **New stable codes:** `AGENT_DECISION_SCHEMA_MISMATCH`, `AGENT_ARGUMENTS_INVALID`,
  `AGENT_VERIFY_NOT_ALLOWED`, `AGENT_ESCALATE_NOT_ALLOWED`, `AGENT_ROLE_BUDGET_EXCEEDED`,
  `AGENT_REPEATED_ACTION`, `AGENT_NO_PROGRESS`, `AGENT_ESCALATED`, `AGENT_SUSPENDED`.

## Status

**Implemented and verified (2026-07-17).** Schema v2, additive `spec.actions` policy, verify/escalate,
per-role budgets, repeated-action + no-progress guards, bounded redacted observations, composition
attenuation for the new kinds, and the DB-backed fail-closed kill switch are implemented as a
compatibility-default increment (legacy compiled agents keep byte-identical configs/checksums). Static
gates, the full SQLite suite (926 passed / 35 skipped), the PostgreSQL affected-app profile
(163 passed, incl. composition FORCE-RLS) and a PostgreSQL non-owner RLS proof of the control table
pass. Evidence and the residual real-broker Celery smoke gap are recorded in
[`verification.md`](verification.md). Written against integration head `b8b6ca7`.

## Completion criteria

`Implemented` when schema v2, verify/escalate, repeat policy/guards, observation budgeting and the
kill switch form a compatibility-default complete increment with S06 fixtures. `Verified` only with
recorded SQLite + PostgreSQL non-owner/RLS + Celery redelivery/restart evidence, the full negative
security matrix and recorded staff/security/SRE review. `Completed` after AGENTS.md verified state,
the Phase 2.6 plan status and master plan are updated and the integration owner accepts the merge
per the [Definition of Done](../../ai/definition-of-done.md).
