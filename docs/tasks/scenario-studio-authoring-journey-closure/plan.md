# Task Plan: scenario-studio-authoring-journey-closure

## Task summary

Close the remaining browser-authoring gaps discovered during the 2026-08-03 owner journey. The
highest priority is prompt authoring and exact artifact content inspection/versioning. The same
governed authoring model then expands to retrieval and profile artifacts, followed by early release
readiness gates, truthful preset availability, Agent Loop evaluation compatibility, and shorter
scenario/document-set journeys.

This is a corrective follow-up to the completed Phase 2.9 UI closure. The implementation must retain
immutable exact-version release pins, server-side authorization, separation of duties, and audited
lifecycle transitions.

## Background

The current UI exposes workflow drafting, artifact selection, candidate release, evaluation, and
promotion as separate capabilities, but an owner acceptance journey found that their composition is
not yet self-explanatory or reliably completable:

- Generate exposes raw manifest role fields such as `prompt_ref`, but does not provide the prompt
  text authoring task the user is trying to perform.
- An artifact can be selected without opening its exact body, and most artifact types cannot be
  created or versioned from the browser.
- Retrieval and profile artifacts lack complete authoring screens.
- Workflow publish can appear unresponsive when the version description is empty, and the newly
  published version is not made obvious in the manifest picker.
- A release can advance to a state that will deterministically fail at the next gate, for example
  because an eval suite was not pinned.
- Agent Loop may be offered as an authoring preset while its background-only compiler decision is
  incompatible with a sync-only evaluation path.
- Scenario and document-set lifecycles expose implementation objects instead of a short guided task
  journey.

The governing sources remain the artifact immutability contract, release exact-pin contract,
workflow DSL/compiler, authorization services, audit policy, and document/index lifecycle. UI state
is never an authorization or readiness authority.

## Scope

### Priority 0 — prompt and artifact content authoring

- Add an authorized artifact workspace with organization-scoped search/list, type and logical-ID
  filters, exact-version history, bounded full-body viewing, checksum/status/usage metadata, exact
  version diff, and release-pin impact.
- Allow creation of a new logical artifact and creation of a new immutable version from an existing
  version. “Edit” always means “create a new version”; published `ArtifactVersion` rows are never
  mutated or directly deleted.
- Make the exact artifact body viewable from every artifact selector before selection. Provide
  `Open`, `Use this exact version`, and—when authorized—`Create new version` actions without losing
  the current scenario/manifest context.
- Deliver a first-class `prompt_template` editor first: prompt text, variables/placeholders,
  validation diagnostics, preview/test inputs where safe, change description, draft save, publish as
  an immutable version, and immediate return to/select in the originating workflow.
- Replace silent publish no-ops with explicit client and server validation. Empty version notes focus
  the field and announce `Bu sürümde nelerin değiştiğini yazın.`; pending, success, and failure states
  are visible and accessible.
- On successful publish, refresh dependent artifact selectors and manifest options and identify the
  exact newly published version without requiring a page reload.

### Priority 1 — retrieval and profile artifact authoring

- Apply the same inspect/create/new-version/diff/select experience to every artifact type supported
  by the registry and its authoritative validator.
- Provide structured authoring forms for `retrieval_profile` and `chunking_profile`, including
  documented defaults, closed allowed fields, range/compatibility validation, and an advanced JSON
  view that cannot bypass the server validator.
- Provide reference-authoring screens for tenant `model_profile` artifacts and any
  `embedding_profile` reference artifact supported by the release/document path. These bodies may
  select only authorized platform-managed profile UUIDs and display safe metadata; they may not
  accept or reveal endpoint, credential, secret, TLS, or egress-policy values.
- Cover the remaining artifact registry types through a capability matrix: structured editor when a
  stable schema exists; validated JSON editor with schema/help when supported but no structured form
  exists; explicit read-only/unsupported explanation when authoring is intentionally prohibited.
- Keep platform profile registration/grant/disable operations separate and restricted to the
  existing platform responsibilities. Tenant artifact authoring does not become platform profile
  provisioning.
