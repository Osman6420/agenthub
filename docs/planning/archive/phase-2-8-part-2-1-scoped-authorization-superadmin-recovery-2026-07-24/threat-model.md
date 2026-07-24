# Threat Model: Phase 2.8 Part 2.1 — Scoped authorization and superadmin recovery

> Archived with the completed task on 2026-07-24.

## Assets and actors

Organization membership, delegated project/scenario/document-set authority, releases, document
content, raw retrieval context, connector secrets, superadmin credentials,
runtime availability and immutable audit evidence. Actors include Global/Organization/Project
Admins, Scenario Editors, Document Set Managers, application workers, the separate superadmin
operator and hostile or compromised members.

## Trust boundaries

Browser/API inputs, active organization, object identifiers, assignment/grant forms, scenario
bindings, released definitions, job payloads, caches, worker transitions and superadmin sessions are
untrusted until server-side authorization and tenant lineage checks complete.

## Principal threats and required controls

| Threat | Required control |
| --- | --- |
| Admin role implicitly reveals document content | Separate metadata/operations/content capabilities; deny content by default |
| Scenario used to exfiltrate a set | DS Manager-approved scenario grant; no raw context; live grant check on every retrieval |
| Binding mistaken for authorization | Require both active binding and current retrieve grant |
| Forged cross-tenant assignment/grant | Direct organization lineage constraints, service checks and forced RLS |
| Global Admin becomes unrestricted superuser | Non-superuser daily account and closed capability mapping |
| Superadmin becomes routine bypass | Separate account/surface, guarded unique strong password, rotation, alerting, runbook and audit; phishing-resistant MFA is deferred to Phase 3 |
| Application roles grow hidden temporary privilege | No elevation/approval/temporary-access subsystem |
| Stale object grant survives revocation | Per-operation check, bounded cache invalidation and queued/worker race tests |
| Project Admin publishes unreviewed release | Release service permits only Global/owning Organization Admin |
| Stop authority used to restore unsafe work | Broader stop than resume predicates; privileged resume provenance |
| Audit outage permits silent mutation | Transactional fail-closed audit for roles, grants and controls; superadmin audit outage alerts/fails according to recovery runbook |
| Hidden/disabled UI action treated as authorization | Every submit/API/task reauthorizes exact action and object |
| Access page leaks foreign identities or object names | Tenant/object-filter before search/count; safe labels and non-enumerating lookup |
| Forged assignment drawer posts broader scopes | Ignore display state; closed schemas and trusted lineage on every selected object |
| Concurrent grant revoke and scenario bind/retrieve | Locked/versioned mutation and live authorization at retrieval |

## Residual risk

A governed scenario may legitimately expose document-derived answers, and a Scenario Editor can
attempt prompt-based indirect disclosure even without direct document-page access. The confirmed
authoring/runtime retrieval and diagnostic-output separation must close this boundary. The
superadmin can bypass normal data separation by design. Guarded credentials, rotation, alerting and
immutable evidence reduce but cannot eliminate that recovery-account risk. Password compromise and
phishing remain explicitly accepted initial-stage residual risks until phishing-resistant MFA is
implemented in Phase 3.

Slice 4 separates scenario release authority from exact document-set operations and removes the
broad legacy runtime predicate. Legacy role values remain in schemas and disposable-demo seed data
until Slice 5 cleanup; reintroducing them into an authorization decision would restore overgranting
and must be rejected by compatibility tests and final code search.

## Required security evidence

Capability and object-list denial matrices; cross-tenant/RLS tests; indirect prompt/retrieval
disclosure tests; correct-document/correct-chunk evaluation with and without content authority;
grant revocation races; Project Admin release and operational-action denial; Scenario
Editor operational-action denial; audit rollback; superadmin alerts and restricted routes;
multiple-organization role composition; kill-switch stop/resume asymmetry;
assignment/request/approve/revoke browser journeys; forged forms, CSRF and accessibility states;
tests proving no elevation/temporary-access path exists; migration tests proving broad legacy roles do not silently become
content grants, or that verified demo-only assignments/users are reset without touching protected
data.
