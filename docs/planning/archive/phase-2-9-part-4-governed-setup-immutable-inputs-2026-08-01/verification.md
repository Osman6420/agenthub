# Verification: phase-2-9-part-4-governed-setup-immutable-inputs

## Result

Implemented and verified 2026-08-01. Exact scenario editors can create every governed contract/eval
release prerequisite, and platform administrators can register, disable, and grant the existing
governed profiles without shell/database bootstrap. No external provider/connector call was made.

## Automated evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Target SQLite | Passed | 55 passed, 2 PostgreSQL-only skips across Part 4, model, embedding, Confluence, and REST tests |
| Target PostgreSQL/RLS | Passed | Same matrix: 57 passed against real PostgreSQL |
| Broad affected SQLite | Passed | Console + artifacts + orchestration + ingestion: 419 passed, 24 backend-only skips |
| Full repository SQLite | Passed | 1,088 passed, 61 PostgreSQL-only skips with workspace `--basetemp` |
| Full repository PostgreSQL | Passed | 1,144 passed, 5 opposite-backend skips with canonical PostgreSQL/Redis/MinIO profile and clean test DB |
| Django/schema | Passed | `manage.py check` clean; `makemigrations --check --dry-run` reports no changes |
| Ruff/diff | Passed | Changed Python formatted/linted; `git diff --check` clean |
| Target mypy | Baseline-limited | No Part 4 error; four unchanged imported baseline errors remain in assignment/tenancy/forms |

The first full SQLite run passed 1,084 tests but four fixtures could not access the global Windows
pytest temp directory; the complete rerun with a new workspace `--basetemp` passed. The first full
PostgreSQL run omitted the documented MinIO host variables and produced storage setup failures; the
canonical clean-DB rerun with PostgreSQL, Redis, and MinIO passed in full.

## Authorization, security, and audit evidence

- Exact editor success creates sequential immutable versions and transactional safe-metadata audit;
  inline-secret validation failure is audited without body content.
- Same-tenant unassigned scenario is 404 and neighboring exact release manager is 403 for authoring.
- Tenant member setup GET/POST is 403. Platform registration audit and inventory contain no endpoint
  or secret reference.
- Embedding grants are explicit/idempotent; model, embedding, Confluence, and REST disable is
  status-only and audited.
- Embedding/Confluence/REST grants lock and re-read the current profile row. Tests prove a stale
  pre-disable object cannot create a post-disable grant.
- Connector tenant pages expose logical profile/revision readiness only; destination, secret ref,
  and source input values remain absent.

## Browser and operational evidence

On the current local build, temporary exact editor and platform-admin identities completed:

1. guided input-contract creation and contextual immutable version display;
2. platform-only REST profile registration with no endpoint/secret echo;
3. exact document-set grant;
4. tenant immutable REST mapping creation and source binding;
5. source readiness display without input, destination, or credential disclosure; and
6. direct tenant access to platform setup denied with 403.

No **Şimdi çalıştır** or other external egress action was invoked. The source remained unsynchronized,
the temporary QA REST profile was disabled, both QA identities were deactivated, and the browser tab
was closed. Desktop visual layout was inspected on the current in-app browser build.

## Architecture, data, and residual risk

No migration, dependency, public API, authentication, role/capability, secret storage, network
policy, firewall, or production-system change. Existing modular-monolith services and ADR-0002/
ADR-0005 egress contracts remain authoritative, so no new ADR is required. Model profiles remain
platform/deployment selected; embedding grants are organization-scoped and connector grants are
exact-document-set scoped.

Platform-admin compromise remains high impact. Profile registration does not prove deployment DNS,
CA, secret, provider, network-policy, privacy, or cost readiness; those gates remain operational and
fail closed. The repository-wide mypy baseline retains four unchanged imported errors.

## Final status

Verified and completed 2026-08-01. Part 5 is next.
