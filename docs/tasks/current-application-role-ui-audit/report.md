# Current application role and UI audit

## Outcome

The current local build is live with eight Compose services; liveness and readiness return HTTP 200. Persistent Gemini chat and embedding profiles were created before the remaining tests, granted where required, and exercised through AgentHub's own provider seams. Chat returned a non-empty response; embedding returned a normalized 3072-dimensional vector. A real staged index built one chunk and, after two missing lifecycle links were supplied as audited test bootstrap state, browser retrieval returned the expected synthetic chunk.

Most previously unverified paths are now exercised: release evaluation/promotion/rollback, sync/background execution, queued cancellation, consumer isolation, pending approval accept/reject/deny, destructive tombstone/purge, and two-way second-tenant isolation. Product code was not changed.

The audit still finds three major product gaps: exact-scenario runtime operators can read other same-tenant scenario runs; UI-created scenarios cannot be made externally callable through the UI; and normal index promotion leaves the document-set state incomplete so retrieval fails despite an “active” index.

## Browser-tested responsibility matrix

| Responsibility / identity | Permitted path verified | Denial verified | Result |
| --- | --- | --- | --- |
| Global + organization administrator (`admin`) | Organization, membership/responsibility, project, document set, consumer, credentials, binding, advanced tombstone/purge inventory | Scenario authoring remains separated | Passed; platform profile/bootstrap still has no UI |
| Organization auditor (`auditor`) | Project, scenario, set and consumer metadata | Create/access mutations return 403 | Passed |
| Project administrator (`project-admin`) | Exact-project scenario + starter draft creation | Studio authoring disabled | Passed |
| Project viewer / second-tenant project viewer | Exact project read | Create disabled; foreign project is 404 in both tenant directions | Passed |
| Scenario viewer | Exact scenario read | Authoring disabled | Partial: direct Studio URL falsely reports no drafts |
| Scenario editor (`editor`) | Studio validate/publish; one-off active-release execution | Project/consumer/document mutations denied | Partial: AI planner is not rendered for this exact-scenario role |
| Scenario release manager (`releaser`) | Exact manifest selection, canonical preflight, candidate compilation, release read | Workflow editing disabled; unassigned user gets 404 | Partial: eval/promote/rollback controls are unreachable in UI |
| Scenario runtime operator | Exact scenario and run navigation | Resource creation and approval decision denied | Failed: same-org cross-scenario run disclosure; no pause/resume/cancel controls |
| Scenario approver (`approver`) | Pending queue, approve and reject | Runtime operator cannot see the item and direct decision is 403 | Passed |
| Document-set manager | Upload, publish, profile selection, staged build, index activation, retrieval after bootstrap, tombstone | Other sets remain hidden; advanced purge is 403 | Partial: normal promotion does not complete retrieval state |
| Document-set content reader | Exact metadata | Upload/publish/index controls absent | Partial: no preview/download surface |
| Active member without responsibility | Organization shell | Exact objects 404; create/access routes 403 | Passed |
| REST consumer | Sync 200, background 202, run status, idempotent cancel | Different consumer gets 404 for status and cancel | Passed after non-UI scenario activation bootstrap |

## Functional and security findings

### High

1. **Exact-scenario runtime responsibility leaks other same-tenant run metadata.** `/console/runs/` and linked workflow-run detail expose other scenarios, including `Document Answer`, to a user assigned only to the audit scenario. The detail is redacted but still reveals scenario, actor, timestamps, status, and event names. List/detail scoping is organization-wide instead of intersecting the actor's exact scenario responsibility.

2. **A UI-created scenario cannot become externally callable through the UI.** Release #7 was active, its alias and consumer binding were active, yet `/v1/responses` returned `SCENARIO_NOT_ALLOWED` because the scenario remained `draft`. No scenario lifecycle control exists, and release promotion does not activate it. After an audited local bootstrap changed only this test scenario to `active`, sync and background API calls passed.

3. **Index promotion reports active without completing the served document-set lifecycle.** The browser successfully built and activated index v1, but one-off retrieval returned `Aktif exact index/retrieval profili bulunamadı`. Normal promotion neither moves `DocumentSetVersion` from `promotable` to `active` nor sets its `built_index_version`. After both missing links were supplied as audited test bootstrap state, the same browser action returned the expected chunk through the real Gemini embedding path.

### Medium

4. **Release lifecycle actions exist but have no usable UI route.** `release_detail` is read-only; `/console/releases/` redirects to Projects although an unused template contains eval/promote/rollback controls. Candidate #7 was compiled in Studio, but eval (1/1 passed), promotion, and rollback had to be exercised through authenticated server endpoints.

5. **Scenario runtime operator cannot perform its declared controls.** There are no exact-run cancel or exact-scenario pause/resume controls. The page explicitly reserves runtime controls for Global/Organization Admin, conflicting with the scenario runtime operator capability set.

6. **Studio AI authoring is not reachable for an exact scenario editor.** The editor can write the draft, but the AI panel is gated by organization-level `canWrite`, not the draft's exact `can_write`. A direct authorized API call reached Gemini but failed with `candidate_invalid_json`: the model returned a fenced response (18 output tokens, 56 characters) while the provider sends no JSON response-format constraint and the parser requires raw JSON.

7. **Required release artifacts are difficult or impossible to author in the UI.** The release manager can pin contracts and eval suites only after they exist, but the tested UI offered no contract/eval-suite creation action. Valid immutable input/output contracts and an eval suite were therefore created through domain services before UI pinning.

