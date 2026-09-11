# Task Plan: scoped-operator-responsibility-authorization-redesign

## Task summary

Replace the mixed single-role membership plus object-assignment authorization model with a
deny-by-default, responsibility-based operator authorization model. An organization membership
will establish tenant affiliation only. Every human privilege—including organization
administration, visibility, authoring, release, runtime operation, document access and tool
approval—will come from an explicit, auditable assignment at organization, project, scenario or
document-set scope.

The owner confirmed on 2026-07-30 that all current users, roles and persisted application data are
disposable demo data. This task therefore does not preserve or backfill legacy membership roles or
delegated assignments. Implementation may use the repository's confirmed local `Fresh` reset path,
after resolving and re-confirming the exact live Compose environment at execution time. This plan
does not itself run a reset or delete data.

## Background

Current authorization combines two incompatible concepts:

- `OrganizationMembership.role` gives one broad role per user and organization.
- Separate project-administrator, scenario-editor and document-set-manager tables add object
  responsibilities.

That split makes a user choose a broad role when joining an organization even though later
responsibilities determine the exact resources they can manage. It also leaves most read
visibility membership-wide and represents tool approvers as organization-wide role strings.

Tool approval has a separate identity defect. A request stores `Consumer.subject` in the string
field `ApprovalRequest.requested_by`, while a decision compares that string with the human
operator's Django username. These are distinct actor classes and namespaces. The current
self-approval check is therefore normally ineffective and can falsely deny when unrelated
consumer and username strings collide.

The current mixed model was an incremental compatibility stage recorded by ADR-0013. The owner has
now chosen a clean target model and explicitly waived legacy data/role compatibility for the
disposable demo environment.

## Locked target architecture

### Membership

`OrganizationMembership` is roleless. It records only:

- exact organization and user;
- lifecycle status (`active` or `revoked`);
- creation and revocation provenance;
- timestamps.

An active membership permits authentication into the organization shell and display of the safe
organization label in navigation. It grants no project, scenario, document-set, approval, audit or
runtime access by itself.

Membership revocation is a top-level deny condition for every assignment. Revocation and
assignment deactivation happen atomically and remain auditable. Rows are retained; routine
membership removal does not physically erase authorization history.

### Responsibility persistence

Use one conceptual responsibility-assignment contract with typed persistence by scope. Do not use
`GenericForeignKey`, untyped target IDs or client-supplied capability lists.

- `PlatformResponsibilityAssignment`
- `OrganizationResponsibilityAssignment`
- `ProjectResponsibilityAssignment`
- `ScenarioResponsibilityAssignment`
- `DocumentSetResponsibilityAssignment`

Each tenant-bound assignment references the exact `OrganizationMembership`, stores the owning
`organization_id` for tenant filtering/RLS, references its typed target where applicable, and
stores:

- a closed responsibility enum valid only for that scope;
- `active`/`revoked` status;
- `assigned_by`, `revoked_by`, `assigned_at`, `revoked_at`;
- optional `expires_at`;
- a bounded, non-sensitive reason code.

Database constraints enforce valid status/provenance combinations and uniqueness of one effective
membership/responsibility/target assignment. Domain services re-derive organization lineage from
trusted targets under row locks. PostgreSQL FORCE RLS and app-role grants cover every new
tenant-bound table.

Global- and organization-administrator assignments are non-expiring: `expires_at` must be null for
those responsibility types. This makes the last-effective-administrator invariant enforceable;
temporary administrative elevation is a separate future design rather than an expiry-driven
lockout risk.

Typed tables are preferred over a single polymorphic table because database foreign keys,
scope-specific uniqueness and deletion protection are authorization controls.

### Closed responsibility vocabulary

The initial vocabulary is intentionally closed and code-owned:

