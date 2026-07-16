# Task Plan: phase-2-6-part-9-studio-authoring-context

## Task summary

Implement P2.6.9: a bounded, tenant/scenario-aware AI workflow planner embedded in Scenario Studio.
Generation produces a transient editable candidate, never a database draft or published object. The
server supplies the only authoritative capability context, rejects invented references, and creates
identifiers only during an explicit authorized save.

## Background

Current AI authoring uses a bounded static workflow guide and free-text description, then transfers
a candidate through a separate acceptance flow that asks for a name/logical ID and persists a
`WorkflowDraft`. This does not give the model the scenario's current authorized node/tool/model/
retrieval capabilities and makes transient generation look like durable authoring.

P2.6.0 fixed the declarative workflow and authority contracts. P2.6.9 moves planning into Scenario
Studio without allowing model output, user text or stale context to grant authority. It can proceed
in parallel with the P2.6.8 isolation spike, but consumes Python-node metadata only through the
public safe catalog contract produced by that lane.

## Scope

### Bounded authoring-context service

- Build a deterministic server-side snapshot scoped by the authenticated actor, organization,
  project and scenario.
- Include only safe metadata required to produce a workflow:
  - scenario type, display name and purpose;
  - safe organization/project metadata;
  - current workflow DSL guide, node types, exact config contracts and platform limits;
  - active organization-allowed managed nodes;
  - active Python-node public metadata when the P2.6.8 catalog contract is available;
  - active tool-binding roles with safe description and approval requirement;
  - available prompt, model and retrieval roles;
  - scenario-bound document-set/retrieval capability summary;
  - input/output contract schemas;
  - safe active/candidate/draft lifecycle metadata.
- Use stable ordering, version the context contract, checksum the canonical snapshot and enforce
  section, entry, schema, byte and token-estimate limits.
- Exclude secrets, credentials, endpoints, Python source, document content, foreign-tenant data,
  hidden authorization state and unnecessary user/operational data.

### Model contract and reference conformance

- Send three separate inputs: immutable server system contract, server-built authoring context and
  untrusted user description. Neither context descriptions nor user text grant authority.
- Require a strict structured union result:
  - `workflow_candidate`; or
  - `capability_missing` with a bounded proposed custom-node description.
- Reject unknown result kinds, extra fields, oversized output and unbounded/raw model text.
- Validate every generated node ref, tool role, prompt/model/retrieval role and schema reference
  against both the supplied snapshot and current live authorized state.
- Never invent/fallback to a similar reference, endpoint, package or capability.
- A capability-missing suggestion may open an unsaved Python-node scaffold through the normal
  author lifecycle. AI cannot create durable source, review, approve, activate, publish, release or
  promote anything.

### Transient Scenario Studio candidate

- Put the planner inside the current scenario's Studio page.
- Generation creates no `WorkflowDraft`, `ArtifactDraft`, `ArtifactVersion`, release or Python-node
  record.
- Normalize the candidate for diagnostics using a server-owned transient placeholder ID that cannot
  be persisted as a real logical ID.
- Open valid or invalid candidates in graph and JSON views and run canonical diagnostics
  immediately.
- Map diagnostics to node/edge identifiers and JSON Pointers. Preserve bounded raw response only
  when parsing fails so the author can repair it; never log it.
- Keep initial transient state in memory only. Do not use localStorage/sessionStorage. Show dirty
  navigation/reload warnings.
- Clearly distinguish Turkish-first lifecycle states: AI temporary candidate, saved mutable draft,
  pending/active Python node, published immutable artifact, candidate release and active release.

### Explicit save, update and copy

- On explicit save, re-authenticate/re-authorize lineage, rebuild or revalidate live capability
  state and rerun canonical workflow validation.
- Generate collision-safe logical ID/slug/revision identifiers through existing server-side
  identifier services. Users may change display name, never system identifiers or lineage.
- If drafts already exist for the scenario, require an explicit choice:
  - update a selected existing draft using the exact expected revision; or
  - create a new copy with a new server-generated logical ID.
- Never silently overwrite. Preserve transient edits on stale revision and return a safe conflict.
- Publish, release compile, eval and promotion remain separate existing operations and revalidate
  references again at their boundaries.

## Non-goals

- Python-node source execution, review or activation (P2.6.8).
- Persistent browser recovery of transient model output in the initial delivery.
- Model-created tools, bindings, prompts, model/retrieval profiles, grants, credentials or releases.
- Automatic save, publish, evaluation, release, promotion or production execution.
- Client-authoritative tenant/project/scenario lineage or authorization.
- Persistent conversation history or multi-agent supervision.
- A new public API, authentication mechanism, production dependency or live-provider requirement.

## Acceptance criteria

1. Context assembly is server-authorized, tenant/scenario-scoped, deterministic, versioned,
   checksummed and bounded by explicit per-section and total budgets.
2. Context and audit/log/trace output contain no secrets, credentials, endpoints, Python source,
   document contents, foreign-tenant records or hidden authorization data.
