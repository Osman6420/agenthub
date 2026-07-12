# Verification: phase-2-p4-acl-rls

## Status

**P4 Verified 2026-07-13.** Automated evidence only; the vector-store/RLS paths run on the
Docker-Compose PostgreSQL/pgvector with the deterministic embedder + hermetic in-memory object
store (no MinIO, no live egress). This closes the serving guardrail: a bound scenario can now serve
real, ACL-scoped, tenant-isolated document RAG.

## Acceptance criteria mapping

- **Deny-by-default:** compiler pins `document_set_versions` only from bindings → published →
  promoted; no binding / not promoted → nothing served (`test_pinning`, `test_no_pinned_versions`,
  `test_deny_by_default_when_not_promoted`).
- **ACL retrieval:** `_retrieve_acl` serves only from pinned versions' active per-`IndexVersion`
  stores, tenant + not-tombstoned scoped, no client filter (`test_end_to_end_returns_bound_documents`,
  `test_cross_set_is_excluded`, `test_tombstoned_document_excluded`).
- **Cross-tenant blocked at both layers:** app predicate (`test_cross_tenant_returns_nothing`) and
  **RLS fail-closed under a NOSUPERUSER role with the app predicate omitted**
  (`test_rls_is_fail_closed_under_non_superuser`, `test_store_has_forced_rls_policy`).
- **Pointer-flip promotion:** promote flips to active + supersedes prior; rollback restores;
  single-active invariant (`test_promotion`).
- **Compatibility:** legacy source-scoped retrieval and all existing suites unchanged.

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Format / lint / type | `ruff format --check`, `ruff check`, `mypy apps config` | Pass — 294 files |
| Django check / drift | `manage.py check`; `makemigrations --check --dry-run` | Pass — no changes |
| Targeted PostgreSQL | `pytest apps/ingestion apps/retrieval` (PostgreSQL) | 58 passed, 2 off-PG guards skipped |
| Final SQLite | `pytest -q` | 454 passed, 18 skipped (pgvector) |
| Final PostgreSQL | `pytest -q --create-db` under `config.settings.local` + MCP/metrics flags | 470 passed, 2 skipped (off-PG guards) |

## Migrations

`documents.0002` (P4.1 binding/grant) and `ingestion.0005` (add `IndexStatus.superseded`) — additive,
no drift, applied by the full PostgreSQL `--create-db` suite.

## Checks not run

- No `FORCE` RLS on the Django-managed tenant tables + no dedicated non-owner app role (production
  hardening; the mechanism + fail-closed behavior are proven on the served stores under `SET ROLE`).
- No live embedding endpoint / retrieval-quality test (deterministic embedder).
- No headless-browser/live-server smoke.

## Final reviews

- Staff engineer: additive; legacy retrieval and public `/v1/query` contract unchanged; promotion is
  metadata-only and atomic.
- Application security: deny-by-default + app predicate + FORCE RLS backstop, all tested including a
  deliberately-omitted app predicate; store names injection-safe; tenant context transaction-local.
- SRE: pointer-flip promote/rollback are O(1) metadata ops; the superseded store is retained for
  instant rollback; deterministic default keeps CI hermetic. Broader RLS + non-owner role is the
  documented production follow-up.
