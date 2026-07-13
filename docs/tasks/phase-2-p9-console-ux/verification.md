# Verification: phase-2-p9-console-ux

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Plan/threat model | Manual review | Pass | P9.1 trust boundaries and authorization recorded before code | P9.2+ refined per increment |
| Focused format/lint | `ruff format ...`; `ruff check ...` | Pass | 2 files formatted; checks passed | New Python files/routes |
| Focused SQLite | `pytest test_scenario_relationship_console.py test_document_acl_console.py test_console.py -q` | Pass | 23 passed | UI/authz compatibility |
| Repository format | `ruff format --check .` | Pass | 342 files already formatted | After implementation |
| Repository lint | `ruff check .` | Pass | All checks passed | After implementation |
| Type check | `mypy apps config` | Pass | 341 source files, no issues | Typed model query used |
| Django system check | `manage.py check` | Pass | 0 issues | Test settings |
| Migration drift | `manage.py makemigrations --check --dry-run` | Pass | No changes detected | P9.1 has no schema change |
| Full SQLite suite | `pytest -q --basetemp=.pytest-tmp-p9-20260713` | Pass | 567 passed, 25 skipped | PostgreSQL-only tests skipped as declared |
| Focused PostgreSQL | `pytest test_scenario_relationship_console.py test_document_acl_console.py -q --create-db` | Pass | 12 passed | Local PostgreSQL |
| P9.2 repository format | `ruff format --check .` | Pass | 343 files already formatted | Final P9.2 diff |
| P9.2 repository lint | `ruff check .` | Pass | All checks passed | Final P9.2 diff |
| P9.2 type check | `mypy apps config` | Pass | 342 source files, no issues | Final P9.2 diff |
| P9.2 Django system check | `manage.py check` | Pass | 0 issues | Test settings |
| P9.2 migration drift | `manage.py makemigrations --check --dry-run` | Pass | No changes detected | P9.2 has no schema change |
| P9.2 focused SQLite | `pytest test_document_workspace_console.py test_document_sets_console.py test_scenario_relationship_console.py -q` | Pass | 18 passed | Bulk, draft, tenant/profile and promotion authorization |
| P9.2 full SQLite | `pytest -q --basetemp=.pytest-tmp-p9-2-full-20260713` | Pass | 574 passed, 25 skipped | PostgreSQL-only tests skipped as declared |
| P9.2 focused PostgreSQL | `pytest test_document_workspace_console.py test_document_sets_console.py test_scenario_relationship_console.py -q --create-db` | Pass | 18 passed | Local PostgreSQL |
| P9.3 repository format/lint | `ruff format --check .`; `ruff check .` | Pass | 344 files formatted; all checks passed | Final P9.3 code |
| P9.3 type check | `mypy apps config` | Pass | 343 source files, no issues | Final P9.3 code |
| P9.3 Django/migration | `manage.py check`; `makemigrations --check --dry-run` | Pass | 0 issues; no changes | No schema change |
| P9.3 focused SQLite | `pytest test_connector_workspace_console.py -q` | Pass | 7 passed | Redaction, preview, exact grants, authz, queue and automation |
| P9.3 related SQLite | `pytest test_connector_workspace_console.py test_document_workspace_console.py test_rest_pull.py test_confluence.py -q` | Pass | 45 passed, 2 skipped | RLS cases are PostgreSQL-only |
| P9.3 full SQLite | `pytest -q --basetemp=.pytest-tmp-p9-3-full` | Pass | 581 passed, 25 skipped | PostgreSQL-only tests skipped as declared |
| P9.3 focused PostgreSQL | `pytest test_connector_workspace_console.py test_rest_pull.py test_confluence.py -q --create-db` | Pass | 40 passed | Includes existing REST/Confluence FORCE-RLS tests |
| P9.4 repository format/lint | `ruff format --check .`; `ruff check .` | Pass | 345 files formatted; all checks passed | Final P9.4 code |
| P9.4 type/Django/migration | `mypy apps config`; `manage.py check`; `makemigrations --check --dry-run` | Pass | 344 source files; 0 issues; no changes | No schema change |
| P9.4 related SQLite | `pytest test_scenario_artifact_console.py test_scenario_relationship_console.py test_console.py -q` | Pass | 21 passed | Artifact scope/escaping, manifest bounds and builder deep links |
| P9.4 full SQLite | `pytest -q --basetemp=.pytest-tmp-p9-4-full` | Pass | 585 passed, 25 skipped | PostgreSQL-only tests skipped as declared |
| P9.4 focused PostgreSQL | `pytest test_scenario_artifact_console.py test_scenario_relationship_console.py -q --create-db` | Pass | 10 passed | Tenant scope and relationship compatibility on PostgreSQL |
| P9.4 frontend | `npm --prefix frontend run typecheck`; `npm --prefix frontend test -- --run` | Pass | Typecheck; 12 tests passed | Includes initial organization/draft deep link |
| P9.5 repository gates | `ruff format --check .`; `ruff check .`; `mypy apps config`; Django/migration checks | Pass | 346 files; 345 typed sources; 0 issues; no changes | Presentation-only increment |
| P9.5 focused SQLite | `pytest test_console_accessibility.py test_console.py test_release_actions.py test_tool_approval_views.py test_scenario_artifact_console.py -q` | Pass | 29 passed | Semantic shell, Turkish render and operation compatibility |
| P9.5 full SQLite | `pytest -q --basetemp=.pytest-tmp-p9-5-final` | Pass | 591 passed, 25 skipped | PostgreSQL-only tests skipped as declared |
| P9.5 focused PostgreSQL | `pytest test_console_accessibility.py test_release_actions.py test_tool_approval_views.py apps/agents/tests/test_console.py -q --create-db` | Pass | 19 passed | Render plus release/tool/run compatibility |
| P9.5 frontend | `npm --prefix frontend run typecheck`; `npm --prefix frontend test -- --run`; `npm --prefix frontend run build` | Pass | Typecheck; 12 tests; 202 modules built | Turkish/responsive builder bundle |