| Scope | Responsibility | Effective authority |
| --- | --- | --- |
| Platform | `global_administrator` | Platform and organization administration across active organizations; no implicit protected document content or tool approval |
| Organization | `organization_administrator` | Manage organization lifecycle within approved bounds, memberships, responsibility assignments, projects/consumers and safe organization metadata |
| Organization | `organization_auditor` | Read safe organization metadata, audit and operational evidence; no mutation or protected content |
| Project | `project_viewer` | View the exact project and safe child-scenario metadata |
| Project | `project_administrator` | Project viewer plus project management, scenario creation and child-scenario viewer/editor delegation |
| Scenario | `scenario_viewer` | View exact scenario safe metadata, configuration summaries and authorized release/run summaries |
| Scenario | `scenario_editor` | Scenario viewer plus authoring and testing; no release, runtime control, approval or document content |
| Scenario | `scenario_release_manager` | Scenario viewer plus compile/promote/rollback/canary lifecycle for the exact scenario |
| Scenario | `scenario_runtime_operator` | Scenario viewer plus exact-scenario runtime pause/resume/cancel controls |
| Scenario | `scenario_approver` | View redacted approval context and decide tool approvals for the exact scenario |
| Document set | `document_set_metadata_viewer` | View exact set metadata and safe lifecycle status only |
| Document set | `document_set_content_reader` | Metadata viewer plus protected document/chunk content read |
| Document set | `document_set_manager` | Content reader plus content/source/index operations and scenario retrieval-grant administration for the exact set |

Responsibilities map centrally to a closed capability vocabulary. Callers request a capability
against trusted targets; they never inspect responsibility strings themselves. Responsibilities
are additive, but authority never crosses an organization or widens from an absent target.

`organization_administrator` may assign responsibilities but does not implicitly receive
`scenario_approver`, protected document-content or document-operation capability. This preserves
separation of duties. The exceptional Django superuser remains a separately audited
`superadmin_recovery` authority, not an assignable responsibility.

### Scope and inheritance

Initial inheritance is deliberately narrow:

- Platform administrator can bootstrap and administer organizations but receives no implicit
  protected content or approval authority.
- Exactly one active daily global administrator must exist; replacement is atomic. Django
  superadmin recovery is excluded from this invariant and is not daily authority.
- Organization administrator can see safe metadata throughout its organization and administer
  memberships/assignments.
- Project viewer/admin can see safe scenario metadata below the exact project.
- Project administrator may assign only scenario viewer/editor responsibilities within the exact
  assigned project. Scenario approver, release manager and runtime operator remain
  organization-administrator assignments.
- Scenario responsibilities never imply document-content access.
- Document-set responsibilities never imply project/scenario authoring or release authority.
- Scenario-to-document-set retrieval requires both an authorized exact-scenario requester/binder
  and approval by an exact document-set manager; neither side can create both authorities alone.
- There is no project- or organization-wide approver inheritance in the initial implementation.
  Approvals require an exact active `scenario_approver` assignment.

### Central authorization decision

Replace role-specific and compatibility predicates with one decision service that accepts:

- authenticated human user;
- closed capability;
- trusted organization and exact typed targets;
- optional decision-time context such as approval ID.

The service must:

1. validate active user and exact target lineage;
2. require active organization and active membership where applicable;
3. load only active, unexpired, target-matching assignments;
4. apply the closed responsibility-to-capability mapping;
5. return allow/deny, stable content-free reason and exact assignment authority source;
6. never derive authority from active-workspace session state, request role strings, object owner
   labels, artifact policy strings or frontend state.

Every console, API, CLI, task and worker action re-authorizes at execution/decision time. List
queries are filtered by the same effective scope before rendering counts, labels or options.

### Tool approval and actor identity

Remove membership role strings from tool-binding approval policy. A binding declares only whether
human approval is required and the supported bounded policy attributes; it cannot choose an
organization role that widens authority. The decision service always requires exact
`scenario_approver` authority for `invocation.scenario`.

Replace ambiguous string actors:

