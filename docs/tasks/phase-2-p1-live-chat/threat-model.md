# Threat Model: phase-2-p1-live-chat

## Assets

Model credentials, platform endpoint catalog, prompts/context, model responses, tenant/release
identity, model usage metadata, audit history, availability and cost budgets.

## Trust boundaries and data flow

Consumer input and retrieved text are untrusted. A release-pinned artifact supplies only a catalog
profile reference. The server resolves the immutable platform profile, resolves its secret at call
time, constructs the OpenAI-compatible request, validates DNS/IP, performs pinned-IP TLS transport,
parses a bounded response, then applies existing output/citation/policy governance. The network and
provider response are untrusted. The deterministic provider crosses no network boundary.

## Threats

- Artifact/request supplies a URL, secret, header, TLS override, or mutable profile and steers SSRF.
- DNS rebinding or redirect reaches private, loopback, link-local, metadata, or unexpected hosts.
- Cross-tenant use or enumeration of a profile widens authorization or leaks configuration.
- Credential, endpoint, prompt, context, response, or document content appears in logs/audit/errors.
- Oversized, malformed, deeply nested, or adversarial JSON exhausts resources or bypasses parsing.
- Timeout/reset/429/503 is blindly retried, duplicating cost or producing divergent answers.
- Provider output injects authorization/tool decisions or bypasses output/citation/policy checks.
- Profile mutation silently changes behavior of an already compiled/released scenario.
- Audit failure hides profile creation or security-sensitive configuration changes.

## Controls

- Platform-admin-only immutable, revisioned catalog; new configuration means a new row/revision.
- Artifact schema allowlists only profile ID/role; endpoint/secret/TLS fields are rejected.
- HTTPS only; validate every resolved IP as public-unicast; connect to pinned IP with hostname SNI
  and certificate verification; deny redirects and caller-supplied transport fields.
- Late secret resolution from `secret:<name>`; no secrets/endpoints/content in logs or audit.
- Connect/read timeouts, request/token/response byte bounds, bounded JSON/schema validation.
- Retry only when no request byte was written or provider idempotency is explicitly guaranteed;
  post-send failure is `outcome_unknown` and never silently resent.
- Model output remains untrusted and passes existing server-side output/citation/policy controls;
  it cannot authorize tools or expand tenant/release permissions.
- Deterministic provider remains default; live egress requires explicit configuration and approval.
- Profile registration audit is fail-closed because it changes a security-sensitive egress target.

## Required negative tests

Non-platform registration; mutation; artifact inline endpoint/secret/TLS rejection; unknown/disabled
profile; caller URL ignored/rejected; private/rebinding DNS; redirect; TLS failure; oversize and
malformed response; post-send no-retry; 429/503 no-retry absent idempotency; log/audit redaction;
default configuration makes no socket call; existing output governance still replaces invalid model
output with fallback.

## Residual risks

OpenAI-compatible providers vary in response/token semantics; the in-house adapter must be kept
small and compatibility-tested. A compromised platform administrator can register an approved
public destination, so administrative access and audit review remain critical. Network policy is an
additional deployment layer and is not activated by this code-only increment.
