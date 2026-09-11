# Task Plan: sprint-4-rag-runtime

## Task summary

Implement Sprint 4 of the [v3 target plan](../../../agenthub-v3-django-plan.md#25-uygulama-asamalari):
the synchronous RAG runtime behind the gateway. Given a verified `ExecutionContext`
and the pinned active release, the runtime retrieves context, generates an answer,
validates it against the output contract, and applies grounding/citation/fallback
policy — so the gateway returns a real, governed result instead of the Sprint 3 stub.

## Background

Sprint 3 shipped the gateway with a runtime-facade seam returning `accepted`. This
sprint fills the seam with a provider-abstracted RAG runtime. The real
pgvector-backed retriever and a real LLM provider arrive in Sprint 5+/via
`ModelProfile`; Sprint 4 defines the provider interfaces and ships deterministic
default providers so the governed pipeline is testable now.

## Scope

- `retrieval`: `RetrievalProvider` interface, `RetrievedChunk`, and a static default
  provider (empty until the pgvector retriever lands in Sprint 5).
- `orchestration`: `ModelProvider` interface + a deterministic stub; a release-bundle
  resolver (cached by immutable release id); the `run_rag` engine; and the policy
  checks (grounding threshold, citations-required, fallback).
- Output-contract validation of the generated answer (model output that fails the
  contract never reaches the client — a fallback is returned instead).
- Gateway wiring: `dispatch` calls `run_rag`, passes the resolved release, records
  usage tokens, and maps runtime failures to stable error codes.

## Non-goals

- No real vector index (Sprint 5) or real LLM call — providers are pluggable seams
  with deterministic defaults. No reranker, streaming, PII redaction engine, or
  conversation memory yet.

## Acceptance criteria

From the v3 plan (Sprint 4):

- An invalid/expired `ExecutionContext` or a non-active release is rejected.
- Model output that violates the output contract does not reach the response.
- Below the grounding threshold, the policy fallback is returned.

## Affected components

New apps `retrieval`, `orchestration`. `gateway` runtime facade now delegates to
`orchestration.run_rag`. Citations are produced only by the runtime (never the model).

## Interfaces affected

Gateway `invoke`/`query` responses now carry a real `output` (`answer`, `sources`,
`fallback_used`) and `status` (`completed`), plus `usage` token counts. Internal
provider interfaces are new extension points.

## Data impact

No new tables. `UsageEvent` now records token counts. Release artifact bodies are
read (pinned, immutable) via the resolver.

## Security impact

- Output governance: the model's answer is validated against the output contract;
  invalid output is replaced by a server-controlled fallback (no leak).
- Citations are runtime-generated from retrieved chunks; model-fabricated
  source ids/URLs are never emitted.
- The runtime acts only on a verified `ExecutionContext` and a still-active release
  (fail-closed). Retrieved context is treated as untrusted.

## Authorization impact

None new; the runtime trusts the gateway-issued, verified context. Tenant scope for
retrieval derives from the context's organization.

## Observability impact

`UsageEvent` gains input/output token counts and `completed`/`fallback` status.
Runtime failures map to stable error codes (`RETRIEVAL_FAILED`,
`MODEL_PROVIDER_FAILED`, `OUTPUT_CONTRACT_VIOLATION`).

## Migration impact

None (no new models). Verified with `makemigrations --check`.

## Dependencies

None new (jsonschema already present). Real providers configured later via settings
dotted paths (`RUNTIME_MODEL_PROVIDER`, `RUNTIME_RETRIEVAL_PROVIDER`).

## Implementation steps

1. `retrieval` provider interface + static provider + `RetrievedChunk`.
2. `orchestration` model provider (stub) + release-bundle resolver (immutable cache).
3. `run_rag` engine + policy (grounding/citations/fallback) + output-contract check.
4. Wire gateway `dispatch` → `run_rag`; usage tokens; runtime error mapping.
5. Tests (invalid context / inactive release / grounding fallback / output-contract
   fallback / completed) + update Sprint 3 gateway tests for real output.
6. Gates on SQLite + PostgreSQL; live end-to-end; docs.

## Test plan

- `run_rag` rejects a tampered/expired context and a non-active release.
- Grounding required + no/low-score retrieval → `fallback_used=true`.
- Model output missing an output-contract-required field → fallback returned; the
  model's raw answer is not present.
- Grounded happy path → `completed`, `fallback_used=false`, runtime-built citations.
- Gateway invoke/query now return `completed` with an `output` object.

## Rollout plan

Additive; behind CI gates. Default providers are deterministic; real providers are
swapped in per environment via settings without code changes.

## Rollback plan

Revert the commit; the gateway returns to the `accepted` stub. No schema changes.

## Risks

- The release-bundle cache must never serve stale content: it is keyed by the
  immutable release id (artifacts are immutable), and the active-release pointer is
  read fresh each request — so no invalidation is required for correctness.
- Fallback must itself be safe/contract-shaped; it is server-controlled and returned
  without echoing model output.

## Open questions

- Prompt templating format and reranker profile shape (kept minimal here; expanded
  with the real providers).

## Status

Verified — all gates green; 65 tests pass on SQLite and real PostgreSQL; the runtime
was exercised live end-to-end showing both the grounding fallback and a grounded
answer with runtime citations on 2026-07-10. Evidence in
[`verification.md`](verification.md). Not yet `Completed`: real pgvector retriever +
real LLM provider (Sprint 5+), PII/injection hardening, and human review remain.

## Completion criteria

Map to the [Definition of Done](../../ai/definition-of-done.md): acceptance criteria
met with recorded evidence; output governance and fallback verified; gates green on
SQLite and PostgreSQL; docs and master plan updated.
