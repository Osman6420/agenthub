# Task Plan: Close the application-role grant inventory for the access/assignment tables

## Status

**Implemented.** The owner reviewed options A and B and chose **B**: `DELETE` is denied on all three
assignment tables and assignment removal is a soft revoke. See "Owner decision" below.

## Problem

`apps/tenancy/tests/test_rls_readiness.py::test_provisioning_sql_names_every_protected_table` is
currently failing on the trunk branch. It compares the model-derived `protected_tenant_tables()`
inventory against `deploy/postgres/provision-app-role.sql` and finds five direct-tenant tables that
were never added to the owner-approved grant inventory:

| Table | Owner app | Introduced by |
| --- | --- | --- |
| `documents_scenariodocumentsetaccessrequest` | `apps/documents` | Phase 2.8 Part 2.1 |
| `documents_scenariodocumentsetgrant` | `apps/documents` | Phase 2.8 Part 2.1 |
| `identity_projectadministratorassignment` | `apps/identity` | Phase 2.8 Part 2.1 |
| `identity_scenarioeditorassignment` | `apps/identity` | Phase 2.8 Part 2.1 |
| `identity_documentsetmanagerassignment` | `apps/identity` | Phase 2.8 Part 2.1 |

The failure predates the Phase 2.8 Part 3 unified-Run work and was found while adding
`workflows_run`, `workflows_runevent` and `workflows_runwait` to the same inventory. It was
deliberately left unfixed there because that task's approval covered only the three unified tables.

## Why this needs its own approval

These are not ordinary state tables. Four of the five carry authorization authority:

- `ScenarioDocumentSetGrant` is the **live scenario retrieve authority** consumed by
  `apps/retrieval/providers.py` during ACL retrieval. A wrong privilege here is a retrieval
  isolation risk, not a bookkeeping bug.
- `ProjectAdministratorAssignment`, `ScenarioEditorAssignment` and `DocumentSetManagerAssignment` are
  read by `apps/identity/authorization.py` to decide operator capability. Excess write privilege on
  these tables is a privilege-escalation surface.

`ScenarioDocumentSetAccessRequest` is a request record that explicitly grants nothing by itself, so
it is the lowest-risk row of the five.

## Impact of leaving it open

The role is deny-by-default, so today the effect is a **fail-closed outage**, not a security hole: in
a non-owner deployment the console access-request/assignment flows and ACL retrieval would raise
`PermissionDenied` at the database. Local and CI runs connect as the superuser owner, which bypasses
RLS and grants, so the gap is invisible outside a real deployment. The red readiness test is the only
signal, and it stays red until this is closed.

## Proposed grants

Derived from the actual code paths, at least privilege. Verified by reading the services rather than
assumed from the model shape:

| Table | Proposed | Justification |
| --- | --- | --- |
| `documents_scenariodocumentsetaccessrequest` | `SELECT, INSERT, UPDATE` | `access_services.py` creates a request and decides it under `select_for_update`; no delete path |
| `documents_scenariodocumentsetgrant` | `SELECT, INSERT, UPDATE` | `update_or_create` on approval; revocation is a **status change** (`status=REVOKED` + `revoked_by`/`revoked_at`), not a row delete, so lineage is retained |
| `identity_projectadministratorassignment` | `SELECT, INSERT, UPDATE` | removal is a soft revoke under option B; no delete path remains |
| `identity_scenarioeditorassignment` | `SELECT, INSERT, UPDATE` | same removal path |
| `identity_documentsetmanagerassignment` | `SELECT, INSERT, UPDATE` | same removal path |

The three `DELETE` grants are the part that genuinely needs owner judgement. Two options:

- **A (proposed):** grant `DELETE` and keep the existing hard-delete removal semantics. Simplest, no
  code change, matches what `assignment_services.remove_*` already does. Cost: the role can erase an
  assignment row, and the only durable record of the removal is the audit event.
