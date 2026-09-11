# Threat Model: Scenario Studio manifest composition and AI repair loop

## Assets

- Exact scenario/project/organization lineage and operator authorization state
- Mutable workflow drafts and transient graph/JSON candidates
- Immutable artifact bodies, versions, checksums and release manifests
- Canonical workflow/release compiler policy and structured diagnostics
- Active/candidate release state and evaluation/promotion separation
- Managed/custom/Python-node, tool, prompt, model and retrieval capability catalogs
- AI authoring system contract, server context, user correction instruction and provider response
- Audit evidence, request/trace correlation and provider cost/rate limits

## Actors

- Authenticated scenario viewer, author/editor and exact scenario release manager
- Organization/platform administrators and auditors under the active authorization model
- Malicious or compromised same-tenant operator
- Foreign-tenant operator attempting IDOR or metadata discovery
- Untrusted model provider and model output
- Malicious text in workflow candidates, catalog descriptions, schemas or correction instructions
- Web/worker/operator processes and database roles

## Entry points

- Scenario Studio bootstrap and exact-scenario deep link
- Manifest options/requirements, preflight and candidate compile JSON endpoints
- Server-rendered compatibility candidate-compile route, if retained
- Workflow graph/JSON diagnostics and node catalog
- AI generation and repair endpoints/provider adapter
- Explicit draft save/update/copy and workflow publish
- Release evaluation, promotion and rollback boundaries downstream
- Logs, audit events, traces and metrics

## Trust boundaries

- Browser route/query/state to trusted server scenario and tenant resolution
- Browser manifest rows to exact artifact re-resolution and role/type validation
- Client preflight result to final transactional compile revalidation
- Compiler exceptions/internal objects to safe structured diagnostic serialization
- Mutable workflow candidate to immutable publication and release pinning
- Tenant catalog/database data to bounded AI authoring-context serialization
- Current candidate and user correction text to separated untrusted model inputs
- Untrusted provider response to strict structured parsing, live reference validation and canonical
  diagnostics
- Application authorization to PostgreSQL FORCE RLS defense in depth

## Data classifications

- Safe artifact identifiers, public descriptions, versions, checksum prefixes, lifecycle status and
  diagnostic codes are tenant-confidential metadata unless existing policy classifies a field more
  restrictively.
- Workflow/artifact bodies, schemas, manifest descriptions, prompts, user instructions and full
  diagnostics context are tenant confidential.
- Credentials, endpoints, Python source, document/chunk contents, authorization internals, raw
  provider errors and foreign-tenant data are restricted.
- Model reasoning/chain-of-thought is neither requested nor stored.

## Authentication

- Existing authenticated Studio session and CSRF controls remain authoritative.
- A scenario ID, artifact ID, candidate checksum, context checksum, diagnostic result or model
  response does not authenticate an operator.
- Every mutation and AI repair turn requires a current authenticated session.

## Authorization

- Server resolves the exact scenario and applies the central closed-capability authorization
  decision at each entry point.
- Scenario authoring permission permits graph/JSON edit, diagnostics and explicit draft lifecycle
  only.
- Exact scenario release-management permission is separately required for release-only artifact
  options, requirements, preflight and candidate compile.
- Scenario visibility, organization membership, frontend visibility and model output do not imply
  release authority.
- The final compile re-authorizes after options/preflight and before mutation.
- AI repair receives authoring authority only; it cannot exercise release, approval, runtime,
  document-content or Python-node activation authority.

## Tenant isolation

- All scenario, artifact, release, node, tool and authoring-context queries begin from a trusted
  exact target and verify organization/project lineage.
- Artifact IDs and roles are re-resolved within the scenario organization; absent and foreign IDs
  follow the existing non-disclosure policy.
- Options and requirements endpoints filter unauthorized rows before serialization.
- PostgreSQL FORCE RLS/app-role grants remain defense in depth and are tested after the concurrent
  authorization redesign.

## External systems

- AI repair uses only the existing approved provider and exact immutable model profile.
- Provider requests contain bounded allowlisted context, current candidate, safe canonical
  diagnostics and user correction instruction; they exclude credentials, endpoints, source and
  document content.
- The provider cannot choose network destinations, profiles, secrets, tenants, artifact IDs or
  authority.
- Timeouts, rate limits, response/depth limits and outcome-unknown handling produce no durable
  mutation.

## Abuse cases

- Forge a foreign/sibling scenario, artifact version, role or checksum.
- Use scenario-author permission to enumerate release-only artifact metadata or compile a release.
- Revoke/expire release authority after preflight and submit the stale selection.
- Select duplicate roles, type-confused artifacts or a valid-looking stale checksum.
- Cause preflight to pass and swap/disable a tool, Python node or dependency before compile.
- Submit an invalid candidate that triggers exception text containing internal paths, schemas,
  tenant data or provider details.
