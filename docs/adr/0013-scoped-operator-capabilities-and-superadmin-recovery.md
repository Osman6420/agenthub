# ADR 0013: Scoped operator capabilities and superadmin recovery

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The current console derives broad organization-wide authority from one membership role and treats
Django `is_superuser` as the normal platform administrator. Those shortcuts cannot express
project-, scenario- or document-set responsibility and allow administrative authority to become a
document-content disclosure path.

## Decision drivers

- Deny by default at every server-side object boundary.
- Keep active-organization selection as navigation state, never authority.
- Permit delegated responsibility without granting document content.
- Preserve an exceptional human recovery path without making it a daily role.
- Add the new model incrementally before removing legacy predicates.

## Considered options

1. Keep organization-wide roles and add view-specific exceptions.
2. Adopt a general policy language/ABAC engine.
3. Use a closed capability vocabulary backed by explicit scoped assignments.

## Decision

Use a central application authorization service with the closed capability vocabulary recorded in
the Part 2.1 plan. The service returns an allow/deny decision, stable content-free reason and exact
authority source.

There is exactly one daily `GlobalAdministrator` assignment. Its user must be active and must not
be a Django superuser. Global Administrator and Organization Administrator receive administrative,
release and applicable runtime capabilities, but neither implicitly receives document-content,
raw-retrieval-context or normal scenario-to-document-set grant authority.

Project Admin, Scenario Editor and Document Set Manager authority is represented by explicit
tenant-bound object assignment rows. Scenario retrieval uses a separate live scenario-to-document
set `retrieve` grant; a binding configures use but never creates authority.

Django `is_superuser` is the separate superadmin recovery identity. The central boundary recognizes
it as the explicit `superadmin_recovery` source. Sensitive superadmin actions require dedicated
high-severity audit and immediate security/operator alerting before endpoint migration is complete.
No temporary elevation, impersonation or application approval subsystem is introduced.

Existing broad predicates remain active only during the staged compatibility rollout. Each
endpoint, task and worker moves to the central service with denial tests before its legacy
predicate is removed.

## Security consequences

Administrative roles no longer imply protected document content. Object and organization lineage
must be taken from trusted persisted models. Superadmin remains deliberately powerful, so migrated
sensitive paths must fail closed when required audit persistence fails and must emit an immediate
alert.

## Operational consequences

Daily administration uses a non-superuser account. For the initial stage, recovery credential
custody, a unique strong password, rotation, alert routing and evidence review are operational
prerequisites before the superadmin path is accepted for use. By owner decision on 2026-07-24,
phishing-resistant MFA is deferred to Phase 3 security hardening; password compromise and phishing
therefore remain accepted residual risks for the initial stage.

## Data and privacy consequences

Assignment and grant rows store safe identifiers and role/grant provenance, not document content.
Authorization logs, audits and metrics use stable reason codes and safe target identifiers only.

## Positive consequences

- One reusable capability contract across console, APIs, tasks and workers.
- Explicit cross-organization and object-scope denial behavior.
- Clear separation between metadata, content and recovery authority.

## Negative consequences

- Staged rollout temporarily maintains both legacy predicates and the new decision service.
- More assignment rows and denial cases require broader migration and test coverage.
- Superadmin alerting and credential controls add operational work.

## Migration impact

Migrations are additive until every caller is switched and the disposable-demo inventory is
verified. Legacy roles are not backfilled into narrower grants. Their removal requires a separate
compatibility gate and proof that no live assignment remains.

## Rollback considerations

Stop using the new assignment UI/service while retaining its rows and audit evidence. Restore the
last verified predicate behind the versioned compatibility boundary; never roll back by granting
superuser, widening RLS or deleting denial tests.

## References

- [Phase 2.8 Part 2.1 plan](../planning/archive/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery-2026-07-24/plan.md)
- [Phase 2.8 Part 2.1 threat model](../planning/archive/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery-2026-07-24/threat-model.md)
- [ADR-0001](0001-custom-console-ldap-auth.md)
- [ADR-0004](0004-tenant-isolation-postgres-rls-connection-context.md)
