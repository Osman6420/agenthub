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

Current task: [AgentHub combined development](../tasks/Agent_Hub_MD/plan.md).
The owner approved security and transition closure. Dependency updates, zero-finding
Python/frontend audits, image/CI lock constraints and local main DB transition are
complete. The task's top section owns evidence, backup/restore rehearsal, tests and
remaining external-environment boundaries. Do not request dependency approval again.

Main local console is port 8000; canonical Update applied all migrations without a
reset. Verify live state per the manual before further operations. The isolated
acceptance stack on 8110 now uses agenthub-security:20260911. Preserve both databases,
object stores and the private .tmp backup. No external production cutover occurred;
legacy index layout remains compatible. Do not repeat passed suites without a change.
Global completion is withheld for the explicit remaining environment limits, not for
unfinished dependency fixes. Large preexisting dirty tree remains uncommitted.

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
