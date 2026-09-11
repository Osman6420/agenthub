# Task Plan: Phase 2.8 Part 2.1 — Scoped authorization and superadmin recovery

> Archived after verified completion on 2026-07-24.

## Objective

Replace organization-wide content roles with a small, explicit authorization model that supports
one daily Global Admin, delegated organization/project/scenario/document-set responsibility,
scenario-to-document-set access and a separate fixed superadmin recovery identity. Administrative
authority must not implicitly disclose document content.

## Owner or responsible area

Identity, tenancy, catalog, documents, releases, runtime control, console and observability.

## Status

**Completed and automatically verified 2026-07-24.** The owner approved every decision in the
approval gate and explicitly approved the authorization/additive-migration implementation on
2026-07-23. The first reviewable slice adds ADR-0013, the central capability decision contract and
the single daily Global Administrator identity without switching existing endpoints. This plan
supersedes the intended long-term use of organization-wide
`scenario_editor`, `document_manager`, `release_manager` and unrestricted Django-superuser bypass.
Current behavior remains authoritative until an implementing task is approved, migrated and
verified.

Slice 4 is complete. Scenario compile/evaluate, promote, canary and rollback entry points use
`scenario.release`; document-set index and connector automation promotion use exact
`document_set.operations.manage`; tool-approval compatibility role resolution uses
`platform.manage`. The broad `can_manage_releases` runtime predicate has been removed while legacy
role values remain only for the Slice 5 reset/compatibility gate. Disabled-organization denial and
existing console/CLI error contracts remain stable.

Slice 5 connects the existing audited delegated-assignment
services to the organization Access page: tenant-filtered member and object choices, explicit
Project Administrator / Scenario Editor / Document Set Manager responsibilities, safe assignment
summaries and exact removal. Organization-wide membership forms stop offering legacy content and
release roles. Stored legacy values remain readable but are not offered by current assignment
surfaces; their destructive demo reset was not required for this non-destructive closure.
Superadmin use is fail-closed audited and immediately alertable, with an operator runbook.

## Scope

- Introduce application-level `global_admin`, delegated `organization_admin`, `project_admin`,
  object-scoped `scenario_editor` and object-scoped `document_set_manager` authority.
- Keep one user eligible for different roles in multiple organizations and object scopes.
- Remove `release_manager` from the target product model. Only Global Admin and the owning
  Organization Admin may publish, promote, roll back or resume a governance-paused release.
- Do not introduce a `document_set_user` person-role. A scenario receives `retrieve` authority over
  a document set; authorized users operate the scenario.
- Separate document-set metadata and operational status from document names, content, previews,
  downloads, raw chunks, retrieval context and connector secrets.
- Separate the daily Global Admin account from a technical Django superadmin recovery account.
- Keep every application user's authority fixed. Add no elevation, temporary-access or
  two-administrator approval subsystem; exceptional intervention uses the superadmin account.
- Align Part 7 kill switches with the same capability model and asymmetric stop/resume rules.

## Non-goals

- General-purpose ABAC or policy-language evaluation.
- A role per UI screen or CRUD verb.
- User-level document-set consumption grants.
- Automatic access inheritance from project membership to document content.
- Impersonation, silent login-as-user or mutable/deletable audit evidence.
- Application-managed temporary privilege, approval or impersonation workflows.

## Baseline before Part 2.1

- `OrganizationMembership` stores one role per user per organization and supports membership in
  several organizations.
- Django `is_superuser` is treated as platform admin and currently bypasses organization
  authorization broadly.
- `organization_admin`, `project_owner`, `scenario_editor` and `document_manager` capabilities are
  organization-wide helper sets. Organization Admin and Scenario Editor currently enter the
  document-management mutation predicate.
- `ScenarioDocumentSetBinding` represents scenario configuration. `DocumentSetGrant` supports an
  opaque `USER`/`GROUP` principal shape but only consumer retrieval grants are currently enforced.
- No project grant, scenario grant or application Global Admin model exists.
- Durable global/organization runtime control and audit foundations exist and are extended by
  Phase 2.8 Part 7.

## Target state

### Roles and scopes

