# AgentHub — Phase 2.5 Product Coherence Plan (COMPLETED)

> **Status: COMPLETED AND OWNER-ACCEPTED (2026-07-16).** Parts 1–9 are implemented and verified.
> The owner delegated the final local Turkish journey to Codex; authenticated browser/API evidence,
> full SQLite/PostgreSQL/frontend gates and the Part 9 review passed. PostgreSQL production-role and
> real external-profile evidence remain explicit Phase 2 live-closure carryover rather than being
> silently treated as verified. Planning does not authorize authentication/authorization,
> tenant-isolation, public-API, dependency, secret, IAM, network or production mutations; each
> applicable implementation increment retains the explicit approval gates in `AGENTS.md`.

## Purpose

Turn the implemented platform capabilities into one coherent Turkish-first product flow. Phase 2.5
must make organization context, domain relationships, document ingestion/indexing, scenario
authoring and public invocation understandable without exposing internal IDs or forcing operators to
assemble the architecture from separate screens.

Phase 2.5 is a required predecessor of the Phase 2 live activation and smoke/rollback closure. It
does not include production activation, persistent server-side conversation history, Personal MCP,
or upload malware/type scanning.

## Owner decisions

- Add an organization overview at `/console/o/<organization-slug>/` while preserving the existing
  canonical list/detail/action URLs for projects, scenarios, document sets, client applications,
  artifacts and releases. Object pages infer and visibly show organization context from the
  authorized target; links do not need a bulk URL migration.
- Keep `/console/` as the dashboard. Show the organizations available to the signed-in user on the
  dashboard with active/disabled state; the organization name opens its workspace overview.
- Keep platform-wide observability/administration outside the tenant workspace; every operational
  action is scoped to the active organization and still authorized server-side.
- Every named domain object links to its detail page. Relationship lists are bidirectional and
  navigable.
- Console creation flows request human names and business settings, not slugs, logical IDs or API
  aliases. The system generates stable identifiers.
- Put the full architecture, artifact catalog and DSL rules in detailed documentation first; an
  in-product architecture tutorial is not required for Phase 2.5.
- Let an existing scenario be exposed through MCP and/or an HTTPS compatibility endpoint. For an
  HTTPS exposure, default the adapter to OpenAI-compatible `/v1/chat/completions`; `/v1/responses`
  remains an explicitly selected alternative rather than an automatically enabled second route.
- Keep the output contract optional and selectable when composing the scenario release/exposure.
  When selected, pin its immutable artifact version and enforce it at the runtime output boundary.
- Conversation history is client-supplied in Phase 2.5. Server-side persistent conversation history
  moves to Phase 3.
- Provide a broad, composable, allowlist-based transform DSL. Do not execute arbitrary Python in
  the application web/worker processes.
- Responsive-width and keyboard/screen-reader manual acceptance remain waived. Turkish terminology
  and complete operator journeys remain required human review.

## Part-based delivery plan

Phase 2.5 is delivered in reviewable parts rather than treating each product heading as one large
implementation. A part is a sprint-like delivery boundary: it has one primary outcome, explicit
approval gates, its own task plan/threat model/verification record and can be reviewed without
assuming a later part is complete.

| Part | Outcome | Phase 2.5 mapping | Main gate |
| --- | --- | --- | --- |
| Part 1 | **Owner-accepted for progression; implemented/offline-verified, PostgreSQL non-owner evidence carried to closure.** Dashboard, organization overview and secure navigable domain graph | P2.5.1 navigation subset + P2.5.2 documentation baseline | Tenant-scope implementation approved 2026-07-14; progression accepted 2026-07-15 |
| Part 2 | **Completed, owner-accepted, and verified.** System-generated identifiers and coherent creation forms | P2.5.1 identifier subset | Full SQLite/PostgreSQL, migration, authorization and compatibility evidence recorded 2026-07-15 |
| Part 3 | **Completed, verified and owner-accepted.** Durable project ownership and consumer credential lifecycle | P2.5.1 ownership/consumer subset | Authenticated token issue/one-time display/revoke/restore and redacted audit journey passed 2026-07-16 |
| Part 4 | **Completed, verified and owner-accepted.** Document-set-first content lifecycle | P2.5.3 | Full authorization/storage regression plus integrated organization relationship journey accepted 2026-07-16 |
| Part 5 | **Completed, verified and owner-accepted.** Unified source, mapping and index journey | P2.5.4 | Full egress/mapping/index regression and local active synthetic index evidence accepted 2026-07-16 |
| Part 6 | **Completed, verified and owner-accepted.** Scenario-isolated JSON/graph authoring, optimistic concurrency and immutable artifact candidate composition | P2.5.5 + P2.5.2 authoring sections | Scenario-scoped JSON → graph → config → validate → publish browser journey passed 2026-07-16 |
| Part 7 | **Completed, verified and owner-accepted.** Versioned governed transform/chunking/retrieval contracts and bounded runtime | P2.5.6 + P2.5.2 DSL sections | Full closed-registry, resource-limit and ACL non-bypass evidence accepted 2026-07-16 |
| Part 8 | **Completed, verified and owner-accepted.** OpenAI-compatible invocation adapters | P2.5.7 | Authenticated Chat/Responses and REST/MCP positive/cross-protocol denial smoke passed 2026-07-16 |
| Part 9 | **Completed, verified and owner-accepted.** Integrated hardening and Phase 2 closure handoff | Phase 2.5 acceptance | Full regression, canonical image build, Turkish journey, credential disable/restore, audit and rollback evidence recorded 2026-07-16 |

