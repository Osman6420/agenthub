# Task Plan: sprint-1-tenant-identity-catalog

## Task summary

Implement the control-plane foundation from Sprint 1 of the
[v3 target plan](../../../agenthub-v3-django-plan.md#25-uygulama-asamalari): tenant
boundary, human/machine identity, the AI project/scenario catalog, an append-only
audit trail, and a **custom operator console authenticated via LDAP** (per
[ADR-0001](../../adr/0001-custom-console-ldap-auth.md)) — replacing Django Admin
as the management surface.

## Background

Sprint 0 delivered a bootable skeleton with no domain models. Every later sprint
(gateway, RAG, ingestion, tools, agents) depends on tenant isolation and identity
being correct and enforced server-side, so they are built first.

## Scope

- `tenancy`: `Organization`, `OrganizationMembership`, tenant-scoped querysets and
  an `allowed_organization_ids(user)` authorization helper.
- `identity`: role and capability constants, `Consumer`, `ConsumerBinding`, and an
  LDAP-configurable authentication backend (disabled in dev/CI, falls back to the
  Django model backend).
- `catalog`: `AIProject`, `Scenario`, `ScenarioAlias` with organization-unique
  alias enforcement.
- `audit`: `AuditEvent` model and an append-only `record_event` service.
- `console`: server-rendered login/logout + organization-scoped dashboard and
  list screens; Django Admin removed from the routed surface (dev-only opt-in).

## Non-goals

- No gateway request path, `ExecutionContext`, RAG/runtime, ingestion, artifact
  versioning/release compiler, tools, or agents (later sprints).
- No full CRUD in the console yet — Sprint 1 provides authenticated, tenant-scoped
  **read** screens plus the model/authorization backbone. Editing flows arrive
  with the artifact/release sprints.
- LDAP is configured and wired but not installed/exercised locally (python-ldap
  builds in the Linux image); dev/CI verify the fallback path.

## Acceptance criteria

From the v3 plan (Sprint 1), all enforced server-side:

- One organization cannot read another's project or scenario records.
- A disabled consumer cannot be resolved for gateway calls (binding lookup denies).
- `ScenarioAlias.alias` is unique within an organization (DB constraint).
- The console is reachable only by an authenticated operator and shows only the
  organizations that operator is authorized for; the Django Admin route is off in
  production.

## Affected components

New apps: `tenancy`, `identity`, `catalog`, `audit`, `console`. Settings gain
authentication backends, login URLs, and guarded LDAP configuration. `config/urls`
routes the console and (dev-only) admin.

## Interfaces affected

New internal HTML surface under `/console/` (login required). No public product API
(that is the gateway, Sprint 3). `/` redirects to `/console/`.

## Data impact

New tables for organizations, memberships, consumers, bindings, projects,
scenarios, aliases, and audit events. First real domain migrations. Operator
profile fields (username, email, name, roles) are synced from LDAP in production;
no directory passwords are stored.

## Security impact

- Tenant isolation is enforced in querysets/services, not just the UI. Cross-tenant
  access is covered by negative tests.
- Authorization derives from `is_superuser` (platform admin), organization
  membership, and role — never from client-supplied values.
- LDAP bind uses a service-account secret from the environment/secret manager over
  LDAPS; failed binds fail closed. Django Admin's broad surface is removed.
- `ConsumerBinding` capabilities are validated against a known allowlist.
- Audit is append-only; the service rejects updates/deletes.

## Authorization impact

Introduces the role set (`platform_admin`…`auditor`) and the capability vocabulary
(`query`…`release_promote`). Sprint 1 enforces organization-scope reads and
consumer-status checks; capability enforcement on the request path lands with the
gateway (Sprint 3).

## Observability impact

State-changing operator/console actions and consumer-binding resolution emit audit
events (actor, action, resource, outcome, reason, request/trace ids where present).

## Migration impact

Additive, backward-compatible initial migrations for the five apps. No destructive
operations. Verified with `makemigrations --check` and applied against real
PostgreSQL.

## Dependencies

New production dependency (optional extra, ADR-approved): `django-auth-ldap`
(+`python-ldap`). Installed in the Linux image; not required when LDAP is disabled.

## Implementation steps

1. `tenancy` models + scoped manager + authorization helper.
2. `identity` roles/capabilities, `Consumer`, `ConsumerBinding`, LDAP settings.
3. `catalog` models + organization-unique alias constraint.
4. `audit` model + append-only service.
5. `console` app: LDAP-configurable auth, login/logout, scoped dashboard/lists;
   remove Django Admin from routed surface (dev-only opt-in).
6. Migrations; unit + integration tests (tenant isolation, constraints, auth).
7. Run all gates against real PostgreSQL; record evidence; update current docs.

## Test plan

- Cross-tenant denial: user in org A cannot see org B projects/scenarios.
- Alias uniqueness within org (constraint violation raises).
- Disabled consumer/binding is not resolvable.
- Capability allowlist validation rejects unknown capabilities.
- Console: anonymous → redirected to login; authenticated non-member sees empty
  scope; superuser sees all; Django Admin route absent when disabled.
- Audit service appends and refuses mutation.

## Rollout plan

Additive migrations; deploy behind CI gates. LDAP enabled per environment via
configuration once directory coordinates and group→role mapping are provided.

## Rollback plan

Revert the commit; drop the new tables (greenfield, no production data). LDAP can
be disabled by configuration without code change.

## Risks

- LDAP/`python-ldap` build/runtime complexity on the image; mitigated by the
  optional extra and the disabled-by-default fallback.
- Tenant-isolation gaps are high impact; mitigated by negative tests at the
  queryset/service layer.

## Open questions

- Directory coordinates, bind service account, and group→role mapping values
  (operational, provided before enabling LDAP in an environment).
- Whether `platform_admin` should be a directory group vs. Django `is_superuser`
  long-term (Sprint 1 uses `is_superuser`).

## Status

Verified — all gates (ruff format/lint, mypy, migration drift, system check) and
23 tests passed on both SQLite and real PostgreSQL on 2026-07-10; end-to-end console
login/scoping confirmed against seeded dev data. Evidence in
[`verification.md`](verification.md). Not yet `Completed`: LDAP live-bind validation
(Linux) and human review remain.

## Completion criteria

Map to the [Definition of Done](../../ai/definition-of-done.md): acceptance criteria
met with recorded evidence; authorization negative/cross-tenant tests pass; audit
verified; formatter/linter/type-check/migration/test gates pass; current-state docs
and master plan updated.
