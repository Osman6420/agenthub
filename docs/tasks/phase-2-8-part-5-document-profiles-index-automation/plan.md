# Task Plan: Phase 2.8 Part 5 — Document profiles and index automation

## Task summary

Make document sets the only normal document workspace, implement governed chunking and
keyword/vector/hybrid retrieval end to end, add optional pinned LLM summaries, apply the
document-manager role and automate staged index preparation without silent activation.

## Background

The repository validates `chunking_profile` strategies and keyword/vector/hybrid
`retrieval_profile` artifacts, but staged builds still use fixed character chunking and runtime
document-set retrieval is vector-only. Documents can also exist outside a set, an advanced storage
inventory remains visible, and lifecycle presentation can mark later stages ready despite unmet
prerequisites.

## Scope

- Upload/create documents only inside an authorized document set and immediately create draft-set
  membership. Remove standalone storage-management navigation from normal UX.
- Deny every new unbound document at the service boundary. Inventory existing unbound rows and
  provide a separate dry-run/confirmed cleanup workflow with pin/hold/backup protections.
- Resolve exact published chunking and retrieval profiles into build/runtime fingerprints. Profile
  changes always create a new immutable index version.
- Implement characters, tokens, headings, pages and tables strategies with bounded size, overlap and
  maximum chunks; report unsupported parser/strategy combinations safely.
- Implement PostgreSQL BM25-style full-text keyword search per immutable index store and retain
  vector search. Hybrid uses weighted reciprocal-rank fusion; expose vector rank/score, keyword
  rank/score and fused score. Apply threshold to the documented normalized/fused score.
- Preserve tenant + consumer grant + pinned document-set-version + active-index + tombstone
  intersection for all retrieval modes.
- Add opt-in document-version summary generation after upload/parse using an approved pinned model
  profile and prompt/contract revision. Store provenance/checksum and index the summary as a
  distinguishable synthetic summary chunk.
- If summary is requested and fails, mark preparation/build with a stable visible error; do not
  silently omit it. Summary content is not logged.
- A published set version may automatically enqueue staged index preparation. Activation remains an
  explicit `can_manage_releases`/document lifecycle action under the approved matrix.
- Make old set/document/index versions addressable and clickable; calculate lifecycle state from
  prerequisite truth so blocked later stages cannot show “Ready”.
- Apply `document_manager` to upload, replace, set draft/version, source, build and permitted index
  operations, but not release/scenario/consumer/role operations.

## Non-goals

- Automatic index activation, tenant-selected network endpoints/secrets, ungoverned summarization,
  deleting published/held content, a global raw-object storage console, question-set evaluation or
  changing public execution APIs.

## Canonical profile behavior

- Chunking profiles are immutable/versioned artifacts and part of the pipeline fingerprint.
- Retrieval profiles select `keyword`, `vector` or `hybrid`, bounded `top_k`, threshold and hybrid
  weights summing to one. `metadata_filter` remains a validated reserved/no-op contract field;
  runtime metadata modeling/enforcement moved to Phase 3 by owner decision on 2026-07-28.
- Weighted reciprocal-rank fusion uses a fixed documented rank constant and profile weights so BM25
  raw-score scale cannot dominate vector similarity. Diagnostic raw/component scores are not
  treated as comparable percentages.
- Summary configuration is optional/off by default and pins model profile, prompt contract revision,
  maximum input/output and language behavior. Summary chunks retain source document/version and a
  `summary` kind; citations still resolve to the source document.

## Acceptance criteria

- Normal UI/services cannot create an unbound document; upload transaction leaves document/version
  and draft membership consistent or rolls back.
- All validated chunking strategies either execute deterministically for supported parsed structure
  or fail with a stable compatibility code.
- Keyword, vector and hybrid modes return authorized results only and expose correct diagnostics.
- Profile or summary provenance changes produce a different pipeline fingerprint/new index.
- Summary enabled/disabled/failure behavior is explicit and reproducible.
- Auto preparation never changes the active index pointer; activation remains authorized/audited.
- Document manager passes the positive document matrix and all negative non-document cases.
- Cleanup dry-run reports exact tenant/object/pin/hold state; apply refuses unsafe rows and requires
  explicit separately recorded approval.
- Lifecycle UI and old-version deep links reflect actual prerequisite state.

## Data and migration impact

Add summary/provenance records and keyword-search structures/direct tenant lineage as required. Each
per-index store must have reviewed PostgreSQL DDL, safe identifiers and RLS-compatible access. Add
fingerprint/profile references without rewriting immutable historical versions. Cleanup is not part
of the additive migration: it is a separate command/operation with dry-run, exact targets, audit and
backup/rollback evidence.

## Security, privacy and external systems

BM25 queries are parameterized; physical table/index identifiers use the existing closed validated
store-name pattern. Retrieval never trusts client tenant/index/grant IDs. Summary egress uses the
shared SSRF-safe model profile/secret boundary with time/size limits. Document/chunk/summary text is
tenant-confidential and excluded from logs, metrics and audit bodies.

