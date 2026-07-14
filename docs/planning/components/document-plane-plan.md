# Document Plane Plan (Phase 2 · Workstream 1)

## Objective

Deliver a governed **document plane**: tenant-owned document content as first-class,
independently managed objects; a mandatory scenario↔document-set binding; deny-by-default,
tenant- and document-set-scoped retrieval authorization (with PostgreSQL RLS as a second
layer); real connectors, parsers, and an OpenAI-compatible embedding provider; and staged,
metadata-atomic reindex/promotion over immutable per-`IndexVersion` embedding stores. This is
Phase 2 priority #1 (see [`../phase-2-plan.md`](../phase-2-plan.md)) and supersedes the
Sprint 5 "one org-scoped `Source` → one index" model as the retrieval trust unit.

## Owner or responsible area

Project owner (approver of dependencies/egress). Implementing area: `apps/ingestion`
(build/index plane), a new `apps/documents` (content plane), `apps/retrieval` (ACL-scoped
query), `apps/releases` + `apps/orchestration` (pinning/resolution), `apps/console` (operator
UI). Consumer gateway seam unchanged in contract.

## Status

**Decisions A–E approved by the owner on 2026-07-12. M0–M3 and M5 are implemented; M4 local
parsers and external OCR are implemented while connectors remain gated.** Content storage,
embedding/indexing, binding + effective consumer ACL retrieval, FORCE RLS stores, runtime wiring
and the operator console are landed. Per-phase external-egress sign-off remains. The M0 outputs:

1. pgvector multi-dimension storage → [ADR-0003](../../adr/0003-vector-storage-blue-green-per-index-version.md);
2. RLS connection-context → [ADR-0004](../../adr/0004-tenant-isolation-postgres-rls-connection-context.md);
3. shared SSRF-safe egress adapter → [ADR-0005](../../adr/0005-shared-ssrf-safe-egress-adapter.md).

New production dependencies and new external egress each still require a separate explicit
owner approval + supply-chain/threat review at the milestone that introduces them.

## Scope

- Content-plane data model: `Source → Document → DocumentVersion → Blob(object)`, plus
  `DocumentSet → DocumentSetVersion → DocumentSetMembership`, a forward-ready ACL grant model,
  and a mandatory `ScenarioDocumentSetBinding`. `tenant_id` mandatory and immutable at every level.
- Deny-by-default retrieval: a scenario retrieves only from the `DocumentSetVersion`s it is
  explicitly bound to, within its tenant; all scoping is server-side from the signed
  `ExecutionContext` + release manifest. Client-supplied tenant/document-set filters are ignored.
  **PostgreSQL RLS** enforces a fail-closed second layer.
- Platform-managed **`EmbeddingProfile`** catalog (provider/model/revision/dimensions/metric/
  normalization/endpoint+secret ref/index-type); no embedding model hard-coded in the schema.
  Real OpenAI-compatible embedding egress over the Sprint 9 SSRF-safe transport, with staged,
  metadata-atomic reindex over immutable per-`IndexVersion` embedding stores.
- Real parsers (pdf/txt/docx/xlsx→markdown) behind a `DocumentParser` interface; image-only
  pages and embedded images dispatched to the **owner-hosted external OCR endpoint** (no
  in-app OCR). Parser dependency selection is comparison-driven and deferred (decision E).
- New connectors: drag-drop **upload** (system source), **Confluence** (by id), **generic REST**.
- Soft-delete (tombstone) as the default removal; a separate, auditable **physical purge**; a
  **retention/purge job** for superseded index stores no longer referenced by any release.
- Operator console UI for per-scenario document sources, set membership, binding, upload,
  soft-delete, and purge — reusing the Sprint 1 console LDAP/session identity + role/tenant
  authorization (no separate auth, no consumer-gateway path, non-authoritative frontend).

## Non-goals

- Person/group-level document authorization **enforcement** (schema is made forward-ready in
  this workstream, but `user`/`group` principals require the Phase 3 personal-MCP identity design).
- AI-assisted authoring and Turkish UI restyle (Workstreams 2 and 3).
- Replacing the Sprint 6 release lifecycle, Sprint 9 tool egress, or the consumer gateway
  authorization contract; the document plane composes with them, it does not fork them.