The architecture/artifact/DSL guide is a cross-cutting deliverable, not a one-time documentation
sprint. Every part updates the guide in the same change when it introduces, clarifies or retires a
contract. Part 1 establishes its terminology, authority map and current-versus-target status; Parts
2–5 add identity, lineage and source contracts; Part 6 reconciles the complete scenario authoring
contract; Part 7 replaces the transform/retrieval target text with the implemented versioned
contract; Part 8 adds invocation/adaptation rules; Part 9 performs final code-to-guide drift review.

Detailed Part 1 plan:
[`phase-2-5-part-1-workspace-navigation`](../tasks/phase-2-5-part-1-workspace-navigation/plan.md).

Detailed Part 2 plan:
[`phase-2-5-part-2-system-identifiers`](archive/phase-2-5-part-2-system-identifiers-2026-07-15/plan.md).

Detailed Part 3 plan:
[`phase-2-5-part-3-ownership-credentials`](../tasks/phase-2-5-part-3-ownership-credentials/plan.md).

Detailed Part 6 plan:
[`phase-2-5-part-6-scenario-studio`](../tasks/phase-2-5-part-6-scenario-studio/plan.md).

Detailed Part 8 plan:
[`phase-2-5-part-8-openai-compatible-invocation`](../tasks/phase-2-5-part-8-openai-compatible-invocation/plan.md).

## P2.5.1 — Organization overview and navigable domain graph

### Information architecture

```text
Organization
├── Projects
│   └── Scenarios
│       ├── DSL / graph
│       ├── Artifacts
│       └── Releases
├── Document sets
├── İstemci uygulamalar (teknik model: Consumer) ve bağları
└── Organization settings
```

`DocumentSet` and `Consumer` remain organization-owned canonical objects and do not appear as
project children. Navigation between scenarios, document sets and consumers is provided by their
bidirectional relationship sections; the organization-level lists remain the complete inventory.

### Active organization contract

- `/console/` remains the operator dashboard. Its organization section lists only organizations the
  user may access, shows each active/disabled state and links the organization name to
  `/console/o/<organization-slug>/`.
- An authorized member may open a disabled organization's overview in an explicitly read-only
  state. Operational mutations are unavailable and denied server-side until the organization is
  active; inaccessible and nonexistent organizations retain indistinguishable not-found behavior.
- Opening an organization overview or a target-object detail/action establishes one relevant
  organization from an authorized `OrganizationMembership`; URL/object identifiers are never
  accepted as authorization by themselves.
- Regular operators may select only organizations where they have an active membership. Platform
  administrators may switch across organizations through an explicit, visibly privileged control.
- Organization-context forms, lookups, autocomplete choices and mutations are narrowed to the
  trusted relevant organization. Cross-organization consumer/scenario combinations are therefore
  impossible in normal UI use.
- Backend same-organization validation, app predicates and PostgreSQL FORCE RLS remain mandatory
  defense in depth. Integrity errors are not removed merely because the UI prevents them.

### Detail pages and required cross-links

- Organization: projects, document sets, consumers, members/roles and settings.
- Organization workspace overview: organization identity/status plus its projects, scenarios,
  document sets, istemci uygulamalar, artifacts and releases. Names link to their detail pages.
- Project: scenarios, owner/member, risk and lifecycle state. It does not list document sets or
  consumers as children.
- Scenario: full DSL/graph, pinned/current artifacts, releases, document sets, bound consumers,
  aliases and recent governed runs.
- Document set: contained documents/versions, sources, set/index versions, bound scenarios and
  effective consumer grants. Scenario and consumer names link to their detail pages.
