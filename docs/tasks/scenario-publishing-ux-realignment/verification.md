# Verification — scenario publishing UX realignment

Date: 2026-08-07. Branch: `feat/foundation-sprint-0-1`. Commit: `2c3bccd`.

The numbers below are the **final** state of the branch after wave 3. Per-wave runs during
development are summarised under "Wave history" and are superseded by these.

## Static checks

| Command | Result |
| --- | --- |
| `.venv\Scripts\ruff.exe format --check apps` | pass |
| `.venv\Scripts\ruff.exe check apps` | `All checks passed!` |
| `.venv\Scripts\mypy.exe apps` | `Success: no issues found in 466 source files` |
| `.venv\Scripts\python.exe manage.py check` | no issues |
| `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` | `No changes detected` |
| `.venv\Scripts\python.exe -m compileall apps config` | pass |

Secret scan over the staged diff (`AIza`, `sk-…`, password/key assignments): clean. The
generated `apps/builder/static/builder/` bundle is gitignored and was not committed.

## Tests — SQLite (`config.settings.test`)

Full suite: **1254 passed, 61 skipped**, 0 failed (235s).

## Tests — PostgreSQL (`config.settings.local`, `--create-db`, pgvector Compose)

Scope `apps/evaluations apps/console apps/releases apps/builder`:
**498 passed, 0 failed** (517s).

