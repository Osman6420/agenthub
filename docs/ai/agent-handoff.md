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

1. **Task and outcome:**
   [`scenario-and-document-authoring-ux/plan.md`](../tasks/scenario-and-document-authoring-ux/plan.md)
   — sixteen owner findings triaged against code and closed; implemented and automatically
   verified. Its predecessor
   [`scenario-publishing-ux-realignment`](../tasks/scenario-publishing-ux-realignment/plan.md)
   is committed (`2c3bccd`, `5139c8b`). Both are `Implemented`, **not `Verified`**: the
   mandatory browser gate has not run for either.
2. **Approved scope:** Delivered scope is recorded in the plan. Two items are identified but
   **not approved and not implemented**: making upstream provider failures readable
   (`UPSTREAM_STATUS` → status class) and fixing their retry classification
   (`WORKFLOW_GENERATION_FAILED` sits in `_TRANSIENT_NODE_ERRORS`, so a bad credential is
   retried forever and a 429 burns the remaining quota). Both change error-code and retry
   contracts. Do not start them without the owner.
3. **Decisions and assumptions:** The release manifest is derived from the published workflow
   and re-asserted at compile time from one shared extractor. The promotion gate stays
   deterministic and hermetic — only `answer_contains` / `citations_present` rows reach
   `eval_suite`. Evaluation measures the newest release the author is working on (a waiting
   candidate first), because judging a candidate *before* promotion is the point. **A stub
   answer may be evaluated but never served**: `_assert_release_gate` refuses to promote or
   canary a generating workflow when `RUNTIME_MODEL_PROVIDER` is unset — a traffic gate, not a
   release-quality gate, because the same release is legitimately evaluated with a stub in CI.
   Governed profile forms read their choices and bounds from `apps/artifacts/governed_dsl`, so
   the form cannot offer what the validator refuses. A published document-set version is a
   starting point: `branch_document_set_version` seeds a draft from it and never mutates it,
   with one open draft at a time.
4. **Working tree:** Branch `feat/foundation-sprint-0-1`. The previous task is committed
   (`2c3bccd`, `5139c8b`); this task is uncommitted at handoff time unless a later commit
   exists. Not pushed. The generated `apps/builder/static/builder/` bundle is gitignored —
   **rebuild it after any frontend change**, because a stale bundle already hid one shipped fix.
5. **Verification:** Evidence is in
   [`verification.md`](../tasks/scenario-and-document-authoring-ux/verification.md). Latest:
   SQLite 1276 passed / 61 skipped; PostgreSQL console/documents/ingestion/releases/evaluations/
   gateway 648 passed / 2 skipped; ruff and `mypy apps` (468 files) clean; frontend tsc + 53
   vitest + build. **No migration in this task.** Outstanding: the browser gate.
6. **Runtime:** Compose is running with `EVALUATION_LLM_JUDGE_ENABLED=true` from the referee
   smoke test; the committed default is `false`. Host-run PostgreSQL tests need `MCP_ENABLED`,
   `METRICS_BEARER_TOKEN` **and** the MinIO variables exported.
7. **Risks and blockers:** The browser gate is the only blocker for `Verified`.
   `MODEL_PROVIDER_NOT_CONFIGURED` keys on the deployment setting, not on whether the pinned
   profile is reachable — a configured but broken provider still promotes and fails at request
   time. The owner's staged-index report is **still unreproduced**: İstanbul set v2 is
   `promotable` with no index, no preparation profile and no build job, and the web log had
   rotated; the rejection path is now instrumented, so a repeat attempt names the failing
   fields. `QuestionEvaluationRun` rows written before the aggregation fix keep wrong summary
   counts with correct evidence; deliberately not rewritten.
8. **Next action:** Run the mandatory browser gate (`manual-testing-guide.md` §10) over both
   tasks together, then reproduce the staged-index button with the owner now that the rejection
   names its cause.

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
