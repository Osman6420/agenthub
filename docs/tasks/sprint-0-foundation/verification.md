# Verification: sprint-0-foundation

Record every executed command and its result. Do not infer success.

## Environment

- OS: Windows 11 (development). Target runtime: Linux container (Python 3.13).
- Python (venv): CPython 3.13.14 (`py -3.13 -m venv .venv`).
- Key versions: Django 5.2.16, Celery 5.6.3, ruff 0.15.21, mypy 2.1.0,
  pytest 9.1.1, pytest-django 4.12.0. Full set in `requirements.lock` (58 pkgs).
- Django settings for checks: `config.settings.test` (SQLite `:memory:`, isolated).
- Date: 2026-07-10.

## Commands and results

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| Dependency install | `pip install -e ".[dev]"` | PASS | `Successfully installed ... Django-5.2.16 celery-5.6.3 ...` |
| Formatter | `ruff format --check .` | PASS | `18 files already formatted` (after applying `ruff format`, which reformatted `config/settings/base.py`) |
| Linter | `ruff check .` | PASS | `All checks passed!` |
| Type-check | `mypy .` | PASS | `Success: no issues found in 18 source files` |
| Migration drift | `python manage.py makemigrations --check --dry-run` | PASS | `No changes detected` (exit 0) |
| System check | `python manage.py check` | PASS | `System check identified no issues (0 silenced).` |
| Unit tests | `pytest` | PASS | `4 passed in 0.82s` |

## Smoke checks (role bootability)

| Check | Command | Result |
| --- | --- | --- |
| Celery app + queues load | `python -c "from config import celery_app; ..."` | PASS — queues `['default','runtime','ingestion','eval']` |
| Web role fails closed w/o secret | `DJANGO_SETTINGS_MODULE=config.settings.production python -c "import django; django.setup()"` | PASS — raises `ImproperlyConfigured: Set the DJANGO_SECRET_KEY environment variable` |
| Web role ASGI imports w/ env set | `DJANGO_SECRET_KEY=... DJANGO_ALLOWED_HOSTS=... python -c "import config.asgi"` | PASS — `ASGIHandler` |
| Worker role entrypoint | `celery -A config --version` | PASS — `5.6.3` |

## Acceptance criteria mapping (Sprint 0)

- "`migrate`, web, and all worker roles start locally" — web ASGI import + worker
  entrypoint + Celery queue load verified above; `makemigrations --check` clean.
  Full Docker Compose boot of the topology is an operator check (see notes).
- "Tests run under isolated test settings" — verified: `pytest` runs on SQLite
  `:memory:` with LocMem cache and eager Celery; no external service required.
- "Migration drift fails CI" — `makemigrations --check --dry-run` wired as a CI
  step and verified locally (exit 0 when in sync).

## Notes / skipped checks

- Integration tests against PostgreSQL/pgvector, Redis, and MinIO are deferred to
  the sprints that introduce those models/flows (Sprint 5+). Booting the full
  Docker Compose topology (`deploy/compose/docker-compose.yml`) is a manual
  operator check for Sprint 0 and was not executed in this run.
- Type-check uses `mypy 2.1.0` with `django-stubs`; `manage.py check` and health
  readiness against a live Redis were not exercised (Redis check is unit-tested
  via a faked dependency).
- Secret scanning and dependency/container scanning are planned CI hardening, not
  yet enabled.
