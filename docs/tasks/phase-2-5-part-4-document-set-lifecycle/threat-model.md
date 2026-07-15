# Threat Model: phase-2-5-part-4-document-set-lifecycle

## Assets

Tenant document metadata and bytes, immutable document versions, set snapshots, source provenance,
index pointers, authorization decisions, and audit evidence.

## Actors

Unauthenticated users, tenant readers, authors, organization administrators, platform administrators,
connector workers, and storage/index infrastructure.

## Entry points

Authenticated console list/detail pages and POST actions for upload, replace, draft removal,
tombstone, publish, build, promote, and purge.

## Trust boundaries

Browser to Django; Django authorization to tenant-scoped ORM queries; Django to object storage;
documents to ingestion/index services; application mutations to audit persistence.

## Data classifications

Document content may be confidential tenant data. Titles, filenames, source identities, membership,
checksums, object keys, and lifecycle state are tenant-sensitive metadata. Audit records are internal
security/operational data.

## Authentication

All console routes require an authenticated Django session and CSRF protection for POST actions.

## Authorization

Tenant membership gates reads; author permission gates draft/upload/tombstone mutations; org/platform
administrator permission gates the advanced inventory and purge. UI visibility is never authoritative.

## Tenant isolation

Set, document, version, membership, source, and index lookups must be scoped to an allowed organization.
Mutation services re-check organization equality and must reject cross-tenant identifiers.

## External systems

Object storage holds bytes; ingestion/parser/index systems consume exact versions. Existing time,
size, MIME, and storage error controls remain authoritative.

## Abuse cases

- Guessing UUID/integer IDs to inspect or mutate another tenant's document.
- A reader posts directly to author/admin-only routes.
- An author accesses advanced purge inventory or purges content.
- Removing or replacing a member in a frozen published version.
- Tombstoning content to erase historical audit/lineage or bypass purge controls.
- Uploading oversized, empty, unsupported, or maliciously named files.
- Surfacing object keys, raw content, stack traces, or cross-tenant existence in UI/errors.

## Failure cases

Object-store write/delete failure, audit persistence failure, concurrent draft mutation, concurrent
replacement, missing parser/index state, connector-owned draft collision, and stale form submission.

## Logging and audit risks

Filenames or titles can contain sensitive data; raw bytes, object keys, and full checksums must not be
logged. Mutations require actor, tenant, action, target, outcome, and request/trace correlation where
available. Audit write failure must not silently permit state mutation.

## Mitigations

Tenant-scoped lookups; server-side role checks; CSRF and POST-only mutations; row locks; immutable
published snapshots; existing bounded upload validation; draft-only removal; tombstone-before-purge;
exact typed confirmation; purge-in-use denial; fail-closed transactional audit; generic bounded errors;
and focused denial/cross-tenant/failure tests.

## Residual risks

The upload-before-database pattern retains a small best-effort orphan cleanup risk during compound
infrastructure failure. Tombstoned documents remain in historical snapshots by design. Browser-based
Turkish usability and accessibility require owner review.

## Required security tests

- Unauthenticated redirects and CSRF/POST enforcement.
- Reader/author/admin authorization matrix for inventory and mutations.
- Cross-tenant UUID/integer denial for detail and every mutation.
- Frozen set-version mutation denial.
- Purge role, confirmation, tombstone, and in-use denial.
- Audit failure rollback and redaction/no-object-key response assertions.
- Upload size/type/empty-file and storage failure compatibility tests.
