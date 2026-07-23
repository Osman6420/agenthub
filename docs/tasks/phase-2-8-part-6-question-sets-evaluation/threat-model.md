# Threat Model: Phase 2.8 Part 6 — Question sets and evaluation

## Assets and classification

Questions, expected/generated answers, expected source anchors, retrieved chunks/scores, question-set
versions, exact release/index/profile pins, judge prompts/verdicts and aggregate metrics. Content is
tenant-confidential; model credentials are restricted.

## Actors, entry points and trust boundaries

Authors/document managers/release roles/auditors, consumers, workers, retrieval/model/judge providers
and malicious content authors. Entry points are question-set CRUD/publish, test start/status/results,
one-off questions and worker/provider callbacks. All authored text, IDs, assertions, model output and
provider responses are untrusted.

## Principal threats and mitigations

| Threat | Required mitigation |
| --- | --- |
| Cross-tenant question/evidence access | Direct tenant lineage, object authorization, FORCE RLS and generic denial |
| Retrieval test bypasses consumer grants | Explicit authorized operator-test policy; never reuse it as consumer authority |
| Raw chunks/answers leak through logs/audit | Content-free logs/audit/metrics/errors; authorized bounded UI only |
| Mutable question/profile/release changes result | Exact immutable versions/checksums pinned on run |
| Judge prompt injection/manipulation | Closed pinned judge contract, bounded inputs, verdict schema validation |
| Judge failure counted as wrong answer | Explicit error/unscored state and denominator rules |
| Aggregate manipulated by retry/duplicates | Run/case uniqueness, idempotency and transactional aggregation |
| One-off question pollutes benchmark | No aggregate persistence without explicit save into mutable draft |
| Regex/complex assertion DoS | Closed bounded deterministic operations; no unbounded user regex/eval |
| Provider cost/resource abuse | Role checks, rate/case/token/time limits, cancellation and metrics |

## Logging, audit and residual risks

Audit version publish and run lifecycle with safe IDs/counts/checksums, never question/answer/chunk
content. LLM judge remains probabilistic even when pinned; show deterministic and judge measures
separately. Authorized chunk display remains a confidentiality surface and requires careful browser
cache/CSP/manual review.

## Required security tests

Cross-tenant set/version/run/evidence IDs; operator-test versus consumer-grant boundaries; role and
disabled-org denial; assertion input bounds; judge injection/malformed/timeout; duplicate/retry;
one-off persistence; redaction/cache behavior; retention; audit failure; PostgreSQL non-owner RLS.
