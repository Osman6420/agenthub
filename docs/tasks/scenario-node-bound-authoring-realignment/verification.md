# Verification: scenario-node-bound-authoring-realignment

## Part 8A — document-set authority correction

### Automated evidence

- `pytest apps/console/tests/test_document_workspace_console.py -q`: 8 passed.
- The matched authorization test proves an exact Document Set Manager with no scenario binding can
  inspect, create and version preparation artifacts, while a bound Scenario Editor with only
  document-set metadata visibility receives HTTP 403 and creates no version.
- The same test rejects a foreign-tenant source artifact without disclosure, proves immutable N+1
  publication and records safe success/denial audit events.
- Ruff format/check passed for the changed Python files. Mypy passed for the new document profile
  authoring service and console views. Django system check, JavaScript syntax and diff whitespace
  checks passed.

### Live/runtime evidence

- Canonical Compose inspection showed PostgreSQL, Redis, MinIO, web, all three worker roles and beat
  running; `/v1/health/live` returned HTTP 200 after a controlled web-only restart.
- The live document-set page displayed new inline artifact cards. Opening the selected chunking
  profile showed editable content, required exact-version description and immutable publish action.
- The obsolete bound-scenario author message was absent. No live artifact version was published.

### Security and operational review

- Server authorization uses exact `DOCUMENT_SET_OPERATIONS_MANAGE` against the requested set. A
  scenario assignment is never consulted and cannot grant this operation.
- Source artifacts are re-resolved by exact organization and allowlisted type. Request bodies are
  bounded, canonical validators run before persistence, active model-profile references are checked,
  and endpoint/secret-bearing platform fields are never accepted or projected.
- Artifact creation and success audit share one transaction. Denials are audited separately without
  artifact body, prompt text, profile endpoint or secret data.

### Residual items

- Retrieval still appears in document-set preparation during the compatibility period. Moving its
  primary ownership into Retrieve-node DSL/runtime remains Part 8D.
- The retained same-origin cross-tab notification is compatibility-only now that document-owned
  primary editing is inline; later cleanup may remove it after node-bound migration.

## Part 3 — Generate-node binding

### Automated evidence

- `pytest apps/builder/tests apps/workflows/tests/test_generate_binding.py
  apps/releases/tests/test_authoring.py -q`: 103 passed.
- `npm test`: 11 files / 45 tests passed; `npm run typecheck` passed.
- Ruff format/check passed for `apps/builder`; targeted mypy passed for the changed service and API.
- Tests prove two Generate nodes receive distinct deterministic roles, release requirements preserve
  each role/type pair, identical bodies reuse the latest immutable version, and a prompt-only change
  creates only that prompt's N+1 version.
- Matched API tests prove exact Scenario Viewer read/deny, Scenario Editor write, foreign-tenant 404,
  stale revision 409 and inactive-model rollback with no partial artifact draft.

### Runtime and UI evidence

- The current frontend bundle was built into the Django static builder output.
- Compose showed PostgreSQL, Redis, MinIO, web, runtime/ingestion/eval workers and beat running;
  `/v1/health/live` returned HTTP 200.
- Browser navigation reached the local operator login page, but the browser session was not signed
  in. No credentials were read or entered, so the authenticated Generate panel remains a manual
  visual check.

### Security and operational review

- GET requires exact scenario visibility; PUT requires exact Scenario Editor authority and a current
  workflow revision. Server code re-resolves the node, active platform model and tenant/scenario
  artifact lineage; the UI never submits or receives provider endpoint/secret fields.
- Workflow body plus prompt/model drafts save in one transaction. Workflow publication validates and
  publishes changed node artifacts in the workflow publication transaction, and audit failure remains
  fail-closed.
- Legacy/custom refs and absent bindings remain readable and are not auto-published. Saving through
  the new node editor deliberately migrates that node to its server-owned stable roles.

### Residual items

- Candidate manifest assembly still asks the release journey to pin the exact artifacts required by
  the generated roles; default/automatic candidate selection belongs to the later defaults and
  candidate-authority delivery slices.
- Retrieve-node binding, document-set inline authoring and live visual confirmation remain open.

## Part 3 follow-up — live route and non-JSON response handling

- Live logs identified the exact failing request as
  `/console/api/builder/drafts/6/generate-nodes/generate/binding/`: the running process returned an
  HTML 404 because its file watcher had stopped before loading the new URLconf.
