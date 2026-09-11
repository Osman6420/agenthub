# Task Plan: Phase 2.9 Part 1 — Exact run authorization and PostgreSQL containment

## Task summary

Close the confirmed same-tenant, cross-scenario run-metadata disclosure and make the same
authorization result hold under the canonical non-owner PostgreSQL application role. Establish one
deny-by-default human-operator run scope for list, detail, event and control paths; reconcile the
least-privilege PostgreSQL grant/readiness/test path; and repair only the stale workflow-wait tests
and typing failures directly coupled to this work.

This task changes authorization and tenant-isolation behavior. The repository owner explicitly
approved implementation on 2026-08-01 with the instruction to complete Phase 2.9 Part 1.

## Background

The 2026-07-31 browser audit proved that a user with `scenario_runtime_operator` responsibility on
one scenario can see another same-organization scenario's execution on `/console/runs/` and can
open its redacted workflow-run detail. Redaction limits content exposure but still reveals scenario,
actor/consumer, timestamps, statuses and event names.

Direct inspection identifies two primary gaps and one adjacent contract drift:

- `apps.console.operations.project_operations` receives only an organization and filters, then
  queries `Run` by organization. The active organization narrows navigation but is incorrectly
  sufficient to populate the execution projection.
- `apps.console.views._scoped_run` resolves a `Run` first and checks only organization-shell access.
  Detail and nested event/branch/join/wait/compensation reads therefore occur before exact scenario
  responsibility is proved.
- `apps.console.scoping.scoped_runs` already expresses the intended broad organization-responsibility
  or exact `scenario_runtime_operator` scope, and dashboard/workflow-list paths use it. Part 1 must
  make this contract canonical rather than introduce another divergent predicate.

The PostgreSQL audit also isolated a non-owner middleware test failure: its temporary role lacks
`SELECT` on `identity_platformresponsibilityassignment`, which `is_platform_admin` reads while
deriving tenant scope. The canonical `deploy/postgres/provision-app-role.sql` already grants access
to that table. The platform assignment table has no organization key and is intentionally outside
the tenant-assignment FORCE RLS migration. Implementation must therefore prove whether the defect
is test/provision/readiness drift before changing database privileges or schema.

Three workflow-wait tests still pass removed `allowed_roles` and `actor_roles` arguments after the
wait contract moved to exact persisted authority/token semantics. They obscure the PostgreSQL
baseline and contribute directly related typing failures.

## Scope

- Define one canonical human-operator run visibility queryset/predicate and use it for:
  - the execution family in the unified `/console/runs/` projection;
  - the legacy `/console/workflow-runs/` list while that compatibility route remains;
  - workflow-run detail and all nested metadata/event collections;
  - run cancellation and recovery target resolution before action authorization;
  - any dashboard count or link that represents the same execution set.
- Preserve the current capability contract:
  - Global Administrator: all runs, narrowed to the selected organization in organization views;
  - Organization Administrator and Organization Auditor: all runs in their assigned organization;
  - Scenario Runtime Operator: runs only for scenarios with an active, unexpired exact assignment;
  - project roles, scenario viewer/editor/release-manager/approver, membership-only and inactive or
    expired assignments: no run visibility unless another qualifying responsibility independently
    grants it.
- Ensure every operation family in the unified projection starts from its native authorized scope.
  In particular, do not let an exact scenario runtime assignment expose evaluation, ingestion,
  index-build or connector-sync metadata merely because the actor can open the Runs page.
- Resolve invisible or foreign run identifiers through the authorized queryset and return a
  non-disclosing 404. Do not fetch an unrestricted run and then use its tenant to widen context.
- Reauthorize every mutation for the exact persisted organization/project/scenario and action after
  read visibility is established. A visible run with insufficient action authority returns 403;
  an invisible run returns 404.
- Audit denied run mutations with stable action/outcome/reason/source and bounded safe identifiers.
  Do not include scenario/run labels, actor/consumer data, event names, payloads, checkpoints or
  error/provider content.
- Reproduce the PostgreSQL failure with a temporary `NOSUPERUSER NOBYPASSRLS` non-owner role;
  compare its grants with the canonical provision script and readiness checks; make the smallest
  change that removes drift without broadening privilege.