## Dependencies

Part 2 document-manager authority; existing document-set versions/grants, staged index lifecycle,
embedding profiles, parser/OCR/connectors and PostgreSQL pgvector/RLS. Independent of Part 3.

## Implementation steps

1. Inventory document creation paths and existing unbound/pinned/held rows; add denial tests and a
   non-mutating report before changing UI.
2. Make set-context upload atomic and remove normal standalone storage entry points.
3. Bind exact chunking profile to staged builds; implement/test structural strategies and pipeline
   fingerprints.
4. Add per-index keyword search and retrieval service; implement vector/keyword/hybrid diagnostics
   with common tenant/grant/tombstone filtering.
5. Add optional summary job/provenance/state, safe model egress and summary-chunk indexing.
6. Wire automatic staged preparation with idempotency/outbox/retry and retain explicit activation.
7. Correct lifecycle computation, historical links and role-honest actions.
8. After separate approval only, run cleanup dry-run, review exact targets, back up and apply bounded
   deletion; record database/object-store reconciliation and audit evidence.

## Test plan

Atomic set upload and unbound denial; all chunk strategies/bounds; profile fingerprint/rebuild;
PostgreSQL BM25/vector/hybrid ranking and diagnostics; ACL/grant/tombstone/cross-tenant RLS; summary
enabled/disabled/provider timeout/size/audit/redaction/provenance; automatic build idempotency,
worker retry and no-auto-activation; document-manager matrix; lifecycle/historical links; cleanup
dry-run/refusal/apply/rollback; quality/static/migration/browser tests.

## Rollout and rollback

Roll out additive profile/search/summary schema first, backfill no content, build new staged indexes
and compare before activation. Disable automatic preparation/summary independently on failure.
Existing active indexes remain serveable. Rollback code without deleting new immutable evidence.
Cleanup occurs last and has its own backup/restore boundary.

## Risks

Score semantics mislead users; BM25/vector ACL divergence; parser/profile mismatch; summary leakage or
hallucination; expensive rebuilds; automatic preparation mistaken for activation; deleting unbound
content still referenced outside modeled pins; role creep.

## Open questions

None for implementation design. Cleanup targets and destructive apply approval are intentionally
resolved from the later inventory rather than assumed here.

## Current implementation decisions

- The additive implementation is active on `feat/foundation-sprint-0-1` from the verified Part 4
  baseline. The working tree was clean at task start.
- Existing public standalone document upload/create paths will be closed. Internal ingestion and
  console paths must supply an exact draft document-set version so document/version creation and
  membership are one database invariant.
- Published immutable `chunking_profile` artifacts will be pinned directly on each new
  `IndexVersion`; retrieval profiles remain exact release inputs and are enforced by the shared
  authorized retrieval path.
- Keyword and vector candidates will come from the same tenant-scoped immutable physical store.
  Hybrid fusion uses a fixed reciprocal-rank constant and applies the threshold only to the
  normalized fused score.
- Optional summary configuration and provenance are additive and fail closed during preparation.
  No document, chunk, query, prompt or summary body is written to logs or audit payloads.
- Automatic preparation is idempotent and produces only a staged/promotable index. It never changes
  an active index pointer.
- Existing unbound rows are in scope only for an exact, non-mutating inventory/dry-run command.
  Cleanup apply, object deletion and database deletion remain outside the approved scope.
- Retrieval metadata schema/storage/query enforcement is outside Part 5. The existing
  `metadata_filter` field remains accepted for forward compatibility but has no runtime effect and
  is documented accordingly; Phase 3 owns implementation and its authorization-negative tests.
- The follow-up hierarchical retrieval extension is opt-in through exact retrieval-profile fields.
  It first ranks only `summary` chunks into a bounded set of exact `DocumentVersion` IDs, then
  searches only `content` chunks from those documents. Returned grounding remains source content,
  never the derived summary. If no authorized summary candidate exists, it falls back to the
  existing direct chunk path so enabling the option does not turn missing summaries into an empty
  answer.
- Hierarchical routing keeps the same tenant/grant/active-index/tombstone intersection in both
  stages. It caps selected documents and chunks per document to prevent fan-out and one-document
  domination. Summary-derived routing scores are diagnostic only and are not represented as source
  confidence.

## Status

**Implemented and repository/PostgreSQL verified; browser acceptance pending.** The additive schema
and services, PostgreSQL retrieval/RLS path, hierarchical summary routing, console lifecycle and
non-mutating inventory are verified by focused and full-suite tests. The requested authenticated
browser walkthrough could not complete because the in-app browser transport closed during its safe
runtime reconnect. Destructive cleanup apply remains a separately authorized operation and was not
performed.

## Completion criteria

Additive and optional-cleanup gates have separate evidence; PostgreSQL retrieval/RLS, egress,
authorization, audit, migration and UX criteria pass; current docs are updated; staff/AppSec/SRE
reviews close before Verified/archive.
