# Verification: Phase 2.8 Part 7 — Unified runs and kill-switch management

> **Status: Implemented and automated/offline verified on 2026-07-29.**

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Unified projection/filter tests | `pytest -q apps/console/tests/test_phase_2_8_part_7.py ...` | Pass | Included in 117 focused tests | Tenant-first visibility, closed kind/bucket/date/page filters, exact dashboard mappings and seven-query native bound |
| Native detail/action auth | Same focused suite | Pass | Exact execution cancel allow/deny and CSRF tests | Projection does not grant a universal action |
| Kill-switch service/migration | Focused suite; `manage.py makemigrations --check --dry-run`; live `manage.py migrate --noinput` | Pass | `agents.0006_unified_runtime_control` applied | Existing global/organization rows migrate in place; exact constraints added |
| Concurrency/in-flight behavior | Workflow/runtime focused tests | Pass | Admission, claim and non-terminal transition boundaries covered | Durable queued/waiting state is retained; cancellation remains explicit |
| Document separation | Document/ingestion focused tests | Pass | Quarantine, restore, connector rejection, grant-revoke and audit rollback covered | Quarantine conveys no content/retrieve capability |
| PostgreSQL RLS | `pytest -q ... apps/agents/tests/test_kill_switch_rls.py` | Pass | Included in 117 focused tests | Direct tenant lineage, corrupt-lineage cross-tenant defense and FORCE-RLS behavior preserved |
| Audit/redaction/metrics | Runtime/document focused tests and source review | Pass | Fail-closed rollback, denial audit, superadmin event prefixes and closed metric labels | No raw payload, prompt, document text, provider error, token or ID metric label |
| Static and migration consistency | `ruff check`; `ruff format --check`; targeted `mypy`; `manage.py check`; `makemigrations --check --dry-run`; `git diff --check` | Pass | Ruff clean; 212 files formatted; mypy clean on 16 changed source files; Django clean; no missing migration | No production dependency added |
| Full regression suite | `DJANGO_SETTINGS_MODULE=config.settings.test pytest -q` | Pass | `1022 passed, 60 skipped in 169.76s` | Skips are backend-specific; changed PostgreSQL paths are covered by the focused suite |
| Live local runtime | Compose `migrate`, service restart, `compose ps`, `/v1/health/live` | Pass | PostgreSQL/Redis/MinIO healthy; web and four workers/beat running; HTTP 200 | Additive migrations applied to the local development stack |
| Browser smoke | In-app browser to `/console/runs/` | Partial | Correct unauthenticated operator-login boundary rendered | No credential/session was created; authenticated owner UX acceptance remains |

## Focused automated result

The final focused PostgreSQL suite covered the changed console, runtime-control, document
quarantine, scenario-grant, ingestion/connector, workflow and runtime-control RLS surfaces:
`117 passed in 45.16s`.

The repository-wide hermetic suite completed with `1022 passed, 60 skipped in 169.76s`. A diagnostic
run under the live local settings also passed 1069 tests; its eight MCP/metrics 404s were caused by
the live `MCP_ENABLED=false` and metrics configuration overriding the pytest settings, and disappeared
under the repository-authoritative test settings.

The projection is bounded to 50 rows per page, 10 pages and 90 days. Its empty/all-kind service
path executes exactly seven native queries, one per supported family, with no row-driven query
growth. Dashboard active/attention records use the exact 90-day execution status contract; done
uses the exact 24-hour contract.

## Review

- Staff engineering: native tables remain authoritative; the projection is presentation-only;
  migrations are additive/preserving and compatibility callers retain their behavior.
- Application security: active organization is a narrowing filter only; every mutation resolves a
  trusted exact target and reauthorizes centrally; audit persistence failures roll back mutations;
  runtime controls and document content authority remain separate.
- SRE: suspension is checked at admission, claim and transition boundaries; running work stops
  cooperatively; bounded counters use closed low-cardinality labels; runbook records privileged
  resume and superadmin intervention.

## Checks not run and remaining risks

- Authenticated responsive/keyboard/screen-reader browser owner acceptance was not run because the
  live browser had no authorized session and no credential was created for verification.
- Production-volume load/latency and representative large-table `EXPLAIN (ANALYZE, BUFFERS)` evidence
  were not run. Query count, range and pagination are bounded, but deployment-scale plans remain a
  promotion gate.
- Real automatic/policy control producers are not introduced by this part; the persisted provenance
  and privileged-resume contract is verified through service tests.
- Application rollback retains the new rows and hides Part 7 surfaces. Schema reversal succeeds only
  when no project/scenario controls exist; otherwise it fails closed because collapsing exact
  controls into one legacy organization row would require separate destructive-change approval.

## Final status

**Implemented and automated/offline verified.** Authenticated browser owner acceptance and
production-scale performance evidence remain explicit rollout gates; the task stays unarchived
until those acceptance gates close.
