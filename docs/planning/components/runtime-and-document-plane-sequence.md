# Implementation Sequence — Live Model Runtime (WS5) + Document Plane (WS1)

## Status

The high-level **delivery order is owner-set** (2026-07-12); this document **elaborates** it into
a phase plan and **invents no new scope**. **Implementation is not yet approved** — the M0 spikes
and per-phase egress sign-off remain the gates. Authorities:

- WS1 design: [`document-plane-plan.md`](document-plane-plan.md) + [threat model](document-plane-threat-model.md).
- WS5 scope: [`../phase-2-plan.md`](../phase-2-plan.md) → "Workstream 5 — Live model runtime".
- Egress architecture: [ADR-0002](../../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md).

## WS5 is a foundational track, not a 5th-in-line priority

Without a real chat provider the product still returns stub answers, so WS5 is **interleaved with
WS1 as a foundational track**, not sequenced after WS4. Both build on one foundation: the
**SSRF-safe stdlib egress** (Sprint 9 `apps.tools.egress`) plus a **platform-managed profile
catalog** (`ModelProfile` / `EmbeddingProfile`) referenced by ID only. Building that once, then
lighting up capabilities in value order, avoids parallel egress implementations and delivers a
real-LLM answer early — the owner's immediate pain — before the larger document-plane migration.

**Owner-set delivery order (2026-07-12):** WS1 M0 security/design spikes → shared egress/provider
infra → chat provider → embedding/indexing → document-ACL retrieval → UI.

Every new external egress and every new dependency below is still an explicit **approval gate** at
its phase (per `AGENTS.md`).

## Serving guardrail

Building and **staging** real-embedding indexes (P3) is separated from **serving** real tenant
corpora to consumers. **No real tenant corpus is promoted/served to a consumer until P4's
deny-by-default document-set binding + RLS are in place.** Until then, P1's real chat runs on
today's tenant-isolated (org + pinned-index) retrieval, and P3 builds/evals staged indexes without
consumer exposure of sensitive corpora.

## Critical path (dependency order)

```
P0 spikes ─┬─> P1 shared egress + REAL CHAT provider ──> (RAG /v1/query answers with a real LLM)
           │
           ├─> (Spike1 pgvector) ─> P2 content plane ─> P3 real embeddings + indexing (staged)
           │                                                     │
           └─> (Spike2 RLS) ─────────────────────────────────────┤
                                                                  v
                                    P4 document-ACL retrieval + RLS  (serves real, ACL'd corpora)
                                                                  │
                                                                  v
                             P5 wire real retrieve+generate into agent & workflow (multi-prompt)
                                                                  │
                                                                  v
                             P6 agent system-prompt ─> P7 parsers+OCR+connectors ─> P8 console UI
```

## Phases

Each phase is additive-migration-only, keeps the deterministic profiles passing (so CI needs no
live egress), and ends with a **demoable capability**.

### P0 — Design spikes (no code) — **DONE (documented as ADRs, 2026-07-12)**

1. **Spike 1 — pgvector multi-dimension storage → [ADR-0003](../../adr/0003-vector-storage-blue-green-per-index-version.md):**
   immutable blue/green per-`IndexVersion` store, system-generated names, pointer-flip promotion,
   retention condition, `vector`≤2000 / `halfvec`≤4000, name-parameterized DAL.
2. **Spike 2 — RLS connection-context → [ADR-0004](../../adr/0004-tenant-isolation-postgres-rls-connection-context.md):**
   non-owner app role, `FORCE ROW LEVEL SECURITY`, transaction-local `set_config('app.tenant_id',…,
   true)` for web + Celery, pooling safety, fail-closed policy, control-plane/data-plane split,
   negative-test matrix.
3. **Spike 3 — shared SSRF-safe egress adapter → [ADR-0005](../../adr/0005-shared-ssrf-safe-egress-adapter.md)**
   (implements the [ADR-0002](../../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md)
   governance): one adapter over `apps.tools.egress` reused by chat/embedding/OCR — profile-ID-only,
   resolved-IP pinning, redirect denial, private/link-local/metadata block, TLS verification,
   timeouts, response-size cap, `secret:<name>` resolution, redacted audit, no-blind-retry.

