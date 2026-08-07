# Threat Model: scenario-publishing-ux-realignment

Proportional model. This task adds console authoring/lifecycle surfaces, derives the release
manifest instead of accepting it from the client, lets evaluation execute a **non-active**
release, and reaches a live model for the LLM referee. It adds no production dependency, no
new egress destination and no new credential. The dominant risks are authorization drift on
the new surfaces, a weakened promotion gate, prompt injection into the referee, and
disclosure through evaluation evidence.

## Assets

- Immutable artifacts and the compiled `ScenarioRelease` manifest (integrity: they decide what
  runs and against which model, prompt and documents).
- The promotion gate (`eval_suite` + `EvalRun`): the only automated barrier before traffic.
- Scenario test questions and `QuestionEvaluationRun` evidence (tenant-confidential: they
  contain generated answers and author intent).
- Judge model/prompt artifacts and the `secret:<name>` credential they resolve behind.
- Consumer traffic: which release an alias actually serves.

## Actors

- Scenario Editor: authors the flow, contracts, test questions and candidates.
- Release Manager: the only role that may change what traffic sees.
- Organization/platform administrator: registers `ModelProfile` catalog revisions.
- Hostile or careless cross-tenant user probing the new UUID-addressed console routes.
- **The model itself**, as an untrusted author of text that is fed back into the referee.

## Entry points

- `POST /console/scenarios/id/<uuid>/publish-and-verify/`, `/promote/`, `/test-questions/`
  (session/LDAP + CSRF, tenant-scoped, not the consumer gateway).
- `POST /console/api/builder/drafts/<pk>/publish-and-verify/`, `GET .../release-manifest/derived/`,
  `GET .../node-artifact-library/` (operator JSON API, no bearer path, no CORS).
- `GET /console/question-evaluations/id/<uuid>/` (evaluation report).
- Outbound: the judge's chat call over the existing SSRF-safe `JsonModelEgressClient`
  (profile-id only; a caller can never supply a destination).

## Trust boundaries

- Browser SPA ↔ server: the client stays non-authoritative. `publish-and-verify` performs
  publish → derive → compile → evaluate **server-side**; the client sends no manifest.
- Author input ↔ compiled release: `derive_manifest` reads the published workflow rather than
  accepting operator-chosen roles, and `_assert_workflow_roles_pinned` re-checks at compile
  time. Advice and enforcement read one extractor so they cannot disagree.
- Generated answer ↔ referee: the answer under judgement is model output. It crosses into a
  second model call as *data*.
- Evaluation ↔ served traffic: an evaluation may execute a candidate; it must never make that
  candidate reachable by a consumer.

## Data classifications

- Test questions, expected answers, generated answers: tenant-confidential.
- Judge verdicts: reduced to `pass`/`fail` plus a stable reason code and the model/prompt
  checksums — never the referee's free text.
- Manifest/derived-summary responses: artifact roles, logical ids, versions and checksums.
  Never tool endpoints, manifests or `secret:<name>` values.
- Model credentials: environment-injected, resolved only inside the egress client.

## Authentication

Unchanged. Console session/LDAP + CSRF on every new surface; 401/403 as JSON on the builder
API. No new anonymous route, no new bearer path.

## Authorization

Deny by default, server-side, and deliberately split:

- Authoring (`publish-and-verify`, test questions, judge model, running an evaluation) requires
  exact **Scenario Editor** authority — the same gate as `draft_publish`.
- **Promotion, activation, rollback and canary remain Release Manager only** and are
  unreachable from any authoring endpoint. `scenario_promote` re-checks
  `can_manage_scenario_releases` regardless of what the page rendered.
- Step 6 merges promotion and activation into one operator action. Both were already
  release-manager transitions with their own preconditions and audit events; the authority
  boundary is unchanged, only the number of clicks.
- The judge model may only reference an **active** platform `ModelProfile`; the catalog itself
  is platform-admin-only and unchanged.

## Tenant isolation

Every new query is organization-bound through `_scoped_scenario` / `_resolve_org_in_scope`;
cross-tenant access returns 404 without disclosing existence. `derive_manifest` resolves
artifacts within the scenario's organization, so a foreign tenant holding artifacts with the
*same* logical ids is never pinned — asserted by a test. `QuestionSet.scenario` is nullable so
organization-wide sets keep `scenario=NULL` and remain governed by organization administration.

## External systems

The Gemini-compatible chat endpoint already approved for `RUNTIME_MODEL_PROVIDER`, reached
through the existing SSRF-safe transport (public-unicast only, resolved-IP checks, bounded
size, explicit timeouts, no redirects). No new destination, dependency or credential.
`EVALUATION_LLM_JUDGE_ENABLED` defaults to `false`.