- The current frontend client now converts HTML/malformed responses into a stable
  `unexpected_response` error carrying the HTTP status instead of leaking a `JSON.parse` exception.
- The builder asset cache key was advanced. Targeted Vitest coverage proves HTML 404 and structured
  JSON errors are both handled correctly; typecheck and production bundle build passed.
- Only the Compose `web` role was restarted/recreated. Health returned HTTP 200 and an
  unauthenticated request to the exact Generate-binding URL returned JSON HTTP 401
  `authentication_required`, proving the route is active. No database, volume, worker or artifact
  state was reset.
- The root watcher error recurred after a plain restart, so the canonical Compose web command now
  watches only `/app/apps` and `/app/config` rather than traversing unrelated worktrees/caches. The
  recreated role reported those exact watch roots and no subsequent watcher error.

## Part 3 follow-up — PostgreSQL workflow-row lock

- The first authenticated Generate-binding PUT reached the new route but PostgreSQL rejected
  `select_for_update().select_related("project", "scenario")`: both relations are nullable and the
  generated outer join attempted to lock its nullable side.
- The transaction now locks only the authoritative `WorkflowDraft` row. Related objects are resolved
  separately inside the same transaction, retaining stale-revision and tenant/scenario checks.
- Ruff format/check passed. The Generate-binding suite passed in both the standard test profile
  (`2 passed`) and a real PostgreSQL disposable test database (`2 passed`).
- The bounded live watcher detected `apps/builder/services.py`, reloaded the web child successfully,
  and `/v1/health/live` remained HTTP 200. No live scenario mutation was issued during verification.

## Part 4 — Retrieve-node binding (implemented; automated verification complete)

### Locked decisions

- Only `COMPILER_VERSION` moves to `workflow-compiler/v6`. `COMPILED_WORKFLOW_API_VERSION` stays at
  `agenthub/compiled-workflow/v5` so already-compiled releases keep executing (acceptance criterion
  7), while `background_claims` — which compares `COMPILER_VERSION` — refuses to resume any claim or
  checkpoint produced under the old retrieve semantics.
- An unbound Retrieve node seeds its editor from the scenario's **active release** retrieval profile,
  so saving without edits preserves current behavior instead of silently applying client defaults.
- Binding is one-way, matching Part 3: there is no "return to release fallback" action.
- Automatic candidate/manifest pinning of the generated retrieval roles stays out of scope and
  belongs to the later defaults/candidate-authority slices.

### Automated evidence

- `pytest apps/builder/tests/test_retrieve_node_binding.py`: 4 passed (new file).
- `pytest apps/builder apps/workflows apps/releases apps/orchestration apps/console`:
  625 passed, 11 skipped (PostgreSQL-only) — the `v5`→`v6` compiler bump broke no fixture or
  assertion.
- Full SQLite suite `pytest`: **1165 passed, 61 skipped**.
- PostgreSQL profile (`config.settings.local`, `--create-db`, Compose PostgreSQL) for
  `apps/builder apps/workflows apps/releases apps/orchestration`: **380 passed, 0 skipped** —
  the workflow-row `select_for_update` path in `save_retrieve_node_binding` holds on real
  PostgreSQL.
- Frontend: `npm run typecheck` passed; `npm test` 12 files / **49 passed** (two new Retrieve panel
  tests); `npm run build` produced the current Django static bundle.
- `ruff format --check` and `ruff check` pass for every file changed by this slice;
  `manage.py check` reported no issues and `makemigrations --check --dry-run` detected no changes
  (this slice adds no migration).

### What the tests prove

- Two Retrieve nodes receive distinct deterministic `ret_*` roles, publish independent immutable
  retrieval profiles, and a change to one node creates an N+1 version only for that node's role.
- Republishing an unchanged draft creates no new artifact version.
- Release dependency extraction requires an exact `retrieval_profile` artifact for each bound role;
  an unbound node adds no requirement and keeps the release-level fallback.
- A legacy/custom `retrieval_profile_ref` is still required by the extractor but is never
  auto-versioned by the builder, so release-manager pins are not overwritten.
- The editor seeds from the active release while unbound, switches to node-owned content once
  bound, and leaves the sibling node reading the release profile.