- Replace the document-set staged-index form's opaque dropdowns with capability-aware pickers:
  `embedding_profile` and `ocr_profile` expose safe details and, only for an authorized platform
  profile operator, a link to create/manage a platform profile revision; `chunking_profile` and
  `retrieval_profile` open their exact artifact bodies and allow authorized create/new-version
  authoring; `summary_model_profile` opens or versions the UUID-only model reference artifact while
  keeping the underlying provider profile platform-managed; and `summary_prompt_contract` opens or
  versions the prompt artifact in the prompt editor. Every picker returns to the staged-index form
  and selects the exact chosen revision/version without discarding the remaining form state.

### Priority 2 — Generate-node behavior authoring

- Make each supported scenario preset declare a server-owned default binding recipe. At scenario
  creation, resolve and visibly preselect authorized exact versions for the input contract, output
  contract, prompt/model bindings, and—when the preset includes RAG—the applicable document set,
  embedding profile revision, chunking profile, and retrieval profile. The author must not have to
  select the same required defaults again in later workflow, manifest, or staged-index steps.
- Defaults are conveniences, not hidden authority: show their logical ID and exact version/revision,
  allow the author to replace any field through its picker, and immediately recompute downstream
  readiness. Never resolve an implicit `latest` at candidate/runtime time.
- If a required preset default is missing, inactive, incompatible, or not granted to the organization,
  mark the preset unavailable before scenario creation with the exact remediation; do not create a
  partially configured scenario that is guaranteed to fail later.
- Replace raw `prompt_ref` as the primary Generate-node control with two user tasks: author an inline
  prompt that will publish as a prompt artifact, or select an existing exact prompt version.
- Replace raw `model_profile_ref` as the primary model control with an authorized model/profile
  selector backed by safe profile metadata.
- Support more than one Generate node by deriving stable, collision-free manifest roles from the
  node identity/purpose (for example `prompt.generate_answer` and `prompt.generate_summary`) and
  showing that generated binding in an advanced/provenance section.
- Preserve backward compatibility for existing workflows whose `prompt_ref` and
  `model_profile_ref` already name manifest roles. Raw role editing remains an advanced DSL action,
  not the default form.
- Publishing a workflow must either pin or request selection of every exact prompt/model role it
  requires; no implicit “latest version” lookup is introduced.

### Priority 3 — early readiness and release gates

- Introduce one server-authoritative readiness/preflight result reused by Studio, manifest assembly,
  candidate creation, evaluation, promotion, activation, and callable-status views.
- Model the visible states distinctly: incomplete draft, structurally complete/evaluable candidate,
  evaluated exact release, promotable release, active release, and callable scenario.
- Block an action at the earliest point when a later failure is deterministic. Candidate creation
  must reject missing exact required roles, including the eval suite when the scenario/release policy
  requires evaluation. `EVAL_SUITE_NOT_PINNED` must therefore be remediated before candidate creation,
  not discovered only during activation.
- Surface field/role-specific blockers with direct actions such as `Prompt oluştur`, `Eval suite
  seç`, `İndeks hazırla`, or `Yetkiliye gönder`. Do not collapse exact safe error codes into a generic
  workflow error.
- Keep asynchronous facts (for example an index build still running) distinct from structural
  omissions, while preventing promotion/activation until the required fact becomes ready.
- Preserve release-manager separation. If the author lacks promotion authority, the guided action is
  `Onaya gönder`; the UI does not promote on the author's behalf.

### Priority 4 — Agent Loop and preset truthfulness

- Add a server capability/readiness descriptor for scenario presets and node types. The create screen
  must disable unsupported presets with an explicit reason, or show a pre-creation warning only when
  a supported remediation path exists.
- Do not advertise Agent Loop as ready when the exact selected policy, worker topology, evaluation
  runner, or promotion path cannot complete it.
