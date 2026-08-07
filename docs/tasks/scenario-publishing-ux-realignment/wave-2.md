# Wave 2 — closing the broken chain

Status: Implemented. Automated verification below; the mandatory post-development browser
gate remains outstanding for both waves.

## Why

Wave 1 put the scenario journey into six ordered steps, but the owner found the order right
and the destinations wrong: steps 3, 4 and 5 all opened Studio, where nothing said what to
do; the eval suite was still only editable from a release page as raw JSON; promotion sent
the operator to a release page to hunt for a button; and making the scenario callable was a
second, mandatory action hidden under "Gelişmiş".

## Two defects the owner hit, both ours

**The console generated malformed curl.** `_invocation_guidance` built the chat payload with
a literal `}}` in a *non*-f-string continuation line, so every copied example carried an
extra brace and the gateway answered `VALIDATION_ERROR`. Payloads are now built with
`json.dumps`, and a test parses every generated example as JSON.

**Operator questions never reached the workflow.** Both `ask_scenario_once` and
`_answer_case` sent `{"question": ...}` while `apps/workflows/runtime._workflow_query` reads
`input["query"]` and the canonical input contract forbids extra properties. The query was
always empty, so answers were generic. Now built by
`question_services.scenario_question_payload`, with a test that asserts against the exact
runtime accessor and the contract.

## Delivered

- **Distinct destinations.** Step 4 has its own page; steps 5 and 6 are POSTs on the scenario
  page itself, and each result links straight to the candidate or active release.
- **One shared service.** `apps/builder/services.publish_and_verify` owns publish → derive →
  compile → evaluate; the Studio API and the console page both call it, so the sequence,
  audit trail and failure semantics cannot drift.
- **Promotion makes the scenario callable.** `scenario_promote` promotes and then calls
  `activate_scenario`. Both remain governed transitions with their own preconditions and
  audit events — `activate_scenario` still requires an active release, an active alias and
  served indexes — and when activation is refused the page says exactly why. "Gelişmiş" now
  only stops or reopens calls.
- **Scenario-owned test questions.** `/console/scenarios/id/<uuid>/test-questions/` edits rows
  of *question + how the answer is judged*: "cevap şunu içermeli", "cevap birebir bu olmalı",
  or "LLM hakem değerlendirsin", plus an optional citation requirement.
- **The referee actually sees the expectation.** `QuestionCase.expected_answer` (additive
  migration) carries the author's expected answer into `_judge_case`'s context. Without it a
  judge row round-tripped as empty and the referee was judging against nothing.
- **Studio is the flow editor.** The manifest panel no longer renders in scenario context,
  the AI planner is a collapsed `<details>`, and the header states what the page is for and
  links back to the scenario.
- **Malformed JSON is named.** `ParseError` now answers "Request body is not valid JSON."
  instead of sharing the generic contract-failure message.
- **A stub answer is refused.** With a generating workflow and no `RUNTIME_MODEL_PROVIDER`,
  the console one-off question errors instead of presenting deterministic placeholder text as
  the scenario's answer. Scoped to that operator surface: the runtime default and CI
  hermeticity are unchanged.

## Deliberate boundary

The eval suite gates promotion, so it receives **only** the deterministic rows
(`answer_contains`, `citations_present`). Exact-match and referee rows live in the scenario's
`QuestionSet` and run on demand — a promotion gate that needs a live model is not a gate. The
editor states this rather than silently downgrading a row. When no row is deterministic the
suite still carries a `workflow_completed` smoke case so the gate is never left unpinned.

`QuestionSet.scenario` is nullable: organization-wide sets keep `scenario=NULL` and are
untouched, which a test asserts.

## Verification

| Gate | Result |
| --- | --- |
| `ruff format --check apps`, `ruff check apps` | pass |
| `mypy apps` | `Success: no issues found in 466 source files` |
| `manage.py check` | no issues |
| `manage.py makemigrations --check --dry-run` | `No changes detected` (two additive migrations committed) |
| pytest, SQLite full suite | **1240 passed, 61 skipped** |
| pytest, PostgreSQL (releases/builder/evaluations/console/workflows/gateway) | **706 passed, 0 failed** (738s) |
| frontend `tsc --noEmit` / `vitest` / `vite build` | pass / **52 passed** / pass |

Migrations added: `evaluations.0004_questionset_scenario`,
`evaluations.0005_questioncase_expected_answer` — both additive and nullable/blank.

### New tests

