# Threat Model: phase-2-p3-embeddings

## Assets

- The platform embedding-endpoint destinations and credentials (catalog secrets).
- Tenant embedding-input text (sent to the embedding endpoint) and the resulting vectors.
- Tenant isolation of which profiles a tenant may use (grants).

## Actors and entry points

- **Platform admin** registering profiles / granting them to tenants (management commands /
  services). Tenants **cannot** create profiles or set endpoints.
- **The ingestion build path** (P3.2) invoking the embedding client with a resolved profile id.
- **The embedding endpoint** (external HTTPS), reached only through the shared SSRF-safe transport.

## Trust boundaries

- Author/tenant/request ↔ destination: closed. Artifacts and callers pass a **profile id only**;
  endpoint/host/scheme/secret/TLS come from the platform catalog (ADR-0002).
- Server ↔ embedding endpoint: the single ADR-0005 choke point (`apps.tools.egress` +
  `http_adapter`) — public-unicast DNS validation, connect-to-resolved-IP with SNI/Host (anti-
  rebinding), redirect denial, TLS verification, connect/read timeouts, response-size cap.

## Threats and mitigations (P3.1)

| Threat | Mitigation |
| --- | --- |
| SSRF / DNS rebinding to internal services via a crafted endpoint | Destinations are catalog-resolved and validated at the shared choke point; resolved IP must be public unicast and is pinned for the TLS connection. Test: private DNS denied before transport. |
| Author/tenant supplying a URL/host/scheme/TLS opt-out | Profile-id-only client; no destination field is accepted from callers/artifacts. Validation rejects non-https/private host at registration. |
| Credential leakage | `secret:<name>` reference only; resolved late from `EMBEDDING_SECRET_*`; never persisted or logged; audit excludes endpoint and secret ref (test-asserted). |
| Privilege escalation (tenant self-registers a profile/grant) | Registration and grant are platform-admin-only; denial audited. |
| Silent dimension truncation (wrong vectors) | Registration rejects an unsupported dimension for the index type; the client rejects any response vector whose length ≠ profile dimensions (no truncate/pad). |
| Ambiguous retry causing double cost / divergent vectors | Post-send failure → `EmbeddingOutcomeUnknown` (`outcome_unknown`), never blindly re-sent (ADR-0002/0005); only provably pre-send failures retry (inside the shared transport). |
| Oversized / malformed / redirect responses | Response-size cap, redirect denial, and JSON/shape validation fail closed with stable codes. |
| Profile mutation after use | `EmbeddingProfile` is immutable (only status may change); delete blocked; a change requires a new revision. |
| Embedding-input / vector disclosure in telemetry | No prompt/input/vector/endpoint content in logs, metric labels, or audit (ids/counts/status only). |

## Residual risks

- **Per-tenant grant enforcement at build time** is wired in P3.2; P3.1 provides the grant model and
  platform-admin management but the ingestion build does not yet consult grants (no build path uses
  the real client until P3.2).
- **Live endpoint behavior** (TLS chain, rate limits, cost, provider response quirks) is unverified
  until a separately-approved environment-specific egress rollout.
- Platform-admin compromise remains powerful (can register destinations); mitigated by audit and
  the platform-admin trust boundary, not eliminated.
