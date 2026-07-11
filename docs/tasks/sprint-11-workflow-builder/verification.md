# Verification: sprint-11-workflow-builder

Sprint 11 delivers the governed workflow builder: a tenant-scoped draft API + compiler
diagnostics + node-schema generation + a shared-path publish (`apps.builder`), and a React
Flow SPA (`frontend/`) served same-origin through Django. The frontend is non-authoritative;
the workflow DSL and backend services are the source of truth.

## Environment

- Interpreter: `.venv` (Python 3.13), dependencies from `requirements.lock`.
- Node toolchain: Node v20.20.0 / npm 10.8.2 (build-time only; the SPA ships as static
  assets). Frontend dependencies pinned in `frontend/package-lock.json`.
- SQLite gates: `DJANGO_SETTINGS_MODULE=config.settings.test`.
- PostgreSQL gates: `DJANGO_SETTINGS_MODULE=config.settings.local` with `--create-db`,
  `MCP_ENABLED=true`, `METRICS_BEARER_TOKEN` set, and a writable `--basetemp` on Windows.

## Commands and results

### Backend increment (implemented and verified)

| Command | Result |
| --- | --- |
| `ruff format --check .` | Pass — 252 files |
| `ruff check .` | Pass — all checks passed |
| `mypy .` | Pass — no issues in 252 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes detected |
| `python manage.py check` | Pass — no issues (0 silenced) |
| `pytest` (SQLite, `config.settings.test`) | Pass — 364 passed, 2 skipped (+27 builder) |
| `pytest apps/builder apps/console --create-db` (PostgreSQL) | Pass — 46 passed |

New additive migration `apps/builder/migrations/0001_initial.py` (`WorkflowDraft`,
unique `(organization, logical_id)`, `(organization, -updated_at)` index). Applied cleanly
on SQLite and PostgreSQL. 27 builder tests in `apps/builder/tests/`.

### Frontend increment (React Flow SPA)

| Command | Result |
| --- | --- |
| `npm ci` (frontend) | _pending_ |
| `npm run test` (frontend unit + e2e builder flow) | _pending_ |
| `npm run build` (frontend) | _pending_ |

## Acceptance-criteria evidence

_pending — filled after implementation and gates._

## Security / privacy notes

_pending._

## Residual risk / not delivered

_pending._