| Role | Scope | Normal authority | Explicit exclusions |
| --- | --- | --- | --- |
| Global Admin | Platform and all organizations | System operations, organization/project/scenario administration, release/publish, global/org kill switches | Document content, raw retrieval context and connector secrets |
| Organization Admin | One or more organizations | Membership, project/scenario administration, release/publish, organization kill switch | Document content and normal document-set grant approval |
| Project Admin | One or more projects | Project/scenario administration and editor assignment | Publish, release rollback, run cancellation, pause/resume, document content and document-set grant approval |
| Scenario Editor | One or more scenarios | Edit/test assigned scenarios and use document sets already granted to those scenarios | Publish, all operational stop/resume actions, raw retrieval context, document content and grant approval |
| Document Set Manager | One or more document sets | Documents, profiles, indexing, quarantine and scenario retrieve-grant approval | Scenario editing, release and organization administration |

An application Global Admin does not require materialized membership rows for every organization.
Delegated roles remain explicit, tenant-bound records. A person may hold different delegated roles
in different organizations.

### Capability contract

Authorization services use named server-side capabilities rather than broad role bypass:

```text
platform.manage
organization.manage
project.manage
scenario.edit
scenario.test
scenario.release
document_set.metadata.read
document_set.retrieve.grant
document_set.content.read
document_set.content.manage
document_set.operations.manage
runtime.cancel
runtime.pause
runtime.resume
```

Global Admin receives administration, release and runtime capabilities but does not receive
`document_set.content.read`, `document_set.content.manage` or raw retrieval-debug authority by
default. Django `is_superuser` is not a normal capability source.

### Scenario-to-document-set authority

Document-set consumption is service/object authorization:

```text
ScenarioDocumentSetGrant(
    organization,
    scenario,
    document_set,
    permission="retrieve",
    granted_by,
    granted_at,
    revoked_by,
    revoked_at,
)
```

- A Document Set Manager for the target set grants or revokes scenario retrieval.
- A Project Admin or Scenario Editor may bind only a set with a current grant.
- A binding configures use; it does not grant use.
- Admission and every retrieval operation revalidate the active scenario, binding, grant and common
  organization lineage.
- Revocation blocks new retrieval immediately without rewriting immutable release history.
- Global/Organization Admin may see safe set metadata and grant state but cannot create a normal
  grant, because doing so could indirectly disclose content through a controlled scenario.

### Release authority

Only Global Admin and the owning Organization Admin can publish, promote, roll back or reactivate a
released scenario. Project Admin prepares and validates changes but cannot publish. Scenario Editor
edits and tests assigned scenarios but cannot publish.

### Data-visibility contract

Global/Organization/Project Admin and Scenario Editor may receive safe set name, public identifier,
availability, index health, responsible manager and bounded error code where required. They do not
receive document lists, filenames, previews, downloads, raw chunks, raw retrieval context,
embeddings, connector secrets or unsafe provider errors.

The system must measure whether retrieval reached the correct document and chunk. Scenario Editor
may see document/source labels, identifiers, ranks, scores and aggregate retrieval metrics, but not
chunk text or surrounding context. A person with `document_set.content.read` may inspect chunk text
and bounded context. Scenario Editor alone must not receive raw document/chunk content. Tests cover
direct and prompt-based indirect disclosure.

## Console UX and user journeys

Part 2.1 includes the complete responsive console experience; object grants must not ship as
API/admin-only features.

### Navigation and information architecture

- Keep the mandatory active-organization selector. It narrows navigation but never grants access.
- Add **Access** under organization administration for members, delegated roles and pending access
  requests.
- Add an **Access** tab to project, scenario and document-set detail pages. Do not introduce a
  separate global role-management application for ordinary delegated work.
- Part 7 owns the primary **Runs & controls** page and global/organization/project/scenario pause
  controls; Part 2.1 supplies the central authorization services and reusable status
  components.

### Organization access page

The organization page shows one row/card per member with safe identity label, organization role,
delegated project/scenario/document-set counts, status and last role update. Expanding a member
shows exact assignments without document names/content. Available actions are capability-filtered:

- Global Admin may add/remove the owning Organization Admin and inspect all safe assignments.
- Organization Admin may add organization members and assign Project Admin, Scenario Editor and
  Document Set Manager scopes inside the organization.
- Project Admin may assign Scenario Editors only inside an assigned project if this delegation is
  owner-approved before implementation.
- No form offers `global_admin`, Django superadmin or document content access
  as an ordinary membership role.
- Exact username lookup remains non-enumerating; unknown/inactive users receive a safe error.
- Removing the last effective Organization Admin is denied with an actionable explanation.

The assignment flow is a guided drawer/page rather than one overloaded role dropdown:

1. Select responsibility type.
2. Select one or more authorized objects within the active organization.
3. Review resulting capabilities and explicit exclusions.
4. Submit with CSRF protection; show audit-safe success or denial.

Bulk assignment may select several projects, scenarios or document sets, but the service writes and
audits explicit object rows. Partial success is not allowed.

### Project access page

Show Project Admins and Scenario Editors grouped by scenario. Project Admin can create and edit
project scenarios according to the approved product decision but sees only document-set safe
metadata already granted to those scenarios. The release action is absent, not merely disabled, for
Project Admin; an explanatory status states that Global/Organization Admin publishes.

### Scenario access and data page

Show:

- Scenario Editors and inherited administration authority.
- Currently bound document sets and separate grant state: `requested`, `granted`, `revoked` or
  `expired/not applicable`.
- Safe document-set metadata only: display name, health/status, responsible manager and grant
  timestamp. Never show document lists, filenames, previews or raw chunks.
- **Request document set access** for Project Admin/Scenario Editor. The picker is restricted to
  safe, discoverable sets in the same organization and creates a request, not a grant.
- **Bind** only after grant approval; binding and permission remain visibly distinct.
- A revoked grant immediately marks the binding unusable and explains that a Document Set Manager
  must approve access again.

Scenario test and retrieval diagnostics calculate correctness against expected document/chunk
identifiers. Scenario Editor sees document/source labels, expected versus retrieved identifiers,
ranks, scores, Hit@K, Recall@K, MRR, nDCG, citation/evidence coverage and bounded latency/error
metrics. Content-authorized Document Set Managers may additionally inspect the matching chunk and
bounded surrounding context. A Scenario Editor who needs that inspection can separately receive
Document Set Manager/content authority for the relevant set; Scenario Editor alone does not imply
it. A scenario with only production `runtime_retrieve` authority cannot be freely prompt-tested
against protected data by a non-content-authorized editor.

### Document-set access page

Document Set Managers see:

- Assigned managers.
- Pending scenario access requests with requesting project/scenario, safe owner/editor labels,
  requested purpose and timestamp.
- Active/revoked scenario retrieve grants.
- Approve, reject and revoke actions with consequence preview and bounded reason.
- Document/index/profile controls already owned by the document surface.

Approval never grants a person document access; it grants the exact scenario `retrieve` permission.
Revocation warns that new retrieval stops immediately and may affect released scenarios. Global and
Organization Admin see safe grant status but no normal approve/regrant action.

### Kill-switch presentation

- Every affected page shows the strongest effective pause and its scope/source without exposing
  sensitive payloads.
- Stop/cancel is available only to Global/Organization Admin and applicable automated safety
  controls; it requires a bounded reason. Immediate safety stop never waits for content approval.
- Resume is shown only when the actor can clear the exact control provenance. Otherwise the UI
  names the required role without exposing private actor data.
- Project Admin and Scenario Editor have no run cancellation, pause or resume controls. Their pages
  show safe operational status and direct them to Organization Admin when intervention is needed.
- Document Set Manager receives ingestion pause/quarantine and scenario-grant revoke controls on
  the document-set page.

### UX states and accessibility

All pages provide loading, empty, filtered-empty, denied, stale/revoked, disabled-organization,
audit-failure and concurrent-update states. Destructive/revocation consequences are described
before confirmation. Status never relies on color alone; dialogs/drawers trap and restore focus;
tables collapse to labelled cards; keyboard, screen-reader, skip-link, error-summary and target-size
requirements follow the console accessibility baseline.

### Daily administration and superadmin recovery

- The daily Global Admin is an application role on a non-superuser account and always uses its fixed
  product permissions.
- A separate Django `is_superuser` superadmin account is retained for exceptional intervention and
  authorization/identity recovery.
- No application elevation, temporary privilege, approval queue, expiry banner or emergency-access
  data model exists.
- For the initial stage, superadmin uses a unique strong password, guarded credential storage,
  rotation and immediate login alerting. Phishing-resistant MFA is deferred to Phase 3 by owner
  decision on 2026-07-24. The account is not offered through organization/member role forms.
- The central authorization boundary recognizes superadmin directly, so individual endpoints do not
  add special elevation branches.
- Every superadmin document list/view/add/delete, document-set grant/revoke, role mutation, release
  mutation and runtime-control action emits a dedicated high-severity audit event and immediate
  alert. Superadmin cannot erase or weaken audit evidence.
- A guarded recovery runbook defines login, intervention, evidence review and logout/credential
  handling. Superadmin remains an exceptional human operating mode, not a normal product role.

