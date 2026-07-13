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

## Acceptance criteria mapping

- Scenario page shows hierarchy, aliases, active release summary, document sets, latest version/
  index readiness, consumer scenario bindings and effective retrieval grants.
- Author actions are exposed from the same screen; legacy document-set routes remain present.
- Turkish-first responsive shell and scenario screens are implemented without a dependency.
- The document-set workspace generates metadata, updates a preserved draft candidate, separates
  publish/build/promotion and displays set/index lifecycle state.
- The connector workspace exposes safe Confluence/REST source status, exact-grant creation,
  no-egress REST mapping preview, bounded schedules, run-now and role-gated automation.

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

## Cross-tenant tests

Foreign scenario detail returns 404; foreign document-set binding is rejected; a foreign binding
cannot be removed through another scenario. A consumer must have an active binding to the exact
scenario before the scenario screen can grant document retrieval.

## Logging and redaction tests

No new logs/metrics and no content-bearing log fields added. P9.3 response tests prove connector
hosts, secret references, REST input values and synthetic content are absent from rendered HTML;
task assertions prove queue payloads contain resource/tenant IDs only.

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

- Browser-assisted visual/accessibility smoke was not run; only template rendering and responsive
  CSS inspection are verified.
- Full PostgreSQL suite was not rerun because P9.1 changes only console presentation/querying;
  focused PostgreSQL authorization tests passed.

## Remaining risks

Legacy pages remain partly English until P9.4–P9.5. Configured-vs-release-effective state still
requires operator understanding despite the explanatory notice.
Bulk storage is intentionally per-file, not transactionally atomic across object storage; a
mid-batch storage failure preserves completed files and reports the partial count. Queue dispatch
is at-least-once and the worker's existing-index guard prevents ordinary duplicate builds, but a
broker ambiguity can still require operator status review.
The JSON mapping editor is intentionally schema-oriented rather than a drag-and-drop mapper;
profile/grant creation remains platform-admin command/service work and live connector egress remains
deployment-gated. Full PostgreSQL regression was not rerun; focused connector/RLS coverage passed.

## Human review required

Visual hierarchy, Turkish terminology, configured-vs-effective explanation, keyboard/focus behavior
and narrow-screen UX require browser review.

## Final status

Verified for P9.1–P9.3; overall P9 remains In progress.