3. System instructions, server context and user description remain separate; prompt injection in
   user/catalog text cannot grant a capability or change validation policy.
4. Only `workflow_candidate` and `capability_missing` structured results are accepted.
5. Every generated reference must exist in the supplied snapshot and current live authorized state;
   invented, foreign, inactive, disabled or stale references fail closed with safe diagnostics.
6. Candidate generation creates zero durable rows and emits no publish/release/activation side
   effect.
7. Valid and invalid candidates remain editable in graph/JSON views; canonical diagnostics identify
   the relevant pointer/node/edge and invalid candidates cannot be saved.
8. Initial transient state is memory-only and protected by dirty-navigation warnings.
9. Explicit save allocates identifiers server-side, locks organization/project/scenario lineage and
   reruns authorization/canonical/reference validation.
10. Existing drafts require explicit update or copy. Update uses optimistic revision concurrency;
    copy receives a new collision-safe logical ID; silent overwrite is impossible.
11. Capability-missing suggestions enter only the normal unsaved Python-node lifecycle and cannot
    bypass automated/human review or activation.
12. Turkish-first UI states clearly separate transient candidate, mutable draft, Python-node review,
    immutable artifact and release lifecycle.
13. Audit/telemetry is bounded and redacted; context checksum/count/byte/token metadata may be
    recorded, while prompts, user text, raw candidates and schemas are not copied to audit/logs.
14. Focused/full SQLite tests and applicable PostgreSQL non-owner/RLS tests, formatter, lint, type,
    Django and migration-drift checks have recorded evidence.

## Affected components

- `apps.orchestration`: authoring prompt/provider contract and bounded result parsing
- `apps.builder`: context service, candidate diagnostics, save/update/copy and identifiers
- `apps.catalog`, `apps.tools`, `apps.documents`, `apps.workflows`: safe scoped catalog adapters
- `apps.console` and `frontend`: unified Studio planner/transient graph/JSON/diagnostics UI
- artifact/release compilation: live reference revalidation without lifecycle bypass
- audit/observability: safe generation/save outcome evidence and bounded metrics
- authoring, builder, console, catalog, tool, release and tenant-isolation tests

## Interfaces affected

The authenticated Studio authoring API gains versioned internal contracts for:

- authoring-context snapshot;
- structured generation result;
- transient diagnostics;
- explicit save/update/copy.

No consumer runtime API or public authentication contract changes. If implementation discovery
requires a new public endpoint or authorization action, stop and obtain explicit owner approval and
update this plan before implementation.

## Data impact

Generation is read-only and transient. Explicit save writes only through the existing tenant-scoped
`WorkflowDraft` lifecycle. Context/candidate bodies are not persisted to audit, logs, traces or
browser storage. Existing draft revision and lineage remain authoritative.

No migration is expected. If durable recovery, new lifecycle records or schema changes become
necessary, stop, update the plan and obtain migration/data/privacy approval.

## Security impact

The principal risks are cross-tenant disclosure, prompt injection, capability invention, stale
snapshot use, mass assignment during save and accidental persistence/logging of model output. The
server constructs and bounds context, separates trusted/untrusted inputs, rejects all references not
in both snapshot and live authorized state, and performs canonical validation at generation response,
save, publish and release compile.

See [threat-model.md](threat-model.md).

## Authorization impact

Existing scenario-author permissions remain authoritative. Context assembly queries each resource
through tenant/action-scoped server services. A model/user-provided role, owner, tenant, scenario or
reference is never authorization proof. Save re-authorizes the chosen update/copy action and locks
lineage server-side.

No authorization contract change is approved by this task plan. Discovered role/action changes
require explicit owner approval before implementation.

## Observability impact

Emit bounded outcome/latency/size counters for context construction, generation parsing,
conformance validation, diagnostics and save. Metric labels use closed outcome classes only. Safe
audit may include actor/tenant/scenario references, action, authorization outcome, context contract
version/checksum, counts, sizes and trace ID. Never record prompt text, user description, raw model
output, Python source, document content, secrets/endpoints or full schemas.

## Migration impact

Expected database migration impact is none. Generation remains transient and save reuses
`WorkflowDraft`. Run migration drift checks. Any newly discovered persistence need is a plan/approval
gate, not an implementation assumption.

## Dependencies

- P2.6.0 committed foundation and ADR-0008/0009/0010
- current canonical workflow compiler/diagnostics and identifier services
- current Scenario Studio graph/JSON/draft/publish lifecycle
- current tenant-scoped tool/model/prompt/retrieval/document-set catalogs
- P2.6.8 safe Python-node public metadata contract before Python-node catalog integration

P2.6.9 context/transient work may proceed before P2.6.8 runtime and P2.6.1 mapping implementation;
it must advertise only capabilities supported by the live compiler.

## Implementation steps

1. Reinspect current authoring provider, builder APIs/services, Studio state, identifier service,
   compiler diagnostics and scoped catalogs; update this plan if the live code differs.
