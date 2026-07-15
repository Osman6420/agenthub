# Task Plan: phase-2-5-part-4-document-set-lifecycle

## Task summary

Deliver the Phase 2.5 Part 4 document-set-first content lifecycle while preserving immutable
document versions, existing storage/purge safety, tenant isolation, and published set snapshots.

## Background

The console already supports document-set creation, bulk upload into a manual draft, set-version
publication, staged index builds, promotion, scenario bindings, consumer grants, and an advanced
standalone document inventory. The primary journey still lacks set-scoped document inspection,
replacement, draft removal, tombstoning, and explicit lifecycle blockers/next actions.

## Scope

- Keep document sets as the primary navigation and content-management surface.
- Move standalone storage/purge inventory behind an explicitly advanced administration route and
  expose it only to organization/platform administrators.
- Add set-scoped inspection of document lineage, parse state, source, memberships, and versions.
- Add set-scoped replacement, removal from mutable drafts, and tombstoning actions.
- Preserve immutable published set versions and exact document-version pinning.
- Present the upload -> parse/normalize -> draft -> published set -> staged index -> active index
  lifecycle with blocking reasons and the next authorized action.
- Cross-link document sets, documents, sources, scenarios, consumers, versions, and active indexes.
- Add authorization, tenant-isolation, audit, failure, and compatibility tests.

## Non-goals

- Changing object-store layout, purge semantics, retention policy, connector execution, parsing,
  index-build internals, or public APIs.
- Removing legacy integer console routes in this part.
- Allowing edits to published document-set versions.
- Physically deleting bytes from the ordinary author workflow.
- Delivering the unified connector/mapping journey reserved for Part 5.

## Acceptance criteria

1. Primary navigation points to document sets and has no standalone document inventory entry.
2. Only platform/org administrators can open the advanced storage/purge inventory; ordinary tenant
   readers/authors cannot enumerate it or invoke purge.
3. An authorized author can inspect a document from its set, upload a replacement as a new immutable
   version, pin it into the active manual draft, remove a member from a draft, and tombstone content.
4. Cross-tenant object identifiers and unauthorized mutations fail closed without revealing object
   existence.
5. Published set memberships remain immutable; removal/replacement affects only a draft snapshot.
6. Tombstoning does not purge bytes or rewrite historical published memberships.
7. Lifecycle UI shows current states, blockers, and only actions the operator is authorized to take.
8. Storage failures and audit failures preserve safe metadata/blob behavior and surface bounded
   operator messages.
9. Focused and full regression checks pass on the repository-supported databases, with evidence
   recorded without quiet test output or premature timeout termination.

## Affected components

- `apps/console`: routes, views, templates, forms, scoping, and tests.
- `apps/documents`: draft membership mutation services and tests.
- `apps/ingestion`: read-only lifecycle/index/source relationships and regression tests.
- Architecture and planning documentation.

## Interfaces affected

Additive authenticated console HTML routes only. Existing internal service signatures and public API
contracts remain compatible.

## Data impact

No schema migration is planned. Replacement creates a new immutable `DocumentVersion`; draft
membership changes update only `DocumentSetMembership`; tombstoning updates lifecycle metadata.

## Security impact

Uploaded bytes remain untrusted and bounded by existing type/size validation. Object-store keys,
checksums, and raw content must not be exposed in HTML. Purge remains admin-only, confirmation-bound,
audited, and blocked while any set version pins the document.

## Authorization impact

Read paths require tenant membership. Author mutations require `can_author_scenarios` for the owning
organization. Advanced inventory and purge require `can_admin_org`. Every object is scoped before
authorization and mutation, and document/set tenant equality is enforced server-side.

## Observability impact

Reuse audited document upload/tombstone/purge services. Add a stable audit event for draft membership
removal. Propagate request IDs from console mutations where supported and never log content or object
keys.

## Migration impact

None expected. Run migration-drift checks to prove no accidental schema change.

## Dependencies

Phase 2.5 Parts 1-3 and the existing documents/ingestion service contracts.

## Implementation steps

1. Baseline current routes, authorization, storage/purge behavior, set lifecycle, and tests.
2. Add task threat model and verification scaffold; mark Part 4 in progress.
3. Separate the advanced inventory from the primary document-set list and enforce admin visibility.
4. Add audited draft-member removal and set-scoped replace/tombstone views.
5. Add document detail and lifecycle projection with cross-links and authorized next actions.
6. Update templates, current-behavior documentation, and regression/security tests.
7. Run focused then full checks to completion; inspect the final diff from engineering, AppSec, and
   SRE perspectives.

## Test plan

- Console happy paths for set-scoped inspect, replace, remove, and tombstone.
- Authentication, read-only, author, org-admin, platform-admin, and cross-tenant cases.
- Published-version immutability and draft-only mutation tests.
- Storage/audit failure tests and safe operator error messages.
- Existing purge-in-use, retrieval tombstone, connector draft isolation, index, and public-ID tests.
- Formatter/linter/type-check, Django system check, migration drift, SQLite full suite, and PostgreSQL
  focused/full suites as applicable. Pytest output is not quieted and test execution is allowed to
  finish.

## Rollout plan

Deploy as additive console routes and service behavior. No migration or destructive data operation.
Restart web/workers only if live manual verification is requested after automated checks.

## Rollback plan

Revert the console/service/template changes. Created immutable document versions remain valid; no
backfill or destructive reversal is required.

## Risks

- Removing a document from the wrong snapshot could violate reproducibility; mutations are draft-only
  under row locks.
- Tombstoning may surprise users because historical pins remain; UI must state this explicitly.
- Partial object-store upload failures may leave bounded orphan-cleanup risk already handled by the
  existing upload service.
- An advanced inventory authorization regression could leak tenant metadata; enforce both queryset
  scoping and admin checks, with denial tests.

## Open questions

- Turkish browser owner review remains required after automated verification.
- Whether retention policy later permits purging historically pinned versions remains outside Part 4.

## Status

Verified. Implementation, SQLite/PostgreSQL regression, authorization, tenant-isolation, audit,
storage/purge compatibility and static checks passed. Authenticated Turkish owner browser acceptance
remains before `Completed`. Scope was approved by the owner on 2026-07-15.

## Completion criteria

All acceptance criteria are implemented; applicable Definition of Done checks and authorization,
tenant, storage, audit, compatibility, and manual-review evidence are recorded separately.