- `ToolInvocation.consumer` remains the authenticated machine requester.
- `ApprovalRequest.initiated_by_user` is an optional protected FK for a verified human initiator
  propagated through the server-owned execution context.
- `ApprovalRequest.decided_by_user` is a protected FK to the exact human decision maker.
- Remove `ApprovalRequest.requested_by` and string `decided_by`.

Self-approval denial applies only when `initiated_by_user` is present and equals the deciding user.
Autonomous consumer requests have no human self-approval comparison. Consumer subjects and human
usernames are never compared. Decision-time checks also require pending status, checksum match,
expiry validity, active membership, active exact scenario assignment, active organization and
non-revoked target/release context.

The approval list returns only approvals the operator may view; it does not render every pending
approval in the organization and merely disable decision controls.

### Project ownership

Remove `AIProject.owner_membership` and the compatibility `owner` authorization implication.
Project responsibility assignments are the authority and product representation of ownership.
If a non-authoritative business contact label remains useful, introduce it later as explicitly
non-authoritative metadata; it is not part of this task.

### Console experience

The access workflow becomes:

1. Add an existing active directory user to the organization without selecting a role.
2. Select that member.
3. Select responsibility scope and exact authorized target.
4. Select one closed responsibility valid for that scope.
5. Review granted capabilities and explicit exclusions.
6. Submit through the audited service.

The member page groups assignments by scope, shows expiry/revocation state, and supports exact
revocation. Target selectors are tenant- and actor-authorized. The organization-admin-only
membership form lists active, non-superuser identities not already active members; it does not
provision or search an external directory.

## Scope

- Replace role-bearing organization membership with roleless lifecycle membership.
- Replace existing delegated assignment tables with the typed responsibility model.
- Preserve global administrator and superadmin recovery semantics in the new central model.
- Expand the capability vocabulary to cover all current read/write surfaces explicitly.
- Replace all membership-role and compatibility authorization predicates in console, service,
  CLI, task and worker paths.
- Make object list visibility responsibility-scoped rather than membership-wide.
- Redesign tool approval policy, persistence, listing and decision authorization.
- Remove project owner membership as authorization/product ownership.
- Redesign organization user/access forms, views, templates and demo seed.
- Add destructive disposable-environment reset and clean-seed verification instructions using the
  existing confirmed `scripts/local-stack.ps1 -Action Fresh` path.
- Update RLS policies, app-role grants, tests, operator/user/security documentation, ADRs and
  planning authority.

## Non-goals

- Preserve, translate or backfill existing users, membership roles, assignments, approvals,
  projects, runs, releases, documents, audit rows or object-store data.
- Add an external ABAC/policy-engine dependency or database-configurable role designer.
- Add external directory search, provisioning or group synchronization.
- Add production data migration or in-place rollback.
- Add project/organization-wide approval inheritance, multi-party approval or temporary
  impersonation.
- Change consumer capability/binding authorization except where typed initiator identity and tool
  approval integration require it.
- Weaken tenant RLS, audit fail-closed behavior, self-approval protection for verified human
  initiators, or superadmin recovery alerting.

## Acceptance criteria

1. `OrganizationMembership` has no role field and an active membership alone grants only the safe
   organization shell.
2. All operator privileges come from active, unexpired typed responsibility assignments and a
   single central capability decision.
3. A user may hold multiple responsibilities across multiple exact scopes; cross-tenant and
   wrong-target assignments are rejected before any metadata disclosure.
4. Membership revocation atomically removes effective authority; no active or historical
   assignment can authorize a revoked/non-member user.
5. Global- and organization-administrator assignments cannot expire. The last effective
   organization administrator cannot be revoked or have membership removed without an atomic
   replacement/bootstrap operation.
6. Lists, detail views, counts, selectors and dashboards show only responsibility-authorized
   resources. Direct object URLs and forged IDs deny consistently.
