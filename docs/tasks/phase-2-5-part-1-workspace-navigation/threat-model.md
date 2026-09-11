# Threat Model: phase-2-5-part-1-workspace-navigation

## Assets

- Organization-scoped domain metadata, relationships and operational status.
- Membership/role assignments and the existence of organizations and objects.
- Document, artifact, release and run metadata.
- PostgreSQL tenant-scope integrity and existing audit evidence.

## Actors

- Anonymous visitor.
- Authenticated organization member with auditor, editor, owner, release-manager or admin role.
- User who belongs to multiple organizations.
- Platform administrator.
- Malicious or compromised authenticated account.

## Entry points

- `/console/` dashboard organization section.
- `/console/o/<organization-slug>/` organization overview.
- Existing canonical list, detail and action URLs.
- Path parameters, query strings, forms and template-generated links.

## Trust boundaries

- Browser input to Django routing and forms.
- Django session identity to membership/action authorization.
- Resolved workspace context to ORM query scoping.
- Web transaction to PostgreSQL transaction-local `app.tenant_scope` and FORCE RLS.
- Release manifest JSON to relationship rendering.

## Data classifications

- Organization/object names and relationships: internal tenant metadata.
- Subjects, token prefixes and actor identifiers: sensitive metadata; render only when required and
  never place in logs casually.
- Document/prompt bodies and token plaintext: restricted; Part 1 must not fetch or expose them for
  navigation.

## Authentication

Django session authentication remains unchanged. Workspace selection is not authentication.

## Authorization

Membership/platform-admin checks authorize workspace read access. Existing server-side action
predicates independently authorize mutations. URL slug, selected option, hidden field and previous
page are never authority.

## Tenant isolation

The resolver finds an organization only inside the user's allowed set, workspace querysets require
that exact organization and PostgreSQL scope is narrowed to its ID. Foreign/missing objects return
indistinguishable not-found behavior. Dashboard/platform-level pages do not become tenant mutation
surfaces. An authorized disabled organization remains readable for inventory/history but all
operational mutations fail server-side, including direct requests that bypass hidden controls.

## External systems

None. Part 1 opens no live egress and adds no dependency.

## Abuse cases

- Enumerate organization slugs through status, timing or error text.
- Request a foreign object primary key through an existing canonical detail/action URL.
- Inject another organization through query string/form input.
- Follow a relationship count/link that was not tenant-filtered.
- Abuse platform-admin fallback to render cross-tenant data without visible privileged context.
- Use untrusted query/form organization input to conflict with the server-derived target organization.

## Failure cases

- Workspace resolution happens after a tenant-owned query.
- Transaction-local scope is not reset between pooled requests.
- Missing active organization silently falls back to all memberships.
- Stale relationship/manifest data raises 500 or leaks foreign identifiers.
- Large relationship pages cause query amplification or operational timeout.

## Logging and audit risks

- Logging raw paths/query strings may capture organization or object identifiers.
- High-cardinality object/slug labels can degrade metrics.
- Navigation-only views could create noisy business audit records.
- Refactoring action URLs could drop existing security/business audit events.

## Mitigations

- Central typed workspace resolver with deny-by-default failure and constant response shape.
- Explicit organization parameter in overview/relationship scoping helpers and server-derived target
  organization on existing object routes.
- Singleton transaction-local PostgreSQL scope before tenant-domain queries and non-owner-role tests.
- Same-organization predicates on every direct and indirect relationship lookup.
- Preserve existing canonical unsafe-method routes and their method/CSRF semantics; add no redirect
  migration.
- Content-free stable reason codes and low-cardinality route telemetry.
- Preserve current mutation authorization and audit services; navigation creates no business audit.
- Query-count fixtures and `select_related`/`prefetch_related` review for relationship pages.

## Residual risks

- Organization slugs remain visible to authorized members and in browser history by design.
- Application superusers can cross organizations by design; visibility and operational governance
  remain required.
- Existing integer object IDs remain locators until Part 2, though they grant no authority.
- Offline tests verify singleton tenant-context call placement but cannot prove PostgreSQL FORCE RLS
  enforcement; dedicated non-owner execution remains a closure blocker.
- Organization inventories are bounded, but representative query-count budgets and live route/error
  behavior remain unmeasured.
- Responsive and assistive-technology manual acceptance remains waived by owner decision.

## Required security tests

- Anonymous, membership-less, wrong-tenant and malformed-slug denial; authorized disabled-tenant
  read-only access plus direct mutation denial.
- Enumeration-safe response body/status comparison.
- Foreign primary key on existing canonical detail/action routes.
- Forged path/query/form organization input.
- Cross-tenant relationship label/count/link absence.
- Role denial for every existing mutation family touched by navigation/scoping changes.
- CSRF and unsafe-method no-redirect regression behavior.
- PostgreSQL non-owner singleton/empty/wrong scope and transaction reset.
- Log/audit redaction and preservation of existing successful/denied mutation audit semantics.
