# Verification: phase-2-5-part-3-ownership-credentials

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Focused Part 3 baseline | `pytest apps/console/tests/test_console.py apps/identity/tests/test_tokens.py -q` | Passed | 15 passed | Run before implementation. |
| Part 3 + affected components (SQLite) | `pytest apps/catalog/tests apps/identity/tests apps/console/tests -q` | Passed | 118 passed | Includes migration, owner, credential, CSRF, denial, audit and redaction coverage. |
| Full repository (SQLite) | `pytest -q` | Passed | 663 passed, 29 skipped | Skips are PostgreSQL/pgvector-only; pytest cache warning is a sandbox filesystem artifact. |
| Focused Part 3/RLS/gateway/MCP (PostgreSQL) | `pytest --ds=config.settings.local ...part_3... ...tenant_context... apps/gateway/tests apps/mcp/tests -q` | Passed | 55 passed, 1 SQLite-only skip | Final code, real PostgreSQL, MCP enabled. |
| Full repository (PostgreSQL) | `pytest --ds=config.settings.local -q` | Passed | 686 passed, 5 skipped | PostgreSQL/pgvector/RLS paths ran; skips are explicit opposite-backend checks. Final error-path scrub was rechecked by the focused PostgreSQL run. |
| Static and schema gates | `ruff format`, `ruff check apps`, `mypy apps`, `manage.py check`, `makemigrations --check --dry-run`, `compileall`, `git diff --check` | Passed | Ruff clean; mypy 355 files; no Django issues or migration drift | No dependency files changed. |
| Runtime preflight | Compose `ps` + `/v1/health/live` | Passed | PostgreSQL/Redis/MinIO healthy; health HTTP 200 | No service started/stopped and live DB was not migrated. |

## Acceptance criteria mapping

1. Verified: console persists an eligible same-organization membership; forged, cross-org and
   ineligible membership tests pass and the service rechecks under row locks.
2. Verified: migration exact-match, unmatched/blank preservation, reverse and re-forward pass on
   SQLite and PostgreSQL with explicit FORCE-RLS tenant scope.
3. Verified: ownership uses `PROTECT`; detail renders durable ownership with legacy fallback.
4. Verified: the GitOps string field remains present/non-authoritative and full GitOps regressions
   pass in both full suites.
5. Verified: console ignores forged subject and generates bounded random opaque subjects; existing
   explicit subjects remain unchanged.
6. Verified: admin happy paths plus anonymous/method/CSRF/read-only/disabled/cross-tenant/foreign
   consumer and foreign-token denials pass.
7. Verified: plaintext is shown once with no-store/no-cache/no-referrer headers and is absent from
   hash, database, audit, subsequent GET, and debug failure response; audit failure rolls back.
8. Verified: rotation atomically revokes/replaces; revoke is idempotent; revoked tokens fail
   resolution immediately.
9. Verified: issue/rotate/revoke audit actions use safe metadata/reason codes and request/trace
   fields; transaction rollback tests cover audit persistence failure.
10. Verified: management command, gateway, MCP, binding, existing token, and subject behavior pass.
11. Verified: SQLite/PostgreSQL migration, RLS, static, schema and full repository gates pass.
12. Partially complete: no dependency/egress/production/destructive change exists; Turkish browser
   journey still requires owner review before `Completed`.

## Security requirement mapping

- Authentication/secret approval is recorded in the plan.
- Token mutators are login + CSRF + POST-only, role-gated, active-organization scoped and use
  locked database rows.
- Plaintext is scrubbed before exception unwind and marked sensitive for production exception
  reporting; the debug technical-500 regression proves the plaintext is absent.
- Mutation and success audit are atomic/fail-closed.
- No OIDC/mTLS/public API/dependency/production change was introduced.

## Authorization tests

Organization/platform admin success and auditor/project-owner-equivalent denial are covered.
Disabled organizations and disabled consumers cannot issue/rotate; revocation remains available for
disabled consumers. Anonymous, GET and missing-CSRF requests cannot mutate credentials.

## Cross-tenant tests

Foreign consumer UUID resolves as not found; a token belonging to another consumer cannot be
rotated/revoked. PostgreSQL tenant context/RLS suites and full PostgreSQL regression pass.

## Logging and redaction tests

Tests assert raw token and token hash absence from durable audit state, later GET responses and
debug failure HTML. One-time responses set `Cache-Control: no-store, max-age=0`, `Pragma: no-cache`,
`Referrer-Policy: no-referrer`, and `X-Robots-Tag: noindex, nofollow`. No credential values were
added as metric labels. The repository has no dedicated secret-scanner command; Ruff's security
rules and manual changed-file inspection found no real credential.

## Audit event tests

`consumer_token.issue`, `.rotate`, and `.revoke` success events record actor, organization, target,
safe status/prefix metadata and stable reason codes. Authorization denials and known inactive-state
failures record deny/failure outcomes. Audit write failure rolls back issue, rotate and revoke.

## Migration verification

`0006_aiproject_owner_membership` adds a nullable protected FK and exact-match data backfill. The
migration establishes one trusted PostgreSQL tenant scope at a time so FORCE RLS neither hides nor
widens rows. Forward/reverse/re-forward preserves owner text and matched linkage on SQLite and
PostgreSQL. Application rollback retains the additive nullable column.

## Behavior comparison with base branch

Existing GitOps owner strings, consumer subjects, bearer format, management-command arguments,
gateway/MCP routes, bindings, and token resolution remain compatible. Console consumer creation no
longer accepts subject and now redirects to canonical detail; this is the approved Part 3 product
change.

## Checks not run

- Live browser/Turkish owner journey: pending owner review. The running dev database was not
  migrated or seeded by this task.
- Production deployment/rollback, live LDAP, external egress and production data: out of scope and
  not authorized.
- A dedicated repository secret scanner is unavailable.
- Concurrent multi-process rotation stress/soak was not run; row locks, uniqueness and deterministic
  transaction tests cover correctness, with load testing retained as residual operational evidence.

## Remaining risks

- Authorized administrators and their browsers can still exfiltrate the one-time plaintext.
- Existing GitOps owner text remains a compatibility label rather than durable membership authority.
- Membership role mutation has no current console surface; future membership lifecycle work must
  reject or reassign ownership before making an owner role ineligible.
- Tokens have no automatic expiry; rotation/revocation remains manual.
- Pytest emits a non-functional cache warning because the sandbox cannot recreate `.pytest_cache`.

## Human review required

- Turkish project-owner and token lifecycle journey.
- One-time token storage warning and rotation/revocation wording.
- Future GitOps durable-owner and automatic token-expiry decisions remain deferred.

## Final diff review

- Staff engineer: additive nullable ownership schema, explicit compatibility label, bounded domain
  services and focused console routes form the smallest complete Part 3 change; no unrelated
  architecture or dependency change was found.
- Application security: scoped authorization, foreign-target non-disclosure, CSRF/POST, row locks,
  hash-only persistence, atomic audit rollback and debug exception redaction are covered. The review
  found and corrected a potential debug technical-500 plaintext leak; no unresolved critical/high
  finding remains.
- SRE: migration is tenant-scoped under FORCE RLS and reversible without deleting legacy data;
  application rollback retains the additive column; audit failure is fail-closed. Browser acceptance,
  token-expiry operations and concurrent soak remain explicit follow-ups rather than hidden claims.

## Final status

Verified. `Completed` and archival are pending the required Turkish owner browser review.
