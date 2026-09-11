# Scenario publishing UX realignment

Status: **Implemented**, automated verification complete ([`verification.md`](verification.md)).
The mandatory post-development browser gate has not run, so this is **not yet `Verified`**.

Security boundaries and residual threats: [`threat-model.md`](threat-model.md).

Delivered in three waves against a live owner using the build between waves. Each wave
started from a defect the owner hit, and each defect turned out to be ours.

## Problem

Making a scenario work required seven screens and two returns, and the operator had to
re-select in a manifest panel the artifacts they had just authored inside their workflow
nodes — by raw logical id. Then the chain broke again: publish a candidate, leave to author
an eval suite, come back, bind the suite to a *new* candidate, leave again to run it.

Owner-reported symptom that opened the task: `EvalRun#6` → `status=error`,
`error_code=WORKFLOW_RETRIEVAL_BINDING_INVALID`, `0/1`, no assertion evaluated — displayed as
a **green success message**.

---

## Wave 1 — the manifest should not be retyped

### Root causes (all confirmed in code)

1. `frontend/src/ScenarioManifestPanel.tsx` — `effectiveRole = requiredRole || roles[0] ||
   artifactType`; the normal selection path produced the *type* name as the role, so a
   `retrieve` node referencing `ret_<identity>_profile` was pinned as `retrieval_profile`.
2. `apps/console/views.py` `preset=minimum` never included node-derived roles and assigned
   `role = type`; the panel cleared the requirement list when the preset loaded.
3. `compile_release` never consulted `analyze_workflow_requirements`, so a manifest missing a
   node's required role compiled successfully and only failed at request time.
4. `release_run_eval` — `run_eval` *returns* (not raises) on runtime failure, so
   `except EvalError` was dead code and every outcome hit `messages.success`.
   `EvalRun.error_code` was rendered nowhere.
5. `prepare_scenario_contract_defaults` prepared no `eval_suite`, so a first candidate could
   never pin one, forcing compile → author suite → return → compile a *second* candidate.

### Key insight

The manifest is a pure function of the scenario and its published workflow. Node-owned
artifacts, tool bindings and transform profiles name their artifact's `logical_id` verbatim;
the scenario contracts and eval suite use `scenario_artifact_logical_id`. Nothing required an
operator decision. Reuse of *shared* resources already happens inside the node config, not the
manifest, so deriving the manifest removes no capability.

### Delivered

- **A** `derive_manifest()` (`apps/releases/authoring.py`) + fail-closed
  `_assert_workflow_roles_pinned` in `apps/releases/compiler.py`, both reading one shared
  `workflow_manifest_requirements()` so advice and enforcement cannot drift.
- **B** `eval_suite` added to `prepare_scenario_contract_defaults` (idempotent).
- **C** `publish_and_verify` — publish → derive → compile → evaluate in one operator action.
- **D** The scenario page leads with six ordered, state-badged steps; the remaining operator
  sections moved into a collapsed "Gelişmiş" block.
- **E** Studio landing lists suppressed in scenario context — scenario creation already
  creates the one draft.
- **F** Eval outcome reported at its real severity (`summarize_eval_run`) with `error_code`
  and per-case reason codes rendered.
- **G** Node-owned artifact version history + "bu sürüme dön" / "mevcut profilden kopyala",
  and the missing `transform_profiles` picker.
- **H** The manifest panel becomes a read-only derived summary with human labels.

---

## Wave 2 — the order was right, the destinations were wrong

The owner used the new build: steps 3, 4 and 5 all opened Studio, where nothing said what to
do; the eval suite was still only editable from a release page as raw JSON; promotion sent the
operator to a release page to hunt for a button; and making the scenario callable was a
second, mandatory action hidden under "Gelişmiş".

### Two defects the owner hit, both ours

- **The console generated malformed curl.** `_invocation_guidance` built the chat payload with
  a literal `}}` in a *non*-f-string continuation line, so every copied example carried an
  extra brace and the gateway answered `VALIDATION_ERROR`.
- **Operator questions never reached the workflow.** `ask_scenario_once` and `_answer_case`
  sent `{"question": ...}` while `apps/workflows/runtime._workflow_query` reads
  `input["query"]` and the canonical input contract forbids extra properties. The query was
  always empty, so answers were generic.

### Delivered

- Distinct destinations: step 4 has its own page; steps 5 and 6 are POSTs on the scenario page
  itself, and each result links straight to the candidate or the active release.
- One shared service: `apps/builder/services.publish_and_verify` is called by both the Studio
  API and the console page, so the sequence, audit trail and failure semantics cannot drift.
- Promotion makes the scenario callable. `scenario_promote` promotes and then calls
  `activate_scenario`; both remain governed transitions with their own preconditions and audit
  events, and when activation is refused the page says exactly why.
- Scenario-owned test questions: rows of *question + how the answer is judged* instead of raw
  JSON on a release page, plus `QuestionCase.expected_answer` so the referee sees the author's
  intent.
- Studio is the flow editor: the manifest panel no longer renders in scenario context and the
  AI planner is a collapsed `<details>`.
- `ParseError` is named ("Request body is not valid JSON.") instead of sharing the generic
  contract-failure message.

### Deliberate boundary

