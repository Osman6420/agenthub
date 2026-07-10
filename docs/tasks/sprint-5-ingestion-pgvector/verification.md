# Verification: sprint-5-ingestion-pgvector

## Result

Sprint 5 implemented and verified on 2026-07-10 with SQLite and PostgreSQL 16 plus
pgvector.

## Evidence

- SQLite full suite: 82 passed, 2 PostgreSQL-only tests skipped.
- PostgreSQL full suite: 84 passed.
- Focused PostgreSQL suite after outbound hardening: 10 passed.
- Ruff lint/format, mypy (130 source files), Django check, and migration-drift check passed.

## Acceptance evidence

- Duplicate claim is denied; a second PostgreSQL session cannot acquire the same
  source advisory lock.
- Successful ingestion atomically creates a `promotable` staged index; it never
  activates the index.
- Terminal failures dead-letter and audit; retry scheduling is also audited.
- Cosine retrieval filters both tenant and explicitly pinned index ids in SQL.
- HTTPS denies non-HTTPS, credentials, redirects, unallowlisted/private destinations,
  and oversized responses. S3 is restricted to the configured bucket and
  tenant-prefixed keys with bounded timeouts/retries.

## Residual risk

- DNS rebinding also requires production egress/DNS controls.
- The deterministic embedder verifies the pipeline but is not production-quality.
- Index activation/release pinning is deferred to Sprint 6 promotion governance.
