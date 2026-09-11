# Verification: phase-2-p3-embeddings

## Status

**P3 Verified.** P3.1 (embedding provider foundation) verified 2026-07-12; P3.2 (per-`IndexVersion`
vector-store DAL + staged blue/green build) verified 2026-07-13. Automated evidence only: every
egress test injects an offline resolver/connection (no socket, no live endpoint), and the vector
store is exercised on the real Docker-Compose PostgreSQL/pgvector with the hermetic in-memory object
store (no MinIO). The served `/v1/query` retriever and the legacy `Chunk` table are unchanged
(pointer-flip promotion, ACL retrieval, RLS, and the chunk data-migration cutover are P4).

## P3.2 acceptance criteria mapping

- Per-`IndexVersion` store: `provision_store` creates a fixed-dimension `vector(D)`/`halfvec(D)`
  table + HNSW cosine index with a system-generated `chunk_iv_<pk>` name (regex-validated, never
  external input); `write_chunks`/`search`/`drop_store` verified on PostgreSQL.
- No silent truncation: `write_chunks` rejects a vector whose length ≠ the store dimension.
- Tenant scoping: `search` filters by `organization_id`; a foreign-tenant row is not returned.
- Staged build: deny-by-default tenant grant required; only a published set version + active profile
  build; `text`/`markdown` only (non-text fails closed); result is `promotable` (never `active`) and
  searchable; a failed build drops the partial store; all audited.
- Off-PostgreSQL: the DAL and build fail closed with `VECTOR_STORE_REQUIRES_POSTGRES`.
- Migration `ingestion.0004` (additive `IndexVersion` re-scope) applies with no drift.

## Checks and evidence (P3.2)

| Check | Command | Result |
| --- | --- | --- |
| Format / lint / type | `ruff format --check`, `ruff check`, `mypy apps config` | Pass — 289 files |
| Django check / drift | `manage.py check`; `makemigrations --check --dry-run` | Pass — no changes |
| Targeted pgvector | `pytest apps/ingestion/tests/test_vector_store.py apps/ingestion/tests/test_staged_build.py` (PostgreSQL) | 9 passed, 2 off-PG guards skipped |
| Final SQLite | `pytest -q` | 440 passed, 10 skipped (pgvector) |
| Final PostgreSQL | `pytest -q --create-db` under `config.settings.local` + MCP/metrics flags | 448 passed, 2 skipped (off-PG guards) |

## Security and authorization evidence (P3.2)

Store names are int-derived and regex-validated (no SQL-identifier injection surface); all values
are bound parameters. `search` is tenant-scoped (RLS is the P4 backstop). The staged build enforces
a per-tenant embedding-profile grant (deny-by-default), rejects unpublished set versions, disabled
profiles, and non-text mime, and never leaves a half-written store `ready`. Audit records
`ingestion.staged_index.built/failed/retired` with ids/counts only (no content, no store name).

## Migration verification (P3.2)

`ingestion.0004_indexversion_dimensions_and_more` is additive (nullable FKs/fields + conditional
unique; `source` relaxed to nullable). No drift; the full PostgreSQL `--create-db` suite applies it.

## Acceptance criteria mapping (P3.1)

- Platform-admin-only catalog: `register_embedding_profile` / `grant_embedding_profile` deny
  non-admins (audited) and succeed for a superuser; audit excludes endpoint/secret (asserted).
- No silent truncation: registration rejects `vector`>2000 and `halfvec`>4000; the client rejects a
  response vector whose length ≠ the profile dimensions.
- Catalog-only, SSRF-safe egress: the client resolves endpoint/model/secret by profile id and runs
  over the ADR-0005 transport (public-unicast DNS, pinned-IP TLS, redirect denial, timeout, size
  cap); private DNS is denied before transport.
- No blind retry: a post-send timeout raises `EmbeddingOutcomeUnknown` (`outcome_unknown`).
- Immutability: an `EmbeddingProfile` cannot be mutated (except status) or deleted.
- Hermetic default: `get_embedding_provider()` returns the deterministic 64-dim provider; the
  ingestion pipeline is unchanged.

## Checks and evidence (P3.1)

| Check | Command | Result |
| --- | --- | --- |
| Format | `ruff format --check .` | Pass |
| Lint | `ruff check .` | Pass |
| Type check | `mypy apps config` | Pass — 284 files |
| Django check | `manage.py check` | Pass |
| Migration drift | `makemigrations --check --dry-run` | Pass — no changes |
| Final SQLite | `pytest -q` | 437 passed, 2 PostgreSQL-only skipped |
| Final PostgreSQL | `pytest -q --create-db` under `config.settings.local` + MCP/metrics flags | 439 passed |
| Targeted embedding | `pytest apps/ingestion` | Pass (incl. 27 new embedding tests) |

## Security and authorization evidence (P3.1)

Negative tests prove: non-platform registration/grant denial (audited); audit excludes endpoint and
secret ref; profile immutability + delete block; unsupported dimension rejection (no truncation);
response dimension mismatch rejection; private-IP DNS rejection before transport; redirect/malformed/
shape fail-closed; post-send timeout `outcome_unknown` (no retry); unknown/disabled/invalid profile
fail-closed; batch-limit enforcement.

## Migration verification (P3.1)

`ingestion.0003_embeddingprofile_tenantembeddingprofilegrant` is additive; drift clean; the full
PostgreSQL `--create-db` suite applies it.

## Checks not run (P3.1)

- No live embedding endpoint/credential/TLS/rate-limit/cost/provider-compatibility test:
  environment-specific egress is not approved.
- No per-`IndexVersion` vector-store, staged-build, eval-on-candidate, retention/purge, or chunk
  data-migration test: those are P3.2.
- Frontend / container / dependency scanners: no such files changed.

## Final reviews (P3.1)

- Staff engineer: change mirrors the verified P1 catalog/egress pattern; deterministic default and
  the ingestion pipeline are unchanged; migration is additive.
- Application security: catalog-only destinations, platform authorization, SSRF/pinned-IP TLS,
  redaction, dimension enforcement, and no-blind-retry are tested.
- SRE: opt-in rollback is configuration-only; the catalog is inert when unused; live rollout still
  requires endpoint/network approval and operational smoke.

## Remaining risks (P3.1)

Per-tenant grant enforcement at build time and all vector-store work arrive in P3.2. Live network
behavior is unverified until a separately-approved egress rollout. Platform-admin compromise remains
powerful.