- Prove protected run and responsibility tables remain FORCE RLS constrained by tenant scope.
  Do not add RLS to a table without tenant lineage or use owner/superuser/BYPASSRLS as a fix.
- Update the stale workflow-wait tests to the current `suspend_run_for_wait` and
  `resume_run_wait` contracts without weakening their replay, forgery, payload, cancellation or
  audit assertions. Repair only typing errors caused by those stale calls or Part 1-owned edits.
- Add focused authorization, PostgreSQL and browser regression evidence and update current-behavior
  documentation only after implementation is verified.

## Non-goals

- Adding scenario pause/resume controls or redesigning runtime-control UX; those are Phase 2.9
  Part 3 concerns.
- Changing consumer-token `/v1/runs/<id>` status/cancel contracts unless a failing regression proves
  they share the human-operator defect.
- Granting run visibility to Project Administrator, Scenario Editor, Release Manager, Approver or
  Viewer roles.
- Treating active organization, session state, query parameters, route identifiers or visible UI
  controls as authorization.
- Exposing raw run inputs/outputs, checkpoints, wait payloads, provider data or document content.
- Broad grants, default privileges, table ownership, superuser, `BYPASSRLS`, disabling FORCE RLS,
  or a client-supplied scenario/role filter.
- A broad mypy cleanup, mass format, dependency change, public API change, destructive migration or
  production-data access.

## Authorization contract

| Actor | List/detail exact assigned scenario | Same-tenant other scenario | Cross-tenant | Cancel exact visible run | Recovery |
| --- | --- | --- | --- | --- | --- |
| Global Administrator | Allow | Allow in selected organization | No row outside selected organization | Per central capability | Existing privileged contract |
| Organization Administrator | Allow | Allow in assigned organization | 404 | Per central capability | Existing admin contract |
| Organization Auditor | Allow | Allow read-only | 404 | 403 + redacted audit | 403 |
| Scenario Runtime Operator | Allow | 404 | 404 | Allow when central exact action check passes | 403 |
| Project roles | 404 | 404 | 404 | 404 | 404 |
| Scenario viewer/editor/releaser/approver | 404 | 404 | 404 | 404 | 404 |
| Active member without responsibility | 404 | 404 | 404 | 404 | 404 |
| Anonymous/inactive/revoked/expired actor | Login/deny | Login/deny | Login/deny | Login/deny | Login/deny |

Where an actor holds multiple active responsibilities, permissions are additive only through the
central server-side capability model. Revoked, inactive or expired assignments contribute nothing.

## Acceptance criteria

1. The unified and compatibility run lists contain exactly the runs authorized by the contract;
   counts, pagination and filters cannot reveal hidden rows.
2. Direct detail/event URLs for same-tenant cross-scenario, cross-tenant and unassigned actors return
   the same non-disclosing 404 and do not query/render nested metadata after denial.
3. Exact scenario runtime operators can still read and cancel an authorized non-terminal run;
   neighboring scenario roles cannot.
4. Organization Auditor retains organization-wide read authority but cannot cancel or recover a
   run; the denial is audited without sensitive metadata.
5. The unified projection does not expose non-execution operation families to an actor whose only
   authority is exact scenario runtime operation.
6. Active-organization selection only narrows an already authorized queryset and cannot widen it.
7. PostgreSQL results match SQLite results under a temporary non-owner, non-superuser,
   `NOBYPASSRLS` role with FORCE RLS enabled on protected tables.
8. The canonical provision script, readiness inspection and test fixtures agree on every privilege
   needed to derive platform/membership scope. No broader grant than the proven operation set is
   added.
9. The three stale workflow-wait tests pass against the current API while preserving all existing
   security, replay/idempotency and audit assertions; directly related mypy errors are closed.
10. Focused and full applicable SQLite/PostgreSQL suites, lint/type/format/system/migration checks,
    and the mandatory browser authorization gate pass with recorded evidence.

## Affected components

- `apps/console/scoping.py` — canonical run visibility.
- `apps/console/operations.py` — authorization-first unified projection inputs.
- `apps/console/views.py` — run list/detail/control target resolution and safe denials.
- `apps/identity/authorization.py` and responsibility models — contract source; change only if tests
  prove a predicate defect.
