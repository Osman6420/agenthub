# AgentHub — Phase 2 Plan (DRAFT)

> **Status: DRAFT — under discussion (project owner + agent). Not approved for
> implementation.** This file captures the Phase 2 intent, the owner's decisions to date,
> and the open questions we still need to resolve before any code is written. Every new
> production dependency and every new external egress named below is a change-boundary item
> that requires explicit approval + a supply-chain/threat-model review first
> (see [`AGENTS.md`](../../AGENTS.md)).

## Purpose

Phase 1 (Sprints 0–11) delivered the verified governed platform: control plane, artifacts/
releases, gateway + MCP, RAG runtime, ingestion + pgvector, eval/promotion, workflow, tool
registry + approval, agent runtime, and the visual workflow builder. Phase 2 extends it
with a **governed document plane**, a **modernized Turkish UI**, **AI-assisted scenario
authoring** (alongside the visual builder), **personal (end-user) MCP with identity delegation**,
and a **foundational live model runtime** — the real LLM provider (base_url + token → actual
call) plus wiring the currently-stubbed generation/retrieval seams across RAG, workflow, and
agent so scenarios truly reach a live model.

## Priority order (owner-set)

1. **Document plane** — per-scenario sources + real ingestion + retrieval-time document
   authorization.
2. **UI modernization + Turkish** (i18n).
3. **AI-assisted authoring** (text → artifact → validate → preview → publish), coexisting
   with the visual builder.
4. **Personal MCP** (end-user identity + on-behalf-of delegation) — after everything else;
   to be detailed in a separate discussion.
5. **Live model runtime (real generation)** — a **foundational enabler added 2026-07-12**:
   implement the real LLM `ModelProvider` (give the app a base_url + token and actually reach the
   model) and wire the currently-stubbed generation/retrieval seams across RAG, workflow, and
   agent so scenarios truly reach a live model. **Sequencing to confirm with the owner**
   (recommended **together with WS1**, since both build on the same SSRF-safe egress + provider
   seam) — it is not "after WS4".

---

## Workstream 1 — Document plane (priority 1)

> **Detailed design (2026-07-12):** the owner's A–E decisions (hybrid tenant/document-set
> isolation, forward-ready principal model, independent `Document` lineage, `EmbeddingProfile`,
> external-OCR parser strategy) are worked out in
> [`components/document-plane-plan.md`](components/document-plane-plan.md) and
> [`components/document-plane-threat-model.md`](components/document-plane-threat-model.md).
> Those two documents are the authoritative WS1 design; the summary below is retained for
> context. Still **draft — not approved for implementation.**

### 1.1 Per-scenario document source management (console UI)

- A console page to manage the document sources a scenario may use, with **role-gated**
  create / read / update / delete and tenant scoping (reuse LDAP/session + Sprint 1 roles).
- New connectors beyond today's `https` / `s3`:
  - **Confluence** (by space / page ID),
  - **generic REST API** source,
  - **direct file upload** (drag-and-drop).
- Reuse the Sprint 5 `Source` model + pluggable connector registry (`apps.ingestion`);
  extend the `CONNECTORS` map. Credentials stay as `secret:<name>` references (never inline).

### 1.2 Scenario ↔ document-set binding (MANDATORY)

- A **required** binding between a scenario and its document set: a scenario retrieves
  **only** from its bound documents. Today `Source` is org-scoped and not linked to a
  scenario — this is the core new model.
- **Owner decision: this binding is mandatory** — no scenario serves retrieval without an
  explicit, authorized document set.

### 1.3 Real document parsing (pdf / txt / docx / xlsx → markdown)

- Add real parsers that convert `pdf` / `docx` / `xlsx` / `txt` to markdown before
  chunk + embed (today only a `text` parser exists).
- **New production dependencies required.** Owner decision: **research ready libraries**
  (candidates to evaluate, e.g. document-extraction toolkits) and choose after a
  provenance / license / maintenance / vulnerability review. Approval gate before adding.
- Upload → parse flow must validate content, size, type, encoding, and nesting independently
  of the filename and store uploads outside executable paths (security rules).

### 1.4 Real embedding provider (OpenAI-compatible)

- Replace the deterministic 64-dim stub with a **real OpenAI-compatible embedding provider**
  over **external HTTPS** with SSRF-safe egress (timeouts, size caps, controlled
  destinations) and `secret:<name>` credentials.