8. **Connector egress remains unavailable from this UI state.** The set's Sources page shows no bound connector and no source wizard because no connector profiles/grants exist. There is also no connector-profile provisioning console path, so external connector sync could not be safely initiated.

### Low / UX consistency

- Scenario Viewer direct Studio URL says there is no draft although revision 2 / published v1 exists.
- The release detail page does not explain where lifecycle actions are performed.
- After candidate compile, dirty manifest selection blocks navigation without a visible explanation; clearing the selection makes navigation work.
- Document-set publish can render duplicate `Taslağı yayımla` buttons.
- Tombstone is available to the set manager, but purge is discoverable only at a separate advanced inventory restricted to organization/global admin.
- Cross-tenant denial is correct, but local `DEBUG=True` renders the full Django route list on 404 pages.
- Navigation remains role-insensitive and labels/timestamps mix Turkish and English.
- Expected 403 responses log full Django warning tracebacks; the known watchfiles permission traceback for a nested worktree remains. No HTTP 500 was observed.

## Completed end-to-end journeys

- Registered active immutable `audit-gemini-chat` (Gemini 3.6 Flash) and `audit-gemini-embedding` (Gemini Embedding 001, 3072 dimensions) profiles; granted embedding use to Demo Org.
- Ran real AgentHub chat and embedding provider calls without printing or persisting the key.
- Parsed the synthetic TXT, built and activated index v1, diagnosed the incomplete lifecycle, then confirmed browser retrieval after audited bootstrap links.
- Created exact contracts and eval suite, compiled candidate #7 in Studio, ran a passing evaluation, promoted it, created/passed candidate #9, and rolled back to #7. Unauthorized lifecycle attempts returned 404 and caused no mutation.
- Executed sync response (200/completed), background response (202/queued), status lookup, two idempotent cancel requests, and observed `cancelled` / `acknowledged`. A different consumer received 404 for status and cancel.
- Approved one high-risk tool request and rejected two; runtime operator saw an empty queue and direct decision returned 403.
- Created `Audit Isolation Org 20260731`, a project, a new local login, membership, and project-viewer responsibility; project reads passed in-scope and returned 404 in both cross-tenant directions.
- Uploaded a disposable document, tombstoned it, removed its draft pin, and permanently purged one version through the confirmation UI. The record no longer exists and cannot be recovered.

## Click and comprehension assessment

| Journey | Approx. clicks/taps | UX assessment |
| --- | ---: | --- |
| Create organization | 3 | Clear for Global Admin; no platform-admin/profile setup guidance |
| Add existing user + project responsibility | 3 + 5 | Dense target form; underlying login still cannot be created in UI |
| Create project | 4 | Simple; slug behavior is explained |
| Create scenario + starter draft | 5 | Good start, but no visible scenario activation step |
| Validate and publish workflow | 5 | Clear once inside Studio |
| Build exact release manifest | About 25 for six pins | Repetitive type → logical ID → version → role selection; presets/checklist would help |
| Eval → promote → rollback | Not reachable in UI | Hidden/unreachable despite implemented endpoints |
| Create client + binding | 4 + about 7 | Capability presets and success feedback would reduce ambiguity |
| Upload → publish → build → activate index | About 12 | Linear guide is useful, but it reports success before retrieval state is complete |
| Retrieval question | 2 | Clear when lifecycle state is valid; generic error otherwise |
| Approve/reject | 1 each after opening queue | Very clear; repeated rows need more contextual requester/input summary |
| Background invoke + cancel | Not executable in console | Only curl text is shown; operator must use a consumer token outside UI |
| Tombstone → unpin → purge | About 7 across three pages | Safety confirmation is good; discoverability is low |

Recommended simplifications: add a governed scenario activation step; make index promotion atomic across set/index linkage; restore a real release lifecycle page; use role-aware navigation; provide manifest presets; gate actions with inline reasons and setup links; expose AI authoring based on exact scenario author permission; add JSON response-mode or safe fence handling for supported providers.

## Capabilities without a usable console path

- Create the underlying human login account.
- Register/disable/grant model, embedding, or connector profiles and configure secret/provider switches.
- Bootstrap the first Global Administrator.
- Activate/disable a scenario lifecycle state.
- Run release eval, promotion, rollback, or canary through reachable navigation.
- Scenario-operator pause/resume/cancel.
- Direct REST/MCP invocation as a logged-in operator.
- Human-readable raw document preview/download for Content Reader.
- Create connector platform profiles or initiate connector egress when none are granted.
- GitOps/control-plane import/export and deployment/maintenance commands.

## Local state and operational caveats

The Gemini key remains environment-only and was never printed or written to the repository. The current containers have the required provider variables, but a future `docker compose` recreation without equivalent external environment injection will remove them; profile database rows alone are insufficient.

The audit leaves reproducible local records: the two Gemini profiles, test artifact versions/releases/runs/approval history, Demo Org test objects, and the second isolation tenant/project/user. Release #7 is active; release #9 is rolled back. The disposable purge target was irreversibly removed. No production system or data was accessed.

## Residual coverage limits

No connector profile/credential was available, so real Confluence/REST connector egress was not authorized or exercised. Model-assisted Studio generation reached Gemini but currently fails strict parsing. Destructive testing was limited to one synthetic purge target.