The eval suite gates promotion, so it receives **only** deterministic rows (`answer_contains`,
`citations_present`). Exact-match and referee rows live in the scenario's `QuestionSet` and run
on demand — a promotion gate that needs a live model is not a gate. When no row is
deterministic the suite still carries a `workflow_completed` smoke case so the gate is never
left unpinned.

---

## Wave 2 addendum — connecting the LLM referee

The referee was fully implemented and entirely unreachable. `QuestionCase.judge_policy` and
`question_services._judge_case` already worked; four things kept it from ever running:

1. `EVALUATION_LLM_JUDGE_ENABLED` defaults to `False` and was unset in the deployment.
2. No judge prompt artifact existed; `_judge_case` requires a parsable `{"verdict": …}`.
3. No scenario-scoped judge model artifact existed.
4. `console.views.question_set_start_answer` never passed the judge pins, so every run hit
   `JUDGE_NOT_PINNED`.

A fifth was ours: wave 2's readiness check only asked "does an active model profile exist",
which was true in this deployment, so referee mode *looked* available while a run would have
returned `unscored`.

### Delivered

- A canonical, server-owned judge prompt, prepared automatically. It constrains the reply to
  the two parsable verdicts and explicitly treats the reference data as untrusted, because the
  answer under judgement is model output that can try to talk the referee into a verdict.
- A separately selectable judge model pinned per scenario. Deliberately not the flow's own
  model: a model grading its own output is a weak check.
- `judge_readiness()` reports the setting gate, the missing model and the missing prompt as
  distinct reasons — each is a real `_judge_case` failure mode.
- `publish_question_set_version()` extracted so the organization-wide path keeps its
  organization-administration gate while the scenario path uses scenario-editor authority.
- `EVALUATION_LLM_JUDGE_ENABLED` added to compose (web *and* worker-eval) and `.env.example`,
  defaulting to `false`.

---

## Wave 3 — evaluation could not evaluate

The owner published six candidates, each with a passing eval, and still could not get their
two test questions to pass. Four defects compounded.

1. **The referee could only measure what was already in production.**
   `start_judged_evaluation` hard-selected `status=ACTIVE`, so an author had to promote a fix
   to production *before* being allowed to test whether the fix worked. `execute_release_input`
   already runs an exact release without requiring it to be served, exactly as the promotion
   gate's `eval_suite` does — only the query was wrong.
2. **Step 6 reported "done" while the fix sat unpromoted.** `state` was `"done"` whenever
   *any* release was active, so the page showed a green ✓ to an operator whose corrected
   candidate was waiting. No promote audit event was recorded across six publishes.
3. **A finished evaluation stood in for every later one.** The idempotency key was permanent,
   so clicking "evaluate" again resolved to the first run and the operator was redirected to
   the old report forever.
4. **Every worker-executed run reported 0 passed.** `execute_question_evaluation_task` loads
   the run with `prefetch_related("case_evidence")` **before** any case runs, so the related
   manager caches an empty list; `_aggregate_run` read that cache and wrote
   `completed_cases=0`, `passed_cases=0` and null metrics onto every completed run. Confirmed
   live: two evidence rows `passed`, run summary `0/2`.

### Delivered

- `judge_target_release(scenario)` — the newest release the author is working on: a waiting
  candidate when there is one, the active release once it has been promoted. Fails closed with
  `RELEASE_REQUIRED`. The page names the target instead of leaving it implicit.
- Re-running measures again; deduplication covers only a run still `queued`/`running`, which
  bounds double-submit cost without freezing the measurement.
- Step 6 stays open while a candidate waits and says the live behaviour has not changed yet.
- `_pending_release` shared by the page and the promote action, so promotion can never reach
  back to a superseded candidate.
- `_aggregate_run` queries the evidence table, not the related manager.
- An evaluation report states its run time, short id and measured release, and a
  scenario-owned run breadcrumbs back to its scenario.

---

## Deliberate scope decisions

- The compile gate requires every **workflow-derived** role; additional pins (release-level
  fallbacks, scenario contracts) remain allowed, so legacy releases still compile.
- The manual manifest path remains for a scenario with no published workflow. It can no longer
  produce a broken release because the compile gate rejects a role mismatch.
- Reverting to an older artifact version republishes the old body *forward* as a new immutable
  version; no mutation, no pinning of a superseded version.
- Step 6 merges promotion and activation. This changes the earlier stated principle that
  "release promotion does not automatically activate the scenario"; the **authority** boundary
  is unchanged (both were already release-manager transitions) and the owner asked for it
  explicitly.

## Authorization

Unchanged. Authoring (`publish-and-verify`, test questions, judge configuration, running an
evaluation) requires exact Scenario Editor authority. Promotion, rollback, canary and scenario
activation remain release-manager-only and are unreachable from any authoring endpoint.

## Out of scope

- Adding an LLM referee to `eval_suite` itself: the promotion gate stays deterministic and
  hermetic.
- Binding real model/embedding profiles: a deployment decision, not this task.
- Making upstream provider failures readable (`UPSTREAM_STATUS` → status class) and fixing
  their retry classification. Identified during wave 3, recorded in `threat-model.md` as a
  residual risk; it changes error-code and retry contracts and needs owner approval.