7. Scenario A approvers cannot view or decide Scenario B approvals without a separate assignment,
   even inside the same organization/project.
8. Organization/project administrators can assign only the explicitly delegated child
   responsibilities and never gain approval or protected content implicitly.
9. Tool artifacts no longer accept `approver_roles`; approval decisions use exact scenario
   assignment and typed human actor identity.
10. Autonomous consumer requests do not run a meaningless human self-approval comparison. A
    verified human initiator cannot decide their own request. Equal consumer-subject and username
    strings do not create identity equality.
11. Every security-sensitive grant, revoke, membership lifecycle and approval decision is
    audit-required and rolls back on audit persistence failure.
12. New assignment tables have reviewed PostgreSQL FORCE RLS, non-owner app-role grants and
    cross-tenant tests.
13. No runtime source path relies on legacy `Role`, `membership.role`, legacy delegated assignment
    classes, `approver_roles`, string `requested_by` or string `decided_by`.
14. A clean local/demo environment can be recreated with migrations and a new seed that provisions
    roleless members plus explicit responsibilities. The reset is never run against an unresolved
    or production-like target.
15. SQLite and PostgreSQL suites, migration checks, lint, format, type checks, authorization
    matrix, RLS, audit, browser/accessibility and worker/CLI checks pass.
16. ADR-0013 is superseded by an accepted ADR describing this model; master plan, architecture,
    user guide, security overview and manual test guide agree with verified behavior.

## Affected components

- `apps/tenancy`: membership schema/lifecycle, tenant visibility helpers and active-organization
  resolution.
- `apps/identity`: responsibility models/services, central capability vocabulary/decision,
  superadmin/global-admin boundary and RLS.
- `apps/catalog`: remove project membership ownership and use project assignments.
- `apps/console`: access UI, scoped lists/details/counts/forms, organization bootstrap, approval UI
  and all legacy role gates.
- `apps/tools`: approval policy schema, requester/decider identity, list/decision services, CLI and
  proxy/runtime integration.
- `apps/releases`: exact scenario release responsibility.
- `apps/documents` and `apps/ingestion`: exact document-set read/content/operation/grant
  responsibilities.
- `apps/agents`, `apps/workflows`, `apps/evaluations`: exact scenario runtime/test/approval
  decisions and typed human initiator propagation.
- `apps/gateway` and `apps/mcp`: preserve consumer authentication while optionally propagating a
  verified human initiator only from trusted server context.
- `apps/audit` and `apps/observability`: assignment authority source and typed actor evidence.
- `deploy/postgres`, migrations, demo seed, local reset runbooks and tests.

## Interfaces affected

- Operator console membership and access forms change incompatibly.
- Tool artifact `spec.approval` removes `approver_roles`; compiler/proxy contracts and fixtures
  change atomically.
- Internal authorization service and reason/source vocabulary change.
- Tool approval models/CLI output use typed human decision identity.
- Project create/edit no longer selects/stores `owner_membership`.
- No public consumer execution endpoint or bearer-token wire-format change is intended.

## Data impact

All current relational and object-store data is treated as disposable demo data. There is no
legacy data backfill. The supported cutover recreates the local PostgreSQL and MinIO volumes and
clears ephemeral Redis state, then applies migrations and the new seed.

Migration history remains intact during implementation. Add/drop migrations express the new
schema, but old data-copy compatibility code is not added. Migration squashing/rebaselining is a
separate follow-up after the new clean-install path is verified.

The exact destructive execution target must be inspected immediately before reset using the
canonical Compose file and `local-stack.ps1 -Action Status`. Use the repository-confirmed typed
`Fresh` flow; do not use `Fresh -Force` in normal implementation or verification.

## Security impact

This is a security-positive redesign but a high-risk implementation:

