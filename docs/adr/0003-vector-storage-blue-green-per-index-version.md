# ADR 0003: Vector storage — immutable blue/green per-`IndexVersion` stores with pointer-flip promotion

- **Status:** Accepted
- **Date:** 2026-07-12

Records the output of **Phase 2 · WS1 M0 Spike 1** (pgvector multi-dimension storage). The decision
is accepted; *implementation timing* is gated by Phase 2 approval.

## Context

The document plane (WS1) must let an active index keep serving while a **new** index of a possibly
**different embedding dimension** is built and evaluated, then promote/roll back without downtime.
pgvector realities constrain this:

- An approximate-search index (HNSW) is built over a **fixed-dimension** column; **HNSW supports up
  to 2000 dims for `vector` and 4000 for `halfvec`**.
- An untyped `vector` column *can* store mixed-dimension rows, but a single HNSW index cannot span
  them — you would need per-dimension expression/partial indexes.
- Today `apps/ingestion` has one `Chunk` table with a static `VectorField(dimensions=64)` and a
  `source`-scoped `IndexVersion`. WS1 re-scopes `IndexVersion` to `(org, document-set-version,
  embedding-profile)` and forbids in-place mutation of an active index.

## Considered options

1. **Dimensionless `vector` column + per-dimension expression/partial indexes.** One physical table
   holding all chunks; a partial HNSW index per dimension (or per index version) via a `WHERE`
   predicate. *Pros:* one table. *Cons:* fragile partial-index management and planner dependence on
   partial-index selection; cross-tenant/version rows share one heap (VACUUM/bloat coupling); a
   version's data cannot be dropped by a cheap `DROP`; promotion still needs careful predicate
   swaps.
2. **One typed `vector(D_env)` table with two blue/green copies (active/staged).** Simple if the
   deployment pins a single dimension, but breaks the moment two dimensions must coexist during a
   dimension change.
3. **A separate immutable physical store per `IndexVersion`** — its own fixed-dimension
   `vector(D)`/`halfvec(D)` column and HNSW index. *Pros:* clean isolation; independent build, drop,
   and retention; **promotion is a metadata pointer flip that touches no vector data**; dimension/
   index-type fixed per store so every HNSW is valid. *Cons:* many relations; store DDL is created
   at build time (names must be system-generated).

**Chosen: Option 3.** Option 1 is recorded as a documented fallback for pathological
high-cardinality/small-set cases; Option 2 is a permitted simplification only where a deployment
provably pins one dimension.

## Decision

- **One physical store per `IndexVersion`.** Column type is `vector(D)` for `D ≤ 2000` and
  `halfvec(D)` for `2000 < D ≤ 4000`, with `D` taken from the pinned `EmbeddingProfile`; an
  unsupported `D`/index-type is **rejected at ingestion start — never truncated**. Each store has
  its own HNSW index with the cosine opclass.
- **System-generated names.** The store relation name is derived from the `IndexVersion` identity
  via a fixed, sanitized template (e.g. `chunk_iv_<id>`), **never** from tenant/user/author input.
- **Status machine:** `building → promotable` (only after the Sprint 6 governed eval) `→ active /
  superseded`. A staged store is never auto-promoted.
- **Promotion / rollback = metadata pointer flip.** Promotion updates the release/binding
  `active_index_version_id` in a **single transaction**; it performs **no rename, copy, or index
  rebuild**. Rollback flips the pointer back. The prior store stays intact for instant rollback.
- **Retention/purge** drops a superseded store's physical relation **only when no release references
  it** and after a retention window; the drop is audited.
- **ORM access.** Because dimensions vary per store, these are **not** static Django models and
  **cannot** be partitions of one typed parent (partitions share the parent column type). They are
  provisioned by migration/DDL and read/written through a thin, **name-parameterized** data-access
  layer that only ever targets a system-generated store name resolved from an `IndexVersion` row
  (no string interpolation of external input). This DAL is the main implementation risk and is
  validated first in the WS1 M3 increment.

## Security consequences

- Physical isolation per index version bounds the blast radius of any single store and makes
  tenant-scoped drops/retention clean. Store names are never attacker-influenced (no SQL-identifier
  injection surface). Each store still carries `tenant_id` and is covered by RLS
  ([ADR-0004](0004-tenant-isolation-postgres-rls-connection-context.md)).

## Operational consequences

- Many relations and build-time DDL; a store inventory + retention job are required. Promotion and
  rollback become O(1) metadata operations (fast, safe, auditable). SQLite cannot exercise this;
  it is a PostgreSQL-only path in tests, like the existing pgvector suite.

## Data and privacy consequences

- Embeddings/chunks inherit tenant classification; store names, vectors, and content never appear in
  logs, metrics labels, or audit (ids/counts/checksums only).

## Positive / negative consequences

- **+** Zero-downtime blue/green reindex across dimension changes; atomic promote/rollback; clean
  retention. **−** More relations to manage and a bespoke name-parameterized DAL instead of a plain
  Django model.

## Migration impact

- Additive: introduce the `EmbeddingProfile`, the per-`IndexVersion` store model/DAL, and a data
  migration that moves existing Sprint-5 deterministic 64-dim chunks into a per-`IndexVersion`
  store, preserving rows. The deterministic profile keeps passing. No consumer-contract change.

## Rollback considerations

- The pointer flip is itself the rollback primitive. If the per-store approach proves operationally
  heavy, Option 2 (single active/staged pair for a pinned dimension) is the documented fallback via
  configuration, without changing the promotion semantics.

## References

- [Document plane plan](../planning/components/document-plane-plan.md) — Spike 1, storage design.
- [WS1+WS5 sequence](../planning/components/runtime-and-document-plane-sequence.md) — P3/P4.
- [ADR-0004](0004-tenant-isolation-postgres-rls-connection-context.md) — RLS over these stores.
- pgvector HNSW dimension limits (`vector` ≤ 2000, `halfvec` ≤ 4000); cosine opclasses.
