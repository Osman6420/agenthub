# Coding Agent Handoff

This is the shared operational handoff for Codex, Claude Code, and other coding
agents working in this repository. It supplements task plans and verification
records; it never replaces them as evidence.

## Sources of truth

- Intended/in-progress scope: `docs/tasks/<task-id>/plan.md`.
- Security assumptions and residual threats: task `threat-model.md`.
- Executed checks and remaining risks: task `verification.md`.
- Current implementation: code, migrations, settings, and tests.
- Cross-task project status: `docs/planning/master-plan.md`.

At handoff, inspect these sources plus `git status`, `git diff`, recent commits,
branches, stashes, and reflog. Do not infer the active task only from open IDE tabs.

## Local runtime snapshot

Last checked: 2026-07-11, Europe/Istanbul.

Record only genuinely time-varying facts here (is a server up, which ports, is MinIO
running). Durable facts — what is implemented/verified, the canonical interpreter, and
how to run the gates — belong in the `@`-imported verified-state of
[`engineering-rules.md`](engineering-rules.md) so every session loads them
automatically. This snapshot is not auto-loaded, so it must never be the only place
such a fact is written.

- Application: `http://127.0.0.1:8000`.
- Health: `GET /v1/health/live` returned `200 {"status":"ok"}`.
- Web process: host Python 3.14 running Uvicorn, not the Compose `web` service.
- Infrastructure: Docker Compose PostgreSQL/pgvector and Redis are running on the
  published localhost ports. MinIO was not running at the last check.
- Runtime logs: `.runtime/web.stdout.log` and `.runtime/web.stderr.log` (gitignored).
- Uvicorn is started without `--reload`; source changes require a web-process restart.
- Uvicorn was restarted after Sprint 8 as PID `2064`; liveness and readiness returned
  `200`, and `/console/` returned the expected unauthenticated `302` redirect.
- Local PostgreSQL now has the additive Sprint 6 and Sprint 8 migrations applied,
  including `evaluations.0001`, `releases.0002`, `artifacts.0002`, and
  `workflows.0001`. A standalone runtime Celery worker was started by the user and
  exposed a stale Redis task whose pytest database row no longer existed. Sprint 8 now
  treats that delivery as a logged no-op; the worker must be restarted to load the fix,
  and a successful non-eager async workflow execution remains pending.
- Interpreter: `.venv` (Python 3.13) is canonical and, after Sprint 5, again has all
  dependencies (`boto3`/`pgvector` installed from `requirements.lock`); gates pass in it
  on SQLite and — with the Compose database — on PostgreSQL. `C:\Python314\python.exe`
  (Python 3.14) is a working fallback that was used during Sprint 5 while `.venv` lacked
  those deps. The durable interpreter/dependency contract lives in the verified-state of
  [`engineering-rules.md`](engineering-rules.md), not in this snapshot.

This is an ephemeral snapshot, not a guarantee. Re-check rather than trusting it:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/v1/health/live
netstat -ano | Select-String ':8000'
docker compose -f deploy/compose/docker-compose.yml ps
Get-Content .runtime\web.stderr.log -Tail 50
```

## Starting the local web application

With PostgreSQL and Redis available on localhost:

```powershell
$env:DJANGO_SETTINGS_MODULE='config.settings.local'
$env:DATABASE_URL='postgres://agenthub:agenthub@localhost:5432/agenthub'
$env:REDIS_URL='redis://localhost:6379/0'
$env:OBJECT_STORE_ENDPOINT='http://localhost:9000'
.venv\Scripts\python.exe -m uvicorn config.asgi:application --host 127.0.0.1 --port 8000
```

Never record operator passwords, bearer tokens, cookies, LDAP credentials, or object
store credentials in this document or runtime logs.

## Manual UI smoke checklist

Use `http://127.0.0.1:8000/console/` with an approved local test operator account.
Record results in the affected task's `verification.md`; do not record credentials.

1. Login redirects to the dashboard and logout works via POST.
2. Lists show only organizations/projects/scenarios/consumers in the operator scope.
3. Platform admin can open and submit `/console/organizations/new/`.
4. Project create renders `owner` as a dropdown of organization members; an owner
   outside the selected organization is rejected.
5. Scenario create writes the scenario and optional alias atomically.
6. Consumer and binding create reject cross-organization selections.
7. Confirm the expected audit event after each successful create.

Current UI evidence:

- Automated SQLite full suite: 85 passed, with 2 PostgreSQL-only tests skipped.
- Automated PostgreSQL console suite: 11 passed.
- The organization-form constructor regression and scoped project-owner selection are
  fixed and the web process was restarted afterward.
- Manual browser re-check of those two corrected forms is pending user confirmation;
  do not mark it manually verified until that confirmation is recorded.

Current cross-agent state:

- Claude completed and committed Sprint 6 as `b66843e`.
- Codex implemented Sprint 7 without modifying Sprint 6 implementation files. Automated
  evidence, including parity against the committed Sprint 6 canary routing contract, is
  in the Sprint 7 verification record.
- Codex implemented and automatically verified Sprint 8 on SQLite and PostgreSQL; see
  its verification record. The web is current, but the user-started worker requires a
  restart after the stale-message fix; manual async workflow smoke remains.

## Agent transition checklist

Before yielding work to another agent:

1. Update the active task plan status and assumptions.
2. Update threat-model mitigations/residual risks when boundaries changed.
3. Record exact commands/results and manual UI evidence in `verification.md`.
4. State whether localhost services are running and whether a restart is required.
5. Report uncommitted and intentionally excluded files (for example local agent
   settings); never overwrite them without authorization.
6. Distinguish implementation complete, automated verification complete, and manual
   UI verification complete.
7. If work is committed, record the commit id; otherwise explicitly say uncommitted.

At the next agent's start, verify this snapshot against live state before acting and
update it when the local runtime topology or common handoff procedure changes.