- removes broad membership-derived visibility and organization-wide approver authority;
- creates explicit least-privilege scope and authority provenance;
- fixes cross-identity self-approval comparison;
- increases the number of authorization checks and denial paths;
- risks temporary privilege widening if any compatibility predicate remains reachable.

Cutover is atomic. Mixed old/new authorization, artifact policy or worker fleets are forbidden.

## Authorization impact

The owner approved this design direction and the disposable-demo-data assumption for planning on
2026-07-30. This planning request does not authorize implementation of the authorization changes or
execution of the destructive reset. Implementation requires an explicit approval for the exact
authorization scope; the reset requires a separate final review and confirmation of the resolved
live target immediately before execution.

Every action and read surface must be inventoried and mapped to a closed capability. A role or
assignment name is never checked outside the central decision service. UI filtering is usability,
not authority; service/worker/CLI paths re-authorize independently.

## Observability impact

Add bounded structured events/metrics for:

- membership and responsibility create/revoke/expire;
- authorization allow/deny by capability, scope kind, authority source and stable reason;
- approval view/decision denial by safe reason;
- destructive demo reset start/success/failure in the local operator output.

Do not log usernames as metric labels, document/tool input, consumer subjects, target names,
assignment free text, secrets or raw policy bodies. Security-sensitive mutations remain
audit-required and fail closed.

## Migration impact

This task uses a destructive clean-data cutover:

1. Add the new responsibility schema and updated runtime code in one feature branch.
2. Add migrations that remove role-bearing/legacy authorization fields and tables without
   backfill.
3. Verify empty-database migrate and seed on SQLite and PostgreSQL.
4. Stop all web/worker/beat processes after live-state inspection.
5. Run the confirmed local `Fresh` reset against the exact disposable Compose project.
6. Apply migrations, seed explicit memberships/responsibilities and restart one version-matched
   fleet.

No in-place production migration is supported. A non-empty, non-disposable environment is a hard
stop, not a best-effort migration target.

## Dependencies

- No new production dependency.
- Existing Django ORM, PostgreSQL RLS, audit service and local stack reset flow.
- Accepted replacement ADR before destructive implementation cutover.
- Exact authorization surface inventory and current runtime/Compose state.

## Implementation steps

### Milestone 0 — authority inventory and durable decision

1. Create an ADR superseding ADR-0013 and record the locked responsibility, inheritance,
   membership lifecycle, typed approval identity and destructive reset decisions.
2. Inventory every current use of `Role`, membership-wide reads, delegated assignment classes,
   `owner_membership`, `authorize`, `approver_roles`, `requested_by` and `decided_by`.
3. Map every console/API/CLI/task/worker action and read query to an exact capability and trusted
   scope. Treat graph results as navigation evidence and confirm every dynamic/decorator/registry
   path by direct code and tests.
4. Record the exact app-role table/RLS inventory and migration dependency graph.

### Milestone 1 — responsibility and membership foundation

1. Add closed responsibility enums and typed assignment models with lifecycle/provenance/expiry.
2. Add roleless membership lifecycle and active-membership deny semantics.
3. Add service boundaries for membership add/revoke and assignment grant/revoke using row locks,
   tenant lineage validation and audit-required transactions.
4. Enforce last-effective-organization-admin and atomic organization bootstrap.
5. Add FORCE RLS policies, app-role grants and non-owner PostgreSQL tests.

### Milestone 2 — central capability decision

1. Expand the capability vocabulary for explicit visibility, membership/assignment administration,
   approval, release, runtime, audit and current document operations.
2. Implement responsibility-to-capability mappings and exact scope inheritance in one module.
3. Return exact assignment authority source and stable safe reason codes.
4. Add a complete matrix test before migrating callers.
5. Add temporary comparison instrumentation only in tests/local verification; do not let the legacy
   decision grant authority after a new-model deny.

### Milestone 3 — read and mutation caller migration