- `apps/tenancy/middleware.py`, `apps/tenancy/services.py` and PostgreSQL readiness/provisioning —
  non-owner bootstrap/read scope.
- `apps/console/tests`, `apps/identity/tests`, `apps/tenancy/tests`, `apps/workflows/tests` — matched
  role/scope, RLS and stale wait coverage.
- Run/audit templates and current-behavior docs only where verified behavior changes.

## Interfaces affected

Human console responses for `/console/runs/`, `/console/workflow-runs/`, workflow-run detail,
cancellation and recovery. The intended change is stricter authorization with non-disclosing 404s;
no public REST/MCP schema, URL or successful authorized response contract is planned to change.

## Data impact

No business-data rewrite, deletion or backfill is planned. Tests use synthetic organizations,
scenarios, assignments, runs and audit records. Authorization queries may change their joins and
predicates; query count and plans must remain bounded.

## Security impact

Positive: removes a confirmed metadata disclosure and prevents active-organization state from acting
as authority. Negative risk: a partial fix can secure one list while leaving detail, counts, filters,
nested events or another operation family exposed. The fix must be applied at shared query/target
resolution boundaries and proven with matched identities.

## Authorization impact

Material and deliberate: same-tenant run access becomes exact-responsibility scoped. This is an
owner-approval-gated implementation change. The capability vocabulary and role grants remain
unchanged; only enforcement is made consistent with them.

## Observability impact

Keep list/detail reads out of the business audit unless current policy requires otherwise. Record
mutation denials with actor, action, submitted/safe target identifier, authorization source/reason,
outcome and request/trace ID where the audit API supports them. Expected 404/403 paths must not log
payloads or high-volume traceback noise. No new high-cardinality metric labels are planned.

## Migration impact

No schema migration is expected. The existing platform-responsibility table cannot receive the
tenant-assignment policy because it has no organization lineage. If implementation discovers that a
schema, policy or production privilege change is required, stop, update this plan/threat model and
obtain explicit approval before creating a migration or altering grants.

## Dependencies

- [Phase 2.9 component plan](../../components/phase-2-9-ui-authorization-lifecycle-closure-plan.md)
- [Current role/UI audit report](../../../tasks/current-application-role-ui-audit/report.md)
- [Audit verification](../../../tasks/current-application-role-ui-audit/verification.md)
- Phase 2.8 exact-responsibility capability model and unified-run projection.
- Canonical PostgreSQL/pgvector/RLS profile and `deploy/postgres/provision-app-role.sql`.
- [Manual testing guide](../../../manual-testing-guide.md), [testing rules](../../../ai/testing-rules.md)
  and [Definition of Done](../../../ai/definition-of-done.md).

## Implementation steps

1. **Approved 2026-08-01.** Implement the authorization/tenant-isolation correction within this
   plan; no contract exception or scope expansion was approved.
2. Add failing SQLite tests that reproduce unified-list and direct-detail disclosure with two
   scenarios in one organization, plus cross-tenant, membership-only, expired/revoked assignment
   and neighboring-role cases.
3. Add a canonical authorized-run queryset/target resolver based on persisted responsibilities and
   central capabilities. Confirm symbol references and dynamic/template routes before replacing
   local predicates.
4. Change the unified projection to receive already-authorized native querysets (or actor-aware
   scope inputs), then apply organization and user filters only as narrowing operations. Cover every
   operation family so exact runtime scope cannot reveal adjacent job metadata.
5. Resolve detail and mutations through the canonical run scope before reading related metadata.
   Preserve exact action authorization, non-disclosing 404/403 semantics and redacted denial audit.
6. Reproduce the non-owner PostgreSQL failure, compare temporary-role grants with the canonical
   provision script/readiness contract and repair only the actual drift. Add a regression that fails
   when required bootstrap privileges diverge.
7. Update the three stale workflow-wait tests to current exact token/persisted-authority APIs and
   close directly related typing errors without weakening assertions.
8. Run focused then full SQLite/PostgreSQL, static, migration and secret/diff checks. Measure
   authorization query count/query plan for the bounded run page.
