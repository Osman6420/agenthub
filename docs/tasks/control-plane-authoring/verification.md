# Verification: control-plane-authoring

## Result

Implemented and verified on SQLite and PostgreSQL on 2026-07-10. The PostgreSQL
full-suite verification was completed while validating Sprint 5.

## Evidence

- `python -m pytest -q -p no:cacheprovider`: 74 passed.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed.
- `python -m mypy .`: passed (115 source files).
- `python manage.py check`: passed, no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.

## Acceptance evidence

- Console: platform-admin-only organization create; tenant-scoped project,
  scenario/alias, consumer, and binding forms; forged cross-tenant selections denied.
- Authorization is enforced again immediately before save.
- Console and GitOps creates write audit events in the domain-write transaction.
- GitOps imports create-only, is idempotent for identical documents, and rejects
  unknown/cross-org references and conflicting reapply.
- No migrations or production dependencies were added.
- Follow-up form regression: platform admin can open organization create; project
  owner is a dropdown sourced from memberships in the operator's admin scope; a
  selected owner must belong to the selected organization.

## Follow-up verification

- SQLite full suite: 85 passed, 2 PostgreSQL-only tests skipped.
- PostgreSQL focused console suite: 11 passed.
- Ruff lint/format, mypy, Django check, and migration-drift check passed.

## Manual UI verification

The local web application is running at `http://127.0.0.1:8000` and was restarted
after the form fixes. Manual browser confirmation of organization create and the
project-owner dropdown is pending; record the result here without credentials.

## Environment note

The checked-in `.venv` referenced a removed Microsoft Store Python 3.13 installation.
Checks ran with the available Python 3.14 interpreter. Python 3.13 remains a separate
verification item.

## Residual risk

- Concurrent first imports of the same identity rely on database uniqueness and may
  surface an integrity error rather than the friendly GitOps conflict message.
- Edit/disable and approval-gated high-risk changes remain out of scope.
