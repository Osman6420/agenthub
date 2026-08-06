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

1. **Task and outcome:** Continue Part 4 Retrieve-node binding in
   [`scenario-node-bound-authoring-realignment/plan.md`](../tasks/scenario-node-bound-authoring-realignment/plan.md).
   The reviewable unit is per-node structured retrieval authoring through DSL, release requirements,
   runtime and immutable artifact publication; it is implemented and automatically verified, and is
   awaiting only the mandatory authenticated browser gate.
2. **Approved scope:** Finish Part 4 only. Preserve legacy release-level retrieval fallback when a
   node binding is absent, fail closed for an explicit missing/invalid role, and keep exact Scenario
   Editor write authorization. Do not start defaults/navigation, document-set cleanup, candidate
   authority or live-traffic authorization changes.
3. **Decisions and assumptions:** Workflow DSL stores only server-owned
   `retrieval_profile_ref`; raw profile JSON remains in governed artifact drafts/versions. Multiple
   Retrieve nodes use deterministic independent roles. Compiler contract is bumped from v5 to v6 so
   stale background claims cannot resume. See the task plan and threat model.
4. **Working tree:** Branch `feat/foundation-sprint-0-1`, last clean commit `88e4e18`. Part 4 is
   uncommitted. Modified files are `apps/builder/{api.py,services.py,urls.py}`,
   `apps/orchestration/{rag_steps.py,tests/test_rag_steps.py}`,
   `apps/releases/authoring.py`, `apps/workflows/{compiler.py,models.py,runtime.py,
   tests/test_generate_binding.py}`, `frontend/src/{Editor.tsx,api.ts,
   components/NodeConfigPanel.tsx,types.ts,useBuilder.ts,__tests__/node_config_panel.test.tsx}`
   and the task plan/verification records. Untracked:
   `apps/workflows/tests/test_retrieve_binding.py` and
   `apps/builder/tests/test_retrieve_node_binding.py`. Preserve all of these changes. The generated
   `apps/builder/static/builder/` bundle is current and gitignored.
5. **Verification:** Evidence is in
   [`verification.md`](../tasks/scenario-node-bound-authoring-realignment/verification.md).
   Automated verification is complete: full SQLite 1165 passed / 61 skipped; PostgreSQL affected
   suites 380 passed; frontend typecheck + 49 vitest + production build; ruff/`manage.py check`/
   `makemigrations --check` clean for this slice. An authenticated platform-admin live session
   covered the L1–L10 authorization/route rows. **Still outstanding:** matched editor/auditor
   identity pairing (their passwords were not available) and the human UX/rendering rows.
6. **Runtime:** Canonical Compose roles are running and `/v1/health/live` returned HTTP 200. The new
   retrieve-binding route answers JSON HTTP 401 unauthenticated, so the URLconf is live. This slice
   adds no migration and requires no restart; re-check live state before relying on it.
7. **Risks and blockers:** The browser gate is the blocker for `Verified`. Repository-wide
   `mypy apps` (3 errors in `apps/builder/tests/test_api.py`) and `ruff format --check apps`
   (`apps/retrieval/providers.py`) were already failing at `88e4e18` and are deliberately untouched.
   A bound Retrieve node cannot be unbound from the UI. Do not mutate a live scenario to verify.
8. **Next action:** Close the remaining browser-gate rows with a signed-in Scenario Editor and a
   matched viewer/auditor plus a rendered UX pass on the Retrieve node panel; the server-side
   authorization rows already passed live as platform admin.

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