- **Owner decision:** test → **cloud models**; production → **local OpenAI-compatible LLM**.
- **Decision refined (2026-07-12) — the authoritative WS1 design supersedes the notes above:**
  the client is an `OpenAICompatibleEmbeddingClient` adapter over the **Sprint 9 SSRF-safe
  stdlib transport**, so **no `openai` dependency is added** at this stage; the endpoint is a
  **platform-allowlisted internal endpoint** (no tenant/request `base_url`), and model +
  dimensions come from a **platform-managed, immutable `EmbeddingProfile`** catalog. A dimension
  change flows through a **staged, immutable blue/green reindex** with a **metadata-atomic
  pointer-flip promotion** — not an in-place column/HNSW mutation. See
  [`components/document-plane-plan.md`](components/document-plane-plan.md).

### 1.5 Document-set authorization (retrieval-time ACL) — highest security risk

- Enforce that a scenario / consumer retrieves **only** from documents it is authorized for:
  a retrieval-time authorization filter with cross-tenant / cross-scope denial and negative
  tests. This is the most sensitive part of Phase 2 and gates any real-corpus rollout.

---

## Workstream 2 — UI modernization + Turkish (priority 2)

- Restyle the operator console + builder (style / color / layout / components).
- Add **i18n**; **screens in Turkish**. Keep server-side authorization authoritative and
  encoding safe (no XSS from localized/stored content).

---

## Workstream 3 — AI-assisted authoring + visual builder coexistence (priority 3)

- **Primary authoring path (AI-assisted):** the user describes the scenario they want in
  **free text** → sent to an LLM **with the DSL rules** → the model returns a **candidate
  artifact** → validated by the existing canonical validator/compiler → **preview** →
  publish through the existing artifact / compile / eval / promote path. No bypass of any
  governance control; the LLM output is untrusted and always re-validated server-side.
- **Owner decision — do not conflict the two:** AI-assisted authoring is the fast primary
  path; the **visual React Flow builder becomes the preview surface** where **small DSL
  edits** are allowed. They coexist; neither replaces the other.
- **Owner decision:** artifacts created **via endpoint OR via AI** must be **visible in the
  UI at the DSL level** (an artifact detail / preview view). Builder scope is trimmed — no
  agent-to-MCP binding, system-prompt entry, or model selection inside the builder; keep
  that in the DSL.
- LLM egress reuses the same SSRF-safe / secret-ref governance as embeddings (test → cloud,
  prod → local OpenAI-compatible).

---

## Workstream 4 — Personal MCP (end-user identity + delegation) [LAST]