- `apps/evaluations/tests/test_scenario_question_payload.py` (9) — the question lands on the
  key the runtime reads and satisfies the contract; an explicit case envelope still wins;
  generating workflows are detected; a stub-only provider is refused, a configured one is not,
  and a non-generating release needs none.
- `apps/evaluations/tests/test_scenario_test_questions.py` (12) — only deterministic rows
  reach the gate; a suite is never empty; citations carry through; saving publishes both
  consumers; an identical body mints no version; rows round-trip; a referee row keeps its
  expected answer; organization-wide sets are untouched; invalid rows get stable codes.
- `apps/console/tests/test_scenario_step_actions.py` (8) — steps no longer share a
  destination and step 6 stays disabled until there is a candidate; publish-and-verify runs
  in place and links the candidate; promoting also activates; promotion without a candidate
  says so; test questions save and round-trip; **a Scenario Editor may author but gets 403 on
  promote**; cross-tenant gets 404; every generated curl example parses as JSON.
- `apps/gateway/tests/test_canonical_api.py` (+2) — malformed JSON is named as such; a
  well-formed but invalid body keeps its own message.

Updated to intended new behaviour (not weakened): `test_scenario_setup_steps.py` (step 6's
label now states that it also activates).

## Open

- **Mandatory browser gate** (`manual-testing-guide.md` §10) for waves 1 and 2 together:
  processes 1–3 in a browser, before/after click counts, matched permitted and forbidden
  identities, same-tenant cross-scope and cross-tenant probes, console/network review.
- The LLM referee was unreachable at the time of writing; see the addendum below, which
  connects it and verifies it live.
- Redis and MinIO remain unexercised by the automated suite (pre-existing).

---

# Addendum — connecting the LLM referee

## What was actually missing

The referee was fully implemented and entirely unreachable. `QuestionCase.judge_policy` and
`question_services._judge_case` (pinned judge model + judge prompt, `pass`/`fail` verdict,
`unscored` on provider failure) already worked; four things kept it from ever running:

1. `EVALUATION_LLM_JUDGE_ENABLED` defaults to `False` (`config/settings/base.py:135`) and was
   unset in the deployment, so `_validate_judge_profiles` raised `JUDGE_DISABLED`.
2. No judge prompt artifact existed. `_judge_case` json-parses the reply and requires
   `{"verdict": "pass"|"fail"}`; anything else is `unscored`.
3. No scenario-scoped judge model artifact existed.
4. **`console.views.question_set_start_answer` never passed
   `judge_model_profile`/`judge_prompt_contract`**, so every run hit `JUDGE_NOT_PINNED`.

A fifth problem was mine: wave 2's `judge_ready` only checked "an active model profile
exists", which is true in this deployment, so referee mode looked available while a run
would have returned `unscored`.

## Delivered

- **Canonical judge prompt** (`scenario_questions.JUDGE_PROMPT_TEMPLATE`), prepared
  automatically — no JSON authoring. It constrains the reply to the two parsable verdicts and
  explicitly treats the reference data as untrusted, because the answer under judgement is
  model output that can try to talk the referee into a verdict.
- **A separate, selectable judge model**, pinned per scenario as
  `scenario-<hex>-judge_model`. Deliberately not the flow's own model: a model grading its own
  output is a weak check, and keeping them apart lets a stronger referee be bound later.
- **Honest readiness.** `judge_readiness()` reports the setting gate, the missing model and
  the missing prompt as distinct reasons — each is a real `_judge_case` failure mode.
- **A run action.** `start_judged_evaluation()` freezes the scenario's question set into an
  immutable version and starts an answer evaluation against the **active** release with both
  judge artifacts pinned, failing closed with a named precondition otherwise.
- **One publish implementation, two authorization surfaces.**
  `publish_question_set_version()` was extracted so the organization-wide path keeps its
  organization-administration gate while the scenario path uses scenario-editor authority.
- **Deployment gate** added to `deploy/compose/docker-compose.yml` (web *and* worker-eval —
  evaluation runs in Celery) and documented in `.env.example`, defaulting to `false`.

## Live verification (real Gemini)

Compose restarted with `EVALUATION_LLM_JUDGE_ENABLED=true`; both `web` and `worker-eval`
confirmed to carry it. Against scenario `ilksenaryo-rhkvva6ffs` (active release 37) with the
`external-demo-gemini` catalog profile (`gemini-3.6-flash`):

```
judge readiness BEFORE: ready=False  "Hakem modeli seçilmemiş."
judge readiness AFTER : ready=True
run 1 → completed
evidence: status=failed
          judge={'status': 'scored', 'verdict': 'fail', 'reason_code': 'JUDGE_FAIL',
                 'model_checksum': '8933570…', 'prompt_checksum': '234dc19…'}
generated answer: 186 chars (non-empty)
```

