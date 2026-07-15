# Verification: phase-2-5-part-1-workspace-navigation

> Status: Implemented and offline-verified on 2026-07-14. PostgreSQL non-owner execution and the
> Turkish manual browser journey remain required before this part is fully verified and closed.

## Environment

- Workspace: `C:\Users\kuzuc\Desktop\agenthub`
- Runtime used for successful Python checks: global Python 3.14 with the global site-packages path
  before `.venv\Lib\site-packages`, pytest plugin autoload disabled and
  `pytest_django.plugin` loaded explicitly.
- The repository virtual environment is not directly executable: its `pyvenv.cfg` points to an
  unavailable Microsoft Store Python 3.13 installation.
- No PostgreSQL service or `pg_isready` executable was available. No production or live external
  system was accessed.

## Automated evidence

| Check | Command | Result | Notes |
| --- | --- | --- | --- |
| Focused console and tenancy tests | `python -m pytest -p pytest_django.plugin apps/console apps/tenancy -p no:cacheprovider` with `DJANGO_SETTINGS_MODULE=config.settings.test` and plugin autoload disabled | **90 passed, 4 skipped** | Skips require PostgreSQL; includes new Part 1 tests and existing route/mutation coverage |
| New Part 1 + relationship regression | `python -m pytest -p pytest_django.plugin apps/console/tests/test_phase_2_5_part_1.py apps/console/tests/test_scenario_relationship_console.py -p no:cacheprovider` | **14 passed** | Dashboard, disabled tenant, foreign target, links and context installation |
| Ruff format | `.venv\Scripts\ruff.exe format --check apps\console apps\tenancy` | **Passed, 35 files** | Configuration unchanged |
| Ruff lint | `.venv\Scripts\ruff.exe check apps\console apps\tenancy` | **Passed** | Configuration unchanged |
| Mypy | `python -m mypy apps\console apps\tenancy` with the runtime workaround above | **Passed, 35 files** | No type errors |
| Django templates | Parse all 21 console templates with the configured Django template engine and static tag library | **Passed, 21 templates** | Includes the four new detail templates |
| Python compilation | `python -m compileall apps\console apps\tenancy` | **Passed** | No syntax failures |
| Django system check | `python manage.py check` with test settings/runtime workaround | **Passed** | `System check identified no issues` |
| Migration drift | `python manage.py makemigrations --check --dry-run` with test settings/runtime workaround | **Passed** | `No changes detected`; Part 1 adds no migration |
| Full suite, initial collection | Repository pytest command with the runtime workaround | **Blocked by environment** | Python 3.14 attempted to load CPython 3.13 `pydantic_core` and `lxml` binaries in two modules |
| Broad suite excluding the two collection-blocked modules | Same pytest command with those two modules ignored | **625 passed, 29 skipped, 1 environment failure** | Remaining OCR failure is the same CPython 3.13 `cryptography/_cffi_backend` ABI mismatch |
| PostgreSQL non-owner suite | Not run | **Pending** | Mandatory acceptance evidence; SQLite cannot prove FORCE RLS behavior |
| Turkish browser journey | Not run | **Pending owner review** | Responsive and assistive-technology acceptance remains waived |

## Acceptance criteria mapping

1. Dashboard organization inventory and active/passive state: covered by
   `test_dashboard_lists_authorized_active_and_disabled_organizations`.
2. Authorized disabled read plus direct mutation denial: covered by
   `test_disabled_organization_is_readable_but_rejects_direct_mutation` and
   `test_platform_admin_cannot_mutate_disabled_organization`.
3. Platform-admin access remains explicit in the dashboard and organization detail presentation;
   automated access behavior is covered, while owner visual acceptance remains pending.
4. Trusted target resolution and singleton context installation: covered by
   `test_organization_and_target_details_install_single_tenant_context` and foreign-target tests.
5. PostgreSQL transaction-local singleton/reset behavior: **pending PostgreSQL non-owner run**.
6. Organization inventories and organization/project/scenario/document-set/client navigation:
   covered by organization inventory and relationship-link tests; manual Turkish journey pending.
