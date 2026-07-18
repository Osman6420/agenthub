# Task Plan: phase-2-6-part-11-product-operational-closure

## Task summary

Close Phase 2.6 as a product: expose every verified orchestration node family in Scenario Studio
with diagnostics and Turkish-first UX, render parallel branches, waits, retries, compensation and
child runs in redacted authorized traces, extend the governed eval assertion vocabulary over the
durable evidence the parts persisted, add bounded metrics/trace linkage and operational alerts,
implement owner-approved retention/purge, publish the reviewed enterprise scenario pack (S01–S07)
as compiler-validated GitOps artifacts, and run the final cross-part acceptance gate: full
regression, PostgreSQL recovery drills, the deferred browser-driven Turkish Studio journey and
owner sign-off. P2.6.11 integrates and accepts; it adds no new runtime grammar or authority.

## Background

The phase plan defines P2.6.11 as continuous integration plus final acceptance — "not a late
UI-only batch". Much of the continuous duty has already landed with the parts (wave 1–3 integration
records, P2.6.10 Turkish console statuses, P2.6.9 Studio AI activation), and the target DSL
contract assigns "Studio diagnostics, eval and operations closure" to this part. What remains is
the cross-part remainder on the integration head after P2.6.6 merges:

- Studio palette/config/diagnostics coverage for the verified-but-unexposed node families, under
  the phase principle that a node appears only after compiler, runtime, recovery, authorization,
  evaluation, audit and compatibility contracts are verified.
- Trace visualization for the new durable structures (branches/joins, waits/human tasks, retry and
  compensation attempts, parent/child links, agent decision/verification trails).
- Eval assertions currently stop at `workflow_completed` + the Sprint 10 agent trajectory kinds
  (`agent_completed`, `agent_tool_invoked`, `agent_no_tools`, `agent_max_steps`); the branch/join,
  wait/resume, retry, compensation, child-run, structured-argument, verification and escalation
  vocabulary is missing.
- Operational closure follow-ups recorded across sprints: retention/purge for branch state, wait
  correlations, planner observations, child links and the Sprint 10 agent-checkpoint 30/90-day
  policy (recorded, never automated); queue-saturation/stuck-wait/retry-storm/compensation-failure/
  budget alerts; dashboards required before enabling concurrency/advanced agents.
- The browser-driven Turkish Studio journey explicitly deferred from the wave-3 integration gate,
  demo-seed repopulation under the separately approved reset procedure, replacement of every dummy
  legacy artifact with the revised canonical grammar, and the phase completion-criteria bookkeeping
  (master plan, AGENTS.md verified state, archive policy).

## Scope

- Inventory current Studio/builder exposure versus verified runtime state, then add palette
  entries, config forms, node-schema metadata and canonical diagnostics for each verified family:
  transform, parallel/join/`for_each`, human-task/timer/event waits, error routes/retry/
  compensation, `subworkflow`/`agent_call`, and the P2.6.6 agent action-policy fields. Gated
  capabilities (Python-node execution, live MCP/live profiles) remain visibly gated, never
  activated by UI exposure.
- Extend the authorized, tenant-scoped run views to render branches, join outcomes, wait states,
  retry/compensation attempts, parent/child run linkage and the redacted agent decision/
  verification/escalation trail; all content stays redacted reason-code/checksum/metadata level.
- Extend the closed eval assertion registry with a bounded vocabulary over durable run evidence
  (candidate kinds, exact names frozen at implementation): branch/join completion and policy
  outcome, wait created/resumed/expired, retry count bounds, compensation executed/skipped, child
  run completion, structured-argument validity, agent verification outcome and escalation.
  Assertions stay data-driven, allowlisted and redacted; no code execution in suites.
- Add bounded-cardinality metrics and trace linkage for parent/child/branch/wait/retry/
  compensation activity plus alert rules (queue saturation, stuck waits, retry storms, compensation
  failure, budget/kill-switch activity) in the monitoring/runbook assets; wire dashboards required
  by the phase rollout gates.
