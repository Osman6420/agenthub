# Coding Agent Handoff

Use this file only when unfinished work moves between Codex, Claude Code, or
another coding agent. It is a short transition record, not project history and
not a substitute for task plans, code, tests, or verification evidence.

## Sources of truth

- Intended and in-progress work: `docs/tasks/<task-id>/plan.md`.
- Security boundaries and residual threats: the task `threat-model.md`.
- Checks already run and remaining verification: the task `verification.md`.
- Implemented behavior: the live code, configuration, migrations, and tests.
- Cross-task status, only when needed: `docs/planning/master-plan.md`.

Link to these sources instead of copying their contents here.

For local application startup, shutdown, service health, and logs, follow
`docs/manual-testing-guide.md` section 0 and the authoritative service topology in
`deploy/compose/docker-compose.yml`. Check live state with the commands there; do
not store general startup instructions or assumed service status in this handoff.

## Active handoff

1. **Task and outcome:** All delivery parts of
   [`scenario-node-bound-authoring-realignment/plan.md`](../tasks/scenario-node-bound-authoring-realignment/plan.md)
   (2, 3, 4, 5, 6, 7, 8A) are implemented and automatically verified. The task is complete except
   for the rendered UX rows of the mandatory browser gate.
2. **Approved scope:** Every owner decision is applied and recorded in the plan. Nothing further is
   approved; a new unit needs its own scope.
3. **Decisions and assumptions:** Node-bound authoring owns prompt, model and retrieval; chunking is
   document-set owned; query-time retrieval is node owned with document-set pins kept as historical
   provenance; contract defaults are canonical, closed and idempotent; candidate preparation and
   evaluation are authoring work while every traffic transition stays release-manager-only.
4. **Working tree:** Branch `feat/foundation-sprint-0-1`. Parts 4, 5, 2 and 6 are committed
   (`e5f1ca1` … `e25b506`). Part 7 is uncommitted at handoff time unless a later commit exists.
   The generated `apps/builder/static/builder/` bundle is current and gitignored.
5. **Verification:** Evidence is in
   [`verification.md`](../tasks/scenario-node-bound-authoring-realignment/verification.md).
   Latest: full SQLite 1187 passed / 61 skipped; PostgreSQL builder/console/documents/ingestion/
   releases 634 passed / 2 skipped with `ingestion.0014` applied to a fresh database; ruff clean
   repository-wide; mypy reports only 3 pre-existing `test_api.py` errors. Browser-gate rows L1–L16
   passed live. **Outstanding:** the rendered UX rows, which need a real browser.
6. **Runtime:** `ingestion.0014` has been applied to the live Compose database and the column is
   nullable with every existing pin retained. Compose roles are running and `/v1/health/live`
   returned HTTP 200 after a web-only restart. Host-run PostgreSQL tests that upload a document need
   `OBJECT_STORE_ENDPOINT`, `OBJECT_STORE_BUCKET` and the MinIO credentials exported.
7. **Risks and blockers:** The rendered UX gate is the only blocker for `Verified`. Reversing
   `ingestion.0014` restores `NOT NULL` and only succeeds while no preparation profile has a null
   retrieval profile. Repository-wide `mypy apps` still reports 3 pre-existing errors in
   `apps/builder/tests/test_api.py`. Scenarios created before Part 2 have no prepared contract
   defaults; no backfill was run.
8. **Next action:** Run the rendered UX pass over the document-set, scenario, Studio and release
   pages, then close the task record and archive the plan per planning policy.

When a transition is required, replace the sentence above with a compact record
containing only:

1. **Task and outcome:** task-plan link and the current acceptance criterion or
   reviewable unit.
2. **Approved scope:** what may change and any approval gates or excluded work.
3. **Decisions and assumptions:** only choices the receiving agent must preserve
   or verify; link durable decisions to their ADR or plan.
4. **Working tree:** changed/untracked files relevant to the task, intentional
   exclusions, and commit/branch reference when applicable.
5. **Verification:** verification-record link, latest relevant results, and checks
   still pending. Distinguish implementation, automated verification, and manual
   verification.
6. **Runtime:** only running services, required restarts/migrations, or other
   ephemeral facts that affect the next action.
7. **Risks and blockers:** unresolved security, authorization, data, operational,
   or compatibility concerns.
8. **Next action:** one concrete, bounded step for the receiving agent.

Do not add completed-sprint narratives, commit diaries, copied architecture,
credentials, tokens, cookies, secrets, personal data, or stale runtime output.

## Transition procedure

The yielding agent must:

1. Update the task plan, threat model, and verification record first.
2. Write the active handoff from those current sources.
3. Inspect `git status` and the relevant diff; identify unrelated local changes
   so the next agent does not overwrite them.
4. State whether work is committed and whether services require restart or
   migrations.

The receiving agent must not trust the snapshot blindly. Before editing, it must:

1. Read the linked task records and repository instructions.
2. Re-run `git status`, inspect the relevant diff, and verify the branch/commit.
3. Re-check any runtime fact needed for the next action.
4. Stop and update the plan if live state contradicts the handoff.

After the transition is accepted or the task is complete, replace the active
handoff with the "No active agent transition" sentence. Durable outcomes belong
in the task verification record, architecture documentation, or an ADR.
