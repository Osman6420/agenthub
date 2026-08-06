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
   Parts 2, 3, 4, 5, 6 and 8A are implemented and automatically verified. The remaining reviewable
   unit is Part 7 (cleanup and additive retrieval-ownership migration).
2. **Approved scope:** Owner-approved decisions already applied: only `COMPILER_VERSION` moved to
   v6; Retrieve binding is one-way; automatic manifest pinning is deferred; only `chunking_profile`
   was retired from Studio; and Part 6's authorization change was explicitly approved. Part 7's
   data-touching migration needs its own rollout/rollback review before it starts.
3. **Decisions and assumptions:** Workflow DSL stores only server-owned refs. An unbound Retrieve
   node seeds from the scenario's active release. Chunking is document-set owned and unreachable
   from Studio. Contract defaults are canonical and closed, prepared at scenario creation, and
   idempotent. Candidate preparation and evaluation are authoring work; every traffic transition
   stays release-manager-only.
4. **Working tree:** Branch `feat/foundation-sprint-0-1`. Parts 4, 5 and 2 are committed
   (`e5f1ca1`, `73ae121`, `a4f4b79`, `b37ea6a`, `459c4ff`). Part 6 is uncommitted at handoff time
   unless a later commit exists: `apps/builder/api.py`, `apps/console/views.py`,
   `apps/console/templates/console/release_detail.html`, plus
   `apps/console/tests/test_candidate_authority.py` and the plan/verification records. The generated
   `apps/builder/static/builder/` bundle is current and gitignored.
5. **Verification:** Evidence is in
   [`verification.md`](../tasks/scenario-node-bound-authoring-realignment/verification.md).
   Latest: full SQLite 1182 passed / 61 skipped; PostgreSQL console/builder/releases/evaluations 432
   passed; ruff, mypy (3 pre-existing errors only), `manage.py check` and `makemigrations --check`
   clean. Live matched-identity probes passed for both the retrieve-binding route and the new
   candidate authority. **Outstanding:** the rendered UX rows, which need a real browser.
6. **Runtime:** Canonical Compose roles are running and `/v1/health/live` returned HTTP 200 after a
   web-only restart. No migration was added by Parts 2, 4, 5 or 6. Host-run PostgreSQL tests that
   upload a document need `OBJECT_STORE_ENDPOINT`, `OBJECT_STORE_BUCKET` and the MinIO credentials
   exported, or they fail with `STORAGE_PUT_FAILED`.
7. **Risks and blockers:** The rendered UX gate is the only blocker for `Verified`. Repository-wide
   `mypy apps` (3 errors in `apps/builder/tests/test_api.py`) and `ruff format --check apps`
   (`apps/retrieval/providers.py`) were already failing at `88e4e18` and are deliberately untouched.
   Deleting a workflow draft still orphans its node-owned artifact drafts. Scenarios created before
   Part 2 have no prepared contract defaults; no backfill was run.
8. **Next action:** Ask the owner whether to start Part 7 (with its migration rollout/rollback plan),
   fix the orphaned artifact-draft defect, or run the rendered UX pass.

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
