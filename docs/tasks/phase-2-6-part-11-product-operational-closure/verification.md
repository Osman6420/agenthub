# Verification: phase-2-6-part-11-product-operational-closure

Integration head: `feat/foundation-sprint-0-1`. Environment: Windows 11, Python 3.13 `.venv`,
Node v20 / npm 10, Compose PostgreSQL(pgvector)/Redis/MinIO up and healthy.

## Status by increment

| Increment | Scope | State |
| --- | --- | --- |
| Step 1 | Remainder inventory + matrix | Verified (recorded in [plan.md](plan.md)) |
| Step 2 | Freeze names/windows (owner input) | Verified |
| A | Studio node exposure + frontend authoring + redacted trace view | Verified |
| B | Eval assertion vocabulary + evidence metadata | Verified (async workflow-structure exercise routed back) |
| C | Metrics + alert rules + runbook | Verified |
| D | Retention/purge (report-mode, 90-day) + console UI + beat | Verified |
| E | S01–S07 GitOps pack + demo-seed reset | Partial — **owner-review gated** (see below) |
| F | PostgreSQL profile + recovery drills + live infra + browser journey + sign-off | Partial — **environment/owner gated** (see below) |

## Commands and results

### Static gates (repo-wide)
- `ruff format --check apps` → 400 files already formatted.
- `ruff check apps` → All checks passed.
- `mypy apps` → Success, no issues in 400 source files.
- `python manage.py check` → no issues.
- `python manage.py makemigrations --check --dry-run` → No changes detected (no migrations added).

### Full SQLite suite (`config.settings.test`)
- `pytest` → **940 passed, 37 skipped** (37 = PostgreSQL-only tests). Includes the 14 new
  P2.6.11 tests. One pre-existing exact-metadata assertion
  (`test_candidate_workflow_uses_isolated_eval_seam`) was updated for the additive candidate
  metadata contract.

### PostgreSQL profile (`config.settings.local`, `--create-db`, Compose PostgreSQL)
- Affected apps `observability + evaluations + builder + console(trace)` → **93 passed**.
- Runtime apps `workflows + agents` (incl. FORCE-RLS composition/recovery) → **290 passed**.

### Frontend gates (Node v20)
- `tsc --noEmit` → clean.
- `vitest run` → **24 passed** (7 files; 13 new/updated in `dsl.test.ts`,
  `node_config_panel.test.tsx`).
- `vite build` → built to `apps/builder/static/builder/`.

## New tests (14)
- `apps/builder/tests/test_api.py::test_node_schema_exposes_all_verified_node_families`
- `apps/console/tests/test_workflow_trace_console.py` (3: authorized redacted trace,
  cross-tenant denial, tenant-scoped list — redaction asserted with a `SECRET` payload marker)
- `apps/evaluations/tests/test_workflow_assertions.py` (2: workflow-structure + agent
  trajectory assertions)
- `apps/artifacts/tests/test_eval_suite.py` (3: allowlist accept + value/count rejects)
- `apps/observability/tests/test_p2611_orchestration_metrics.py` (2: bounded counters + alert
  syntax)
- `apps/observability/tests/test_p2611_retention.py` (3: report vs commit, in-window
  protection, audit preservation + idempotency, platform-admin gating)
- `apps/workflows/tests/test_runtime.py` updated (candidate metadata contract)

## Security / redaction evidence
- Workflow trace view renders only codes/checksums/counts/timestamps; a `SECRET` seeded into
  `input_state`/`result_state`/`merged_state`/`redacted_payload`/`execution_context` is asserted
  **absent** from the response. Cross-tenant detail → 403; list is membership-scoped.
- Retention audit `after` payload asserted free of the bulky-state marker; rows and lineage
  retained, only named columns cleared; report mode mutates nothing.
- Metric labels restricted to `kind/mode/outcome/phase/failure_class` with an `other` fallback;
  no tenant/run/artifact identifiers in labels.
- Retention purge is platform-admin gated (console + `--commit`), fail-closed (audit shares the
  batch transaction), idempotent.

## Route-back (owning parts, not patched here)
- Eval candidate seam `run_workflow_candidate` cannot execute async parallel/wait workflows
  (`WorkflowParallelPending`), so branch/join/wait/retry/compensation assertions are delivered
  as vocabulary + logic + metadata contract + unit tests, but their end-to-end candidate
  exercise over async S0x trajectories depends on P2.6.2–P2.6.5 adding async candidate
  execution. Agent trajectory assertions run fully today.

## Environment/owner-gated remainder (E/F)
- **E — GitOps S01–S07 pack publish:** the threat-model requires published GitOps examples to
  be compiler-validated synthetic fixtures **after owner review**; the S0x design fixtures
  exist under `docs/tasks/phase-2-6-contract-and-scenario-foundation/fixtures/`. Publishing the
  reviewed pack and running the approved demo-seed reset are owner-gated actions, not performed
  autonomously.
- **F — recovery drills / live Grafana-Prometheus-OpenShift / Turkish browser journey / owner
  sign-off:** real-broker Celery recovery drills, live monitoring verification and the recorded
  browser journey require the running worker/monitoring stack and a human owner; recorded as
  operational follow-ups. Compose infra services (PostgreSQL/Redis/MinIO) are up; live
  Grafana/Prometheus and OpenShift are not deployed in this environment.

## Residual risks
- Async workflow-structure eval evidence unproven end-to-end (route-back above).
- Live monitoring/alert behavior unverified until the monitoring stack runs.
- Acceptance pack not yet published (owner-review gate) — no stale-grammar sweep performed.