- Per-scenario **physical** pgvector indexes (rejected in decision A; the physical boundary is
  the tenant, the logical retrieval/ACL unit is the document-set version). Physical isolation is
  **per-`IndexVersion` immutable store**, not per-scenario.
- Adding the `openai` dependency for embeddings at this stage (decision 3); using the `openai`
  library's custom `base_url` as an egress control (its flexibility is not an SSRF control).

## Current state

- `apps/ingestion` (Sprint 5): `Source` (org-scoped connector, `https`/`s3` only), pipeline
  (`text` parser, `fixed` chunker, `deterministic` 64-dim embedder), `IndexVersion`
  (**source-scoped**), an index-scoped `Document` (belongs to an `IndexVersion` — a *build*
  artifact, not a managed content object), and `Chunk` with a fixed `VectorField(dimensions=64)`
  HNSW index. See [`apps/ingestion/models.py`](../../../apps/ingestion/models.py).
- `apps/retrieval`: `PgvectorRetrievalProvider.retrieve(query, profile, organization_id,
  index_versions)` filters by `organization_id` + pinned `index_version_id__in` +
  promotable/active status only. **No document-set/per-document ACL layer and no RLS exist yet.**
- Pinning seam: release manifest pins `index_versions`;
  [`apps/orchestration/resolver.py`](../../../apps/orchestration/resolver.py) reads them and
  [`apps/orchestration/runtime.py:103`](../../../apps/orchestration/runtime.py) passes
  `bundle.index_versions` to the retriever. The document-set layer hooks **above** this seam and
  promotion becomes a pointer flip on the pinned id (below).
- `EMBEDDING_DIMENSIONS = 64` is hard-coded on the vector column; there is no embedding-provenance
  record and no per-`IndexVersion` physical store.
- Removal is not modeled; there is no soft-delete/tombstone or purge path.

## Target state

### Content plane — `apps/documents` (new app)

Immutable, tenant-scoped content lineage. `tenant_id` (organization) FK is **mandatory and
never mutated** on every model below; all are RLS-protected tenant data-plane tables.

- **`Source`** (reuse/extend `apps/ingestion.Source`): add `source_type ∈ {https, s3, upload,
  confluence, rest}`; `upload` is a system source. Keep the existing inline-credential ban and
  connector-config allowlist; new connectors carry only `secret:<name>` references.
- **`Document`** (canonical content object): `organization`, `source` (provenance;
  upload→system source), `logical_id`, `title`, `current_version`, `lifecycle_state ∈ {active,
  tombstoned}`, `created_at`, `deleted_at`.
- **`DocumentVersion`** (immutable): `document`, `version`, `checksum` (sha-256), `mime_type`,
  `object_key` (tenant-prefixed blob key), `byte_size`, `parser`, `parse_status`, element/page
  metadata (counts only). Bytes live in the object store (MinIO/S3) under a tenant prefix.
- **`DocumentSet`**: the **logical ACL/retrieval unit**. `organization`, `logical_id`, `name`,
  `status`.
- **`DocumentSetVersion`** (immutable published snapshot): `document_set`, `version`,
  `embedding_profile`, `built_index_version` (FK into the build plane), `status ∈ {draft,
  building, promotable, active, superseded}`. Membership is frozen at publish.
- **`DocumentSetMembership`** (immutable within a version): `document_set_version`,
  `document_version` (pinned exact version), ordinal/metadata.
- **`ScenarioDocumentSetBinding`** (mandatory): `scenario` × `document_set`. A scenario with
  retrieval **must** have at least one binding or it retrieves nothing (deny-by-default). At
  release-compile time each binding resolves to a specific published `DocumentSetVersion`.
- **`DocumentSetGrant`** (forward-ready ACL): `document_set`, `principal_type ∈ {consumer,
  service, user, group}`, `principal_ref`, `permission`. **WS1 enforces only `consumer` +
  scenario-binding**; `user`/`group` rows may exist but are inert until Phase 3 identity/delegation.

### Build/index plane — `apps/ingestion` (extended)

