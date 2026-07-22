# Phase 2.7 Part 2 — Verification

Implemented via **Option A** (hand-rolled, on the existing SSRF-safe stdlib transport). No new
dependency, no egress-policy change, no migration.

## What changed

- `apps/tools/egress.py` — `ValidatedDestination` gains `session_required: bool = False`;
  `validate_destination` reads `destination.session`.
- `apps/tools/tool_schema.py` — `destination.session` is an optional boolean (author-pinned).
- `apps/tools/http_adapter.py` — `BoundedHttpResponse` gains `session_id` (captured from the
  `Mcp-Session-Id` response header); single bounded read unchanged.
- `apps/tools/proxy.py` — the no-egress passthrough carries `session_required`.
- `apps/tools/mcp_adapter.py` — the `tools/call` response is parsed from either
  `application/json` **or** `text/event-stream` (SSE); when `destination.session` is pinned the
  adapter runs `initialize` → capture `Mcp-Session-Id` → `notifications/initialized` →
  `tools/call` with the session header. Pinned-IP / TLS / bounded / no-redirect egress unchanged;
  HTTPS + public-IP still enforced (loopback/private denied).

## Automated gates (all pass)

| Gate | Result |
| --- | --- |
| `ruff format --check apps` | 400 files formatted |
| `ruff check apps` | All checks passed |
| `mypy apps` | no issues in 400 source files |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `pytest` (config.settings.test) | **947 passed, 37 skipped** (was 942; +5 new) |

New tests (`apps/tools/tests/`):
- `test_mcp_adapter.py`: SSE response parsed; SSE notification events before the result ignored;
  SSE with no result event → `MCP_RESULT_INVALID`; session handshake sends
  `initialize` → `notifications/initialized` (with `Mcp-Session-Id`) → `tools/call` (with
  `Mcp-Session-Id`). All existing single-shot JSON tests still pass unchanged.
- `test_tool_artifacts.py`: `destination.session` optional boolean accepted; non-boolean rejected.

## Live end-to-end evidence

Drove the **real `McpToolAdapter`** against a live in-process MCP server over a real socket
(plain-HTTP injected connection factory; production keeps the TLS-pinned public-IP factory). The
server required a session and answered `tools/call` with `text/event-stream`. Observed wire
sequence and parsed result:

```
initialize                 session=-
notifications/initialized  session=live-sess-abc
tools/call                 session=live-sess-abc     (response: text/event-stream)
adapter result body: {'query': 'refund policy', 'hits': 2}
LIVE SSE + SESSION HANDSHAKE OK
```

## Residual risk / not done

- **stdio** transport not supported (out of scope, network-only by design).
- Server-initiated streaming beyond the single result, resumability (`Last-Event-ID`), elicitation
  and sampling are not supported (out of scope).
- The SSE body is bounded by the existing `max_response_bytes` single read; a spec-compliant server
  closes the POST stream after the response, so EOF arrives promptly. A server that holds the
  stream open relies on the read timeout as the backstop.
- No live smoke against a third-party public MCP server (deployment-gated; SSRF egress denies
  loopback, so CI/local use the injected factory). Recommended before enabling a real external MCP
  tool in production.

## 2026-07-22 review correction

- Session-required initialize responses now reject missing, whitespace/control-character, and
  oversized session identifiers with `MCP_SESSION_INVALID`.
- Parameterized regression coverage proves failure occurs after initialize and before any
  notification or `tools/call` request.
- Included in the 2026-07-22 targeted regression run: **55 passed, 2 PostgreSQL-only skipped**;
  ruff format/check, mypy, Django system check, and migration drift checks passed.