**Gate cleared for design; the following phases still require implementation approval + per-phase
egress sign-off.** No runtime change.

### P1 — Shared egress + real chat model (fastest visible win) · WS5 5.1–5.2 — IMPLEMENTED

Implemented and verified 2026-07-12 under
[`phase-2-p1-live-chat`](../../tasks/phase-2-p1-live-chat/plan.md). The provider is opt-in;
deterministic remains the default and no environment-specific live endpoint was opened.

- Implement the shared egress adapter (Spike 3) and the real `OpenAICompatibleModelProvider`
  (chat) over it, driven by a **platform-catalog `ModelProfile` referenced by ID** (no author/
  tenant/request `base_url`/host/scheme/credential/TLS choice — ADR-0002). Enforce timeout,
  response-size cap, token budget, and the no-blind-retry rule (a post-send failure is an unknown
  outcome, not a retry).
- `run_rag` (`/v1/query`) already calls the provider seam → **no runtime rewrite**; verify the
  grounding gate, output-contract, citation policy, fallback, token usage, redaction, and the
  prompt-injection boundary (system instructions separated from retrieved/user text) on the live
  path.
- **Approval gate:** the chat egress endpoint/profile (test → cloud, prod → local).
- **Demo:** a real RAG scenario answers via a live LLM (still using today's deterministic
  embedder/retriever) — directly resolves "profile-pinned endpoint + token → real model". No
  `openai` dependency.

### P2 — Content plane & storage · WS1 M1

- Rename `apps.ingestion.Document → IndexedDocument` (`RenameModel`, preserve rows/PKs/FKs); add
  `apps/documents` models (`Source→Document→DocumentVersion→Blob`, `DocumentSet` versioning);
  object-store upload; soft-delete tombstone + auditable purge. No retrieval behavior change.
- **Depends on:** Spike 1 (store design informs the model), Spike 2 (RLS tables).
- **Demo:** upload/list/soft-delete/purge documents (operator API), fully tenant-scoped + audited.

### P3 — Real embeddings + indexing (staged, not yet served) · WS1 M3

- Platform `EmbeddingProfile` catalog + per-tenant grants; `OpenAICompatibleEmbeddingClient`
  **reusing the P1 egress**; per-`IndexVersion` immutable stores; dimension/index-type validation
  (no silent truncation); staged build → eval; retention/purge job. Embeddings run over managed
  documents (text/markdown first; richer formats arrive in P7).
- **Serving guardrail:** staged indexes are built and eval'd but **real tenant corpora are not
  promoted/served to consumers until P4**.
- **Approval gate:** the embedding egress endpoint/profile.
- **Demo:** a document set builds a real-embedding staged index that passes eval (operator view),
  with no consumer exposure yet.

### P4 — Document-ACL retrieval + RLS · WS1 M2 (security core; unlocks serving)

- `DocumentSetVersion`/`Membership`, mandatory `ScenarioDocumentSetBinding`, release-compile
  pinning + resolver expansion, retrieval ACL predicate, **RLS policies + connection-context
  wiring**, `DocumentSetGrant` (consumer-only enforcement), and **pointer-flip promotion** of the
  eval'd P3 index. Negative tests: deny-by-default, cross-tenant at app **and** RLS layers,
  cross-set, client-filter-ignored.
- **Demo:** end-to-end **real, ACL-scoped document RAG on `/v1/query`** — real embeddings + real
  chat answer grounded only in the scenario's bound, tenant-authorized documents; a
  deliberately-omitted app predicate is still blocked by RLS (proven by test).

### P5 — Wire real retrieval + generation into agent & workflow · WS5 5.3–5.4

- Replace the agent `retrieve` stub and the workflow `retrieve`/`generate` stubs with the governed
  real providers (P1 chat + P4 ACL retrieval). Add **per-node prompt/model binding** to the
  workflow `generate` node (references a governed `prompt` role/template + optional catalog
  `ModelProfile`) → **multi-prompt / multi-model workflows** become runnable.
- **Demo:** an agent does real document RAG in its loop; a workflow with several `generate` nodes
  runs distinct real prompts, all under contracts/policy/fallback.

