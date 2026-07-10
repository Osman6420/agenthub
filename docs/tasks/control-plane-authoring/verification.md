# Verification: control-plane-authoring

## Result

Implemented and verified on SQLite on 2026-07-10. PostgreSQL-specific verification
was not run in this environment.

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

## Environment note

The checked-in `.venv` referenced a removed Microsoft Store Python 3.13 installation.
Checks ran with the available Python 3.14 interpreter using the unchanged
`requirements.lock`. Python 3.13 and real PostgreSQL remain verification items.

## Residual risk

- Concurrent first imports of the same identity rely on database uniqueness and may
  surface an integrity error rather than the friendly GitOps conflict message.
- Edit/disable and approval-gated high-risk changes remain out of scope.
