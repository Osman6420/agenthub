# Verification: phase-2-p3-embeddings

## Status

**P3.1 (embedding provider foundation) Verified 2026-07-12.** Automated evidence only; every
transport test injects an offline resolver/connection, so no socket is opened and no live embedding
endpoint was configured or called. **P3.2 (staged blue/green indexing) is not yet implemented.**

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
