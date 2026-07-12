# Implementation Sequence — Live Model Runtime (WS5) + Document Plane (WS1)

## Status

**Draft proposal for owner sign-off — not approved for implementation.** This document only
**orders** work already designed elsewhere; it invents no new scope. Authorities:

- WS1 design: [`document-plane-plan.md`](document-plane-plan.md) + [threat model](document-plane-threat-model.md).
- WS5 scope: [`../phase-2-plan.md`](../phase-2-plan.md) → "Workstream 5 — Live model runtime".

## Why interleave WS1 and WS5

They share one foundation: the **SSRF-safe stdlib egress** (Sprint 9 `apps.tools.egress`) plus a
**platform-managed provider/profile catalog** with `secret:<name>` resolution. WS5 uses it for the
chat model; WS1 uses it for the embedding model and the external OCR endpoint. Building that
foundation once, then lighting up capabilities in value order, avoids three parallel egress
implementations and delivers a real-LLM answer early (the owner's immediate pain: "give the app a
base_url + token and reach the model") **before** the larger document-plane migration.

Every new external egress and every new dependency below is still an explicit **approval gate** at
its phase (per `AGENTS.md`).

## Critical path (dependency order)

```
P0 spikes ─┬─> P1 shared egress + REAL CHAT provider ──> (RAG /v1/query answers with a real LLM)
           │            │
           │            └─────────────────────────────┐
           ├─> (Spike1 pgvector) ─> P2 content plane ─┤
           └─> (Spike2 RLS)   ────────────────────────┴─> P3 binding+ACL+RLS ─> P4 real embeddings
                                                                                     │  (real, ACL'd
                                                                                     │   document RAG
                                                                                     │   on /v1/query)
                                                                                     v
                                             P5 wire real retrieve+generate into agent & workflow
                                                            │  (multi-prompt workflows; real agent RAG)
                                                            v
                                             P6 agent system-prompt ─> P7 parsers+OCR+connectors ─> P8 console UI
```

## Phases

Each phase is additive-migration-only, keeps the deterministic profiles passing (so CI needs no
live egress), and ends with a **demoable capability**.

### P0 — Design spikes (no code)

Document three short notes (candidate ADRs) before any migration:

1. **Spike 1 — pgvector multi-dimension storage** (WS1): immutable blue/green per-`IndexVersion`
   store, system-generated names, pointer-flip promotion, retention condition, `vector`≤2000 /
   `halfvec`≤4000. *(from the WS1 plan)*
2. **Spike 2 — RLS connection-context** (WS1): non-owner app role, `FORCE ROW LEVEL SECURITY`,
   transaction-local `set_config('app.tenant_id',…,true)` for web + Celery, pooling safety,
   fail-closed policy, control-plane/data-plane split, negative-test matrix. *(from the WS1 plan)*
3. **Spike 3 — shared SSRF-safe egress adapter (NEW, shared by WS1+WS5)**: one adapter contract
   over `apps.tools.egress` reused by the **chat model**, the **embedding model**, and the **OCR**
   endpoint — target/scheme/host allowlist, resolved-IP pinning, redirect denial, timeouts,
   response-size cap, bounded retries, `secret:<name>` resolution, redacted audit; plus the
   **endpoint-governance decision** (platform-allowlisted destinations vs author-set per profile;
   recommended: allowlist + author selects among platform-registered profiles).

**Gate for all following phases.** Deliverable: three design notes; no runtime change.

### P1 — Shared egress + real chat model (fastest visible win) · WS5 5.1–5.2

- Implement/confirm the shared egress adapter (Spike 3) and the real
  `OpenAICompatibleModelProvider` (chat) over it, driven by the `model_profile` artifact
  (`endpoint`/base_url, `model`, `secret:<name>` token, timeout), plugged via
  `RUNTIME_MODEL_PROVIDER`. Enforce timeout, response-size cap, token budget, bounded retries.
- `run_rag` (`/v1/query`) already calls the provider seam → **no runtime rewrite**; verify the
  grounding gate, output-contract, citation policy, fallback, token usage, and redaction on the
  live path.
- **Approval gate:** the chat egress endpoint (test → cloud, prod → local).
- **Demo:** a real RAG scenario answers via a live LLM (still using today's deterministic
  embedder/retriever) — directly resolves "base_url + token → real model". No `openai` dependency.

### P2 — Content plane & storage · WS1 M1

- Rename `apps.ingestion.Document → IndexedDocument` (`RenameModel`, preserve rows/PKs/FKs); add
  `apps/documents` models (`Source→Document→DocumentVersion→Blob`, `DocumentSet` versioning);
  object-store upload; soft-delete tombstone + auditable purge. No retrieval behavior change.
- **Depends on:** Spike 1 (store design informs the model), Spike 2 (RLS tables).
- **Demo:** upload/list/soft-delete/purge documents (operator API), fully tenant-scoped + audited.

### P3 — Binding, ACL & RLS retrieval · WS1 M2 (security core)

- `DocumentSetVersion`/`Membership`, mandatory `ScenarioDocumentSetBinding`, release-compile
  pinning + resolver expansion, retrieval ACL predicate, **RLS policies + connection-context
  wiring**, `DocumentSetGrant` (consumer-only enforcement). Negative tests: deny-by-default,
  cross-tenant at app **and** RLS layers, cross-set, client-filter-ignored.
- **Demo:** a scenario retrieves only from its bound document-set version; a deliberately-omitted
  app predicate is still blocked by RLS (proven by test).

### P4 — Real embeddings + blue/green reindex · WS1 M3

- Platform `EmbeddingProfile` catalog + per-tenant grants; `OpenAICompatibleEmbeddingClient`
  **reusing the P1 egress**; per-`IndexVersion` immutable stores; dimension/index-type validation
  (no silent truncation); staged build → eval → **pointer-flip promotion**; retention/purge job.
- **Approval gate:** the embedding egress endpoint.
- **Demo:** end-to-end **real, ACL-scoped document RAG on `/v1/query`** — real embeddings + real
  chat answer grounded only in authorized tenant documents.

### P5 — Wire real retrieval + generation into agent & workflow · WS5 5.3–5.4

- Replace the agent `retrieve` stub and the workflow `retrieve`/`generate` stubs with the governed
  real providers (P1 chat + P4 ACL retrieval). Add **per-node prompt/model binding** to the
  workflow `generate` node (references a governed `prompt` role/template + optional
  `model_profile`) → **multi-prompt / multi-model workflows** become runnable.
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
  document RAG runs on `text`/markdown from P4; this phase adds the richer formats.
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
- **Security-core (P3) before real embeddings (P4):** never light up real corpora until
  deny-by-default + RLS are proven.
- **Parsers (P7) after the ACL/embedding core:** real RAG runs on text/markdown first; pdf/docx/
  xlsx + OCR are additive per-format capability, and carry the heaviest dependency/approval load.
- **Alternative** if the owner wants the full document plane before any live LLM: run P2→P8 of WS1
  first and defer P1/P5/P6; the interleave above is the recommended value-first order.

## Approvals summary (per phase)

| Phase | New egress | New dependency |
| --- | --- | --- |
| P1 | chat model endpoint | none (stdlib client) |
| P4 | embedding model endpoint | none (stdlib client) |
| P7 | OCR endpoint + Confluence/REST | document-parser lib (post comparison) |

## Governance held across all live phases (WS5 5.6)

Per-call timeout, response-size cap, token budget, bounded retries + circuit-breaking on model/
embedding/OCR egress; grounding/output-contract/policy/fallback on every real generation path;
**no prompt/response content in logs, metric labels, or audit** (ids/counts/latency/stable codes
only); per-provider latency/error/token metrics on the Sprint 7 Prometheus surface.

## Links

- WS1: [`document-plane-plan.md`](document-plane-plan.md), [threat model](document-plane-threat-model.md)
- WS5: [`../phase-2-plan.md`](../phase-2-plan.md#workstream-5--live-model-runtime-real-generation-foundational)
- Reused seams: Sprint 6 release lifecycle, Sprint 7 metrics/tracing, Sprint 9 SSRF-safe egress.
