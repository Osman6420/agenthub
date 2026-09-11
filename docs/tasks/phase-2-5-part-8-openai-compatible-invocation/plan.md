# Task Plan: phase-2-5-part-8-openai-compatible-invocation

## Task summary

Add governed OpenAI-compatible HTTPS invocation adapters for existing scenarios while preserving
the existing MCP and `/v1/query`/`/v1/invoke` paths. A scenario is presented through the protocol
of an authenticated, scenario-bound consumer: `mcp` uses the existing MCP ingress and `rest` uses
HTTPS. New HTTPS usage defaults to `POST /v1/chat/completions`; `POST /v1/responses` is the explicit
alternative for asynchronous workflow/agent scenarios. The release's `output_contract` role stays
optional and selectable; when present, its exact immutable version remains the runtime validation
authority.

## Background

The gateway already authenticates hashed bearer credentials, authorizes an organization-scoped
consumer binding and capability against a generated scenario alias, selects an active/canary
release, validates the input contract, issues a signed execution context, records idempotency,
audit and usage, and dispatches to the governed runtime. MCP deliberately delegates to this same
policy seam. Part 8 must add transport adapters, not a second invocation or authorization stack.

The repository already models the presentation choice as `Consumer.protocol` (`rest` or `mcp`).
No separate scenario-exposure model is planned: effective exposure is the intersection of an active
consumer, matching protocol, active scenario binding, required capability, active/canary release
and enabled ingress. Separate consumers may expose the same scenario over MCP and HTTPS.

Part 8 implements a small, versioned compatibility subset rather than claiming full OpenAI API
equivalence. Planning references:

- [OpenAI API quickstart and streaming overview](https://platform.openai.com/docs/quickstart/make-your-first-api-request)
- [OpenAI API backward-compatibility and request-ID guidance](https://platform.openai.com/docs/api-reference/backward-compatibility)
- [OpenAI Responses streaming event reference](https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal/delta)

## Scope

- Add `POST /v1/chat/completions` as the default HTTPS compatibility adapter for synchronous RAG
  scenarios.
- Add `POST /v1/responses` for synchronous RAG and bounded background workflow/agent invocation.
- Interpret required `model` only as the authenticated consumer's bound generated `scenario_alias`;
  never accept raw project/scenario/release IDs or provider model IDs as authority.
- Reuse gateway binding, capability, canary routing, input/output-contract, execution-context,
  rate-limit, idempotency, audit and usage seams.
- Enforce `Consumer.protocol`: compatibility HTTPS routes require `rest`; MCP requires `mcp`.
- Convert bounded OpenAI-shaped requests to canonical gateway input and canonical runtime results to
  bounded compatible envelopes in a dedicated adapter/service layer.
- Keep client-supplied conversation history request-scoped and content-free in telemetry.
- Show protocol, scenario alias, supported adapter and safe copyable guidance in the console.
- Document the exact supported/unsupported field matrix and compatibility-version policy.

## Non-goals

- Full OpenAI API parity, provider model hosting/discovery or `/v1/models`.
- Persistent conversations, threads, previous-response lookup, transcript retention or memory.
- Images, audio, files, remote URLs, base64 attachments, multimodal content or uploads.
- Client-defined tools/functions/MCP, tool choice or client-supplied executable schemas. Scenario-
  pinned tools remain controlled by the immutable release.
- Chat Completions for async workflow/agent runs; those use Responses background mode.
- Token-by-token streaming. `stream: true` is rejected until a real bounded runtime streaming seam
  exists; a fabricated one-chunk stream is not compatible.
- Batch, embeddings, moderation, assistants, conversations, files, realtime or other OpenAI APIs.
- New production dependencies, outbound calls, DSL changes or request overrides of release pins.

## Acceptance criteria

1. A valid `rest` consumer with a bound RAG scenario and `query` capability can call
   `/v1/chat/completions` with `model=<generated scenario alias>` and bounded text messages and gets
   a valid `chat.completion` envelope.
2. The same RAG scenario works through `/v1/responses`; workflow/agent scenarios can be queued only
   through Responses background mode with their existing capability and idempotency rules.
3. Alias resolution is organization-, consumer- and binding-scoped. Raw IDs, foreign aliases,
   disabled consumers/bindings/scenarios and missing capabilities fail closed without target leaks.
4. MCP and HTTPS reuse identical release/canary/runtime governance, but a credential cannot cross
   its configured protocol.
5. Text-only history allows at most 64 messages, roles `developer`, `system`, `user`, `assistant`,
   32,000 characters per message and 100,000 total. At least one user message is required. Unknown,
   nested, non-text, tool, file and over-bound content is rejected before dispatch.
6. Chat accepts only `model`, `messages`, optional `stream: false` and bounded optional `user`.
   Responses accepts only `model`, `input`, optional `background`, optional `stream: false` and
   bounded optional `user`. Unknown fields are rejected, not silently ignored.
7. `response_format`, `tools`, `tool_choice`, `functions`, `store`, `previous_response_id`, provider
   sampling/token controls and arbitrary metadata are unsupported and cannot override governance.
8. The mapper uses the latest user text as `query` and includes normalized `messages` only if the
   pinned input contract permits it. Contract errors return safe pointer-only diagnostics.
9. A pinned `output_contract` is enforced before adaptation. Without one, no business schema is
   inferred. An `answer` string maps to text; other valid JSON output becomes deterministic canonical
   JSON text. Output is not duplicated into telemetry or unbounded extensions.
10. Chat success includes opaque `chatcmpl-...` id, `object=chat.completion`, creation time, requested
    alias as `model`, one assistant choice, finish reason and bounded usage. Responses use opaque
    `resp_...` IDs and stable statuses without internal numeric IDs.
11. Errors use compatible `error.message`, `error.type`, `error.param`, `error.code` while preserving
    AgentHub's safe stable code. Auth, authorization, throttle, validation, idempotency, release and
    runtime failures have fixtures and correct HTTP status/`Retry-After` behavior.
12. `Idempotency-Key` is optional for synchronous RAG and required for background workflow/agent
    creation. Hashing covers adapter, normalized body and alias; exact replay retains opaque IDs and
    differing reuse conflicts.
13. Request/trace IDs propagate and a trusted request-ID response header is returned. Audit/usage
    distinguish adapters using bounded values and never record messages, output, token or `user`.
14. Existing `/v1/query`, `/v1/invoke`, `/v1/runs/*` and MCP contracts retain regression coverage.
    Protocol enforcement is an intentional tightening audited before rollout.
15. Console pages show protocol and supported routes. Output contract remains the existing optional
    immutable release role; no second mutable exposure copy is created.

## Affected components

- `apps/gateway`: routes, schema/adapters, protocol enforcement, compatible errors and tests.
- `apps/mcp`: protocol enforcement and shared-policy regression.
- `apps/identity`: existing consumer protocol semantics; no new authority model.
- `apps/releases` and runtimes: reuse of active/canary routing and optional output-contract pin.
- `apps/console`: scenario/consumer invocation guidance.
- `apps/observability` / `apps/audit`: bounded operation names and correlation.
- Settings and architecture/API/manual-testing documentation.

## Interfaces affected

- Add `POST /v1/chat/completions` and `POST /v1/responses`.
- Tighten ingress: `/mcp/` accepts `mcp` consumers; public HTTPS gateway accepts `rest` consumers.
- Remove or rename no existing request/response field.
- Snapshot the supported subset. Any new authority-bearing input requires public-contract review.

## Data impact

Messages/output are transient at adapter ingress and use existing runtime redaction. No transcript
table or raw payload is added to idempotency, audit, usage, logs or metrics. Existing workflow/agent
redacted persistence remains authoritative. Client `user` is untrusted content, not authority, and
is not persisted or emitted to telemetry.

## Security impact

The new public JSON surface risks enumeration, cross-tenant access, protocol confusion, oversized
history, prompt injection, governance override, idempotency abuse, transcript leaks and false parity.
Explicit bounds/schemas, existing authorization, release-only authority and negative tests mitigate
them. See `threat-model.md`.

## Authorization impact

The owner's 2026-07-16 instruction approves this additive public API/authentication change. No new
capability is added: synchronous calls require `query`; background workflow requires `workflow_run`;
background agent requires `agent_invoke`. Authorization is server-side before release lookup. The
OpenAI `model`, `user`, roles and metadata never grant authority.

## Observability impact

- Add bounded Chat/Responses operation values to existing request/error/latency/usage telemetry.
- Reuse request/trace middleware and return its trusted request ID.
- Audit success/denial with safe actor, tenant, target, adapter, outcome and reason only.
- Keep alias/consumer IDs out of metric labels and preserve `Retry-After`.

## Migration impact

No database migration is planned. Reuse `Consumer.protocol`, bindings, aliases, release roles and
idempotency storage. Inventory seeded/GitOps/documented clients for cross-protocol use before
implementation; issue correctly typed credentials rather than weakening enforcement.

## Dependencies

No new production dependency. Reuse DRF, `jsonschema`, bearer auth, throttle, idempotency, audit,
usage and runtimes. Official SDKs may be optional dev smoke clients only if already available.

## Implementation steps

1. Capture gateway/MCP/console baselines and inventory protocol usage in code, fixtures and GitOps.
2. Add bounded request dataclasses/schema validators and deterministic normalizers with boundary
   tests before runtime connection.
3. Extract a transport-neutral authorized invocation service from the current private view seam so
   REST, MCP and adapters share policy without view-to-private-view calls.
4. Enforce protocol at ingress with auth/cross-protocol/cross-tenant denial coverage.
5. Implement Chat adaptation for synchronous RAG, stable idempotent IDs and output-contract mapping.
6. Implement Responses synchronous RAG and background workflow/agent adaptation using existing
   durable runs; never poll Celery while holding an HTTP worker.
7. Add bounded observability, request-ID headers and redaction tests.
8. Add Turkish console guidance with protocol, alias, supported route, output-contract pin and safe
   examples containing no real token.
9. Update architecture, compatibility and manual-test docs; add SDK/curl contract fixtures.
10. Run focused/full SQLite/PostgreSQL tests and all quality gates without pytest `-q` or timeout;
    run synthetic live Chat/Responses/MCP smoke.
11. Perform staff/AppSec/SRE final-diff review and record evidence before commit.

## Test plan

- Schema: minimal requests, roles, text forms, missing/unknown fields, all size boundaries, nesting,
  controls, multimodal/tool/override attempts and deterministic mapping.
- Auth: missing/revoked token, disabled/protocol-mismatched consumer, missing binding/capability,
  foreign/closed alias, cross-tenant same alias, inactive scenario and unavailable release.
- Runtime: active/canary parity, optional/present/violated contracts, RAG/provider failures,
  background workflow/agent and unsupported Chat scenario type.
- Idempotency/concurrency: replay, body/adapter conflict, missing/bounded key, concurrent duplicate and
  stable replayed IDs.
- Errors/privacy: compatible snapshots, HTTP/`Retry-After`, safe messages, and absence of token,
  messages, output and `user` from telemetry/idempotency.
- Compatibility: representative current OpenAI Python/JavaScript clients when available plus curl;
  unknown SDK fields fail explicitly.
- Regression: full affected and repository SQLite/PostgreSQL suites plus legacy contracts.
- Manual: Turkish guidance; Chat/Responses/MCP success; wrong protocol, revoked token, foreign alias,
  contract violation and throttle demonstrations.

## Rollout plan

1. Ship behind `OPENAI_COMPAT_ENABLED=false`; legacy gateway and MCP remain available.
2. Inventory/fix protocol-mismatched consumers before strict protocol enforcement; never mutate
   credentials automatically.
3. Enable non-production, run synthetic smoke and verify audit, IDs, rate limits, queue and redaction.
4. Enable per environment and monitor bounded request/error/latency rates, auth/conflict/throttle/5xx
   changes and worker pressure.
5. Advertise only the documented subset; default RAG HTTPS guidance to Chat and workflow/agent to
   Responses background mode.

## Rollback plan

Disable `OPENAI_COMPAT_ENABLED` without changing releases, aliases, credentials or runtime data.
For legacy protocol mismatch, issue a correctly typed consumer/token rather than globally permitting
confusion. Accepted background runs remain governed through existing status/cancel paths. No schema
rollback is needed.

## Risks

- SDK evolution may send new fields; strict rejection is safer but may need reviewed additions.
- Chat cannot represent async execution; eligibility and guidance must fail clearly.
- Character limits are not provider token counts; runtime caps remain final authority.
- Protocol tightening may break tolerated misuse; inventory/replacement credentials are required.
- Canonical JSON text is interoperable but clients may prefer an `answer`-shaped output contract.
- Synchronous RAG latency remains bounded by existing downstream timeouts; Chat adds no async escape.

## Open questions

- Verify whether redirected aliases are resolved or rejected by the existing binding service; keep
  compatibility routes identical to `/v1/query` unless deliberately documented.
- Reuse the established request-ID header name rather than adding a competing one.
- Verify representative SDK acceptance of the minimal Responses background envelope; adjust only
  response shape, never authorization-bearing inputs, based on fixtures.

## Status

Verified for the automated scope. Public API/authentication scope was approved on 2026-07-16.
Implementation and full SQLite/PostgreSQL verification completed on 2026-07-16. Authenticated live
synthetic smoke and Turkish owner browser review remain pending and are carried to Part 9 closure.

## Completion criteria

- Every acceptance criterion has automated evidence or explicit owner-reviewed manual evidence.
- SQLite/PostgreSQL and repository quality gates pass without weakened controls.
- Compatibility, protocol denial, cross-tenant, bounds, idempotency and redaction tests pass.
- Current-behavior and Phase 2.5/master plans reflect implemented reality.
- Staff/AppSec/SRE review finds no unresolved high-severity issue.