- **Rename** the existing index-scoped `Document` → **`IndexedDocument`** to free the `Document`
  name for the content plane. The migration uses Django `RenameModel` — it **preserves existing
  rows, primary keys, and all FK relationships (no drop/recreate)**; `Chunk.document` and
  `select_related("document")` follow the rename. `IndexedDocument` gains an optional link to the
  canonical `DocumentVersion` recording which content it was built from / which index snapshot it
  entered.
- Re-scope **`IndexVersion`** from `source` to **`(organization, document_set_version,
  embedding_profile)`** — the tenant+corpus retrieval unit that multiple scenarios reuse. Each
  `IndexVersion` is immutable once built.
- **`EmbeddingProfile`** — a **platform-managed catalog** (not tenant-created; see below).
- **Per-`IndexVersion` immutable embedding store**: each `IndexVersion` owns a
  **dimension-fixed** physical embedding store/table and its own HNSW index. **Physical
  store/table names are generated safely by the system** (derived from the `IndexVersion`
  identity via a fixed template), never from application/user/tenant input. Active and staged
  `IndexVersion`s of **different** profiles/dimensions therefore coexist without conflict
  (blue/green). `Chunk` rows carry `document_version`, `document_set_version_id`, and `tenant_id`.
- **Dimension/index-type validation at the start of ingestion**: reject an unsupported dimension
  for the chosen index type — **no silent truncation** (e.g. never 4096→4000). Grounding:
  pgvector builds an ANN (HNSW) index only over uniform-dimension rows; HNSW supports up to
  **2000 dims for `vector`** and **4000 dims for `halfvec`**. The chosen `index_type`
  (`vector`/`halfvec`) and `dimensions` on the `EmbeddingProfile` must be compatible or the build
  is rejected before any embedding call.

### EmbeddingProfile — platform-managed, immutable, revisioned ([ADR-0002](../../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md))

- Platform administrators define profiles; **tenants cannot create free endpoint/model/profiles**
  and may only **select among profiles allowlisted to them** (a `TenantEmbeddingProfileGrant`).
- **Artifacts and the runtime reference an `EmbeddingProfile` by ID only.** A tenant, artifact,
  prompt, or request may **not** set `base_url`, host/port, scheme, credential/secret selection, or
  TLS-verification behavior — the catalog is a *managed profile catalog*, not a string host
  allowlist. The same rule governs the chat `ModelProfile` (WS5).
- A **used profile is never modified in place**. Any change to provider, `model_id`,
  `model_revision`, `dimensions`, `normalization`, `distance_metric`, or `index_type` creates a
  **new `EmbeddingProfile` revision** and a **new staged reindex**. A future tenant-specific
  profile is still created by a platform admin and assigned to only that tenant.
- The endpoint is a **platform-allowlisted destination** resolved from the profile; `secret_ref`
  is a `secret:<name>` reference.

### Embedding egress — SSRF-safe adapter (no `openai` dependency)

- `OpenAICompatibleEmbeddingClient` is an adapter over the **Sprint 9 SSRF-safe stdlib
  transport** (`apps/tools/egress`): it **reuses** the existing target/scheme/host validation,
  DNS→resolved-IP pinning (anti-rebinding), redirect-denial, **TLS certificate verification**,
  connect/read timeouts, response-size cap, private/link-local/metadata blocking, and redacted
  audit. **No `openai` dependency is added.** The endpoint comes from the selected
  `EmbeddingProfile` (platform catalog, ID-referenced); the model name comes from that profile.
  The `openai` library's custom `base_url`/transport hooks are explicitly *not* used as an egress
  control (that flexibility is not an SSRF defense).
- **Idempotency:** an embedding call that fails *after the request is sent* (read timeout) is
  **not** blindly retried — a retry risks double cost and divergent vectors. Retries are limited
  to safe pre-connection failures; a post-send failure is treated as an unknown outcome and the
  chunk/build is failed for controlled re-drive, never silently re-sent (ADR-0002).

### Retrieval — deny-by-default effective authorization (app predicate + RLS)

Effective retrieval scope =
**(scenario ↔ document-set bindings, pinned to versions in the release manifest)
∩ (consumer authorized to the scenario)
∩ (tenant_id from the signed `ExecutionContext`)**,
resolved entirely server-side. Concretely:

