# Task Plan: phase-2-p4-acl-rls

## Task summary

Phase 2 P4 (Workstream 1 · M2) — the **security core** that unlocks serving real tenant corpora:
mandatory scenario↔document-set binding, deny-by-default document-ACL retrieval, PostgreSQL
`FORCE ROW LEVEL SECURITY` as a fail-closed second layer (ADR-0004), and pointer-flip promotion of
the P3-staged index. Delivered in reviewable increments because it is the highest-risk milestone:

- **P4.1 — binding + ACL grant foundation (this increment, done):** `ScenarioDocumentSetBinding`
  (mandatory, same-tenant) and forward-ready `DocumentSetGrant` (only `consumer` enforced in WS1),
  plus audited services. Additive; no enforcement wired yet.
- **P4.2 — release-compile pinning + resolver expansion + ACL retrieval predicate:** compile the
  bindings to pinned `document_set_version_ids`, expand them in the resolver to active
  `index_version_ids`, and constrain the retriever to `(org ∩ pinned index versions ∩ pinned
  doc-set versions ∩ consumer-authorized ∩ not-tombstoned)`. Deny-by-default: a scenario with no
  binding retrieves nothing. Client-supplied filters ignored.
- **P4.3 — PostgreSQL RLS (ADR-0004):** non-owner app role without `BYPASSRLS`, `FORCE ROW LEVEL
  SECURITY` on tenant data-plane tables, transaction-local `set_config('app.tenant_id', …, true)`
  for web + Celery, fail-closed on missing/invalid context, control-plane/data-plane separation.
- **P4.4 — pointer-flip promotion:** promote an eval'd P3 staged index to `active` and flip the
  binding/release pointer in one transaction (no rename/copy/rebuild); rollback flips back. Full
  negative-test matrix (cross-tenant at app **and** RLS layers, cross-set, deny-by-default,
  client-filter-ignored, RLS-fail-closed).

## Background

Phase 2 P1/P2/P3 are verified. P3 builds **staged** per-`IndexVersion` blue/green stores but the
serving guardrail holds real corpora back until P4's deny-by-default binding + RLS are in place.
Authorities: [`document-plane-plan.md`](../../planning/components/document-plane-plan.md) (retrieval
+ RLS sections), [ADR-0004](../../adr/0004-tenant-isolation-postgres-rls-connection-context.md),
[ADR-0003](../../adr/0003-vector-storage-blue-green-per-index-version.md) (pointer-flip promotion).

## Scope (P4.1 — this increment)

- `ScenarioDocumentSetBinding` (org-denormalized; unique `(scenario, document_set)`; `clean()`
  forbids a cross-tenant scenario↔set link) and `DocumentSetGrant` (`principal_type ∈ {consumer,
  service, user, group}`, opaque `principal_ref`, `permission`; unique per
  `(set, type, ref, permission)`). Additive migration `documents.0002`.
- Audited services: `bind_scenario_document_set`, `unbind_scenario_document_set`,
  `grant_document_set` (only `consumer`/`service`/`user`/`group` validated; enforcement of
  non-consumer principals is WS4).

## Non-goals (P4.1)

No resolver/retrieval enforcement, no RLS, no pointer-flip promotion, no operator API/console
surface yet (those are P4.2–P4.4 / P8). `user`/`group` grants are inert until WS4. No served
retrieval path changes.

## Acceptance criteria (P4.1)

- A scenario can be bound to a same-tenant document set; a cross-tenant scenario↔set bind is
  rejected; a duplicate bind fails closed with a stable code; unbind is audited.
- A `consumer` grant is created and audited; an unknown principal type/permission is rejected; a
  duplicate grant fails closed.
- Every binding/grant carries a mandatory, same-tenant `organization`; additive migration, no drift.

## Status

**P4 Implemented and Verified (2026-07-13) — the serving guardrail is now satisfiable.**

- **P4.1** — binding + ACL grant foundation (commit `80d140f`).
- **P4.2** — the release compiler pins `document_set_versions` (deny-by-default from bindings), the
  resolver carries them, the runtime passes them, and `PgvectorRetrievalProvider._retrieve_acl`
  serves only from the pinned versions' **active** per-`IndexVersion` stores, tenant- and
  not-tombstoned-scoped; no client filter is honored. Legacy source-scoped retrieval is unchanged.
- **P4.3** — each per-`IndexVersion` store is provisioned with `ENABLE`/`FORCE ROW LEVEL SECURITY`
  and a `NULLIF(current_setting('app.tenant_id', true), '')::bigint` tenant policy; `set_tenant_context`
  sets it transaction-locally, and `write_chunks`/`search`/`_retrieve_acl` run inside a transaction
  that sets it. Proven fail-closed under a NOSUPERUSER role via `SET ROLE` (superusers bypass RLS).
- **P4.4** — `promote_staged_index` pointer-flips a promotable index to `active` and supersedes the
  prior active one for the same document-set version in one metadata-only transaction;
  `rollback_staged_index` restores; the `promote_staged_index [--rollback]` command exposes it.

Evidence: ruff/mypy/check/no-drift clean; SQLite 454 passed / 18 skipped (pgvector);
PostgreSQL `--create-db` 470 passed / 2 skipped (off-PG guards). Additive migrations `documents.0002`
(P4.1) and `ingestion.0005` (add `IndexStatus.superseded`). No new dependency; no live egress; the
deterministic embedder + hermetic object store keep CI hermetic.

## Negative-test matrix (verified on PostgreSQL)

deny-by-default (no binding → no pin → nothing; a staged-but-not-promoted index is never served);
cross-tenant (org B pinning org A's version yields no active index; **RLS blocks a wrong/missing
`app.tenant_id` even with the app predicate omitted**); cross-set (only the pinned version's docs);
tombstoned document excluded; RLS fail-closed under a non-superuser role; pointer-flip single-active
invariant + rollback.

## Test plan (P4.1)

Bind same-tenant + audit; cross-tenant bind rejected; duplicate bind rejected; unbind + audit;
consumer grant + audit; unknown principal type rejected; duplicate grant rejected.

## Rollback

Additive migration `documents.0002` is reversible; the models are inert until P4.2 wires
enforcement, so reversing has no retrieval impact.