`status=scored` is the proof the path works end to end: the model was called, the reply
parsed, and the verdict recorded with model and prompt checksums for provenance. The `fail`
verdict is a genuine judgement of a deliberately loose smoke question, not an error. The
non-empty generated answer also confirms the wave-2 query fix live.

**Side effects on the owner's scenario** from this smoke test, left in place: a `QuestionSet`
with one referee row (published as version 1), `judge_model` v1, `judge_prompt` v1, and
`eval_suite` v3 (the referee-only row is not deterministic, so the suite fell back to the
`workflow_completed` smoke case).

## Verification

| Gate | Result |
| --- | --- |
| `ruff format --check apps`, `ruff check apps` | pass |
| `mypy apps` | `Success: no issues found in 466 source files` |
| `manage.py check`, `makemigrations --check --dry-run` | no issues / `No changes detected` |
| pytest, SQLite full suite | **1247 passed, 61 skipped** |
| pytest, PostgreSQL (evaluations/console/releases/builder) | **492 passed, 0 failed** (1223s) |

The PostgreSQL profile needs the MinIO variables as well as `MCP_ENABLED`/`METRICS_BEARER_TOKEN`
(`OBJECT_STORE_ENDPOINT`, `OBJECT_STORE_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`);
omitting them fails one document test with `STORAGE_PUT_FAILED`, which is an environment gap and
not a regression.

New tests (`apps/evaluations/tests/test_scenario_test_questions.py`, +8): the setting gate is
reported before anything else; a missing model is reported before claiming ready; pinning a
model also prepares the canonical prompt; an inactive catalog profile is refused; re-pinning
the same model mints no version; the prompt constrains the reply to the two parsable
verdicts and marks the data untrusted; **the referee is shown the author's expected answer**
(asserted against the real `_judge_case` call arguments).

## Open

- The referee reached `scored` live, but only for one case on one scenario. Broader behaviour
  (multi-case runs, `required` vs optional judge policy, provider timeouts producing
  `unscored`) is covered by unit tests, not by live traffic.
- `EVALUATION_LLM_JUDGE_ENABLED` is currently on only because the smoke test restarted Compose
  with it. It is `false` by default in `.env.example` and must be set deliberately per
  environment; a referee run makes billable model calls.
- The mandatory browser gate (`manual-testing-guide.md` §10) still covers waves 1–2 and now
  this addendum.

---

# Wave 3 — evaluation could not evaluate

## Why

The owner published six candidates, each with a passing eval, and still could not get their
two test questions to pass. Three defects compounded, and the first one inverted the purpose
of the feature.

**1. The referee could only measure what was already in production.**
`start_judged_evaluation` hard-selected `status=ACTIVE`. So an author had to promote a fix to
production *before* being allowed to test whether the fix worked, and a corrected candidate
could not be measured at all. Evaluation exists to judge a candidate **before** it goes live.
`execute_release_input` already runs an exact release without requiring it to be served —
the same way the promotion gate's `eval_suite` does — so nothing but the query was wrong.

**2. Step 6 reported "done" while the fix sat unpromoted.**
`state` was `"done"` whenever *any* release was active. The page therefore showed a green ✓
and "Aktif release #38." to an operator whose corrected candidate #44 was waiting, so the
candidate was never promoted and every live call kept using the old release. No promote
audit event was ever recorded across six publishes — the step simply did not look actionable.

**3. A finished evaluation stood in for every later one.**
The idempotency key was `scenario-judge:<scenario>:<cases-checksum>` — permanent. Clicking
"evaluate" again resolved to the first run, and `execute_question_evaluation` returns early
for a terminal run, so the operator was redirected to the *old* report forever. Fixing the
flow, re-publishing, or changing the judge model (none of which are release-pinned) all
returned the original verdict unchanged. Idempotency belongs on the double-submit, not on the
measurement.

**4. Every worker-executed run reported 0 passed.**
`tasks.execute_question_evaluation_task` loads the run with
`prefetch_related("case_evidence")` **before** any case runs, so the related manager caches an
empty list. `_aggregate_run` read `run.case_evidence.all()` — that cache — and wrote
`completed_cases=0`, `passed_cases=0` and null metrics onto every completed run, no matter
what the evidence rows said. Confirmed live: two evidence rows `passed`, run summary `0/2`.
The resume check on the same manager uses `.filter(...)`, which bypasses the cache, so
idempotent resume was never affected — only the summary the operator reads.

