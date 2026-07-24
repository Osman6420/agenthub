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

- **Task and outcome:** Continue
  [`Phase 2.8 Part 2.1`](../tasks/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery/plan.md).
  Slices 1–4 are implemented and automatically verified. Scenario releases, exact document-set
  operations and tool platform-role resolution now use the central capability service; the broad
  legacy release predicate is removed.
- **Approved scope:** The owner approved every Part 2.1 product decision plus authorization and
  additive migrations on 2026-07-23. Slice 4 may migrate release/existing endpoint predicates.
  Slice 5 owns Access UI and superadmin alert/runbook/compatibility cleanup. Do not remove legacy
  roles until the plan's cleanup gate is met.
- **Decisions and assumptions:** Preserve
  [`ADR-0013`](../adr/0013-scoped-operator-capabilities-and-superadmin-recovery.md): administrative
  authority does not imply document content; only an assigned Document Set Manager grants scenario
  retrieval; binding is configuration; live grant revocation immediately blocks new retrieval.
- **Working tree:** Phase planning is committed at `c17e5ca`; Part 2.1 Slices 1–3 are the current
  `feat(auth): add scoped operator authorization foundations` HEAD and Slice 4 is uncommitted.
  Exclude unrelated concurrent changes in `AGENTS.md`,
  `CLAUDE.md`, `.cbmignore`, `docs/tasks/codebase-memory-developer-tooling/`, `.worktrees/` and
  Celery Beat schedule files.
- **Verification:** See
  [`verification.md`](../tasks/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery/verification.md).
  Slice 4 evidence includes 29 release-focused, 37 document-operation, 13 tool-authorization,
  315/317 identity-release-ingestion-tools and 168 console tests passing; two expected
  off-PostgreSQL guards skipped. Ruff, Mypy, Django check, migration drift and diff check pass.
  Full repository and browser/accessibility suites remain pending.
- **Runtime:** The complete local Compose topology is running. PostgreSQL, Redis and MinIO are
  healthy; web liveness returns HTTP 200. Migrations `identity.0007`, `identity.0008` and
  `documents.0006` are applied to the persistent local database.
- **Risks and blockers:** Slice 5 Access UI and compatibility cleanup remain. Superadmin MFA,
  high-severity alerting and recovery runbook are not production-ready. Legacy role values remain
  in schemas and disposable-demo seed data but no Slice 4 runtime release predicate consumes them.
- **Next action:** Start Slice 5 with the responsive Access UI and superadmin alert/runbook, then
  remove legacy role choices only after the plan's reset and rollback gate is verified.

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
