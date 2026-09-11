# Verification: Phase 2.9 Part 6

## Outcome

Completed 2026-08-02. The console navigation now reflects active exact responsibilities while all
direct routes retain server authorization. Content Reader/Manager byte access is exact-set-version,
bounded, attachment-safe and fail-closed audited. Manifest and consumer presets remain review-only
recommendations and cannot create releases or capabilities by themselves. Safe local 403/404
guidance removes technical route dumps for authenticated console requests.

## Authorization and security evidence

- Exact scenario editor, runtime operator, document content reader and unassigned navigation states
  are asserted independently. Empty runtime history does not hide a runtime operator's entry point.
- Preview/download resolve the already scoped set, document and version, then independently require
  `DOCUMENT_SET_CONTENT_READ` and an exact `DocumentSetMembership` for that version.
- Metadata-only access is denied and audited; an unpinned sibling version is denied; foreign parent
  resolution remains 404 through existing scoped querysets.
- Preview is 256 KiB max, UTF-8 strict and MIME-allowlisted; download is 25 MB max,
  `application/octet-stream`, `attachment`, `nosniff`, CSP sandboxed and `no-store`.
- Size rejection precedes object-store reads. Stored bytes and object keys are absent from audit and
  safe error payloads. Audit includes propagated request/trace IDs. A required audit failure
  propagates before any content response is returned.
- Manifest recommendations use only one unambiguous scenario workflow logical ID and scenario-owned
  canonical contract/eval logical IDs; missing/ambiguous roles remain explicit and manual.
- Consumer preset submissions must exactly match the server-owned capability tuple or select the
  custom path; model allowlist and cross-organization validation remain authoritative.

## Automated checks

- Ruff on all touched Python modules and the Part 6 test: passed.
- `manage.py check`: passed.
- `manage.py makemigrations --check --dry-run`: `No changes detected`.
- Part 6 focused backend: `9 passed`, including same-tenant cross-set and cross-tenant 404 probes.
- Console/document/authorization/release blast radius: `117 passed`.
- Full SQLite suite: `1098 passed, 61 skipped` in 193.78 s. Skips are declared PostgreSQL/pgvector/
  row-lock/RLS cases.
- Existing PostgreSQL test database, no create/reset (`--reuse-db`): Part 6 plus responsibility and
  assignment RLS tests `15 passed`.
- Manifest frontend focused test: `3 passed`.
- Full frontend: `33 passed`; TypeScript typecheck passed; Vite production build passed.
- Targeted mypy on the six touched production modules reported no Part 6 error. The command remains
  non-green on four pre-existing baseline errors in `apps/identity/assignment_services.py`,
  `apps/tenancy/services.py`, and earlier lines 168/253 of `apps/console/forms.py`; Part 7 owns the
  repository type-baseline closure. A full mypy run additionally reports existing test typing debt.
- Frontend output retained one pre-existing React `act(...)` warning in the AI authoring test; it did
  not fail the suite and is outside the changed manifest component.

## Reconciled audit findings

- Scenario Viewer Studio deep-link/read-only state is covered by the existing app deep-link suite,
  which passed in the full frontend run.
- Release lifecycle dead ends were closed by Part 3 and remained green in the backend blast radius.
- The document-set detail template has one `Taslağı yayımla` action; no duplicate remains.
- Touched release/document labels and document timestamps are Turkish-first. Local console 403/404
  HTML no longer exposes Django route lists or tracebacks to authenticated or anonymous requests.

## Interaction and accessibility evidence

- Manifest recommendation makes the release path load recommendation → review/kanonik preflight →
  candidate save, below the ten-primary-action target. Exact IDs, versions, roles and checksum
  remain visible and cannot be skipped.
- Dirty selection exposes save, discard and continue choices and retains the native unload guard.
- Existing visible-focus, skip-link, responsive table and builder-layout assertions/build remain
  green. New controls are native buttons/selects/links with accessible labels and status/alert roles.

## Review

- Staff engineering: no schema/dependency/public contract change; one content service owns the read
  contract; presets reuse existing immutable artifact and capability vocabularies.
- Application security: deny-by-default exact scope, active-content prevention, bounded reads,
  content-free errors/audit and fail-closed audit were reviewed against the threat model.
- SRE: no migration, background worker, new network call or durable state; storage errors are stable
  and safe; responses are non-cacheable; rollback is a code/template revert.

## Unverified / transferred gate

Target-browser visual, keyboard-only, responsive-width and end-to-end manual role journeys were not
claimed in this part because the current session has no browser runner. The component plan assigns
that deterministic browser and manual acceptance gate to Phase 2.9 Part 7. This is the only remaining
Part 6 presentation risk; automated DOM, backend and production-build evidence is complete.