2. Fix context/result contract versions and exact section/entry/schema/byte/token-estimate limits.
3. Implement pure deterministic context serializers per catalog with explicit safe field allowlists.
4. Implement the tenant/scenario-scoped context assembler and canonical checksum.
5. Define strict structured model result schemas and bounded parser/error mapping.
6. Enforce snapshot membership and live authorized-state conformance for every generated reference.
7. Refactor generation so it returns transient candidate/diagnostics and performs no durable write.
8. Integrate the planner into Studio graph/JSON/diagnostics with memory-only dirty state and
   Turkish-first statuses.
9. Implement explicit save/update/copy using server identifiers, lineage checks, live validation and
   optimistic concurrency.
10. Add capability-missing UI/scaffold seam without durable Python-node creation or lifecycle bypass.
11. Revalidate references at publish/release compile and add stale-capability race tests.
12. Update current-behavior/user/architecture documentation and verification evidence.
13. Run repository and PostgreSQL gates, then review the final diff as staff engineer, AppSec and
    SRE before marking implemented/verified.

## Test plan

- Context determinism/checksum, ordering, section and total size/token budget boundaries.
- Safe-field allowlist and secret/endpoint/source/document-content/foreign-tenant exclusion.
- Authentication failure, author action denial and cross-tenant scenario/catalog access.
- Prompt-injection strings in user text and catalog descriptions without authority expansion.
- Strict union parsing, invalid/extra/oversized JSON and bounded repair diagnostics.
- Invented, inactive, disabled, foreign and stale node/tool/prompt/model/retrieval/schema refs.
- Database-query/write assertions proving generation creates no rows or lifecycle mutation.
- Graph/JSON round-trip and pointer/node/edge diagnostics for invalid candidates.
- Memory-only transient state and navigation/reload warning behavior.
- Save happy/invalid/authz/cross-tenant paths, server identifiers and locked lineage.
- Existing-draft update/copy selection, stale revision, concurrent update and collision handling.
- Publish/release stale-reference revalidation and immutable lifecycle regression.
- Capability-missing scaffold remains unsaved and cannot approve/activate/publish.
- Audit/log/trace redaction and bounded metric labels.
- Formatter, Ruff, mypy, Django checks, migration drift, focused/full SQLite and applicable
  PostgreSQL non-owner/RLS suites.

## Rollout plan

- Keep Studio AI independently disabled by default.
- Ship context and structured-result contracts before enabling the UI journey.
- Use deterministic/fake providers in CI and a separately approved model profile for local canary.
- Enable for selected non-production organizations/scenarios after non-disclosure and no-write proof.
- Monitor bounded outcome/latency/size metrics and disable immediately on disclosure/conformance
  anomalies.
- Integrate Python-node catalog metadata only after the P2.6.8 safe contract is merged and retested.

## Rollback plan

- Disable `AI_AUTHORING_MODEL_PROFILE_ID`/Studio planner capability to stop new generation.
- Preserve existing drafts/artifacts/releases; transient candidates disappear without mutation.
- Roll back UI/context code together to a matching contract version.
- Do not delete drafts or reinterpret persisted workflow/release records.
- Remove Python-node metadata adapter exposure independently if its later integration is faulty.

## Risks

- Context construction can disclose foreign-tenant or sensitive catalog data.
- Catalog descriptions and user text can prompt-inject the planner.
- Snapshot-to-save races can approve stale/inactive capability references.
- Large schemas/catalogs can cause token, latency and cost amplification.
- Invalid model output can corrupt Studio state or be accidentally persisted/logged.
- Inline Python-node suggestions can blur transient, draft, review and active states.
- Identifier/lineage fields can become mass-assignment surfaces during update/copy.
- Multiple Studio tabs can overwrite a draft without exact revision enforcement.
- A client-side-only validation path can diverge from canonical compiler behavior.

## Open questions

1. Exact initial budgets per context section, total bytes, schema depth/properties and token estimate.
2. Whether bounded raw invalid model output may be returned to the authenticated browser for repair,
   and its maximum size/redaction policy.
3. Exact transient placeholder ID format and the canonical diagnostic normalization boundary.
4. Whether initial `capability_missing` opens only a metadata scaffold or also a separately requested
   transient source-generation flow; neither may persist automatically.
5. Studio layout details for planner/catalog/diagnostics/lifecycle panels at supported viewport sizes.

These decisions must close as constants, schemas and tests before implementation is marked complete.

## Status

Planned. P2.6.0 is complete; implementation may begin from the approved integration baseline. The
Python-node catalog integration remains dependent on the P2.6.8 safe public metadata contract.

## Completion criteria

`Implemented` requires the complete context, structured-result, transient Studio and explicit-save
journey with tests and current-behavior documentation. `Verified` requires all acceptance criteria,
SQLite/PostgreSQL evidence, non-disclosure/no-write proof and security/SRE review. `Completed`
requires verification closure and integration-owner acceptance without unresolved high-severity
security, authorization or data findings.
