# Threat Model: scenario-studio-authoring-journey-closure

## Assets

- Tenant-authored artifact bodies, drafts, immutable versions, checksums, and version history.
- Prompt text, test inputs/outputs, document content, retrieval/chunking settings, and contracts.
- Exact release manifests, eval suites/results, promotion approvals, active releases, and aliases.
- Platform model/embedding/OCR profiles, credentials, endpoints, TLS/egress policy, and tenant
  grants.
- Workflow graphs, derived prompt/model roles, Agent Loop checkpoints, and background eval outcomes.
- Actor, organization, scenario, document-set, run, release, and audit identities.

## Actors

- Organization viewer/content reader.
- Scenario author and artifact author.
- Document manager.
- Evaluator.
- Release manager/approver.
- Runtime operator.
- Platform administrator/profile operator.
- Background worker and external governed model/embedding provider.
- Authenticated same-tenant attacker, cross-tenant attacker, and compromised browser/session.

## Entry points

- Artifact list, exact body, history, diff, usage, draft, create, and publish endpoints.
- Scenario Studio artifact picker, prompt editor, node configuration, and workflow publish.
- Readiness/preflight, manifest, candidate, eval, promotion, activation, and callable-status endpoints.
- Preset capability and document search-settings endpoints.
- Prompt preview/test and Agent Loop/background evaluation dispatch/status paths.
- Browser deep links, IDs, query parameters, submitted JSON/text, and worker messages.

## Trust boundaries

- Browser to authenticated/CSRF-protected console server.
- Tenant-scoped console services to artifact/catalog/workflow/ingestion data.
- Tenant artifacts to platform-managed profile registry and grants.
- Web process to worker queue/checkpoint storage.
- Runtime/evaluation process to governed external model/embedding providers.
- Authored content to HTML/JSON rendering, logs, audit events, metrics, and diagnostics.
- Readiness projection to authoritative transactional lifecycle services.

## Data classifications

- Artifact metadata and IDs: internal tenant data.
- Prompts, contracts, workflow bodies, eval cases, and document content: tenant-confidential; may contain
  personal or sensitive business data.
- Provider credentials, tokens, certificates, private endpoints: secret/restricted platform data and
  never tenant-artifact content.
- Eval/runtime outputs and traces: tenant-confidential and potentially derived sensitive data.
- Audit records: security-sensitive operational data with safe identifiers and redacted payloads.

## Authentication

- All authoring, exact-body, readiness, release, eval, profile, and document operations require the
  existing authenticated console session and CSRF protections.
- Worker operations use existing trusted service identity and must not accept browser-asserted actor,
  organization, role, profile grant, or approval facts.
- No authentication behavior changes are authorized by this task without separate owner approval.

## Authorization

- Authorize every object/action server-side: list and body view, diff/usage, create draft, publish new
  version, prompt preview, profile selection, manifest mutation, candidate, eval, promote, activate,
  index operation, and preset use.
- Keep read, author, evaluate, approve/promote, operate runtime, manage documents, and manage platform
  profiles as separate responsibilities.
- Derived UI steps and disabled buttons are advisory only. Lifecycle services re-check the actor,
  organization, object scope, state, exact checksum/pin, and responsibility transactionally.
- Exact release usage can reveal scenario/business information and therefore requires authorization,
  not merely artifact read permission.

## Tenant isolation

- Scope all artifact/profile/release/scenario/document queries from the authenticated organization;
  never trust organization IDs from the request body or artifact/profile IDs alone.
- Cross-tenant exact IDs, logical IDs, version numbers, checksums, profile UUIDs, draft IDs, usage
  links, and diff pairs fail closed without existence disclosure.
- Preserve PostgreSQL direct tenant lineage, FORCE RLS behavior, non-owner application roles, and
  transaction-local tenant scope for added queries/jobs.
- Workers reload tenant-scoped objects under the persisted trusted tenant/actor context and reject
  stale, mismatched, or revoked grants.

## External systems

- Governed model and embedding providers through existing SSRF-safe adapters and platform profiles.
- PostgreSQL/RLS, Redis/worker queue, and object/index storage used by current lifecycle services.
- No new dependency or external service is assumed. Any addition requires separate production-
  dependency and security review.

## Abuse cases

- Guess an artifact ID to read another tenant's prompt/body, release usage, or version history.
- Use diff/preview/error detail to infer a hidden artifact or platform profile.
- Put secrets, endpoints, template injection, script markup, oversized/deep JSON, or deceptive Unicode
  into artifact/prompt bodies and exfiltrate through rendering, logs, diagnostics, or providers.
- Submit a platform profile UUID without a tenant grant, or smuggle credential/endpoint fields inside
  a model/embedding reference artifact.
- Race two editors to publish the same next version or bind a different version than the one previewed.
- Manipulate derived Generate roles through duplicate labels/renames to bind a malicious or unintended
  prompt/model.
- Manipulate preset defaults or stale client state to bind a cross-tenant, ungranted, inactive, or
  different artifact/profile version than the exact version shown during scenario creation.