- Consumer: stable subject, authentication mode, token metadata, scenario bindings, effective
  document-set grants and recent usage. Scenario/document-set names link back.
- Artifact: body/DSL, versions, scenarios/releases pinning the exact version and reusable scope.
- Release: scenario, exact pinned artifacts, evaluation/promotion state and rollback lineage.
- Every list uses the object's display name as the primary link; internal IDs may appear only as
  secondary diagnostics where operationally necessary.

### System-generated identifiers

- Organization, project, scenario, document set, document and consumer console flows ask for a
  display name, not a slug/logical ID.
- Generate immutable internal/public identifiers server-side. Human-readable slugs are derived from
  the name and receive a collision-resistant suffix; renaming a display name does not silently break
  stable URLs or external contracts.
- Generate scenario API aliases as `project-scenario-xxxx` (four random characters, collision
  checked inside the organization). The console does not ask users to invent aliases.
- GitOps/import APIs may retain explicit stable identifiers for idempotent declarative workflows;
  this exception is not exposed as a normal console creation field.

### Human users, membership and project ownership

Human console users are not owned by exactly one organization. `OrganizationMembership` links a
user to one or more organizations with an organization-scoped role. This is required to determine
which tenant data and actions the person may access. A project owner must be selected from the
active organization's eligible memberships; a user outside the organization cannot be assigned.
Phase 2.5 should replace the current free-text project-owner persistence with a durable membership
or user reference through an additive compatibility migration.

### Consumer creation and credentials

A consumer is a machine/application identity, not a human membership. The current default gateway
authentication is a bearer `ConsumerToken`:

Current-state gap: the console currently asks the operator for the raw `subject` and creates only
the `Consumer` row; it does not issue or display a token. Tokens are currently issued separately by
the `create_consumer_token` management command. In bearer mode the subject is a stable unique
machine label used for organization-scoped identity, audit and token-management lookup; the bearer
token is the actual credential presented to the gateway.

- In default bearer mode, the console generates an opaque stable consumer subject; the operator
  supplies only a display name and protocol.
- A token is required for the consumer to call `/v1/*` or MCP. Token issuance is a separate
  explicit action after consumer creation, supports multiple named tokens, and shows plaintext once.
- Only the token hash and a safe prefix are stored. The detail page supports rotation/revocation and
  never displays an existing plaintext token.
- `OIDC sub`, service-account identifier or mTLS certificate subject is supplied only when that
  authentication mode is actually configured. The raw help text “Stable authenticated subject…” is
  replaced by mode-specific Turkish guidance and is not shown as an unexplained required field.

Adding console token issuance or changing authentication modes is an authentication/secrets change
and therefore requires explicit implementation approval, audit/redaction tests and rollback design.

## P2.5.2 — Architecture, artifact catalog and DSL documentation

Create detailed documentation before adding further in-product help. At minimum it must define:

- Organization → project → scenario ownership and isolation.
- Organization-level document sets/consumers and their scenario relationships.
- Source → document → immutable document version → document-set version → index version lineage.
- Scenario draft → immutable artifacts → compiled release → promoted runtime behavior.
- Consumer authentication → scenario alias binding/capability → document-set grant authorization.
- Every artifact type, schema, required/optional fields, bounds, examples, validation codes,
  versioning rules, compatibility expectations and release role.
- Complete workflow/agent/retrieval/transform DSL grammar, node/edge contracts, copyable LLM prompt
  sections, valid examples and invalid examples with diagnostics.
- The difference between a workflow node and an artifact: nodes live inside a
  `workflow_definition`; a release may pin multiple independent artifact roles.

### Artifact reuse decision

Published immutable artifacts are reusable by multiple projects and scenarios inside the same
organization. The registry key is organization + artifact type + logical ID + version, and each
release pins an exact version/checksum. Reuse never creates mutable shared behavior: changing an
artifact creates a new version and does not alter existing releases. Cross-organization reuse is
denied; copying to another organization creates separate lineage. Project-scoped mutable drafts may
seed or publish organization-scoped artifacts but do not themselves become cross-project shared
runtime state.

The scenario create/edit journey must expose this reuse deliberately: authors can search and select
compatible published artifact versions from the active organization instead of recreating them.
The authoring guide and Scenario Studio must explain exact-version/checksum pinning, type
compatibility, the effect on existing releases and when a new artifact version is required.

Authoritative documentation entry point:
[`artifacts-and-dsl-authoring-guide.md`](../architecture/artifacts-and-dsl-authoring-guide.md).

## P2.5.3 — Document-set-first product model

- Remove the standalone document inventory from primary navigation. Retain any elevated
  storage/purge inventory only as an explicitly advanced administration surface.