- Implement retention/purge for branch state, wait correlations/token hashes, planner observation
  checkpoints, parent/child links and agent checkpoints as bounded, audited, fail-closed jobs with
  owner-approved windows and a default report/dry-run mode; purge never touches audit records or
  run evidence inside its retention window.
- Assemble the enterprise acceptance pack: executable S01–S07 scenario artifacts and eval suites
  passing compiler/eval/promotion gates in the non-production environment, published as GitOps JSON
  only after compiler validation and owner review; repopulate the demo seed via the separately
  confirmed reset procedure so no stale-grammar artifact or compiled release remains.
- Run and record final acceptance: full SQLite regression, full PostgreSQL non-owner/RLS profile,
  Celery/PostgreSQL recovery drills (restart, redelivery, reconciliation), the browser-driven
  Turkish end-to-end Studio journey (author → diagnose → publish → release → run → trace), and
  owner sign-off.
- Update canonical documentation (AGENTS.md verified state, phase/master plans, current-behavior
  docs, ADR follow-ups), record verification evidence and archive per planning policy.

## Non-goals

- New workflow/agent grammar, runtime semantics, state-machine or authority changes — those belong
  to the owning parts; a gap found here is routed back as a part-owned fix, not patched in the UI.
- Activating deployment-gated capabilities: Python-node execution (ADR-0011 attestation), live MCP
  endpoints/credentials, live model/embedding/OCR/AI profiles and live event ingress all keep
  their separate environment approvals; the acceptance pack runs with deterministic defaults.
- New production dependencies (Python or frontend) and new public API endpoints.
- Production deployment, live Grafana/Prometheus/OpenShift verification beyond what the local/
  Compose environment can prove — remaining live-infrastructure checks are recorded as explicit
  operational follow-ups, not silently assumed.
- Load/soak performance testing beyond bounded smoke evidence (recorded follow-up if deferred).
- Multi-agent supervision, personal MCP, upload scanning, conversation history (Phase 3).

## Acceptance criteria

1. Every verified node family is authorable end-to-end in Studio (palette, config form, node
   schema, canonical diagnostics with JSON Pointer locations and Turkish-first labels); no
   unverified or deployment-gated capability becomes reachable through the UI.
2. Run traces render branches, joins, waits, retries, compensation, child links and agent
   decision/verification/escalation trails for authorized tenant members only, at redacted
   metadata level (codes, checksums, counts, timestamps — no payloads, prompts or secrets), with
   cross-tenant access denied and tested.
3. The eval assertion registry covers the new vocabulary as closed allowlisted data; suites bound
   to candidate releases exercise branch/join, wait/resume, retry, compensation, child-run,
   structured-argument, verification and escalation outcomes with redacted stable reason codes.
4. Metrics/alerts exist with bounded labels (kind/status/reason only); tenant/run/artifact
   identifiers appear in logs/traces/audit only; alert rules for queue saturation, stuck waits,
   retry storms, compensation failures and budget/kill-switch events are present in the monitoring
   assets and exercised at least synthetically.
5. Retention/purge jobs run bounded, audited and fail-closed under owner-approved windows, with
   report mode, per-class coverage (branch state, wait correlations, observations, child links,
   agent checkpoints) and tests proving audit/evidence records and in-window data are never
   deleted.
6. The S01–S07 acceptance pack passes compiler, eval and promotion gates in non-production with
   deterministic providers; GitOps JSON examples are published only after compiler validation and
   recorded owner review; no dummy/stale-grammar artifact or compiled release remains after the
   approved reset/repopulation.
7. Full regression evidence is recorded: complete SQLite suite, complete PostgreSQL non-owner/RLS
   profile, frontend gates, and Celery/PostgreSQL recovery drills (worker restart, redelivery,
   crash-window reconciliation) on the integration head.
8. The browser-driven Turkish Studio journey is executed and evidenced end-to-end, closing the
   wave-3 deferral.
9. Canonical docs match code (AGENTS.md verified state, phase-2-6/master plans, current-behavior
   docs), durable decisions have ADRs where needed, verification records are complete, the archive
   policy is applied, and owner sign-off on Phase 2.6 completion is recorded.
