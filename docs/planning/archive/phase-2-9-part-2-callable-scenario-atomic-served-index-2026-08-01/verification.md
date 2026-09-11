# Verification: phase-2-9-part-2-callable-scenario-atomic-served-index

## Result

Implemented and verified on 2026-08-01. Scenario callability is now an explicit exact-release-
manager transition, and served-index promotion/rollback owns the document-set version, exact built
index pointer, and index status in one fail-closed transaction.

## Check evidence

| Check | Command/profile | Result | Evidence and notes |
| --- | --- | --- | --- |
| Baseline | `git status --short --branch` | Passed | Clean branch at `1265dcd` before edits |
| Discovery | Codebase Memory, Serena, `rg`, direct inspection | Passed | Healthy persisted graph; public/shared symbols and dynamic routes confirmed from source |
| Syntax | `python -m py_compile` on changed modules | Passed | No syntax failures |
| Django system check | `python manage.py check` | Passed | No issues |
| Migration drift | `python manage.py makemigrations --check --dry-run` | Passed | No changes detected |
| Changed-file lint/format | Ruff check and format check | Passed | All changed Python files conform |
| Target SQLite | Part 2 catalog/console/gateway/ingestion/migration tests | Passed | 22 passed after final lock-order and lineage review |
| Broad SQLite blast radius | Adjacent catalog/console/gateway/documents/ingestion suites | Passed | 64 passed, 20 PostgreSQL-only skips |
| Full SQLite | Full pytest suite | Passed | 1,074 passed, 60 skipped; zero failures |
| Target PostgreSQL/pgvector | Part 2 and adjacent suites | Passed | 55 passed, 1 off-PostgreSQL guard skipped; final promotion suite rerun passed 10/10 including two-thread serialization |
| Full PostgreSQL/pgvector | Full suite, then affected storage files with canonical MinIO env | Passed | Initial run: 1,119 passed, 5 skipped; 3 failures and 7 errors were all missing local MinIO credentials. Exact affected files reran with canonical local MinIO configuration: 17 passed |
| Frontend tests | `npm --prefix frontend test` | Passed | 8 files, 29 tests; one pre-existing React `act(...)` warning |
| Frontend build | `npm --prefix frontend run build` | Passed | TypeScript no-emit and Vite production build succeeded |
| Target mypy | Changed production modules | Baseline-limited | No changed-file error; four imported pre-existing errors remain in `identity/assignment_services.py`, `tenancy/services.py`, and `console/forms.py` |
| Live migrations | Canonical local Compose PostgreSQL | Passed | Documents 0009/0010 and ingestion 0013 applied; preflight found one coherent active pair and no split active indexes |
| Runtime | Recreate web and ingestion worker; `/v1/health/live` | Passed | HTTP 200 after restart; PostgreSQL, Redis, and MinIO healthy |
| Browser allow | Synthetic exact release manager, current build | Passed | Active -> disabled -> active from scenario page; both success notices and truthful state/action rendered |
| Browser deny | Existing exact approver, current build | Passed | Lifecycle action rendered disabled; direct neighboring-role POST test returned 403 |
| Responsive UI | 390, 900, and 1440 px | Passed | Lifecycle card, status, action, navigation, and horizontal compact navigation remained readable without overlap |
| Diff hygiene | `git diff --check` | Passed | No whitespace errors; Windows checkout reports the expected CRLF normalization warning for `console/views.py` |

## Acceptance criteria mapping

- Exact release manager activate/disable and idempotent replay: catalog service, console, gateway,
  PostgreSQL, and live browser evidence passed.
- Readiness: activation requires an active release, active alias, and every exact release index pin
  to already be the coherent served pair.
- Atomic served pointer: promotion/rollback locks one document set, all versions and indexes in a
  deterministic order, supersedes prior active metadata, sets the exact built pointer, and commits
  its success audit in the same transaction.
- Failure/retry: coherent replay is idempotent; invalid state and injected audit failure preserve
  the prior pair; immutable stores remain available for rollback.
- Concurrency: two PostgreSQL threads promoting different versions of one set complete without
  deadlock and leave exactly one coherent served set-version/index pair.
- Data upgrade: the preparation migration deterministically reconciles legacy split metadata before
  additive conditional uniqueness constraints are installed; it deletes no rows or stores.

## Security and authorization evidence

- Scenario lifecycle uses central `scenario.release` authorization against trusted organization,
  project, and exact scenario objects.
- Same-tenant other-scenario routes are non-disclosing 404; neighboring editor/approver roles are
  denied; management-command index promotion requires exact document-set operations authority.
- Console mutations are authenticated POST-only with CSRF. Gateway callability changes only after
  the explicit scenario transition.
- Stable audit events contain identifiers, state names, decision/outcome, reason, and request ID;
  no token, prompt, document byte, provider output, or secret is recorded.

## Migration and rollback evidence

The local PostgreSQL preflight reported one active document-set version, one active index, and no
split pair. All three additive migrations applied successfully. Application web and ingestion
worker roles were recreated and liveness returned 200. Behavioral rollback uses explicit scenario
disable or `rollback_staged_index`; schema rollback removes constraints but intentionally does not
fabricate the ambiguous pre-reconciliation state.

## Staff / AppSec / SRE review

- Staff: release activation remains separate from scenario callability; retrieval retains its
  public contract and now consumes one coherent metadata pointer.
- AppSec: exact-object authorization, CSRF, tenant lineage, non-disclosing routes, and redacted audit
  outcomes are preserved; no grant, secret, endpoint, or egress policy changed.
- SRE: lock order begins at the document-set mutex, partial uniqueness blocks duplicate active rows,
  audit failure rolls back state, prior immutable stores remain rollback targets, and migration
  preflight/runtime health evidence is recorded.

## Unverified assumptions and remaining risks

- The full PostgreSQL suite was not rerun as one monolithic command after adding MinIO credentials;
  the only failing files from the first run were rerun exactly and passed.
- The repository-wide mypy baseline remains nonzero in four unchanged imported locations; Phase 2.9
  Part 7 owns the broader quality-debt closure.
- The local synthetic `qa-p29-manager` record remains as non-production QA evidence but was
  deactivated immediately after the browser run; its sole assignment is exact-scenario release
  manager and it has no platform/organization authority.

## Final status

Verified and completed 2026-08-01. Part 3 is the next active milestone.
