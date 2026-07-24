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

- **Task and outcome:** Phase 2.8 Part 3 Gate 2 unified persistence/state machine is active; see the
  [Part 3 plan](../tasks/phase-2-8-part-3-unified-workflow-engine/plan.md).
- **Approved scope:** Plan/ADR and additive compiler/runtime/persistence work. Public API,
  authorization and the exact destructive migration/reset remain separate approval gates.
- **Decisions and assumptions:** Preserve ADR-0013 authorization boundaries. Per
  [ADR-0014](../adr/0014-unified-workflow-engine-cutover.md), one workflow engine replaces RAG,
  workflow and agent paths; old local workflow/run data is disposable and will not be converted.
- **Working tree:** Part 3 plan/ADR, compiler v5, gated `agent_loop`, release pins, shared agent
  policy and tool-free workflow adapter are committed at `4554e1d`. The current uncommitted Gate 2
  slice adds migration `0010`, transition-token/checksum idempotency, cooperative cancellation and
  bounded sync-lease expiry resolution; old models/routes/workers remain active. Exclude unrelated
  Codebase Memory repair files and any user-owned `.codebase-memory/`, `.worktrees/` or Celery Beat
  schedule files.
- **Verification:** See the
  [Part 3 verification record](../tasks/phase-2-8-part-3-unified-workflow-engine/verification.md).
  Full workflow/builder affected package passes (254); release/workflow regression passes (211);
  latest agent/workflow regression passes (297); PostgreSQL unified Run/RLS/idempotency/cancellation/
  lease checks pass (13, including concurrent duplicate-token replay); Gate 2 affected regression
  passes (253); migration drift, focused Ruff and Mypy pass; focused frontend tests pass (5) and
  TypeScript typecheck passes.
- **Runtime:** Full Compose topology is running; PostgreSQL, Redis and MinIO report healthy.
  Migration `0010` has not been applied to the live development database. Re-check pending old work
  before any cutover or reset.
- **Risks and blockers:** Exact destructive migration/reset and public API removal are not approved.
  Codebase Memory transport closed during the latest call and exposed no callable freshness-status
  endpoint, so this slice was cross-checked with Serena, `rg`, code, migrations and PostgreSQL tests.
  Disconnect hooks, lease scanning/recovery tooling and worker/API integration remain pending.
- **Next action:** Design and implement the smallest background executor claim/delivery boundary
  using the unified transition token and checkpoint CAS; do not connect public routes yet.

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
