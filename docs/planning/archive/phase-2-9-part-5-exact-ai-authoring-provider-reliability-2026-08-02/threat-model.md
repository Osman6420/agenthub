# Threat Model: phase-2-9-part-5-exact-ai-authoring-provider-reliability

## Assets and actors

Exact scenario responsibilities, Studio bootstrap state, bounded authoring context, immutable model
profile configuration, prompt contracts, provider usage, untrusted provider output, transient
candidates, accepted drafts, and audit evidence. Actors include exact editors, viewers, release
managers, organization administrators without editor responsibility, unassigned/foreign users, and
attackers controlling prompt text or provider output.

## Entry points and abuse cases

Scenario Studio GET; generate, repair, and accept POSTs; outbound model request; and provider response
parsing. Abuse includes using an organization flag to gain scenario authority, forging hierarchy
IDs, leaking a protected scenario through UI state, prompt injection, multiple/ambiguous JSON object
smuggling, markdown/prose parser confusion, oversized/deep output, auto-publish, sensitive logging,
and duplicate model spend after a timeout or outcome-unknown result.

## Controls

- Exact persisted scenario resolution and central editor authorization in bootstrap and every API.
- UI state is non-authoritative; viewers and unrelated roles never receive a writable AI affordance.
- Approved immutable active profile, SSRF-safe egress adapter, secret indirection, outbound limits,
  JSON response mode, and separated trusted system/untrusted user messages.
- Raw response byte bound precedes parsing. Only a raw JSON object or one complete JSON fence is
  normalized; strict JSON, object type, depth, body, workflow, and live-reference validation follow.
- Generation/repair stays transient. Explicit accept is separately authorized and never publishes.
- Stable redacted audit categories and usage/size metadata only; no prompt, provider response,
  candidate, endpoint, credential, or secret-ref logging.
- Timeout/provider errors are retryable only when the existing error contract proves pre-send or
  failed execution; `OUTCOME_UNKNOWN` explicitly tells the operator not to blind-retry.

## Failure and residual risk

Provider JSON-mode support can vary despite an OpenAI-compatible surface; deterministic fixtures and
the approved synthetic smoke cover the configured profile, while other profiles remain deployment
acceptance work. A compromised platform admin or secret backend remains high impact. Browser state
can become stale, but POST authorization rechecks current responsibilities. Provider quality and
cost are operational risks; validation prevents publication, not poor suggestions.
