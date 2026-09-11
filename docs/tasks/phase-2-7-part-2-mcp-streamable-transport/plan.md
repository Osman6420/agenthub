# Phase 2.7 Part 2 — External MCP tool transport: Streamable HTTP / SSE

Status: **Implemented + Verified** via Option A (see [`verification.md`](verification.md)). No new
dependency, no egress-policy change, no migration. Parent:
[`docs/planning/phase-2-7-plan.md`](../../planning/phase-2-7-plan.md).

## 1. Problem & current gap

AgentHub can call an external server *as a governed tool* only through `McpToolAdapter`
(`apps/tools/mcp_adapter.py`), which today is **HTTPS-only, single-shot JSON-RPC**: one `POST` of
`tools/call`, expecting a single `application/json` body, read once under a byte cap
(`apps/tools/http_adapter.perform_bounded_https_request` → `response.read(max+1)`).

It does **not** support the standard MCP transports a real off-the-shelf server uses:

- **Streamable HTTP** where the server answers a `POST` with `text/event-stream` (SSE) instead of
  a single JSON body — the common default (e.g. the reference `server-everything`);
- the MCP **session lifecycle**: `initialize` handshake, the `Mcp-Session-Id` response header
  echoed on subsequent requests, and the `notifications/initialized` follow-up;
- the legacy **HTTP+SSE** two-endpoint transport;
- **stdio** transport (out of scope — network-only by design).

Consequence: most public/reference MCP servers cannot be attached as an AgentHub tool without a
plain-JSON shim.

## 2. The hard invariant that constrains every option

Outbound tool egress is the security boundary. `apps/tools/egress.validate_destination` +
`perform_bounded_https_request` guarantee, per the v3 threat model:

- **HTTPS only**, **public-unicast IP only** (loopback/private/link-local/metadata denied);
- connection is made to the **pre-resolved, validated IP** with TLS **SNI/cert hostname** = the
  original host — this is the DNS-rebinding defense;
- **no redirects**, **bounded response size**, **bounded connect/read timeout**;
- a post-send timeout becomes `OUTCOME_UNKNOWN`, never a false success;
- credentials resolve only via `secret:<name>` and are never logged.

**Any transport we adopt must keep all of the above.** This is the deciding factor in the library
evaluation below, and it is non-negotiable (AGENTS.md priority 1).

## 3. Goals / non-goals

**Goals:** attach a standards-compliant Streamable-HTTP MCP server as a governed tool; parse an
SSE response for a single `tools/call`; perform the minimal session handshake when the server
requires it — all behind the existing pinned-IP, SSRF-safe, TLS-verified, bounded egress, with the
tool contract / field allowlist / risk-approval / audit unchanged.

**Non-goals:** stdio transport; server-initiated streaming/notifications beyond the one result;
resumability/`Last-Event-ID`; elicitation/sampling; changing the SSRF policy (loopback stays
denied — local servers are reached only in tests via an injected connection factory).

## 4. Ready-made library evaluation (per owner request)

The official **`mcp` Python SDK** (`modelcontextprotocol/python-sdk`) provides a maintained
`streamablehttp_client` (session lifecycle, SSE parsing, JSON-RPC types). Assessed against the
invariant in §2:

| Option | Protocol correctness | Keeps SSRF-safe pinned-IP egress? | New prod deps | Sync/async fit | Verdict |
| --- | --- | --- | --- | --- | --- |
| **A. Hand-roll** bounded SSE reader + minimal session on the existing stdlib transport | We implement the small surface we need | **Yes — unchanged** (`connection_factory` stays) | **None** | Sync (matches the Celery proxy) | **Recommended default** |
| **B. `mcp` SDK, its own transport** | Full, maintained | **No** — httpx/anyio open their own connections, bypassing our IP-pinning + bounds | `mcp` + tree | Async→sync bridge needed | **Rejected** (breaks the security boundary) |
| **C. `mcp` SDK for protocol + custom SSRF httpx transport** | Full, maintained | Only if a custom httpx transport re-implements IP-pinning + SNI + bounds (spike) | `mcp` + tree | Async→sync bridge (`asyncio.run` per call) | **Alternative, later** |

Notes grounding the table:
- `httpx`/`anyio` are already in `requirements.lock` **transitively** and unused by app code; the
  SDK itself, plus `httpx-sse`/`pydantic-settings`/etc., would be **new direct** production
  dependencies → explicit approval + provenance/licence/maintenance review + lockfile update
  (AGENTS.md change boundary).
