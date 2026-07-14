# Threat Model: document-plane (Phase 2 · Workstream 1)

Companion to [`document-plane-plan.md`](document-plane-plan.md). Draft — reviewed and updated
before implementation of each milestone.

## Assets

Tenant document content and versions, blobs in object storage, document-set membership and
bindings, ACL grants, embeddings/index lineage, embedding-profile and connector configuration,
`secret:<name>` references, and database/object-store/egress availability.

## Actors

Authorized console operators (LDAP/session, role- and tenant-scoped), ingestion/reindex workers,
runtime consumers acting through a signed `ExecutionContext`, and external systems: the
owner-hosted OpenAI-compatible embedding endpoint, the owner-hosted OCR endpoint, Confluence, and
generic REST sources. `user`/`group` principals exist in the schema but are **not enforced** in
this workstream (deferred to Phase 3 personal MCP).

## Entry points

Console operator JSON API (document-set/membership/binding CRUD, multipart upload, soft-delete,
purge, source CRUD), internal build/reindex service, Celery task payloads carrying only ids,
source connectors, the parser/OCR/embedding egress clients, and the ACL-scoped retrieval query.
The consumer gateway contract is unchanged.

## Trust boundaries

Operator session to console API; console API to object store; database to worker; worker to
external embedding/OCR/Confluence/REST endpoints; untrusted uploaded/fetched bytes to parser;
parser to external OCR; signed runtime context + release manifest to the ACL-scoped vector query.

## Data classifications

Document content, versions, chunks, and embeddings inherit tenant classification and may contain
PII, secrets, or regulated data. Object keys and provenance are sensitive. Logs, metrics, and
audit carry identifiers, counts, checksums, and stable reason codes only — never content, object
bytes, secret refs, or egress URLs/query strings.

## Authentication

Console API reuses Sprint 1 LDAP/session auth (CSRF-enforced, 401/403 JSON, no CORS, not the
consumer bearer path). External egress authenticates with `secret:<name>` references resolved at
call time; credentials never appear in source config, task payloads, logs, or the UI.

## Authorization

Deny-by-default and server-side at object/action/tenant/field level. Console read is
membership-scoped (`allowed_organization_ids`); create/update/delete/publish/purge require the
existing authoring/lifecycle roles; purge requires an elevated role. Retrieval effective
authorization = **scenario↔document-set binding (pinned to a version) ∩ consumer authorization
∩ tenant_id**, all resolved from the signed context + release manifest. Clients cannot supply
tenant, document-set, index scope, or an embedding `base_url`. RLS is a fail-closed second layer,
explicitly **not** a replacement for these application checks.

## Tenant isolation

`tenant_id` (organization) is mandatory and immutable on every content-, set-, index-, and
chunk-level model. Tenant is the physical boundary; document-set version is the logical ACL/
retrieval unit; each `IndexVersion` is a physically isolated immutable store with a
system-generated (never application-supplied) name. The vector query always constrains
`organization_id` **and** the pinned `document_set_version_id`/`index_version_id` set, plus
`document.deleted_at IS NULL`.

**PostgreSQL RLS** enforces a fail-closed backstop: `FORCE ROW LEVEL SECURITY` on tenant
data-plane tables, an application DB role that is **not** the table owner and lacks `BYPASSRLS`,
policies of the form `tenant_id = current_setting('app.tenant_id')::bigint`, and a
**transaction-local** `set_config('app.tenant_id', <tenant_id>, true)` established from the
trusted context after each transaction begins (never session-level, so nothing leaks across a
pooled connection). Missing/invalid context returns **no rows**. Control-plane / global
worker-claim tables are separated from tenant data-plane tables; the worker gets no broad bypass
role, and cross-tenant administration runs through a separate auditable admin function/role.
Cross-tenant and cross-set access are negatively tested at both the app-predicate and RLS layers.

## External systems

Owner-hosted embedding endpoint, owner-hosted OCR endpoint, Confluence, generic REST,
PostgreSQL/pgvector, object store (MinIO/S3), Redis/Celery. Every outbound call requires an
allowlisted scheme/host, resolved-IP pinning (anti-DNS-rebinding), connect/read timeouts,
response-size caps, bounded retries, and `secret:<name>` credentials — reusing the Sprint 9
SSRF-safe **stdlib** transport. Private/link-local/metadata ranges are blocked. The embedding
endpoint is a platform-allowlisted, environment-specific endpoint (test → cloud / prod → local)
taken from the selected `EmbeddingProfile`; neither tenant nor request may supply a `base_url`,
and the `openai` library's `base_url`/transport flexibility is not used as an egress control. No
`openai` dependency is added for embeddings at this stage.

## Abuse cases

- Cross-tenant or cross-document-set id injection; scenario retrieving from an unbound set;
  client-supplied tenant/set/index filter attempting to widen scope.
- SSRF / DNS-rebinding via a connector URL, the embedding endpoint, the OCR endpoint, or a
  generic-REST source; egress to metadata/private networks.
- Malicious upload: decompression bomb, oversized file, mismatched MIME vs content, embedded
  active content, path-traversal in filename/object key, image flood to exhaust the OCR budget.
- Document content used as trusted instructions (prompt injection) or as an exfiltration channel.
- Inline secret smuggled into connector/profile config; secret ref leaking via logs/UI/error.
- Silent dimension truncation (e.g. 4096→4000) or an unsupported dimension/index-type
  (`vector`>2000 / `halfvec`>4000) corrupting relevance or masking a profile mismatch.
