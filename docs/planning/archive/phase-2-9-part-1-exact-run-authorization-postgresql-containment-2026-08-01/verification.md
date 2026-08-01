# Verification: Phase 2.9 Part 1 — Exact run authorization and PostgreSQL containment

> Status: Implemented and verified on 2026-08-01. Owner approval, focused regressions, both full
> database profiles, static/system checks and the mandatory current-build browser gate are recorded
> below.

| Check | Result | Evidence |
| --- | --- | --- |
| Owner approval | Passed | The owner instructed Codex on 2026-08-01 to complete Phase 2.9 Part 1, including the planned authorization and tenant-isolation correction. |
| Controlled pre-fix regression | Passed as a reproduction | The initial 12-item SQLite selection produced 9 failures and 3 passes; the failures exposed same-tenant adjacent-scenario list/detail access before the fix. |
| Focused run authorization (SQLite) | Passed | Disposable Python 3.13 container, `config.settings.test`: 23 passed in 24.04s across `test_phase_2_9_part_1.py`, `test_workflow_trace_console.py` and `test_phase_2_8_part_7.py`. |
| Focused PostgreSQL/security regressions | Passed | Canonical Compose PostgreSQL profile with `--create-db`: 11 passed in 27.67s across the Part 1 matrix, current human-wait authority test and temporary non-owner middleware test. |
| Full SQLite backend | Passed | Split only to keep output bounded: console/workflows/tenancy/identity 446 passed, 18 PostgreSQL-only skipped; remaining apps 610 passed, 42 PostgreSQL-only skipped. Total: **1,056 passed, 60 skipped** of 1,116. |
| Full PostgreSQL backend | Passed | Canonical local PostgreSQL/pgvector profile: critical group 461 passed, 3 profile-specific skipped; remaining apps 650 passed, 2 guard-only skipped. Total: **1,111 passed, 5 skipped** of 1,116. |
| Ruff lint | Passed | `ruff check apps` completed with no findings. |
| Ruff formatting | No new debt | Task-owned new file and mechanically touched small tests are formatted. Repository-wide check reports 10 pre-existing files would be reformatted, improved from the 11-file audit baseline; broad unrelated formatting was intentionally not performed. |
| Mypy | Part 1 clean; repository baseline remains | The stale wait API errors were closed. Full `mypy apps` improved from 22 to 12 errors; the 12 remaining errors are outside Part 1 in 11 pre-existing files. |
| Django/system checks | Passed | `manage.py check`, `makemigrations --check --dry-run`, `compileall apps config` and `git diff --check` passed; no migration drift was detected. |
| Mandatory browser gate | Passed | Current restarted web build, synthetic exact runtime operator: only the assigned scenario's six runs were listed; assigned detail opened; a known same-tenant adjacent-scenario detail returned 404. At 390×844 there was no horizontal overflow; filter/main content remained visible; browser console warnings/errors were empty. Original approver session was restored. |
| Runtime health | Passed | Canonical Compose reported all eight services running, PostgreSQL/Redis/MinIO healthy, and `/v1/health/live` plus `/v1/health/ready` returned 200 after the web-only restart. |

## Acceptance criteria mapping

1. Unified and compatibility lists begin with `scoped_runs(user)` and only then apply organization,
   date and request filters. The exact-operator regression proves allowed and hidden rows and URLs;
   the fixed seven-query projection test proves the page remains bounded.
2. Detail and cancellation target resolution now calls the same authorized queryset. Same-tenant
   adjacent-scenario and cross-tenant identifiers return 404 before nested metadata or mutation;
   the hidden run remains unchanged.
3. The exact runtime operator can read and cancel its assigned run under the existing central action
   check. Viewer, editor, release manager and approver responsibilities do not grant run reads.
4. The organization auditor retains organization-wide reads, receives 403 on cancel, causes no
   state change and emits a denial audit without scenario label or actor identifier.
5. Only the execution family receives the run queryset. Other unified-operation families retain
   their native authorized querysets and are not widened by runtime responsibility.
