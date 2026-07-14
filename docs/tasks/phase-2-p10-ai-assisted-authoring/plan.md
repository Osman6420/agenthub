# Task Plan: phase-2-p10-ai-assisted-authoring

## Task summary

Deliver Workstream 3 in two increments: P10.1 provides the verified governed workflow-candidate
path; P10.2 extends the same untrusted-candidate pattern to an explicit allowlist of other artifact
types and makes the server prompt/DSL rule contract immutable, versioned and evaluable.

## Background

P9 made exact release artifacts, canonical DSL and matching builder drafts visible in the console.
The remaining WS3 journey is free text → platform-selected LLM → candidate → diagnostics/preview →
explicit publish. ADR-0002/0005 already define the profile-ID-only stdlib model-egress boundary.
The owner previously decided that chat/embedding destinations are platform allowlisted and that AI
authoring and the visual builder coexist. Operator-triggered authoring egress and its cost controls
were explicitly approved by the owner on 2026-07-14 with the limits recorded in this plan. Live
endpoint, secret, CA and firewall rollout remain separately gated.

## Scope

- P10.1: workflow candidates only; a Turkish free-text description creates a bounded candidate in
  an existing/new project-scoped `WorkflowDraft` and opens it in the graph preview.
- A dedicated authoring provider sends fixed server-side DSL instructions as `system` and the
  operator description as untrusted `user` content. It reuses `ModelProfile` and ADR-0005 transport.
- One deployment-selected `AI_AUTHORING_MODEL_PROFILE_ID`; no endpoint/profile/secret selector in
  tenant requests or artifacts. Missing configuration disables generation.
- Strict JSON-object extraction, size/depth limits and canonical workflow diagnostics before any
  candidate is returned. Invalid candidates remain previewable only if safely parsed and bounded;
  they cannot publish.
- Author-only, CSRF-protected, same-origin operator API; per-actor+organization rate limit; audited
  request/success/failure using identifiers, counts and stable codes only.
- Explicit user action transfers the generated candidate into a draft. Generation never publishes,
  compiles a release, runs eval, promotes, or changes runtime state.
- P10.2: add artifact-type-specific candidate envelopes beyond `workflow_definition`, using the
  existing canonical `ArtifactType` validators and explicit diagnostics/accept/publish separation.
- P10.2: introduce an immutable version/checksum for each server-owned prompt + DSL/schema rule
  contract, compatibility/evaluation evidence, audited rollout and rollback.
- Candidate → diagnostics → explicit draft/preview transfer and Turkish operator terminology are
  the prioritized human journeys; responsive-width and keyboard/screen-reader manual acceptance are
  not P9/P10 completion requirements by owner decision on 2026-07-14.

## Non-goals

- Live environment profile/secret/network provisioning.
- Automatic retry after a request may have been sent; `outcome_unknown` is terminal.
- Automatic artifact publish/release compile/eval/promotion.
- General prompt/model/agent/MCP configuration inside the visual builder.
- Caller-defined arbitrary artifact types or a universal unvalidated JSON generator. P10.2 uses a
  server allowlist and per-type validation/risk review.
- Personal identity/OIDC/OBO/LDAP changes (moved to Phase 3 discovery).
- A new SDK or production dependency.

## Acceptance criteria

- [x] An authorized scenario author can submit a bounded description for an organization/project
  and receive a parsed candidate plus canonical compiler diagnostics.
- [x] The provider destination, credential and model are resolved only from the immutable platform
  profile configured by `AI_AUTHORING_MODEL_PROFILE_ID`; tenant input cannot influence them.
- [x] System DSL instructions and user description are separate chat roles; the description and
  model response are treated as untrusted data and never as authorization.
- [x] Invalid JSON, oversized/deep output, inline secrets, forbidden DSL fields and invalid graph
  shapes fail safely without artifact/release creation.
- [x] A successful candidate is copied to a project-scoped mutable draft and graph preview only after
  explicit operator action; publish remains the existing separate server-authorized operation.
- [x] Authentication, author denial, cross-tenant project/profile attempts, CSRF, rate limiting,
  audit outcomes, redaction and `outcome_unknown` no-retry behavior have negative tests.
- [x] CI/test defaults perform no network call and remain deterministic through an injected fake
  authoring provider.
