# Task Plan: phase-2-p3-embeddings

## Task summary

Implement Phase 2 P3 (Workstream 1 · M3): real embeddings + staged indexing, built and evaluated
but **not served to consumers** (the serving guardrail holds real corpora back until P4). Delivered
in two verified increments:

- **P3.1 — embedding provider foundation (this increment, done):** a platform-managed immutable
  `EmbeddingProfile` catalog + per-tenant grants, and an opt-in `OpenAICompatibleEmbeddingClient`
  over the ADR-0005 shared SSRF-safe transport, driven by a profile id only. Deterministic embedder
  remains the default; no live egress, no new dependency.
- **P3.2 — staged blue/green indexing (next increment):** per-`IndexVersion` immutable vector
  stores with system-generated names + name-parameterized DAL (ADR-0003), `IndexVersion` re-scoped
  to `(org, document_set_version, embedding_profile)`, a staged build over managed documents,
  dimension/index-type-validated store provisioning, governed eval on the candidate, retention/
  purge of unreferenced stores, and a data migration moving the existing 64-dim chunks into a
  per-`IndexVersion` store — all PostgreSQL-only for the vector paths.

## Background

Phase 2 kickoff is approved; P1 (chat) and P2 (content plane) are verified. Owner-set order:
shared egress/provider infra → chat → **embedding/indexing** → document-ACL retrieval → UI. The
egress governance is ADR-0002 (profile-id-only catalog, stdlib adapter, no blind retry) implemented
by ADR-0005; the vector-storage design is ADR-0003 (immutable blue/green per-`IndexVersion` stores,
pointer-flip promotion, `vector`≤2000 / `halfvec`≤4000, no silent truncation).

## Scope (P3.1 — this increment)

- `EmbeddingProfile` (platform-managed, immutable, revisioned) + `TenantEmbeddingProfileGrant`
  (per-tenant allowlist) models and additive migration.
- `validate_embedding_profile_fields` including the dimension/index-type rule (reject unsupported
  dimension — never truncate).
- `OpenAICompatibleEmbeddingClient` + `DeterministicEmbeddingProvider` + `get_embedding_provider()`
  factory behind `RUNTIME_EMBEDDING_PROVIDER` (empty → deterministic 64-dim).
- Platform-admin `register_embedding_profile` / `grant_embedding_profile` services (audited,
  redacted) + `register_embedding_profile` / `grant_embedding_profile` management commands.

## Non-goals (P3.1)

The per-`IndexVersion` store/DAL, `IndexVersion` re-scope, staged build wiring, eval-on-candidate,
retention/purge, and the chunk data migration are P3.2. Consumer serving of real corpora is P4.
Artifact/release pinning of an embedding profile is P4. No parser/OCR work (P7). No `openai`
dependency; no live embedding endpoint opened.

## Acceptance criteria (P3.1)

- Only a platform admin can register an immutable `EmbeddingProfile` revision or grant it to a
  tenant; denial and success are audited without endpoint/secret content.
- A profile with an unsupported dimension for its index type is rejected at validation
  (`vector`>2000 / `halfvec`>4000), never truncated.
- The real client resolves endpoint/model/secret only from the catalog by id, applies the ADR-0005
  transport controls (public-unicast DNS, pinned-IP TLS, redirect denial, timeout, response cap),
  enforces the exact response dimension (no truncation/pad), and treats a post-send timeout as
  `outcome_unknown` with no blind retry.
- Default configuration stays deterministic and hermetic; the ingestion pipeline is unchanged.

## Affected components (P3.1)

`apps/ingestion` (new `EmbeddingProfile`/grant models, `embedding.py`, `embedding_schema.py`,
`embedding_services.py`, two management commands, migration `0003`), `config/settings/base.py`
(`RUNTIME_EMBEDDING_PROVIDER`), tests, and Phase 2/master/current-state docs.

## Data impact

Additive: `ingestion_embeddingprofile` (platform-scoped, immutable) and
`ingestion_tenantembeddingprofilegrant`. No content persisted; audit carries ids/counts only.

## Security impact

Removes author/tenant-controlled embedding destinations and credentials (catalog-only). SSRF/DNS-
rebinding/redirect/TLS/timeout/size controls are the single shared ADR-0005 choke point. Full
analysis in `threat-model.md`.