10. Final-diff review (staff engineering, application security, SRE) is recorded; remaining risks
    and deferred live-infrastructure checks are explicit.

## Affected components

- `apps/builder` + `frontend/` (Studio palette, config forms, node-schema endpoint, diagnostics
  presentation, trace views, Turkish copy) — client stays non-authoritative.
- `apps/console` (authorized run/trace/operations views, retention/operations surfaces as needed).
- `apps/evaluations` (assertion registry + tests; isolated candidate execution seam unchanged).
- `apps/workflows` / `apps/agents` read-side evidence serialization for traces (no semantic
  change); retention/purge jobs (likely management commands + Celery beat entries).
- `apps/observability` (metrics, trace linkage), `deploy/` monitoring/alert/runbook assets.
- Scenario fixtures/GitOps examples, demo seed, `docs/` (plans, AGENTS.md verified state, ADR
  follow-ups, archive).

## Interfaces affected

No public consumer API change. Operator/console JSON surfaces may gain read-only trace/status
fields and role-gated retention/operations actions (existing session/CSRF auth patterns; any new
mutating operator action is role-gated, audited and listed in the final report). The eval
`eval_suite` artifact keeps its closed data-only assertion contract, extended additively. GitOps
example artifacts are additive documentation/fixtures. Management commands may be added for purge/
reconciliation reporting; they follow the existing role/tenant/audit conventions.

## Data impact

No new tenant-owned domain tables are expected; retention/purge bookkeeping should reuse existing
records (if a small additive bookkeeping table proves necessary it goes through integration-owner
migration allocation). Purge is the deliberate destructive surface of this part: it deletes only
named, owner-approved data classes outside their retention windows, in bounded audited batches,
fail-closed on ambiguity, and never deletes audit trails or in-window run evidence. The demo-seed
reset touches only the explicitly named non-production database under the P2.6.0 reset procedure.

## Security impact

This part widens read surfaces (traces, eval reports, Studio metadata) rather than execution
authority. Principal risks are over-disclosure through trace/eval rendering, cross-tenant leakage
in new read endpoints, UI-driven exposure of gated capabilities, unsafe purge and non-synthetic
data in published GitOps examples. All are covered in [threat-model.md](threat-model.md).

## Authorization impact

No authentication change and no new consumer capability. All new read/operator surfaces enforce
the existing role/tenant model server-side (membership-scoped reads; role-gated mutations;
deny-by-default). Eval, promotion, release and approval authority are unchanged. Purge/retention
actions are platform-operator scoped, audited, and their windows are owner-approved before
enablement.

## Observability impact

This part is largely the observability closure itself: new bounded metrics and alert rules, trace
linkage for parent/child/branch activity, and audited retention actions. All additions follow the
existing rules — bounded label sets, identifiers in logs/traces/audit only, redaction before
persistence, fail-closed audit for security-relevant operator actions, fail-open optional
telemetry.

## Migration impact

None planned. Any late-discovered additive migration (e.g., purge bookkeeping) requires
integration-owner allocation and the standard drift checks. The demo-seed reset is an operational
action under the approved procedure, never a migration step. No destructive migration is
authorized.

## Dependencies

- All owner-selected parts merged and verified on the integration head — P2.6.6
  ([plan](../phase-2-6-part-6-governed-agent-loop/plan.md)) is the last runtime prerequisite;
  wave 1–3 integration evidence stands for the rest.
- Owner decisions: retention windows per data class (phase open decision), alert thresholds, and
  review/sign-off of the published GitOps scenario pack.
- Compose PostgreSQL/Redis/MinIO environment for recovery drills and the browser journey; Node
  toolchain for frontend gates.
- The separately confirmed reset procedure for demo-seed repopulation.

## Implementation steps

1. Re-inspect the post-P2.6.6 integration head; inventory Studio exposure, eval vocabulary,
   metrics, retention follow-ups and stale dummy artifacts against verified runtime state; update
   this plan with the concrete remainder matrix.
2. Freeze the assertion-kind names, metric/alert names and retention windows (owner approval for
   windows); record them here.
