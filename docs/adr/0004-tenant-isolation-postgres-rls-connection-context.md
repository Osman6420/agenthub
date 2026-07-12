# ADR 0004: Tenant isolation via PostgreSQL Row-Level Security with a transaction-local connection context

- **Status:** Accepted
- **Date:** 2026-07-12

Records the output of **Phase 2 · WS1 M0 Spike 2** (RLS connection-context design). The decision is
accepted; *implementation timing* is gated by Phase 2 approval. RLS is a **defense-in-depth second
layer**, never a replacement for the application authorization already required by
[`security-rules.md`](../ai/security-rules.md).

## Context

WS1 introduces tenant document data-plane tables (documents, versions, sets, memberships, index
versions, and the per-`IndexVersion` vector stores of [ADR-0003](0003-vector-storage-blue-green-per-index-version.md)).
Application-level tenant predicates are primary, but a single missing `WHERE tenant_id = …` is a
cross-tenant leak. The owner directed that RLS enforce a fail-closed backstop, with the tenant
context carried **transaction-locally** so nothing leaks across a pooled connection.

## Considered options

1. **Application predicate only.** Simplest; one missing predicate leaks across tenants.
2. **RLS with a session-level GUC** (`SET app.tenant_id`). Enforced in the database, but a
   connection returned to the pool retains the GUC and the next checkout can read another tenant's
   rows.
3. **RLS with `FORCE ROW LEVEL SECURITY`, a non-owner app role without `BYPASSRLS`, and a
   transaction-local GUC** (`set_config('app.tenant_id', …, true)`). Fail-closed, pool-safe.

**Chosen: Option 3** (in addition to — not instead of — the application predicate).

## Decision

- **Enable + FORCE.** `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` on every tenant
  data-plane table. The application connects as a role that is **not the table owner**, is **not a
  superuser**, and lacks **`BYPASSRLS`**, so policies apply to it (owners/superusers/`BYPASSRLS`
  would otherwise bypass RLS).
- **Policies.** Read/visibility `USING (tenant_id = current_setting('app.tenant_id', true)::bigint)`
  and, for writes, a matching `WITH CHECK`. `current_setting(…, true)` returns `NULL` when the
  setting is absent, so `tenant_id = NULL` yields **no rows** and inserts are rejected — **missing or
  invalid context fails closed**.
- **Transaction-local context.** Each unit of work sets the context **after** opening its
  transaction: `SELECT set_config('app.tenant_id', <tenant_id>, true)` (the `true`/`is_local` flag
  scopes it to the transaction). It is **never** set at session scope, so a pooled connection never
  carries a tenant between operations.
  - **Web:** a middleware wraps the request in an atomic block (or `ATOMIC_REQUESTS`) and sets the
    context from the gateway-signed `ExecutionContext` (runtime) or the operator session's tenant
    scope (console).
  - **Workers:** a Celery task base/wrapper opens an atomic block and sets the context from the
    run's tenant before touching tenant tables.
- **Trusted source only.** `tenant_id` comes from the signed context or the authenticated operator
  session — **never** from client input.
- **Plane separation.** Global control-plane / worker-claim / catalog tables (e.g. release pointers,
  the `ModelProfile`/`EmbeddingProfile` catalog, ingestion claim rows) are **not** under tenant RLS
  and are **not** reachable via a broad tenant-bypass role. Cross-tenant administration uses a
  **separate, audited admin role/function**, not the request/worker role.
- **Pooling.** `SET LOCAL`/transaction-local `set_config` is compatible with pgbouncer **session or
  transaction** pooling; **statement** pooling is unsupported (it breaks multi-statement
  transactions) and is documented as prohibited for the app role.

## Security consequences

- A missing application predicate can no longer leak across tenants: the database returns no rows.
- No `BYPASSRLS`/owner privileges on the request/worker path; migrations and admin run under a
  distinct, audited role. Context is transaction-scoped, closing the pooled-connection leak.

## Operational consequences

- The app DB role, table ownership, and pooling mode become deployment invariants (documented and
  change-controlled). Readiness/CI must assert RLS is enabled + forced on the tenant tables and that
  the app role lacks `BYPASSRLS`. RLS is a **PostgreSQL-only** guarantee; SQLite test runs skip it,
  so the negative-tests below run on PostgreSQL.

## Negative-test matrix (required before the ACL milestone promotes)

- Missing context → 0 rows; wrong-tenant context → 0 rows; write with mismatched tenant → rejected
  by `WITH CHECK`; a pooled connection reused across tenants does not leak; the app role cannot
  `ALTER TABLE … DISABLE ROW LEVEL SECURITY` or otherwise bypass; cross-tenant admin only via the
  separate role.

## Data and privacy consequences

- Enforces tenant data minimization at the storage boundary. No tenant identifiers beyond safe ids
  appear in logs/metrics labels.

## Migration impact

- Additive DDL to enable + force RLS and create policies; an **operational** step to provision the
  non-owner app role and set table ownership/pooling. Introduced with the WS1 M2 (ACL) milestone.

## Rollback considerations

- A specific table's RLS can be disabled by migration as a **temporary, audited exception**, falling
  back to the application predicate — a time-boxed emergency measure, not a steady state.

## References

- [Document plane plan](../planning/components/document-plane-plan.md) — Spike 2, retrieval ACL.
- [Document plane threat model](../planning/components/document-plane-threat-model.md) — tenant isolation.
- [ADR-0003](0003-vector-storage-blue-green-per-index-version.md) — the vector stores RLS covers.
- [ADR-0001](0001-custom-console-ldap-auth.md) — operator identity/authorization this composes with.
