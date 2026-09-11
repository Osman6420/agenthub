# Verification: qa-analiz-19-bulgu-duzeltme

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Targeted tests, per bug | `pytest <files>` (SQLite) | Pass, incrementally per phase | Session transcript | Run after each of the 19 fixes, before moving on |
| Full repo suite (SQLite) | `.venv\Scripts\python.exe -m pytest` | 1330 passed, 66 skipped, 0 failed | Session transcript | All skips are PostgreSQL-only guards (pre-existing pattern) |
| PostgreSQL profile, touched apps | `pytest apps/documents apps/ingestion apps/releases apps/tools apps/console apps/evaluations apps/gateway apps/mcp --create-db` against Compose PostgreSQL (`config.settings.local`) | 837 passed, 2 skipped, 0 failed | Session transcript | Includes the BUG-002 real-thread concurrency test (`test_scenario_create_rejects_a_truly_concurrent_duplicate_submit`, PostgreSQL-only per existing repo convention for this class of test), run and confirmed passing individually too |
| `ruff format --check apps` | full repo | 474 files, all formatted | Session transcript | |
| `ruff check apps` | full repo | All checks passed | Session transcript | |
| `mypy apps` | full repo | 7 errors, all pre-existing and unrelated to this change (6 in untouched migration-history test files, 1 pre-existing `apps/console/views.py` finding at an unrelated line, unchanged by this diff — confirmed by locating it far from every edit in this task and by `git diff` not touching that line) | Session transcript | mypy run via a local `mypy==1.15.0` install instead of the repo-locked `mypy==2.1.0`/`librt==0.13.0` -- the locked `librt` native extension is blocked by this host's Windows Application Control policy (`Uygulama Denetimi ilkesi`) regardless of version; 1.15.0 has no such dependency and gave full, working type-checking coverage. This is a host-environment substitution, not a repo change; flagged as a residual environment note below |
| `manage.py check` | SQLite + PostgreSQL profiles | System check identified no issues | Session transcript | |
| `manage.py makemigrations --check --dry-run` | SQLite + PostgreSQL profiles | No changes detected | Session transcript | Confirms migration `apps/ingestion/migrations/0016_scope_staged_job_checksum_constraint_to_active_states.py` fully matches the model state |
| `python -m compileall apps config` | | No errors | Session transcript | |
| Frontend `tsc --noEmit` | `npm --prefix frontend run typecheck` | Clean | Session transcript | |
| Frontend `vitest run` | `npm --prefix frontend run test` | 58 passed (13 files) | Session transcript | +5 new tests (BUG-006 x2, BUG-008 x2, BUG-006/edge-removal x1) over the pre-task 53 |
| Frontend `vite build` | `npm --prefix frontend run build` | Built in 311ms | Session transcript | Matches the repo's Node CI gate order (tsc → vitest → build) |

## Acceptance criteria mapping

Each bug's own "Kabul kriteri" in `TEST-ANALIZ.md` §3, implemented as described in the session
plan; BUG-016 met via a documentation correction (no functional gap exists today per the
report's own finding); BUG-019 explicitly requires no code change (report's own acceptance
criterion is N/A -- no delete UI exists in this build).

## Security requirement mapping

- BUG-003/BUG-015 (grant-on-bind): gated behind the exact same `Capability.
  DOCUMENT_SET_RETRIEVE_GRANT` / `AuthoritySource.DOCUMENT_SET_RESPONSIBILITY` predicate
  `approve_scenario_document_set_access` already enforced; no new capability introduced;
  audited (`scenario_document_set_access.grant_on_bind`).
- BUG-010 (promote confirmation): additive safety gate, fails closed to the pre-existing
  behavior only when there is genuinely no impact; audited denial path
  (`ACTIVE_RELEASES_AFFECTED`).
- BUG-001 (gateway honesty): no new data exposed -- `run.error_code` was already public via
  `GET /v1/runs/{id}`.
- BUG-016: documentation-only; no code/behavior change.

## Authorization tests

Covered per-bug in the phase test additions (see `git diff --stat`); notably
`test_bind_grant_is_noop_without_document_set_manager_authority` (BUG-003 negative path) and
the existing cross-tenant/negative tests in `test_scenario_access.py`, `test_document_acl_console.py`
re-run clean (no regression).

## Cross-tenant tests

No cross-tenant predicate was touched by this task; the full existing cross-tenant test suite
(documents, console, releases, tools) re-ran clean on both SQLite and PostgreSQL.

## Logging and redaction tests

Unaffected; no logging/redaction code was touched. Audit events added (BUG-003/015/018) follow
the existing `record_event`/`_audit` patterns already used by their surrounding modules.

## Audit event tests

New audit actions verified by test: `scenario_document_set_access.grant_on_bind`,
`release.canary_stop` (reason=`superseded_by_promotion`), plus existing `documents.grant.create`
reused for the evaluation-consumer grant.

## Migration verification

One additive migration (`apps/ingestion/migrations/0016_scope_staged_job_checksum_constraint_to_active_states.py`):
narrows `uniq_staged_job_org_request_checksum` from unconditional to active-status-only,
mirroring the existing `uniq_active_staged_index_build` pattern. Narrowing a unique constraint
cannot conflict with existing data (it only relaxes enforcement). Verified via
`makemigrations --check --dry-run` (clean) and the PostgreSQL profile run above (which applies
migrations for real via `--create-db`).

## Behavior comparison with base branch

`test_index_promotion_requires_document_set_manager` (pre-existing) needed a one-line update to
its `promote_staged_index` mock-call assertion (added `confirm_active_release_impact=False`,
BUG-010's new keyword) -- the only pre-existing test whose assertions needed updating for a
signature change; behavior for its actual scenario (no active-release impact) is unchanged.
`test_a_length_mismatch_drops_the_pointers_instead_of_guessing` (BUG-012's prior test) was
renamed and re-scoped to assert the still-true "no wrong attribution" property, plus a new test
asserts the added unattributed-evidence behavior.

## Checks not run

- **Mandatory post-development browser UI/UX/authorization gate** (full role/tenant matrix,
  screenshots): not run in full given the size of this change set (19 findings across 8 apps +
  frontend). A scoped smoke pass is planned next (see final report) covering: bind+grant flow,
  "Sor" idempotent replay, index-promote confirmation, release rollback-of-a-rollback, canary
  stop-on-promote, workflow-builder edge delete, scenario-create duplicate-submit message,
  platform profile form grouping. Recorded here as a **partial/N/A** row per
  `docs/ai/testing-rules.md`'s explicit requirement that a skipped check be named with a reason,
  not silently omitted.
- Live connector/MCP/kill-switch/profile-creation flows: out of scope (see plan's Non-goals).

## Remaining risks

- BUG-005's "recompile now" button and BUG-010's promote-confirmation checkbox add UI surface
  that has not been exercised in a real browser (only via Django test client, which does not
  execute JS/CSS or prove visual layout).
- The evaluation-consumer auto-grant (BUG-015) is scoped to whichever document set is being
  bound; an operator relying on the OLDER manual `document_set_grant_consumer` UI path for other
  consumers is unaffected, but this was not exhaustively cross-checked against every existing
  consumer-grant screenshot in the original QA report.

## Human review required

- Confirm the Turkish user-facing copy (new messages, empty-state text, button labels) reads
  correctly in context -- authored without native-speaker review beyond matching the repo's
  existing tone.
- Browser-gate execution per "Checks not run" above.

## Final status

Implemented and Verified (automated). Not `Completed` per `docs/ai/definition-of-done.md` --
the mandatory browser gate is outstanding (see "Checks not run").