9. Follow manual-testing-guide section 0 before touching the local runtime, then run the mandatory
   browser gate with matched allowed/denied roles, direct URLs/POSTs, console/network review and
   redacted evidence.
10. Review the final diff as staff engineer, AppSec and SRE; update verification/current-behavior
    docs, master/component status and archive only after every release-blocking criterion is proven.

## Test plan

- Unit/queryset: active/unexpired assignment semantics, multiple additive responsibilities,
  inactive user/organization, selected-organization narrowing, stable filters and pagination.
- Console integration: unified/legacy list, detail and nested metadata, exact cancel, recovery,
  dashboard counts/links, invalid IDs, same-tenant other scenario and two-way cross-tenant probes.
- Role matrix: Global Admin, Organization Admin, Auditor, Project Admin/Viewer, Scenario
  Viewer/Editor/Release Manager/Runtime Operator/Approver and membership-only.
- Operation-family isolation: execution plus evaluation, question evaluation, ingestion, index
  build and connector sync rows in the same organization.
- Audit/redaction: visible-but-forbidden mutation, audit persistence failure behavior, no labels,
  consumer/actor data, event names, payloads, checkpoints or provider errors.
- PostgreSQL: exact matrix under non-owner role, FORCE RLS properties/policies, empty/wrong tenant
  scope, transaction-local scope reset, canonical grants/readiness drift and no forbidden DELETE.
- Workflow waits: suspend/resume/replay, forged token/tenant/actor, invalid payload, conflict,
  expiration, protected mapping, cancellation convergence and audit counts using current APIs.
- Quality/browser: repository commands plus the mandatory post-development browser gate.

## Rollout plan

Ship the authorization and grant/readiness correction as one release after PostgreSQL and browser
evidence passes. Before rollout, compare authorized run counts for synthetic role fixtures and
confirm database privileges on the deployment role. Monitor safe 404/403 rates and run-page errors;
do not log target content. No production data is accessed as part of this task.

## Rollback plan

Rollback must remain deny-safe. If the authorized query path fails, disable or return an empty run
surface for narrowly scoped actors rather than restoring organization-wide disclosure. Preserve
existing run/audit data. Revert test/provision/readiness changes only as a reviewed set; never
restore owner, superuser, `BYPASSRLS`, disabled FORCE RLS or broad default privileges. Use a
forward-fix for any security regression.

## Risks

- Securing `/console/runs/` while leaving detail, dashboard counts, legacy list or nested events
  inconsistent.
- Conflating organization membership with organization responsibility or runtime capability.
- Accidentally removing legitimate organization-auditor read access or exact runtime cancellation.
- Filtering after pagination/counting and leaking hidden row totals or producing unstable pages.
- Letting non-execution families inherit execution visibility in the unified projection.
- Query amplification from per-row `authorize` calls; prefer set-based persisted assignment scope
  with bounded queries, then exact action authorization for mutations.
- Treating a test-fixture grant omission as evidence for a broad production privilege change.
- Adding tenant RLS to the platform assignment table without a trustworthy tenant key.
- Audit records or expected-denial logs becoming a secondary metadata disclosure.

## Open questions

- Resolved: canonical deployment provisioning already contains the platform-assignment and user
  reads; only the temporary non-owner test fixture had drifted.
- Resolved: `project_operations` requires an explicit already-authorized execution queryset. This
  is the smallest boundary that prevents organization state from establishing run visibility while
  leaving every other operation family on its native scope.
- Resolved: existing denial-audit behavior remains unchanged; action denial does not depend on
  audit persistence succeeding. No new failure-policy contract was introduced.
- Resolved: this work enforces the already accepted exact-responsibility model, so current-behavior
  documentation is sufficient and no ADR is required.

## Status

**Implemented and verified on 2026-08-01.** All acceptance criteria are mapped in
`verification.md`; the task is ready for archival.

## Completion criteria

- Every acceptance criterion maps to passing evidence in `verification.md`.
- Applicable formatter, linter, type, unit/integration/security/PostgreSQL/migration/secret and
  browser checks pass with exact commands and counts recorded.
- Staff-engineering, application-security and SRE reviews find no unresolved release-blocking issue.
- Current-behavior documentation and planning status are updated only after verification; durable
  decisions move to an ADR if the approved contract changes.
