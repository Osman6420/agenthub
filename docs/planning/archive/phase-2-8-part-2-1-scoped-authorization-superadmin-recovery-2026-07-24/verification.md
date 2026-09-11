# Verification: Phase 2.8 Part 2.1 — Scoped authorization and superadmin recovery

> Archived with the completed task on 2026-07-24.

## Status

**Verified 2026-07-24.** Slices 1–5 are implemented. Automated authorization, tenant isolation,
Access UI, superadmin audit/alert and runbook checks pass. Live visual browser inspection could not
run because this session exposed no browser backend; automated accessibility and responsive
rendering coverage passed.

## Environment

- Date: 2026-07-23
- Runtime: repository Compose topology; PostgreSQL, Redis, MinIO, web and workers reported running,
  infrastructure health checks were healthy, and `GET /v1/health/live` returned HTTP 200 before
  implementation.
- Python: 3.13.14 in the existing `web` Compose service.
- Django: 5.2.16.
- Host `.venv` launcher was unavailable with the documented Windows
  `A specified logon session does not exist` failure. It was not treated as verification evidence.

## Slice 1 evidence

| Check | Command | Result |
| --- | --- | --- |
| Identity regression and new capability tests | `docker compose -f deploy/compose/docker-compose.yml exec -T web python -m pytest apps/identity/tests` | Pass: 18 tests |
| Ruff | `docker compose ... exec -T -e RUFF_CACHE_DIR=/tmp/ruff-part-2-1-final web python -m ruff check apps/identity/models.py apps/identity/authorization.py apps/identity/tests/test_operator_authorization.py` | Pass |
| Mypy | `docker compose ... exec -T web python -m mypy apps/identity/authorization.py apps/identity/models.py` | Pass: 2 files |
| Migration drift | `docker compose ... exec -T web python manage.py makemigrations --check --dry-run` | Pass: no changes detected |
| Django system check | `docker compose ... exec -T web python manage.py check` | Pass: no issues |
| Patch whitespace | `git diff --check` | Pass |

## Verified behavior

- Exactly one additive Global Administrator record can exist.
- Model validation rejects an inactive user, a Django superuser and a false singleton marker.
- Global Administrator receives administration/release/runtime capabilities but is denied document
  content and normal scenario-to-document-set grant authority.
- Organization Administrator authority is organization-bound and does not imply document content.
- Disabled organizations reject normal administrative/release mutations.
- Django superuser is reported as the explicit `superadmin_recovery` authority source rather than a
  normal Global Administrator.
- Anonymous/inactive identities fail closed with a stable content-free reason.
- Existing endpoint predicates are unchanged in this compatibility slice.

## Slice 2 evidence

| Check | Command | Result |
| --- | --- | --- |
| Identity regression, assignment and PostgreSQL RLS | `docker compose -f deploy/compose/docker-compose.yml exec -T web python -m pytest apps/identity/tests` | Pass: 27 tests |
| Ruff | `docker compose ... exec -T -e RUFF_CACHE_DIR=/tmp/ruff-part-2-1-slice2-final web python -m ruff check apps/identity/models.py apps/identity/authorization.py apps/identity/assignment_services.py apps/identity/tests/test_operator_authorization.py apps/identity/tests/test_delegated_assignments.py apps/identity/tests/test_assignment_rls.py` | Pass |
| Mypy | `docker compose ... exec -T web python -m mypy apps/identity/models.py apps/identity/authorization.py apps/identity/assignment_services.py` | Pass: 3 files |
| Migration drift | `docker compose ... exec -T web python manage.py makemigrations --check --dry-run` | Pass: no changes detected |
| Django system check | `docker compose ... exec -T web python manage.py check` | Pass: no issues |

### Slice 2 verified behavior

- Project Admin, Scenario Editor and Document Set Manager assignments require an active target
  organization member and reject recovery superadmin targets.
- Assignment models revalidate direct target lineage on normal ORM saves and carry a direct,
  non-null organization discriminator.
- All three assignment tables have canonical PostgreSQL `FORCE ROW LEVEL SECURITY`; a non-owner,
  non-bypass role can see only the active tenant scope.
- Global/Organization Admin may assign every delegated responsibility. Project Admin may assign
  and remove Scenario Editors only inside its exact assigned project.
- Forged scenario/project lineage and cross-tenant/ineligible target users fail closed.
- Scenario Editor cannot publish; Document Set Manager content authority is limited to the exact
  assigned set.
- Successful create/remove operations are audited inside their mutation transaction. Required
  audit failure restores the assignment; authorization denials produce durable content-free deny
  events after mutation rollback.
- Migration `identity.0008_delegated_assignments` reverses and reapplies successfully in the
  PostgreSQL test database.

## Slice 3 evidence

