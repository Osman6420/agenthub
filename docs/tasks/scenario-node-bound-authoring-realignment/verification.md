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

The probe used one disposable workflow draft created and then deleted through the console API. No
existing draft, scenario, release or index was modified, nothing was published, and the environment
was confirmed restored afterwards (workflow drafts `1..6` unchanged, zero `ret_*` artifact drafts,
zero `ret_*` artifact versions).

**Defect found during the live run:** deleting a workflow draft leaves its node-owned artifact
drafts behind (two orphan `retrieval_profile` drafts had to be removed explicitly). This affects
Generate bindings equally and predates this slice's node binding work; it is unpublished,
tenant-scoped working state only, so there is no release, runtime or disclosure impact. Recorded for
the Part 7 cleanup slice.

### Not yet verified / blocked

- **The mandatory browser gate is only partially satisfied.** The authorization, direct-URL/POST and
  route-liveness rows above ran against the real server, but: (a) only the `admin` identity was
  available — the `editor`, `auditor` and `releaser` operator passwords were not supplied, so matched
  permitted/forbidden identity pairing and visible affordance parity were not exercised live (they
  are covered by automated tests only); and (b) no rendering engine was available, so the human UX
  assessment (discoverability, click count, keyboard use, responsive layout, browser console/network
  review) has not been done. These rows remain outstanding.
- Repository-wide `mypy apps` still reports **3 pre-existing errors** in
  `apps/builder/tests/test_api.py` (unmodified by this slice, present at commit `88e4e18`), and
  repository-wide `ruff format --check apps` still reports pre-existing drift in
  `apps/retrieval/providers.py`. Both are outside the approved Part 4 scope and are reported, not
  worked around.
- Known limitation: a bound Retrieve node cannot be returned to release-level fallback from the UI.