- API: foreign-tenant GET/PUT 404, viewer GET 200 with `can_write=false`, viewer PUT 403, stale
  revision 409, invalid profile body 400 `candidate_invalid_artifact` with no artifact draft
  persisted, and an authorized save that writes only the server-owned role into the node config.
- Frontend: the retrieval editor renders server-seeded values, never exposes the manifest role as an
  author field, submits the edited body, and is read-only for a viewer.

### Live evidence

- Compose reported PostgreSQL, Redis, MinIO, web, all three workers and beat running;
  `/v1/health/live` returned HTTP 200.
- An unauthenticated request to the new `/console/api/builder/drafts/<id>/retrieve-nodes/<node>/
  binding/` route returned a JSON **HTTP 401** (not an HTML 404), proving the URLconf is live in the
  running process. No draft, artifact, release or scenario state was mutated.

### Authenticated live session (2026-08-06)

Run against the current build with a signed-in platform-admin operator session on the local Compose
stack. Credentials were supplied by the owner for this run only and are not recorded here.

| # | Check | Result |
| --- | --- | --- |
| L1 | `/console/` and `/console/builder/` while signed in | HTTP 200 both |
| L2 | Retrieve binding GET on an unbound node | HTTP 200, canonical seed profile, `configured=false`, `can_write=true`; no endpoint, secret or platform-model field in the payload |
| L3 | PUT with a stale revision | HTTP 409, no state change |
| L4 | PUT with `top_k=500` (outside the canonical bound) | HTTP 400, no artifact draft persisted |
| L5 | Authorized PUT | HTTP 200; the node config receives only `retrieval_profile_ref`, never the node id or raw profile |
| L6 | Second Retrieve node bound in the same draft | Distinct role (`ret_580c…` vs `ret_032c…`); binding one node leaves the sibling's config untouched |
| L7 | GET on the still-unbound sibling | HTTP 200, `configured=false`, independent seed |
| L8 | Unauthenticated GET on the binding route | HTTP 401 JSON |
| L9 | Nonexistent draft id | HTTP 404 |
| L10 | Existing draft, node id that is not a Retrieve node | HTTP 400 with a content-free code |

A second run covered matched permitted/forbidden identities on a `demo`-tenant draft, with the
`editor` (exact Scenario Editor) and `auditor` (organization auditor) console accounts:

| # | Check | Result |
| --- | --- | --- |
| L11 | `editor` creates the draft and GETs the binding | HTTP 201 / HTTP 200 with `can_write=true` |
| L12 | `editor` saves the binding | HTTP 200 |
| L13 | `auditor` GETs the same binding | HTTP 200 with **`can_write=false`** — read is allowed, write authority is not advertised |
| L14 | `auditor` PUTs the same binding | **HTTP 403**, no state change |
| L15 | `editor` requests a foreign-tenant draft's binding | **HTTP 404**, no existence disclosure |
| L16 | `auditor` requests the same foreign-tenant draft | **HTTP 404** |

Both runs used disposable workflow drafts created and then deleted through the console API. No
existing draft, scenario, release or index was modified, nothing was published, and the environment
was confirmed restored afterwards (workflow drafts `1..6` unchanged, zero `ret_*` artifact drafts,
zero `ret_*` artifact versions, zero probe drafts).

**Defect found during the live run:** deleting a workflow draft leaves its node-owned artifact
drafts behind (two orphan `retrieval_profile` drafts had to be removed explicitly). This affects
Generate bindings equally and predates this slice's node binding work; it is unpublished,
tenant-scoped working state only, so there is no release, runtime or disclosure impact. Recorded for
the Part 7 cleanup slice.

### Not yet verified / blocked

- **The mandatory browser gate is satisfied for authorization, not for UX.** The authorization,
  matched-identity, cross-tenant, direct-URL/POST and route-liveness rows (L1–L16) ran against the
  real server with three distinct operator identities. No rendering engine was available, so the
  human UX assessment — discoverability, click count, feedback, error recovery, keyboard use,
  responsive layout at 390/900/1440 px and browser console/network review — has **not** been done
  and remains outstanding for the Retrieve node panel.
- Repository-wide `mypy apps` still reports **3 pre-existing errors** in
  `apps/builder/tests/test_api.py` (unmodified by this slice, present at commit `88e4e18`), and
  repository-wide `ruff format --check apps` still reports pre-existing drift in
  `apps/retrieval/providers.py`. Both are outside the approved Part 4 scope and are reported, not
  worked around.