- Replace the blanket Agent Loop background-only outcome with compiler-derived execution eligibility.
  Bounded loops without approval/human/event waits and with enforceable step/tool/time budgets may be
  sync-eligible; all other loops remain background-only.
- Make evaluation honor the compiled execution mode. Add bounded background evaluation polling or
  completion handling with deadline, cancellation, durable outcome, and safe exact error propagation;
  do not force every evaluation through sync execution.
- Add preset/compiler/evaluator compatibility tests so a preset offered as supported can complete the
  release path in the declared environment.

### Priority 5 — shorter guided journeys

- Recompose scenario authoring into four primary steps while retaining advanced views:
  1. **Scenario:** name, purpose, and only environment-supported presets.
  2. **Behavior:** graph, prompt text, model, tools, and input/output contracts.
  3. **Data and test:** document set/retrieval configuration, generated smoke eval or custom eval,
     and one readiness checklist.
  4. **Go live:** publish exact artifacts, assemble the manifest, create candidate, evaluate, request
     approval/promote, activate, and confirm callable status through explicit audited operations.
- The UI may orchestrate these operations but may not merge their domain transactions or hide
  authorization decisions. Each completed transition remains independently auditable and retry-safe.
- Recompose document-set work into three primary tasks:
  1. **Content:** source/upload, draft extraction preview, and publish.
  2. **Search settings:** Keyword/Vector/Hybrid presets plus advanced embedding, chunking, retrieval,
     and optional summary prompt/model settings; publish and start staged indexing explicitly.
  3. **Usage:** retrieval test, staged/served readiness, grants/bindings, and scenario selection.
- Show an always-visible progress summary, current blocker, next authorized action, and deep links to
  advanced artifact/release/index details.

### Priority 6 — hardening, documentation, and rollout

- Update the user guide, authoring/DSL architecture guide, permission matrix, and manual browser
  guide to describe the task-oriented paths and immutable-version semantics.
- Add automated browser coverage for the prompt-first scenario journey, artifact inspection and
  versioning, retrieval/profile authoring, unsupported preset denial, release early gates, multi-
  Generate roles, and Agent Loop evaluation modes.
- Run live owner acceptance for both a no-document scenario and a document-backed scenario before
  declaring the task verified.

## Non-goals

- Mutating or deleting a published artifact version.
- Allowing tenant authors to register provider endpoints, enter credentials, change TLS/egress
  policy, or grant themselves access to platform model/embedding profiles.
- Replacing exact release pins with implicit latest-version resolution.
- Weakening server-side authorization because a UI control is hidden or disabled.
- Automatically promoting/activating releases or serving indexes without the existing authorized,
  explicit lifecycle transitions.
- Making every artifact type editable when the authoritative backend intentionally supports it only
  as a platform-managed or read-only object; such cases must be visible and explained.
- Changing public runtime API contracts unless separately reviewed and explicitly approved.

## Acceptance criteria

1. An authorized scenario author can open the exact content and metadata of any artifact version
   visible in a selector, then return and select that exact version without losing work.
2. An authorized artifact author can create a prompt, publish it with a required change description,
   see the new immutable version immediately, and bind it to a Generate node without typing
   `prompt_ref`.
3. Two Generate nodes can use different prompt/model bindings; roles are deterministic and
   collision-free, and existing explicit-role workflows remain compatible.
4. Creating a supported preset preselects visible, authorized exact input/output contracts and all
   preset-required bindings. A RAG preset also carries its applicable embedding, chunking, and
   retrieval defaults into the document/workflow journey, so the author only opens a picker when
   changing a default. Missing or unauthorized defaults make the preset unavailable before creation.
5. Authorized users can inspect and create new versions of retrieval and chunking profiles through
   validated forms. Model/embedding reference authoring exposes only granted, safe profile metadata
   and UUID references.
   On the staged-index form, all six profile/prompt fields can be opened and inspected; artifact
   fields offer authorized create/new-version actions, while platform embedding/OCR profiles offer
   only safe detail plus an authorized platform-management handoff rather than inline secret-bearing
   editing.