| Check | Command | Result |
| --- | --- | --- |
| Documents regression, request/grant and migration/RLS | `docker compose -f deploy/compose/docker-compose.yml exec -T web python -m pytest apps/documents/tests` | Pass: 53 tests |
| Pinning, ACL revocation and orchestration regression | `docker compose ... exec -T web python -m pytest apps/documents/tests/test_pinning.py apps/retrieval/tests/test_acl_retrieval.py apps/orchestration/tests` | Pass: 35 tests |
| Request/grant lifecycle focused | `docker compose ... exec -T web python -m pytest apps/documents/tests/test_scenario_access.py` | Pass: 6 tests |
| Request/grant migration and RLS focused | `docker compose ... exec -T web python -m pytest apps/documents/tests/test_scenario_access_migration.py` | Pass: 3 tests, including non-superuser cross-tenant scope |
| Cached-bundle runtime compatibility | `docker compose ... exec -T web python -m pytest apps/orchestration/tests/test_runtime.py apps/orchestration/tests/test_rag_steps.py` | Pass: 11 tests |
| Ruff | `docker compose ... exec -T -e RUFF_CACHE_DIR=/tmp/ruff-part-2-1-grants-final web python -m ruff check ...` | Pass |
| Mypy | `docker compose ... exec -T web python -m mypy apps/documents/models.py apps/documents/access_services.py apps/documents/services.py apps/retrieval/providers.py apps/orchestration/resolver.py apps/orchestration/runtime.py apps/orchestration/rag_steps.py` | Pass: 7 files |
| Migration drift | `docker compose ... exec -T web python manage.py makemigrations --check --dry-run` | Pass: no changes detected |
| Django system check | `docker compose ... exec -T web python manage.py check` | Pass: no issues |

The first combined test invocation stalled without producing a result and was discarded as
evidence. Docker showed no orphan pytest process; the same groups passed when isolated as recorded
above.

### Slice 3 verified behavior

- Project Admin and Scenario Editor may request a same-organization document set for their exact
  scenario; request purpose is bounded and a request never grants retrieval.
- Only the exact assigned Document Set Manager may approve, reject or revoke access. Global and
  Organization Admin cannot use administrative authority to create or revoke a normal content
  grant.
- Binding through the new authorization service requires both exact scenario edit authority and a
  current live retrieve grant. Binding remains configuration, not authority.
- New release compilation pins only sets having both a binding and live scenario grant.
- Existing immutable release manifests retain their pins, but PostgreSQL ACL retrieval receives the
  trusted release scenario ID and revalidates the live grant on every operation. Revocation returns
  no chunks immediately without deleting the binding or release history.
- Consumer ACL, tenant, pinned version and live scenario grant are intersected before index access.
- Approval audit failure restores the pending request and creates no grant. Unauthorized
  approve/revoke attempts are denied and audited with stable content-free reasons.
- Request and grant tables carry direct organization lineage, canonical PostgreSQL FORCE RLS, and
  verified reversible migration `documents.0006_scenario_document_set_access`.

## Slice 4 evidence

Slice 4 migrates scenario release, exact document-set operations and the last endpoint-level
superuser compatibility decision to the central capability service. The broad
`can_manage_releases` runtime predicate is removed.

| Check | Command | Result |
| --- | --- | --- |
| Release lifecycle and console focus | `docker compose ... exec -T web python -m pytest apps/releases/tests/test_lifecycle.py apps/releases/tests/test_lifecycle_commands.py apps/console/tests/test_release_actions.py apps/console/tests/test_scenario_artifact_console.py` | Pass: 29 |
| Document-set promotion and connector focus | `docker compose ... exec -T web python -m pytest apps/ingestion/tests/test_rest_pull.py apps/console/tests/test_document_workspace_console.py apps/console/tests/test_connector_workspace_console.py` | Pass: 37 |
| Tool authorization focus | `docker compose ... exec -T web python -m pytest apps/tools/tests/test_authz.py apps/tools/tests/test_commands.py apps/console/tests/test_tool_approval_views.py` | Pass: 13 |
| Identity/release/ingestion/tools regression | `docker compose ... exec -T web python -m pytest apps/identity/tests apps/releases/tests apps/ingestion/tests apps/tools/tests` | Pass: 315, skip: 2 expected off-PostgreSQL guards |
| Console regression | `docker compose ... exec -T web python -m pytest apps/console/tests` | Pass: 168 |
| Removed-predicate compatibility focus | `docker compose ... exec -T web python -m pytest apps/console/tests/test_phase_2_5_part_1.py` | Pass: 8 |
| Ruff | `docker compose ... python -m ruff check` over Slice 4 files | Pass |
| Mypy | `docker compose ... python -m mypy` over five changed source modules | Pass |
| Django system check | `docker compose ... python manage.py check` | Pass |
| Migration drift | `docker compose ... python manage.py makemigrations --check --dry-run` | Pass: no changes |
| Patch whitespace | `git diff --check` | Pass |

### Slice 4 verified behavior

- Global Administrator and the owning Organization Administrator receive scenario release
  authority; foreign Organization Administrators, legacy Release Managers, Project
  Administrators, Scenario Editors and unrelated members fail closed.
- Disabled or missing organizations remain denied before the central capability decision.
- Console scenario compile and release lifecycle actions plus release CLI actor resolution share
  the new compatibility facade.
- Existing CLI error codes remain stable during staged migration.
- Exact Document Set Managers, not legacy Release Managers or organization-wide administrators,
  activate staged indexes and approve connector promotion automation.
