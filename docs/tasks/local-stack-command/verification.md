# Verification: local-stack-command

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| PowerShell syntax | PowerShell parser API against `scripts/local-stack.ps1` | Pass | `powershell_parse=PASS` | No lifecycle action executed |
| Required artifacts | `Test-Path` for runbook, plan, and threat model | Pass | `required_files=PASS` | Documentation present |
| Compose schema | `docker compose -f deploy/compose/docker-compose.yml config --quiet` | Pass | Exit 0 | Read-only; elevated Docker pipe access required |
| Real status path | `.\scripts\local-stack.ps1 -Action Status` | Pass | PostgreSQL, Redis, and MinIO healthy; liveness HTTP 200 | No service mutation |
| Diff hygiene | `git diff --check` | Pass | Exit 0 | No whitespace errors |
| Destructive-path review | Manual code review | Pass | Only `Fresh` reaches `down --volumes`; confirmation or `-Force` required | `Update` and `Stop` preserve volumes |
| Force warning review | Documentation/runtime static review | Pass | Runbook danger block, manual-guide warning, and red console warning | `-Force` remains intentionally non-interactive |
| Frontend build | `npm --prefix frontend run build` | Pass | TypeScript and Vite built 205 modules | Locked dependency audit reported 1 moderate, 1 high, and 1 critical vulnerability; no dependency was changed |
| Current image build | `docker compose -f deploy/compose/docker-compose.yml build` | Pass | All application-role images exported | Current source bind mount and image inputs validated |
| Live update/migration | Infrastructure `up`, `run --rm migrate`, application-role `up` | Pass | Applied `agents.0004_runtime_control_write_policy`; all canonical roles started | Existing `pgdata` and `miniodata` preserved |
| Pending migrations | `docker compose ... exec -T web python manage.py migrate --check` | Pass | Exit 0 | No pending migration |
| Live readiness | `/v1/health/live` and `/v1/health/ready` | Pass | HTTP 200; database/migrations/Redis `ok` | Full Compose application topology running |

## Acceptance criteria mapping

- `Update` builds current frontend/image, migrates, starts all roles, waits for health, and preserves
  named volumes.
- `Fresh` uses the same startup path after explicit confirmed volume deletion.
- Health failures return non-zero after bounded status and web-log diagnostics.
- The operations runbook documents prerequisites, data semantics, seed behavior, status/log/stop,
  port conflicts, and Docker access failures.

## Security requirement mapping

The CLI uses closed validation sets and fixed subprocess argument arrays, never evaluates user input,
does not print the process environment, and makes destructive behavior explicit.

## Authorization tests

N/A; no application authorization path changed.

## Cross-tenant tests

N/A; no application or tenant data path changed.

## Logging and redaction tests

Static review passed: the script does not echo environment variables or credentials. Diagnostic logs
are bounded to 100 lines. Application-log content remains governed by existing application controls.

## Audit event tests

N/A; local process lifecycle is not an application business/security mutation.

## Migration verification

No migration files changed. The canonical update sequence invoked the `migrate` Compose role before
starting application roles and applied `agents.0004_runtime_control_write_policy`. A subsequent
`migrate --check` returned exit 0.

## Behavior comparison with base branch

Existing raw Compose and specialist host-mode instructions remain available. The new wrapper is the
default documented full-stack path.

## Checks not run

- `Fresh` was not run because it would delete the user's local data.
- The wrapper's update stages were completed individually after the outer command runner timed out
  while waiting for the combined command; frontend build, image build, infrastructure, migration,
  application-role startup, liveness, and readiness all passed separately.
- Application unit/type/lint suites were not run because no application code or dependency changed.
- PowerShell Pester/PSScriptAnalyzer checks are not repository-provided.

## Remaining risks

Docker/npm registry availability and local port ownership are external prerequisites. An intentional
`Fresh -Force` permanently deletes local Compose data.

## Human review required

Confirm the command naming and whether automatic demo seeding should remain opt-in (recommended).

## Final status

Verified.
