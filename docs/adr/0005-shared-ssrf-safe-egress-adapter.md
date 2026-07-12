# ADR 0005: Shared SSRF-safe egress adapter for model, embedding, and OCR calls

- **Status:** Accepted
- **Date:** 2026-07-12

Records the output of **Phase 2 · WS1/WS5 M0 Spike 3** (shared egress adapter). It **implements the
mechanism** for the governance decided in
[ADR-0002](0002-model-embedding-egress-profile-catalog-stdlib-adapter.md) (platform-managed profile
catalog, profile-ID-only references, stdlib adapter, SDK deferred). Accepted; implementation timing
is gated by Phase 2 approval.

## Context

WS5 (chat model) and WS1 (embedding model, external OCR) each need outbound HTTPS to an
OpenAI-compatible or OCR endpoint. Building three separate egress paths would triplicate SSRF
controls and drift. The Sprint 9 tool egress (`apps/tools/egress`) already implements a public-
unicast-only, resolved-IP-checked stdlib transport; this ADR settles the **single adapter contract**
reused by all three call sites.

## Considered options

1. **Per-call-site HTTP code.** Fastest locally; guarantees drift and inconsistent SSRF posture.
2. **A shared adapter, but callers pass a URL.** Centralizes transport but re-opens the SSRF hole
   ADR-0002 closed (author/tenant-influenced destinations).
3. **A shared adapter that accepts a profile ID only and resolves the destination from the platform
   catalog**, over the Sprint 9 SSRF-safe transport. **Chosen.**

## Decision

- **Contract.** `egress.call_json(profile_id, operation, payload) -> Response`. Callers pass a
  **catalog profile ID** and an operation (`chat`, `embeddings`, `ocr`) — **never a raw URL, host,
  scheme, header set, or TLS option**. The adapter resolves `profile_id` through the platform
  `ModelProfile`/`EmbeddingProfile`/OCR-profile catalog to `{endpoint, model, secret_ref,
  tls_policy, timeout}`, resolves `secret_ref` from the secret manager at call time, builds the
  request server-side, and returns a bounded, parsed response. One adapter, three response parsers.
- **Transport controls (reused from Sprint 9, enforced at one choke point):**
  - scheme = https only; host taken from the resolved profile endpoint;
  - DNS resolution then **validate every resolved IP is public unicast** — reject private, loopback,
    link-local, and cloud-metadata ranges — and **connect to the validated IP with SNI/Host set to
    the hostname** (defeats DNS rebinding);
  - **redirects denied**; **TLS certificate verification on** (no per-request opt-out);
  - connect/read **timeouts**; **response-size cap** enforced while streaming;
  - **redacted audit** — record ids/operation/latency/status only; never the URL query, headers,
    token, prompt, or response body.
- **Idempotency — no blind retry (per ADR-0002).** Failures are classified:
  - **Provably pre-send** (for example DNS failure, connect refused, or TLS handshake failure
    before any request byte is written): bounded retry with exponential backoff + jitter.
  - **HTTP 429/503:** receiving an HTTP response means the request may have been processed; these
    responses are retried only when the provider contract documents the operation as idempotent
    (or a provider-supported idempotency key makes it so). `Retry-After` is honored only after that
    safety condition is met. Otherwise the call is not automatically re-sent.
  - **Post-send** (request bytes were written, then read timeout / reset / partial response):
    **no retry** — return `outcome_unknown` to the caller. Callers handle it per their governance:
    RAG generation → server fallback; ingestion embedding → fail the chunk/build for controlled
    re-drive (never silent re-send); agent/workflow → their existing terminal-code handling.
    Provider-declared idempotency keys may be used where a provider documents them.
- **Call sites.** chat (WS5 `OpenAICompatibleModelProvider`), embeddings (WS1
  `OpenAICompatibleEmbeddingClient`), OCR (WS1 parser image dispatch) all go through this adapter.
  No `openai` dependency (ADR-0002).

## Security consequences

- SSRF/DNS-rebinding defenses and TLS verification live in one place and cannot be weakened per
  call or per profile. Destinations are catalog-resolved, not author/tenant-influenced. Secrets are
  resolved late and never logged.

## Operational consequences

- One transport to maintain and test; per-provider quirks live in thin response parsers. Live egress
  is opt-in per environment (test → cloud, prod → local) and gated by the deterministic-profile
  fallback, so CI performs no live calls.

## Negative-test matrix (required before any live phase promotes)

- Rebinding (public A record that resolves to a private IP) is blocked; private/loopback/link-local/
  metadata endpoints are rejected; a redirect is denied; an oversized response is truncated/failed;
  a TLS-verification failure aborts; a caller-supplied URL/host/scheme is rejected (only profile IDs
  accepted); a post-send timeout yields `outcome_unknown` and is **not** retried; a provably
  pre-send failure retries within bounds; 429/503 is not retried without a documented idempotency
  guarantee; secrets/prompts/URLs are absent from logs and audit.

## Data and privacy consequences

- Prompts, embeddings inputs, document images, responses, endpoints, and secrets stay out of logs,
  metric labels, and audit (ids/latency/status/stable codes only).

## Migration impact

- Additive: a shared `egress` adapter module reusing `apps/tools/egress`, plus the profile catalog
  resolution path. The `model_profile` artifact stops inlining endpoint/secret (ADR-0002). No
  consumer-contract change.

## Rollback considerations

- Each call site is behind its provider seam with the deterministic profile as fallback; a faulty
  live provider is disabled by configuration without data loss. Adopting an SDK later is a new ADR
  superseding ADR-0002 decision 2, not a change to this adapter's SSRF contract.

## References

- [ADR-0002](0002-model-embedding-egress-profile-catalog-stdlib-adapter.md) — governance this implements.
- [Document plane plan](../planning/components/document-plane-plan.md) — Spike 3, embedding/OCR egress.
- [WS1+WS5 sequence](../planning/components/runtime-and-document-plane-sequence.md) — P1/P3/P7 egress gates.
- Reuses the Sprint 9 SSRF-safe egress (`apps/tools/egress`).