- The SDK is **async** (anyio); the tool proxy/adapters are **synchronous** (Celery worker). Option
  C needs an event loop per call and careful cancellation/timeout mapping to `OUTCOME_UNKNOWN`.
- Option B's transport does its own DNS + connection management, so it would **not** traverse
  `validate_destination`'s resolved-IP pinning — the exact DNS-rebinding defense we must keep. This
  is why B is rejected regardless of convenience.

### Recommendation

**Do Option A now.** For the narrow need (one `tools/call` over SSE + an optional session
handshake) hand-rolling is both *more secure* (the pinned-IP egress is preserved verbatim, zero new
dependency, no async bridge) and *not much code* — SSE framing for a single response is small and
fully bounded. This is the "practical and sensible" choice for the current scope.

**Revisit Option C** only if we later need the broad protocol surface (resumability, server
notifications, elicitation/sampling, concurrent streams). At that point the SDK's maintained
protocol layer earns its dependency cost — **gated on a spike proving a custom httpx transport can
pin to the validated IP with correct SNI/cert-hostname and enforce our size/timeout/no-redirect
bounds.** If that spike fails, stay on Option A.

## 5. Design sketch (Option A)

1. **Transport:** add a bounded, incremental reader beside `perform_bounded_https_request` that,
   when the response `Content-Type` is `text/event-stream`, reads events under the same byte cap
   and read deadline, parses `event:`/`data:` frames, and returns the first JSON-RPC message whose
   `id` matches the request. Enforce a max-events / max-bytes ceiling; a stream that exceeds it is
   `RESPONSE_TOO_LARGE`. `application/json` responses keep the current single-read path. Everything
   still flows through the injected `connection_factory` (IP-pinned, TLS-verified).
2. **Adapter:** `McpToolAdapter` branches on `Content-Type`; SSE path reuses the JSON-RPC result
   extraction (`result.structuredContent` → `result`), same error mapping (`MCP_ERROR`,
   `MCP_TOOL_ERROR`, `MCP_RESULT_INVALID`).
3. **Session (optional, config-pinned):** when the tool definition marks the destination as
   session-required, do `initialize` → capture `Mcp-Session-Id` → send `notifications/initialized`
   → `tools/call` with the header → best-effort close. Stateless per invocation; no session state
   persisted. Kept behind the same pinned destination.
4. **Egress policy unchanged:** HTTPS + public-IP only; loopback/private still denied. Local/CI
   tests exercise the SSE reader and handshake via an **injected connection factory** (offline, no
   socket), exactly as the current adapter tests do.

## 6. Test plan

Offline (no live egress in CI), via injected connection factory:
- SSE happy path: single `message` event carries the `tools/call` result → parsed structured
  content.
- SSE with interleaved notification events before the result → result still extracted; unrelated
  events ignored.
- Oversized / never-terminating stream → `RESPONSE_TOO_LARGE` at the byte/event ceiling.
- Post-send read timeout → `OUTCOME_UNKNOWN` (never a false success).
- Session handshake: `initialize` → `Mcp-Session-Id` echoed on `tools/call`; missing/!2xx
  handshake fails closed.
- Content-negotiation: `application/json` still takes the single-read path unchanged.
- Egress denial unchanged: loopback/private destination rejected before any socket.

## 7. Change-boundary gates (must clear before/if implementing)

- Option A: no new dependency, no egress-policy change, no API change → normal review + the §6
  tests + a live smoke against one real Streamable-HTTP server (deployment-gated, not CI).
- Option C (if ever chosen): explicit dependency approval for `mcp` + tree, supply-chain/licence/
  maintenance review, lockfile update + `pip check`, and the pinned-IP httpx-transport spike signed
  off by security before adoption.

## 8. Open questions

- SSE stream bound: cap by total bytes, event count, and a wall-clock read deadline together — pick
  defaults consistent with the existing `max_response_bytes` / `timeout_seconds`.
- Do we advertise session support per tool definition (a `destination.session: true` flag) or
  auto-detect from a `400/"session required"` response? Prefer explicit, author-pinned.
- Whether to fold the SSE reader into the existing OCR async-polling bounded seam or keep a
  dedicated MCP reader (leaning dedicated, to keep OCR untouched).

## 2026-07-22 review correction

For `destination.session: true`, require a non-empty bounded visible-ASCII `Mcp-Session-Id` from
the initialize response. Missing or unsafe upstream values fail closed before notification or tool
execution, preventing a configured session-required destination from silently downgrading to the
single-shot path or reflecting unsafe header data.