6. Organization selection is applied inside `project_operations` only after the caller supplies an
   authorized queryset; it is a narrowing filter, not authority.
7. SQLite and canonical PostgreSQL results agree. The PostgreSQL test uses a temporary
   `NOSUPERUSER NOBYPASSRLS` role and the repository's FORCE-RLS tenant-context path.
8. The temporary-role fixture now matches the already-canonical provision script by granting only
   the reads required for platform-admin and membership scope derivation. No production grant,
   policy, owner or schema changed.
9. All three stale workflow-wait call sites use the current event-token or persisted human-actor
   contract. Forged identifiers, wrong tenant, bearer-token misuse, neighboring/unassigned actors,
   invalid payload and replay conflict remain asserted; directly related mypy errors are gone.
10. Both full database profiles, focused security regressions, lint/system/migration checks and the
    browser gate passed. Repository-wide formatting and typing retain only documented pre-existing
    debt, with no Part 1 regression.

## Security and authorization evidence

- Authorization is applied before list projection, pagination, direct-object resolution, related
  event rendering and cancel mutation.
- The tested paired identities cover exact runtime operator, scenario viewer/editor/release
  manager/approver, revoked/expired runtime assignments, organization auditor and cross-tenant
  access. Existing full-suite coverage supplies global/organization administrators, project roles
  and membership-only behavior through the same `scoped_runs` predicate.
- Hidden same-tenant and cross-tenant identifiers return the same 404 and produce no mutation.
- Human waits authorize the persisted actor and exact scenario approval responsibility; role names
  and bearer tokens supplied by a client cannot confer human-decision authority.
- The PostgreSQL correction is fixture drift only: `identity_platformresponsibilityassignment` and
  `auth_user` are required reads already present in canonical provisioning. No broad/default grant,
  superuser, ownership, `BYPASSRLS` or FORCE-RLS weakening was introduced.

## Logging, audit and redaction evidence

The auditor cancel denial stores only the bounded run UUID plus existing stable action/outcome/reason
fields; the test rejects scenario label and actor identifier leakage. Human-wait denial tests assert
four audited denials and confirm that none consumes one-shot authority. Browser console inspection
found no warning/error output. No new metric label or high-volume read audit was added.

## Migration and operational evidence

No model, migration, production privilege or business data changed. Migration drift is empty. The
web service alone was restarted to load the current mounted source; infrastructure and workers were
left running, and live/readiness endpoints remained healthy.

## Behavior comparison with the audit baseline

The 2026-07-31 audit and the controlled failing regression both showed an exact runtime operator
seeing an adjacent same-organization scenario's run. After the fix, the same class of synthetic
identity sees only its assigned scenario in automated SQLite/PostgreSQL tests and in the current
browser build; the adjacent direct URL returns 404.

## Checks not fully clean

- Repository-wide `ruff format --check apps` retains 10 previously existing unformatted files.
- Repository-wide mypy retains 12 unrelated pre-existing errors in 11 files. No Part 1-owned type
  error remains.

These are not release blockers for this narrowly scoped security correction because both baselines
improved or remained unchanged and all changed behavior passed both database profiles.

## Remaining risks

- The synthetic browser user and exact runtime assignment remain in the disposable local demo
  database so the evidence can be reproduced; they are passwordless and have no production access.
- Production rollout still requires the normal deployment-role privilege comparison and safe
  404/403 monitoring described in the task plan.
- Pre-existing repository formatting and mypy debt remains visible to Phase 2.9 Part 7.

## Human review

Staff-engineering review found one canonical queryset boundary and a bounded projection query count.
Application-security review confirmed non-disclosing 404/403 semantics, persisted authority,
redacted denial audit and no privilege broadening. SRE review confirmed no migration, healthy
Compose services and a deny-safe rollback. The current-build browser gate was completed with the
owner's existing session restored afterward.

## Final status

**Implemented and verified.** All Part 1 release-blocking evidence is complete; remaining Phase 2.9
work begins with Part 2.
