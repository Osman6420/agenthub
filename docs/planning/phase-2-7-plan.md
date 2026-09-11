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

## Part 2 — External MCP tool transport: Streamable HTTP / SSE (IMPLEMENTED + VERIFIED)

Full plan + evidence: [`docs/tasks/phase-2-7-part-2-mcp-streamable-transport/`](../tasks/phase-2-7-part-2-mcp-streamable-transport/plan.md).
Delivered via **Option A** (hand-rolled SSE reader + author-pinned session handshake on the existing
SSRF-safe stdlib transport): the `tools/call` response is parsed from `application/json` **or**
`text/event-stream`; `destination.session: true` triggers `initialize` → `Mcp-Session-Id` →
`notifications/initialized` → `tools/call`. No new dependency, no egress-policy change, no migration;
`pytest` 947 passed / 37 skipped, plus a live socket-level SSE+session end-to-end check. The `mcp`
SDK (Option C) remains the documented fallback if the broad protocol surface is ever needed.

**Current gap.** `McpToolAdapter` is **HTTPS-only, single-shot JSON-RPC** (one `POST` of
`tools/call`, single `application/json` body). It does not support the **Streamable HTTP / SSE**
responses, the **session lifecycle** (`initialize` → `Mcp-Session-Id` → `notifications/initialized`),
the legacy HTTP+SSE transport, or stdio — so most off-the-shelf MCP servers can't be attached as a
tool without a plain-JSON shim.

**Hard constraint.** The SSRF-safe egress (pinned resolved-IP + TLS SNI + no redirects + bounded
size/timeout + public-IP-only, defeating DNS rebinding) must be preserved by whatever transport we
adopt. This decides the library question.

**Ready-made library decision (owner asked to prefer one if practical).** Evaluated the official
`mcp` Python SDK. Its default transport (httpx/anyio) opens its own connections and would **bypass
our pinned-IP egress** → rejected. Using the SDK only for protocol + a custom SSRF-safe httpx
transport is a viable *later* alternative but adds new production deps (approval + supply-chain
review) and an async→sync bridge, gated on a spike proving the transport can pin to the validated
IP. **Recommendation: hand-roll a bounded SSE reader + minimal session handshake on the existing
stdlib SSRF-safe transport** — for this narrow scope it is both more secure (egress unchanged, zero
new dependency) and small. Full trade-off table and design in the task plan.

**Scope (design first; no implementation until change-boundary approval):** SSE-aware bounded
reader beside `perform_bounded_https_request`; optional author-pinned session handshake; HTTPS +
public-IP enforcement, tool contract, field allowlist, risk/approval, and audit all unchanged; no
stdio; offline SSE/handshake tests (injected connection factory) + one deployment-gated live smoke.