## Authorization impact

Profile registration and tenant grants are platform-admin-only and audited. The runtime reads
active catalog profiles by id; tenant/artifact/request input cannot alter destination, secret, or
TLS policy. Per-tenant grant enforcement at build time lands with P3.2.

## Observability impact

Audit `embedding_profile.create` / `embedding_profile.grant` (allow/deny) with ids/dimensions/
status only — never endpoint, host, or secret ref. No prompt/embedding-input/response content in
logs or audit.

## Migration impact

One additive migration (`ingestion.0003`). No destructive change; the deterministic default keeps
the full suite runnable without live egress. The chunk data migration is deferred to P3.2.

## Dependencies

No new production dependency (reuses the stdlib `apps.tools` egress). Live embedding egress requires
a separate environment-specific owner sign-off and is outside this increment.

## Test plan (P3.1)

Schema: valid fields; vector/halfvec dimension limits (no truncation); field rejections. Services:
platform-admin-only registration + grant, audit redaction, immutability. Client (offline-injected):
deterministic default; catalog happy path + normalization; dimension mismatch; batch-limit; private
DNS denied before transport; redirect/malformed/shape fail-closed; post-send timeout =
`outcome_unknown`; unknown/disabled profile fail-closed. Full suite on SQLite and PostgreSQL.

## Rollout / rollback

Ship the additive catalog and opt-in client while deterministic remains default. Populate approved
profiles through the governed command only after a separate environment-specific egress approval.
Rollback: leave `RUNTIME_EMBEDDING_PROVIDER` empty (deterministic); the catalog is additive and
inert. Reverse `ingestion.0003` only before data is relied upon.

## Scope (P3.2 — staged blue/green indexing)

- Name-parameterized per-`IndexVersion` vector-store DAL (`apps/ingestion/vector_store.py`):
  `provision_store` / `write_chunks` / `search` (cosine) / `store_exists` / `drop_store`; store name
  is `chunk_iv_<int-pk>` (regex-validated, never external input); `vector(D)`/`halfvec(D)` fixed per
  store; PostgreSQL-only (fails closed off PostgreSQL).
- `IndexVersion` re-scoped: additive nullable `document_set_version` + `embedding_profile` +
  `dimensions` + `index_type` + `store_ready`; `source` made nullable; conditional unique on
  `(document_set_version, embedding_profile, version)`. Migration `ingestion.0004`.
- `build_staged_index` (`apps/ingestion/staged_build.py`): tenant-grant check (deny-by-default),
  published-set-version + active-profile checks, provision store, read each pinned `DocumentVersion`
  blob (`text`/`markdown` only in P3), chunk, embed (deterministic default), write via the DAL,
  leave `promotable` (never `active` — serving guardrail), audited; fail-closed drops the partial
  store; `retire_staged_index` drops a staged/superseded store (refuses an active one).
- `build_staged_index` management command.

## Non-goals (P3.2)

Pointer-flip promotion to `active` + release/binding pinning + eval-on-candidate + repointing the
served retriever + migrating the legacy 64-dim `Chunk` rows into per-`IndexVersion` stores are **P4**
(they cross the serving guardrail and the ACL/RLS core). The legacy `Chunk` table and the current
`/v1/query` retriever are left untouched here.

## Status

**P3 Implemented and Verified.** P3.1 (2026-07-12): SQLite 437 / PostgreSQL 439. P3.2 (2026-07-13):
per-`IndexVersion` store DAL + re-scoped `IndexVersion` (migration `0004`) + staged build, verified
on real PostgreSQL (store built/written/cosine-searched); SQLite 440 passed / 10 skipped (pgvector),
PostgreSQL `--create-db` 448 passed / 2 skipped (off-PG guards). No live endpoint opened; the served
retriever is unchanged. Continue at **P4** (document-ACL retrieval + RLS + pointer-flip promotion).

## Completion criteria

Acceptance criteria mapped in `verification.md`; ruff/mypy/check/migration/SQLite/PostgreSQL,
authorization, tenant-isolation, SSRF, redaction, and final-diff reviews pass for P3.1 and P3.2.
