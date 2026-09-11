# Verification: phase-2-6-part-5-child-composition

Environment: Windows host, `.venv` (Python 3.13), Compose PostgreSQL/Redis/MinIO healthy (`docker
compose -f deploy/compose/docker-compose.yml ps`). Composition is disabled by default; the tests set
`WORKFLOW_COMPOSITION_ENABLED=True`.

| Check | Command | Result | Notes |
| --- | --- | --- | --- |
| Ruff format | `ruff format --check apps` | PASS | 372 files already formatted |
| Ruff lint | `ruff check apps` | PASS | All checks passed |
| mypy | `mypy apps` (settings=test) | PASS | no issues in 372 source files |
| Django check | `manage.py check` | PASS | 0 issues |
| Migration drift | `manage.py makemigrations --check --dry-run` | PASS | No changes detected |
| compileall | `python -m compileall apps config` | PASS | — |
| Focused composition (SQLite) | `pytest apps/workflows/tests/test_composition.py` | PASS | 35 passed, 1 skipped (RLS→PG) |
| Full suite (SQLite) | `pytest` (settings=test) | PASS | 822 passed, 31 skipped |
| Composition + RLS (PostgreSQL) | `pytest apps/workflows/tests/test_composition.py --create-db` (settings=local) | PASS | 36 passed incl. FORCE-RLS non-owner |
| Affected apps (PostgreSQL) | `pytest apps/workflows apps/agents apps/releases apps/gateway --create-db` | PASS | 257 passed |
| Celery redelivery/restart smoke | Not run | GAP | Automated redelivery/terminal-guard covered by SQLite/PG tests; real Redis/Celery worker-restart smoke deferred (see Remaining risks) |

## Acceptance criteria mapping

Pending implementation. Every numbered criterion in [plan.md](plan.md) must map to automated or
recorded manual evidence before status becomes `Verified`.

## Security requirement mapping

Pending. Required cases are enumerated in [threat-model.md](threat-model.md).

## Authorization tests

Pending. Tests must independently remove each of the four ADR-0009 authority sources and prove
fail-closed behavior.

## Cross-tenant tests

Pending. Include foreign organization role/release/run/link substitution and PostgreSQL non-owner
FORCE RLS evidence.

## Logging and redaction tests

Pending. Verify that mapped state, tokens, signed contexts, credentials, raw capability/policy
details and provider errors are absent from logs, traces, metrics and audit metadata.

## Audit event tests

Pending. Cover admission accepted/denied, child start/result/failure, cancellation, late result,
budget/cycle denial and required-audit persistence failure.

## Migration verification

Pending. Record live migration-head inspection, selected additive migration number, forward
migration, migration drift, constraints/indexes and tenant RLS provisioning.

## Behavior comparison with base branch

Pending. Existing workflows, agents, release compilation and public invoke/status/cancel behavior
must remain unchanged when composition is absent or disabled.

## Checks not run

All implementation checks are unrun because this task is currently planning-only.

## Remaining risks

- Initial numeric limits and nested-composition policy are not yet fixed.
- Child failure behavior before P2.6.4 is not yet selected.
- Shared transition/dispatch ownership must be reconciled with parallel P2.6.2/P2.6.3 work.
- Production activation remains prohibited until PostgreSQL/Celery and authorization evidence pass.

## Human review required

- Integration owner: compiler/transition seam and migration allocation
- Application security: capability attenuation, execution context and tenant/RLS proof
- SRE: dispatch/reconciliation, cancellation, budgets, rollout and recovery
- Product/architecture owner: initial limits, nesting and child failure behavior

## Acceptance criteria mapping (implemented)

- Criteria 1–2 (compiler pinning): `test_composition.py::test_valid_composition_compiles_when_enabled`,
  `test_subworkflow_config_validation`, `test_agent_call_action_validation`,
  `test_release_pins_exact_child_metadata`, `test_unpinned_child_role_fails_closed`,
  `test_self_cycle_rejected`; disabled-by-default `test_composition_disabled_rejects_nodes`.
- Criterion 3–4 (four-source authority): `test_source1_parent_caps_denied`,
  `test_source4_no_child_binding_denied`, `test_source2_callsite_envelope_gates_capability`,
  `test_source3_child_release_allowlist_excludes_capability`.
- Criterion 5 (fresh context / mapped-only input): `test_admit_creates_separate_child_run_and_link`,
  `test_agent_child_context_carries_max_decisions`, `test_invalid_child_input_denied`.
- Criterion 6 (separate durable runs + immutable link): admit/link tests + FORCE-RLS test.
- Criterion 7 (budgets + cycle guards): `test_max_depth_denied`, `test_cumulative_calls_denied`,
  `test_cycle_via_ancestry_denied`, `test_stale_child_release_denied`.
- Criterion 8 (idempotency/terminal): `test_duplicate_admission_is_idempotent`,
  `test_late_result_cannot_mutate_terminal_parent`, `test_child_completion_schedules_parent_resume`,
  `test_cancellation_propagates_to_pending_child`.
- Criterion 9–10 (untrusted output / safe failure): `test_finalize_invalid_child_output_denied`,
  `test_finalize_child_failure_fails_closed`, `test_finalize_pending_then_success`.
- Criterion 11 (tenant/RLS): `test_child_link_force_rls_blocks_cross_tenant` (PostgreSQL).
- Criterion 12 (S07): `test_end_to_end_parent_runs_both_children` + `fixtures/S07-sequential-composition.json`.
- Compatibility: `test_non_composition_workflow_still_compiles`; full suite unchanged (822 passed).

## Final status

Implemented and Verified (SQLite + PostgreSQL), disabled by default. Real Redis/Celery worker-restart
smoke and P2.6.4 error-route integration remain the recorded gaps before production activation.