6. Every registry artifact type has an explicit capability state: structured authoring, validated
   JSON authoring, or read-only/unsupported with a reason. No selector is an opaque label-only list.
7. Empty workflow/artifact version notes produce an inline, announced validation error and no silent
   button behavior. Success refreshes all dependent selectors.
8. A release that requires evaluation cannot become a candidate without an exact eval-suite pin.
   Other deterministic downstream blockers are reported at the earliest actionable step by the
   shared server preflight.
9. Unsupported presets are visibly disabled or warned before scenario creation, with the exact
   capability reason. A preset marked supported passes an automated create-to-evaluate contract test.
10. Agent Loop sync eligibility is derived from bounded policy. Background-only loops can be evaluated
   through a bounded background path, and error codes remain specific and actionable.
11. A normal scenario journey presents four primary steps and the document-set journey presents
    three. Advanced exact pins and lifecycle objects remain inspectable.
12. Authorization allow/deny, cross-tenant denial, immutable-version behavior, audit emission,
    redaction, stale revision/conflict, idempotent retry, and rollback behavior are tested at service,
    API, UI, and browser levels as applicable.
13. Owner acceptance demonstrates: prompt-first no-document scenario to callable state; document-
    backed scenario using authored retrieval/chunking settings to callable state; and a deliberately
    unsupported preset stopped before creation.

## Affected components

- `apps/artifacts`: artifact registry, validation, immutable creation/versioning, content projection,
  authorization, usage and diff services.
- `apps/console`: artifact workspace, Scenario Studio endpoints, readiness projection, guided
  scenario/document journeys, profile-safe projections, and audit-aware actions.
- `apps/workflows`: Generate role derivation, compiler execution eligibility, preset capability
  analysis, and exact dependency requirements.
- `apps/catalog` and evaluation services: candidate preflight, eval pin enforcement, execution-mode
  aware evaluation, promotion/activation readiness, and exact error propagation.
- `apps/ingestion`: retrieval/chunking/profile validation and document search-settings readiness.
- `frontend`: artifact editor/viewer/picker, prompt editor, Generate node configuration, publish
  feedback, readiness checklist, preset gating, and guided step composition.
- Documentation and browser/unit/integration/security test suites.

## Interfaces affected

- New or extended authenticated console endpoints for artifact capability metadata, exact body view,
  draft/create-new-version, diff, safe usage impact, and picker refresh.
- New or extended server preflight/readiness representation consumed by authoring and release views.
- Workflow authoring projection may add derived per-node binding metadata while the canonical DSL and
  existing explicit manifest-role inputs remain backward compatible.
- Preset descriptors gain environment capability and remediation fields.
- Evaluation control gains execution-mode-aware start/status behavior. Any public API change is out
  of scope without separate approval; console interfaces remain CSRF-protected and server-authorized.

## Data impact

- Prefer existing immutable `ArtifactVersion` and draft models; assess whether generic artifact drafts
  need to expand beyond current contract types.
- Exact artifact bodies remain stored and checksummed as today. Viewing introduces no new replica or
  secret-bearing cache.
- Readiness/capability results should be derived or short-lived and must not become an alternative
  authority to exact release/index/run state.
- Any new provenance for derived Generate roles must be deterministic from canonical workflow data or
  stored within the checksummed workflow/artifact boundary.

## Security impact

- Artifact bodies are untrusted authored JSON/text and require bounded size/depth, schema validation,
  safe rendering, output encoding, and secret-pattern checks.
- Prompt previews/tests must use governed model profiles, bounded inputs/timeouts, existing egress
  controls, redaction, and auditable execution; they must not silently run merely by opening an editor.
- Profile reference forms and staged-index pickers must prevent credential/endpoint smuggling and
  return only allowlisted safe metadata; embedding/OCR platform-profile management must not be
  mistaken for tenant artifact editing.
- See [threat-model.md](threat-model.md).

## Authorization impact

- Reuse exact organization/scenario responsibilities and object-level predicates server-side for
  every list, body view, usage view, draft, publish, candidate, evaluation, promotion, and activation
  action.