7. Exact artifact/release navigation: covered by the release/artifact assertions in
   `test_scenario_document_set_consumer_and_release_pages_cross_link`.
8. Cross-tenant targets and labels: foreign project, client application and release return 404;
   dashboard and overview HTML exclude the foreign organization fixture.
9. Existing scenario URL remains canonical: asserted without redirect by
   `test_detail_pages_are_cross_tenant_safe_and_keep_canonical_urls`.
   Existing focused console tests cover unchanged POST endpoints, authorization and CSRF behavior.
10. Turkish terminology is implemented in navigation/templates; owner manual review is pending.
11. The artifact/DSL guide now separates Current, Part 1, Later Phase 2.5 and Phase 3 contracts and
    links its code authorities. Automated link/fence validation remains included in final diff checks.
12. Confirmed by diff and migration check: no schema, credential, gateway API or live-call change.

## Security and authorization evidence

- Organization slugs and object IDs resolve only through membership/platform-admin scoped
  querysets. Missing and foreign targets use `Http404`; tests assert no foreign organization name
  appears in returned HTML.
- The trusted organization ID is installed into transaction-local tenant context immediately after
  organization or target resolution, before relationship queries.
- Disabled organizations remain readable but `can_admin_org`, `can_author_scenarios`,
  `can_manage_releases`, approval decisions, invocation cancellation and agent cancellation all
  deny operational mutations, including platform-admin requests.
- Creation forms omit disabled organizations and disabled-organization project/scenario/client
  choices. Client token plaintext is never loaded or rendered; the detail page exposes stored safe
  metadata only.
- Existing business/security audit services and unsafe-method route shapes were not replaced.
  Navigation GETs intentionally add no business audit event.

## Staff-engineer, AppSec and SRE review

- **Staff engineer:** existing canonical domain routes remain unchanged; the organization overview
  and missing project/client/release details are additive. Relationship lists have explicit bounds.
  A duplicate unreachable `return` found during final review was removed.
- **AppSec:** server-derived tenant lineage, foreign-target 404 behavior and disabled-tenant
  fail-closed writes are covered offline. No secret or content body was added to templates/logs.
  Residual blocker: run the same flows under the dedicated PostgreSQL non-owner role.
- **SRE:** no migration, dependency, external call or production configuration change. Overview
  inventories are capped at 100 rows and runs at 50; project rows at 200; client relationships and
  grants are batch-loaded to avoid per-row queries. Representative query-count budgets and live
  route/error metrics have not yet been measured.

## Behavior comparison and rollback

- `/console/` remains the dashboard.
- Existing domain list/detail/action URLs remain canonical; no GET or unsafe-method redirect was
  introduced.
- New routes are limited to the organization overview and previously missing project,
  client-application and release detail pages.
- Rollback is application-only: revert the views, routes, templates, authorization guard and docs.
  No data rollback is required.

## Checks not completed

- PostgreSQL non-owner singleton scope, empty/wrong scope denial and transaction reset.
- Manual Turkish forward/reverse journey and visibly privileged platform-admin review.
- Representative organization-overview query-count budget.
- A completely green full repository suite on the current machine; the installed binary wheels are
  for Python 3.13 while the available interpreter is Python 3.14.

## Remaining risks

- SQLite/fake-context tests prove call placement but not PostgreSQL FORCE RLS enforcement.
- Large authorized organizations are intentionally truncated; pagination is deferred and the UI
  shows the bound.
- Organization slugs and integer object locators remain visible to authorized users by design;
  Part 2 introduces generated identifiers, while authorization continues to ignore locator value.
- Manual Turkish wording and navigation coherence may still require presentation-only adjustments.

## Human review required

- Run focused console/tenancy tests against PostgreSQL using the dedicated non-owner application
  role and record singleton/reset evidence.
- Review dashboard -> organization -> project -> scenario -> document set -> client application and
  reverse navigation, plus artifact/release inspection.
- Confirm disabled organization read-only presentation and platform-admin privileged context.

## Final status

Implemented and offline-verified; not fully verified or closed until PostgreSQL and owner browser
acceptance evidence is recorded.