1. Gateway authenticates consumer + tenant and signs `ExecutionContext` (carries `org_id`).
2. Scenario authorization runs as today (binding/capability).
3. The release manifest pins `document_set_version_ids` (compiled from the mandatory
   `ScenarioDocumentSetBinding`); the resolver expands them → their active `index_version_ids`
   and carries the `document_set_version_ids` forward.
4. `PgvectorRetrievalProvider` filters `organization_id = ctx.org` **AND**
   `index_version_id IN (pinned)` **AND** `document_set_version_id IN (pinned)` **AND**
   `document.deleted_at IS NULL` **AND** index status promotable/active. No filter comes from
   the client.
5. **RLS second layer** (below) rejects any row whose `tenant_id` does not match the
   transaction-local tenant context — a fail-closed backstop against a missing app predicate.

### PostgreSQL RLS — fail-closed defense-in-depth

- RLS is enabled with `FORCE ROW LEVEL SECURITY` on tenant-scoped **data-plane** tables. The
  application DB role is **not the table owner** and does **not** hold `BYPASSRLS`, so
  `FORCE ROW LEVEL SECURITY` applies policies to it (owners would otherwise bypass RLS).
- Each request/worker data operation, **after opening its transaction**, establishes
  **transaction-local** tenant context from the trusted signed context:
  `SELECT set_config('app.tenant_scope', <server-derived-scope>, true)` (the `true`/`is_local` flag scopes it
  to the transaction so it never leaks to the next operation on a pooled connection). Policies
  call `agenthub_tenant_scope_contains(organization_id)`; if the setting is missing
  or invalid the policy returns **no rows** (fail-closed). No session-level tenant state is left
  on the pool.
- **Control-plane / global worker-claim tables are separated from tenant data-plane tables.** The
  worker is **not** given a broad role that bypasses all tenant tables; cross-tenant management
  runs through a separate, auditable admin function/role.
- RLS is documented as a **second layer against a missing tenant filter, not a replacement** for
  application authorization.

## Interfaces

- **Console operator JSON API** (session/LDAP, CSRF, role/tenant-scoped — *not* the consumer
  gateway, no CORS): document-set CRUD, membership edit, `ScenarioDocumentSetBinding` manage,
  upload (multipart → object store → `Document`/`DocumentVersion`), soft-delete, purge, source
  CRUD for new connectors. Read is membership-scoped; write requires the existing authoring role;
  purge requires an elevated role.
- **`DocumentParser` interface**: `parse(blob, mime_type) -> ParsedDocument(markdown, elements)`;
  registry keyed by mime/type, same shape as the existing `PARSERS` registry.
- **Embedding provider interface**: extends the existing `EMBEDDERS` seam with the
  `EmbeddingProfile`-driven `OpenAICompatibleEmbeddingClient`.
- **OCR egress client (implemented P7.3)**: whole-PDF multipart submit to the owner-approved async
  `/api/v1` service, bounded polling, raw Markdown result and durable-result-before-idempotent-ACK
  ordering. Immutable `OcrProfile` + tenant grant; tenant/request/service URLs are never followed.
- **Release/resolver**: manifest gains `document_set_versions`; resolver expands to the active
  `index_versions` (backward-compatible — existing pinned-index releases keep working).
- **Promotion is a pointer flip**: see Data flows.
- Consumer gateway `/v1/query` / `/v1/invoke` **contracts unchanged**.

## Data flows

- **Ingest**: source/upload → `Document`+`DocumentVersion` (checksum, mime, object_key) →
  dimension/index-type validated against the `EmbeddingProfile` → parser (→ OCR egress for
  images) → chunker → embedding egress (profile) → `Chunk` rows written into the **new immutable
  per-`IndexVersion` store** for a staged `DocumentSetVersion`.
- **Publish/promote (metadata-atomic)**: a staged `IndexVersion` is built and eval'd (reuse
  Sprint 6 governed eval against the candidate). **Promotion does NOT rename tables, copy data,
  or rebuild indexes.** It flips the active `index_version_id` pointer on the release/binding
  record **within a single transaction**, so promotion and rollback are metadata-level atomic.
  The prior `IndexVersion` becomes `superseded` but its store is left intact for instant rollback.
