# P2.6.11 owner-run acceptance steps (increments E & F)

Increments A–D are implemented and verified (see [verification.md](verification.md)). The steps
below are **owner/operator actions** that close increments E and F to reach `Completed`. They
require a running worker/monitoring stack, owner review, and a human sign-off, so they are not
performed autonomously. Run from the repo root in the project virtualenv unless noted.

Prerequisites (already true in the current dev box): Compose PostgreSQL/pgvector, Redis and
MinIO up and healthy. Verify:

```powershell
docker compose -f deploy/compose/docker-compose.yml ps
```

---

## E — Enterprise acceptance pack (S01–S07) + demo-seed reset

**E1. Review the scenario fixtures as synthetic (owner).**
Confirm every S0x fixture under
`docs/tasks/phase-2-6-contract-and-scenario-foundation/fixtures/workflows/` and the
`scenario-corpus.md` contain only synthetic data (no real tenant, endpoint, credential or PII).
The threat model requires published GitOps examples to be compiler-validated **synthetic
fixtures after owner review** — this review is the gate.

**E2. Build executable artifacts + eval suites and run the gates (non-production).**
For each accepted scenario, author the input/output contracts, workflow/agent definition,
policy and `eval_suite` as artifacts, then:

```powershell
.venv\Scripts\python.exe manage.py validate_artifacts
.venv\Scripts\python.exe manage.py compile_release ...      # per scenario
.venv\Scripts\python.exe manage.py run_eval ...             # candidate isolation
.venv\Scripts\python.exe manage.py promote_release ...      # fail-closed on a passing eval
```

Note (route-back): scenarios that use async parallel/for_each/wait structures cannot be
exercised by the isolated eval candidate seam yet (see the B route-back in the plan); their
branch/join/wait/retry/compensation assertions will not pass end-to-end until P2.6.2–P2.6.5 add
async candidate execution. Use the deterministic RAG/linear-workflow/agent scenarios for the
gate-passing pack and record the async ones as pending.

**E3. Publish the reviewed GitOps JSON (owner).**
Only after E1/E2 pass, export/commit the compiler-validated pack under `gitops/` (mirror
`gitops/mcm/`). Run a secret/PII scan over the added files before committing.

**E4. Approved demo-seed reset + repopulation (destructive — confirm target DB first).**
This resets the named non-production demo tenant only. Confirm the database name, then:

```powershell
# reset per the P2.6.0 reset procedure, then:
.venv\Scripts\python.exe manage.py seed_demo
```

Verify no stale-grammar artifact or compiled release remains (search the demo tenant’s
artifacts/releases for the pre-P2.6 grammar).

---

## F — Final acceptance (drills, live infra, browser journey, sign-off)

**F1. Bring up the application tier.**
Follow section 0 of [`docs/manual-testing-guide.md`](../../manual-testing-guide.md). Start web +
Celery worker (`queue=runtime,ingestion`) + beat. Confirm readiness (migration state) and that
the report-only retention beat (`report-retention-backlog`, daily) is scheduled.

**F2. Celery/PostgreSQL recovery drills (record evidence).**
- **Worker restart mid-run:** start a workflow/agent run, kill the worker mid-execution, restart,
  confirm the run resumes with no duplicate side effects (idempotent tool/child execution).
- **Duplicate delivery:** redeliver a task message; confirm terminal-state idempotency (no
  double execution).
- **Crash-window reconciliation:** kill during a wait/branch dispatch; confirm
  `reconcile_workflow_waits` / staged-build reconciliation converges.
Capture worker logs + run trace (Console → "Workflow izleri") for each.

**F3. Retention purge dry-run then (approved) commit.**
```powershell
.venv\Scripts\python.exe manage.py purge_retention                          # report only
.venv\Scripts\python.exe manage.py purge_retention --commit --actor <admin> # after window approval
```
Confirm report-mode mutates nothing and commit clears only >90-day bulky state; check the
`retention.purge` audit rows.

**F4. Live Grafana/Prometheus verification.**
Deploy/point Prometheus at the metrics endpoint (bearer `METRICS_BEARER_TOKEN`), load
`deploy/monitoring/prometheus-rules.yaml` and `deploy/monitoring/grafana-dashboard.json`.
Synthetically trigger each new alert (queue saturation, stuck waits, retry storm, compensation
failure, budget/kill-switch) and confirm it fires and links to the runbook section
(`docs/operations/sprint-7-observability-runbook.md`). Grafana/Prometheus are **not** deployed
in the current box — this needs the monitoring stack.

**F5. Turkish browser Studio journey (record).**
In a browser (LDAP-disabled dev auth), walk the end-to-end Turkish flow and record screenshots
or a screen capture:
author (Scenario Studio, incl. a new node family) → diagnose → publish → compile/promote release
→ run → view the redacted workflow trace. Store the recording under this task folder and
reference it in `verification.md`.

**F6. Owner sign-off.**
Record explicit Phase 2.6 completion sign-off (owner + date) in `verification.md`, update
`docs/planning/master-plan.md` and `docs/planning/phase-2-6-plan.md`, transfer any durable
decisions to ADRs, and archive the task per planning policy.

---

## Done-when

- E: S01–S07 gate-passing pack committed under `gitops/` after review; demo seed reset with no
  stale grammar.
- F: recovery drills, live alerts and the Turkish journey evidenced in `verification.md`; owner
  sign-off recorded; master/phase plans updated; task archived.