- Create, upload, replace, add, remove, tombstone and inspect documents from a document-set detail
  journey. Bulk upload is the default; file names produce display titles and stable system IDs.
- Organization and document-set creation no longer request slugs/logical IDs.
- A document remains a technical versioned storage/lineage entity because one immutable version may
  be pinned safely, audited and reused. The user-facing product treats it as content managed inside
  document sets.
- Display one lifecycle: uploaded → parsed/normalized → set draft → set version published → staged
  index built/evaluated → active index promoted. Each state exposes its blocking reason and next
  authorized action.
- Set and document pages cross-link their scenarios, consumers, sources, versions and active index.

## P2.5.4 — Unified source, mapping and indexing journey

### Why REST source and REST mapping are different

- A platform profile owns the approved endpoint, credential reference, CA/private-network policy,
  timeout and response bounds.
- An immutable mapping contract describes how a bounded JSON response becomes canonical documents:
  record pointer, identity/title/content pointers, allowlisted inputs and metadata.
- A source instance binds one approved profile revision and one mapping-contract revision to a
  document set plus safe operator inputs and refresh policy.

The separation is required for secret isolation, reuse, review, reproducibility and safe remapping,
but users should not have to assemble it across unrelated screens.

### Source wizard

1. Choose upload, Confluence or generic REST.
2. Select an organization-authorized platform profile; endpoint and secret values stay hidden.
3. For REST, select an existing mapping contract or create a new revision in the wizard.
4. Validate against a bounded synthetic/sample response without opening an unapproved network call.
5. Preview only safe derived metadata and normalized output shape.
6. Bind the source to the current document set and choose manual or approved periodic refresh.
7. Run sync and show fetch, mapping, parse, changed/unchanged and draft-candidate counts.

### Normalization and change flow

- Upload PDF/DOCX/XLSX/text/HTML/JSON and connector payloads through the governed parser/mapping
  boundary into canonical normalized text/Markdown plus safe metadata.
- Compute source identity and checksums before creating versions. Unchanged source content creates
  no new `DocumentVersion`, is not reparsed/re-embedded and reuses compatible vectors.
- Changed/new/deleted items are visible before a new document-set draft is accepted.
- A sync never changes the active index directly. It produces a draft candidate; publishing,
  staged build/evaluation and promotion remain explicit governed steps unless an already-approved
  automation mode performs those exact gates.

### Required statuses and navigation

Show source health/last sync, per-run counts and safe failure codes; document parse/normalization;
set draft/published version; index building/promotable/active/failed; embedding/reuse counts. Every
source, document set, scenario and consumer reference links to its corresponding detail page.

## P2.5.5 — Unified scenario studio

- One scenario page shows the complete authored and active definitions, not disconnected artifact
  fragments.
- Accept canonical DSL/JSON, run server-side validation and display pointer-bound diagnostics.
- Render a valid workflow definition as a visual graph; graph edits round-trip through the same
  canonical compiler rather than introducing a second schema.
- Include the detailed copyable LLM authoring contract from P2.5.2.
- Show workflow/agent definition, input/output contracts, prompt/model/retrieval/tool bindings,
  document sets, consumers, exact active release artifacts and release history.
- When creating or editing a scenario draft, allow the author to select compatible published
  immutable artifact versions already available in the same organization. The selector shows
  artifact type, display/logical identity, exact version and checksum/status; it excludes
  cross-organization and type-incompatible artifacts. Selecting an existing artifact creates only
  a draft/reference or release-manifest pin and never mutates the reusable artifact. A new artifact
  version remains an explicit authoring action, and publish/release/promotion gates remain separate.
- Preserve draft → diagnostics → explicit transfer → immutable publish → release compilation gates;
  neither DSL editing nor AI candidates auto-publish or auto-promote.

## P2.5.6 — Flexible governed retrieval and transform DSL

### Meaning of an allowlist-based DSL

The DSL is declarative JSON/YAML that composes platform-implemented operations. Users describe
*what* transformation is required, while the platform executes only registered operations with
validated schemas. It has no `eval`, imports, arbitrary function calls, filesystem, subprocess,
network access, secret lookup or unbounded loops/recursion.

Initial operation families should include:

- Select/rename/drop fields with JSON Pointer paths.
- Flatten/nest records; explode bounded arrays; map records; deduplicate by stable keys.
- Filter with typed comparisons and bounded boolean expressions.
- Coalesce/default, type conversion, date/number parsing and validation.
- Whitespace/Unicode normalization, bounded replace, split/join and safe template composition.
- Construct title/content/metadata; preserve source identity and lineage.
- Chunk by characters/tokens/headings/pages/tables with overlap and hard bounds.
- Select keyword/vector/hybrid retrieval, weights, metadata filters, top-k, thresholds and an
  allowlisted reranker profile.