- **Retrieve**: signed context + manifest pins → server-resolved active index/doc-set ids →
  app-predicate + RLS-scoped cosine query → citations.
- **Remove**: soft-delete sets `deleted_at` (immediately excluded from answers via the
  `document.deleted_at IS NULL` predicate; fully purged from storage on the next
  rebuild+promote). Physical purge is a separate, elevated, audited operation deleting blob +
  chunks + versions.
- **Retention/purge of superseded stores**: a background job drops a superseded `IndexVersion`'s
  physical store **only when no release references it** and after any retention window.

## Security boundaries

- Tenant is the **physical** security boundary (enforced by app predicate + RLS); document-set
  version is the **logical** ACL/retrieval unit; each `IndexVersion` is a **physically isolated
  immutable store**. Cross-tenant and cross-set access is deny-by-default and tested negatively.
- All external egress reuses the Sprint 9 bounded/pinned TLS transport: scheme/host governance,
  resolved-IP pinning, connect/read timeouts, response-size caps, bounded retries,
  `secret:<name>` credentials, and redacted audit. Embedding/OCR/tool destinations remain
  public-unicast-only. ADR-0006 adds a separate Confluence-only, deployment-owned private-CIDR
  policy; it does not relax the public validator. No tenant/request `base_url`.
- Uploaded/parsed bytes are untrusted: validate content and size independently of filename;
  store outside executable paths; bound decompression; treat document text as data, never as
  instructions.
- The console frontend stays non-authoritative; every validation/authorization/lifecycle/purge
  decision is a backend round-trip. UI never exposes object keys beyond tenant scope, secret
  refs, physical store names, or egress endpoints.

## Dependencies

Each item below is **approval-gated at its milestone**. Current status:

- **Embedding client** — **no dependency**: an `OpenAICompatibleEmbeddingClient` adapter over the
  existing Sprint 9 SSRF-safe stdlib transport (decision 3). `openai` is explicitly **not** added
  here.
- **Parser libraries** — pdfplumber, python-docx and openpyxl were owner-approved and added for
  local parsing; no parser opens network egress. OCR remains an external profile-only service.
- **External egress**: embedding/OCR and offline Confluence implementations are profile-only and
  threat-modeled. Each live environment still needs its concrete profile/network/secret sign-off.
  Generic REST is implemented offline under ADR-0007; live profiles remain disabled pending
  environment-specific endpoint, credential and capacity review.

### Parser comparison (decision E — to complete before any dependency is added)

| Option | Formats | Table fidelity | Image/OCR hook | License | Native deps / footprint | Air-gapped | Verdict |
|---|---|---|---|---|---|---|---|
| Unified (e.g. markitdown-class) | pdf/docx/xlsx/pptx | medium | needs image extraction to feed OCR | MIT-class | light–medium | yes | candidate |
| Unified ML (e.g. docling-class) | pdf/docx | high | built-in OCR/models (heavy) | MIT-class | heavy (ML weights) | yes but large | likely rejected (in-app OCR unwanted) |
| Ecosystem (e.g. unstructured-class) | many | high | optional external services | Apache-class | heavy, many native deps | partial | risk: external calls/footprint |
| Format-specific (pypdf/pdfplumber + python-docx + openpyxl) | per-format | high (pdfplumber tables) | explicit image extraction → our OCR | permissive | light, pure-python | yes | **preferred baseline** |

Preference (owner): permissive license, no external service call, air-gapped, **OCR optional**
— image-only PDF pages and embedded pdf/docx images are sent to the owner's OCR endpoint, not
processed in-app. The format-specific stack behind `DocumentParser` best matches this; the
final pick is confirmed in Milestone M4 before the dependency is approved.

## Design spikes (M0 — prerequisite to implementation)

All three are **now documented as ADRs (2026-07-12)** — the prerequisite for any migration or
implementation. Phase 2 kickoff is approved; per-phase egress/dependency sign-off remains.

