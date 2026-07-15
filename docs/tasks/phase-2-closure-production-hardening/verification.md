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

- Completed Phase 2.5 verification and Turkish operator-journey sign-off.
- PostgreSQL non-owner role, FORCE RLS and pooled-context negative-test evidence.
- Live-profile approval records and bounded synthetic smoke results for Confluence, REST,
  embedding, OCR and AI authoring.
- Privacy/retention, cost ceilings, audit/monitoring, disable and rollback evidence.

Governed upload malware/type scanning and its quarantine/failure/redaction/runbook evidence moved
to Phase 3 by owner decision on 2026-07-14; it is not a Phase 2 closure criterion.

## Checks not run

All environment-specific and live checks are pending concrete inputs and execution approval.
Production connection pooling, production role/secret provisioning and production policy activation
remain unverified and require deployment approval. P11 staging-equivalent evidence follows below.

## P11.2–P11.4 evidence (2026-07-14)

- Nine indirect models received direct, non-null tenant lineage through additive/backfill migrations;
  fresh SQLite and PostgreSQL migration chains pass.
- Full SQLite after implementation: `632 passed, 29 skipped`.
- Broad PostgreSQL 16 tenancy/gateway/workflow/agent/ingestion: `253 passed, 5 skipped`; focused RLS
  package after removing `PUBLIC EXECUTE`: `16 passed, 3 skipped`.
- A temporary `agenthub_p11_verify` database and `agenthub_p11_verify_app` role exercised the real
  migration and SQL templates. Readiness reported `47/47`; role flags were all least-privilege
  (`NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`, `NOBYPASSRLS`); immutable artifact
  update/delete were false while authorized draft delete was true.
- The first rollback probe exposed default PostgreSQL `PUBLIC EXECUTE` on the scope helper. The
  migration now revokes it. Rebuilt evidence showed `PUBLIC EXECUTE=false`; after rollback the role
  was `NOLOGIN` with table and function privileges false.
- `tenancy.0002` reverse then forward completed successfully. Temporary database and role were
  deleted. The persistent local `agenthub` database was not migrated or role-mutated.
- Final repository gates pass: Ruff format and lint over 358 files, mypy over 358 source files,
  Django system check, migration drift check and `git diff --check`.