## Acceptance criteria mapping

- Scenario page shows hierarchy, aliases, active release summary, document sets, latest version/
  index readiness, consumer scenario bindings and effective retrieval grants.
- Author actions are exposed from the same screen; legacy document-set routes remain present.
- Turkish-first responsive shell and scenario screens are implemented without a dependency.
- The document-set workspace generates metadata, updates a preserved draft candidate, separates
  publish/build/promotion and displays set/index lifecycle state.
- The connector workspace exposes safe Confluence/REST source status, exact-grant creation,
  no-egress REST mapping preview, bounded schedules, run-now and role-gated automation.
- The scenario/artifact workspace resolves exact immutable release pins inside the tenant, renders
  bounded escaped canonical JSON, and opens only server-validated builder organization/draft links.
- The console and builder expose Turkish-first operational wording, keyboard skip/focus treatment,
  named scrollable tables and a stacked narrow-screen builder without changing server contracts.

## Security requirement mapping

- URL/form identifiers are scoped and revalidated server-side.
- POST-only mutations retain CSRF middleware and route through audited domain services.
- Django templates auto-escape stored labels; no unsafe rendering was added.

## Authorization tests

Author happy-path and auditor mutation denial pass on SQLite; focused suite passes on PostgreSQL.
P9.2 additionally verifies author-only upload/build and release-manager-only index promotion on
SQLite and PostgreSQL.
P9.3 verifies author source/run/stage controls, release-manager-only automatic promotion and auditor
denial; exact-set profile grants and bound scenario targets are revalidated server-side.
P9.4 is read-only; artifact IDs and builder query parameters are scoped server-side. Foreign
artifact/draft/organization identifiers return 404 without widening the builder API list scope.
P9.5 changes presentation only; existing release/tool/run authorization suites remain green on
SQLite and PostgreSQL.

## Cross-tenant tests

Foreign scenario detail returns 404; foreign document-set binding is rejected; a foreign binding
cannot be removed through another scenario. A consumer must have an active binding to the exact
scenario before the scenario screen can grant document retrieval.

## Logging and redaction tests

No new logs/metrics and no content-bearing log fields added. P9.3 response tests prove connector
hosts, secret references, REST input values and synthetic content are absent from rendered HTML;
task assertions prove queue payloads contain resource/tenant IDs only.
P9.4 adds no mutation, audit event, logging or metric path; artifact bodies remain response-only,
auto-escaped and omitted from HTML above the configured display bound.

## Audit event tests

Binding create/remove and grant create/remove events asserted in the P9.1 test.
P9.2 asserts per-document upload/upsert audit and staged-build authorization audit; existing index
promotion service retains its audited pointer flip.
P9.3 reuses contract/source/schedule/run audit events and asserts a broker dispatch failure closes
the durable run as `dead_letter` with `rest_sync.dispatch_failed` evidence.

## Migration verification

No migration; `makemigrations --check --dry-run` reports no changes.

## Behavior comparison with base branch

Existing document-set relationship routes remain; P9.1 adds scenario-centred routes and replaces
the scenario list/base shell presentation. Public gateway/MCP contracts are unchanged.

## Checks not run

- Browser-assisted visual/accessibility smoke was not run because the repository has no approved
  browser automation dependency/tool. Template rendering, semantic assertions, responsive CSS
  inspection and frontend build passed.
- Full PostgreSQL suite was not rerun; focused P9.5 operation/render tests and earlier connector/RLS
  suites passed on PostgreSQL.

## Remaining risks

Protocol/domain identifiers remain intentionally English where translation would obscure contracts.
Configured-vs-release-effective state still requires operator understanding despite the explanatory notice.
Bulk storage is intentionally per-file, not transactionally atomic across object storage; a
mid-batch storage failure preserves completed files and reports the partial count. Queue dispatch
is at-least-once and the worker's existing-index guard prevents ordinary duplicate builds, but a
broker ambiguity can still require operator status review.
The JSON mapping editor is intentionally schema-oriented rather than a drag-and-drop mapper;
profile/grant creation remains platform-admin command/service work and live connector egress remains
deployment-gated. Artifact pin discovery is intentionally bounded to the newest 500 scoped releases
and scenario history/project drafts to 20/50 rows; the UI discloses the pin-scan bound. Full
PostgreSQL regression was not rerun; focused connector/RLS and P9.4 tenant coverage passed.

## Human review required

Owner browser acceptance remains required on the served console:

- 390 px: sidebar navigation scroll, tables scroll horizontally, actions wrap, and builder palette/
  canvas/config stack without hiding controls.
- 900 px and 1440 px: hierarchy, line lengths, table density and scenario configured-vs-effective
  explanation remain legible.
- Keyboard-only: the skip link reaches `main`, focus is always visible, forms/buttons/tables are
  reachable in a logical order, and status/error messages are announced by the target screen reader.
- Turkish/domain terminology: translations are understandable to operators while artifact,
  release, consumer, workflow and protocol identifiers remain unambiguous.

## Final status

P9.1–P9.5 implementation and automated verification complete. Final owner browser/operator
acceptance remains open and is the only P9 closeout item.