1. Migrate organization/project/scenario/document-set list and detail scoping first.
2. Migrate membership, assignment, project/scenario creation, authoring and release services.
3. Migrate document, ingestion, evaluation and runtime controls.
4. Migrate CLI, Celery tasks, management commands, gateway/MCP-adjacent human context and all
   background/resume paths.
5. Remove membership-wide read assumptions and legacy role helpers only after their callers have
   denial tests.

### Milestone 4 — scenario-scoped approval and typed actors

1. Change tool artifact schema/compiler/proxy contract to remove `approver_roles`.
2. Persist optional verified human initiator separately from the consumer.
3. Persist exact human decider FK and migrate audit events to typed actor references.
4. Filter approval queues by exact scenario visibility/approval authority.
5. Re-authorize exact `scenario_approver` assignment at decision time.
6. Implement self-approval only for a matching verified human initiator.
7. Cover autonomous consumer, human initiator, identity-string collision, revoked assignment,
   expiry, checksum, concurrent decision and cross-scenario cases.

### Milestone 5 — console and seed

1. Remove role selection/change UI from membership lifecycle.
2. Replace the overloaded assignment form with scope → target → responsibility → review.
3. Show effective assignments, exclusions, expiry and revocation per member and per object.
4. Remove project owner membership UI/persistence.
5. Rewrite demo seed to create roleless memberships and explicit responsibilities.
6. Update navigation/dashboard empty states for members with no assignments.

### Milestone 6 — destructive schema cleanup and clean cutover

1. Add destructive migrations dropping membership role, legacy assignment tables, owner fields and
   obsolete approval identity/policy fields.
2. Prove empty-database migration and seed on SQLite and PostgreSQL.
3. Inspect canonical Compose and health state; stop the exact versioned fleet.
4. Execute the typed-confirmation `Fresh` reset only against the owner-confirmed disposable local
   environment.
5. Rebuild/migrate/seed/start one version-matched web/worker/beat fleet.
6. Prove no stale worker can consume old contracts.

### Milestone 7 — closure

1. Remove runtime imports/references to legacy authorization and add static absence checks.
2. Run the full Definition of Done matrix and authenticated browser journeys.
3. Review the diff as staff engineer, AppSec and SRE; resolve all critical/high findings.
4. Update ADR, master/Phase 2.8 plan, architecture, security overview, user guide and manual test
   guide to verified current behavior.
5. Record verification evidence and archive the task only after owner acceptance.

## Test plan

### Authorization matrix

- Anonymous, inactive user, revoked membership, membership-only user and disabled organization.
- Every responsibility against every capability at exact, parent, sibling, child and foreign
  tenant scopes.
- Multiple additive responsibilities and expiry boundaries.
- Project-child visibility/delegation without cross-project access.
- Project admin cannot delegate scenario approval/release/runtime authority; organization admin can
  grant those exact responsibilities without receiving them implicitly.
- Organization/global admin exclusions for approval and protected content.
- Last organization admin concurrency and audit rollback.

### Read and metadata non-disclosure

- List, detail, count, selector, dashboard and direct-URL tests for unassigned/sibling/foreign
  targets.
- Safe organization shell for membership-only users with no project/scenario/document metadata.
- Approval queue excludes unauthorized scenarios rather than rendering disabled rows.

### Approval

- Scenario A approver allow; Scenario B/sibling/foreign deny.
- Revoked/expired assignment after request but before decision denies.
- Autonomous consumer has no human self-approval comparison.
- Verified initiating human cannot decide own request; another assigned human can.
- Equal consumer subject and human username remain distinct.
- Pending/expired/already-decided, checksum mismatch, concurrent decisions and audit failure.
- CLI and console use the same decision service.

### Persistence, migration and RLS

- Model/service constraints for wrong scope/responsibility and cross-tenant targets.
- SQLite forwards/reverse behavior where supported.
- PostgreSQL clean migration, FORCE RLS table inventory and non-owner tenant isolation.
- App-role grant inventory and provisioning/rollback scripts.
- Clean seed and local `Fresh` recreation with no legacy role/assignment data.

