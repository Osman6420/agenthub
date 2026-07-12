# Threat Model: phase-2-p2-content-plane

## Assets

- Tenant document content (blob bytes in the object store) and its metadata lineage.
- Tenant isolation of content, versions, sets, and memberships.
- The audit trail of content lifecycle actions.

## Actors and entry points

- **Operators** (LDAP/session console identity) through the JSON API under
  `/console/api/documents/`. No consumer/bearer path exists on this surface.
- **The ingestion pipeline**, which still writes the renamed `IndexedDocument` build artifact.
- **The object store** (S3/MinIO), a backing service reached only by the server.

## Trust boundaries

- Console operator ↔ server: authorization is server-side (membership + role); CSRF enforced;
  the frontend is non-authoritative.
- Server ↔ object store: keys are server-constructed, tenant-prefixed, and traversal-validated.
- Tenant ↔ tenant: every model carries a mandatory, immutable `organization`; `clean()` rejects
  cross-tenant parent/child links; all querysets derive scope from `allowed_organization_ids`.

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Cross-tenant read of documents/sets | Membership-scoped querysets; cross-tenant detail returns 404; API tests assert isolation. |
| Cross-tenant write (pin another tenant's content into a set) | `DocumentSetMembership.clean()` requires the pinned `DocumentVersion` and the set version to share the tenant; negative test covers it. Forward-ready for P4 FORCE RLS. |
| Privilege escalation (non-author uploads / non-admin purges) | Upload/soft-delete require `can_author_scenarios`; purge requires `can_admin_org`; tests assert 403 denials. |
| Object-key traversal / cross-prefix access | Keys are built only by `build_object_key` (opaque, `tenants/<org>/` prefixed); the store validates prefix and rejects `..`/leading-slash; get/delete operate only on keys read from tenant-scoped rows. |
| Blob/key or store-internal disclosure | The API never serializes `object_key`, physical store names, or endpoints; a storage failure maps to a content-free `storage_unavailable` (502); redaction test asserts no `object_key` in responses. |
| Upload abuse (oversized, unexpected type, empty) | Size cap (`DOCUMENTS_MAX_UPLOAD_BYTES`), declared-mime allowlist, and empty-body rejection; oversized upload leaves no version. Bytes are stored inert (no parsing/execution in P2). |
| Content injection via document text | Document bytes are treated as untrusted data and never interpreted; parsing/embedding (which will keep text as data, separate from system prompts) is deferred to P3/P7. |
| Purging content still served | Purge refuses (`DOCUMENT_IN_USE`) any document with a version pinned into a published set (`PROTECT` FK backs the check). |
| Audit tampering / loss | Audit is append-only (model-enforced) and written in the same transaction as the state change (fail-closed); purge audit precedes the delete within one transaction. |
| Secret leakage in logs/audit | No secrets are handled here; audit carries ids/counts/checksums/stable codes only. |
| Rename data loss | `RenameModel` preserves rows/PKs/FKs; verified on SQLite and PostgreSQL and by the ingestion pipeline suite; reversible. |
| DoS via orphaned blobs | Upload writes the blob before the DB row and best-effort deletes it on DB failure; unique random keys make stray orphans unreferenced and reclaimable by the P3 retention/purge job. |

## Residual risks

- **RLS is not yet enforced** (P4). Tenant isolation currently rests on the app predicate +
  `clean()` invariants; the FORCE-RLS second layer is deferred by design (serving guardrail: no
  real tenant corpus is served to consumers until P4).
- **No content-type sniffing**: the declared mime is trusted for the allowlist only; content
  validation/parsing is P7. Bytes are stored inert, so this does not enable execution.
- **Object-store availability** is a new operational dependency for uploads; failures fail closed
  with a stable code but block uploads until restored.
- A transient object-store error during purge can leave some blobs deleted while metadata remains;
  purge is idempotent and safe to retry to convergence.
