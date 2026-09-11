# Verification: sprint-10-agent-runtime

Sprint 10 delivers the bounded, guarded agent runtime (`apps.agents`) on the verified
Sprints 8–9 workflow, tool-proxy, approval, and telemetry contracts. LangGraph is
integrated only as an `AgentPlanner` adapter (`AGENT_PLANNER`, default deterministic).

## Environment

- Interpreter: `.venv` (Python 3.13), dependencies from `requirements.lock`. One approved
  production dependency added: `langgraph==1.2.9` (exact pin). `pip check` reports no
  broken requirements. `langsmith` is a dormant transitive dep — no API key, no tracing.
- SQLite gates: `DJANGO_SETTINGS_MODULE=config.settings.test` (in-memory, hermetic; the
  deterministic planner runs, no graph/network code).
- PostgreSQL/pgvector gates: `DJANGO_SETTINGS_MODULE=config.settings.local` against the
  Docker Compose `pgvector/pgvector:pg16` database, `pytest --create-db` with
  `MCP_ENABLED=true` / `METRICS_BEARER_TOKEN` set so the Sprint 7 MCP/metrics tests run.
- Windows: a writable `--basetemp` was passed to avoid the shared `pytest-of-*` error.

## Commands and results

| Command | Result |
| --- | --- |
| `ruff format --check .` | Pass — 240 files |
| `ruff check .` | Pass — all checks passed |
| `mypy .` | Pass — no issues in 240 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes detected |
| `python manage.py check` | Pass — no issues (0 silenced) |
| `pytest` (SQLite, `config.settings.test`) | Pass — 337 passed, 2 skipped (PostgreSQL-only) |
| `pytest apps/agents apps/gateway apps/evaluations apps/releases apps/observability apps/console --create-db` (real PostgreSQL/pgvector, MCP+metrics enabled) | Pass — 142 passed |
| `pip check` | Pass — no broken requirements |
| CI lock check (langgraph/langgraph-checkpoint/langchain-core vs `requirements.lock`) | Pass — versions match (1.2.9 / 4.1.1 / 1.4.9) |

New migrations (additive only): `apps/agents/migrations/0001_initial.py` (`AgentVersion`,
`AgentRun` with opaque `public_id` UUID, `AgentRunEvent`, per-consumer idempotency unique
constraint, org/status/created index) and `apps/artifacts/migrations/0003_alter_
artifactversion_type.py` (adds the `agent_definition` choice). Applied cleanly on SQLite
and PostgreSQL via `--create-db`. 62 agent-specific tests in `apps/agents/tests/`.

## Acceptance-criteria evidence

- **Pinned to release/version/context/limits/checkpoint across retry and resume.** The
  compiled agent config (objective/output keys, retrieval flag, ordered tool allowlist,
  cap-clamped limits) is immutable and checksummed; the release pins `agent_checksum`;
  the runtime reads only the pinned config and the durable redacted checkpoint —
  `test_compiler.py`, `test_runtime.py::test_high_risk_tool_pauses_then_resumes`.
- **Cannot call an unbound tool or bypass proxy policy.** Every planner decision is
  re-validated against the compiled tool allowlist and decision-kind allowlist; tool use
  flows only through `request_tool_invocation` / `execute_invocation` —
  `test_runtime.py::test_validate_decision_blocks_unlisted_tool`,
  `test_validate_decision_blocks_unknown_kind`; release closure fails closed when a
  declared tool has no pinned binding — `test_compiler.py::test_release_rejects_tool_not_
  pinned`.
- **Resource limits terminate deterministically with a stable code and no requeue.**
  `test_runtime.py::test_step_cap_fails_closed` (`AGENT_MAX_STEPS`→failed),
  `test_deadline_exceeded_times_out` (`AGENT_TIMED_OUT`→timed_out),
  `test_incompatible_checkpoint_never_resumes` (`AGENT_CHECKPOINT_INCOMPATIBLE`).
- **Crash/redelivery and cancel preserve one valid transition; no double side effect.**
  `test_terminal_run_is_idempotent_on_redelivery`, `test_missing_run_is_safe_noop`,
  `test_cancellation_is_observed_by_the_loop`; the tool step reuses the Sprint 9
  idempotency key (`agent:<run_id>:<step>`) so an approved call is never re-executed.
- **Pause/resume/reject through the approval boundary.** `test_high_risk_tool_pauses_
  then_resumes` (pause→`waiting_approval`, auto-resume path to completion),
  `test_rejected_tool_fails_the_run_closed` (`TOOL_REJECTED`→failed).
- **Final output passes contract + policy; trajectory assertions block promotion.**
  `test_runtime.py::test_policy_requires_citations_fails_closed` (`POLICY_VIOLATION`);
  `test_eval.py` (`agent_completed`, `agent_tool_invoked`, `agent_no_tools`,
  `agent_max_steps` including a budget-exceeded FAILED case).
- **Trace/status/cancel is tenant/action scoped and redacted.** Gateway dual-dispatch and
  cross-tenant isolation — `test_gateway.py::test_status_and_output_after_completion`,
  `test_cross_tenant_run_is_not_found`, `test_cancel_via_delete`,
  `test_agent_invoke_denied_without_capability`; console — `test_console.py`
  (login required, tenant-scoped list, redacted trace with no raw objective, cross-tenant
  403, POST cancel); commands — `test_commands.py` (redacted listing, cross-tenant cancel
  rejected).
- **LangGraph adapter parity + isolation.** `test_langgraph_adapter.py` proves the
  LangGraph planner returns the same decisions as the deterministic planner across the
  transition matrix and that a run completes identically under `AGENT_PLANNER`, while all
  caps and the tool allowlist stay enforced by the runtime regardless of planner.

## Security / privacy notes

- Raw chain-of-thought and raw payloads are never persisted: input is redacted at ingress
  (strings→`[redacted]`), the checkpoint is a redacted working state, and events carry
  only allowlisted decision/outcome labels + checksums. Verified by the "no `hello`
  leaks" assertions in `test_commands.py` and `test_console.py`.
- Model decisions are proposals, never authorization; the runtime is the trust boundary.
- No LangSmith / LangGraph Cloud / hosted service / new public endpoint was added. The
  default `AGENT_PLANNER` is the deterministic planner, so CI/tests run no graph code and
  no outbound call.

## Residual risk / not delivered

- A global start/resume kill switch, the checkpoint retention/purge job (the 30/90-day
  policy is recorded but not automated), and production-like load/soak tests remain
  operational follow-ups.
- No live-server smoke or live-egress test was run; the automated suite uses the
  deterministic model provider and the no-egress tool adapter. A standing local Uvicorn/
  Celery worker (if any) must be restarted and `manage.py migrate` run before serving
  Sprint 10 code against the persistent local database.
- On resume the tool executes with the run's redacted checkpoint state (deterministic
  governance runtime); a durable encrypted short-lived raw-payload design remains
  separately approved future work (consistent with the Sprint 8/9 redaction stance).
