# Verification: phase-2-6-part-6-governed-agent-loop

Status: **Verified** (SQLite full suite + PostgreSQL affected-app/non-owner RLS + all static
gates). Real-broker Celery restart smoke was **not** run (documented gap below); task-level
redelivery/idempotency and claim/terminal behavior are covered synchronously through
`execute_agent_run`.

Written against integration head `b8b6ca7` (`feat/foundation-sprint-0-1`).

## Scope implemented

- Decision schema v2 (`AGENT_DECISION_SCHEMA_VERSION = 2`): `AgentDecision(schema_version, kind,
  role, arguments, reason_code)` with `parse_decision` exact-key validation; kinds `retrieve`,
  `tool`, `verify`, `respond`, `escalate`. `apps/agents/planner.py`.
- Additive `spec.actions` policy (`verify_roles`, `repeat_retrieval`, `escalation_enabled`,
  `role_call_caps`) with author-time validation (`apps/agents/agent_schema.py`) and a compiled block
  emitted **only when authored** for checksum stability (`apps/agents/compiler.py`). Release compiler
  rejects a side-effecting/approval-requiring verification role (`apps/releases/compiler.py`).
- Runtime (`apps/agents/runtime.py`): dual argument validation (runtime contract + protected
  namespaces, then the unchanged proxy), `verify` execution over retrieval / no-side-effect tools,
  `escalate` closed platform envelope terminal, per-role budgets, repeated-action checksum guard,
  bounded no-progress termination, and bounded redacted code/count observation summaries.
- DB-backed fail-closed kill switch (`AgentRuntimeControl`, `agents.0003`): global + per-org,
  enforced at Celery task claim/resume (`apps/agents/tasks.py`), role-gated audited
  `suspend_agent_runtime` / `resume_agent_runtime` commands, manual RLS + global-singleton partial
  index. App-role grants updated in `deploy/postgres/provision-app-role.sql`.
- Composition attenuation: `AGENT_CALL_ACTIONS` expanded to include `verify`/`escalate`, `_ACTION_CAPS`
  mapped, and `allowed_actions` carried into the child claim so a pre-P2.6.6 parent denies the new
  kinds by default (`apps/workflows/compiler.py`, `apps/workflows/composition.py`).
- LangGraph adapter parity with schema v2 incl. verify routing (`apps/agents/langgraph_planner.py`).
- `CHECKPOINT_SCHEMA_VERSION` bumped to 2; v1 checkpoints refused by the existing guard.

## Commands and results

All from the repo root in `.venv` (Python 3.13).

### Static gates (host)

| Command | Result |
| --- | --- |
| `ruff format --check apps` | 392 files already formatted |
| `ruff check apps` | All checks passed |
| `mypy apps/agents apps/workflows apps/releases` | Success, no issues |
| `manage.py check` (test settings) | 0 issues |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `python -m compileall apps config` | OK |

### SQLite (`config.settings.test`)

- `pytest apps/agents/tests` → **104 passed** (incl. new `test_governed_loop.py`, 32 cases).
- `pytest` (full suite) → **926 passed, 35 skipped** (skips are the documented
  PostgreSQL-only RLS/pgvector/advisory-lock cases).

### PostgreSQL (`config.settings.local`, Compose pgvector pg16, `--create-db`)

Env: `MCP_ENABLED=true METRICS_BEARER_TOKEN=test-token`, writable `--basetemp`.

- `pytest apps/agents apps/workflows/tests/test_composition.py apps/releases` → **163 passed**
  (includes the composition FORCE-RLS cases skipped on SQLite; the new `agents.0003` migration
  applied cleanly with its manual RLS policy + global-singleton partial index).
- `pytest apps/agents/tests/test_kill_switch_rls.py` → **2 passed** — proves under a
  `NOSUPERUSER NOBYPASSRLS` role that a per-org control row is visible only in its own tenant scope
  while the global (`NULL`-org) row is visible in every scope (the runtime enforcement contract).

## Acceptance criteria mapping

1. Closed versioned schema, fail-closed codes — `test_governed_loop.py` (parse/validate suite). ✔
2. Planner is proposal-only; allowlist/role/argument re-validation — decision-validation + argument
   pre-validation tests; proxy re-validation unchanged (tools suite green). ✔
3. `verify` only over compiled no-side-effect actions; side-effecting rejected at compile —
   `test_side_effecting_verification_role_rejected_at_release_compile`. ✔
4. `escalate` distinct audited terminal, closed envelope, no free text —
   `test_escalate_is_a_distinct_audited_terminal`, `test_escalation_envelope_sanitizes_free_text`. ✔
5. Repeat/budget/global caps enforced; deterministic exhaustion — budget/no-progress tests. ✔
6. Repeated-action denial, approval-resume exempt, no-progress termination — repeat/no-progress
   tests + `test_arguments_survive_approval_resume_with_checksum_binding`. ✔
7. Approval invariants under v2 — existing `test_runtime.py` pause/resume + the arguments-resume
   checksum-binding test. ✔
8. Observation redaction/budget — `test_observations_are_code_count_only`. ✔
9. Kill switch instant, org-scoped, role-gated, state-preserving — kill-switch tests + RLS test. ✔
10. Compatibility — `test_legacy_agent_config_unchanged_without_actions`; full Sprint 10 regression
    green unmodified. ✔
11. S06 journey + denials — covered by the pytest matrix (pytest-only per frozen decision (6)). ✔
12. Gates + reviews — this record; review below. ✔

## Residual risk / gaps

- **Real-broker Celery restart smoke not run.** Consistent with the Sprint 10 note (no live-server
  smoke). The task claim/terminal/idempotency and kill-switch-at-claim/resume paths are exercised
  synchronously through `execute_agent_run`; `acks_late` + `select_for_update` idempotency is unchanged.
- A model-backed planner (deployment-gated) sees bounded code/count observations by design; provider
  egress governance is a deployment decision outside this part (CI keeps the deterministic planner).
- Kill-switch console button is P2.6.11; incident response uses the audited management commands here.

## Reviews (final diff)

- **Staff engineer:** additive-only; legacy compiled agents keep byte-identical configs/checksums;
  new behavior is opt-in per authored `spec.actions`; one additive forward-only migration.
- **AppSec:** every authority decision stays server-side; dual argument validation before the
  unchanged proxy; protected-namespace + size bounds on arguments; observations are code/count only;
  escalation envelope is closed (no free text); kill switch is role-gated (superuser) + audited +
  FORCE-RLS on the control table proven under a non-owner role.
- **SRE:** kill switch is instantly effective without restart, org-isolated, preserves durable state,
  and re-dispatches on resume; bounded no-progress/repeat guards prevent runaway loops; no new
  production dependency or live egress.
