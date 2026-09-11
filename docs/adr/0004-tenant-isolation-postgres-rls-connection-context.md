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

### Phase 2 closure clarification (2026-07-14)

Operator sessions may be members of several organizations and existing console lists intentionally
span that authorized set. The transaction-local context is therefore represented as a bounded,
sorted `app.tenant_scope` of organization ids for operator requests and as a singleton scope for
gateway/worker operations. The scope is always derived server-side from authenticated membership,
authenticated consumer identity, or an identifier-only worker message whose first query also
matches the organization id. Client request bodies and artifact data never set it. Policies call a
platform-owned `app_tenant_scope_contains(organization_id)` helper; absent/empty scope returns false.

Identity bootstrap tables needed before the tenant is known (`tenancy_organizationmembership`,
`identity_consumer`, `identity_consumertoken`) are not protected by this tenant policy and instead
retain narrow application queries and table-specific grants. Nullable cross-plane audit/usage
tables also keep a separate append/admin design. These exceptions must remain explicit in readiness
and deployment documentation.

- **Enable + FORCE.** `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` on every tenant
  data-plane table. The application connects as a role that is **not the table owner**, is **not a
  superuser**, and lacks **`BYPASSRLS`**, so policies apply to it (owners/superusers/`BYPASSRLS`
  would otherwise bypass RLS).
- **Policies.** Read/visibility and write checks call the platform-owned
  `agenthub_tenant_scope_contains(organization_id)` helper. It parses only the bounded server-set
  transaction-local scope; absent/empty scope yields **no rows** and rejects writes, while malformed
  scope errors rather than widening access — **missing or invalid context fails closed**.
- **Transaction-local context.** Each unit of work sets the context **after** opening its
  transaction: `SELECT set_config('app.tenant_scope', <scope>, true)` (the `true`/`is_local` flag
  scopes it to the transaction). It is **never** set at session scope, so a pooled connection never
  carries a tenant between operations.
  - **Web:** middleware wraps the request in an atomic block and sets console scope from authenticated
    memberships; gateway bearer authentication replaces the initially empty scope with the
    authenticated consumer's singleton organization.
  - **Workers:** task messages carry object id plus organization id; each database phase opens an
    atomic block, sets singleton scope, and matches both identifiers on its first query.
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

- Missing context → 0 rows; wrong-tenant context → 0 rows; multi-membership scope reveals only that
  exact set; write with mismatched tenant → rejected by `WITH CHECK`; a pooled connection reused
  across tenants does not leak; the app role cannot
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
