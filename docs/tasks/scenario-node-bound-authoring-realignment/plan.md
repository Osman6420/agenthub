# Task Plan: scenario-node-bound-authoring-realignment

## Objective

Realign artifact authoring with the domain object that consumes each artifact. Scenario Studio must
be node-oriented, document preparation must stay on the document-set page, default contracts must
not require repetitive selection, and a Scenario Editor must be able to prepare a complete candidate
without gaining any live-traffic authority.

## Current implemented baseline to reuse

- Immutable prompt, chunking, retrieval and model-reference drafts can already be inspected,
  validated, versioned and published.
- Staged-index selectors already preserve exact selections and project safe embedding/OCR/model
  metadata without endpoints or secrets.
- Generate DSL/runtime already accepts optional `prompt_ref` and `model_profile_ref` manifest-role
  names, but the UI exposes those identifiers instead of editing the bound content in the node.
- Retrieve DSL currently rejects all config. Runtime instead reads one release-level
  `retrieval_profile`, while document-set preparation also stores a retrieval profile. This duplicate
  ownership must be removed from the primary UX without losing historical provenance.
- Input/output contracts and eval suites currently have manual creation actions on the scenario main
  page. Scenario authors can version artifacts but cannot preflight or compile a candidate.

## Target ownership and UI

| Concern | Owner | Primary UI | Persisted/runtime contract |
| --- | --- | --- | --- |
| Input contract | Scenario boundary | Hidden default; explicit override action in Studio settings | Exact default or override artifact pin |
| Output contract | Scenario boundary | Hidden default; explicit override action in Studio settings | Exact default or override artifact pin |
| Generate prompt | Generate node | Prompt textarea inside that node | System-managed prompt artifact role/version |
| Generate model | Generate node | Safe model selector inside that node | System-managed model-profile artifact role/version |
| Retrieval behavior | Retrieve node | Structured retrieval editor inside that node | `retrieval_profile_ref` manifest role resolved per node |
| Chunking | Document set | Inline staged-index editor | Exact document-preparation/index provenance |
| Embedding and OCR | Document set | Safe selector/inspector; platform management remains separate | Exact granted platform revision |
| Document summarization prompt/model | Document set | Inline staged-index editor | Exact preparation/index provenance pair |
| Eval suite | Candidate evaluation journey | Release/evaluation step, not scenario main page | Exact eval-suite pin before required evaluation |

## Workflow DSL and release semantics

1. Keep raw prompt text, platform model UUIDs and artifact database IDs out of workflow DSL.
2. Generate-node UI edits prompt text and model choice directly. On save/publish, the server reuses
   the unchanged exact artifact or creates a new immutable version, then writes stable node-specific
   manifest-role names to `prompt_ref` and `model_profile_ref`.
3. Two Generate nodes receive independent stable roles and may use different prompt/model versions.
   Role generation is server-owned, deterministic from durable node identity, collision-checked and
   never editable as a primary user field.
4. Extend Retrieve config with optional `retrieval_profile_ref`. The release dependency extractor
   must require an exact `retrieval_profile` artifact for that role, and runtime must resolve that
   role for the executing node. Multiple Retrieve nodes may bind different profiles.
5. Existing compiled workflows remain readable: empty Generate bindings retain the current release
   fallback; legacy Retrieve nodes with empty config retain the release-level retrieval fallback for
   a documented compatibility window. New/edited workflows use node bindings.
6. Bump the compiled-workflow/compiler contract for the new Retrieve semantic and prevent stale
   checkpoints from resuming under changed binding rules.

## Default contracts and evaluation placement

- Scenario creation chooses deterministic canonical input/output defaults from the selected scenario
  preset and prepares their exact pins automatically.
- Normal authoring does not repeatedly ask the user to select those contracts. **Change input
  contract** and **Change output contract** create explicit overrides through canonical validation
  and immutable versioning.
- Remove input-contract, output-contract and eval-suite creation cards from the scenario main page.
- Place eval-suite selection/creation in the candidate evaluation step. If evaluation is required,
  candidate readiness must block before release creation when no exact suite is selected.

## Document-set realignment

- Move chunking and document-summary prompt/model editing into the document-set staged-index page;
  do not route these primary actions through Scenario Studio.
