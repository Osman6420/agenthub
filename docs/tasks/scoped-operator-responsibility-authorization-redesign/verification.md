# Verification — scoped operator responsibility authorization redesign

Date: 2026-07-31

Status: implementation evidence recorded; task remains open because the repository-wide legacy
role-era test suite has not yet been rewritten.

## Implemented and verified

- Organization membership is roleless and lifecycle-only.
- Platform, organization, project, scenario and document-set responsibilities are typed,
  lifecycle-aware and centrally evaluated.
- Organization/global administrators do not implicitly edit, approve, release, operate runtime or
  read protected document content.
- Project administrators may create scenarios and delegate only scenario viewer/editor
  responsibilities.
- Tool and workflow human decisions require exact scenario approval authority.
- Tool approval actors use typed user foreign keys; consumer subjects are not compared with human
  usernames.
- Builder draft content is visible only with exact scenario visibility and mutable only with exact
  scenario editor authority.
- User addition is roleless and uses an organization-admin-only eligible-user dropdown.
- New tenant responsibility tables have FORCE RLS and app-role provisioning coverage.
- The resolved local demo database was flushed, migrated and reseeded after live Compose target
  review. The running web health endpoint returned HTTP 200.

## Verification evidence

- `ruff format` completed for affected Python sources.
- `ruff check apps/builder apps/console apps/tenancy apps/identity apps/tools apps/releases
  apps/documents apps/evaluations apps/agents apps/workflows`: passed.
- `python manage.py check`: passed.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- Focused SQLite authorization/approval/console/RLS run: 30 passed, 5 PostgreSQL-only skips.
- Builder exact-scenario authorization run: 2 passed.
- Workflow human-task exact-approver run: 2 passed.
- Clean PostgreSQL migration and focused authorization/RLS/Builder/tool/workflow run: 23 passed,
  2 tests intentionally skipped because they assert the non-PostgreSQL branch.
- Local PostgreSQL migrations applied through Builder `0005`, Identity `0012`, Tools `0006`,
  Tenancy `0004` and Workflows `0018`.
- Local `GET /v1/health/live`: HTTP 200, `{"status":"ok"}`.
- Runtime-source scan found no legacy membership role, delegated assignment class,
  `approver_roles`, workflow `allowed_roles`, workflow `allowed_decision_roles` or
  `self_approval_allowed` authorization path.

## Checks not complete

- Repository-wide test collection finds 988 tests but stops on 14 legacy test modules importing
  deleted role/delegated-assignment symbols. Thirty-eight test files still contain role-era setup
  and require semantic replacement with typed responsibilities; compatibility aliases were not
  added because they would preserve the authorization model being removed.
- Full unit/integration suite was therefore not run to completion.
- Mypy/type-check, browser accessibility/responsive journeys, frontend build/tests, secret scan and
  worker/CLI exhaustive regression were not rerun after the final workflow/Builder tightening.

## Residual risk

- Unmigrated legacy tests can conceal regressions in older console, document, ingestion, release,
  agent and workflow paths even though focused new-model tests pass.
- Artifact drafts created before the clean cutover may have a null scenario and are deliberately
  inaccessible as protected content. The authorized demo reset removed such rows; production
  in-place migration is out of scope.
