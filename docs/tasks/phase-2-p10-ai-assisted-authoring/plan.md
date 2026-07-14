# Task Plan: phase-2-p10-ai-assisted-authoring

## Task summary

Implement Workstream 3 as a governed AI-assisted workflow-authoring path: bounded free text becomes
an untrusted candidate workflow DSL, is validated by the existing canonical compiler, previewed as
a mutable `WorkflowDraft`, and may be published only through the existing explicit builder path.

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

## Non-goals

- Live environment profile/secret/network provisioning.
- Automatic retry after a request may have been sent; `outcome_unknown` is terminal.
- Automatic artifact publish/release compile/eval/promotion.
- General prompt/model/agent/MCP configuration inside the visual builder.
- Non-workflow artifact generation in P10.1.
- Personal identity/OIDC/OBO/LDAP changes (WS4 remains last).
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

## Affected components

- `apps.builder`: authoring service, internal operator API, audit/rate limiting and tests.
- `apps.orchestration`: narrow authoring provider over the existing model egress transport.
- `frontend`: free-text candidate form, diagnostics and explicit transfer to draft/preview.
- Settings, current-behavior docs, handoff and verification evidence.

## Interfaces affected

- Additive authenticated same-origin operator route under `/console/api/builder/ai-candidates/`.
- Additive frontend builder workflow. Public consumer gateway and MCP contracts are unchanged.

## Data impact

The operator description and raw model response are transient and must not be persisted or logged.
Only the parsed bounded DSL enters an existing `WorkflowDraft` after explicit acceptance. P10.1 is
planned without a migration.

## Security impact

Adds cost-bearing model egress from an operator action. The LLM output crosses an untrusted-code/data
boundary and must pass bounded parsing plus the canonical validator. Endpoint/profile/secret values
remain platform-only. Prompt injection cannot grant tool, tenant, publish or runtime authority.

## Authorization impact

Organization membership remains read scope. Candidate generation and draft transfer require
`can_author_scenarios` for the exact organization; a supplied project must belong to it. The UI is
non-authoritative and every request is rechecked server-side.

## Observability impact

Audit stable requested/succeeded/failed/rate-limited outcomes with actor, organization, configured
profile ID, lengths/token counts, latency class and stable reason only. Never record descriptions,
prompts, candidate DSL, model response, endpoints, headers or secrets. Metrics use bounded labels.

## Migration impact

None planned for P10.1.

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

Ship disabled by default. Platform operations registers/chooses an approved immutable profile and
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

## Open questions

- P10.2 may generalize the same candidate envelope to other artifact types after P10.1 evidence.

## Status

Implemented and verified offline — live profile/network/privacy/cost activation remains a separate
deployment gate, and owner browser acceptance remains manual.

## Completion criteria

Implemented and Verified are tracked separately. Completion requires full evidence, current-behavior
documentation, final staff/AppSec/SRE review and no unresolved authorization/redaction defects.
