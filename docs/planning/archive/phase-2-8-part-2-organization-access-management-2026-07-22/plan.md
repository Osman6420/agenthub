# Task Plan: Phase 2.8 Part 2 — Organization and access management

## Task summary

Make one validated organization the mandatory console workspace, add governed organization and
membership management, introduce the document-only role, and remove tenant/parent selectors from
contextual create flows.

## Background

Part 1 added a working organization selector but retained a cross-organization state and forms that
accept organization or project choices. Organization membership is already unique per
`(organization, user)` and carries one role. Console authorization is server-side; this part must
preserve that boundary while making the UI reflect it.

## Scope

- Remove “Tüm organizasyonlar”; keep the last valid selection or choose the deterministic first
  authorized organization ordered by `name`, `slug`, `pk`.
- Add platform-admin-only organization creation in the selector/organization management surface.
  Create the organization and its required initial `organization_admin` atomically, then select it.
- Add an active-organization “Kullanıcılar ve yetkiler” page for listing, adding, changing and
  removing memberships using existing directory/Django users only.
- Add `document_manager` to the single-role model. Organization admins retain document authority;
  document managers gain document/set/source/index authoring only and no project, scenario,
  consumer, release or membership administration.
- Remove organization from new Project, DocumentSet and Consumer forms. Derive it from the
  revalidated active organization at POST time.
- Make scenario creation project-context-only. Remove the project selector and bind the trusted,
  authorized project from the contextual route.
- Authorize an object before aligning an authorized cross-organization deep link to that object's
  workspace. Never reveal foreign metadata while resolving context.
- Add role-honest explanations and accessible empty/denial states.

## Non-goals

- Multiple roles per membership, user/account provisioning, LDAP group administration or SSO
  changes.
- Changing consumer bearer authentication or public gateway authorization.
- Document search profiles, summaries, question sets, unified runtime or kill switches.
- Treating active organization, submitted role labels or form parents as authority.

## Authorization matrix

| Action | Platform admin | Organization admin | Document manager | Other roles |
| --- | --- | --- | --- | --- |
| Create organization + initial admin | Allow | Deny | Deny | Deny |
| List memberships in active org | Allow | Allow | Deny | Deny |
| Add/change/remove membership | Allow | Allow in own org | Deny | Deny |
| Create project/consumer | Allow | Allow in active org | Deny | Existing predicates |
| Create scenario in project | Allow | Existing author predicate | Deny | Existing author predicate |
| Manage documents/sets/sources/indexes | Allow | Allow | Allow in own org | Existing predicate only where intentionally retained |

An organization administrator cannot assign `platform_admin` because that authority remains Django
`is_superuser`. The last organization-admin membership cannot be removed or changed to another role.
Disabled organizations remain readable under existing rules and reject mutations.

## Acceptance criteria

- No console page offers or displays “Tüm organizasyonlar”. Multi-org users always have one valid
  workspace; users with no accessible organization receive a non-disclosing no-workspace state.
- Forged, stale, revoked or disabled selections never widen scope.
- Organization creation is platform-admin-only, audited, atomic and results in an initial admin.
- Membership mutations are tenant-scoped, single-role, audited and fail closed when audit fails.
- `document_manager` can perform only the documented document-plane actions.
- Project, set and consumer create requests cannot select a foreign organization; scenario requests
  cannot select a foreign project through form/query tampering.
- Contextual create forms preserve server-generated identifiers and existing validation/audit paths.
- Browser, keyboard and screen-reader journeys explain the current organization and required role.

## Affected components and interfaces

Console context/scoping, forms/views/templates/routes and tests; tenancy role/capability services and
membership model choices; document authorization predicates. Existing canonical object URLs remain,
but create URLs become contextual where needed. No public gateway contract changes.

## Data and migration impact

Add the `document_manager` role choice with a reviewed migration if Django detects a field-choice
change. No membership cardinality or existing role is rewritten. Organization creation adds an
initial membership transactionally. No tenant data is deleted.

## Security, privacy and observability

The active workspace is session presentation state. Every service loads and authorizes the target
organization/object independently. Membership audit records contain safe user/organization IDs,
old/new role labels, outcome and reason, not directory attributes or session values. Page views are
not business-audited; state changes are fail-closed audited.

## Dependencies

Verified Part 1 shell, existing tenancy predicates and membership uniqueness. Part 5 consumes the
document-manager contract; it must not redefine the role.

## Implementation steps

1. Freeze an explicit action-level authorization matrix and add denial tests before UI work.
2. Change workspace resolution to mandatory deterministic selection; update selector, dashboard and
   list tests, including revoked membership and platform admin behavior.
3. Add transactional organization creation with required initial admin and audit rollback.
4. Add membership forms/services/routes with row locking, last-admin protection and safe user
   selection; keep all writes behind organization/platform admin predicates.
5. Add `document_manager` and apply its least-privilege predicate to every current document mutation;
   verify it is absent from project/scenario/consumer/release actions.
6. Refactor contextual create handlers so trusted active organization/project is injected server-side
   and removed from submitted form fields.
7. Update explanatory copy, accessibility semantics and manual testing instructions.
8. Review migrations, RLS impact, audit behavior and final diff as staff engineer/AppSec/SRE.

## Test plan

- Happy paths for selection, organization creation, membership lifecycle and contextual creates.
- Anonymous, no-membership, wrong-role, disabled-org, cross-tenant object/user/parent and forged
  session/POST denial.
- Last-admin, self-role change, duplicate membership, concurrent update and audit-write rollback.
- Document-manager positive document cases and negative project/scenario/release/consumer cases.
- PostgreSQL non-owner/RLS suite; SQLite compatibility; CSRF/method/accessibility/browser regression.
- Ruff format/lint, mypy, Django checks and migration drift.

## Rollout and rollback

Roll out after applying the additive role migration. Rollback restores the prior UI/context behavior
and ignores the new role value only after confirming no membership still uses it; otherwise keep the
additive choice while reverting behavior. No user or organization is deleted during rollback.

## Risks

- Session scope mistaken for authorization; context alignment before object authorization; orphaning
  an organization admin; document-manager capability accidentally leaking into scenario authoring;
  directory user enumeration; concurrent membership changes.

## Open questions

None. Single-role membership and deterministic first-organization selection are owner-approved.

## Status

**Verified 2026-07-22.** Mandatory workspace selection, atomic organization creation,
membership lifecycle, `document_manager`, contextual creation and authorized deep-link alignment
are implemented. SQLite, PostgreSQL/RLS, static and authenticated browser evidence is recorded in
`verification.md`.

## Completion criteria

All acceptance criteria are implemented; migration and PostgreSQL RLS evidence pass; audit and
cross-tenant tests pass; current behavior docs are updated; final staff/AppSec/SRE reviews close; the
task reaches Verified before archival.