- Known limitation: a bound Retrieve node cannot be returned to release-level fallback from the UI.

## Part 5 — document-set inline authoring (Studio handoff retirement)

### Baseline finding

Acceptance criterion 4 was already met by Part 8A: `document_profile_inspector.html` renders inspect,
new-version and create-new controls for chunking, retrieval, summary-model and summary-prompt on the
document-set staged-index page. This slice therefore delivered only the retirement of the Studio
handoff for chunking, which `apps/ingestion` alone consumes — `apps/releases` and
`apps/orchestration` contain no `chunking_profile` reference, so it is not a release-pinnable role.

### What changed

- `apps.builder.services` gained `DOCUMENT_SET_OWNED_ARTIFACT_TYPES` and dropped
  `chunking_profile` from `AUTHORABLE_ARTIFACT_TYPES`.
- `apps.builder.api` removed chunking from the artifact-draft source allowlist and the
  new-version eligibility set, excluded document-set-owned drafts from the draft list, and made
  `_scoped_artifact_draft` exclude them so detail, update, delete and publish all 404 by direct URL.
- `apps.console.views.scenario_artifact_options` excludes document-set-owned types from the type
  list and returns 404 for an explicit chunking request.
- The React authoring components (`NewGovernedProfilePanel`, `ArtifactDraftEditor`,
  `ScenarioManifestPanel`, `App`, `GovernedProfileEditor`, api/types unions) no longer have any
  chunking path, so no client can produce one.

### Automated evidence

- `pytest apps/builder/tests/test_document_set_owned_artifacts.py`: 4 passed (new file).
- `pytest apps/builder apps/console/tests/test_phase_2_8_part_4.py
  apps/console/tests/test_document_workspace_console.py`: 116 passed.
- Full SQLite suite: **1167 passed, 61 skipped**.
- PostgreSQL profile for `apps/builder apps/console`: **356 passed, 0 failed**.
- Frontend: typecheck passed, `npm test` 12 files / **50 passed**, production bundle rebuilt.
- `ruff format --check` and `ruff check` clean for `apps/builder` and `apps/console`;
  `manage.py check` no issues; `makemigrations --check --dry-run` no changes (no migration).

### What the tests prove

- Chunking is absent from `AUTHORABLE_ARTIFACT_TYPES` and present in
  `DOCUMENT_SET_OWNED_ARTIFACT_TYPES`; the service rejects a chunking draft with
  `unsupported_artifact_type` and persists nothing.
- The draft API rejects a chunking create (400) and refuses to seed a draft from a published
  chunking artifact (404).
- A pre-existing chunking draft disappears from the list and returns 404 on detail, update and
  publish, while the row itself stays intact and unmodified.
- The release-manifest picker omits chunking from its type list and 404s an explicit request at both
  the logical and exact-version levels.
- The Studio profile panel offers only `retrieval_profile` and `model_profile`, defaults to a
  scenario-owned type, and renders no chunking editor anywhere.

### Environment note