- Keep embedding/OCR safe inspection and platform-only provisioning boundaries unchanged.
- Deprecate document-set retrieval selection in the primary flow. Preserve existing
  `DocumentSetPreparationProfile` and `IndexVersion` retrieval references as historical provenance
  until an additive compatibility migration and rollback path are verified.
- New query-time retrieval behavior comes from the executing Retrieve node. Index/build submission
  continues to reauthorize all document-set-owned profile IDs server-side.

## Authorization lifecycle

- Exact Document Set Manager: inspect, create and version chunking and document-summary
  prompt/model artifacts for that document set. A bound-scenario responsibility is neither required
  nor sufficient; the same set may be shared by multiple scenarios.
- Exact Scenario Editor: edit workflow and node-bound artifacts, override contracts, assemble,
  preflight and compile a candidate, and run required evaluation.
- Release Manager/Approver: promote, rollback, canary/traffic transitions, scenario activate/disable
  and every other action that can change live traffic.
- UI visibility never grants authority; each operation retains server-side exact scenario, project,
  organization and tenant checks. This is an intentional authorization-contract change and requires
  matched allow/deny and audit evidence before rollout.

## Delivery parts

1. **Document-set authority correction:** remove bound-scenario author lookup from every staged-index
   authoring affordance; add exact document-set-manager create/new-version endpoints and inline
   controls with tenant/type/profile re-resolution.
2. **Defaults and navigation:** automatic input/output defaults; move eval authoring; remove redundant
   scenario-main actions without breaking direct-route authorization.
3. **Generate-node binding:** inline prompt/model controls, stable hidden roles, immutable reuse/new
   version behavior, multi-Generate support and release dependency tests.
4. **Retrieve-node binding:** DSL/compiler/runtime `retrieval_profile_ref`, per-node structured editor,
   multi-Retrieve support, compatibility fallback and compiled-contract bump.
5. **Document-set inline authoring:** chunking and summary prompt/model inline edit/new-version;
   retire Studio handoffs and preserve safe embedding/OCR projection.
6. **Candidate authority simplification:** allow exact Scenario Editors to preflight/compile/evaluate;
   keep all live traffic transitions release-manager-only.
7. **Cleanup and migration:** remove obsolete generic primary controls, migrate/deprecate duplicate
   retrieval ownership additively, update current-behavior docs, and run full PostgreSQL/browser gates.

## Acceptance criteria

1. A new scenario has usable exact input/output defaults without manual artifact selection.
2. Prompt text and model choice are edited inside each Generate node; two Generate nodes can publish
   and execute different exact bindings.
3. Retrieval profile is edited inside each Retrieve node and is enforced through DSL compilation,
   release dependency extraction and runtime resolution; two Retrieve nodes can differ.
4. Chunking and document-summary prompt/model are fully inspectable/editable/versionable on the
   document-set page without Scenario Studio navigation.
5. Scenario main page has no input/output/eval creation panel. Overrides and eval preparation remain
   reachable at the point of use.
6. Scenario Editor can reach an evaluated candidate but receives server denial for promotion,
   rollback, canary, activation and disable. Release Manager retains those live controls.
7. Legacy releases and workflows execute unchanged during the compatibility window; historical index
   provenance remains readable.
8. Foreign-tenant IDs, forged roles, inactive profiles, stale revisions and direct unauthorized
   requests fail closed without content, endpoint or secret disclosure.

## Data, security and operational risks

- Stable node-role generation can collide after node copy/rename; durable node identity and explicit
  collision tests are required.
- Automatic defaults can silently weaken validation if they are overly permissive; canonical preset
  schemas and visible override state are required.
- Per-node runtime resolution can accidentally fall back after a forged/missing explicit role;
  fallback is permitted only when the binding is absent, never when an explicit binding is invalid.
- Retrieval ownership migration can change result quality or invalidate active indexes; rollout must
  preserve active releases/indexes and support a deny-safe forward fix.
- Broader candidate preparation authority must not include any action that changes live traffic and
  must retain safe mutation audit events.

## Status

Part 8A implemented and verified: document-set profile create/new-version now uses exact Document Set
Manager authority, independent of every bound scenario.

