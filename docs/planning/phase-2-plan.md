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
authoring** (alongside the visual builder), and — last — **personal (end-user) MCP with
identity delegation**.

## Priority order (owner-set)

1. **Document plane** — per-scenario sources + real ingestion + retrieval-time document
   authorization.
2. **UI modernization + Turkish** (i18n).
3. **AI-assisted authoring** (text → artifact → validate → preview → publish), coexisting
   with the visual builder.
4. **Personal MCP** (end-user identity + on-behalf-of delegation) — after everything else;
   to be detailed in a separate discussion.

---

## Workstream 1 — Document plane (priority 1)

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
  The `openai` client library may be used (approval + supply-chain review still required).
- Real embeddings change the vector dimension → **pgvector column + HNSW index
  reconfiguration**, plus a reindex / migration strategy for existing chunks.

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

## Cross-cutting constraints

- Every new production dependency (document parsers, `openai` client) and every new external
  egress (embeddings, LLM) needs **explicit owner approval + supply-chain + threat-model
  review** before implementation.
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
- Optimistic concurrency (revision/ETag + visible conflict), autosave debounce, soft-delete
  retention/purge, a distinct `project_editor` permission, and a Content-Security-Policy —
  to be reconsidered under the trimmed-builder direction (some may no longer be needed).

See the consolidated Sprint 11 record:
[`sprint-11-workflow-builder`](../tasks/sprint-11-workflow-builder/plan.md).

## Open questions (to discuss)

- Document ACL granularity: per-source, per-document, or per-scope? Shared vs. per-scope
  pgvector indexes for isolation?
- Confluence / REST connector auth model and rate/size limits; upload storage backend and
  malware/type scanning.
- Chosen document-parser libraries (and their licenses/footprint) and the embedding
  dimension / reindex/migration plan.
- Which OpenAI-compatible endpoints (cloud test + local prod), egress allowlist, and secret
  provisioning.
- Personal-MCP identity source (which IdP), the OBO token format, and downstream (ERP)
  trust/verification contract.
- UI framework/theming approach and localization ownership.

## Status

Draft. Next step: refine priorities/scope with the owner, then split into approved
component plans under `docs/planning/components/` with per-workstream threat models before
any implementation.

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