3. Deliver Studio palette/config/diagnostics per verified family with frontend tests and
   node-schema coverage; keep gated families visibly gated.
4. Deliver authorized redacted trace rendering for branches/waits/retries/compensation/child runs/
   agent trails with cross-tenant and redaction tests.
5. Extend the eval assertion registry plus suite fixtures over S01–S07 trajectories.
6. Add metrics/trace linkage, alert rules and dashboard/runbook updates; exercise alerts
   synthetically.
7. Implement retention/purge jobs (report mode first), audits and negative tests; enable deletion
   only after owner window approval.
8. Build the acceptance pack: finalize S01–S07 artifacts/evals, run compiler/eval/promotion gates
   in non-production, execute the approved demo-seed reset/repopulation, publish GitOps JSON after
   owner review, and verify no stale-grammar artifact remains.
9. Run full regression: SQLite suite, PostgreSQL non-owner/RLS profile, frontend gates, Celery/
   PostgreSQL recovery drills; then execute and record the Turkish browser journey.
10. Update AGENTS.md verified state, phase/master plans, current-behavior docs and ADRs; complete
    `verification.md`; apply the archive policy; obtain and record owner sign-off.
11. Final-diff review as staff engineer, application-security engineer and SRE; report remaining
    risks and deferred live-infrastructure checks.

## Test plan

- Frontend: vitest component coverage for new palette/config/trace/status surfaces, `tsc`,
  `vite build`; node-schema contract tests server-side.
- Authorization: membership-scoped trace/eval reads, role-gated operator actions, cross-tenant
  denial for every new read path (SQLite + PostgreSQL non-owner/RLS).
- Redaction: trace/eval/alert/audit payload assertions — codes/checksums/counts only; no prompts,
  payloads, secrets, endpoints or foreign-tenant identifiers.
- Eval: assertion-kind allowlist enforcement, redacted reason codes, S01–S07 suite runs over the
  isolated candidate seam, unknown-kind rejection.
- Retention/purge: window boundaries, report-versus-delete modes, bounded batches, audit-trail
  preservation, in-window protection, ambiguity fail-closed, idempotent re-run.
- Observability: metric label boundedness, alert rule syntax/trigger simulation, trace linkage
  presence.
- Acceptance: compiler/eval/promotion gates over the pack; reset/repopulation leaves no stale
  grammar (search-verified); recovery drills (worker restart mid-run, duplicate delivery,
  crash-window reconciliation) on Compose services.
- Repository gates: `ruff format --check`, `ruff check`, `mypy`, `manage.py check`,
  `makemigrations --check --dry-run`, full SQLite pytest, PostgreSQL profile per the manual-testing
  guide, frontend CI equivalents.
- Browser journey: scripted/recorded Turkish end-to-end Studio flow with evidence in
  `verification.md`.

## Rollout plan

- Land incrementally behind the existing role gates; read-only surfaces first, then eval
  vocabulary, then alerts, then purge (report mode), then deletion after owner window approval.
- The acceptance pack and reset run only in the named non-production environment.
- Dashboards/alerts must be in place before any organization canary enables concurrency or
  advanced agent policies (phase rollout gate).
- Live-infrastructure verification (Grafana/Prometheus/OpenShift, live profiles) stays a recorded
  operational follow-up with named owners.

## Rollback plan

- UI/eval/metrics additions are additive and role-gated; disable by reverting the increment —
  no runtime state is affected.
- Purge rollback: deletion is irreversible by design, so windows are owner-approved, batches are
  bounded and audited, and report mode precedes enablement; a wrong window is stopped by disabling
  the job (forward-fix), and audit evidence of what was deleted persists.
- Acceptance-pack artifacts are immutable versions; a rejected pack is superseded by new versions,
  never edited in place.
- Documentation/status rollback follows normal review; no destructive history rewrite.

## Risks

- Trace/eval rendering is the highest-value leak surface of the phase; a single unredacted field
  ships tenant content to operator screens.
- Purge misconfiguration could destroy run evidence or audit-adjacent data; fail-closed defaults
  and window approval are load-bearing.
