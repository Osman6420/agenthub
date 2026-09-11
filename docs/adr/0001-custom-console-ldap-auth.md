# ADR 0001: Custom operator console with LDAP authentication instead of Django Admin

- **Status:** Accepted
- **Date:** 2026-07-10

## Context

The v3 target plan originally proposed starting the internal control-plane UI on
Django Admin (decision §1.9, §23) and authenticating humans via OIDC/SSO (§10.1).
The product owner has decided that operators must manage the platform through a
**purpose-built console owned by the team**, not Django Admin, and must
authenticate against the corporate **LDAP / Active Directory** directory. This
ADR records that durable decision and its consequences.

## Decision drivers

- Operator UX and screens must fit AgentHub concepts (organizations, scenarios,
  releases, approvals, run trajectories) rather than raw model CRUD.
- Enterprise identity is centralized in LDAP/AD; operator accounts and group
  membership must come from the directory, not from a separate user store.
- Authorization must map directory groups to AgentHub roles (`platform_admin`,
  `organization_admin`, `project_owner`, ...) and enforce tenant scope server-side.
- Django Admin exposes broad, model-level power that is hard to constrain to the
  fine-grained, tenant-scoped, fail-closed model the plan requires.

## Considered options

1. **Django Admin + OIDC** (original plan). Fastest to stand up, but couples the
   management surface to Django's model admin and a different identity source than
   the corporate directory.
2. **Django Admin hardened + LDAP backend.** Keeps admin but bends it heavily;
   still leaks model-level semantics and is awkward to scope per tenant/role.
3. **Custom server-rendered console (Django views/templates) + LDAP auth.**
   Full control of screens, authorization, and audit; more work than admin but
   aligned with the target model. Can later evolve to an API + SPA (the Sprint 11
   builder) without changing the identity/authorization model.

Chosen: **Option 3.**

## Decision

- The primary internal management surface is a **custom console** (Django app
  `apps/console`, server-rendered), served under a dedicated path (`/console/`).
- Human operators authenticate via **LDAP/Active Directory** using
  `django-auth-ldap`. Directory groups map to AgentHub roles; a Django user is
  provisioned/synchronized from the directory on login. No operator passwords are
  stored by AgentHub.
- **Django Admin is not the management surface.** It is removed from the default
  and production URL configuration. It may remain enabled only in local
  development (behind an explicit setting) as a debugging convenience.
- LDAP is **configurable and environment-driven**. In environments without a
  directory (local dev, CI, tests) LDAP is disabled and Django's model backend
  authenticates local accounts, so the console remains testable without a server.
- Service/consumer authentication for the runtime gateway (OIDC client
  credentials / service-account JWT / mTLS) is unchanged by this ADR; it governs
  machine callers, while LDAP governs human operators.

## Security consequences

- Operator credentials never live in AgentHub; account lifecycle follows the
  directory. LDAP bind uses a service account whose secret is provided only via
  the secret manager, over LDAPS (TLS) with certificate validation.
- Authorization is enforced server-side from directory-group→role mapping plus
  organization membership and tenant scope; client-supplied roles are never
  trusted. The console must apply the same tenant-isolation rules as the gateway.
- Removing Django Admin reduces a broad, model-level attack/mis-authorization
  surface. The dev-only admin toggle must default off and never ship enabled to
  production.
- LDAP injection is prevented by using the library's parameterized filters and
  escaping; failed binds fail closed.

## Operational consequences

- New production dependency `django-auth-ldap` (and its `python-ldap` native
  dependency, requiring `libldap`/`libsasl` in the container image).
- New required configuration: LDAP server URI (LDAPS), bind DN + secret,
  user/group search bases, and group→role mapping. Readiness may include a
  directory reachability check (added with the console).
- Group-to-role mapping is operational policy and must be documented and change-
  controlled.

## Data and privacy consequences

- A minimal operator profile (username, email, display name, group-derived roles)
  is synchronized from the directory into the local user table to support audit
  attribution. No directory passwords are stored. Audit events reference the
  operator's stable subject.

## Positive consequences

- Management screens match domain concepts and enforce fine-grained, tenant-aware
  authorization and audit.
- Single corporate identity source for operators; centralized deprovisioning.
- Clean evolution path to the Sprint 11 API + SPA builder without an identity
  redesign.

## Negative consequences

- More implementation effort than Django Admin; console screens are now our code
  to build, test, and secure.
- LDAP/`python-ldap` adds build/runtime complexity and an external dependency in
  the login path.

## Migration impact

- Removes Django Admin from the routed surface (dev-only opt-in retained).
- Adds `apps/console`, `apps/identity` role/auth mapping, and LDAP settings.
- No production data migration (greenfield). The Sprint 0 local `admin` superuser
  remains valid for local, LDAP-disabled development only.

## Rollback considerations

- LDAP can be disabled per environment (falls back to local Django auth) without
  code changes. Re-enabling Django Admin in an emergency is a settings/URL change,
  but is discouraged and must be time-boxed and audited.

## References

- [v3 target plan](../../agenthub-v3-django-plan.md) §1.9, §10.1, §23.
- [master plan](../planning/master-plan.md) — open decision: identity/authorization.
- Supersedes the "start on Django Admin + OIDC" stance for the human operator
  surface; the machine/consumer identity model is unchanged.