## Interfaces

- Central authorization service for roles, object grants and superadmin recovery authority; views,
  APIs, tasks and workers
  do not reconstruct predicates.
- Responsive console pages and reusable components for delegated role assignment, scenario-to-set
  grant requests/decisions, effective-capability explanations and current runtime controls.
- Closed audit schemas for role/grant/superadmin/kill-switch attempts and outcomes.
- Safe reason codes and public identifiers only in logs and metrics.

## Data flows

1. Admin assigns a delegated role within trusted tenant/object lineage.
2. Scenario author requests an existing document set for a scenario.
3. Target Document Set Manager approves or rejects the retrieve grant.
4. Author binds only an authorized set; release compilation records the binding but not a new grant.
5. Runtime reauthorizes binding plus live grant before retrieval.
6. Exceptional intervention uses the separate superadmin identity and is specially audited.
7. Kill-switch changes flow through Part 7 controls independently of document content authority.

## Security boundaries

- Active organization and client-supplied role/scope/grant fields never grant authority.
- Every delegated object and grant must share direct organization lineage; PostgreSQL RLS remains a
  second layer, not the sole authorization mechanism.
- List querysets are authorization-filtered before search, count, pagination or serialization.
- Stop authority is deliberately broader than resume authority; neither implies content access.
- Audit failure rolls back role, grant and kill-switch mutations.
- Only the exceptional superadmin identity bypasses fixed application roles; its use is alerted and
  specially audited.
- See
  [the companion threat model](threat-model.md).

## Dependencies

- Verified Phase 2.8 Parts 1–2 organization context and membership management.
- Part 3 unified workflow/runtime contract.
- Part 4 scenario authoring/release services.
- Part 5 document profiles/index operations and set manager surface.
- Part 7 unified operations and kill-switch controls.
- Existing tenant/RLS, audit and authentication infrastructure; initial superadmin password
  custody, rotation and alerting require a separately reviewed operations design. Phishing-resistant
  MFA is a Phase 3 hardening dependency, not a Slice 5 completion gate.

## Milestones

1. Record an ADR for the capability model, superuser boundary, delegated scopes and scenario-to-set
   grant semantics.
2. Obtain owner approval for every decision in the approval gate below; add annotated desktop and
   narrow-screen wireframes for organization/project/scenario/document-set access.
3. Inventory every current role predicate, superuser bypass, list queryset, background task and
   release/document mutation; define a compatibility and denial matrix.
4. Add Global Admin, project/scenario/document-set assignments and scenario-to-set grants with
   tenant constraints, RLS, audit and additive migrations.
5. Move release authority to Global/Organization Admin only; remove runtime dependence on
   `release_manager`.
6. Build the organization/project/scenario/document-set access UI and enforce content/metadata
   separation plus live scenario grant checks across console, APIs,
   ingestion, retrieval, evaluation and workers.
7. Add superadmin high-severity audit/alert coverage and the guarded recovery runbook; add no
   product elevation UI or data model.
8. Apply the kill-switch matrix and reusable control UX in Part 7, run migration/compatibility
   rollout and remove obsolete
   organization-wide roles only after no live assignments remain.

## Risks

- A scenario can become a document-exfiltration proxy even when direct document pages are hidden.
- Broad `is_superuser` checks or forgotten task/worker paths can bypass the capability service.
- Revoked grants may remain effective in caches, queued work or released artifacts.
- Role migration can overgrant existing organization-wide editors/managers.
- The guarded superadmin recovery path can bypass normal data separation and must remain tested,
  alerted and exceptional rather than becoming routine access.
- Overly narrow recovery controls can prevent incident response; overly broad controls defeat data
  separation.

## Open decisions

Implementation cannot start until every remaining `Open` row is approved. Confirmed rows record the
owner's current product decision:

