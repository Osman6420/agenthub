# Task Plan: Phase 2.8 Part 6 — Question sets and evaluation

## Task summary

Add reusable versioned question sets, document-set retrieval diagnostics and exact-release scenario
answer evaluation. Show retrieved chunks/scores and report retrieval quality separately from answer
quality, with deterministic assertions and an optional pinned LLM judge.

## Background

Existing `eval_suite` artifacts run deterministic assertions against candidate releases but do not
provide an operator-friendly question-set lifecycle, direct document-set retrieval testing, chunk
score inspection or separated retrieval/answer metrics. Operators need both repeatable batch tests
and one-off questions from document-set and scenario pages.

## Scope

- Add organization-owned QuestionSet, mutable draft/version lifecycle and immutable published
  QuestionSetVersion/Case records. A case contains a bounded question, expected answer assertions and
  optional expected document/version/passage anchors.
- Allow published question-set versions to be reused by authorized document sets and scenarios
  without copying or mutable “latest” references.
- Run document retrieval tests against an exact document-set version, active/staged index as
  explicitly selected, and exact retrieval profile. Persist a bounded evaluation run and per-case
  evidence identifiers/scores.
- Display authorized retrieved chunk text, document/source, ordinal and vector/BM25/fused score in
  the result UI. If retained immutable index content is unavailable, show evidence unavailable
  rather than substituting current content.
- Compute retrieval `hit@k`, `recall@k` and mean reciprocal rank from expected source/passage anchors.
  Cases without retrieval ground truth are excluded from retrieval denominators and counted as
  unscored.
- Run scenario answer evaluation through the exact candidate/active release and unified runtime.
  Compute a separate answer pass rate from deterministic exact, normalized-contains,
  citation/source and output-schema assertions.
- Add an optional LLM judge using a pinned immutable model profile and pinned judge prompt/contract
  revision. Store verdict, safe reason code and provenance, never chain-of-thought. Judge errors are
  “unscored”, not automatic answer failures.
- Add one-off “Sor” experiences to document-set and scenario pages. Show answer/retrieval evidence;
  do not affect aggregate metrics unless explicitly saved into a question-set draft.
- Provide batch run status, progress, separate metric cards, failed/unscored filters and case detail.

## Non-goals

- Training/fine-tuning, automatic release promotion based only on a percentage, mutable question-set
  pins, storing model chain-of-thought, using an unpinned tenant-selected judge endpoint or merging
  retrieval and answer results into one success percentage.

## Data contracts and scoring

- Questions, expected answers and anchors have explicit size/count limits and are tenant-confidential.
- Expected passage anchors use stable document/version plus a normalized passage checksum or bounded
  locator; raw expected passages are not copied into audit/logs.
- `hit@k`: at least one expected source/passage in top-k. `recall@k`: matched expected anchors divided
  by expected anchors. `MRR`: reciprocal rank of first match. Aggregate denominators include only
  cases with applicable ground truth.
- Answer pass rate includes applicable deterministic/judge assertions according to the published
  case policy. Errors and non-applicable assertions have explicit counters; the UI always shows
  numerator, denominator and unscored/error counts.
- Evaluation provenance pins question-set version, release/index/retrieval profile, model/judge
  profile, prompt contract and relevant checksums.

## Authorization matrix

Question-set drafts and document retrieval tests require document/scenario author authority as
appropriate; publishing follows the owning governed artifact/evaluation authority; exact-release
scenario evaluation follows existing evaluation/release roles; auditors may read redacted evidence
but cannot mutate or start runs unless already authorized. Every object is tenant-scoped; selecting
an active organization does not grant access.

## Acceptance criteria

- Operators can create, version, publish and reuse a question set without editing a published version.
- Document test results show the exact chunks and component/fused scores returned for each question.
- Correct-source expectations produce deterministic hit/recall/MRR values with explicit denominators.
- Scenario tests show answers and separate deterministic/judge verdicts plus an independent answer
  pass rate.
- One-off questions never change aggregate data without explicit save confirmation.
- Cross-tenant set/version/run/evidence/judge access is non-disclosing and protected by RLS.
- Raw confidential content is absent from logs, metric labels, audit payloads and safe errors.
- Retry/idempotency prevents duplicate runs/cases from corrupting aggregates.

## Migration, privacy and observability impact

