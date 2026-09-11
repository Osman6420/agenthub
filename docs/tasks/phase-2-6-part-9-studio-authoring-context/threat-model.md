# Threat Model: phase-2-6-part-9-studio-authoring-context

## Assets

- Tenant-scoped scenario/project/organization metadata
- Active managed/Python-node and tool/prompt/model/retrieval catalogs
- Document-set/retrieval capability and workflow contract schemas
- Author identity, permissions, draft lineage and revision state
- Model prompt/context, transient candidate and canonical diagnostics
- Immutable artifact/release lifecycle and server identifier integrity

## Actors

- Authorized and malicious scenario authors
- Organization/platform admins and auditors
- Compromised tenant accounts
- Untrusted model provider/output
- Malicious catalog descriptions, tool metadata and user prompt content
- Web/worker/operator processes and model provider infrastructure

## Entry points

- Scenario Studio natural-language planner input
- Server authoring-context assembly queries
- Model provider request/response
- Candidate JSON/graph diagnostics
- Explicit save/update/copy API
- Capability-missing Python-node scaffold
- Publish and release compilation revalidation

## Trust boundaries

- Browser/user text to server authorization and prompt separation
- Tenant database/catalog records to bounded safe context serializer
- Server context/system contract to external model provider
- Untrusted model output to strict parser/reference conformance
- Transient candidate to canonical compiler diagnostics
- Browser transient state to explicit authorized durable save
- Snapshot references to current live catalog/release state

## Data classifications

Safe public node/tool descriptions and workflow limits are internal tenant metadata. Scenario
contracts, draft bodies and catalog schemas may be confidential. Document contents, credentials,
secrets, endpoints, Python source, authorization internals and foreign-tenant records are restricted
and excluded from model context, client responses, logs, traces and audit payloads.

## Authentication

Existing authenticated Studio sessions remain authoritative. Model/provider identity and possession
of a candidate/context checksum do not authenticate an author. Save/update/copy requires a current
authenticated session and CSRF protections through existing server surfaces.

## Authorization

Context assembly and save perform server-side object/action/tenant authorization. Client/model
tenant, owner, scenario, roles and references are untrusted. Every generated reference is validated
against both the supplied snapshot and current live authorized state. Publish/release boundaries
repeat validation.

## Tenant isolation

All context queries begin from the authorized scenario and follow direct organization/project
lineage. Catalog services must require organization scope and deny foreign rows. PostgreSQL RLS is
defense in depth, not a substitute for application authorization. Cross-tenant tests cover context,
candidate refs, update/copy and stale races.

## External systems

The model provider receives only the bounded approved context and user description through existing
governed model egress. CI uses deterministic/fake providers. No model-selected endpoint, secret or
network target is allowed. Provider timeout, rate limit, malformed output and uncertain outcome
produce safe transient errors and no database mutation.

## Abuse cases

- Request another tenant's scenario/context or insert a foreign catalog ref.
- Put prompt-injection instructions in user text, tool/node descriptions or schemas.
- Invent an active-looking node/tool/model/retrieval role absent from the snapshot.
- Use a once-valid ref after it is disabled/revoked before save or release.
- Exfiltrate secrets/endpoints/source/document contents through context, diagnostics or logs.
- Submit oversized/deep schemas/catalogs/model output for memory/token/cost exhaustion.
- Forge organization/project/scenario/logical ID during save or copy.
- Silently overwrite an existing draft with a stale/missing revision.
- Trigger generation repeatedly for spend/rate-limit denial of service.
- Turn capability-missing into automatic Python source persistence/activation.
- Persist transient output in browser storage where XSS/other users can recover it.

## Failure cases

- Model timeout, rate limit, invalid JSON or unexpected structured-result version
- Context budget overflow or safe serializer failure
- Catalog capability disabled between snapshot, response, save, publish or release
- Concurrent draft update/stale revision
- Identifier collision
- Canonical compiler rejects syntactically parsed output
- Audit commit failure for an explicit save/security-sensitive transition
- Provider outcome unknown after request without a valid candidate
- Page navigation/reload with unsaved transient state

## Logging and audit risks

Prompts, user text, candidates, schemas and catalog descriptions may contain confidential or
injection content. Raw provider errors may expose endpoints or request fragments. IDs can create
high-cardinality metrics. Audit must not become a copy of the model context/candidate.

## Mitigations

- Explicit safe-field allowlists and deterministic bounded context serializers
- Separate trusted system contract, server context and untrusted user text
- Strict structured union parser and unknown-field rejection
- Snapshot membership plus live server authorization/reference validation
- Generation no-write transaction/query assertions
- Canonical compiler diagnostics before save and repeated validation at later lifecycle boundaries
- Server-generated identifiers and lineage; exact revision optimistic concurrency
- Memory-only transient state and dirty navigation warnings
- Existing governed egress, timeout/response limits and deterministic CI provider
- Redacted stable events, context checksum/count/size metadata only and bounded metric labels
- Rate/cost limits and independent Studio AI kill switch
- Capability-missing remains an unsaved scaffold in the normal reviewed Python-node lifecycle

## Residual risks

Authorized context still leaves the platform for approved model processing. Token estimates may
diverge from provider tokenization. Catalog descriptions can influence model quality even when they
cannot grant authority. Memory-only state is lost on refresh. Multi-tab conflicts remain possible
but must fail safely through revision checks. Browser XSS would expose currently visible transient
state and remains a platform-wide control dependency.

## Required security tests

- Authentication/CSRF failure and scenario-author action denial
- Cross-tenant context, catalog ref, save, update and copy denial
- Secret/credential/endpoint/Python-source/document-content exclusion
- Prompt injection in every untrusted context section without authority expansion
- Invented/inactive/disabled/foreign/stale reference rejection
- Context/schema/model-output byte/depth/count/token boundaries
- Generation creates no database row or lifecycle side effect
- Server lineage/identifier protection and mass-assignment denial
- Concurrent/stale revision and silent-overwrite denial
- Provider timeout/rate-limit/invalid-JSON/outcome-unknown no-write behavior
- Capability-missing cannot persist/approve/activate/publish/release
- Audit/log/trace redaction and bounded metric cardinality
- Publish/release revalidation after capability revocation
