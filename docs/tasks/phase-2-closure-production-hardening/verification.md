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

## Phase 2.5 handoff readiness (2026-07-16)

Phase 2.5 Parts 1–9 are completed, verified and owner-accepted. The canonical application image builds;
frontend, full SQLite, full PostgreSQL/Redis, formatter, lint, type, Django, migration and compile
gates pass, and the authenticated Turkish product journey was accepted on 2026-07-16.

The live Phase 2 items below remain blocked on concrete owner/environment inputs rather than code:

| Live item | Required input and approval |
| --- | --- |
| Confluence | Approved base URL, CA/DNS/private-CIDR policy, secret reference, synthetic space/page and disable owner |
| Generic REST | Approved HTTPS URL, auth secret reference, response mapping, synthetic payload, schedule and disable owner |
| Embedding | Provider/model profile, endpoint/network policy, retention/privacy decision, token/cost ceiling and synthetic text |
| OCR | Provider profile, endpoint/network policy, retention/privacy decision, page/size/cost ceiling and synthetic document |
| AI authoring | `ModelProfile`, `AI_AUTHORING_MODEL_PROFILE_ID`, privacy/retention/spend approval and non-publishing candidate smoke input |
| Production RLS | Exact database/pool topology, application role secret, change window, rollback approver and pool-leak evidence |
| Operations | Alert/metric owner, redacted audit review, disable/rollback drill and residual-risk sign-off |

No real profile, credential, network rule, production role or production data was created or changed
during the Part 9 local verification.

## Local live-closure probe — 2026-07-16

- The local PostgreSQL catalog inventory found all expected protected/bootstrap/telemetry tables,
  but `check_tenant_rls --app-role agenthub_app` failed closed with `APP_ROLE_MISSING` and 47
  table-specific `SELECT_MISSING` findings (48 total). No role/grant/policy mutation was attempted.
- Active local embedding profiles exist, including one deterministic synthetic index that is active,
  store-ready and contains one document/chunk. This is useful local evidence, not production approval.
- A local `gemini-chat` model profile exists. The running web/worker were started with the selected
  AI-authoring profile and both governed Scenario Studio and live Gemini workflow candidates passed
  canonical diagnostics. A separately launched shell did not inherit that process environment;
  this was an inspection-scope mismatch, not missing AI-authoring functionality. The selector is not
  persisted in the developer `.env`. No Confluence, generic REST or OCR profile is registered.
- Consequently Phase 2.5 is closed, but Phase 2 live-environment closure remains open and must not be
  represented as passed until the missing role/profile/network/privacy/cost/rollback evidence lands.

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