- The acceptance pack can silently depend on deployment-gated capabilities and mask gaps behind
  deterministic stubs; each scenario must state what it proves and what stays gated.
- Studio exposure can outrun verification if the inventory in step 1 is wrong.
- Alert/metric additions can explode cardinality or page on noise; thresholds need owner review.
- Cross-part regressions surface here last; schedule risk concentrates at final acceptance.
- The browser journey depends on local environment stability (Compose, Node, LDAP-disabled auth
  path); flakiness must not be papered over — failures are diagnosed, not rerun blindly.

## Open questions

1. Exact retention windows per data class (owner decision; agent checkpoints have a recorded
   30/90-day policy — confirm and extend to branches/waits/observations/child links).
2. Exact assertion-kind names and whether any need candidate-run evidence not yet persisted (would
   route back to the owning part).
3. Scope of operator retention/operations UI versus management commands only in this increment.
4. Browser-journey tooling (scripted Playwright-style run versus manually recorded evidence) and
   where the recording lives.
5. Whether bounded load/soak smoke is executed here or recorded as a named follow-up with an
   owner.
6. Which live-infrastructure checks the owner wants attempted against the local/Compose
   environment versus explicitly deferred.

## Resolved decisions (2026-07-17)

- **(1) Retention principle — decided by the owner.** Data needed for retrospective traceability
  (audit records, decision/outcome lineage, run evidence metadata, parent/child linkage) is
  retained and is not purged in this phase. High-detail bulky state (agent checkpoints, planner
  observation summaries, branch working state, wait correlation hashes) uses the recorded
  30/90-day windows. The exact per-class 30-versus-90 assignment is frozen at implementation
  step 2 under this principle, and deletion still ships behind report-mode first.

## Step 1 remainder inventory (2026-07-17)

Taken on the post-P2.6.6 integration head (`feat/foundation-sprint-0-1`, HEAD `6c3fb7f`). Parts
1–10 are merged and gate-verified. The concrete cross-part remainder against verified runtime
state:

### A. Studio node exposure (`apps/builder/node_schema.py` + `frontend/`)

Runtime `BUILTIN_NODE_TYPES` (18, `apps/workflows/compiler.py:50`): input, retrieve, generate,
condition, format_output, validate_contract, end, custom, tool, transform, **parallel, join,
for_each**, event_wait, human_task, timer, **subworkflow, agent_call**.
Studio `_BUILTIN_NODES` (13, `node_schema.py:25`): input, retrieve, generate, format_output,
validate_contract, condition, tool, transform, custom, event_wait, human_task, timer, end.
- **Palette gap (5 families):** `parallel`, `join`, `for_each`, `subworkflow`, `agent_call`.
- **Config-surface gap:** node-level `retry_policy` (retry-eligible nodes) and `compensation` are
  not exposed as config fields; the P2.6.6 agent action-policy (`spec.actions`: `verify_roles`,
  `repeat_retrieval`, `escalation_enabled`, `role_call_caps`) lives in the `agent_definition`
  artifact, so it is exposed via the agent/`ArtifactDraft` authoring surface, not the workflow
  palette.
- **Architecture note:** the frontend palette (`Palette.tsx`) and config form
  (`NodeConfigPanel.tsx`) render entirely from the backend node-schema, so most exposure is a
  backend `node_schema.py` change. The three branch-region families (parallel/for_each/join)
  additionally need frontend region/edge rendering + canonical diagnostics beyond flat field
  descriptors.
- **Stays gated (never activated by UI):** custom Python-node execution
  (`PYTHON_NODE_RUNTIME_ENABLED`/`PYTHON_NODE_RUNNER_ATTESTED`), live MCP, live model/embedding/
  OCR/AI profiles.

### B. Eval assertion vocabulary (`apps/evaluations/assertions.py`)

Existing kinds: answer `contains`/`not_contains`, `min_sources`, `workflow_completed`,
`workflow_node_executed`, `agent_completed`, `agent_tool_invoked`, `agent_no_tools`,
`agent_max_steps`.
- **Missing (to freeze names at step 2):** branch/join completion + policy outcome, wait
  created/resumed/expired, retry-count bounds, compensation executed/skipped, child-run
  completion, structured-argument validity, agent verification outcome, escalation.
