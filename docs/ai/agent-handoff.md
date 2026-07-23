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
  Slices 1–3 are implemented: central operator capabilities and Global Administrator; delegated
  project/scenario/document-set assignments; scenario-to-document-set request/grant/revocation
  with compile-time and live retrieval enforcement.
- **Approved scope:** The owner approved every Part 2.1 product decision plus authorization and
  additive migrations on 2026-07-23. Slice 4 may migrate release/existing endpoint predicates.
  Slice 5 owns Access UI and superadmin alert/runbook/compatibility cleanup. Do not remove legacy
  roles until the plan's cleanup gate is met.
- **Decisions and assumptions:** Preserve
  [`ADR-0013`](../adr/0013-scoped-operator-capabilities-and-superadmin-recovery.md): administrative
  authority does not imply document content; only an assigned Document Set Manager grants scenario
  retrieval; binding is configuration; live grant revocation immediately blocks new retrieval.
- **Working tree:** Phase planning is committed at `c17e5ca`; Part 2.1 Slices 1–3 are the current
  `feat(auth): add scoped operator authorization foundations` HEAD. Exclude unrelated concurrent changes in `AGENTS.md`,
  `CLAUDE.md`, `.cbmignore`, `docs/tasks/codebase-memory-developer-tooling/`, `.worktrees/` and
  Celery Beat schedule files.
- **Verification:** See
  [`verification.md`](../tasks/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery/verification.md).
  Latest passing evidence includes identity 27 tests, documents 53 tests, pinning/ACL/orchestration
  35 tests, cached-bundle runtime 11 tests, focused request/grant 6 tests, migration/RLS 3 tests,
  Ruff, Mypy, migration drift and Django system check. Full repository and browser/accessibility
  suites remain pending.
- **Runtime:** The local Compose stack was healthy before implementation. Migrations
  `identity.0007`, `identity.0008` and `documents.0006` have not been applied to the persistent
  local database; no restart was performed.
- **Risks and blockers:** Legacy console/API predicates and binding UI remain. Runtime is
  fail-closed without a live scenario grant, but Slice 4–5 must migrate callers and UX. Superadmin
  MFA, high-severity alerting and recovery runbook are not production-ready.
- **Next action:** Start Slice 4 by inventorying every `can_manage_releases`, `release_manager` and
  endpoint-level `is_superuser` caller, then migrate one bounded release lifecycle path to the
  central capability service with denial, cross-tenant and audit-failure tests.

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