### Regression and quality

- Full Django unit/integration suite.
- Gateway/MCP, release, tool, workflow, agent, document, ingestion and evaluation suites.
- Ruff lint/format, mypy, Django check and migration-drift checks.
- Frontend build/tests where access UI assets change.
- Authenticated browser keyboard, screen-reader, responsive and empty-state journeys.
- Secret scan and final static searches for removed runtime contracts.

## Rollout plan

1. Documentation/ADR and exact inventory.
2. Implement and verify on an isolated branch/worktree with disposable SQLite/PostgreSQL.
3. Build one immutable application revision containing schema, callers, seed and workers.
4. Inspect local Compose/health state immediately before the destructive action.
5. Stop the fleet, run the typed-confirmation `Fresh` reset, migrate and seed.
6. Start one version-matched fleet and run health, authorization, approval and manual smoke gates.
7. Accept only after evidence shows no legacy runtime reference or unauthorized metadata path.

This plan authorizes no production rollout. Any non-disposable environment requires a new data
inventory, migration design and explicit approval.

## Rollback plan

Rollback is not an in-place schema downgrade. Because data is disposable:

1. stop the new fleet;
2. restore the previous code revision;
3. run the confirmed local `Fresh` reset against the exact disposable Compose project;
4. apply the previous migrations and previous seed;
5. restart one previous-version fleet and run its health/smoke checks.

Do not run mixed old/new workers or attempt to reinterpret new assignments as legacy roles.

## Risks

- Missing one membership-wide queryset leaks metadata despite correct mutation authorization.
- A legacy role helper left reachable can widen a new-model deny.
- Incorrect scope inheritance can grant sibling project/scenario access.
- Assignment/membership revocation races can leave transient authority.
- Generic or untrusted target identifiers can bypass tenant lineage.
- Tool policy/compiler/runtime versions can diverge during cutover.
- Destructive reset can target the wrong Compose project or erase non-demo data.
- Removing project owner fields can break forms, GitOps fixtures or seed assumptions.
- RLS/app-role inventory drift can make tests pass as database owner but fail or leak in production
  posture.
- An over-flexible responsibility vocabulary can become an unsafe custom-role engine.
- Narrow approval assignments can create availability gaps; dashboards must surface “no active
  approver” without widening authorization.

## Open questions

No architecture-blocking product question remains for the initial implementation. The following
are deferred enhancements, not reasons to widen the first cut:

- multi-party/four-eyes approval beyond one exact scenario approver;
- project-level approver inheritance;
- directory search/provisioning;
- time-bound just-in-time elevation;
- database-configurable custom responsibility bundles;
- production data migration.

## Status

In progress. Implementation authorization was granted by the owner on 2026-07-30. Clean
SQLite/PostgreSQL migration evidence and exact local Compose target review were completed; the
owner-authorized local demo database was flushed and reseeded with roleless memberships and typed
responsibilities on 2026-07-31. Builder protected content and workflow human decisions now use
exact scenario authority; workflow-authored role strings were removed. The repository-wide
role-era test conversion is complete and the final SQLite suite passes 1,047 tests with 60
PostgreSQL-only skips. Ruff and migration-drift checks pass. Full PostgreSQL regression,
browser/accessibility, type-check and final task archival remain.

## Completion criteria

- All acceptance criteria are separately marked Implemented and Verified with command/evidence
  links.
- The applicable formatter, linter, type, unit, integration, PostgreSQL/RLS, migration, security,
  audit, browser and clean-reset checks pass.
- No unresolved critical/high staff-engineer, AppSec or SRE finding remains.
- Checks not run, assumptions and residual risks are explicit.
- Replacement ADR and current-state documentation are accepted.
- Task verification is recorded, the master plan is updated and the completed task is archived
  according to planning policy.