- Personal MCP calls bound to an **end-user identity** (e.g. "grant my access", "get my
  payroll").
- Verify the person, then **forward / delegate on-behalf-of** to the next system (e.g. an
  **ERP**), with impersonation-safe controls and full audit (authenticated + effective +
  impersonating identity).
- This is a **significant identity/authorization expansion** — today only machine/consumer
  identity exists. **Owner decision: do this after all other workstreams; discuss in more
  detail separately.**

---

## Workstream 5 — Live model runtime (real generation) [FOUNDATIONAL]

Added 2026-07-12 at the owner's instruction: *"everything you flagged as missing must be
completed."* Today the runtime ships **only deterministic stubs** — a `model_profile` artifact
can declare `endpoint` + `model` + `secret:<name>` token, but no provider actually calls it, and
several generation/retrieval seams are placeholders. This workstream makes scenarios reach a real
model. It is **foundational** (nothing is a real product without it) and reuses the WS1 SSRF-safe
egress; the owner sets its final sequence (recommended alongside WS1).

### Current gaps (verified by code inspection 2026-07-12)

- **No real model provider.** `apps/orchestration/providers.py` contains only
  `StubModelProvider`; `RUNTIME_MODEL_PROVIDER` defaults to empty. `model_profile`
  (`endpoint`/`model`/`api_key: secret:<name>`) is declared but never invoked.
- **Agent retrieval is a stub.** The agent loop's `retrieve` decision returns empty chunks
  (`apps/agents/runtime.py`) — agents do **not** do real document RAG today; only the standalone
  `run_rag` (`/v1/query`) path calls the real pgvector retriever.
- **Workflow `generate`/`retrieve` nodes are stubs.** `apps/workflows/runtime.py` writes a fixed
  `{"answer": "generated"}` and empty chunks; no model call, no per-node prompt.
- **Agents have no authored system prompt.** `agent_definition` carries no prompt text; the loop
  uses the raw user objective as the prompt.
- **Multi-prompt scenarios are only drawable, not runnable.** The workflow DAG can hold multiple
  `generate` nodes, but with stubbed generation there is no real multi-prompt / multi-model flow.

### 5.1 Real LLM `ModelProvider` (base_url + token → live call)

- Implement an `OpenAICompatibleModelProvider` (chat/generation) over the **Sprint 9 SSRF-safe
  stdlib transport** (same pattern as the WS1 embedding client — reuse target/scheme/host
  validation, resolved-IP pinning, redirect denial, timeouts, response-size cap, bounded retries,
  redacted audit). Driven by the `model_profile` artifact: `provider`, `endpoint`/base_url,
  `model`, `secret:<name>` token, `timeout_seconds`; plugged via `RUNTIME_MODEL_PROVIDER`.
- **Endpoint governance:** platform-allowlisted destinations; test → cloud, prod → local
  OpenAI-compatible. Decide whether the endpoint is free-form per `model_profile` (author-set) or
  restricted to a platform allowlist like WS1 embeddings — **open decision** (recommend allowlist
  + author selects among allowlisted model profiles, mirroring the `EmbeddingProfile` catalog).
- **No `openai` dependency** unless a later review approves it; default is the stdlib client.

### 5.2 Light up RAG generation

- Once 5.1 exists, `run_rag` (`/v1/query`) reaches the real model with no runtime change (the
  generate seam already calls the provider). Verify grounding gate, output-contract governance,
  citation policy, fallback, token usage, and redaction all hold on the live path.

### 5.3 Wire real retrieval into the agent + workflow

- Replace the agent `retrieve` stub and the workflow `retrieve` node with the governed retrieval
  provider (WS1 ACL-scoped pgvector), so agents and workflows do **real, authorized document RAG**
  — not just the standalone query path.

### 5.4 Real workflow generation + multi-prompt / multi-model

- Wire the workflow `generate` node to the real provider with **per-node prompt/model binding**:
  a `generate` node references a governed `prompt` role/template (data, validated, redaction-safe)
  and optionally a specific `model_profile`. This enables **scenarios that need several different
  LLM prompts** (multiple `generate` nodes in one DAG, each with its own prompt/model), all still
  governed by contracts/policy/fallback.

### 5.5 Agent system prompt (authored, governed)

- Extend `agent_definition` to reference a governed **system-prompt / instruction** artifact
  (data, not code: validated, bounded, redaction-safe, checksummed, pinned in the release) so an
  agent has an authored persona/instructions. Today there is none. Keep the loop's tool/decision
  re-validation unchanged (the prompt is an input, never authorization).

### 5.6 Governance, cost, and observability on live paths

- Enforce per-call **timeout, response-size cap, token budget**, bounded retries with backoff, and
  circuit-breaking on model egress; grounding/output-contract/policy/fallback on every real
  generation path (RAG, workflow, agent); **no prompt/response content in logs, metrics labels, or
  audit** (ids/counts/latency/stable codes only). Add per-provider latency/error/token metrics
  reusing the Sprint 7 Prometheus surface.

### Relation to other workstreams

WS5 makes generation *work*; **WS3** (AI-assisted authoring + artifacts visible/editable in the UI
at DSL level) makes prompts/models *authorable and visible in the UI* instead of GitOps-only. WS5
reuses the **WS1** SSRF-safe egress and provider-catalog pattern. Dependencies/egress here follow
the same explicit-approval + supply-chain/threat-review gate.

## Cross-cutting constraints

- Every new production dependency and every new external egress needs **explicit owner
  approval + supply-chain + threat-model review** before implementation. WS1 decision
  (2026-07-12): **no `openai` dependency** for embeddings — the client reuses the Sprint 9
  SSRF-safe stdlib transport; only the document-parser dependency remains pending the WS1
  comparison (see [`components/document-plane-plan.md`](components/document-plane-plan.md)).
- Reuse the existing controls: tenant isolation, deny-by-default authorization,
  `secret:<name>` handling, redaction, and the append-only audit trail.
- Real model providers plug in behind the existing provider seams
  (`RUNTIME_MODEL_PROVIDER` / `RUNTIME_RETRIEVAL_PROVIDER`) — no runtime rewrite.

## Relationship to Sprint 11

Sprint 11 delivered a subset of the originally-approved builder scope. Several planned
enhancements are **reclassified into this Phase 2 plan** because the builder is being
repurposed toward AI-assisted authoring + preview (Workstream 3):

- Artifact **detail / preview** view for endpoint- and AI-produced artifacts (→ Workstream 3).
- GitOps **export of a draft** / import → draft seed (→ Workstream 3).
- Builder-embedded **test / eval / trace panels** (today the builder links out to the existing
  console screens) — reconsider under Workstream 3's preview surface, or keep as console links.
- Optimistic concurrency (revision/ETag + visible conflict), autosave debounce, soft-delete
  retention/purge, a distinct `project_editor` permission, and a Content-Security-Policy —
  to be reconsidered under the trimmed-builder direction (some may no longer be needed).

See the consolidated Sprint 11 record:
[`sprint-11-workflow-builder`](../tasks/sprint-11-workflow-builder/plan.md).

## Open questions

**Workstream 1 — resolved in the authoritative design**
([`components/document-plane-plan.md`](components/document-plane-plan.md)): document ACL
granularity + index isolation (hybrid — tenant is the physical boundary, document-set version
is the logical ACL/retrieval unit; no per-scenario physical index), embedding
dimension/reindex (platform-managed `EmbeddingProfile` + immutable blue/green reindex +
metadata-atomic pointer-flip promotion), and the parser approach (format-specific stack behind
a `DocumentParser` interface; final library chosen at M4). Remaining WS1 items are milestone
decisions, not open blockers: Confluence/REST connector auth + rate/size limits, upload storage
backend + malware/type scanning (M4), and the concrete embedding/OCR endpoints, egress
allowlist, and secret provisioning (deployment config).

**Workstreams 2–4 — still open (not yet decomposed):**

- UI framework/theming approach and localization ownership (WS2).
- AI-authoring LLM prompt/DSL-rule contract and the exact scope of preview-time DSL edits (WS3).
- Personal-MCP identity source (which IdP), the OBO token format, and the downstream (ERP)
  trust/verification contract (WS4).

## Status

Draft. **Workstream 1 is design-complete and authoritative** (component plan + threat model
under [`components/`](components/)) but **not approved for implementation**; its immediate next
step is the two **M0 design spikes** (pgvector multi-dimension storage; RLS connection context)
documented before any migration or code. **Workstreams 2–4 remain in discovery** and are not
yet decomposed into component plans.

### Workstream status

| WS | Scope | Status |
| --- | --- | --- |
| 1 | Document plane | Design complete (component plan + threat model) — implementation **not approved**; M0 spikes pending |
| 2 | UI modernization + Turkish | Discovery — not decomposed |
| 3 | AI-assisted authoring (+ builder preview) | Discovery — not decomposed |
| 4 | Personal MCP (identity + delegation) | Discovery — to be detailed separately, last |
| 5 | Live model runtime (real generation) | Scoped 2026-07-12 — **foundational**; sequence to confirm (recommended with WS1); not started |

---

## Appendix — owner raw notes (Türkçe, verbatim)

Original `docs/TO-do_ikinci_faz.md`, preserved verbatim so intent is not lost in
translation:

```
TO-do ikinci faz

Belli bir senaryonun erişeceği dokuman ların kaynakları birinin yonetmesi, kaldırılacaksa
silmesi için bi sayfa olacak yetkilendirme yapısına göre erişileccek(confluence da şu id
altındakiler, şu rest apiden gelenler, drag drop ile dokuman ekleme)
bu dokumanların belli formatlarda(pdf, txt, docx, xlsx) md ye donüştürülüp, chunklanıp
vectorleştirilip db ye basılması(embedding model openai format ında dışardan bağlanacak llm
gibi)
senaryo dokuman guvenlik yetki yapısıyla kurgulanacak.

arayuz moderleştirilecek (stil renk şekil vs) ekranlar türkçe olacak

build ekranında agent a mcp baglama sistem prompt verme model seçme vs yok. çok kompleks
olacaksa dsl de kalsın builder sadece mevcut artifactleri ekranda göstersin
build ekranında kullanıcı oluşturmak istediği senaryo metin olark alınacak, dsl in kuralları
ile yapay zekaya gonderilecek artifact yapay zekadan alınacak.
arayüz üzerinden değil de endpoint le artifact ekleniyor mu. o artifact arayüzde
goruntulenebiliyor mu, olmalı

senaryolar dışarı http ve mcp olarak sunulabilsin. kişisel mcp çagrıları için (bana izin
gir, bordromu getir vs) kişi doğrulamasını yapabilecek bir sonraki sisteme(erp vs.)
iletebilecek yapı kurgulansın
```