Add direct-tenant question-set/version/case, evaluation-run and result/evidence tables with unique
version/case/run constraints, retention fields and FORCE RLS. Store bounded identifiers, scores,
checksums and optional generated answers only according to documented retention; do not duplicate
chunk bodies where exact index content can be resolved. Emit counts/durations/status metrics with
low-cardinality labels and content-free audit events for publish/start/complete/cancel.

## Dependencies

Part 5 search diagnostics/profiles for document evaluation; verified Part 3 runtime and Part 4
scenario/release context for answer evaluation. Existing eval assertions and release gates may be
reused but remain governed by their current services.

## Implementation steps

1. Define schema, retention/classification, authorization matrix and safe assertion vocabulary; add
   migrations/RLS before UI.
2. Implement draft/publish/version services with immutable pins, audit and concurrency protection.
3. Implement document retrieval runner/evidence and deterministic retrieval metrics over Part 5's
   common retrieval service.
4. Implement exact-release answer runner, deterministic assertions and optional pinned judge with
   bounded egress/provenance.
5. Add batch and case-result UI plus one-off document/scenario question forms; explicit “save to
   draft” is the only path into aggregate question data.
6. Add retention/redaction, cancellation/idempotency, observability and failure-state behavior.
7. Verify PostgreSQL RLS, calculations, provider failures, UX/accessibility and final diff.

## Test plan

Draft/version immutability and concurrent publish; question/anchor validation; exact retrieval metrics
with ties/missing/multiple anchors/top-k boundaries; component/fused score display; scenario answer
assertions; judge success/timeout/malformed/prompt version/provenance; one-off non-persistence;
idempotency/retry/cancel; cross-tenant/role/disabled/RLS; retention/redaction/audit; full quality,
migration, browser and accessibility checks.

## Rollout and rollback

Roll out additive tables and deterministic evaluation first; keep LLM judge disabled until an approved
profile/prompt and privacy/cost review exist. Disable new run admission without deleting historical
evidence. Rollback UI/workers while retaining immutable question/evaluation records; schema removal is
not required for application rollback.

## Risks

Misleading percentages, wrong denominators, content leakage through evidence, judge nondeterminism or
bias, stale mutable references, excessive token/cost use, duplicate result aggregation and coupling
evaluation directly to promotion without policy approval.

## Open questions

None. Deterministic scoring is the baseline; the pinned LLM judge is optional and separately gated.

## Status

**Implemented and automated/offline verified on 2026-07-29.** The repository-owned
`apps.evaluations` subsystem remains the implementation boundary. Existing release-gate
`eval_suite` behavior is backward compatible; Part 6 adds question-set, retrieval-evaluation and
richer answer-evaluation contracts alongside it. Judge use remains optional and environment-gated.

### Milestone status

- [x] Tenant-owned question-set, immutable version/case and evaluation evidence schema implemented.
- [x] PostgreSQL FORCE RLS, lineage constraints and non-owner policy verification implemented.
- [x] Draft/publish/reuse services and deterministic scoring implemented.
- [x] Exact document-set/index/profile retrieval evaluation implemented.
- [x] Exact-release answer evaluation and optional pinned judge boundary implemented.
- [x] Batch/case-result and one-off document/scenario console journeys implemented.
- [x] Redaction, audit, metrics, retry/idempotency, cancellation and retention behavior verified.
- [x] Focused, full repository and PostgreSQL/RLS evidence recorded; browser policy block and
  remaining authenticated visual owner acceptance are explicit in `verification.md`.

### Implementation assumptions

- Existing `apps.evaluations` is extended rather than introducing a parallel evaluation app.
- Existing `eval_suite` release gates and `run_eval()` callers retain their current contract.
- Part 5's `RetrievalProvider.retrieve()` is the only retrieval execution boundary; evaluation does
  not bypass its tenant/index/document-set filters or reuse operator-test authority as consumer
  authority.
- Deterministic evaluation ships enabled. LLM judge execution remains disabled unless an approved
  immutable model profile, prompt contract, privacy/cost review and environment flag are all present.

## Completion criteria

All scoring/provenance, authorization/RLS, redaction/retention, deterministic/judge failure and UX
criteria pass; current docs and manual journeys are updated; staff/AppSec/SRE/data/UX reviews close;
verification reaches Verified before archival.
