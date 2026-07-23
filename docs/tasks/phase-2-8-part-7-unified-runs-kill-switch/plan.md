# Task Plan: Phase 2.8 Part 7 — Unified runs and kill-switch management

## Task summary

Provide one organization-scoped operational page for execution, evaluation, ingestion, index-build
and connector-sync work, while preserving each job's native authorization and lifecycle. Add audited
run/scenario/project/organization/platform runtime controls to the console. Implement the role,
content-separation, superadmin-recovery and stop/resume rules from the
[Part 2.1 scoped authorization plan](../phase-2-8-part-2-1-scoped-authorization-superadmin-recovery/plan.md).

## Background

Part 1 retained one Runs navigation item but underlying records and detail pages remain split. Part 3
unifies scenario execution Run/Event only; ingestion/evaluation/sync still have distinct models and
control semantics. Agent runtime suspension exists through commands but not a complete unified
console experience. A read model must not accidentally create universal cancellation authority.

## Scope

- Build a bounded read-only operational projection/service across unified execution Run,
  evaluation, ingestion, staged index build, Confluence sync and REST sync records.
- List newest-first with type, status, name/context, organization, project/scenario/set where
  applicable, actor/consumer safe label, start/update/duration and safe reason code.
- Filter by mandatory active organization, job type, normalized status group, project, scenario,
  document set and bounded date range. Pagination/cursors and counts are bounded.
- Route each row to its authorized native detail/trace and expose only actions supported by that
  record type and role. Keep workflow/agent distinction as secondary node/action diagnostics, not a
  separate page.
- Point dashboard health KPIs to exact prefiltered operational results without listing records on
  the dashboard.
- Generalize the durable runtime control to scenario, project, organization and platform scopes for
  the unified workflow engine. Show current state, scope, safe reason, source, actor, update time and
  whether privileged resume is required.
- Treat the application Global Admin as a non-superuser daily operator. Global Admin manages
  platform/organization controls; Organization Admin manages its organization and contained
  scenario/project controls. Project Admin and Scenario Editor have no cancellation, pause or
  resume authority.
- Keep document controls separate: a Document Set Manager may pause ingestion, quarantine its set
  and revoke a scenario retrieve grant. Runtime control never grants document content access.
- Make stop authority deliberately broader than resume authority. Resume reauthorizes the exact
  scope, control source and privileged-resume flag.
- Require bounded reasons and fail-closed audit. There is no application elevation or temporary
  access workflow; exceptional intervention uses the separate, specially audited superadmin.
- Check suspension during API admission and before every transition claim/resume. New suspended
  execution requests fail with a safe service error; queued/waiting state is preserved and resumes
  only when control is cleared.
- Running work stops cooperatively at a safe transition boundary. Suspension does not mass-cancel;
  per-run cancellation remains explicit and separately authorized.

## Non-goals

- One polymorphic database table for every job, universal cancel/retry, cross-organization aggregate
  mode, exposing raw job payload/state/provider errors, hard-killing worker processes or using the
  active organization as authority.
- Routine use of Django superuser, user-level document-set roles, granting document content through
  runtime controls, allowing Project Admin to publish, or requiring approval before an immediate
  safety stop.

## Read-model and status contract

- The projection uses a closed `kind` vocabulary and maps native statuses to display groups without
  rewriting native state. It returns stable public identifiers/authorized target URLs, safe labels,
  timestamps and reason codes only.
- Query/filter allowlists and maximum date/page limits are enforced server-side. Invalid/unknown
  filters do not fall back to an unbounded query.
- Native detail services perform their own object authorization. The projection cannot grant an
  action merely because it displayed a row.
- Dashboard links carry signed/allowlisted or server-constructed filters, not trusted tenant IDs.

## Kill-switch semantics and authorization

| Action | Global Admin | Organization Admin | Project Admin | Scenario Editor | Document Set Manager |
| --- | --- | --- | --- | --- | --- |
| Cancel authorized individual run | Allow | Own organization | Deny | Deny | Deny |
| Pause/resume scenario | Allow | Own organization | Deny | Deny | Deny |
| Pause/resume project | Allow | Own organization | Deny | Deny | Deny |
| Pause/resume organization | Allow | Own organization | Deny | Deny | Deny |
| Pause/resume platform | Allow | Deny | Deny | Deny | Deny |
| Pause ingestion / quarantine set | Operational stop; no content | Safe status/request only | Deny | Deny | Assigned set |
| Revoke/regrant scenario retrieve authority | Deny | Deny | Deny | Deny | Assigned set |

The automated safety system may activate any applicable control but cannot resume it. Global
suspension dominates organization, project and scenario state; organization suspension dominates
project/scenario; project dominates scenario. A narrower resume never overrides an active broader
control.

Every control records `scope_type`, trusted `scope_id`, closed `reason_code`, bounded reason, source
(`human`, `automatic`, `policy`), actor, timestamps and `requires_privileged_resume`. Resume is
idempotent but still reasoned and audited. A role may resume only controls permitted by the matrix
and provenance. Project Admin and Scenario Editor cannot place or clear runtime controls. Disabled
organizations reject operational resume/start according to existing lifecycle rules.

The daily Global Admin account is application-authorized and not Django superuser. A separate
superadmin is reserved for exceptional intervention and control-plane recovery. Superadmin may
operate any kill-switch or document-set grant through the central authorization boundary, with a
dedicated high-severity audit event and immediate alert for each action. No kill-switch row conveys
document content authority to an ordinary application role.