Part 3 (Generate-node binding) is implemented and automatically verified. This delivery slice:

- replace the raw `prompt_ref` / `model_profile_ref` inputs with prompt text and a safe model-profile
  selector inside each Generate node;
- persist the workflow body and both node-owned artifact drafts in one transaction under exact
  Scenario Editor authority and optimistic revision control;
- derive hidden, deterministic, collision-checked roles from the immutable workflow logical identity
  and node id;
- publish only changed node-owned artifact bodies as immutable versions before publishing the
  workflow definition, while reusing an identical latest version; and
- cover two-Generate independence, stale revision, inactive/forged model, foreign-tenant and
  viewer-denial paths plus release dependency extraction.

The current local browser session reached the authenticated-console boundary but had no signed-in
operator session, so visual live-page confirmation remains manual; the current bundle was built and
the full frontend suite passed.

Part 3 follow-up (2026-08-04) is implemented and verified: the live Compose web reloader stopped
after a permission error under an unrelated worktree, leaving the old URLconf active while the new
frontend called the Generate-binding route. The web role was recreated without resetting data, the
frontend JSON client was hardened against HTML/empty error bodies, and the exact route plus client
behavior were verified.

Part 3 PostgreSQL follow-up (2026-08-04) is implemented and verified: the first authenticated PUT
exposed a PostgreSQL-only `FOR UPDATE` restriction because nullable project/scenario relations were
joined in the locking query. The lock now targets only the workflow row and PostgreSQL-backed tests
cover the path.

Part 4 (Retrieve-node binding) is implemented and automatically verified (SQLite, PostgreSQL and
frontend); the mandatory authenticated browser gate remains outstanding. This delivery slice:

- adds optional `retrieval_profile_ref` to the canonical Retrieve-node config and moves
  `COMPILER_VERSION` to `workflow-compiler/v6` so stale background claims/checkpoints cannot resume
  under the changed semantics, while the compiled graph `api_version` stays at v5 so
  already-compiled releases keep executing;
- resolves an explicit node role to its exact release-pinned retrieval profile at runtime, fails
  closed when that explicit binding is absent/invalid, and retains release-level fallback only when
  the node has no binding;
- puts the structured retrieval editor directly inside each Retrieve node, backed by exact Scenario
  Editor authorization, optimistic revision control, deterministic hidden roles and immutable
  changed-only publication, seeded from the scenario's active release while the node is unbound; and
- proves two Retrieve nodes remain independent across UI authoring, DSL compilation, release
  dependency extraction and runtime provider invocation, including PostgreSQL transaction evidence.

Operational rule for this slice: legacy refs and absent bindings remain readable and retain the
current runtime fallback. Only server-derived node roles participate in automatic artifact
publication; an explicit legacy/custom role is never silently overwritten until the author saves
that node through the new editor. Binding is one-way: there is no UI action that returns a bound
Retrieve node to the release-level fallback. Automatic candidate/manifest pinning of the generated
retrieval roles remains out of scope here.

Part 5 (document-set inline authoring) is implemented and automatically verified. Acceptance
criterion 4 was already met by
Part 8A: chunking, retrieval, summary-model and summary-prompt artifacts can all be inspected,
versioned and created from the document-set staged-index page. The remaining work is therefore
**retiring the Scenario Studio handoff for chunking**, which is owned by the document set:

- remove `chunking_profile` from every Studio authoring surface — the builder's authorable artifact
  types, the artifact-draft source allowlist, the new-version eligibility set, the draft list and
  the draft detail route — so the document-set page is the single primary editor;
- exclude `chunking_profile` from the scenario release-manifest artifact picker. It is consumed only
  by `apps/ingestion` staged preparation and is referenced by neither `apps/releases` nor
  `apps/orchestration`, so it is not a release-pinnable role;
- hide existing unpublished chunking drafts from the Studio surface entirely (owner decision) while
  leaving the rows and every published immutable version intact; and
- drop the chunking editor from the React authoring components so no client path can produce one.

Owner decision for this slice: current scenarios are demo data, so no compatibility allowance is
required for chunking roles previously reachable through Studio. Published chunking artifact
versions and the document-set preparation profiles that pin them are untouched.
