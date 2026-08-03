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
