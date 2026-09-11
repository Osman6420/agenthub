# Task Plan: scenario-studio-authoring-journey-closure-part-2

## Task summary

Extend the Part 1 immutable authoring foundation to retrieval/chunking profiles and the six
document-set staged-index selectors. Artifact-backed fields become inspectable and versionable;
platform embedding/OCR profiles expose only safe metadata and a responsibility-gated management
handoff.

## Scope

- Add structured, closed forms for `chunking_profile` and `retrieval_profile`, backed exclusively by
  the existing canonical validators and immutable `create_artifact_version` service.
- Support new logical artifacts and edit-as-new-version while preserving logical descriptions and
  requiring exact-version notes.
- Add a closed `model_profile` reference form that selects an active platform profile UUID and never
  accepts endpoint, host, path, credential, TLS, or egress fields.
- Reuse the prompt editor semantics for summary prompt contracts.
- Decorate all six staged-index selectors with open/inspect actions and capability explanations.
- Show safe platform metadata for embedding/OCR profiles; only platform administrators receive a
  management handoff. Tenant/document authors cannot mutate platform profiles.
- Preserve staged-index form values while inspecting or authoring, and select a newly created exact
  artifact version on return.
- Publish a registry capability matrix: structured, validated JSON, or read-only/unsupported with a
  reason. Part 2 implements structured authoring only for the types above.

## Non-goals

- Provider profile provisioning by tenant/document authors.
- Displaying platform host, path, secret reference, TLS, network, or egress configuration.
- Mutating/deleting an immutable artifact/profile revision.
- Generate-node binding UX, preset defaults, release readiness, or Agent Loop changes.
- Claiming every artifact registry type is authorable; prohibited types remain explicit.

## Authorization

- Artifact/profile reads require the existing exact organization/document-set scope.
- Staged-index inspection requires `DOCUMENT_SET_OPERATIONS_MANAGE` on that exact set. Creating or
  versioning retrieval/chunking/summary artifacts in Studio additionally requires exact scenario
  author responsibility on the bound scenario selected for the handoff.
- Platform profile create/disable/grant remains `PLATFORM_MANAGE`; links are hidden and server-denied
  otherwise.
- Server re-resolves every artifact/profile ID; cross-tenant IDs are non-disclosing.

## Data and migration impact

- Expand `ArtifactDraft` choices to retrieval/chunking/model profiles only if the shared draft path is
  used; no published artifact schema changes.
- Prefer additive UI/API projections and existing immutable models. No destructive migration.

## Security and operational risks

- Safe profile projection may accidentally reveal endpoints/secrets.
- Generic JSON could bypass closed retrieval/chunking fields.
- Return-to-form state could select a foreign or stale exact ID.
- A document manager could be granted broader platform-profile authority by mistake.
- Large bodies or metadata could create rendering/logging pressure.

## Implementation steps

1. Record capability, validator, consumer, storage, and responsibility matrices.
2. Add safe exact artifact and platform-profile projections for the staged-index workspace.
3. Implement structured retrieval/chunking authoring and canonical diagnostics/publication.
4. Implement closed model-profile UUID selection and summary-prompt handoff.
5. Add all six selector inspect/manage/new-version affordances with state-preserving return.
6. Test allow/deny/cross-tenant, closed fields, secret redaction, bounds, stale state, immutable N+1,
   audit rollback, and form-state return.
7. Run frontend/backend/PostgreSQL/browser gates, review, document, and commit Part 2 separately.

### Active delivery slice — Part 2A

1. Expand the governed artifact-draft allowlist and model choices to `chunking_profile` and
   `retrieval_profile`; keep source-copy tenant/scenario scoped and immutable.
2. Add field-specific structured editors driven by the existing canonical v1 body shapes. No
   unrestricted JSON authoring is exposed as the primary profile flow.
3. Reuse the inline manifest reuse-or-publish behavior for both profile types and add new-logical
   profile creation from Scenario Studio.
4. Verify canonical unknown-field/range/weight rejection, authorization, exact N+1 publication,
   frontend form behavior, migration consistency, and live browser behavior.
5. Commit Part 2A independently, then continue with staged-index selectors and safe platform/model
   profile projections in Part 2B.

### Active delivery slice — Part 2B

1. Preselect the exact persisted `DocumentSetPreparationProfile` values whenever the staged-index
   form is reopened.
2. Pair all six selectors with a single selected-option inspector. Artifact bodies are bounded and
   escaped; embedding/OCR and referenced model projections omit endpoint and secret-bearing fields.
3. Open chunking, retrieval and prompt artifacts in Scenario Studio with exact type, logical ID and
   version deep links when the user also has author responsibility on a bound scenario.
4. Keep the staged form in its original tab. When Studio publishes a replacement exact version,
   select it in that tab through a same-origin, bounded notification without changing the other five
   selections; the build endpoint still reauthorizes every submitted ID.
5. Verify tenant-grant rejection, safe-field redaction, exact deep-link selection, current-selection
   defaults, frontend build, live health and responsibility-gated visibility.

### Active delivery slice — Part 2C

1. Add closed `model_profile` draft creation/versioning. The browser selects only an active platform
   profile and the persisted tenant artifact body is exactly `{profile_id: UUID}`.
2. Project only profile UUID, logical ID, revision, provider, model and output-token limit. Endpoint,
   host, path, secret reference, TLS, network and egress fields never enter the tenant response.
3. Let exact scenario authors inspect/version supported artifact content without granting release
   assembly authority; preset, preflight and compile remain exact release-manager operations.
4. Publish an explicit capability state for every registry type: structured here, guided elsewhere,
   or read-only/unsupported with a reason.
5. Notify the staged-index tab when any supported Studio editor publishes a replacement exact
   version; the server remains authoritative for every eventual build selection.

## Acceptance criteria

1. Every staged-index selector has a visible inspect action and states whether it is editable here.
2. Authorized document managers can create and version retrieval/chunking artifacts through closed
   fields; invalid ranges/weights/unknown fields fail through the canonical validator.
3. Summary prompt opens the prompt authoring flow; summary model creates only `{profile_id: UUID}`
   from a server-projected active profile choice.
4. Embedding/OCR safe views expose identity, revision, provider/model or dimensions/status and bounds,
   but never host/path/secret/TLS/egress data.
5. Platform management handoff is visible only to platform administrators and remains server-gated.
6. Returning from inspection/version creation preserves other staged-index choices and selects the
   new exact artifact version.
7. Viewer/unauthorized/cross-tenant requests fail closed; bodies and sensitive profile fields are not
   logged or audited.
8. Existing staged build submission and Part 1 prompt/scenario paths remain compatible.

## Status

Completed — Part 1 committed at `ef05d3b`; prompt inline correction committed at `7115d77`;
Part 2A retrieval/chunking authoring was committed at `e8e9800`; Part 2B six-selector inspection,
safe platform/model projections, persisted defaults and exact Studio handoff was committed at
`4c65be8`. Part 2C closed model-profile reference authoring and registry-wide capability states and
was committed at `e8b1b7e`. Ownership/placement corrections discovered after acceptance are tracked
separately in the [node-bound authoring realignment plan](../scenario-node-bound-authoring-realignment/plan.md).

## Completion criteria

- Acceptance criteria have automated and live-browser evidence.
- Applicable migration, format, lint, type, frontend, backend, PostgreSQL, security, and browser gates
  pass or concrete blockers are recorded.
- Staff/AppSec/SRE review finds no unresolved high-risk issue.
- Part 2 is committed independently before Part 3 starts.
