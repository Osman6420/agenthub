# Threat Model: phase-2-9-part-2-callable-scenario-atomic-served-index

## Assets

Scenario callability, active release/alias lineage, served document/index pointers, immutable stores,
consumer/retrieval authorization, and audit evidence.

## Actors

Exact scenario release managers, exact document operations managers, neighboring roles, unassigned
or inactive users, consumers, workers, organization/global administrators, and recovery superadmin.

## Entry points

Scenario lifecycle POSTs, index promotion POST, lifecycle service calls, gateway/retrieval resolution,
migrations, and uncertain-result retries.

## Trust boundaries

Browser identifiers are untrusted. Session/CSRF authenticates but does not authorize. Tenant context,
exact responsibility, and object lineage are resolved server-side. Vector stores remain immutable.

## Data classifications

Lifecycle metadata/opaque IDs are internal. Tokens, prompts, output, document content, vectors,
endpoints, and secrets are restricted and excluded from audit/messages.

## Authentication

Console mutations require an active authenticated Django user, POST, and CSRF. Consumer calls retain
active bearer credential and protocol checks.

## Authorization

Scenario transitions require exact `scenario.release`; index transitions require exact
`document_set.operations.manage`. Membership alone is insufficient. Foreign and same-tenant
cross-scope identifiers must neither authorize nor disclose.

## Tenant isolation

Scenario/release/alias/set/version/index rows must share trusted organization lineage. Tenant context
is installed before tenant-table access; PostgreSQL non-owner FORCE RLS verification is mandatory.

## External systems

PostgreSQL and immutable per-index-version stores. No new network destination, provider, connector,
secret source, dependency, or production access.

## Abuse cases

- Forge another scenario/index ID or use a neighboring role.
- Promote a foreign/cross-set index or race two promotions into split state.
- Replay a timed-out request to disturb the new served pair.
- Leak content/secrets through audit or couple release promotion to implicit activation.

## Failure cases

Audit failure, constraint violation, stale instance, concurrent transition, legacy split state,
missing release/alias/store readiness, and process interruption mid-transition.

## Logging and audit risks

Events can leak existence/content or state can commit without audit. Use stable codes and opaque
IDs/counts only; successful transition audit shares the metadata transaction.

## Mitigations

Exact scoped selection, central authorization, deterministic locks, lineage/readiness checks,
conditional uniqueness, idempotent replay, transactional audit, non-disclosing handling, POST/CSRF,
separate lifecycle commands, immutable stores, and denial/concurrency/failure tests.

## Residual risks

Metadata cannot prove physical store content; existing build/eval evidence and `store_ready` remain
trust inputs. Human clarity/click cost still needs mandatory browser review.

## Required security tests

Exact allow plus neighboring/inactive/unassigned/foreign denials; cross-lineage rejection;
concurrent/duplicate constraints; idempotent replay; audit-failure rollback; inactive/active/disabled
gateway behavior; exact retrieval pointer; redaction; PostgreSQL non-owner FORCE RLS.