- Connector workers revalidate that exact Document Set Manager assignment before applying an
  approved promotion; revocation fails closed.
- Tool approval compatibility resolves Global Administrator and recovery superadmin through
  `platform.manage`, with no direct endpoint-level `is_superuser` branch.
- No production caller or definition of the broad `can_manage_releases` predicate remains.

## Slice 5 evidence

Slice 5 connects the audited delegated-assignment services to organization and object Access
surfaces, removes legacy content/release roles from ordinary membership forms, and adds the
exceptional superadmin audit/alert/runbook boundary.

| Check | Command | Result |
| --- | --- | --- |
| Access UI, Part 2 and assignment-service focus | `docker compose ... exec -T web python -m pytest apps/console/tests/test_phase_2_8_part_2_1_access.py apps/console/tests/test_phase_2_8_part_2.py apps/identity/tests/test_delegated_assignments.py` | Pass: 20 |
| Console regression | `docker compose ... exec -T web python -m pytest --reuse-db apps/console/tests` | Pass: 170 |
| Ruff | `docker compose ... python -m ruff check` over the Access UI files | Pass |
| Mypy | `docker compose ... python -m mypy apps/console/forms.py apps/console/views.py` | Pass |
| Django system check | `docker compose ... python manage.py check` | Pass |
| Migration drift | `docker compose ... python manage.py makemigrations --check --dry-run` | Pass: no changes |
| Patch whitespace | `git diff --check` | Pass |
| Browser responsive/accessibility inspection | In-app Browser discovery | Not run: no browser backend is available in this session |
| Access, observability and manifest focus | `docker compose ... python -m pytest apps/console/tests/test_phase_2_8_part_2_1_access.py apps/observability/tests/test_manifests.py apps/observability/tests/test_signals.py --reuse-db` | Pass: 10 |
| Console/identity/ingestion/documents regression | `docker compose ... python -m pytest apps/console/tests apps/identity/tests apps/ingestion/tests/test_confluence.py apps/ingestion/tests/test_rest_pull.py apps/documents/tests --reuse-db` | Pass: 287 |
| Changed production-file Mypy | `docker compose ... python -m mypy apps/identity/superadmin_middleware.py apps/observability/signals.py apps/console/views.py` | Pass |
| Django system check | `docker compose ... python manage.py check` | Pass: no issues |
| Migration drift | `docker compose ... python manage.py makemigrations --check --dry-run` | Pass: no changes |

### Slice 5 verified behavior

- Organization Access lists exact Project Administrator, Scenario Editor and Document Set Manager
  assignments with safe target labels and per-member counts.
- The assignment form offers only active, non-superuser organization members and exact
  same-organization projects, scenarios and document sets.
- Forged cross-tenant target IDs fail form validation before the audited service; every accepted
  create/remove is reauthorized and audited by the existing mutation service.
- Ordinary membership add/change forms no longer offer `release_manager`, `document_manager`,
  `project_owner`, `scenario_editor` or `platform_admin`.
- Project, scenario and document-set details expose tenant-scoped Access sections without foreign
  member leakage and link authorized administrators to the organization Access surface.
- Every authenticated superadmin console route writes a safe pre-action audit event before view
  execution; audit persistence failure stops the request. Superadmin login and activity increment a
  bounded metric consumed by an immediate page-severity Prometheus alert.
- The recovery runbook covers guarded strong-password custody, minimum intervention, evidence
  review, logout/rotation and fail-closed audit/alert handling. Phishing-resistant MFA remains in
  Phase 3 by owner decision.
- Stored legacy role values remain readable for compatibility and existing disposable demo data,
  but ordinary membership forms cannot create them. No destructive local reset was performed.

## Reviews

- Staff engineering: additive model and decision API are small; existing callers remain compatible.
- Application security: deny-by-default decisions, trusted organization input, content exclusions
  and fail-closed superadmin pre-action audit are covered. The superadmin remains intentionally
  powerful; password compromise/phishing is the accepted initial-stage residual risk.
- SRE: the complete local Compose topology is running and healthy; liveness returned HTTP 200.
  Migrations `identity.0007`, `identity.0008` and `documents.0006` are applied locally. No new
  Slice 4 migration is required.

## Checks not run

- Full repository SQLite and PostgreSQL/RLS suites.
- Live browser visual/responsive inspection; no browser backend was available. Automated console
  accessibility tests passed inside the 287-test regression.
- Concurrent request/approve/revoke races and browser accessibility tests.

## Residual risks

- Legacy role values remain in compatibility schemas and disposable-demo seed data until Slice 5;
  no Slice 4 runtime authorization decision consumes `release_manager`.
- `QuerySet.update` and raw SQL can bypass model validation; production mutation paths must use the
  audited assignment service, while RLS remains the tenant backstop rather than a complete lineage
  constraint.
- Superadmin activity is audited and alertable, but operational alert delivery and credential
  custody must still be exercised in each deployment environment.
- Phishing-resistant MFA is an accepted Phase 3 hardening item and is not a Slice 5 completion gate.
