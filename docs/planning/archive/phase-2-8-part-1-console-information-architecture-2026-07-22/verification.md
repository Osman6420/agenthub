# Verification: phase-2-8-part-1-console-information-architecture

## Status

**Verified and owner-accepted — 2026-07-22.** Automated navigation, authorization, compatibility,
full regression and PostgreSQL tenant-boundary checks pass. The owner exercised the authenticated
console iteratively, accepted the final organization/menu journey and requested Part 1 closure.
Separate 390/900/1440 screenshot artifacts were not retained.

## Evidence table

| Area | Planned evidence | Result |
| --- | --- | --- |
| Plan/document structure | Plan, threat model, current-state docs and status links reviewed | Pass — 2026-07-22 |
| Navigation and redirects | `pytest apps/console/tests` | Pass — 155 tests |
| Authorization and tenant isolation | Cross-tenant/disabled-org console tests plus PostgreSQL tenant checks | Pass — PostgreSQL 165 passed, 3 non-applicable skips |
| Unsafe-method compatibility | Legacy GET redirect and POST method regression | Pass — POST is not redirected (405) |
| Accessibility and responsive UX | Tab/table/nav assertions and authenticated owner journey | Pass; separate width screenshots not retained |
| Static/application checks | Ruff format/lint, mypy, Django check, migration drift | Pass after import/typing cleanup |
| Regression | Full SQLite suite | Pass — 987 passed, 38 PostgreSQL-dependent skipped |
| Runtime | Canonical Compose state and `/v1/health/live` | Pass — all roles up, infrastructure healthy, HTTP 200 |
| Final review | Staff engineer, AppSec and SRE diff reviews | Pass — stale filters removed; health results bounded to 200 rows |

## Executed commands

```powershell
docker compose -f deploy/compose/docker-compose.yml exec -T web python -m ruff format --no-cache --check apps config
docker compose -f deploy/compose/docker-compose.yml exec -T web python -m ruff check --no-cache apps config
docker compose -f deploy/compose/docker-compose.yml exec -T -e DJANGO_SETTINGS_MODULE=config.settings.test web python -m mypy --cache-dir=/tmp/agenthub-mypy apps
docker compose -f deploy/compose/docker-compose.yml exec -T -e DJANGO_SETTINGS_MODULE=config.settings.test web python manage.py check
docker compose -f deploy/compose/docker-compose.yml exec -T -e DJANGO_SETTINGS_MODULE=config.settings.test web python manage.py makemigrations --check --dry-run
docker compose -f deploy/compose/docker-compose.yml exec -T -e DJANGO_SETTINGS_MODULE=config.settings.test -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 web python -m pytest -p pytest_django.plugin apps/console/tests -q
docker compose -f deploy/compose/docker-compose.yml exec -T -e DJANGO_SETTINGS_MODULE=config.settings.test -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 web python -m pytest -p pytest_django.plugin -q
```

Results: Ruff format reported 413 files formatted; Ruff lint passed; mypy checked 403 source files
without errors; Django reported no issues; migration drift reported no changes; console tests passed
155/155; full SQLite regression passed 987 tests with 38 PostgreSQL-specific skips; PostgreSQL
console and tenancy checks passed 165 tests with 3 non-applicable opposite-backend skips. The repository's
host virtualenv could not launch in this desktop session, so pytest, Ruff and mypy were run in the
canonical web container. Missing dev tools were installed only into the running container user's
environment; no dependency or lock file changed. Ruff cache was disabled because `/app/.ruff_cache`
is not writable.

Before manual or PostgreSQL verification, follow section 0 of
[`docs/manual-testing-guide.md`](../../../manual-testing-guide.md), inspect the canonical Compose file,
query live Compose state and check `/v1/health/live`. If the host Python launcher is unavailable,
use the documented disposable Python 3.13 container fallback without modifying dependencies.

## Manual acceptance checklist

- [x] 390 px: responsive rules and bounded-table assertions pass; owner accepted closure without a
      retained screenshot artifact.
- [x] 900 px: project → scenario journey and sidebar behavior accepted in the iterative live review.
- [x] 1440 px: information density and line lengths accepted in the iterative live review.
- [x] A page taller than the viewport keeps the sidebar dark, readable and independently usable.
- [x] Keyboard-only journey covers skip link, organization menu, tabs, table rows/actions
      and logout with visible focus.
- [x] Screen-reader names/selected states are meaningful for navigation, tabs, tables and statuses.
- [x] Old list bookmarks reach the intended authorized context; exact detail bookmarks still work
      (automated route evidence).
- [x] Health KPI links open dedicated scoped exact-record lists and the home page renders no
      individual health records (automated link, filtering and deep-link evidence).
- [x] Organization selection uses a JavaScript-independent menu of explicit CSRF-protected POST
      buttons; selection returns to the selected scope's Ana Sayfa rather than an old organization's
      detail URL.

## Unverified assumptions

- No separate screenshot evidence was retained for each target width; closure relies on automated
  responsive/accessibility assertions plus the owner's iterative authenticated live review.

## Residual risks

No schema, role, production dependency, public API, mutation authority, audit contract or persisted
data was changed. Legacy list redirects intentionally change bookmark destinations while retaining
exact detail routes. Health-result lists are deliberately bounded to 200 rows pending later unified
operations pagination.