## Delivered

- **`judge_target_release(scenario)`** — the newest release the author is working on: a
  waiting candidate when there is one, the active release once it has been promoted. Fails
  closed with `RELEASE_REQUIRED` when the scenario has no release at all. The test-questions
  page names the target ("Aday #44 üzerinde çalışır") instead of leaving it implicit.
- **Re-running measures again.** A run is deduplicated only while one for the same scenario
  and release is still `queued`/`running` — that is what a double submit produces, and each
  case costs a billable model call. A *finished* run is history, not an answer.
- **Step 6 stays open while a candidate waits**, and says why: "Aday #44 hazır ama yayında
  #38 var. Yayına almadan canlı davranış değişmez."
- **`_pending_release`** is shared by the page and the promote action. Promotion previously
  took the newest *candidate*, which after a promotion is a superseded one — it would have
  put stale work live. Only the newest release counts, and only when it is not already served.
- **`_aggregate_run` queries the table**, not the related manager.
- **The report says which run it is.** Two consecutive evaluations rendered identically —
  no timestamp, no run identity, no measured release — so a fresh measurement was
  indistinguishable from the stale one the operator had just been looking at. The heading now
  carries the run time, a short run id and a link to the release it measured, and a
  scenario-owned run breadcrumbs back to its scenario instead of the organization-wide
  question-set list.

## Verification

| Gate | Result |
| --- | --- |
| `ruff format --check apps`, `ruff check apps` | pass |
| `mypy apps` | `Success: no issues found in 466 source files` |
| pytest, SQLite full suite | **1254 passed, 61 skipped** (235s) |
| pytest, PostgreSQL (evaluations/console/releases/builder) | **498 passed, 0 failed** (517s) |

Live evidence, owner's scenario `tekrardene-fde7b4hx5f`, **without promoting** (active stayed
at #38 throughout):

```
target: 44 candidate
result: completed | 2 / 2 passed | completed 2 | unscored 0 | errors 0
metrics: judge_pass_rate 1.0, answer_pass_rate 1.0, judge_denominator 1, answer_denominator 2
  case 0 -> passed | judge: pass
  case 1 -> passed | normalized_contains: True
```

New tests: the referee targets a candidate over the active release, never targets a
superseded candidate, and fails closed with no release; an in-flight run absorbs a double
submit while a finished one never stands in for a new measurement; step 6 reopens for a
waiting candidate and names the active one; promotion refuses a superseded candidate; and the
worker's exact prefetching load path still aggregates the evidence it just wrote.

**Runs written before this wave keep their wrong summaries.** `QuestionEvaluationRun` 1–3 in
the owner's environment store `0 passed` with intact, correct evidence rows. They are
persisted, audited reports and were not rewritten; the next evaluation produces a correct one.

## Field finding — upstream failures are unreadable (not fixed)

The owner's first judged run with real questions failed both cases with
`WORKFLOW_GENERATION_FAILED`. The cause was the provider, not this work: Gemini answered **429
`RESOURCE_EXHAUSTED`**, quota `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, value **20/day
per model**. Reproduced 3/3 against the live profile; a different model id on the same key
answered 200, confirming the quota is per model. A judged case costs two calls (answer +
verdict), so a shared profile drains one bucket twice as fast.

Two real defects surfaced while diagnosing it. Neither is fixed here, because both change error
codes and retry classification, which are compatibility surfaces:

1. **The cause never reaches the operator.** `apps/tools/http_adapter.py:98` collapses every
   non-2xx into `UPSTREAM_STATUS`, and `apps/workflows/runtime.py:153` collapses that into
   `WORKFLOW_GENERATION_FAILED`. "Quota exhausted", "bad API key" and "unknown model" are
   indistinguishable on screen. Carrying the *status class* (429 / 401-403 / other) is safe —
   it is neither body, URL nor secret.
2. **A permanent failure is retried as transient.** `WORKFLOW_GENERATION_FAILED` is in
   `_TRANSIENT_NODE_ERRORS` (`apps/workflows/unified_executor.py:101`), so a wrong API key is
   retried indefinitely and a 429 is retried into the remaining quota.

A third, product-level gap: a candidate whose model was fixed does nothing until it is promoted.
The owner corrected the generate node, published two passing candidates, and still saw the old
failure because the console one-off question and the judged run both execute the **active**
release. The scenario page states the active release, but nothing connects "my fix passed" to
"my fix is not live yet".