- **Spike 1 — pgvector multi-dimension storage → [ADR-0003](../../adr/0003-vector-storage-blue-green-per-index-version.md).**
  Chose an **immutable blue/green per-`IndexVersion` store** (fixed-dim `vector(D)`/`halfvec(D)` +
  own HNSW, system-generated names, `vector`≤2000 / `halfvec`≤4000, no silent truncation), with
  promotion as a metadata **pointer flip** (no rename/copy/rebuild) and a retention/purge condition;
  the dimensionless-column-with-partial-index option is a documented fallback. Includes the
  name-parameterized DAL implementation note.
- **Spike 2 — RLS connection-context → [ADR-0004](../../adr/0004-tenant-isolation-postgres-rls-connection-context.md).**
  `FORCE ROW LEVEL SECURITY`, a non-owner app role without `BYPASSRLS`, a **transaction-local**
  `set_config('app.tenant_scope', …, true)` hook for web + Celery, fail-closed missing/invalid context,
  control-plane/data-plane separation, pgbouncer session/transaction (not statement) pooling, and a
  negative-test matrix.
- **Spike 3 — shared SSRF-safe egress adapter → [ADR-0005](../../adr/0005-shared-ssrf-safe-egress-adapter.md)**
  (implements the [ADR-0002](../../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md)
  governance). One adapter over `apps.tools.egress` reused by chat/embedding/OCR: profile-ID-only
  destinations, resolved-IP pinning, redirect denial, private/link-local/metadata block, TLS
  verification, timeouts, response-size cap, `secret:<name>` resolution, redacted audit, and the
  **no-blind-retry** (post-send = `outcome_unknown`) stance, with a negative-test matrix.

## Milestones

Each milestone is additive-migration-only, keeps the deterministic profile passing, never
mutates an active index in place, and promotes only via the pointer flip after eval. The
**authoritative delivery order** (interleaved with WS5, value-first) is
[`runtime-and-document-plane-sequence.md`](runtime-and-document-plane-sequence.md); that sequence
builds **staged** embeddings (M3) before **serving** ACL retrieval (M2) under an explicit serving
guardrail (real tenant corpora are not served to consumers until deny-by-default binding + RLS are
in place), so the milestone numbers below are scope units, not the build order.

- **M0 — Design spikes** (above): **done** — documented as ADR-0003 / ADR-0004 / ADR-0005. Gate
  for all following work; Phase 2 kickoff is approved and per-phase egress/dependency sign-off remains.
- **M1 — Content plane & storage**: rename `Document → IndexedDocument`; `apps/documents` models;
  object-store upload; soft-delete + auditable purge. No retrieval behavior change yet.
- **M2 — Binding, ACL & RLS retrieval**: `DocumentSet`/`Version`/`Membership`,
  `ScenarioDocumentSetBinding`, release-compile pinning + resolver expansion, retrieval ACL
  predicate, RLS policies + connection-context wiring, `DocumentSetGrant` (consumer-only
  enforcement). Negative tests: deny-by-default, cross-tenant (app + RLS), cross-set,
  client-filter-ignored.
- **M3 — Real embeddings & blue/green reindex**: platform `EmbeddingProfile` catalog +
  per-tenant grants; `OpenAICompatibleEmbeddingClient` over the SSRF-safe transport; per-
  `IndexVersion` immutable stores; dimension/index-type validation; staged build → eval →
  pointer-flip promotion; retention/purge job for unreferenced stores.
- **M4 — Parsers & connectors**: parser interface, selected parsers, upload, external OCR and P7.4a
  Confluence are implemented and verified offline. Live Confluence rollout remains deployment-gated;
  P7.4b generic REST, periodic no-op refresh and compatible unchanged-vector reuse are implemented
  and verified offline under ADR-0007; live endpoint/credential rollout remains gated.
- **M5 — Phase 2 production closure hardening**: broader Django-table FORCE RLS, dedicated non-owner
  application role, upload malware/type scanning, and concrete live Confluence/REST/embedding/OCR
  profiles with privacy/retention, network/secret, smoke and rollback evidence. Authoritative task:
  [`phase-2-closure-production-hardening`](../../tasks/phase-2-closure-production-hardening/plan.md).
- **M5 — Console UI**: per-scenario document sources, set membership, binding, upload,
  soft-delete/purge — role/tenant-scoped, non-authoritative.