- Tenant/request supplying an embedding `base_url` to redirect egress; RLS context left on a
  pooled connection and read by the next tenant's operation; application DB role holding
  `BYPASSRLS` or owning tables (bypassing FORCE RLS).
- Reindex race: two workers building the same document-set version; staged index auto-promoted
  without eval; in-place mutation of an active index; promotion rename/copy/rebuild losing
  atomicity; superseded store dropped while still referenced, or orphaned forever.
- Tenant creating an arbitrary endpoint/model via a self-defined `EmbeddingProfile`, or mutating
  a profile already used by a built index; an artifact/prompt/request supplying `base_url`,
  host/port, scheme, credential selection, or TLS-verification behavior instead of a profile ID.
- Blind retry of an embedding/model call after a post-send failure (read timeout) causing double
  cost and divergent vectors/answers.
- Document/retrieved text smuggling instructions into the model (prompt injection), or model
  output attempting to authorize a tool call or widen scope.
- Soft-deleted or purged document still retrievable; purge not fully removing blobs.
- Privilege escalation: non-owner triggering purge; cross-org membership/binding selection;
  worker granted a broad tenant-bypass role.

## Failure cases

Worker loss after claim; object-store or database or audit failure; embedding/OCR/connector
timeout or oversized response; parse failure or partial parse; partial index build; stale
advisory lock; terminal retry exhaustion; promotion/rollback interrupted mid-cutover; blue/green
storage left orphaned.

## Logging and audit risks

Exceptions can carry URLs, query strings, object keys, or document text. Normalize to stable
reason codes; never persist raw exception strings, document bytes, embeddings, object bytes,
secret refs, or credentials. Audit is separate from application logs, restricted, retained, and
integrity-protected; audit-persistence failure for purge and binding/grant changes is
**fail-closed** (security-critical administration).

## Mitigations

Deny-by-default connector/parser/embedder registries and per-destination allowlists; resolved-IP
pinning and bounded timeouts/sizes/retries on the Sprint 9 stdlib egress; platform-allowlisted
embedding/OCR endpoints with no tenant/request `base_url` and no `openai` dependency; mandatory
immutable `tenant_id`; layered retrieval predicate (org + pinned set + pinned index + `deleted_at`
null) plus DB constraints plus **fail-closed FORCE RLS** with a transaction-local
`set_config('app.tenant_id', …, true)`, a non-owner app role without `BYPASSRLS`, and
control-plane/data-plane table separation; `secret:<name>`-only credentials with redaction;
upload content/size/MIME validation independent of filename, decompression bounds, and
per-document OCR call budget; **platform-managed, immutable, revisioned `EmbeddingProfile`
catalog** with per-tenant grants and no silent dimension/index-type coercion (dimension validated
at ingestion start; `vector`≤2000 / `halfvec`≤4000); **immutable blue/green per-`IndexVersion`
stores** with system-generated names, never promoted without Sprint 6 eval, never mutating the
active index, promoted/rolled back by a single-transaction **pointer flip** (no rename/copy/
rebuild), and reclaimed by a retention/purge job only when unreferenced; source advisory locks
against duplicate builds; late Celery ack and idempotent, terminal-state build/promote;
soft-delete tombstone with live answer exclusion plus auditable physical purge; role-gated,
non-authoritative console with UI never exposing endpoints, object keys beyond scope, physical
store names, or secret refs; **egress via a platform-managed profile catalog referenced by ID
only** (no artifact/tenant/request `base_url`/host/scheme/credential/TLS choice), over the shared
transport that also verifies TLS and pins the resolved IP; **no blind retry** — a post-send
embedding/model failure is an unknown outcome, failed for controlled re-drive, never silently
re-sent; **prompt-injection boundary** — system instructions built server-side and kept separate
from document/retrieved/user text, tool calls never authorized by model output (re-validated by
the Sprint 9/10 proxy + approval), and citation/grounding/output-contract/policy applied *after*
the model; redacted, separate, fail-closed audit for security-critical actions.

## Residual risks

DNS pinning and production egress policy still require infrastructure controls. Content-level
prompt injection remains governed by runtime policy, not ingestion trust. The RLS
connection-context design (transaction-local GUC, pooling safety, role model) must be settled in
Spike 2 and proven by negative tests before it is relied upon. Person/group ACL is only
schema-forward-ready here; its enforcement and the trusted propagation of end-user identity are
Phase 3 identity/delegation concerns and must not be assumed active. Real embedding/OCR relevance and the final
parser dependency are validated in M3/M4 before promotion.

## Required security tests

Cross-tenant retrieval denial at **both** the app-predicate and RLS layers (including a
deliberately-omitted app predicate proving RLS still blocks the row); unbound-scenario
deny-by-default; client-supplied tenant/set/index filter ignored; tenant/request `base_url`
rejected; soft-deleted document excluded from answers; purge removes blob + chunks + versions;
unsupported/mismatched embedding dimension or index-type rejected without truncation;
embedding/OCR/connector SSRF scheme/host/DNS-rebinding denial; upload content/size/MIME and
decompression-bomb defense; duplicate build-claim prevention; staged-index-not-auto-promoted;
no in-place active-index mutation; pointer-flip promotion/rollback atomicity; retention-purge
only-when-unreferenced; RLS missing/invalid-context returns no rows and pooled-connection GUC
non-leak; tenant cannot self-define/mutate an `EmbeddingProfile`; cross-org membership/binding
rejection; purge and worker-bypass role-escalation denial; redaction of content/secret/URL/
store-name in logs and audit.
