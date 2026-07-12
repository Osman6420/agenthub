# Task Plan: phase-2-p2-content-plane

## Task summary

Implement Phase 2 P2 (Workstream 1 · M1): the tenant-owned **content plane** and its storage.
Rename the Sprint 5 index build artifact `ingestion.Document → IndexedDocument`, add the new
`apps/documents` app (`Document → DocumentVersion` content lineage plus `DocumentSet →
DocumentSetVersion → DocumentSetMembership` versioning), object-store blob upload, soft-delete
tombstone, and an auditable physical purge, all exposed through a role/tenant-scoped operator
JSON API. No retrieval behavior change, no scenario binding, no ACL enforcement, and no RLS —
those arrive in P4.

## Background

Phase 2 kickoff is approved; P1 (live chat + shared egress catalog) is verified. The document
plane is designed in [`components/document-plane-plan.md`](../../planning/components/document-plane-plan.md)
with owner decisions A–E, and its M0 spikes are accepted as ADR-0003/0004/0005. The interleaved
delivery order in [`runtime-and-document-plane-sequence.md`](../../planning/components/runtime-and-document-plane-sequence.md)
places P2 (content plane & storage) after P1 and before P3 (real embeddings). Sprint 5 modeled
content as an index-scoped `Document` (a build artifact); P2 introduces the managed content object
and frees the `Document` name via `RenameModel`.

## Scope

- Rename `ingestion.Document → IndexedDocument` with a rows/PKs/FKs-preserving `RenameModel`
  migration; update `Chunk.document`, the ingestion service, and the retriever reference.
- New `apps/documents` models: `Document`, `DocumentVersion` (immutable), `DocumentSet`,
  `DocumentSetVersion` (immutable published snapshot), `DocumentSetMembership` (immutable). Every
  model carries a mandatory, denormalized `organization` (tenant) column and `clean()` rejects any
  cross-tenant parent/child link (forward-ready for P4 RLS).
- Object-store abstraction with a real S3/MinIO backend and a hermetic in-memory backend for
  tests; per-tenant opaque key prefix; bounded size and mime allowlist.
- Services: upload (blob + immutable version, advancing `current_version`), soft-delete tombstone
  (idempotent), auditable physical purge (elevated, fail-closed, refuses content pinned into a
  published set), and document-set create/version/add-member/publish. All audited in-transaction.
- Operator JSON API under `/console/api/documents/` reusing console LDAP/session + role/tenant
  authorization and CSRF; read is membership-scoped, write requires `can_author_scenarios`, purge
  requires `can_admin_org`.

## Non-goals

Scenario↔document-set binding, retrieval ACL predicate, `DocumentSetGrant` enforcement, and
PostgreSQL RLS (all P4); real embeddings, `EmbeddingProfile`, and per-`IndexVersion` blue/green
stores (P3); parsers/OCR/Confluence/REST connectors and the parser dependency (P7); the console
HTML/SPA surface (P8); linking `IndexedDocument → DocumentVersion` (added in P3 when managed
documents are embedded). No new production dependency and no new external egress.

## Acceptance criteria

- The rename preserves data: existing ingestion rows/PKs/FKs are intact; `Chunk.document` targets
  `IndexedDocument`; the retriever still cites `document.source_uri`/`title`; migration applies on
  SQLite and PostgreSQL with no drift.
- Upload stores bytes in the object store under a tenant-prefixed key and records an immutable
  `DocumentVersion`; a second upload advances the version; size/mime/empty validation rejects bad
  input with stable codes and leaves no version.
- Soft-delete tombstones idempotently; purge physically removes blobs + versions, is audited and
  elevated-role-gated, and refuses a document pinned into a published document-set version.
- Every parent/child model relationship is same-tenant; a cross-tenant document version cannot be
  pinned into another tenant's set.
- The operator API is 401 without auth, membership-scoped on read, author-gated on write,
  admin-gated on purge, 404 cross-tenant, and never exposes object keys/store internals.
- Deterministic/hermetic gates: the suite runs with an in-memory object store and no live egress.

