# Verification: Phase 2.8 Part 2 — Organization and access management

> **Status: Verified 2026-07-22.** Automated SQLite/PostgreSQL evidence, migration, static checks
> and authenticated browser inspection passed.

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Mandatory-workspace console regressions | `docker compose -f deploy/compose/docker-compose.yml exec -T -e DJANGO_SETTINGS_MODULE=config.settings.test web python -m pytest apps/console/tests/test_phase_2_8_part_2.py apps/console/tests/test_phase_2_8_part_1.py apps/console/tests/test_console_ux_overhaul.py` | Passed | 41 passed in 14.82s | Deterministic default, stale/revoked state, blank-switch denial, platform admin and Part 1 compatibility |
| Part 2 authorization and lifecycle | `python -m pytest apps/console/tests/test_phase_2_8_part_2.py` in Compose test container | Passed | 12 passed | Organization+initial-admin atomicity, audit rollback, membership lifecycle/last-admin, forged parents, document-manager matrix, deep-link alignment |
| PostgreSQL/RLS affected suite | `python -m pytest --ds=config.settings.local apps/console/tests/test_phase_2_8_part_2.py apps/tenancy/tests/test_isolation.py apps/tenancy/tests/test_rls_readiness.py apps/tenancy/tests/test_tenant_context.py apps/documents/tests apps/ingestion/tests/test_rls.py apps/agents/tests/test_kill_switch_rls.py` | Passed | 74 passed, 3 backend-opposite skips in 30.51s | Real PostgreSQL; tenant/RLS/document boundaries included |
| Full SQLite suite | `docker compose -f deploy/compose/docker-compose.yml exec -T -e DJANGO_SETTINGS_MODULE=config.settings.test web python -m pytest` | Passed | 999 passed, 38 PostgreSQL-only skips in 49.21s | 1037 collected |
| Ruff lint | `python -m ruff check apps config scripts manage.py` | Passed | All checks passed | Main source tree |
| Ruff format | `python -m ruff format --check apps config scripts manage.py` | Passed | 415 files already formatted | Main source tree |
| mypy | `python -m mypy apps config` | Passed | No issues in 414 source files | Application and configuration boundaries |
| Django/migration checks | `manage.py check`; `manage.py makemigrations --check --dry-run`; `docker compose ... run --rm migrate` | Passed | 0 issues; no drift; `tenancy.0003` applied OK | Additive role-choice migration |
| Manual accessibility/browser journey | Authenticated in-app browser against restarted local web | Passed | Mandatory `ahmet` workspace; member page; no parent selectors; skip-link/main focus contract | `document_manager` present, `platform_admin` absent; temporary browser user removed |

## Acceptance and security mapping

Evidence covers deterministic organization selection, platform-only atomic creation, membership
lifecycle and last-admin locking, contextual creates, document-manager least privilege, audit
rollback, CSRF/method enforcement through the full suite, and non-disclosing cross-tenant denial.

## Behavior comparison with base branch

The cross-organization selector option and organization/project form fields are removed. Scenario
creation has a project-context route; the legacy GET entry requires an authorized project UUID.
Canonical detail URLs continue to work and align the workspace only after authorization. Part 1
regressions and the full suite passed.

## Checks not run and remaining risks

Host `.venv` could not start in the non-interactive Windows session (`A specified logon session
does not exist`); the repository-documented Compose Python 3.13 environment was used. The system
Python lacked `opentelemetry` and was not used as evidence. Membership creation requires the exact
username of an existing active directory account and does not enumerate the directory. Directory
search/provisioning remains outside this Part 2 surface. No unresolved correctness or authorization
failure remains.

## Human review required

Deployment owners should review directory discoverability policy and target-browser responsive
appearance. Automated semantics and one authenticated desktop browser journey passed.

## Final status

**Verified.** Part 2 acceptance criteria are met.
