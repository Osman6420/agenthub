# Threat Model: Phase 2.8 Part 2 — Organization and access management

## Assets and data classification

Tenant boundaries, memberships, role assignments, organization lifecycle, session workspace state
and tenant-owned objects. User identifiers and membership relationships are internal/confidential;
secrets and credentials are not part of this UI.

## Actors and entry points

Platform admins, organization admins, document managers, other members, revoked/membership-less
users and malicious authenticated users. Entry points are the organization selector, organization
creation, membership list/mutations, contextual create routes and authorized deep links.

## Trust boundaries

Browser/session/form values are untrusted. Django authentication establishes identity; tenancy
services and target-object lineage establish authorization. LDAP/Django user records are selectable
identities, not proof of tenant membership. PostgreSQL RLS backs direct tenant tables.

## Principal abuse and failure cases

| Threat | Required mitigation |
| --- | --- |
| Forged active organization widens scope | Revalidate membership every request; active scope only narrows authorized querysets |
| IDOR while aligning a deep link | Authorize exact target before metadata render or session alignment |
| Submitted organization/project overrides context | Remove fields; derive and reauthorize trusted parent server-side |
| Organization admin grants platform authority | Platform admin is never a membership role assignable by this UI |
| Cross-tenant user enumeration/assignment | Bound user results and membership writes to authorized management flow; generic foreign denial |
| Last admin removed or concurrent updates race | Transaction/row locks and last-admin invariant at write time |
| `document_manager` gains unrelated authority | Dedicated least-privilege predicate plus negative tests for every other action family |
| Audit outage leaves unaudited role change | Required audit in the same transaction; rollback on failure |
| Disabled organization mutated | Existing disabled-tenant server predicate remains authoritative |
| GET/CSRF misuse performs business mutation | POST-only, CSRF-protected mutations; safe context alignment carries no business authority |

## Logging and audit risks

Do not log session IDs, raw form bodies, LDAP attributes or foreign target values. Audit successful
and denied membership/organization mutations with safe IDs, action, outcome, reason and request/trace
correlation. Workspace selection itself is not a business audit event.

## Residual risks

Single-role membership may require role changes rather than additive responsibility. A capped user
selector can limit discoverability but must not weaken server authorization. These are accepted UX
constraints, not security exceptions.

## Required security tests

Anonymous/membership-less denial; forged/stale/revoked session; cross-tenant target and user IDs;
role escalation; last-admin concurrency; document-manager least privilege; disabled organization;
CSRF/method denial; audit failure rollback; PostgreSQL non-owner RLS isolation; content-free logs and
errors.
