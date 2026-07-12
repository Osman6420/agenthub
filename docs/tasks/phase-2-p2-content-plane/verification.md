# Verification: phase-2-p2-content-plane

## Status

Verified 2026-07-12. Automated evidence only; the suite ran with the hermetic in-memory object
store and opened no socket to a real object store or egress endpoint.

## Acceptance criteria mapping

- **Rename preserves data & relationships**: `RenameModel` (rows/PKs/FKs preserved); `Chunk.document`
  targets `IndexedDocument`; retriever access (`select_related("document")` →
  `document.source_uri`) verified; migration applies on SQLite and PostgreSQL with no drift.
- **Upload + versioning**: blob stored under a tenant-prefixed key; immutable `DocumentVersion`
  recorded; second upload advances `current_version`; empty/mime/oversized rejected with stable
  codes leaving no version.
- **Removal**: soft-delete tombstones idempotently (single audit); purge removes blobs + versions,
  is audited and admin-gated, and refuses a document pinned into a published set (`DOCUMENT_IN_USE`).
- **Tenant isolation**: cross-tenant `DocumentVersion`/`DocumentSetVersion`/membership rejected by
  `clean()`; a cross-tenant document version cannot be pinned into another tenant's set.
- **Operator API**: 401 unauthenticated; membership-scoped list; author-gated upload/soft-delete;
  admin-gated purge; cross-tenant 404; response never contains `object_key`.
- **Hermetic**: default deterministic runtime unchanged; no live egress; object store injected.

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Baseline SQLite | `pytest -q` (before changes) | 375 passed, 2 skipped |
| Format | `ruff format --check .` | Pass — 277 files |
| Lint | `ruff check .` | Pass |
| Type check | `mypy apps config` | Pass — 276 files |
| Django check | `manage.py check` | Pass |
| Migration drift | `makemigrations --check --dry-run` | Pass — no changes |
| Diff whitespace | `git diff --check` | Pass |
| Final SQLite | `pytest -q` | 410 passed, 2 PostgreSQL-only skipped |
| Final PostgreSQL | `pytest -q --create-db` under `config.settings.local` with `MCP_ENABLED=true` + `METRICS_BEARER_TOKEN` | 412 passed |
| Targeted content plane | `pytest apps/documents apps/ingestion apps/retrieval` | Pass — 45 (PostgreSQL, incl. pgvector + advisory-lock) / 43 + 2 skipped (SQLite) |

## Security and authorization evidence

Negative tests prove: unauthenticated 401; cross-tenant list isolation and 404 detail; author-role
requirement for upload and soft-delete (auditor 403); admin-role requirement for purge (author 403);
out-of-scope org upload 404; cross-tenant membership rejection; object-key absence from API
responses; invalid object-key rejection; upload size/mime/empty rejection; purge refusal for pinned
content. Audit assertions confirm the upload event records the checksum (not content) and the
soft-delete/purge events are written.

## Migration verification

`ingestion.0002_rename_document_indexeddocument` renames `ingestion_document →
ingestion_indexeddocument` and retargets the `Chunk.document` FK. It drops the pgvector HNSW index
from Django state around the rename (empty DB operations) so the SQLite chunk-table remake does not
regenerate the index's invalid `WITH (...)` DDL; the physical index is untouched on PostgreSQL and
never existed on SQLite. `documents.0001_initial` is additive (five tables, tenant-scoped
constraints). No drift; the full PostgreSQL `--create-db` suite applies both.

## Checks not run

- No live object-store (MinIO/S3) integration test: uploads use the hermetic in-memory backend by
  design; a real-store smoke is an operational follow-up.
- No RLS / cross-tenant-at-DB-layer test: RLS is P4 (not in this scope).
- No embedding/retrieval behavior test beyond "unchanged": P2 changes no retrieval path.
- Frontend gates: no frontend files changed.
- Container/secret/dependency scanners: no dependency, image, or lockfile changed.

## Final reviews

- **Staff engineer**: change is confined to the content plane + a data-preserving rename; the
  deterministic runtime and public contracts are unchanged; migrations are additive/reversible.
- **Application security**: tenant columns are mandatory and same-tenant-validated; object keys are
  opaque and never disclosed; uploads are bounded and stored inert; purge is elevated, audited, and
  fail-closed. RLS remains the deferred P4 second layer.
- **SRE**: the object store is a new backing dependency for uploads; failures fail closed with
  stable codes; the hermetic backend keeps CI green; both migrations are reversible.

## Remaining risks

Tenant isolation currently rests on the app predicate + `clean()` invariants until P4 adds FORCE
RLS. Declared mime is trusted for the allowlist (no content sniffing until P7). A transient
object-store error mid-purge is recoverable by a safe purge retry.
