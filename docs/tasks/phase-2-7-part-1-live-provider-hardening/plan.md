# Phase 2.7 Part 1 — Live-provider runtime hardening

Status: **Verified** (see [`verification.md`](verification.md)).

## Problem

With the deterministic stub providers (CI default) the real-provider generation paths were never
exercised. Configuring a real provider (Gemini via the platform `ModelProfile` catalog, called
through the ADR-0005 SSRF-safe egress) surfaced three defects.

## Changes (code)

1. `apps/orchestration/providers.py` — `OpenAICompatibleModelProvider.generate` now always sends a
   `user` turn. Without retrieval context the prompt is the `user` message; with context the prompt
   stays the `system` instruction and the untrusted data is the `user` turn. Fixes Gemini HTTP 400
   `contents is not specified` on system-only requests.
2. `apps/agents/runtime.py` — the respond step's `ModelProviderError` is translated to the terminal
   `AgentRuntimeError("AGENT_MODEL_FAILED")` so the Celery task marks the `AgentRun` `failed`
   (fail-closed) instead of leaving it stuck `running`.

## Tests added

- `apps/orchestration/tests/test_live_model_provider.py::test_openai_provider_sends_user_turn_when_context_is_empty`
- `apps/agents/tests/test_runtime.py::test_model_provider_failure_marks_run_failed`

## Non-code (demo wiring, documents the required release shape)

- The demo `assistant` agent release pins the Gemini `model_profile` and an authored
  `system_prompt`; it completes on live Gemini. A real (non-stub) model provider requires a pinned
  `model_profile` in the release, else `MODEL_PROFILE_INVALID`.

## Out of scope / follow-ups

- Async agent runs read the objective from the **redacted** durable snapshot, so the raw query
  reaches a real model as `[redacted]`. Un-redacting runtime input while keeping durable/audit
  copies redacted is data-protection-sensitive and needs its own approved design.
- External MCP tool transport (Streamable HTTP / SSE) — Phase 2.7 Part 2 (planned).

## Scope guardrails

No new dependency, no migration, no change to authorization, public API, egress policy, or audit
schema. Additive behavior + tests only.

## 2026-07-22 review correction

Preserve the authored prompt as a `system` message even when retrieval context is empty. To satisfy
OpenAI-compatible backends that reject system-only requests, append a fixed, content-free user turn
instead of lowering the system prompt to user priority. This retains the provider compatibility fix
without changing the prompt trust boundary.
