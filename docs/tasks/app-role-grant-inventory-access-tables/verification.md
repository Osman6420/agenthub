# Verification: application-role grant inventory for the access/assignment tables

Owner decision: **option B** — no `DELETE` on any of the five tables; delegated assignment removal is
a soft revoke. See [`plan.md`](plan.md).

## What changed

| Area | Change |
| --- | --- |
| Schema | `identity.0009_delegated_assignment_revocation` adds `status`, `revoked_by`, `revoked_at` and a revocation-completeness `CheckConstraint` to the three assignment models. Additive only. |
| Authorization | `apps/identity/authorization.py` filters all three assignment lookups on `status=ACTIVE`, so a revoked row carries no authority. |
| Services | `remove_delegated_assignment` revokes instead of deleting; `_create_or_reinstate` reuses a revoked row on re-grant and re-runs model validation. |
| Console | The members page, the three object-detail views and the remove view all scope to active assignments; removing an already-revoked assignment is a clean 404. |
| Provisioning | All five tables added to `deploy/postgres/provision-app-role.sql` at `SELECT, INSERT, UPDATE`. No `DELETE`. |
| Operations | `docs/operations/phase-2-app-role-rollout.md` states why `DELETE` is withheld and that a missing privilege must be diagnosed, not granted around. |

## Two non-obvious constraints that shaped the implementation

- Model validation requires the target to be an active organization member, so a `save()`-based
  revoke would have made it **impossible to withdraw a departed user's authority**. Revocation uses a
  queryset `update()` deliberately. Proved by
  `test_authority_stays_revocable_after_the_target_leaves_the_organization`.
- The unique constraint still matches a revoked row, so a naive re-grant would have failed as
  `ASSIGNMENT_ALREADY_EXISTS`. `_create_or_reinstate` reuses the row and re-proves eligibility. Proved
  by `test_reinstating_a_revoked_assignment_reuses_the_row_and_reproves_eligibility` and
  `test_reinstatement_is_refused_after_the_target_leaves_the_organization`.

## Tests added

| Test | Proves |
| --- | --- |
| `identity…::test_revoked_assignment_row_survives_but_grants_no_capability` | The row is retained for lineage and `authorize()` denies with `CAPABILITY_NOT_GRANTED`. |
| `identity…::test_removing_an_already_revoked_assignment_is_denied` | Second removal is `ASSIGNMENT_NOT_FOUND` and audited as a denial. |
| `identity…::test_authority_stays_revocable_after_the_target_leaves_the_organization` | Revocation is not blocked by membership validation. |
| `identity…::test_reinstating_a_revoked_assignment_reuses_the_row_and_reproves_eligibility` | Re-grant reuses the row; a second grant while active is still rejected. |
| `identity…::test_reinstatement_is_refused_after_the_target_leaves_the_organization` | Reinstatement re-proves eligibility instead of trusting the old row. |
| `console…::test_access_page_hides_a_revoked_assignment_and_refuses_to_remove_it_twice` | Operator surface shows active assignments only; double removal is a 404. |
| `tenancy…::test_access_authority_tables_are_provisioned_without_delete` | All five are in the inventory and named in no `DELETE` grant. |
| `tenancy…::test_access_authority_grants_make_a_non_owner_role_rls_ready_without_delete` | A `NOSUPERUSER NOBYPASSRLS` probe role with exactly these grants is RLS-ready with no issues, and `has_table_privilege(…, 'DELETE')` is false for all five. |

The existing audit-failure-restores test now asserts the row returns to `ACTIVE` with a null
`revoked_by`/`revoked_at` rather than merely still existing, so a partial revoke would fail the test.

## Incidental defects found and fixed

- **Stale migration targets dropped other apps' tables.** Four migration tests
  (`identity`, `documents`, `console`, `catalog`) reversed one app to a pinned target and never
  migrated forward again. Reversing one app cascades to whatever depends on it, so `workflows_run` and
  its siblings were silently dropped for the rest of a PostgreSQL session — this only surfaced once
  those files were run in the same invocation as the workflows tests. Each now restores every leaf
  migration in an autouse fixture.
- **`DELETE` in a comment read as a grant.** The `delete_grants` assertions split the SQL on `;`
  without stripping comments, so a rationale mentioning `DELETE` would have failed the check. Both the
  new and the existing unified-run assertion now strip comment lines first.
- **A concurrency test lacked its PostgreSQL marker.**
  `test_concurrent_background_delivery_has_one_claim_owner` needs real row locking; on SQLite it
  raised `database table is locked`. It now carries the same `skipif` every sibling concurrency test in
  the file already had. PostgreSQL coverage is unchanged.

## Commands run

| Command | Result |
| --- | --- |
| `ruff format --check .` | 438 files already formatted |
| `ruff check .` | All checks passed |
| `mypy apps config` | 13 errors — identical to the pre-existing baseline, none in changed code |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `pytest` (SQLite, `config.settings.test`) | **1071 passed, 53 skipped, 0 failed, 0 errors** |
| `pytest --ds=config.settings.local --create-db apps/tenancy apps/identity apps/documents apps/console apps/catalog apps/retrieval apps/workflows/tests/test_unified_run.py` | **332 passed, 3 skipped** |

The SQLite baseline before this task was 1062 passed / 51 skipped / **1 failed** / **2 errors**. The
failure was `test_provisioning_sql_names_every_protected_table`, which this task closes; the suite is
now fully green.

## Residual risk

- The grants are proved against a probe role in a test database. A real deployment still needs the
  rollout procedure in `docs/operations/phase-2-app-role-rollout.md` executed and observed.
- Revoked rows accumulate with no retention policy. They are small and carry no payload, but if the
  assignment tables ever grow materially this should join the existing retention job.
- The readiness gate is a test, not a blocking CI job. The plan's "drift recurrence" risk stands: a new
  tenant table can still merge with a red gate unless that is made blocking.