- Conditional branches over typed metadata with a bounded step/depth/output budget.

Every operation has a versioned schema, deterministic behavior, input/output limits, safe error
codes, preview fixtures and canonical serialization. A pipeline has maximum steps, nesting, input
bytes, records, output bytes and execution time. New operations are added through reviewed platform
code/plugins, not tenant-supplied Python.

This supports broad data manipulation through composition while keeping execution auditable and
tenant-safe. If a future use case truly requires Python, it needs a separately approved isolated
sandbox service with no network/secrets, immutable package allowlists, signed code, CPU/RAM/time and
output limits; it is not part of Phase 2.5.

## P2.5.7 — OpenAI-compatible invocation and client-supplied history

- Preserve `/v1/query`, `/v1/invoke` and their existing `scenario_alias` contracts.
- Treat MCP and HTTPS as explicit scenario exposure choices; enabling one does not implicitly
  enable the other. Preserve the governed MCP invocation path.
- Add selectable `/v1/chat/completions` and `/v1/responses` HTTPS compatibility adapters, with
  `/v1/chat/completions` as the default for a new HTTPS exposure. This is an additive public API
  change and requires a dedicated compatibility/threat-model task before implementation.
- Keep the output contract selector optional. If an output contract is selected, pin the exact
  immutable version into the release/exposure and enforce it after scenario execution; if it is
  omitted, the adapter still applies its own bounded response-envelope validation but does not
  invent or infer a business output schema.
- Route the OpenAI-compatible `model` value through the authenticated consumer's bound generated
  scenario alias; never accept raw project/scenario/release IDs as authority.
- Support bounded client-supplied `messages`/input history and map it into the scenario input
  contract. Apply message count, role, per-message, total-character/token and attachment bounds.
- Do not persist a server-side conversation/thread transcript in Phase 2.5. Keep audit/usage data
  content-free and redacted. Persistent conversation memory, retention/export/deletion and
  user-scoped authorization are Phase 3 work.
- Document supported and intentionally unsupported OpenAI fields, streaming/tool behavior, stable
  error mapping, idempotency, rate limits and compatibility-version policy.

## Security, authorization and operational risks

- Organization URL context can become an insecure direct-object reference if trusted without
  membership/action checks; retain server-side authorization and RLS negative tests.
- Generated identifiers must use collision-safe, non-predictability-appropriate primitives and
  must not expose database primary keys as public authority.
- Token plaintext is a secret shown once; audit only safe token metadata and fail closed if secure
  issuance cannot complete.
- Bidirectional relationship pages can leak tenant data through counts, labels or links; scope every
  query and test cross-tenant empty/404 behavior.
- Transform flexibility can become arbitrary code execution or resource exhaustion; enforce the
  closed operation registry and global budgets at the runtime boundary.
- OpenAI compatibility expands a public API and untrusted payload surface; use explicit schemas,
  bounded history, existing authentication/capability/rate-limit/idempotency controls and redaction.
- Removing user-entered identifiers requires compatibility aliases/redirects and additive migration;
  existing GitOps refs, releases and external aliases cannot be silently renamed.

## Verification and acceptance

- Unit/integration/negative tests for active-org switching, forged org URLs, cross-tenant links,
  form choices, relationship counts and mutations.
- Migration compatibility and rollback evidence for system identifiers, project owner references
  and any new relationship/index fields.
- Complete Turkish manual journeys for organization → project → scenario → document set/consumer →
  DSL/release and the reverse cross-links.
- Source wizard tests for upload/Confluence/REST, invalid mapping, unchanged/changed/deleted content,
  partial failure, retry/idempotency, draft/index/promotion and redacted audit.
- DSL schema/property/boundary tests; unknown operation, oversized/deep pipeline, injection-like
  strings and cross-tenant profile references deny safely.
- OpenAI contract fixtures for both endpoints, legacy gateway regression, auth/capability denial,
  bound/unbound alias, bounded history, rate limit, idempotency, error compatibility and redaction.
- Full repository formatter/linter/type/unit/integration/PostgreSQL/migration/security gates plus
  staff-engineer, AppSec and SRE final-diff review.

## Exit criteria

All increments are separately implemented and verified; current-behavior and architecture docs
match the product; no unresolved critical/high finding remains; Turkish operator journeys receive
owner sign-off. Phase 2.5 then hands off to the separately gated Phase 2 live-environment closure
plan. Phase 2 does not close merely because Phase 2.5 is complete.