- [x] P10.2 exposes only explicitly approved artifact types; unsupported/high-risk types fail closed
  before model egress and every returned candidate receives the canonical type validator.
- [x] P10.2 candidates remain transient until an explicit, re-authorized accept action; generation
  cannot create an immutable artifact, release, eval, promotion, tool binding or runtime change.
- [x] Prompt/DSL contracts have immutable IDs, revisions and checksums; the selected revision and
  artifact type appear only as bounded safe audit metadata and support staged rollback.
- [x] Artifact-type compatibility/regression evals cover valid, malformed, oversized/deep,
  inline-secret, cross-tenant and authorization-denial cases.

## Affected components

- `apps.builder`: authoring service, internal operator API, per-type diagnostics/acceptance,
  audit/rate limiting and tests.
- `apps.orchestration`: narrow authoring provider over the existing model egress transport.
- `frontend`: free-text candidate form, diagnostics and explicit transfer to draft/preview.
- Settings, current-behavior docs, handoff and verification evidence.

## Interfaces affected

- Additive authenticated same-origin operator route under `/console/api/builder/ai-candidates/`.
- Additive membership/author-scoped non-workflow draft list/detail/diagnostics routes under
  `/console/api/builder/artifact-drafts/`; deliberately no publish route.
- Additive frontend candidate-type selection and type-appropriate preview/diagnostics. Public
  consumer gateway and MCP contracts remain unchanged.

## Data impact

The operator description and raw model response are transient and must not be persisted or logged.
Only parsed bounded candidate data enters type-appropriate mutable authoring state after explicit
acceptance. P10.1 has no migration. P10.2 adds `ArtifactDraft` through additive `builder.0002`; the
prompt-contract registry is immutable code rather than database state and does not overload artifact
history.

## Security impact

Adds cost-bearing model egress from an operator action. The LLM output crosses an untrusted-code/data
boundary and must pass bounded parsing plus the canonical validator. Endpoint/profile/secret values
remain platform-only. Prompt injection cannot grant tool, tenant, publish or runtime authority.
Tool definitions/bindings, model profiles, source definitions and custom executable nodes are
high-risk candidates and require an explicit per-type security decision; P10.2 does not enable them
merely because they exist in `ArtifactType`.

## Authorization impact

Organization membership remains read scope. Candidate generation and draft transfer require
`can_author_scenarios` for the exact organization; a supplied project must belong to it. The UI is
non-authoritative and every request is rechecked server-side.

## Observability impact

Audit stable requested/succeeded/failed/rate-limited outcomes with actor, organization, configured
profile ID, lengths/token counts, latency class and stable reason only. Never record descriptions,
prompts, candidate DSL, model response, endpoints, headers or secrets. Metrics use bounded labels.

## Migration impact

None for P10.1. P10.2 adds only `builder.0002_artifactdraft`; no existing rows or columns change.

## Dependencies

No new production dependency. Reuse the existing stdlib OpenAI-compatible/profile-managed egress.
The disabled-by-default operator-triggered network/cost behavior was approved on 2026-07-14. Live
profile activation and environment-specific network/secret rollout remain separately gated.

## Implementation steps

1. Obtain explicit approval for operator-triggered, profile-only authoring egress and stated limits.
2. Add settings with disabled-by-default profile ID, description/output bounds and actor/org rate.
3. Implement a dedicated authoring provider with separate system/user messages and no blind retry.
4. Implement bounded candidate extraction/diagnostics and fail-closed audit behavior.
5. Add author-scoped CSRF operator API and frontend preview/accept flow.
6. Add negative security, redaction, rate, provider and frontend tests.
7. Run full SQLite, focused PostgreSQL, frontend and repository gates; update current-state docs.
8. Inventory artifact types and classify each as initial allowlist, later allowlist or prohibited;
   record canonical validator, mutable preview target, authorization and side-effect risk.
9. Design/version the prompt + DSL/schema contract and its compatibility/evaluation/rollback model.
10. Implement P10.2 type-by-type with negative security tests and Turkish candidate diagnostics/
    explicit transfer journey; keep live egress disabled until the Phase 2 closure milestone.

Implementation detail: generation returns a transient candidate envelope and canonical diagnostics;
a separate acceptance request re-validates the same bounded candidate and creates or updates the
selected project-scoped draft. The server stores no candidate token or raw model content between
those actions. Rate-limit cache failure denies generation with a stable safe code.