## Acceptance criteria

- Every supported job appears once with correct kind/status/context and no cross-tenant metadata.
- Filters/pagination are bounded and exact; dashboard KPI links open the records represented by the
  KPI definition.
- Detail/action buttons reflect and recheck native authorization; unsupported actions are explained.
- Global/org suspension changes are CSRF-protected, reasoned, audited and fail closed on audit error.
- Scenario/project stop and provenance-aware resume follow the exact role matrix; Project Admin and
  Scenario Editor have no operational control and Project Admin cannot publish.
- Kill-switch visibility and operation reveal no document list/content/raw retrieval context.
- Document-set quarantine and scenario-grant revocation stop use without granting Global,
  Organization or Project Admin routine content authority.
- Suspended admission/claim/resume behavior is race-tested; durable queued/waiting state is not lost.
- Global/organization/project/scenario dominance and organization isolation are clear in UI and
  enforced server-side.
- No raw prompts, document content, provider errors, tokens/secrets or high-cardinality IDs enter
  metric labels/logs.
- Responsive table/card, keyboard, focus, status text and screen-reader behavior pass acceptance.

## Data and migration impact

Reuse native job models for the projection. Migrate/rename existing agent runtime control into a
unified runtime control only after Part 3, preserving global/org rows, direct tenant lineage,
constraints and RLS policy. Add indexes only from measured query plans. No job payloads are copied
into a denormalized table unless later evidence requires a separately approved design.

## Security, observability and audit

All projection querysets begin with authorized tenant/object scope and are then narrowed by active
organization/filter. Status normalization is presentation only. Audit cancel/suspend/resume attempt,
authorization decision, effective capability source, exact scope, control provenance, outcome,
reason and trace using safe IDs. Alert on every superadmin login/action. Emit bounded metrics for suspended
admission/claims and control state without organization/run IDs as labels.

## Dependencies

Part 1 navigation/dashboard and verified Part 3 unified execution/control contract. Existing native
evaluation/ingestion/sync scoping/detail pages remain sources of truth. Authorization and
superadmin recovery follow the
[Part 2.1 scoped authorization plan](../phase-2-8-part-2-1-scoped-authorization-superadmin-recovery/plan.md);
scenario-to-document-set grants from Part 5 remain independent from runtime controls.

## Implementation steps

1. Define closed job/status/filter contract and native authorization/action matrix; capture query
   plans and data-volume bounds.
2. Implement tenant-first projection and cursor/pagination/filter service with unit/RLS tests.
3. Build unified list and native detail links/actions; replace remaining type-separated primary
   navigation and correct dashboard KPI targets.
4. Migrate runtime control to the unified engine; implement transactional
   scenario/project/organization/platform controls, hierarchy and provenance-aware resume.
5. Implement central stop/resume predicates for Global and Organization Admin; prove Project Admin
   and Scenario Editor cancellation/pause/resume denial plus Project Admin release denial.
6. Add document-set ingestion pause/quarantine and superadmin scenario-grant intervention without
   exposing content or conflating binding, retrieve grant and runtime state.
7. Enforce control at admission and each transition boundary; test concurrent flip/claim/resume,
   grant revocation and in-flight cooperative stop behavior.
8. Add the superadmin runbook, high-severity audit/alerts, metrics/operator explanations,
   responsive/accessibility behavior and final reviews.

## Test plan

Projection deduplication/order/filter/date/page boundaries; exact KPI links; every job kind/detail;
anonymous/no-role/cross-tenant/disabled/RLS; native action denial;
global/organization/project/scenario precedence; stop/resume asymmetry and provenance; Project Admin
publish/cancel/pause/resume denial; Scenario Editor cancel/pause/resume denial;
automated-stop/manual-resume denial;
document quarantine and retrieve-grant revocation; no document content through operations views;
superadmin intervention audit/alert; proof that no temporary elevation path exists; audit failure
rollback; concurrent suspend/admit/claim/resume/cancel; queued/waiting and running semantics;
query-count/performance bounds; redaction/log/metric labels; full quality, migration, browser and
accessibility suites.

## Rollout and rollback

Roll out read-only projection first and compare it with native counts. Add UI actions only after
control-service tests and runbook review. Runtime-control migration is additive/preserving before old
code removal. Rollback hides actions/page and restores native navigation while retaining control
rows; guarded superadmin command interfaces remain available. Never roll back by clearing suspension state.

## Risks

Metadata leaks in cross-model unions, misleading normalized status, unbounded queries, stale KPI
definitions, universal-action assumptions, kill-switch race windows, hierarchy/precedence errors,
audit outage or operators confusing suspension with cancellation. Additional risks are operational
controls accidentally leaking into authoring roles, broad Global Admin content access, a scenario
leaking raw retrieval context, automatic controls being cleared by a lower role, and superadmin
becoming routine.

## Open questions

- Superadmin MFA, credential custody, alert recipients and audit retention are owned by Part 2.1.
- The read model remains non-authoritative, suspension remains distinct from cancellation and these
  open identity choices do not permit broad superuser use.

## Status

**Planned.** Depends on verified Part 3 runtime/control behavior.

## Completion criteria

Projection, native authorization, suspension concurrency, RLS, audit, performance, accessibility and
runbook evidence pass; current docs are updated; staff/AppSec/SRE reviews close; task reaches Verified
before archival.