- Separate read, author/new-version, release-author, evaluator, release-manager, runtime-operator,
  document-manager, and platform-profile responsibilities. UI affordances reflect, but never replace,
  the authoritative decision.
- Cross-tenant artifact IDs, profile IDs, release usage, drafts, and diff endpoints must fail closed
  without existence disclosure.
- Any change to the existing authorization contract requires owner approval before implementation.

## Observability impact

- Audit artifact logical creation, new-version publication, denied view/author attempts, prompt preview
  execution, manifest changes, candidate preflight failure/success, evaluation start/outcome,
  approval/promotion, activation, and preset capability denial using safe actor/tenant/target IDs.
- Add stable operational events/metrics for readiness blocker codes, publish validation failures,
  evaluation mode/outcome/latency, background evaluation deadline/cancellation, and selector refresh
  failures without logging artifact bodies, prompts, document content, or credentials.
- Propagate request/trace IDs across console, worker, evaluation, and runtime operations.

## Migration impact

- No migration is assumed in the plan. The first implementation slice must confirm whether existing
  generic draft and artifact models support all required authoring states.
- If a schema change becomes necessary, add a separate reviewed migration step with backward/forward
  compatibility, PostgreSQL non-owner/RLS verification, data backfill bounds, and rollback evidence.
- No destructive migration or rewrite of existing artifact/release pins is permitted.

## Dependencies

- Existing immutable artifact services and per-type validators.
- Existing Scenario Studio draft/publish and manifest-option APIs.
- Workflow compiler dependency extraction and release exact-pin validation.
- Existing eval runner, background worker/checkpoint lifecycle, release promotion, and activation
  services.
- Existing platform model/embedding profile registries and tenant grants.
- Existing document preparation, staged index build, promotion, retrieval test, and consumer grants.

## Implementation steps

### Milestone 0 — baseline and contracts

1. Reproduce and record the owner journeys for workflow publish, releases 18/20, artifact picker,
   Generate prompt, Agent Loop, and document preparation against current live topology.
2. Inventory every `ArtifactType`, validator, runtime consumer, secret classification, authoring
   responsibility, and current UI/API support in one capability matrix.
3. Define the shared artifact projection and readiness/blocker contracts. Record a focused ADR if
   derived Generate roles or the shared readiness state machine changes durable architecture.
4. Freeze browser/test fixtures for backward-compatible existing workflows and release manifests.

### Milestone 1 — prompt-first artifact foundation (P0)

1. Implement authorized exact artifact body/history/usage/diff APIs with bounded safe projections.
2. Generalize governed artifact drafts/new-version publication without weakening immutable storage or
   per-type validation.
3. Implement the artifact workspace and selector drawer with open, compare, new-version, and exact-
   select actions.
4. Implement `prompt_template` structured authoring, diagnostics, required version notes, accessible
   publish feedback, and automatic selector/manifest refresh.
5. Verify prompt create → publish → inspect → bind across allow, deny, cross-tenant, conflict, secret-
   pattern, size, audit, and accessibility cases before expanding types.

### Milestone 2 — retrieval and profile authoring (P1)

1. Add closed, versioned validators and structured editors for retrieval and chunking profiles where
   current schemas are incomplete; preserve backward-compatible reading of valid legacy versions.
2. Add safe model/embedding profile reference pickers backed by platform grants and UUID-only
   artifacts; test that secrets/endpoints cannot enter or leave the surface.
3. Add structured or validated-JSON editors for remaining supported artifact types and explicit
   read-only reasons for prohibited types.
4. Integrate every artifact picker with exact preview/version history and originating-context return.

### Milestone 3 — Generate-node binding UX (P2)

1. Define preset-owned default binding recipes and atomically resolve authorized exact contract,
   prompt/model, and RAG document/profile versions during scenario creation. Project those defaults
   into later forms instead of asking for duplicate selection.
2. Specify and implement deterministic per-node prompt/model role derivation with collision and node-
   rename behavior covered by tests.