## Abuse cases

- **Prompt injection into the referee.** The answer being judged is model output and can try
  to talk the referee into `pass`. The pinned judge prompt marks the reference data untrusted
  and constrains the reply to two parsable verdicts; anything else is `unscored`, never a pass.
- A Scenario Editor trying to reach traffic by promoting from an authoring endpoint.
- Manifest forgery: pinning a foreign or type-named artifact to smuggle a different prompt,
  model or document set into a release.
- Weakening the promotion gate by routing referee rows into `eval_suite`, making a live model
  call decide whether a release may go live.
- Harvesting another tenant's questions, answers or artifact names through the UUID-addressed
  evaluation report or the node-artifact library.
- Re-running an evaluation in a loop to burn provider quota or budget.
- An evaluation of a candidate leaking into served traffic.

## Failure cases

- Provider unavailable, rate-limited or returning non-JSON: the case is `unscored` with a
  stable reason code, never a silent pass. Observed live as HTTP 429.
- Judge model or prompt unpinned/disabled: readiness reports the exact missing precondition
  and the run is refused rather than started to return `unscored`.
- Compile with a missing node-derived role: fails closed with `workflow_role_unpinned`.
- Promotion with no eval, a stale eval or unready indexes: unchanged fail-closed lifecycle.
- Worker crash mid-run: `.filter()`-based resume skips cases that already have evidence.

## Logging and audit risks

- Audit events exist for draft publish, node-binding publish, release compile, promotion,
  activation, test-question save, judge configuration, question-set publish and run
  start/completion.
- Evidence must carry codes, checksums and counts — never the referee's reasoning text, the
  prompt, the credential or the endpoint. The judge result is reduced at the boundary.
- Console messages surface `error_code` values, which are stable and content-free.

## Mitigations

- The manifest is derived from the published workflow and re-asserted at compile time; one
  shared extractor feeds both, so preflight cannot promise what the compiler rejects.
- The promotion gate stays hermetic: only deterministic `answer_contains` /
  `citations_present` rows reach `eval_suite`; referee rows live in `QuestionSet` and run on
  demand. The editor states this rather than silently downgrading a row.
- Evaluating a candidate uses `execute_release_input`, which runs an exact release without
  serving it. No alias, canary or scenario status is touched.
- The judge prompt is canonical and server-owned (checksummed artifact), not author-written.
- The judge model is deliberately separate from the flow's own model: a model grading its own
  output is a weak check.
- Re-running is deduplicated only while a run is `queued`/`running`, which bounds double-submit
  cost without freezing the measurement.
- Promotion considers only the newest release, so a superseded candidate can never go live.
- `EVALUATION_LLM_JUDGE_ENABLED` is off by default; enabling it is a deployment decision.

## Residual risks

- **Upstream failures are collapsed.** Every non-2xx becomes `UPSTREAM_STATUS` and then
  `WORKFLOW_GENERATION_FAILED`, so an operator cannot distinguish exhausted quota from a bad
  credential or an unknown model. Worse, that code is in `_TRANSIENT_NODE_ERRORS`, so a
  permanent misconfiguration is retried as transient and a 429 is retried into the remaining
  quota. Identified, not fixed — it changes error-code and retry contracts and needs approval.
- Referee verdicts are non-deterministic and unauditable beyond `pass`/`fail`; two runs of the
  same cases may disagree. This is why the referee does not gate promotion.
- `QuestionEvaluationRun` rows written before the aggregation fix store wrong summary counts
  with correct evidence; they were not rewritten.
- The manual manifest path still exists for a scenario with no published workflow. It can no
  longer produce a release that fails at request time, but it remains a raw-identifier surface.
- The mandatory browser gate has not run, so rendered authorization affordances (disabled
  controls, hidden actions) are proven by tests but not by a real browser.

## Required security tests

- Scenario Editor may author and evaluate but receives 403 on promote — asserted.
- Cross-tenant probes on every new route return 404 — asserted.
- A foreign tenant's identically named artifacts are never derived into a manifest — asserted.
- The compile gate rejects type-named roles that previously compiled — asserted as a
  regression test of the released defect.
- The judge prompt constrains the reply to the two parsable verdicts and marks reference data
  untrusted — asserted against the prompt body.
- A non-`scored` judge result never yields a pass; `required` policy forces `unscored`.
- Referee rows never reach `eval_suite`; organization-wide question sets stay untouched.
- Evaluating a candidate changes no release status, alias or scenario lifecycle.
- **Not covered by automated tests:** live prompt-injection resistance of the referee, and
  cross-tenant probing through a real browser session (browser gate).