## Risks

- **pgvector fixed-dimension HNSW**: active + different-dimension staged indexes must coexist.
  Mitigation: immutable blue/green per-`IndexVersion` store (Spike 1); dimension/index-type
  validated up front; no silent truncation.
- **ACL leak**: a single missing predicate = cross-tenant/cross-set exposure. Mitigation:
  layered app predicate + FORCE RLS (fail-closed) + DB constraints + mandatory negative tests.
- **RLS/pooling misconfiguration**: a leaked session GUC or an over-privileged app role would
  break isolation. Mitigation: transaction-local `set_config` only, non-owner app role without
  `BYPASSRLS`, Spike 2 design + negative tests.
- **Rename churn**: `Document → IndexedDocument` touches the `Chunk` FK and the provider.
  Mitigation: `RenameModel` migration preserving rows/PKs/FKs (no drop/recreate) + tests first.
- **Egress abuse (SSRF/DNS-rebinding)** on four new external calls. Mitigation: reuse the Sprint 9
  SSRF-safe transport; platform-allowlisted embedding/OCR endpoints; no tenant/request base_url.
- **Stale-index consistency**: soft-deleted docs remain in already-built indexes until reindex.
  Mitigation: live `deleted_at` predicate for immediate answer exclusion + reindex to purge.
- **Orphaned/leaked stores**: a superseded store dropped while still referenced, or never dropped.
  Mitigation: retention/purge job drops only when no release references it.
- **Parser resource abuse** (decompression bombs, huge tables, image floods to OCR). Mitigation:
  byte/element/page/image caps, per-document OCR call budget.

## Open decisions

Resolved by the owner on 2026-07-12 (constraints captured above):
pgvector multi-dim → immutable blue/green per-`IndexVersion` store with pointer-flip promotion
(Spike 1 confirms); rename `Document → IndexedDocument` preserving rows/PKs/FKs; embedding egress
via the SSRF-safe stdlib transport adapter, no `openai` dep, no tenant/request base_url; RLS
`FORCE`d, fail-closed, transaction-local context; `EmbeddingProfile` a platform-managed,
immutable, revisioned catalog with per-tenant grants.

Remaining (non-blocking, decided at their milestone):

- Parser library selection — pending the M4 comparison; format-specific stack is the preferred
  baseline. No dependency added before sign-off.
- Blob dedup by checksum — optional; defer unless storage pressure warrants.
- Connector specifics — Confluence is Data Center with a least-privilege PAT profile and
  connector-specific private policy (ADR-0006); generic-REST source definition and auth remain
  governed by ADR-0007; live source/auth review and upload size/type/scan limits remain operational gates.
- Vector storage — the separate immutable store is decided by ADR-0003; changing it requires a
  superseding ADR.

## Testing strategy

- **Security/authorization (required)**: cross-tenant retrieval denial at **both** the app
  predicate and RLS layers (including a deliberately-omitted app predicate proving RLS blocks it);
  scenario with no binding retrieves nothing; client-supplied tenant/document-set filter ignored;
  soft-deleted document excluded from answers; purge removes blob+chunks; unsupported embedding
  dimension/index-type rejected (no silent truncation); embedding/OCR/connector SSRF +
  DNS-rebinding denial; tenant/request `base_url` rejected; upload content/size validation and
  decompression-bomb defense; RLS missing/invalid-context returns no rows; pooled-connection GUC
  non-leak.
- **Integration**: object-store upload/read; staged build → eval → **pointer-flip promotion** →
  rollback (metadata-atomic); resolver expansion; ACL predicate + RLS on real pgvector
  (PostgreSQL gate); retention/purge only-when-unreferenced.
- **Migration**: `Document → IndexedDocument` rename preserving rows/PKs/FKs; `IndexVersion`
  re-scope; introduction of per-`IndexVersion` stores; RLS enablement; each with data invariants
  and a rollback/forward-fix path.
- **Contract**: consumer gateway `/v1/query` behavior unchanged for a bound scenario; existing
  index-pinned releases still resolve.
- Deterministic profile keeps the full suite runnable without live egress.

## Observability requirements

