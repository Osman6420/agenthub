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
Manager authority, independent of every bound scenario. Later delivery parts remain planned.