- **B:** deny `DELETE` and convert assignment removal to a soft revoke (status + `revoked_by`/
  `revoked_at`), mirroring how `ScenarioDocumentSetGrant` already handles revocation. Stronger
  tamper-evidence and consistent with the document plane, but it is a schema + service change with a
  migration and a query-filter audit across `apps/identity/authorization.py`.

Recommend deciding A vs B explicitly; do not let the grant silently define the semantics.

## Owner decision

**Option B.** No `DELETE` is granted on any of the five tables. Assignment removal became a soft
revoke, so the assignment plane now matches how the document plane already revokes a grant, and the
application role cannot erase the record of who held which authority.

Two consequences that were not obvious from the option statement and shaped the implementation:

- Model validation requires the target to be an active organization member. A `save()`-based revoke
  would therefore have made it **impossible to withdraw a departed user's authority**, so revocation
  uses a queryset `update()` that bypasses model validation deliberately.
- The unique constraint still matches a revoked row, so re-granting after a revoke would have failed
  as `ASSIGNMENT_ALREADY_EXISTS`. `_create_or_reinstate` reuses the revoked row and re-runs model
  validation, which re-proves eligibility at reinstatement rather than trusting the old row.

## Acceptance criteria

- [x] Owner records a decision on option A or B for the three assignment tables — **B**.
- [x] `provision-app-role.sql` names all five tables at the approved privilege level, in the existing
      grouped-by-intent structure with a comment stating why each level was chosen.
- [x] `test_provisioning_sql_names_every_protected_table` passes, i.e. the inventory has **no**
      remaining gap — not just these five.
- [x] A PostgreSQL test proves the grants are sufficient and bounded, following the pattern of
      `test_unified_run_grants_make_a_non_owner_role_rls_ready_without_delete`: a
      `NOSUPERUSER NOBYPASSRLS` probe role granted exactly the inventory privileges reports
      `inspect_rls_readiness(...).ready is True` with no issues, and `has_table_privilege(..., 'DELETE')`
      is false for every table where `DELETE` was denied —
      `test_access_authority_grants_make_a_non_owner_role_rls_ready_without_delete`.
- [x] Option B: additive migration `identity.0009_delegated_assignment_revocation`, `authorization.py`
      filters that exclude revoked assignments, and tests proving a revoked assignment denies the
      capability, that revocation survives the target leaving the organization, and that reinstatement
      re-proves eligibility.
- [x] `docs/operations/phase-2-app-role-rollout.md` reflects the new grants so an operator rolling out
      the role does not reproduce the gap.

## Verification plan

- `pytest apps/tenancy/tests/test_rls_readiness.py` on SQLite and PostgreSQL.
- `pytest --ds=config.settings.local apps/identity/tests apps/documents/tests apps/retrieval/tests
  apps/console/tests` for the affected authorization and retrieval paths.
- The non-owner probe-role test above.
- Repository gates: `ruff format --check .`, `ruff check .`, `mypy apps config`,
  `manage.py makemigrations --check --dry-run`, `manage.py check`.

## Risks

- **Over-granting.** `DELETE` on an authorization table lets a compromised application role erase
  evidence of who held authority. Option B removes this at the cost of a migration.
- **Under-granting.** A missing privilege fails closed at runtime in production only, since CI runs as
  the owner. The probe-role test is the control that catches this before rollout.
- **Drift recurrence.** The readiness test already guards the inventory; it was allowed to stay red,
  which is what let this accumulate. Consider making the gate blocking in CI as a follow-up so the
  next new tenant table cannot merge without its grant.

## Out of scope

- Any change to the RLS policies themselves; all five tables already carry FORCE RLS and the canonical
  `tenant_isolation` policy.
- The unified `workflows_run`/`workflows_runevent`/`workflows_runwait` grants, which are already
  landed and verified in `phase-2-8-part-3-unified-workflow-engine/verification.md`.
