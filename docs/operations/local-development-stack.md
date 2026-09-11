# Local development stack

`scripts/local-stack.ps1` is the supported Windows entry point for the complete local AgentHub
topology: PostgreSQL/pgvector, Redis, MinIO, migrations, web, runtime/ingestion/eval workers, and
Celery beat. It also builds the workflow-builder frontend before application startup.

Run commands from the repository root in PowerShell. Prerequisites are Docker Desktop with Compose,
Node.js/npm, and access to the Docker engine. Real provider settings remain optional environment
variables; never commit credentials to `.env`.

## Normal update: preserve local data

Use this after pulling or changing code. It installs the locked frontend packages, builds the
frontend and application image, starts infrastructure, applies forward migrations, recreates all
application roles, waits for liveness, and prints service state:

```powershell
.\scripts\local-stack.ps1
# Equivalent:
.\scripts\local-stack.ps1 -Action Update
```

`Update` preserves the Compose `pgdata` and `miniodata` volumes. It does not roll migrations back or
seed/replace existing records.

`Update` does not reinstall dependencies on every source edit:

- Frontend `npm ci` runs only when `package-lock.json`, Node, or npm changes. Otherwise the existing
  locked `node_modules` installation is reused and only the local frontend build runs.
- Python third-party packages live in a Docker layer keyed by `pyproject.toml` and `requirements.lock`. Editing `apps/` or
  `config/` reinstalls only the local `agenthub` package with `--no-build-isolation --no-deps`; it
  does not resolve or download Python dependencies or build tools.
- When dependency metadata genuinely changes or the Docker build cache was manually removed,
  BuildKit reuses its pip download cache where available. A first build on a new machine or after
  cache pruning still requires registry access.

## Clean start: delete all local data

Use this only when the local database and object store may be discarded:

```powershell
.\scripts\local-stack.ps1 -Action Fresh
```

The command requires typing `FRESH` before it runs `docker compose down --volumes`. For an intentional
non-interactive reset:

```powershell
.\scripts\local-stack.ps1 -Action Fresh -Force
```

> **DANGER — `Fresh -Force` is a high-risk, destructive command.** It bypasses the interactive
> confirmation and immediately deletes this Compose project's complete local PostgreSQL database and
> MinIO object-storage volumes. This includes every local tenant, user, scenario, release, run,
> document, index, audit record, uploaded object, and any other data stored there. The script cannot
> undo or recover this deletion. Never use `-Force` unless the environment has been positively
> identified as disposable and permanent data loss is explicitly intended. Never paste it into
> routine startup or troubleshooting instructions.

Both `Fresh` variants permanently remove this Compose project's local PostgreSQL and MinIO volumes;
plain `Fresh` requires typed confirmation, while `Fresh -Force` removes that final safety barrier.
The new database is empty except for migrations. Demo users are deliberately not seeded automatically,
because `seed_demo` prints credentials and changes data. Seed them explicitly when needed:

```powershell
docker compose -f deploy/compose/docker-compose.yml run --rm web python manage.py seed_demo
```

The command prints a generated password and one-time tokens. Capture them only in an approved local
password manager; do not put them in source control or persistent logs.

## Status, logs, and stop

```powershell
.\scripts\local-stack.ps1 -Action Status
.\scripts\local-stack.ps1 -Action Logs -Service web
.\scripts\local-stack.ps1 -Action Logs -Service worker-ingestion
.\scripts\local-stack.ps1 -Action Stop
```

`Status` queries Compose and `http://127.0.0.1:8000/v1/health/live`. `Logs` is deliberately bounded to
the latest 100 lines. `Stop` stops containers but preserves named volumes, so the next `Update`
continues with the same data.

For ordinary development, use `Update` and `Stop`. Neither deletes named volumes. Do not use `Fresh`,
and especially do not use `Fresh -Force`, as a troubleshooting shortcut.

## Failure handling

- If Docker reports an engine/pipe access error, start Docker Desktop and run PowerShell with an
  account permitted to use its engine.
- If port 8000 (or an infrastructure port) is already allocated, stop the old host-mode process or
  other stack, then rerun `Update`. The script never kills unrelated processes automatically.
- A failed migration prevents application roles from starting and is printed directly by the
  command. Correct the migration/configuration and rerun `Update`.
- A failed liveness wait prints Compose state and the latest 100 web log lines, then exits non-zero.
  Inspect other roles with `Logs -Service <name>`.
- Provider and object-store overrides are inherited by Compose from the current environment. The
  script does not print them. See `.env.example` for supported local variable names.

Do not run host-mode web/Celery processes alongside the complete Compose topology. Host mode remains
available for focused debugging in [the manual testing guide](../manual-testing-guide.md), but the
single-command Compose mode is the default operational standard.