## Affected components

`apps/ingestion` (rename + service ref + retriever ref), new `apps/documents`, `config/settings`
(app registration, storage settings, test backend), `config/urls` (API mount), task docs, and the
verified-state/handoff/planning status lines.

## Interfaces affected

New internal operator JSON API under `/console/api/documents/`. Internal `ingestion.Document`
Python/table name changes to `IndexedDocument` (rows preserved). No public consumer gateway
contract change; `/v1/query` / `/v1/invoke` behavior unchanged.

## Data impact

Additive: five new `documents_*` tables plus a rename of `ingestion_document →
ingestion_indexeddocument`. Blob bytes live in the object store (tenant-prefixed); the DB holds
metadata only (checksum, mime, opaque key, counts). No document content is persisted in logs or
audit.

## Security impact

New tenant-scoped content tables with mandatory, immutable `organization` columns and same-tenant
`clean()` invariants; object keys are opaque and tenant-prefixed; the API never leaks keys/store
names. Uploads are size- and mime-bounded and treated as inert data (no parsing/execution in P2).
Full analysis in `threat-model.md`.

## Authorization impact

Read is membership-scoped; create/upload/soft-delete require the scenario-author role; physical
purge requires the elevated organization-admin role; cross-tenant targets 404. All decisions are
server-side; the API carries no bearer path and enforces CSRF.

## Observability impact

Audited actions (redacted; ids/counts/checksum/stable state only): document upload, soft-delete,
purge; set create; set-version create/add-member/publish. Purge and all audit writes are
in-transaction (fail-closed). No content, object keys, or store names in logs/audit.

## Migration impact

`ingestion.0002_rename_document_indexeddocument` (rename; drops the pgvector HNSW index from state
around the rename so the SQLite chunk-table remake does not emit invalid `WITH` DDL — the physical
index is untouched on PostgreSQL and absent on SQLite, matching Sprint 5) and `documents.0001`
(additive). Both are reversible and verified on SQLite and PostgreSQL.

## Dependencies

No new production dependency (the S3 client reuses the already-approved `boto3`). No new external
egress. The object store is a required backing service for uploads in local/production; tests use
the hermetic in-memory backend.

## Implementation steps

1. Capture the green baseline; inventory the `Document` reference surface.
2. Rename `Document → IndexedDocument` (model, service, retriever, `RenameModel` migration).
3. Add `apps/documents` models + migration; register the app and settings.
4. Add the object-store abstraction (S3 + in-memory) and the document/document-set services.
5. Add the operator JSON API + URLs; mount under `/console/api/documents/`.
6. Add model/storage/service/api/rename tests, including tenant-isolation negatives.
7. Run the SQLite and PostgreSQL gates plus ruff/mypy/check/drift; update the verified-state and
   handoff/planning docs; commit.

## Test plan

Storage roundtrip + idempotent delete + invalid-key rejection + hermetic backend; model
cross-tenant `clean()` rejections + object-key uniqueness; service upload/versioning/validation,
soft-delete idempotency, purge (blob+version removal, in-use refusal), document-set lifecycle +
cross-tenant membership rejection; API auth/scoping/role-gating/redaction/cross-tenant-404;
rename FK/table integrity + retrieval-shaped access. Full suite on SQLite and PostgreSQL.

## Rollout plan

Additive migrations plus a table rename applied before serving. The object store is configured per
environment; the deterministic/hermetic backend keeps CI green. No consumer-facing change ships.

## Rollback plan

Both migrations are reversible (the rename ships a symmetric down path; `documents.0001` drops the
additive tables). The document plane is inert until P3/P4 wire it into embeddings/retrieval, so
reversing it does not affect current retrieval.

## Status

Implemented and Verified (2026-07-12). No live object store or egress was opened by the automated
suite (hermetic in-memory backend). Continue at P3 (real embeddings + indexing, staged).

## Completion criteria

Acceptance criteria mapped in `verification.md`; ruff/mypy/check/migration/SQLite/PostgreSQL,
authorization, tenant-isolation, redaction, and final-diff reviews pass.