- **Audit** (redacted; ids/counts/checksums/decision only, never content): document
  create/update/soft-delete/purge, membership change, binding create/remove, `EmbeddingProfile`
  create + per-tenant grant, index build/promote(pointer-flip)/rollback, store retention-purge,
  `DocumentSetGrant` change, authorization denials. Purge and binding/grant audit failures are
  **fail-closed**.
- **Metrics** (bounded labels, no content/URL/tenant/prompt/store-name in labels): ingestion
  counts, parse failures by stable code, embedding/OCR egress duration + failure counts, index
  build duration, retrieval ACL-filter application, RLS-denied counts. Reuse the Sprint 7
  Prometheus surface.
- **Logs/errors**: stable codes only; never log document bytes, object keys beyond scope,
  physical store names, secret refs, or egress URLs/query strings.

## Rollout

M0 (spike docs) gates everything. Then milestone-staged behind additive migrations. Index/
embedding changes ship as staged builds that serve only after eval + **pointer-flip promotion**
(never in-place). New egress destinations added to the platform allowlist per environment (test →
cloud endpoints, prod → local endpoints) with the deterministic profile as the always-available
fallback. RLS is enabled with policies validated by negative tests before the ACL milestone is
promoted. Console UI ships last (M5).

## Rollback

- Index/embedding changes: rollback flips the active `index_version_id` pointer back within one
  transaction (metadata-atomic); the prior immutable store is retained for instant rollback and
  dropped only later by the retention/purge job.
- Schema: additive migrations are reversible; the rename and re-scope migrations ship with
  down-migrations and are exercised on representative data before promotion.
- RLS: policies can be disabled per table via migration if a blocking defect appears, falling
  back to the app predicate (documented as a temporary, audited exception, not a steady state).
- Egress/dependency: each is behind config/allowlist and can be disabled back to the
  deterministic profile / disabled connector without data loss.

## Completion criteria

Per-milestone: acceptance criteria mapped to evidence; security negative tests (cross-tenant at
app + RLS layers, cross-set, deny-by-default, client-filter-ignored, SSRF, base_url-rejected,
RLS-fail-closed) passing; redacted audit verified; additive/reversible migrations verified on
SQLite + PostgreSQL (RLS/vector paths on PostgreSQL); no new dependency or egress without
recorded owner approval + supply-chain/threat review; final diff reviewed for authorization,
tenant isolation, privacy, and egress control. Workstream complete when a bound scenario
retrieves only its authorized, tenant-scoped document-set content end-to-end through real parsing
+ embeddings, with soft-delete/purge, blue/green staged reindex, pointer-flip promotion, and RLS
all governed and audited.

## Links

- Phase 2 overview: [`../phase-2-plan.md`](../phase-2-plan.md)
- Threat model: [`document-plane-threat-model.md`](document-plane-threat-model.md)
- Interleaved WS1+WS5 delivery order: [`runtime-and-document-plane-sequence.md`](runtime-and-document-plane-sequence.md)
- Egress architecture decision: [ADR-0002](../../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md)
- M0 spike ADRs: [ADR-0003 vector storage](../../adr/0003-vector-storage-blue-green-per-index-version.md),
  [ADR-0004 RLS tenant isolation](../../adr/0004-tenant-isolation-postgres-rls-connection-context.md),
  [ADR-0005 shared egress adapter](../../adr/0005-shared-ssrf-safe-egress-adapter.md)
- Supersedes as retrieval trust unit: [`../../tasks/sprint-5-ingestion-pgvector/plan.md`](../../tasks/sprint-5-ingestion-pgvector/plan.md)
- Reused seams: Sprint 6 release lifecycle, Sprint 7 metrics/tracing, Sprint 9 SSRF-safe egress.
- Technical grounding: pgvector HNSW dimension limits (`vector`≤2000, `halfvec`≤4000) and
  mixed-dimension `vector` columns needing per-dimension expression/partial indexes; PostgreSQL
  `FORCE ROW LEVEL SECURITY` (applies policy to table owners) and transaction-local
  `set_config(..., true)` (no pooled-connection leak); `openai` custom `base_url`/transport is a
  configuration surface, not an SSRF control.