3. Add inline prompt/new artifact and existing exact-version selection to Generate configuration.
4. Move raw role fields to advanced mode and retain round-trip compatibility for existing DSL.
5. Make workflow publish and manifest assembly explain and resolve all derived exact dependencies.

### Milestone 4 — shared readiness and early release gates (P3)

1. Implement one server-side readiness analyzer with stable blocker codes and authorized remediation
   links/metadata.
2. Apply it transactionally to candidate creation, eval, promotion, activation, and callable status;
   client checks are advisory mirrors only.
3. Require exact eval-suite pins before candidate creation when evaluation is mandatory and move all
   other deterministic next-gate failures to their earliest actionable boundary.
4. Update publish and release UI to show current state, blocker, next authorized action, pending
   asynchronous requirements, and successful refresh.

### Milestone 5 — Agent Loop and preset compatibility (P4)

1. Implement compiler-derived Agent Loop sync/background eligibility from closed bounded policy.
2. Make evaluation dispatch according to compiled mode and add bounded background completion,
   timeout, cancellation, retry/idempotency, and exact failure handling.
3. Add environment-aware preset capability analysis and disable/warn before creation.
4. Add contract tests asserting every enabled preset can traverse create, compile, candidate, and
   evaluation gates in its declared topology.

### Milestone 6 — guided scenario and document journeys (P5)

1. Compose existing explicit domain operations into the four-step scenario shell with resumable
   progress, one readiness checklist, deep links, and separation-of-duty handoff.
2. Compose document operations into Content, Search settings, and Usage tasks, including retrieval/
   profile authoring and staged-versus-served clarity.
3. Preserve direct advanced routes for experts and ensure browser back/refresh/deep-link behavior does
   not lose drafts or display stale readiness.

### Milestone 7 — hardening and closure (P6)

1. Run targeted service/API/UI/browser/security tests after each milestone, then full repository
   format, lint, type, unit/integration, PostgreSQL non-owner/RLS, worker, and secret checks.
2. Perform staff-engineer, application-security, SRE, accessibility, and Turkish content reviews of
   the final diff and live topology.
3. Complete the two owner end-to-end acceptances and unsupported-preset denial journey.
4. Update current-state docs, ADRs if applicable, verification evidence, master plan, and archive the
   task only after Implemented and Verified are both evidenced.

## Test plan

- Artifact service/API: type matrix, create logical artifact, next version, stale conflict,
  immutability, checksum, schema errors, body bounds, diff bounds, usage accuracy, idempotent retry.
- Authorization/security: unauthenticated, missing responsibility, exact-object denial, cross-org ID,
  profile grant denial, secret/endpoint fields, stored/rendered injection, CSRF, audit success/deny,
  body and log redaction.
- Prompt UX: create/edit-as-new-version, placeholder diagnostics, version-note focus/announcement,
  publish pending/success/failure, selector refresh, origin return, exact binding.
- Retrieval/profile UX: structured validation boundaries, legacy body view, UUID-only model/embedding
  refs, revoked/disabled grant, safe metadata, unsupported/read-only explanation.
- Generate: zero/one/multiple nodes, duplicate labels, node rename, deterministic roles, existing
  explicit roles, manifest completeness, no implicit latest lookup.
- Preset defaults: input/output and non-RAG creation, complete RAG defaults, author override,
  organization grant filtering, inactive/incompatible/missing default, no duplicate selection in
  later steps, exact-version stability after a newer version is published.
- Release: eval-required and optional policies, missing each exact role, invalid eval suite, index
  pending/failed/ready, unauthorized transition, concurrent/stale manifest, exact evaluated checksum,
  promotion and activation rollback.
- Agent Loop: bounded sync-safe policy, human/approval wait, tool and step budgets, background success,
  deadline, cancellation, worker loss/retry, exact error code, unsupported topology/preset.
- Browser: four-step no-document scenario, four-step RAG scenario, three-step document preparation,
  release-manager handoff, back/refresh/deep-link, keyboard/focus/ARIA, narrow viewport, Turkish copy.