## Test plan

- Missing/invalid profile configuration; caller cannot supply profile, URL, host, secret or headers.
- Authentication, author role, foreign organization/project and CSRF denial.
- Empty/oversized/control-character descriptions; JSON fence/object parsing, depth and byte bounds.
- Valid workflow, invalid workflow, inline secret and forbidden execution/network field diagnostics.
- Rate limit boundary and actor/organization isolation.
- Provider safe failure, malformed response and post-send `outcome_unknown` with no retry.
- Audit success/failure/rate-limit fields and prompt/response/content redaction.
- Explicit draft creation/preview, separate publish and no artifact/release side effect.

## Rollout plan

Ship P10.1/P10.2 disabled by default. Platform operations registers/chooses an approved immutable
profile and
sets `AI_AUTHORING_MODEL_PROFILE_ID` only after environment-specific endpoint, CA, secret, firewall,
privacy and cost approval. Start with a conservative rate and monitor stable outcome/token metrics.

## Rollback plan

Unset `AI_AUTHORING_MODEL_PROFILE_ID` to disable the UI/API generation action immediately. Existing
drafts/artifacts remain ordinary governed records and require no data rollback.

## Risks

- Denial of wallet from repeated author requests.
- Prompt injection or malicious output attempting to introduce endpoints, secrets or executable code.
- Sensitive descriptions/candidates leaking through logs, audit, errors or tracing.
- Model produces syntactically valid but semantically poor workflows; human preview remains required.
- Post-send uncertainty incurs cost without a usable candidate and must not be retried blindly.

## Decisions

- Initial limits approved on 2026-07-14: description 8 KiB, candidate 256 KiB, JSON depth 20, five
  requests per actor+organization per ten minutes.
- Profile selection is one deployment-selected UUID, not a tenant-visible model picker.
- Approval covers implementing the disabled-by-default network/cost behavior only. It does not
  approve a live endpoint, secret, CA, DNS, firewall rule or production activation.
- P10.2 is required in Phase 2 and is developed with the candidate journey, not deferred as an
  optional future phase. Expansion is allowlisted per artifact type rather than universal.
- Prompt/DSL contract governance is P10.2 scope. Canonical validators remain authoritative.
- Live AI-authoring activation occurs in the Phase 2 closure hardening milestone.
- Responsive-width and keyboard/screen-reader manual acceptance are not required; Turkish
  terminology and candidate → diagnostics → explicit transfer remain priorities.
- P10.2 initial allowlist is `workflow_definition`, `input_contract` and `output_contract`.
  Input/output contracts are low-side-effect JSON Schema documents with an existing canonical
  validator. `prompt_template`, `policy_profile`, `chunking_profile`, `retrieval_profile`,
  `memory_policy` and `eval_suite` remain later candidates until their body contracts are stricter.
  `model_profile`, `source_definition`, `custom_node_definition`, `tool_definition`,
  `tool_binding` and `agent_definition` remain prohibited on this route because they can introduce
  egress, credentials, executable behavior, tool authority or runtime decisions.
- Non-workflow candidates transfer to a new tenant/project-scoped mutable `ArtifactDraft`; this is
  author working state only and has no publish endpoint in this increment. Workflow candidates keep
  using `WorkflowDraft` and the existing graph preview/publish separation.
- Prompt/DSL contracts use a server-owned immutable code registry. Each entry has a stable ID,
  positive revision, artifact type and SHA-256 checksum over its exact system instructions. The
  deployment may select an existing revision through a bounded setting; adding/changing a revision
  requires code review and regression evidence. No database persistence or migration is needed for
  the contract registry.

## Open design decisions for P10.2

- Whether later low-side-effect artifact types receive stricter canonical body schemas and become
  eligible for the allowlist.
- Whether generic artifact drafts gain a separate governed publish surface after product review.

## Status

P10.1 and P10.2 are implemented and verified offline. Live activation is reserved for the Phase 2
closure hardening milestone; Turkish terminology and the candidate journey remain prioritized human
review, without responsive/accessibility manual acceptance requirements.

## Completion criteria

Implemented and Verified are tracked separately. Completion requires full evidence, current-behavior
documentation, final staff/AppSec/SRE review and no unresolved authorization/redaction defects.
