# Threat Model: phase-2-5-part-8-openai-compatible-invocation

## Assets

- Consumer bearer credentials and authenticated identity.
- Tenant/project/scenario aliases, bindings and capabilities.
- Immutable active/canary releases and pinned contracts, prompts, profiles, data and tools.
- Client conversation content and governed scenario output.
- Runtime capacity, provider budget, queues, idempotency, audit and usage integrity.

## Actors

- Authorized REST or MCP consumers.
- Authorized organization/project/release operators.
- Unauthenticated callers, stolen-token holders, malicious tenant consumers and compromised clients.
- Existing governed model, retrieval and tool systems.

## Entry points

- New `POST /v1/chat/completions` and `POST /v1/responses`.
- Existing `/mcp/`, `/v1/query`, `/v1/invoke` and `/v1/runs/*` regression surfaces.
- Console scenario/consumer guidance.
- Celery workflow/agent execution created by Responses background requests.

## Trust boundaries

1. Untrusted HTTP crosses byte limits, authentication, throttle and explicit schema validation.
2. Authenticated consumer plus untrusted `model` crosses tenant-scoped binding/capability resolution.
3. Authorized scenario crosses active/canary release and immutable contract resolution.
4. Normalized history crosses the signed execution-context boundary into runtime.
5. Runtime output crosses optional business-contract validation and bounded envelope adaptation.
6. Safe metadata crosses into audit, usage, logs, traces and metrics; content must not.
7. Background creation crosses the database/Celery boundary using durable idempotent run state.

## Data classifications

- Bearer token/header: secret; hash only at rest and never telemetry.
- Messages, client `user`, input/output and retrieval: potentially confidential/personal.
- Alias, consumer subject and release metadata: internal identifiers, safe only when scoped.
- Request/trace IDs, adapter, status and stable error: bounded operational metadata.

## Authentication

Reuse `ConsumerTokenAuthentication`; add no OpenAI-issued-key interpretation. Reject missing,
malformed, unknown, revoked and disabled credentials before target resolution. Enforce protocol:
REST credentials cannot call MCP and MCP credentials cannot call compatibility HTTPS routes.
Errors do not echo token prefixes or lookup details.

## Authorization

Resolve `model` only as `ScenarioAlias` through the authenticated consumer's organization/subject
binding. Require `query`, `workflow_run` or `agent_invoke` according to operation/type. Select a
release only after authorization. Reject raw IDs, tools, tenant hints and contract/profile overrides.
Client `user` and message roles are content, not identity or delegation.

## Tenant isolation

Alias, binding, release, canary, contract, run, idempotency, audit and usage remain organization-
scoped. Same alias text in another tenant is indistinguishable from unavailable. Contract resolution
comes only from the selected release. Background status/cancel remains consumer/tenant scoped with
opaque identifiers.

## External systems

Part 8 adds no outbound system. Existing model, retrieval, tool, Redis, PostgreSQL and Celery
boundaries retain their controls. “OpenAI-compatible” is only the inbound envelope; AgentHub does
not forward the caller's body to OpenAI.

## Abuse cases

- Alias enumeration by response or timing differences.
- Cross-tenant/raw-ID/profile injection through `model` or metadata.
- Protocol confusion to bypass intended exposure.
- Oversized/deep history, controls or JSON bombs exhausting CPU/memory.
- Prompt injection attempting to override policy, tools, contracts, auth or tenant scope.
- Client tools/functions/MCP causing egress or privilege expansion.
- Client schema/response controls bypassing output contracts or exhausting validation.
- Idempotency collision/reuse, concurrent duplicate runs or unstable replay IDs.
- Streaming holding connections or bypassing size controls.
- Content/token leakage through errors, logs, audit, usage, traces, metrics or idempotency.
- Valid repeated requests exhausting budget, retrieval, DB or workers.
- Clients assuming unsupported retention, tools, modalities or sampling behavior.

## Failure cases

- Authentication, throttle or schema failure before lookup.
- Missing binding/capability, disabled scenario or unavailable release.
- Input contract incompatible with normalized history.
- Retrieval/model/runtime timeout or failure after acceptance.
- Missing/invalid output or optional output-contract violation.
- Audit/usage/idempotency persistence failure or race.
- Celery enqueue failure after background transaction commit.
- Client disconnect or envelope adaptation failure.
- Rollout discovers legacy cross-protocol credentials.

## Logging and audit risks

Framework logs or exceptions could capture bodies/headers; validation could echo content; metric
labels could gain aliases/users; audit could duplicate output. Use content-free stable events,
pointer-only diagnostics, safe scoped references, bounded dimensions and explicit redaction tests.
The adapter must not suppress existing gateway audit-failure behavior.

## Mitigations

- Pre-parse byte limit plus depth, count and character bounds; text-only allowlists and unknown-field
  rejection.
- Hashed bearer auth, active-consumer check, per-consumer throttle and protocol/binding/capability/
  tenant authorization.
- Alias-only `model`; no raw-ID/provider fallback and uniform safe denial.
- Release as sole authority for contracts, prompts, profiles, tools and runtime.
- Signed execution context and runtime resource/time/output limits.
- Async Responses path for workflow/agent and explicit Chat denial; no worker-thread polling.
- Existing idempotency constraint plus adapter/body/alias hash and stable replay envelope.
- Optional output-contract validation before deterministic bounded adaptation.
- Reject streaming, multimodal, tools, retention and previous-response fields until designed.
- Content-free telemetry, safe errors, request/trace propagation and bounded metric labels.
- Feature flag, synthetic smoke, protocol inventory, monitoring and route-disable rollback.

## Residual risks

- Compatibility is intentionally narrower than OpenAI and future SDK defaults may need review.
- Prompt injection may influence behavior inside immutable authorized capabilities.
- Character bounds do not equal tokenization; runtime caps remain necessary.
- Stolen credentials retain granted authority until revocation.
- Existing runtimes may retain redacted background state under current policy.
- Synchronous RAG latency/cost can be abused within configured limits.

## Required security tests

- Missing/malformed/unknown/revoked token and disabled consumer.
- REST-to-MCP and MCP-to-HTTPS protocol-confusion denial.
- Missing/disabled binding, missing capability, inactive scenario, foreign/same-text alias and
  cross-tenant release/contract non-disclosure.
- Raw IDs and authority hints rejected.
- Unknown fields, malformed JSON, byte/depth/message/character boundaries, role confusion, controls,
  multimodal/tool/function/MCP/schema/retention override attempts.
- Input/output-contract success, absence and violation with safe errors.
- Idempotency replay/conflict/concurrency and stable opaque IDs.
- Throttle/downstream failure mapping with `Retry-After`.
- Redaction of token, messages, output and client `user` across all telemetry/storage.
- Background workflow/agent authorization, opaque IDs, queue failure and scoped status.
- Legacy gateway/run/MCP authorization and contract regression.
