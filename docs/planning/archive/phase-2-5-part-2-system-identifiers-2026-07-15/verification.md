# Verification: phase-2-5-part-2-system-identifiers

> Status: Completed, owner-accepted, and verified on 2026-07-15.

| Check | Result | Evidence |
| --- | --- | --- |
| Identifier allocation, atomicity, routes and denial paths | **Passed** | Part 2 plus affected console tests: 37 passed |
| Console and tenancy regression (SQLite) | **Passed** | 95 passed, 4 skipped |
| Full repository regression (SQLite) | **Passed** | 646 passed, 29 skipped |
| Part 2 migration forward/reverse/re-forward (SQLite) | **Passed** | 1 passed; existing UUIDs survived reverse to expand and re-forward |
| Affected console and tenancy regression (PostgreSQL) | **Passed** | 97 passed, 3 skipped; includes PostgreSQL RLS/non-owner cases and migration coverage |
| Full repository regression (PostgreSQL) | **Passed** | 670 passed, 5 skipped after observability tests were correctly marked for database access required by tenant middleware |
| Static and schema gates | **Passed** | Full-app Ruff format/check, mypy (352 files), Django check, migration drift, compileall and `git diff --check` |
| Turkish owner acceptance | **Accepted** | The owner explicitly requested Part 2 closure on 2026-07-15; automated Turkish normalization and destination coverage passed; no separate browser recording is claimed |

## Acceptance criteria mapping

1. **Verified:** covered console forms omit technical identifiers and forged POST
   values cannot select them.
2. **Verified:** Turkish/ASCII, punctuation-only, long-name, duplicate, collision and
   exhaustion cases are covered by allocator tests.
3. **Verified:** scenario and its initial active
   `<project>-<scenario>-<four base32 chars>` alias are created atomically.
4. **Verified for affected contracts:** explicit service/GitOps identifiers remain
   accepted; migrations preserve existing slugs, logical IDs and consumer subjects.
5. **Verified:** project, scenario, document, document-set and consumer public IDs are
   unique, non-null UUIDs after migration and default on new rows.
6. **Verified:** generated links use scoped UUID routes; legacy integer GET and POST
   handlers remain compatible and share the same authorization path.
7. **Verified:** display-name changes cannot mutate generated identifiers or public IDs.
8. **Verified:** malformed, missing and foreign-tenant locators are non-disclosing.
9. **Verified for changed surfaces:** permission checks, disabled-organization denial,
   method restrictions, audit calls and PostgreSQL RLS regressions pass.
10. **Verified:** additive expand/backfill/constrain migrations pass
    forward/reverse/re-forward tests on SQLite and PostgreSQL. Rollback retains the
    additive columns at the expand state.
11. **Accepted:** automated Turkish behavior passes and the owner explicitly accepted
    Part 2 closure without requiring a separate browser recording.
12. **Verified:** no dependency, credential, egress, production or destructive-data
    change was introduced.

## Security and authorization evidence

- Public UUIDs are locators only. Both canonical and legacy resolvers first restrict
  candidates to organizations allowed for the authenticated actor, install the
  trusted singleton tenant scope, and then apply the existing action permission.
- Cross-tenant UUID/integer, malformed UUID, absent target, anonymous, wrong-role and
  disabled-organization tests retain non-disclosing responses.
- Identifier suffixes use `secrets`, bounded retry counts and content-free failure
  codes. Document IDs do not include original filenames or document content.
- Scenario plus alias creation and document-set create/audit execution are atomic.
  Unrelated integrity errors are not mislabeled as identifier collisions.

## Compatibility, logging and audit evidence

- Existing slugs, logical IDs, aliases, consumer subjects, storage-key inputs and
  explicit declarative creation seams are not rewritten.
- Existing console creation/action audit calls remain on the shared handlers. No
  identifier, filename or user-entered name was added as a metrics label.
- Artifact and release integer routes are intentionally unchanged for the Part 6
  authoring-contract review; consumer subject/token behavior remains Part 3 scope.

## Migration verification

Each affected app uses an additive three-stage sequence: nullable expand, per-row UUID
backfill on the active database alias, then unique/non-null constrain with UUIDv4
defaults for future rows. The migration test begins at the pre-expand graph, creates
representative existing data, migrates to constrained state, checks uniqueness and
preservation, reverses to expand, then re-forwards while asserting the same UUIDs.

## Commands and results

- `ruff format --check apps/catalog apps/documents apps/identity apps/tenancy apps/console`:
  78 files already formatted.
- `ruff check apps/catalog apps/documents apps/identity apps/tenancy apps/console`:
  all checks passed.
- `python -m mypy apps`: success for 352 source files.
- `python manage.py check`: no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `python -m compileall -q apps` and `git diff --check`: passed.
- SQLite full suite: 646 passed, 29 skipped.
- PostgreSQL affected suite: 97 passed, 3 skipped.
- PostgreSQL full suite: 670 passed, 5 skipped. The two previously blocked
  observability tests now declare the database access required because PostgreSQL
  tenant middleware enters `transaction.atomic()`.

The repository `.venv` points to an unavailable Microsoft Store Python. Verification
used the gitignored `.runtime/py314-part2` environment with the repository's existing
`.[dev]` dependency set; no dependency manifest or lock file changed.

## Checks not run

- Production deployment, live external egress and destructive rollback; none is
  authorized by this task.
- Concurrent multi-process collision stress/load testing. Database uniqueness is the
  race authority and collision handling is covered deterministically.

## Remaining risks

- Legacy integer routes remain intentionally available until a separately approved
  deprecation decision.
- UUIDs reduce accidental key disclosure but must never be treated as authorization.
- A separate browser recording was not produced; the owner accepted closure based on
  the automated Turkish normalization, form, route, and destination evidence.

## Human review required

- Confirm when legacy integer routes may enter a future deprecation cycle.
- Keep project ownership and consumer credential lifecycle assigned to Part 3.

## Final status

Completed, owner-accepted, and verified. No unresolved Part 2 closure item remains.