| Decision | Status | Product decision / recommended default |
| --- | --- | --- |
| Who may create scenarios? | **Confirmed 2026-07-23** | Global/Organization/assigned Project Admin; Scenario Editor edits only assigned scenarios |
| May Project Admin assign Scenario Editors? | **Confirmed 2026-07-23** | Yes, only inside an assigned project; cannot grant Project Admin or document roles |
| Scenario Editor operational authority | **Confirmed** | None: cannot cancel runs, pause or resume |
| Project Admin operational authority | **Confirmed** | None: cannot cancel runs, pause or resume |
| What safe document-set metadata may admins/editors see? | **Confirmed** | Set/document/source display labels, public IDs, health, manager and grant state may be shown; chunk text/context still requires content authority |
| Retrieval development and diagnostics exposure | **Confirmed** | Scenario Editor sees document/source labels, IDs and retrieval metrics but no chunk text/context; content-authorized users see bounded chunk context; only content-authorized editors may freely prompt-test protected data |
| Who approves scenario-to-set retrieve grants? | **Confirmed 2026-07-23** | An assigned Document Set Manager only |
| Application elevation model | **Confirmed** | None: no temporary-access table, approval flow, expiry or per-action elevation code |
| Superadmin authentication | **Reconfirmed 2026-07-24** | Initial stage: separate non-daily identity with a unique strong password, guarded storage, rotation and monitoring; phishing-resistant MFA is deferred to Phase 3 |
| Superadmin alert recipients and evidence retention | **Confirmed 2026-07-23** | Immediate security/operator alert and retention under the security-audit policy |
| Legacy role/data handling | **Confirmed** | Existing assignments/users are demo-only and may be reset after environment verification; no production-style role backfill |
| Revocation effect on released scenarios | **Confirmed 2026-07-23** | Immediate denial of new retrieval; immutable release stays recorded but cannot bypass live grant |

These product decisions do not authorize implementation changes by themselves. Authentication,
authorization and migration work still requires the explicit implementation approval mandated by
the repository change policy. That approval was given by the owner on 2026-07-23.

## Implementation slices

- [x] Slice 1: ADR-0013, single daily Global Administrator record, central capability vocabulary
  and deny-by-default decisions for Global/Organization Admin and superadmin recovery.
- [x] Slice 2: project/scenario/document-set assignments and audited mutation services.
- [x] Slice 3: scenario-to-document-set request/grant/revocation model and live enforcement.
- [x] Slice 4: release and existing endpoint migration away from broad legacy roles.
- [x] Slice 5: responsive access UI, superadmin alerting/runbook and final compatibility cleanup.

## Testing strategy

- Positive and negative capability matrix for every role/action/scope.
- Browser journeys for each access page, assignment drawer, request/approve/revoke lifecycle and
  kill-switch visibility/resume provenance.
- Multiple-organization, multiple-project, multiple-scenario and multiple-document-set assignments.
- Forged/cross-tenant object IDs, stale/revoked grants, disabled organizations and RLS probes.
- Release denial for Project Admin/Scenario Editor and success for Global/Organization Admin.
- Direct and indirect document disclosure tests, including scenario test/debug output.
- Superadmin fixed-authority, high-severity audit/alert, credential/runbook and non-routine-use
  tests.
- Accessibility tests for keyboard/focus/error summaries/status text; responsive desktop and
  narrow-screen visual verification; safe empty/denied/concurrent-update states.
- Worker/admission/cache race tests for grant revocation and runtime controls.

## Observability requirements

Audit authorization decision, action, safe target, actor, effective authority source, outcome,
reason and trace. Emit bounded counts for denials, superadmin login/actions and kill-switch state
without tenant, user, document or run identifiers in metric labels. Alert immediately on every
superadmin login and sensitive action.

## Rollout

Add tables and central enforcement before removing old predicates. Verify conclusively that the
target database is the disposable demo environment, then reset demo users/assignments instead of
backfilling broad legacy roles. Any non-demo or protected data invalidates this shortcut and
requires a separately approved inventory/migration. Introduce explicit assignments, measure
denials, then switch each surface to the central service. Remove obsolete role choices only after
reset rehearsal, rollback evidence and explicit authorization-change approval.

## Rollback

Disable new assignment UI and restore the previously verified predicates through a
versioned compatibility flag while retaining all audit and grant rows. Do not roll back by granting
superuser, widening RLS, deleting denial tests or clearing kill switches.

## Completion criteria

The ADR and current-state documentation are updated; all capability/list/worker/release/content
boundaries pass unit, integration, PostgreSQL RLS, concurrency, security, migration, browser and
runbook verification; no unrestricted superuser bypass remains in normal application paths; staff,
AppSec and SRE reviews close; task evidence reaches Verified.

## Links

- [Phase 2.8 plan](../../phase-2-8-plan.md)
- [Phase 2.8 Part 7 plan](../../../tasks/phase-2-8-part-7-unified-runs-kill-switch/plan.md)
- [Current security overview](../../../security-overview.md)
- [Threat model](threat-model.md)
