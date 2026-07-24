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

- **Task and outcome:** Phase 2.8 Part 3 Gate 2 unified persistence is active; the background
  claim/delivery boundary is implemented and verified; see the
  [Part 3 plan](../tasks/phase-2-8-part-3-unified-workflow-engine/plan.md).
- **Approved scope:** Plan/ADR and additive compiler/runtime/persistence work. Public API,
  authorization and the exact destructive migration/reset remain separate approval gates.
- **Decisions and assumptions:** Preserve ADR-0013 authorization boundaries. Per
  [ADR-0014](../adr/0014-unified-workflow-engine-cutover.md), one workflow engine replaces RAG,
  workflow and agent paths; old local workflow/run data is disposable and will not be converted.
- **Working tree:** HEAD is `edd8ae2` on `feat/foundation-sprint-0-1`; foundation commits are
  `4554e1d` and `df22f9a`. The uncommitted task diff adds `background_claims.py`, additive migration
  `0011`, Run claim fields/constraint, claim-aware transitions, tests and task records. Later commits
  after `df22f9a` are unrelated and must be preserved. Old models/routes/workers remain active.
- **Verification:** See the
  [Part 3 verification record](../tasks/phase-2-8-part-3-unified-workflow-engine/verification.md).
  Latest background claim PostgreSQL suite passes (20, including two-writer ownership, duplicate/
  stale delivery, cancellation/deadline, crash recovery, tenant scoping and audit rollback); affected
  workflow/builder/release regression passes (261); migration drift, focused Ruff and Mypy pass.
- **Runtime:** Full canonical Compose topology is running; PostgreSQL, Redis and MinIO are healthy and
  liveness returns 200. Migrations `0009` through `0011` have not been applied to the live development
  database. Re-check state before any migration, restart, cutover or reset.
- **Risks and blockers:** Exact destructive migration/reset and public API removal are not approved.
  Codebase Memory is callable and the path-matched index reports 10,263 nodes/44,684 edges, but no
  `index_status` endpoint is exposed. Serena, `rg`, direct code/diff and PostgreSQL tests were also
  used. No Celery task is registered; disconnect hooks, scheduling, fleet revision enforcement,
  general recovery tooling and full graph execution remain pending.
- **Next action:** Connect the verified identifier-only delivery/claim boundary to the smallest
  unified Celery executor slice with revision/kill-switch checks; keep public routes and old workers
  unchanged.

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
