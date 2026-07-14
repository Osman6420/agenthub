# Verification: Phase 2 closure production hardening

## Status

P11.1 RLS deployment-readiness inventory is implemented and offline-verified. No role, grant,
policy, table, connection, tenant context, production-hardening or live-activation mutation was
executed.

## P11.1 evidence (2026-07-14)

- Targeted SQLite: `6 passed, 2 skipped` (PostgreSQL-only cases skipped).
- Targeted PostgreSQL 16 with an isolated `--create-db`: `6 passed, 2 skipped` (SQLite-only cases
  skipped). This proves exact canonical-policy recognition, non-owner/non-bypass role acceptance,
  missing-role fail-closed reporting and known unprotected-table denial.
- Full SQLite regression: `626 passed, 27 skipped`.
- Ruff format/check: `355 files already formatted`; all checks passed.
- Mypy: no issues in 355 source files.
- Django system check: no issues; migration drift check: no changes detected.
- `git diff --check`: passed.

The first PostgreSQL run exposed an unhandled missing-role lookup in
`has_table_privilege`; the implementation was corrected to report `APP_ROLE_MISSING` and the
complete PostgreSQL test was rerun successfully. The persistent local database was read only for
policy-expression inspection; all test DDL ran against the isolated test database and cleaned up
its generated probe role.

## Evidence required before closure

- PostgreSQL non-owner role, FORCE RLS and pooled-context negative-test evidence.
- Upload scanner selection/approval, quarantine/failure/redaction tests and operational runbook.
- Live-profile approval records and bounded synthetic smoke results for Confluence, REST,
  embedding, OCR and AI authoring.
- Privacy/retention, cost ceilings, audit/monitoring, disable and rollback evidence.

## Checks not run

All environment-specific and live checks are pending concrete inputs and execution approval.
Application connection pooling/context propagation, a real dedicated app role, the nine indirect
tenant-table schema/policy designs, bootstrap/telemetry access and actual policy activation remain
unverified.