### P6 — Agent system prompt (authored, governed) · WS5 5.5

- Extend `agent_definition` to reference a governed **system-prompt/instruction** artifact (data:
  validated, bounded, redaction-safe, checksummed, release-pinned). Tool/decision re-validation
  unchanged (prompt is input, never authorization).
- **Demo:** an agent runs with an authored persona/instructions instead of the raw user objective.

### P7 — Parsers + OCR + connectors · WS1 M4

- `DocumentParser` interface + selected parsers (pdf/docx/xlsx→markdown), **external OCR egress**
  for image-only pages/embedded images, and upload/Confluence/generic-REST connectors. Real
  document RAG runs on `text`/markdown from P3–P4; this phase adds the richer formats.
- **Approval gate:** parser dependency (post comparison table) + OCR egress endpoint + connector
  endpoints.
- **Demo:** upload a PDF/DOCX/XLSX → parsed → embedded → retrievable, with image content OCR'd via
  the owner's endpoint.

### P8 — Console UI · WS1 M5

- Operator UI for per-scenario document sources, set membership, binding, upload, soft-delete,
  purge — role/tenant-scoped, non-authoritative (reuses console LDAP/session authz).
- **Demo:** the whole document plane is operable from the console (still GitOps-compatible).

## Sequencing rationale & alternatives

- **P1 first** deprioritizes nothing in WS1; it is decoupled (uses existing indexes) and delivers
  the owner's headline capability immediately with the smallest surface.
- **Embedding/indexing (P3) before document-ACL retrieval (P4)** follows the owner-set order, held
  safe by the serving guardrail: staged indexes are built/eval'd, but real corpora are served to
  consumers only after deny-by-default binding + RLS (P4).
- **Parsers (P7) after the ACL/embedding core:** real RAG runs on text/markdown first; pdf/docx/
  xlsx + OCR are additive per-format capability, and carry the heaviest dependency/approval load.
- **Alternative** if the owner wants the full document plane before any live LLM: run P2→P8 of WS1
  first and defer P1/P5/P6; the interleave above is the recommended value-first order.

## Approvals summary (per phase)

| Phase | New egress | New dependency |
| --- | --- | --- |
| P1 | chat model profile/endpoint | none (stdlib client) |
| P3 | embedding model profile/endpoint | none (stdlib client) |
| P7 | OCR endpoint + Confluence/REST | document-parser lib (post comparison) |

## Governance held across all live phases

- **Egress:** platform-catalog profile referenced by ID only (no author/tenant/request `base_url`/
  host/scheme/credential/TLS choice); shared transport verifies TLS, pins the resolved IP, denies
  redirects, blocks private/link-local/metadata ranges, and caps timeout/response size (ADR-0002).
- **Idempotency:** no blind retry — a chat/embedding call failing *after send* is an unknown
  outcome (double-cost/divergent-answer risk), failed for controlled re-drive, never re-sent.
- **Prompt injection:** document/retrieved/user text is untrusted **data**; system instructions are
  built server-side and kept separate; tool calls are never authorized by model output (Sprint 9/10
  proxy + approval re-validate); citation/grounding/output-contract/policy run **after** the model.
- **Observability:** per-provider latency/error/token metrics on the Sprint 7 Prometheus surface;
  **no prompt/response content** in logs, metric labels, or audit (ids/counts/latency/stable codes).

## Links

- WS1: [`document-plane-plan.md`](document-plane-plan.md), [threat model](document-plane-threat-model.md)
- WS5: [`../phase-2-plan.md`](../phase-2-plan.md)
- Egress governance: [ADR-0002](../../adr/0002-model-embedding-egress-profile-catalog-stdlib-adapter.md)
- M0 spike decisions: [ADR-0003 vector storage](../../adr/0003-vector-storage-blue-green-per-index-version.md),
  [ADR-0004 RLS tenant isolation](../../adr/0004-tenant-isolation-postgres-rls-connection-context.md),
  [ADR-0005 shared egress adapter](../../adr/0005-shared-ssrf-safe-egress-adapter.md)
- Reused seams: Sprint 6 release lifecycle, Sprint 7 metrics/tracing, Sprint 9 SSRF-safe egress.
