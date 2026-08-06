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

1. **Task and outcome:** Continue
   [`scenario-node-bound-authoring-realignment/plan.md`](../tasks/scenario-node-bound-authoring-realignment/plan.md).
   Parts 3, 4 and 5 are implemented and automatically verified; the next reviewable unit is Part 2
   (defaults and navigation) or Part 6 (candidate authority), whichever the owner picks.
2. **Approved scope:** Owner-approved decisions already applied: only `COMPILER_VERSION` moved to
   v6, Retrieve binding is one-way, automatic manifest pinning is deferred, and only
   `chunking_profile` was retired from Studio. Do not start Part 7 retrieval-ownership migration or
   any live-traffic authorization change without a new approval.
3. **Decisions and assumptions:** Workflow DSL stores only server-owned refs; raw bodies stay in
   governed artifact drafts/versions. An unbound Retrieve node seeds from the scenario's active
   release. Chunking is document-set owned and unreachable from Studio, including by direct URL.
   Current scenarios are demo data, so no chunking compatibility allowance was required.
4. **Working tree:** Branch `feat/foundation-sprint-0-1`. Parts 4 and its evidence are committed
   (`e5f1ca1`, `73ae121`, `a4f4b79`). Part 5 is uncommitted at handoff time unless a later commit
   exists: `apps/builder/{api.py,services.py}`, `apps/console/views.py`,
   `apps/builder/tests/{test_api.py,test_services.py}`,
   `apps/console/tests/test_phase_2_8_part_4.py`, the React authoring components and their tests,
   plus the plan/verification records. New file:
   `apps/builder/tests/test_document_set_owned_artifacts.py`. The generated
   `apps/builder/static/builder/` bundle is current and gitignored.
5. **Verification:** Evidence is in
   [`verification.md`](../tasks/scenario-node-bound-authoring-realignment/verification.md).
   Latest: full SQLite 1167 passed / 61 skipped; PostgreSQL `apps/builder`+`apps/console` 356
   passed; frontend typecheck + 50 vitest + production build; ruff/`manage.py check`/
   `makemigrations --check` clean. Browser-gate rows L1-L16 passed live with three operator
   identities. **Outstanding:** the rendered UX rows, which need a real browser.
6. **Runtime:** Canonical Compose roles are running and `/v1/health/live` returned HTTP 200. No
   migration was added by Parts 4 or 5 and no restart is required; re-check live state first.
   Host-run PostgreSQL tests that upload a document need `OBJECT_STORE_ENDPOINT`,
   `OBJECT_STORE_BUCKET` and the MinIO credentials exported, or they fail with
   `STORAGE_PUT_FAILED`.
7. **Risks and blockers:** The rendered UX gate is the only blocker for `Verified`. Repository-wide
   `mypy apps` (3 errors in `apps/builder/tests/test_api.py`) and `ruff format --check apps`
   (`apps/retrieval/providers.py`) were already failing at `88e4e18` and are deliberately untouched.
   Deleting a workflow draft still orphans its node-owned artifact drafts (routed to Part 7).
8. **Next action:** Ask the owner whether to run the rendered UX pass, take Part 2 (defaults and
   navigation), or take Part 6 (candidate authority).

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
