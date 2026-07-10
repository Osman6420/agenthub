# Threat Model: sprint-4-rag-runtime

## Assets

- The generated answer and its citations returned to consumers.
- The pinned release bundle (prompt, policy, contracts, profiles).
- Retrieved context (treated as untrusted input to the model).

## Trust boundaries

- Gateway → runtime (verified `ExecutionContext` only).
- Retrieved content / model output → response (governed by contract + policy).
- Runtime → providers (retrieval, model) — external/opaque, bounded.

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Model emits output violating the contract (leak, oversize, wrong shape) | Generated output is validated against the release output contract; on failure a server-controlled fallback is returned — the model output never reaches the client. |
| Model fabricates source ids/URLs (citation spoofing) | Citations are built by the runtime from retrieved chunks only; model-provided sources are ignored. |
| Ungrounded/hallucinated answer served | Grounding policy: if required and retrieval is empty or below `min_top_score`, a fallback is returned instead of an answer. |
| Acting on a forged/expired context or stale release | Runtime runs only on a verified context and re-checks the release is active (fail-closed). |
| Prompt injection via retrieved context | Retrieved context is treated as untrusted; it is not executed as instructions (policy hardening expands in later sprints). |
| Cross-tenant retrieval | Retrieval scope derives from the context organization; the pgvector retriever (Sprint 5) enforces tenant/index filters in-query. |
| Sensitive data in usage/trace | UsageEvent stores counts/status/ids only — no prompt text, no PII, no secrets. |

## Residual risk

- Default providers are deterministic stubs; real retrieval (pgvector) and a real LLM
  are integrated later, at which point provider timeouts, size limits, and PII
  redaction must be validated.
- Prompt-injection defenses are minimal in this MVP (untrusted-context marking);
  full policy enforcement (PII redaction, instruction-stripping) is later work.