- **Evidence dependency:** durable events already persisted carry the needed evidence
  (`parallel_region_opened`, `join_closed`, `child_admitted`/`child_completed`/`child_failed`;
  P2.6.6 agent schema-v2 verify/escalate). Confirm each candidate kind maps to persisted
  evidence during step 5; any missing evidence routes back to the owning part.

### C. Metrics & alerts (`apps/observability/metrics.py`, `deploy/monitoring/`)

Existing series include `agenthub_workflow_runs_total{status}`,
`agenthub_workflow_nodes_total{node_type}`, `agenthub_agent_runs_total{status}`,
`agenthub_agent_steps_total{decision}`, tool invocation/approval counters, and the ingestion
gauges/histograms. Monitoring assets exist: `deploy/monitoring/grafana-dashboard.json`,
`deploy/monitoring/prometheus-rules.yaml`.
- **Missing:** bounded-label series + trace linkage for parallel branch/join outcomes, waits
  (created/resumed/expired), retry attempts, compensation, and parent/child run linkage; alert
  rules for queue saturation, stuck waits, retry storms, compensation failure, and
  budget/kill-switch activity.

### D. Retention/purge

No retention/purge job or management command exists today (the `purge` hits in `apps/documents`
are the unrelated blob-tombstone purge). Retention principle already resolved (below).
- **Missing:** bounded, audited, fail-closed, report-mode-default purge jobs for agent
  checkpoints (recorded 30/90-day policy), planner observation summaries, branch working state,
  wait correlation/token hashes, and parent/child links; traceability/audit/eval evidence is
  retained and never purged in this phase. Per-class 30-vs-90 assignment frozen at step 2.

### E. Trace rendering (`apps/console`)

Present: `agent_run_detail` (redacted event trail), `workflow_human_task_decide`,
`workflow_recoveries`/`workflow_recovery_decide`.
- **Missing:** a general authorized workflow run trace/detail view rendering branches, join
  outcomes, wait states, retry/compensation attempts and parent/child linkage; the agent trace
  predates schema v2 and needs verification/escalation rows. All at redacted
  code/checksum/count level, membership-scoped, with cross-tenant denial tests.

### F. Acceptance pack & stale artifacts

S01–S07 exist only as design fixtures
(`docs/tasks/phase-2-6-contract-and-scenario-foundation/fixtures/workflows/S0x-*.target.json`),
not executable GitOps artifacts + eval suites. Main-tree GitOps sample is `gitops/mcm/`
(customer-information; confirm current grammar). Demo seed is
`apps/console/management/commands/seed_demo.py` (one RAG + one approval-workflow + one agent).
- **Missing:** executable S01–S07 artifacts + eval suites passing compiler/eval/promotion gates
  in non-production; owner-reviewed published GitOps JSON; demo-seed repopulation replacing any
  stale-grammar artifact.

### Suggested implementation order (read-only first, destructive last)

1. Studio exposure (A) + trace rendering (E) — read-side, additive, role-gated.
2. Eval vocabulary (B).
3. Metrics + alerts (C).
4. Retention/purge (D) — report mode first, deletion only after owner window approval.
5. Acceptance pack + demo-seed reset (F), then final regression + Turkish browser journey.

## Step 2 frozen decisions (2026-07-18)

Owner decisions on the open questions (via task kickoff): drive **autonomously through
increments A–F**; **retention all-90-day**; retention gets **a console UI in addition to
management commands**; **attempt live Grafana/Prometheus infra locally** and record the Turkish
browser journey. Frozen names below (final names reconcile against persisted evidence at each
increment; any gap routes back to the owning part, not patched here):

- **Eval assertion kinds (increment B):** `workflow_branch_completed`,
  `workflow_join_completed`, `workflow_wait_created`, `workflow_wait_resumed`,
  `workflow_wait_expired`, `workflow_retry_within`, `workflow_compensation_executed`,
  `workflow_compensation_skipped`, `workflow_child_completed`, `agent_arguments_valid`,
  `agent_verified`, `agent_escalated`. Data-only, allowlisted, redacted stable reason codes.
