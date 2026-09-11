# Task Plan: sprint-3-gateway-execution-context

## Task summary

Implement Sprint 3 of the [v3 target plan](../../../agenthub-v3-django-plan.md#25-uygulama-asamalari):
the public gateway — the single authenticated entry point that authenticates a
consumer, authorizes a scenario alias + capability, enforces idempotency and rate
limits, issues a signed short-lived `ExecutionContext`, and returns a standard error
envelope. This is the first externally reachable product API.

## Background

Sprints 1–2 built tenant/identity/catalog and the artifact/release registry. The
gateway sits in front of the (later) runtime and is the sole place consumers reach
the platform. It must be fail-closed: no raw project/release/tool selection, all
authorization server-side, and the exact release pinned per request.

## Scope

- Consumer authentication via bearer token (`ConsumerToken`, hashed at rest) — a
  pluggable seam; OIDC/JWT/mTLS are added later without changing the flow.
- DRF wiring: standard error envelope, per-consumer rate limiting, request IDs.
- `ExecutionContext`: HMAC-signed, short-lived, carrying org/project/scenario/
  release/consumer/capabilities; issued by the gateway and verifiable downstream.
- Endpoints: `POST /v1/invoke`, `POST /v1/query` (RAG facade), `GET /v1/runs/{id}`,
  plus the existing health probes.
- Idempotency: `Idempotency-Key` replay + conflict (409) on differing body.
- Input validation against the release's input contract (gateway schema validation).
- Audit + a first `UsageEvent` per request (`observability` app).

## Non-goals

- No answer generation/RAG runtime yet (Sprint 4). The gateway resolves everything,
  issues the context, and returns an `accepted` result via a runtime-facade seam.
- No streaming/SSE, MCP ingress (Sprint 7), or agent/workflow runs (Sprint 8/10).
- No OIDC/JWT/mTLS credential providers yet (token seam only).

## Acceptance criteria

From the v3 plan (Sprint 3):

- No/invalid token → 401; unauthorized alias or missing capability → 403.
- A caller cannot gain access via a raw project/release ID — only a bound
  `scenario_alias` routes; unknown/foreign alias is denied.
- The same `Idempotency-Key` with a different request body → 409.

## Affected components

New: `gateway` gains models/views/auth/context/errors; `identity` gains
`ConsumerToken`; new `observability` app (`UsageEvent`). New dependency:
`djangorestframework`.

## Interfaces affected

New public endpoints under `/v1/`. Standard JSON error envelope with stable codes.
The signed `ExecutionContext` is an internal contract passed to the runtime.

## Data impact

New tables: `identity_consumertoken` (hashed tokens; no plaintext), `gateway_
idempotencyrecord`, `observability_usageevent`. No PII stored beyond hashed subject
references.

## Security impact

- Deny-by-default: unauthenticated → 401; unauthorized alias/capability → 403; all
  decisions server-side from the consumer's bindings, never client-supplied ids.
- Tokens are stored only as SHA-256 hashes; the plaintext is shown once at creation.
- `ExecutionContext` is HMAC-signed with the Django secret and expires (default 5
  min); downstream verifies signature + expiry (fail-closed).
- Idempotency prevents duplicate side effects and conflicting replays (409).
- Rate limiting per consumer bounds abuse. Error messages are safe/stable; internal
  detail is logged, not returned.

## Authorization impact

Capability enforcement now happens on the request path: `invoke`/`query` require the
`query` capability on the resolved binding. Cross-tenant/foreign alias is denied.

## Observability impact

Each request gets a request id, an audit event (auth/authz outcome), and a
`UsageEvent` (scenario/release/consumer/status/latency; token counts arrive with the
runtime).

## Migration impact

Additive migrations for `identity`, `gateway`, `observability`. Verified with
`makemigrations --check` and applied to real PostgreSQL.

## Dependencies

New production dependency: `djangorestframework` (ADR-approved as part of the plan).

## Implementation steps

1. Add DRF + settings (error handler, throttle, request id).
2. `ConsumerToken` model + hashing + `create_consumer_token` command.
3. Gateway auth (bearer → consumer), permission, error envelope + codes.
4. `ExecutionContext` sign/verify; runtime-facade stub.
5. `IdempotencyRecord`; `/v1/invoke`, `/v1/query`, `/v1/runs/{id}`.
6. `UsageEvent`; per-consumer rate limit.
7. Tests (401/403/409, raw-id denial, context sign/verify/expiry, input-contract
   400, error-envelope snapshot); gates on SQLite + PostgreSQL; end-to-end invoke.

## Test plan

- 401 without/with invalid token; 403 for foreign/unbound alias and missing
  capability; 409 for idempotency-key body conflict; replay returns the stored
  response.
- A body with `project_id`/`release_id` but no `scenario_alias` is rejected (no
  access via raw ids).
- ExecutionContext verifies when fresh, fails on tampering and after expiry.
- Input failing the release input contract → 400 `INPUT_CONTRACT_VIOLATION`.
- Disabled consumer/token → 401/403; no active release → `RELEASE_NOT_AVAILABLE`.

## Rollout plan

Additive; behind CI gates. The runtime facade returns `accepted` until Sprint 4
wires generation. Tokens are issued per consumer via the management command.

## Rollback plan

Revert the commit; drop the three new tables (greenfield). No external state.

## Risks

- Token/credential handling is security-critical; mitigated by hashing at rest,
  fail-closed lookups, and negative tests.
- Rate-limit state depends on the cache backend; default rate is generous and the
  throttle is unit-tested in isolation to avoid cross-test contamination.

## Open questions

- Long-term consumer credential model (OIDC client creds vs. mTLS vs. tokens); this
  sprint ships the token seam and leaves the others pluggable.

## Status

Verified — all gates green; 59 tests pass on SQLite and real PostgreSQL; the live
gateway flow (401/200/400/403/409, idempotency replay, query facade) was exercised
end-to-end against the dev database on 2026-07-10. Evidence in
[`verification.md`](verification.md). Not yet `Completed`: RAG runtime output
(Sprint 4), OIDC/JWT/mTLS credentials, and human review remain.

## Completion criteria

Map to the [Definition of Done](../../ai/definition-of-done.md): acceptance criteria
met with recorded evidence; authorization negative tests pass; no secrets in logs;
gates green on SQLite and PostgreSQL; docs and master plan updated.
