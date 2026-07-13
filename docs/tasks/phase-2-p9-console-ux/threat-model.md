# Threat Model: phase-2-p9-console-ux

## Assets

Tenant hierarchy, scenario metadata, document-set membership/readiness, consumer identities,
retrieval grants, release state and authorization topology.

## Actors

Platform administrators, organization administrators, project owners, scenario editors, auditors,
authenticated but unrelated operators, and attackers with a stolen/low-privilege console session.

## Entry points

Authenticated scenario/detail GET routes and CSRF-protected binding/grant POST routes.

## Trust boundaries

Browser → Django session/CSRF boundary; URL/form IDs → tenant-scoped querysets; console view →
audited document domain services; configured relationship → release-pinned runtime state.

## Data classifications

Scenario/consumer names are internal metadata. Relationship topology is authorization-sensitive.
Document content, filenames beyond the scoped operator response, credentials, tokens and connector
secrets must not enter logs. Bulk uploads cross the browser/object-store boundary; staged builds
cross the worker/profile-governed embedding and optional OCR egress boundaries.

## Authentication

Existing Django session authentication (LDAP in production, local backend in development). This
task does not change identity providers or authenticate end users to the gateway.

## Authorization

All reads derive from scoped organization querysets. All writes require current server-side author
permission and same-tenant targets. Existing services enforce model invariants and emit audit.

## Tenant isolation

Cross-tenant scenario, set, consumer, binding and grant IDs return 404 or a generic rejected action
without exposing foreign metadata. Platform-admin cross-tenant visibility remains intentional.

## External systems

P9.1 has none. P9.2 may invoke only platform-managed embedding/OCR profiles already granted to the
tenant. Browser-supplied hosts, URLs, credentials and profile configuration are never accepted.

## Abuse cases

- IDOR by changing scenario/set/consumer/binding/grant IDs.
- Low-role operator submitting hidden POST forms directly.
- CSRF relationship mutation.
- Stored XSS through scenario, set or consumer names.
- Confusing configured bindings with active release/index scope.
- Batch memory/size exhaustion, duplicate generated IDs, misleading partial success, MIME spoofing
  and unsafe filenames.
- Cross-tenant profile/build/index IDs, author-triggered promotion, forged worker tenant IDs and
  replayed build requests.

## Failure cases

Duplicate bindings/grants, deleted/disabled targets, stale pages, audit persistence failure, a
relationship changed after the page was loaded, broker unavailability, failed parser/embedding/OCR
calls and a staged build that is never promoted.

## Logging and audit risks

Do not add identifiers with uncontrolled cardinality to metrics. Reuse safe actor/action/target/
outcome audit events. State mutations remain fail-closed with domain-service audit persistence.

## Mitigations

Scoped querysets, POST-only mutations, CSRF, permission rechecks, same-tenant filters, Django
auto-escaping, stable generic errors, domain services, and explicit configured-vs-effective labels.
P9.2 additionally applies file-count/per-file/aggregate byte limits, server-generated slug IDs,
the existing MIME allowlist, tenant-granted immutable profile selection, identifier-only task
payloads, tenant context in the worker, and release-manager-only promotion.
P9.3 keeps connector destinations, authentication, secret references and source-input values out
of the tenant read model; exact set grants and same-tenant contracts are revalidated by domain
services. Synthetic REST preview is size/item bounded, performs no egress and returns metadata only.
Schedule targets are restricted to scenarios already bound to the source set, with release-manager
authorization for automatic promotion; queued sync tasks carry run and organization IDs only.

## Residual risks

Organization membership currently grants organization-wide read visibility; scenario-level LDAP
operator read ACL is not part of the current model. Personal user/group runtime ACL is deferred to
WS4 and must not be implied by this screen.

## Required security tests

Authentication redirect, membership-less/cross-tenant 404, cross-tenant mutation denial,
non-author 403, CSRF behavior, audit creation/removal evidence, and escaped stored labels.
P9.2 also requires bulk boundary/duplicate/MIME tests, draft replacement/baseline tests, profile
grant and cross-tenant denial, author-vs-release-manager checks, queue dispatch and promotion audit.
P9.3 requires profile/secret redaction, invalid/cross-tenant source IDs, exact-grant denial, malicious
contract/preview payloads, schedule interval/mode/target checks, queue failure and ID-only payloads.