- **Metric series (increment C, bounded labels only):** `agenthub_workflow_branches_total{outcome}`,
  `agenthub_workflow_joins_total{mode,outcome}`, `agenthub_workflow_waits_total{kind,phase}`
  (phase = created/resumed/expired), `agenthub_workflow_retries_total{failure_class}`,
  `agenthub_workflow_compensations_total{outcome}`, `agenthub_workflow_children_total{kind,status}`.
- **Alert rules (increment C):** `AgentHubQueueSaturation`, `AgentHubStuckWaits`,
  `AgentHubRetryStorm`, `AgentHubCompensationFailure`, `AgentHubBudgetKillSwitch`.
- **Route-back (increment B, discovered 2026-07-18):** the isolated eval candidate seam
  (`run_workflow_candidate`) runs synchronously and raises `WorkflowParallelPending` on
  parallel/for_each nodes, so it cannot execute async branch/wait/retry/compensation
  workflows end-to-end. The full assertion **vocabulary + logic + metadata contract**
  (`_workflow_structure_evidence`) and unit tests are delivered now; exercising those
  assertions over real async S0x candidate trajectories requires the owning parts
  (P2.6.2–P2.6.5) to add async candidate execution. Routed back, not faked — the seam
  returns empty structure evidence for `run_id == 0`. Agent trajectory assertions
  (`agent_verified`/`agent_arguments_valid`/`agent_escalated`) run fully today.
- **Retention windows (increment D):** a single **90-day** window for every purgeable class
  (branch working state, wait correlation/token hashes, planner observation summaries, agent
  checkpoints, parent/child links). All traceability/audit/eval evidence is retained
  indefinitely. Deletion ships behind report-mode first.

## Status

In progress — increments **A–D implemented and verified**; E/F partial and
environment/owner-gated. Evidence in [verification.md](verification.md):

- **A** Studio exposure: all five node families + retry/compensation/composition-gate metadata
  (`apps/builder/node_schema.py`); frontend authoring (new field kinds, node mappings,
  retry/compensation, branch/`on_error` edges) with tsc + 24 vitest + `vite build`; authorized
  redacted workflow trace view (`console/workflow_run_detail`) with cross-tenant + redaction
  tests.
- **B** Eval vocabulary: 12 new assertion kinds (allowlisted, redacted) + candidate evidence
  metadata contract. Async workflow-structure candidate exercise **routed back** to
  P2.6.2–P2.6.5 (seam can't run async structures); agent trajectory assertions run today.
- **C** Metrics: 6 bounded-label series + 6 signal receivers + 5 alert rules + runbook
  sections; bounded-label and alert-syntax tests.
- **D** Retention/purge: `apps/observability/retention.py` (90-day, report-mode default,
  fail-closed audited batches, idempotent), `purge_retention` command, platform-admin console
  page, report-only beat entry; report/commit/in-window/audit/idempotency/gating tests.

Verification totals: full SQLite **940 passed / 37 skipped**; PostgreSQL affected apps
**93 passed** + workflows/agents FORCE-RLS **290 passed**; static gates + mypy clean; frontend
gates green.

**Remaining for `Completed` (environment/owner-gated):** E — publish the compiler-validated
S01–S07 GitOps pack **after owner review** + run the approved demo-seed reset; F — real-broker
recovery drills, live Grafana/Prometheus verification, the recorded Turkish browser journey,
and owner sign-off. These require the running worker/monitoring stack and a human owner and are
not performed autonomously.

## Completion criteria

`Implemented` when Studio coverage, trace rendering, eval vocabulary, metrics/alerts, retention
jobs and the acceptance pack exist on the integration head. `Verified` when acceptance criteria
1–8 have recorded command/test/drill/journey evidence in `verification.md`. `Completed` — which
closes Phase 2.6 — additionally requires criteria 9–10: documentation/ADR/archive closure, the
master-plan evidence update, explicit residual-risk reporting and recorded owner sign-off per the
[Definition of Done](../../ai/definition-of-done.md).
