# ADR 0002: Model/embedding egress via a platform-managed profile catalog and a stdlib OpenAI-compatible adapter

- **Status:** Accepted
- **Date:** 2026-07-12

Governs how the runtime reaches external chat and embedding models (Phase 2 Workstreams 1 and 5).
The decision is accepted; its *implementation timing* is gated by Phase 2 approval. It supersedes
the earlier convenience of inlining `endpoint`/`api_key` inside the `model_profile` artifact
(see `gitops/mcm/artifacts/model_profile_default_chat.yaml`).

## Context

AgentHub must call real OpenAI-compatible chat and embedding endpoints (test → cloud, prod →
local). Today only a deterministic stub ships and the `model_profile` artifact inlines an
endpoint + secret reference. The owner set the durable architecture for external model/embedding
egress. Two coupled questions: (a) who may choose the destination/credentials, and (b) do we adopt
the official `openai` SDK or a small in-house adapter.

## Decision drivers

- **SSRF / tenant safety:** a host allowlist alone is insufficient; the destination and connected
  IP must be controlled, and untrusted authors/tenants/prompts must not steer egress.
- **Supply chain:** fewer transitive dependencies ease CVE tracking, SBOM, and air-gapped
  mirroring; a full SDK enlarges that surface.
- **Egress-policy fidelity:** we must own retry/redirect/DNS/IP-pinning/timeout behavior; an SDK's
  retry/redirect/streaming/proxy/env-var/custom-transport defaults may not match our policy, and
  SDK version bumps can change request/response and retry behavior.
- **API surface:** the near-term need is embeddings + bounded chat-completions — a small surface
  where a full SDK adds little.

## Considered options

1. **`openai` SDK, author-set endpoints per `model_profile`.** Fastest, but couples egress control
   to SDK internals and lets artifact authors choose destinations — the weakest SSRF posture.
2. **`openai` SDK pointed only at a managed endpoint.** Removes author-set destinations but keeps
   the SDK's dependency tree and behavioral coupling.
3. **Stdlib OpenAI-compatible adapter over the Sprint 9 SSRF-safe transport + a platform-managed
   profile catalog.** Full control of egress policy at one choke point, minimal dependencies.

Chosen: **Option 3.**

## Decision

1. **Platform-managed profile catalog.** Chat egress is configured by an immutable, revisioned
   **`ModelProfile`** and embedding egress by an immutable, revisioned **`EmbeddingProfile`**, both
   administered only by platform admins. **Artifacts and the runtime reference a profile by ID
   only.** A tenant, artifact, prompt, or request may **not** set `base_url`, host/port, scheme,
   credential/secret selection, or TLS-verification behavior. Any change to provider, endpoint,
   model, revision, dimensions, normalization, or metric produces a **new profile revision** (and,
   for embeddings, a new staged reindex). The allowlist is therefore a *managed profile catalog*,
   not merely a string host check.

2. **Stdlib adapter, no SDK now.** An `OpenAICompatibleModelProvider` and
   `OpenAICompatibleEmbeddingClient` speak the OpenAI-compatible HTTP protocol over the shared
   Sprint 9 SSRF-safe transport. **No `openai` dependency is added.** The transport enforces, at
   one point: post-DNS **resolved-IP validation/pinning** (anti-rebinding), redirect denial,
   private/link-local/metadata range blocking, **TLS certificate verification**, connect/read
   timeouts, response-size caps, and log/audit redaction.

3. **Egress idempotency is not assumed.** A chat or embedding call that fails *after the request is
   sent* (e.g. read timeout) is **not** safely retryable — a retry risks double cost and a
   divergent answer. Retries are limited to safe pre-connection failures or provider behaviors
   explicitly documented as idempotent. Callers treat a post-send failure as `outcome_unknown`
   (mirroring the Sprint 9 tool-invocation stance), not as a retryable transient.

4. **Deferral, not a permanent ban.** This is chosen because the current API surface is narrow. If
   streaming, multimodal, realtime, structured outputs, or complex tool-calling grow the surface
   enough that maintaining our adapter costs more than it saves, the official SDK is re-evaluated
   via explicit approval + threat/supply-chain review. Record the reason as "deferred due to the
   current narrow API surface," not ideology.

## Security consequences

- Profile-ID-only references remove author/tenant-controlled destinations, closing an SSRF vector
  the allowlist alone would not. Credentials remain `secret:<name>` resolved at call time.
- A single transport choke point makes DNS/IP pinning, redirect denial, TLS verification, and
  redaction auditable and uniformly enforced for chat, embeddings, and OCR.
- No prompt or response content enters logs, metric labels, or audit (ids/counts/latency/stable
  codes only).

## Operational consequences

- The `ModelProfile`/`EmbeddingProfile` catalog is change-controlled platform configuration;
  profile revisions are the unit of model/endpoint change.
- Lighter image/SBOM and simpler air-gapped mirroring than shipping the SDK; the cost is owning a
  small adapter and tracking OpenAI-compatible provider variations ourselves.

## Data and privacy consequences

- Endpoints and credentials are platform-held; artifacts carry only a profile ID. Prompts/
  responses follow data minimization and redaction.

## Positive consequences

- Strong, centralized egress control; small dependency surface; clean seam
  (`RUNTIME_MODEL_PROVIDER` / the embedding client) to swap providers or, later, the SDK.

## Negative consequences

- We maintain the adapter and chase provider-compatibility quirks; rich features (streaming,
  multimodal) would be more work than an SDK — the trigger to revisit (decision 4).

## Migration impact

- The `model_profile` artifact stops inlining `endpoint`/`api_key` and instead references a
  platform-catalog `ModelProfile` id; the `gitops/mcm` example is updated when this lands. A new
  `EmbeddingProfile` catalog is introduced (Phase 2 WS1). Additive; no consumer-contract change.

## Rollback considerations

- Providers are behind the `RUNTIME_MODEL_PROVIDER` / embedding-client seam and the deterministic
  profile remains the always-available fallback, so a faulty provider is disabled by configuration
  without data loss. Adopting the SDK later is a new ADR that supersedes decision 2 only.

## References

- [Phase 2 plan](../planning/phase-2-plan.md) — Workstream 5 (live model runtime) and Workstream 1.
- [Document plane plan](../planning/components/document-plane-plan.md) — `EmbeddingProfile`, egress.
- [WS1+WS5 sequence](../planning/components/runtime-and-document-plane-sequence.md).
- Reuses the Sprint 9 SSRF-safe egress (`apps/tools/egress`).
