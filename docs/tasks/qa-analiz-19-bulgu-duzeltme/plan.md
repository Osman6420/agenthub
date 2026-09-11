# Task Plan: qa-analiz-19-bulgu-duzeltme

## Task summary

Fix all 19 verified findings (BUG-001..019) from the QA report at
`D:\Masaüstü\Agent Hub\agenthub-transfer-2026-08-19\agenthub\TEST-ANALIZ.md`, run against a
transfer copy of this repository (2026-08-28..31). Re-verified against this repo
(`feat/foundation-sprint-0-1`) on 2026-09-01: all 19 still apply.

## Background

See TEST-ANALIZ.md §1-§7 for the full seven-round QA narrative, per-bug root-cause analysis,
and §4 for the report's own fix-priority order. Owner decisions (this session): fix all 19
findings; for BUG-003/BUG-015 use option (a) — the "bind" action grants retrieval access
directly for an actor who already holds `document_set_manager` authority, rather than building
a separate request/approve console flow.

## Scope

BUG-001 through BUG-015 get code changes. BUG-016 gets a documentation-only correction.
BUG-017, BUG-018 get code changes. BUG-019 gets no code change (report's own acceptance
criterion is N/A — no delete UI exists to trigger it); it is recorded here as a design input
for any future scenario/document-set delete feature.

## Non-goals

- Live connector (Confluence/REST) egress, live MCP invoke, kill-switch live triggering, live
  model/embedding profile creation — the QA report itself deferred these pending owner approval;
  out of scope here.
- Plaintext API keys in `deploy/compose/.env` — an ops/secret-manager concern, not a code fix.
- Extending duplicate-submit protection (BUG-002's pattern) to every other console "create" form
  — scoped to `scenario_create`, the one the report demonstrated live.
- BUG-009's endpoint-field consolidation (scheme/host/port/path → one URL field) — kept to
  template/form grouping only, no model/schema change.

## Acceptance criteria

Each bug's own "Kabul kriteri" in TEST-ANALIZ.md, as scoped above.

## Affected components

apps/documents, apps/ingestion, apps/gateway, apps/console, apps/evaluations, apps/releases,
apps/tools (docs only), frontend/src (builder SPA).

## Data impact

BUG-004 requires converting `StagedIndexBuildJob`'s org+checksum unique constraint to a
partial/conditional index (active statuses only) — additive, no data rewrite, no risk to
existing rows (see migration impact).

## Security impact

BUG-003/015 change authorization-adjacent behavior: binding a document set to a scenario now
also grants retrieval (`ScenarioDocumentSetGrant` + a `DocumentSetGrant` for the synthetic
`system:evaluation` consumer) when the actor already holds `document_set_manager` capability.
No new capability is introduced; the grant is created under the same capability check
`approve_scenario_document_set_access` already uses. Owner-approved (option a).

## Authorization impact

See above. All other fixes are UI/UX/error-handling/data-integrity; no other authorization
predicate changes.

## Observability impact

BUG-003/015/018/017 grant/lifecycle changes are audited via the existing `record_event`/
`_audit` patterns already used by their surrounding services.

## Migration impact

One additive migration (`apps/ingestion`) for BUG-004's conditional unique constraint.

## Dependencies

None blocking; BUG-003 and BUG-015 are implemented together (same call site).

## Implementation steps

See phased plan (Faz A-E) recorded in this session; summarized per-bug fix approach in
TEST-ANALIZ.md itself plus the session's plan file. Each phase: implement -> targeted tests ->
ruff/mypy/makemigrations --check -> next phase. Final: full SQLite suite, PostgreSQL profile for
affected apps, frontend build+vitest, then rebuild/restart the local stack.

## Test plan

Per-bug targeted tests listed against each fix; full repository gates at the end (see
`docs/ai/testing-rules.md`). The mandatory post-development browser gate is run as a scoped
smoke pass only (not the full role/tenant matrix) given the size of this change set — recorded
as a partial/N/A row with reason, not silently skipped.

## Rollout plan

Local environment only in this task; rebuild via `.\scripts\local-stack.ps1` at the end.

## Rollback plan

Standard git revert; the migration is additive/reversible (constraint narrowing).

## Risks

Faz A touches authorization-adjacent grant creation and a DB constraint — highest scrutiny.
Full risk list to be finalized in the closing report.

## Open questions

None outstanding; see AskUserQuestion answers earlier in this session.

## Status

Implemented and Verified (automated). See `verification.md` for full evidence; the mandatory
post-development browser gate is outstanding, so this is not yet `Completed`.

## Completion criteria

Per `docs/ai/definition-of-done.md`. Met: acceptance criteria implemented with test evidence;
security/authorization review done inline (see `verification.md`); formatter/linter/type-check/
unit/integration/migration checks passed on SQLite and PostgreSQL; final diff reviewed. Not yet
met: the mandatory browser UI/UX/authorization gate (recorded as a named, reasoned gap, not a
silent omission).
