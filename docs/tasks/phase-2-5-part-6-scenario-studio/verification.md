# Verification: phase-2-5-part-6-scenario-studio

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Final diff | `git diff --check` | Passed | Clean on 2026-07-16 | Staff, AppSec and SRE review performed |
| Backend focused | `python -m pytest -p pytest_django.plugin apps/builder/tests apps/console/tests/test_scenario_artifact_console.py` | Passed | 60 passed in 10.94s | No `-q`, no pytest timeout |
| Frontend focused | `npm test -- --run src/__tests__/flow.test.tsx src/__tests__/artifact_draft_editor.test.tsx src/__tests__/app_deeplink.test.tsx src/__tests__/ai_authoring.test.tsx` | Passed | 4 files, 8 tests | Includes dirty-save to publish revision handoff |
| Frontend full | `npm test` | Passed | 6 files, 17 tests in 3.05s | All builder interaction suites included |
| Frontend type/build | `npm run typecheck`; `npm run build` | Passed | TypeScript clean; production bundle rebuilt | Generated Django static bundle updated |
| Python static/schema | `ruff format --check apps`; `ruff check apps`; `python -m mypy apps`; `manage.py check`; `makemigrations --check --dry-run`; `compileall apps config` | Passed | Ruff clean; mypy clean across 356 files; Django, migration drift and compile checks clean | Disposable Python 3.13 fallback used after the Windows venv launcher failed |
| Full SQLite | `python -m pytest -p pytest_django.plugin` | Passed | 682 passed, 29 skipped in 35.64s | No `-q`, no pytest timeout |
| Full PostgreSQL | `python -m pytest -p pytest_django.plugin` | Passed | 706 passed, 5 skipped in 107.05s | PostgreSQL 16/pgvector and Redis Compose services; no `-q`, no pytest timeout |

## Acceptance criteria mapping

Optimistic concurrency covers workflow and artifact draft update/delete plus workflow publish.
Scenario-scoped Studio deep links enforce direct scenario/project/organization lineage. The
scenario page exposes same-organization immutable versions and creates exact candidate manifest
pins through the canonical compiler without publication or promotion.

## Security and authorization mapping

Expected revisions are checked server-side after authorization and under row locks. Stale writes
return stable `stale_revision` with HTTP 409 and neither mutate nor reflect bodies. Author/auditor
and release-manager boundaries passed. Only release managers can compile candidates. Forged foreign
scenario/artifact selections and incompatible reserved roles fail without mutation or disclosure.

## Logging, redaction and audit mapping

Conflict responses contain only stable safe fields. Existing audited mutations passed; stale
requests stop before audit/write. Candidate compilation and its safe-reference audit event share a
transaction, so audit persistence failure rolls back the release.

## Migration verification

`builder.0003_draft_revisions` additively defaults both draft revisions to `1` and adds a nullable
scenario foreign key to workflow drafts. Migration drift and full PostgreSQL verification passed.

## Checks not run

Authenticated Turkish owner browser acceptance was not run; it remains the explicit manual gate.

## Remaining risks

Authenticated visual/wording acceptance and complex real-world author usability remain manual.
Candidate selection is intentionally bounded to the first 200 ordered registry entries; search or
pagination is a future usability enhancement, not a security or correctness gap.

## Human review required

Authenticated Turkish Scenario Studio journey, including two-tab conflict and candidate-versus-
active lifecycle wording.

## Final status

Implemented and automated-verified; authenticated Turkish owner browser review pending.
