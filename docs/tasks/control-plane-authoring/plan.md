# Task Plan: control-plane-authoring

## Task summary

Add first-class ways to create control-plane records — organizations, projects,
scenarios (+aliases), consumers, and consumer bindings — through two governed paths
(per [v3 plan §6.4](../../../agenthub-v3-django-plan.md#64-gitops-ve-django-admin-iliskisi)
and [ADR-0001](../../adr/0001-custom-console-ldap-auth.md)):

1. Role-gated create forms in the operator console (until now read-only).
2. GitOps import (`import_control_plane`) from reviewed YAML.

## Background

Sprints 1–4 can create artifacts/releases/tokens via CLI/GitOps, but organizations,
projects, scenarios, consumers, and bindings could only be added via `manage.py
shell`. The console listed them but offered no authoring. This task closes that gap.

## Scope

- `tenancy` role helpers: `can_admin_org`, `can_author_scenarios`, `user_roles_in_org`.
- Console create forms + views for Organization, Project, Scenario (+ optional
  alias), Consumer, and ConsumerBinding — tenant-scoped, role-gated, audited.
- GitOps `import_control_plane` command importing the same kinds from YAML.

## Non-goals

- No edit/delete flows yet (create only); no bulk edit. Status changes and edits are
  a follow-up. Release authoring stays with `compile_release` (artifacts via GitOps).
- No new authorization roles; reuse the Sprint 1 role set.

## Acceptance criteria

- A platform admin can create an organization from the console; a non-admin cannot.
- An organization admin can create projects/consumers/bindings only within an org
  they administer; cross-org creation is denied server-side.
- A project owner/scenario editor can create scenarios (+alias) within their org.
- Console create paths write an audit event and enforce the same tenant scope as
  reads (no widening).
- `import_control_plane` creates the same records from YAML idempotently and rejects
  cross-org bindings and unknown organizations.

## Affected components

`console` gains forms/views/templates. `tenancy` gains role helpers. `catalog` gains
a GitOps importer + command. No schema changes (models already exist).

## Interfaces affected

New authenticated console routes (`/console/<entity>/new`). New management command
`import_control_plane`. No public API change.

## Data impact

No new tables. New rows created through validated, audited paths. Binding capability
allowlist and cross-org invariants (already enforced in models) apply.

## Security impact

- Writes are role-gated server-side: organization creation is platform-admin only;
  org-scoped creation requires the right membership role in that org. Client-supplied
  org/role values are validated against the user's actual scope.
- Form querysets are limited to the user's scope so a user cannot attach a child to
  an organization/project they cannot administer.
- Every create emits an audit event (actor, action, resource, outcome).

## Authorization impact

Introduces write-authorization helpers layered on Sprint 1 roles. Read scope is
unchanged.

## Observability impact

Audit events for each authoring action; no new metrics.

## Migration impact

None.

## Dependencies

None new.

## Implementation steps

1. `tenancy` role helpers.
2. Console `forms.py` (scoped ModelForms) + create views + `form.html` + nav/new links.
3. `catalog` GitOps importer + `import_control_plane` command.
4. Tests (role/cross-tenant denial, happy path, gitops import).
5. Gates on SQLite + PostgreSQL; live authoring from console and GitOps; docs.

## Test plan

- Non-admin cannot open/submit the organization create form (403/redirect).
- Org admin of org A cannot create a project in org B (form rejects the choice).
- Scenario create writes scenario + alias; alias uniqueness enforced.
- Binding create rejects cross-org consumer/scenario.
- `import_control_plane` creates org→project→scenario→alias→consumer→binding.

## Rollout plan

Additive; behind CI gates. Console links appear for authenticated operators; actions
are gated by role.

## Rollback plan

Revert the commit; console returns to read-only. No schema changes.

## Risks

- Write authorization is security-critical; mitigated by server-side scope checks and
  negative tests. Form queryset scoping must match the read-scope helpers.

## Follow-up fixes

- OrganizationForm accepts the common authenticated-user constructor contract used by
  create views.
- Project owner is selected from organization memberships rather than free text. The
  submitted owner is revalidated against the selected organization server-side.

## Open questions

- Edit/disable flows and approval for high-risk changes (follow-up).

## Status

Verified on SQLite and PostgreSQL, including follow-up form fixes.

## Completion criteria

Map to the [Definition of Done](../../ai/definition-of-done.md): role/cross-tenant
negative tests pass; audit verified; gates green on SQLite and PostgreSQL; docs
updated.
