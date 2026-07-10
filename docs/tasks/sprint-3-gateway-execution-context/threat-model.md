# Threat Model: sprint-3-gateway-execution-context

## Assets

- Consumer credentials (bearer tokens) and the authorization decision path.
- The signed `ExecutionContext` (short-lived authority passed to the runtime).
- Idempotency records and usage/audit trail.

## Trust boundaries

- Public network / external consumer → gateway (authenticated, rate-limited).
- Gateway → runtime (via signed ExecutionContext, not raw trust).
- Application → PostgreSQL/Redis (private).

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Unauthenticated access | No/invalid token → 401; endpoints require an active consumer + active token. |
| Token theft / at-rest exposure | Tokens stored only as SHA-256 hashes; plaintext shown once; revocable; lookups fail closed. |
| Privilege escalation via raw project/release/tool id | Routing is by bound `scenario_alias` only; raw ids in the body are ignored; foreign/unbound alias → 403. |
| Capability bypass | Required capability checked against the resolved binding server-side; missing → 403 `CAPABILITY_DENIED`. |
| Cross-tenant access | Binding resolution uses the consumer's organization; foreign alias does not resolve. |
| ExecutionContext forgery/replay | HMAC-signed with the Django secret; short TTL; downstream verifies signature + expiry; tampering fails. |
| Duplicate side effects / conflicting retries | Idempotency-Key: identical body replays the stored response; differing body → 409. |
| Abuse / DoS | Per-consumer rate limit; bounded request size; safe error envelope. |
| Injection via input payload | Input validated against the release's JSON-Schema input contract before use; invalid → 400. |
| Information leak in errors | Stable, safe error codes/messages; internal detail logged, never returned; no secrets/PII in audit or usage. |

## Residual risk

- The bearer-token seam is the only credential type in this sprint; OIDC/JWT/mTLS
  are pluggable later. Token rotation/expiry policy is basic (active/revoked).
- The runtime facade returns `accepted` (no generation yet); output-contract/policy
  enforcement on the response arrives with the runtime (Sprint 4). Until then no
  model output is produced or returned.
- Rate-limit accuracy depends on the shared cache; a cache outage degrades limiting
  (fail-open on limiting only, never on authentication/authorization).
