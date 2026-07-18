# AgentHub — Phase 2.7 Plan (IN PROGRESS)

> **Status: IN PROGRESS.** Phase 2.7 hardens the *live* runtime paths that Phase 2's
> foundational live-model work (see [`phase-2-plan.md`](phase-2-plan.md)) exposed once a real
> provider (Gemini via the platform `ModelProfile` catalog) is actually configured and called.
> Every new production dependency and every new external egress remains a change-boundary item
> requiring explicit approval + a supply-chain/threat-model review first (see
> [`AGENTS.md`](../../AGENTS.md)).

## Purpose

Phase 2 wired the governed generation/retrieval seams to real providers but the default
deterministic stubs masked several real-provider defects. Phase 2.7 fixes those defects, proves
the live Gemini path end-to-end (RAG + agent), and plans the missing external **MCP tool
transport** modes.

## Part 1 — Live-provider runtime hardening (IMPLEMENTED + VERIFIED)

Task record: [`docs/tasks/phase-2-7-part-1-live-provider-hardening/`](../tasks/phase-2-7-part-1-live-provider-hardening/plan.md).

Three correctness fixes, all covered by regression tests; no new dependency, no migration, no
API/authorization/egress change:

1. **System-prompt-only request rejected by Gemini.** `OpenAICompatibleModelProvider.generate`
   sent a `system`-only message when there was no retrieval context; Gemini's OpenAI-compat
   layer rejects that with HTTP 400 `contents is not specified`. The prompt is now the `user`
   turn when there is no context (system + user when context is present). This is the
   "user-prompt-less system prompt" fix.
2. **Agent model-generation failure left the run stuck `running`.** A `ModelProviderError`
   raised inside the agent loop's respond step escaped the task's `AgentRuntimeError` handler,
   so the durable `AgentRun` never left `running`. It is now translated to the terminal, stable
   `AGENT_MODEL_FAILED` code so the task marks the run `failed` (fail-closed, audited).
3. **Agent scenarios reach real Gemini.** A real (non-stub) model provider requires the release
   to pin a `model_profile`; the demo agent release did not, so it failed
   `MODEL_PROFILE_INVALID`. The demo `assistant` agent now pins the Gemini `model_profile` and an
   authored `system_prompt`, and completes on live Gemini. (This is demo wiring, not a code
   change; it documents the required release shape for real-model agents.)

### Known limitation recorded (not a Part 1 change)

Async agent runs read their objective from the **redacted** durable start snapshot
(`apps/agents/services._redact` blanks every string), so with a real model the raw user query
reaches the model as `[redacted]`. Authored `system_prompt` + retrieval grounding are the
intended signal; letting the runtime use the unredacted input while keeping durable/audit copies
redacted is a **data-protection-sensitive** change that needs its own design + approval. Tracked
for a later part.

## Part 2 — External MCP tool transport: Streamable HTTP / SSE (PLANNED)

**Motivation / current gap.** AgentHub can call an external server as a governed tool only over
the `McpToolAdapter`, which today is **HTTPS-only, single-shot JSON-RPC**: one `POST` of
`tools/call`, expecting a single `application/json` body (`apps/tools/mcp_adapter.py` +
`apps/tools/http_adapter.perform_https_post`). It does **not** support:

- the **MCP Streamable HTTP** transport when the server answers with `text/event-stream` (SSE),
- the MCP **session lifecycle** (`initialize` handshake, `Mcp-Session-Id` header,
  `notifications/initialized`),
- the legacy **HTTP+SSE** two-endpoint transport, or
- **stdio** transport (network-only by design).

Egress also remains **public-unicast HTTPS only** (`apps/tools/egress.validate_destination`), so
loopback/private MCP servers are denied — a deliberate SSRF control that Part 2 keeps.

**Planned scope (design first; no implementation until approved):**

1. Add an SSE-aware response reader to the bounded transport: parse `text/event-stream`, enforce
   the same byte cap / timeout / redirect controls, and extract the single JSON-RPC result for a
   `tools/call`. Reject unbounded/streaming tool results.
2. Add optional MCP session handling (initialize → `Mcp-Session-Id` → call → close) behind the
   same pinned-destination, TLS-verified, SSRF-safe egress.
3. Keep HTTPS + public-IP enforcement; keep the tool contract, field allowlist, risk/approval,
   and audit unchanged. No stdio. No new production dependency without approval + review.
4. Tests: SSE framing, session handshake, oversized/streaming rejection, timeout→outcome-unknown,
   and offline-only (no live egress in CI).

**Open questions:** whether to reuse the existing `perform_bounded_https_request` seam or add a
streaming-aware sibling; how to bound an SSE stream deterministically; whether session state
belongs in the adapter (stateless per call preferred).