Host-run PostgreSQL tests that upload a document need `OBJECT_STORE_ENDPOINT`,
`OBJECT_STORE_BUCKET`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` exported for the published
MinIO port; `config.settings.local` defaults to the real S3 backend while `config.settings.test`
uses an in-memory store. Without them `test_phase_2_5_part_2` fails with `STORAGE_PUT_FAILED`. This
is a profile gap, not a regression — the same test passes once the endpoint is set.

### Not yet verified

- The rendered UX pass for the document-set page and the Studio profile panel after chunking
  removal. Server-side behavior is covered above; the browser gate's UX rows still need a real
  browser.

## Part 2 — defaults and navigation

### What changed

- New `apps/console/scenario_defaults.py` owns the canonical default contract bodies, the exact
  scenario-scoped logical-id helper and an idempotent `prepare_scenario_contract_defaults`.
- `scenario_create` prepares both contracts inside the same transaction as the scenario, alias and
  workflow draft, each with its own audit event.
- The scenario detail page renders read-only contract status plus one explicit override action; the
  three creation buttons are gone.
- Eval-suite preparation moved to the release detail page (candidate evaluation step).
- `_release_artifact_example` now seeds an override from the exact canonical default, and the eval
  case example uses the canonical `query` key instead of `question`, which reached no node.

### Automated evidence

- `pytest apps/console/tests/test_scenario_contract_defaults.py`: 7 passed (new file).
- `pytest apps/console apps/gateway apps/releases`: 318 passed.
- Full SQLite suite: **1174 passed, 61 skipped**.
- PostgreSQL profile for `apps/console apps/releases apps/gateway`: **325 passed**.
- `ruff format --check` and `ruff check` clean for `apps/console`; `mypy apps` reports only the 3
  pre-existing `test_api.py` errors; `manage.py check` no issues; `makemigrations --check` no
  changes (no migration).

### What the tests prove

- All three presets produce exactly two v1 contract artifacts at the scenario-scoped logical ids,
  with two matching audit events.
- The defaults accept the canonical envelope and reject an empty body, an empty query, the wrong key
  (`question`), an extra field, a missing `sources`, and a non-string answer — so the default is not
  a permissive schema that silently weakens validation.
- Re-running preparation creates no second version and returns nothing.
- The scenario page shows the default status and exactly two override actions, contains no
  `?type=eval_suite` creation link, and points to the evaluation step instead.
- The override route seeds from the canonical default for an exact Scenario Editor and returns 403
  for a project administrator without that exact scenario responsibility.

### Not yet verified

- The rendered UX pass for the reshaped scenario page and the relocated eval-suite action.
- Existing scenarios created before this slice have no prepared defaults; no backfill was run. They
  keep the previous behavior of an absent contract until an author creates one.

## Part 6 — candidate authority simplification

Owner approval for this authorization-contract change was recorded before implementation.

### What changed

- `apps/builder/api._release_scenario` became `_candidate_scenario`: manifest requirements,
  preflight and compile now accept an exact Scenario Editor as well as a release manager.
  `_artifact_scenario` delegates to it, so one helper owns candidate-preparation authority.
- `apps/console/views._evaluable_release` allows the same editor to run a required evaluation.
  `_manageable_release` is unchanged and still guards promote, rollback, canary and activation.
- The release page computes `can_eval` from manager-or-author, so an editor sees the eval action on
  a candidate and no traffic control.

### Automated evidence

- `pytest apps/console/tests/test_candidate_authority.py`: 8 passed (new file).
- `pytest apps/console apps/builder apps/releases apps/evaluations`: 423 passed, 1 skipped.
- Full SQLite suite: **1182 passed, 61 skipped**.
- PostgreSQL profile for `apps/console apps/builder apps/releases apps/evaluations`:
  **432 passed**.
- `ruff format --check`/`ruff check` clean; `mypy apps` reports only the 3 pre-existing
  `test_api.py` errors; `manage.py check` no issues; `makemigrations --check` no changes.

### What the tests prove

- A Scenario Editor resolves requirements, preflights and compiles a candidate (HTTP 201), and the
  compile produces a candidate without activating anything.
- The same editor runs an evaluation: an `EvalRun` is created and the release stays `candidate`.
- The same editor receives **HTTP 403** on promote, rollback, canary start and scenario lifecycle
  change, and no release becomes active.
- The release page shows the editor the eval action and none of the promote/rollback/canary URLs.
- A Scenario Viewer is denied both preflight and evaluation, and no `EvalRun` is created.
- A foreign-tenant editor receives 404 — not 403 — on both the builder and console surfaces, so
  cross-tenant existence is not disclosed.

### Live evidence

Compose web was restarted to load the change; `/v1/health/live` returned HTTP 200.

| Identity | Action | Result |
| --- | --- | --- |
| `editor` | GET candidate release detail | HTTP 200 |
| `editor` | POST promote | **HTTP 403** |
| `editor` | POST rollback | **HTTP 403** |
| `editor` | GET canary start | **HTTP 403** |
| `auditor` | POST run eval | **HTTP 403** |
| `editor` | candidate release page affordances | eval action present; promote, rollback and canary absent |
| `auditor` | candidate release page affordances | eval action absent |

No live release, scenario or traffic state was changed. The positive live eval was deliberately not
run: it would write an `EvalRun` row against owner data, and the automated suites already cover it.

### Not yet verified

- The rendered UX pass for the release page under an editor identity.
- The release-manifest preset recommendation remains release-manager-only by prior design; it was
  not re-scoped and has no new evidence.
