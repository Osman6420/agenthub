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

- **Task and outcome:** No incomplete Part 2.1 unit. The task is completed and archived in the
  [`Phase 2.8 Part 2.1 plan`](../planning/archive/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery-2026-07-24/plan.md).
- **Approved scope:** Part 2.1 authorization, additive migrations, Access UX and superadmin
  recovery controls are closed. Start a new active handoff before Part 3 implementation.
- **Decisions and assumptions:** Preserve
  [`ADR-0013`](../adr/0013-scoped-operator-capabilities-and-superadmin-recovery.md): administrative
  authority does not imply document content; only an assigned Document Set Manager grants scenario
  retrieval; binding is configuration; live grant revocation immediately blocks new retrieval.
- **Working tree:** Slice 4 is committed at `1729510`; Slice 5 closes in the next commit.
  Exclude unrelated concurrent changes in `AGENTS.md`,
  `CLAUDE.md`, `.cbmignore`, `docs/tasks/codebase-memory-developer-tooling/`, `.worktrees/` and
  Celery Beat schedule files.
- **Verification:** See
  [`verification.md`](../planning/archive/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery-2026-07-24/verification.md).
  Slice 4 evidence includes 29 release-focused, 37 document-operation, 13 tool-authorization,
  315/317 identity-release-ingestion-tools and 168 console tests passing; two expected
  off-PostgreSQL guards skipped. Slice 5 Access evidence includes 20 focused and 170 console tests,
  Ruff, Mypy, Django check, migration drift and diff check passing. Browser visual/accessibility
  inspection is pending because no browser backend is available.
- **Runtime:** The complete local Compose topology is running. PostgreSQL, Redis and MinIO are
  healthy; web liveness returns HTTP 200. Migrations `identity.0007`, `identity.0008` and
  `documents.0006` are applied to the persistent local database.
- **Risks and blockers:** Live visual browser inspection was unavailable. Stored legacy role values
  remain readable for compatibility but cannot be selected in ordinary membership forms.
  Phishing-resistant MFA is deferred to Phase 3 by owner decision on 2026-07-24.
- **Next action:** Create a fresh handoff for Phase 2.8 Part 3 before implementation.

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
