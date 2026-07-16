# Verification: phase-2-5-part-8-openai-compatible-invocation

## Current status

Implemented and automated-verified on 2026-07-16. Authenticated live synthetic smoke and Turkish
owner browser review remain pending for the integrated Part 9 closure.

## Planning evidence — 2026-07-16

- Inspected the current gateway, MCP, consumer protocol/binding/capability, release compiler,
  optional output-contract and workflow/agent/RAG runtime seams.
- Confirmed MCP currently delegates to the gateway policy path and that `Consumer.protocol` already
  contains the closed `rest`/`mcp` presentation vocabulary.
- Confirmed release compilation does not require `output_contract`, while all three runtimes enforce
  it when pinned.
- Reviewed current official OpenAI HTTPS documentation for Chat/Responses shape, streaming/request
  ID and backward-compatibility planning. The OpenAI Docs MCP was unavailable in this session; its
  required install attempt failed with Windows `codex.exe: Access is denied`, so official-domain
  web documentation was used as the documented fallback.
- `git diff --check` passed for the planning change.

## Implemented behavior

- Added feature-gated `/v1/chat/completions` for synchronous RAG and `/v1/responses` for synchronous
  RAG plus background workflow/agent creation. Local/test settings enable the adapters; base/
  production configuration is disabled by default.
- `model` resolves only through the authenticated consumer's generated scenario alias binding.
  Existing capability, active/canary release, contract, execution-context, idempotency, audit and
  usage boundaries remain authoritative.
- Added strict text-only request schemas and message/character/body bounds. Streaming, multimodal
  content, client tools/functions and request-side governance overrides fail explicitly.
- Enforced consumer protocol in both directions. REST credentials use HTTPS; MCP credentials use
  MCP. Protocol denials are audited without request content.
- Preserved optional release-pinned output-contract behavior and deterministic bounded response/
  compatible error envelopes.
- Added Turkish scenario/consumer invocation guidance and separate REST/MCP demo credentials.

## Automated evidence — 2026-07-16

- Focused gateway/MCP after fixture split: `46 passed`.
- Focused OpenAI adapter after body-size ordering fix: `15 passed`; after workflow background
  coverage: `16 passed`.
- Broad gateway/MCP/console/workflow/agent run before the body-size fix: `262 passed, 1 failed`; the
  failure proved the adapter read `request.data` before checking Content-Length. The order was fixed
  and the focused regression passed.
- Full SQLite container profile: `711 passed, 29 skipped` (`740 collected`). Skips are the documented
  PostgreSQL/RLS/pgvector cases.
- Full PostgreSQL/Redis container profile: `735 passed, 5 skipped` (`740 collected`). Skips are the
  intentional off-PostgreSQL guard assertions.
- Mypy: `Success: no issues found in 360 source files`.
- Django system check: `0` issues.
- Migration drift: `No changes detected`.
- Compileall: successful for `apps` and `config`.
- Ruff lint: all changed and repository Python files passed.
- `git diff --check`: passed.

Tests ran without pytest `-q` and without a pytest timeout. The host `.venv` Python launcher failed
before Python startup with the documented Windows `A specified logon session does not exist` error,
so the manual-testing-guide Python 3.13 isolated-container fallback was used. Compose PostgreSQL,
Redis and MinIO were healthy before the PostgreSQL profile.

## Formatter exception

Repository-wide `ruff format --check apps` reports only pre-existing wrapping in
`apps/builder/node_schema.py`, which is outside Part 8 and unchanged in this worktree. All Part 8
Python files are formatted. The unrelated file was not modified or staged.

## Staff engineer / AppSec / SRE review

- Staff: adapters stay thin and reuse the canonical gateway/release/runtime seams; no alternate
  authority, schema or runtime was introduced. Legacy endpoint fields remain intact.
- AppSec: alias-only routing, protocol enforcement, explicit schemas/bounds, capability denial,
  output-contract authority, content-free telemetry and cross-protocol tests are present. No secret,
  raw message or client `user` is returned or logged by the adapter.
- SRE: adapters are base-disabled, locally testable, rate-limited through the existing throttle,
  correlated by request ID, and removable by one feature flag. Background operations reuse durable
  queues instead of holding HTTP workers.

## Verification still required

- Authenticated live-server curl/OpenAI-SDK smoke after restarting the local web/worker with the new
  code and freshly seeded separate REST/MCP credentials.
- Turkish owner browser review of scenario/consumer invocation guidance.
- Exact third-party OpenAI SDK version matrix beyond the documented minimal HTTP contract.
