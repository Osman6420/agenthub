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
   [`scenario-publishing-ux-realignment/plan.md`](../tasks/scenario-publishing-ux-realignment/plan.md)
   — all three waves plus the LLM-referee addendum are implemented and automatically verified.
   The task is `Implemented`, **not `Verified`**: the mandatory browser gate has not run.
2. **Approved scope:** Delivered scope is recorded in the plan. Two items are identified but
   **not approved and not implemented**: making upstream provider failures readable
   (`UPSTREAM_STATUS` → status class) and fixing their retry classification
   (`WORKFLOW_GENERATION_FAILED` sits in `_TRANSIENT_NODE_ERRORS`, so a bad credential is
   retried forever and a 429 burns the remaining quota). Both change error-code and retry
   contracts. Do not start them without the owner.
3. **Decisions and assumptions:** The release manifest is derived from the published workflow,
   never accepted from the client, and re-asserted at compile time from one shared extractor.
   The promotion gate stays deterministic and hermetic — only `answer_contains` /
   `citations_present` rows reach `eval_suite`; exact-match and referee rows live in the
   scenario's `QuestionSet`. Evaluation measures the newest release the author is working on
   (a waiting candidate first), because judging a candidate *before* promotion is the point.
   Step 6 merges promotion and activation at the owner's explicit request; the authority
   boundary is unchanged (both were already release-manager transitions) and this supersedes
   the earlier "promotion does not auto-activate" wording.
4. **Working tree:** Branch `feat/foundation-sprint-0-1`, commit `2c3bccd` (50 files). Clean
   except for this documentation restructure. Not pushed. The generated
   `apps/builder/static/builder/` bundle is current and gitignored.
5. **Verification:** Evidence is in
   [`verification.md`](../tasks/scenario-publishing-ux-realignment/verification.md). Final:
   SQLite 1254 passed / 61 skipped; PostgreSQL evaluations/console/releases/builder 498 passed;
   ruff and `mypy apps` (466 files) clean; frontend tsc + 52 vitest + build. Additive migrations
   `evaluations.0004`/`0005`. **Outstanding:** the browser gate, and live prompt-injection
   resistance of the referee.
6. **Runtime:** `evaluations.0004`/`0005` are applied to the live Compose database. Compose is
   currently running with `EVALUATION_LLM_JUDGE_ENABLED=true` because of the referee smoke
   test; the committed default in `.env.example` and compose is `false`. Host-run PostgreSQL
   tests need `MCP_ENABLED`, `METRICS_BEARER_TOKEN` **and** the MinIO variables exported —
   omitting the latter fails one document test with `STORAGE_PUT_FAILED`, which is not a
   regression.
7. **Risks and blockers:** The browser gate is the only blocker for `Verified`. The compile gate
   is a fail-closed tightening: a GitOps pack relying on type-named roles for a node-bound
   workflow now fails with `workflow_role_unpinned` (intended; no active release is
   re-validated). Referee verdicts are non-deterministic, which is why they do not gate
   promotion. `QuestionEvaluationRun` rows written before the aggregation fix keep wrong
   summary counts with correct evidence; they were deliberately not rewritten. Owner-environment
   side effects are listed at the end of the verification record.
8. **Next action:** Run the mandatory browser gate
   (`manual-testing-guide.md` §10) over the scenario page's six steps, the test-questions page
   (target-release label, judge panel), step 6 with a waiting candidate, and the evaluation
   report heading — with matched permitted/forbidden identities and cross-tenant probes. Then
   close the task record and archive the plan per planning policy.

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
