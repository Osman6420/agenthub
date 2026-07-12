# Threat Model: phase-2-p4-acl-rls

## Assets

- Tenant document corpora served to consumers via `/v1/query` retrieval.
- Tenant isolation of retrieved passages (the highest-value invariant of the document plane).
- The active-index pointer per document-set version (what content is live).

## Actors and entry points

- **Consumers** through the gateway `/v1/query` (already scenario-authorized at the gateway).
- **Operators** building/promoting staged indexes (management commands / services).
- **The retrieval path**, reaching per-`IndexVersion` pgvector stores under a tenant context.

## Trust boundaries and layered enforcement

Effective retrieval scope is resolved **entirely server-side** and enforced in depth:

1. **Deny-by-default binding.** The compiler pins only `document_set_versions` resolved from the
   scenario's `ScenarioDocumentSetBinding`s. No binding → no pin → nothing retrieved.
2. **App predicate.** `_retrieve_acl` filters active index versions by
   `organization_id = ctx.org` ∩ pinned `document_set_version_ids` ∩ `status=active` ∩
   `store_ready`, and excludes tombstoned documents. No filter comes from the client.
3. **RLS backstop (ADR-0004).** Every per-`IndexVersion` store has `FORCE ROW LEVEL SECURITY` with
   a `NULLIF(current_setting('app.tenant_id', true), '')::bigint` tenant policy; retrieval sets the
   transaction-local `app.tenant_id`. A missing/empty/wrong context returns **no rows even if the
   app predicate were omitted** — proven under a NOSUPERUSER role.

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Cross-tenant retrieval (missing/forgotten app predicate) | RLS `FORCE` + tenant policy is the fail-closed second layer; the index-version tenant filter is the first. Both tested (`test_cross_tenant_returns_nothing`, `test_rls_is_fail_closed_under_non_superuser`). |
| A scenario retrieving unbound content | Deny-by-default: only bound → published → **promoted** versions are served. `test_no_pinned_versions` / `test_deny_by_default_when_not_promoted`. |
| Cross-set leakage | Only the pinned document-set version's active store is queried. `test_cross_set_is_excluded`. |
| Client-supplied tenant/set filter | The retriever accepts none; all scope derives from the signed context + release manifest. |
| Serving soft-deleted content | `document.deleted_at IS NULL` predicate excludes tombstoned docs immediately. `test_tombstoned_document_excluded`. |
| Serving an unevaluated/half-built corpus | Only `status=active` stores are served; promotion is an explicit, audited pointer flip; a promotable staged index is never served. |
| Promotion race / split active pointer | `promote`/`rollback` run under `select_for_update` in one transaction, superseding the prior active index; single-active invariant tested. |
| SQL-identifier injection via store name | Store names are int-derived + regex-validated (ADR-0003); all values are bound parameters. |
| Tenant-context leak on a pooled connection | `set_config(..., is_local=true)` is transaction-scoped and reset at transaction end (ADR-0004). |

## Residual risks

- **RLS scope in this increment is the served per-`IndexVersion` stores** (the retrieval surface the
  serving guardrail protects). Enabling `FORCE` RLS on the Django-managed tenant tables
  (`documents_*`, `ingestion_chunk`) plus provisioning a dedicated **non-owner, non-superuser app
  role** (CI/local currently connect as the superuser owner, which bypasses RLS) is the remaining
  production hardening; the *mechanism* and fail-closed behavior are proven here under `SET ROLE`.
- The gateway consumer→scenario authorization is unchanged and remains the consumer-facing gate; the
  `DocumentSetGrant` `consumer` principal is available for finer per-consumer ACLs but WS1 authorizes
  via the scenario binding. `user`/`group` grants stay inert until WS4.
- No live embedding endpoint is exercised (deterministic embedder); real-provider retrieval quality
  is unverified until a separately-approved egress rollout.