Required environment for this profile: `MCP_ENABLED=true`, a non-empty
`METRICS_BEARER_TOKEN`, **and** the MinIO variables `OBJECT_STORE_ENDPOINT=http://localhost:9000`,
`OBJECT_STORE_BUCKET=agenthub`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY=minioadmin`.
Omitting the MinIO variables fails one document test with `STORAGE_PUT_FAILED` — an
environment omission, not a regression (`OBJECT_STORE_ENDPOINT` defaults to empty in
`config/settings/base.py`). This cost one wasted investigation during wave 1 and is recorded
here so it is not repeated.

## Frontend (Node v20 / npm 10)

| Command | Result |
| --- | --- |
| `tsc --noEmit` | pass |
| `vitest` | **52 passed** (12 files) |
| `vite build` | pass |

## Migrations

`evaluations.0004_questionset_scenario` (nullable FK) and
`evaluations.0005_questioncase_expected_answer` (blank CharField). Both additive; existing
organization-wide question sets keep `scenario=NULL`, asserted by a test.

## New and changed tests

- `apps/releases/tests/test_derived_manifest.py` (5) — derivation satisfies every required
  role; the derived manifest compiles; **the released defect is a regression test** (type-named
  roles now raise `workflow_role_unpinned` instead of compiling); missing artifacts are
  reported in author language without leaking the derived role; a foreign tenant's artifacts
  with the *same* logical ids are never resolved.
- `apps/builder/tests/test_publish_and_verify.py` (10) — one call publishes, compiles and
  evaluates; the default suite removes the second-candidate round trip; missing artifacts are
  reported without creating a candidate; viewer denied (403); cross-tenant denied (404); never
  promotes; stale revision rejected (409); derived manifest reports pins; node artifact library
  serves history/copy sources; library denies a viewer.
- `apps/console/tests/test_scenario_setup_steps.py` (3) — steps render in journey order with
  honest state; a Scenario Editor sees authoring actions but the promote control is disabled;
  cross-tenant 404.
- `apps/console/tests/test_scenario_step_actions.py` (10) — steps no longer share a
  destination; publish-and-verify runs in place and links the candidate; promoting also
  activates; promotion without a candidate says so; test questions round-trip; **a Scenario
  Editor may author but gets 403 on promote**; cross-tenant 404; every generated curl example
  parses as JSON; **a waiting candidate keeps step 6 open**; **promotion never reaches back to
  a superseded candidate**.
- `apps/evaluations/tests/test_scenario_question_payload.py` (9) — the question lands on the
  key the runtime reads and satisfies the contract; a stub-only provider is refused.
- `apps/evaluations/tests/test_scenario_test_questions.py` (23) — only deterministic rows reach
  the gate; a suite is never empty; saving publishes both consumers; organization-wide sets are
  untouched; a referee row keeps its expected answer; the judge prompt constrains the reply to
  the two parsable verdicts and marks the data untrusted; **the referee is shown the author's
  expected answer** (asserted against the real `_judge_case` call arguments); readiness reports
  the setting gate and the missing model as distinct reasons; **evaluation targets a candidate
  over the active release**, never a superseded one, and fails closed with no release; **an
  in-flight run absorbs a double submit while a finished one never stands in for a new
  measurement**.
- `apps/evaluations/tests/test_question_sets.py` (+1) — **the worker's exact prefetching load
  path still aggregates the evidence it just wrote**. The pre-existing test passed because it
  executed a run that had not been prefetched, which is why the defect was invisible.
- `apps/gateway/tests/test_canonical_api.py` (+2) — malformed JSON is named as such.
- Updated to intended new behaviour (**not weakened**): `test_scenario_contract_defaults.py`
  (defaults cover all three scenario-scoped roles — 2→3 by design), `test_evaluations.py`
  (an `error` run is not reported as a pass ratio), `test_scenario_setup_steps.py` (step 6's
  label states that it also activates), `toolbar.test.tsx`, `app_deeplink.test.tsx`,
  `test_phase_2_8_part_1.py`, `test_phase_2_8_part_4.py`.

## Live evidence (running Compose stack, owner's organization)

**Wave 1 — the reported defect repaired.** Scenario `ilksenaryo-rhkvva6ffs`: `derive_manifest`
→ `ok=True`, pinning the artifacts under the roles the workflow nodes actually reference
(release 33 had pinned the same artifacts as `retrieval_profile` / `prompt_template` /
`model_profile`). Compiled candidate **#34**; `run_eval` → `Eval geçti: 1/1`, `error_code=''`.
Release 33 untouched; no promotion or traffic change.

**Judge — real provider, both verdicts.** Scenario `tekrardene-fde7b4hx5f` with a catalog
profile over the shared SSRF-safe transport:

```
readiness BEFORE: ready=False "Hakem modeli seçilmemiş."   AFTER: ready=True
wrong answer -> {"status":"scored","verdict":"fail","reason_code":"JUDGE_FAIL", model+prompt checksums}
right answer -> {"status":"scored","verdict":"pass","reason_code":"JUDGE_PASS", …}
```

`status=scored` proves the path end to end: the model was called, the reply parsed, and the
verdict recorded with provenance. The referee both rejects and accepts correctly.

**Wave 3 — a candidate measured without promoting.** Active release stayed at #38 throughout:

```
target: 44 candidate
result: completed | 2 / 2 passed | completed 2 | unscored 0 | errors 0
metrics: judge_pass_rate 1.0, answer_pass_rate 1.0, judge_denominator 1, answer_denominator 2
```

Re-verified through the exact console code path after the re-run fix (run 8, distinct from the
stale run 3), and two consecutive operator clicks produced two independent runs with different
generated answers — confirming they were real, separate model calls.

**Environment side effects left in place** (owner's data, not test fixtures): scenario
`ilksenaryo` and `tekrardene` each carry a `QuestionSet`, `judge_model` and `judge_prompt`
artifact; two `ModelProfile` catalog revisions were registered
(`external-demo-gemini-judge` r1/r2) via the supported `register_model_profile` command;
`QuestionEvaluationRun` 1–3 keep the wrong summary counts written by the pre-fix aggregation
(evidence rows are correct and were not rewritten).

## Wave history (superseded)

| Wave | SQLite | PostgreSQL |
| --- | --- | --- |
| 1 | 1209 passed / 61 skipped | 657/657 across affected apps once MinIO was configured |
| 2 | 1240 passed / 61 skipped | 706 passed |
| 2 addendum (judge) | 1247 passed / 61 skipped | 492 passed |
| 3 (final) | **1254 passed / 61 skipped** | **498 passed** |

## Not run / open

- **Mandatory browser gate** (`manual-testing-guide.md` §10) — the blocker for `Verified`.
  Processes 1–3 must be exercised in a browser with before/after click counts, matched
  permitted and forbidden identities, same-tenant cross-scope and cross-tenant probes, direct
  URL/POST checks, visible affordance parity, and a console and network error review. It now
  also covers the wave-3 surfaces (test-questions target label, step 6 with a waiting
  candidate, the evaluation report heading).
- Live prompt-injection resistance of the referee is untested; only the prompt's constraints
  and the `unscored` fallbacks are asserted.
- Redis and MinIO remain unexercised by the automated suite (pre-existing).

## Residual risks

Recorded in [`threat-model.md`](threat-model.md#residual-risks). The material ones:

- Upstream provider failures are collapsed into one code and a permanent misconfiguration is
  retried as transient. Identified and **not fixed** — it changes error-code and retry
  contracts and needs owner approval.
- The compile gate is a fail-closed tightening: any GitOps pack or `compile_release` invocation
  that relied on type-named roles for a node-bound workflow now fails with
  `workflow_role_unpinned`. Intended; the diagnostic names the role and node. No existing
  active release is re-validated.
- Referee verdicts are non-deterministic, which is why they do not gate promotion.
- Legacy scenarios holding more than one `WorkflowDraft` fall back to the org-wide Studio
  listing and still use the manual manifest panel.