- Use manifest descriptions, workflow node config, schemas or correction instructions for prompt
  injection and capability escalation.
- Ask AI repair to save, publish, activate, release, promote, reveal secrets or access another
  tenant.
- Repeatedly invoke AI repair to exhaust cost/rate/provider capacity.
- Feed oversized/deep candidates, many manifest rows or high-cardinality IDs to exhaust resources.
- Trick dependency suggestions into silently selecting a semantically wrong exact version.
- Exploit browser XSS to read current in-memory manifest/candidate state.

## Failure cases

- Artifact/options request fails after some rows are selected
- Canonical preflight rejects role/type, workflow, dependency or checksum state
- Final compile disagrees with stale preflight because state or authorization changed
- Audit persistence fails during candidate creation
- Compiler diagnostic lacks a safe mapping
- Dependency analysis finds multiple compatible versions or an inactive/missing role
- Provider timeout, rate limit, malformed JSON, invalid union, stale context or outcome unknown
- AI repair returns a worse candidate, invented reference or unrelated changes
- Navigation/reload loses transient manifest or AI candidate
- Concurrent tab updates a draft, artifact, capability or release
- Authorization redesign changes capability APIs during implementation

## Logging and audit risks

- Raw compiler exceptions may contain internal implementation or tenant-confidential values.
- Manifest selections, descriptions, candidate bodies, schemas and AI instructions may contain
  confidential or injection-controlled text.
- Provider errors may expose endpoint/request fragments.
- Exact IDs/checksums in metric labels create high cardinality and unnecessary correlation risk.
- Treating preflight as a mutation audit could create noisy, content-rich records; omitting final
  compile failure evidence could weaken security traceability.

## Mitigations

- Closed request/response schemas, unknown-field rejection and byte/count/depth limits
- Trusted exact-scenario resolution and current central authorization at every operation
- Tenant-scoped re-resolution of all artifact/capability references
- Typed diagnostic codes with an allowlisted serializer and safe fallback `compile_failed`
- No raw exception/provider response in client, audit, log, trace or metric output
- Shared canonical compiler logic for requirements, preflight and final compile
- Transactional final revalidation and fail-closed audit persistence for candidate creation
- In-memory transient state, dirty navigation warning and explicit reset
- No persistence from preflight, requirements or AI repair
- Separate trusted system contract/context/diagnostics from untrusted candidate/user text
- Fresh context and diagnostics per repair turn; strict structured result union
- Live reference/capability validation after model output
- Existing governed provider profile, egress, timeout, rate/size and kill-switch controls
- Explicit operator confirmation for ambiguous exact versions and AI replacement candidates
- Compatibility and regression tests across compiler callers and authorization cutover

## Residual risks

- An authorized operator can send tenant-confidential workflow data to the approved model provider.
- Safe diagnostic codes may still reveal that a same-tenant role/capability exists; release-only
  responses therefore remain separately authorized.
- Preflight is advisory and can become stale; only final compile is authoritative.
- Browser XSS can read currently visible in-memory state.
- AI repair can change behavior in ways canonical structural validation cannot judge; human review,
  tests, evaluation and promotion remain required.
- Token estimates and cost controls can differ from provider billing.
- A dependency suggestion can be structurally valid but semantically undesirable; ambiguous choices
  remain explicit and release evaluation is not bypassed.

## Required security tests

- Authentication and CSRF denial for every new endpoint
- Author versus exact release-manager capability matrix
- Revoked/expired membership/responsibility and disabled organization denial
- Cross-tenant/sibling scenario/project and forged artifact ID non-disclosure
- Role/type confusion, duplicate role/version, stale checksum and inactive capability denial
- Capability/authorization revocation between options, preflight, repair and compile
- Preflight/requirements/AI repair create zero durable rows
- Candidate compile rollback on canonical or audit failure
- Structured diagnostic safe-field allowlist and raw exception/provider-text exclusion
- Prompt injection in candidate, user instruction, catalog description and schema without authority
  expansion
- Secret/credential/endpoint/Python-source/document-content exclusion from provider, response,
  audit, logs, traces and metrics
- Candidate/context/manifest byte, depth, node, edge, artifact-count and rate boundaries
- Provider timeout/rate-limit/invalid-output/outcome-unknown no-write behavior
- Invented, foreign, disabled and stale AI references rejected after response
- Capability-missing cannot persist, review, approve, activate, publish, release or promote
- PostgreSQL non-owner/FORCE RLS tests for final authorization implementation