- Bypass required eval by calling candidate/promotion endpoints directly or replaying stale readiness.
- Mark an unsupported preset as ready through client manipulation or environment-state race.
- Construct an Agent Loop that appears bounded but waits indefinitely, performs unapproved tools,
  spends unbounded provider cost, or leaves orphaned background evaluations.
- Abuse the guided `Go live` action to collapse author and release-manager responsibilities or repeat
  non-idempotent transitions.

## Failure cases

- Artifact publish succeeds but selector refresh fails, leading the user to bind a stale version.
- Artifact body/diff exceeds response/render bounds or unsafe content reaches the DOM.
- Profile grant is revoked between selector load and artifact publish/runtime/eval.
- Readiness projection is stale or disagrees with candidate/promotion transactional validation.
- Required eval suite is missing, invalid, or evaluates a checksum different from the candidate.
- Agent Loop compiler mode and evaluation dispatch disagree; worker is absent; evaluation times out;
  cancellation races with completion; retry creates duplicate work.
- Guided journey partially completes and browser refresh loses the next action or repeats a transition.
- Audit persistence or downstream provider/index/worker failure leaves ambiguous user feedback.

## Logging and audit risks

- Prompts, eval inputs/outputs, document content, provider responses, artifact bodies, credentials, and
  endpoints must not be written to application logs, metrics labels, traces, or broad audit metadata.
- Stable error/blocker codes must remain useful without disclosing cross-tenant existence or secrets.
- Audit each security-sensitive state change and denial with safe actor/tenant/target references,
  authorization decision, outcome, reason code, and trace ID.
- Define and test existing fail-open/fail-closed audit persistence behavior for each newly exposed
  action; do not silently weaken it in guided orchestration.

## Mitigations

- Central object/action authorization and organization scoping; FORCE RLS/non-owner verification;
  cross-tenant non-disclosure tests.
- Immutable published versions, optimistic draft revision checks, transactional next-version
  allocation, exact IDs/checksums, and post-publish exact-version confirmation.
- Closed per-type schemas/allowlists, body size/depth/string limits, safe JSON parsing, secret-pattern
  detection, output encoding, CSP-compatible rendering, and bounded diff generation.
- UUID-only model/embedding reference validators, safe OCR-profile projections, and server-side
  active-grant revalidation at publish, candidate, eval, runtime, and document-index use.
- Deterministic persisted/checksummed Generate binding identity; collision validation and backward-
  compatibility tests.
- Server-owned preset recipes, organization/grant/type/status validation at resolution and use,
  atomic persistence of the displayed exact defaults, and no client-supplied or runtime `latest`
  resolution.
- One readiness analyzer for explanation, plus authoritative transactional revalidation at every state
  change; no trust in cached/client readiness.
- Environment-derived preset capability with fail-closed unknown state; contract tests for every
  enabled preset.
- Closed Agent Loop policy, bounded steps/tools/time/provider budgets, approval-aware mode decision,
  durable idempotent jobs/checkpoints, deadline, cancellation, retry, and worker health checks.
- Explicit per-transition guided orchestration with idempotency keys, durable progress derived from
  authoritative state, and release-manager handoff rather than impersonation/automatic approval.
- Governed prompt preview with explicit user action, safe test data guidance, existing provider egress
  controls, timeout/cost bounds, and redacted audit.

## Residual risks

- Authors can intentionally place sensitive tenant data in prompts or eval cases; governance and
  access control reduce but cannot eliminate content-classification mistakes.
- Secret-pattern detection has false negatives/positives and does not replace platform profile
  separation or operator review.
- Capability/readiness can change immediately after display; transactional action-time validation and
  actionable retry remain required.
- Background provider/worker failures can still delay evaluation despite bounded deadlines and clear
  terminal state.
- Legacy artifact bodies may not satisfy newly tightened structured schemas; read compatibility and
  explicit migration-to-new-version guidance are required.

## Required security tests

- Authentication and CSRF denial for every new mutation; unauthenticated body/history/diff/usage
  denial.
- Responsibility matrix allow/deny for view, author, publish, preview, manifest, candidate, eval,
  promote, activate, document, and platform-profile actions.
- Same-tenant exact-object denial and cross-tenant non-disclosure for artifact, version, draft,
  profile, release usage, scenario, document set, and diff pairs on SQLite and PostgreSQL/RLS paths.
- Secret/endpoint field rejection and redaction tests for model/embedding artifacts, API responses,
  diagnostics, logs, traces, metrics, and audit.
- Stored/reflected script/HTML/template injection, malicious placeholders, Unicode confusion, JSON
  depth/size, diff size, and prompt preview input bounds.
- Concurrent/stale draft publication, next-version collision, exact-version selection, revoked grant,
  stale readiness, replay/idempotency, and checksum mismatch tests.
- Direct endpoint attempts to bypass missing eval pin, readiness, approval, promotion, activation,
  preset capability, or Agent Loop execution-mode restrictions.
- Agent Loop unbounded policy, unauthorized tool, approval wait, worker loss, timeout, cancellation
  race, duplicate delivery, and provider failure tests.
- Audit success/denial/failure behavior with safe metadata and trace propagation for all newly exposed
  security-sensitive actions.