- Repository gates: formatter, linter, type check, frontend tests/build, backend tests, PostgreSQL/RLS,
  migration check, worker checks, secret scan, and final diff review as required by Definition of Done.

## Rollout plan

1. Ship additive body-view/prompt-authoring APIs and UI behind an organization-scoped feature flag;
   retain existing Studio and manifest paths.
2. Expand artifact types only after the P0 security/authorization/browser gate passes.
3. Introduce readiness analysis in observe-only comparison mode, reconcile differences, then enforce
   candidate blocking before changing the guided release default.
4. Enable Agent Loop/presets per environment capability; default to disabled with an explicit reason
   when worker/eval support is unverified.
5. Make the guided journeys the default after live acceptance; retain advanced routes through at
   least one compatibility window and publish migration guidance.

## Rollback plan

- Disable the new authoring/guided-journey flags and return to existing routes without removing any
  immutable artifact versions or exact release pins.
- Keep new versions created through the feature as valid immutable history; rollback must not delete
  or rewrite them.
- Revert readiness enforcement only to the previous authoritative server gates, never to client-only
  trust or automatic activation.
- Disable Agent Loop/preset capability exposure per environment if background evaluation or worker
  health regresses; in-flight runs follow existing bounded cancellation/recovery policy.
- Any migration receives its own backward-compatible rollback procedure before approval.

## Risks

- A generic editor can accidentally expose or accept secret-bearing profile configuration.
- Derived Generate roles can break existing manifests or become unstable after graph edits.
- Duplicated readiness logic can disagree across UI, candidate, eval, promotion, and runtime.
- Earlier enforcement can block previously accepted but incomplete drafts/releases; rollout requires
  clear remediation and compatibility handling.
- Background evaluation can leak workers or leave ambiguous outcomes without deadlines,
  idempotency, and durable checkpoints.
- Guided orchestration can conceal real domain transitions or encourage unauthorized automatic
  promotion if separation of duties is not explicit.
- Large artifact bodies/diffs or prompt previews can create denial-of-service, cost, egress, or data
  exposure risks.

## Open questions

- Which currently valid artifact types intentionally remain platform/GitOps-managed rather than
  tenant-authorable? Milestone 0 must resolve this per type and responsibility.
- Should inline prompt drafts publish during workflow publish or through an explicit prior `Promptu
  yayımla` action? The chosen design must preserve atomic user feedback and exact immutable pins.
- What is the stable role identity when a Generate node is renamed: immutable node ID, explicit
  binding key, or a persisted generated key? This requires a compatibility decision before P2.
- Which release policies require eval, and can a bounded default smoke suite be generated explicitly
  for simple scenarios? No hidden or silently passing eval suite is permitted.
- What environment evidence is sufficient to mark Agent Loop and each preset as supported?

## Status

In progress — owner authorized sequential implementation and per-part commits on 2026-08-03.
[Part 1 — prompt-first artifact foundation](../scenario-studio-authoring-journey-closure-part-1/plan.md)
was committed at `ef05d3b`. [Part 2 — retrieval/profile authoring and staged-index selectors](
../scenario-studio-authoring-journey-closure-part-2/plan.md) remains the next expansion unit. The
[prompt inline manifest correction](../prompt-inline-manifest-authoring/plan.md) was implemented and
verified first after owner acceptance showed that Part 1's separate preview/editor controls did not
yet provide the required select–inspect–edit–bind task. Later milestones remain planned.

## Completion criteria

- All acceptance criteria map to recorded automated and manual evidence.
- Every milestone is separately marked Implemented and Verified; plan status does not advance on code
  completion alone.
- Applicable Definition of Done checks pass and unavailable checks/residual risks are explicit.
- Current-state documentation and any durable ADR are updated.
- Final owner acceptance confirms the prompt-first artifact flow, retrieval/profile authoring,
  early release blocking, supported-preset truthfulness, and shortened scenario/document journeys.
