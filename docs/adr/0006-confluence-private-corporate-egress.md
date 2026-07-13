# ADR 0006: Connector-specific private corporate egress for Confluence

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

ADR-0005 requires every resolved destination address to be public unicast. That remains the correct
default for model, embedding, OCR, tool, MCP, generic HTTPS, and future generic REST calls. The
approved P7.4 Confluence Data Center source is different: it is an on-premises corporate service
whose fully qualified hostname resolves only to private addresses.

Globally allowing private addresses would turn AgentHub into an internal-network SSRF primitive.
Putting CIDRs, URLs, TLS switches, or headers in tenant source configuration would have the same
effect. The connector therefore needs a separate, platform-owned policy boundary without weakening
ADR-0005.

## Decision drivers

- Preserve public-unicast-only behavior for all existing egress callers.
- Reach only the reviewed corporate Confluence network, with DNS-rebinding and redirect defenses.
- Keep destination, network, credential, and TLS decisions outside tenant/artifact/request input.
- Add no HTTP/Atlassian/LangChain production dependency.
- Keep CI hermetic and live egress disabled until deployment-specific review.

## Considered options

1. Relax ADR-0005 globally to allow private addresses. Rejected: excessive SSRF blast radius.
2. Let each source carry its base URL and CIDRs. Rejected: tenant-controlled internal-network access.
3. Use an Atlassian/LangChain client with `verify_ssl=False`. Rejected: bypasses pinned-IP transport,
   redirect denial, response caps, and mandatory certificate validation.
4. Add a connector-specific validator driven by an immutable platform profile and a deployment-owned
   network-policy identifier. **Chosen.**

## Decision

- `validate_destination()` and every existing caller remain unchanged and public-unicast-only.
- A separate `validate_private_destination()` entry point is usable only by the Confluence Data
  Center client. It accepts canonical profile fields plus a `network_policy_id`; it does not accept
  tenant CIDRs.
- `network_policy_id` resolves through deployment configuration. Every configured CIDR is validated,
  and every DNS answer must be a private address inside at least one CIDR in that exact policy.
  Empty, malformed, mixed allowed/disallowed, or public answers fail closed.
- Loopback, link-local, multicast, reserved, unspecified, and metadata-class addresses remain denied
  even if a policy mistakenly contains them.
- The transport connects to a validated/pinned IP while using the canonical hostname for SNI and the
  HTTP Host header. Redirects are denied. HTTPS certificate and hostname verification are mandatory;
  corporate CA trust is installed by the deployment, never selected or disabled by a source.
- The immutable platform `ConfluenceProfile` stores only the policy identifier, canonical endpoint
  fields, `secret_ref`, and bounded operational limits. A source carries root/exclusion page IDs and
  relational profile/document-set bindings only.
- The Confluence client constructs a fixed read-only Data Center REST path allowlist, ignores response
  links, uses bounded GET-only retries, and never exposes a general HTTP proxy.
- Default deployment policy configuration is empty. Without a registered profile, granted source,
  configured policy, and resolved secret, no socket is opened.
- This ADR accepts offline implementation. Live rollout remains separately gated on the real base
  URL/context path, Data Center version, DNS results, CIDRs, CA chain, firewall, secret injection,
  service-account scope, and positive/negative permission smoke tests.

## Security consequences

The application intentionally gains a narrow route to a private network. Compromise of the platform
profile catalog, deployment policy registry, DNS/CA, application process, or firewall can exceed the
application-layer boundary. Defense in depth therefore requires least-privilege service accounts and
an egress firewall restricted to the reviewed Confluence host/port.

Tenant-controlled URLs, CIDRs, credentials, headers, CA bundles, redirects, and TLS opt-outs remain
forbidden. Existing public-only regression tests are mandatory alongside exact-private allow,
unlisted/mixed/public/metadata denial, and pinned-host transport tests.

## Operational consequences

Corporate DNS/IP/CA rotation fails closed until deployment policy/trust is updated and reviewed.
Diagnostics and audit use stable codes and profile/policy IDs; they never record host, URL, IP/CIDR,
token, page title/body, or raw upstream errors.

## Data and privacy consequences

The service account can create durable tenant-owned copies of readable Confluence pages. Confluence
per-user ACLs are not reproduced; after import, AgentHub document-set grants, release pinning, and RLS
govern serving. Permission removal upstream becomes visible only after a fully successful sync and an
explicit candidate publish/build/promote flow.

## Positive consequences

- Existing egress security behavior and deterministic CI remain unchanged.
- The private route is reviewable, profile-only, bounded, and reusable only for the named connector.
- No new production dependency or tenant-facing endpoint configuration is introduced.

## Negative consequences

- Deployment needs explicit CIDR policy, corporate CA trust, firewall rules, and rotation procedures.
- A safe configuration error causes availability failure.
- The connector cannot be generalized to arbitrary internal REST services without a new approved
  contract and policy review.

## Migration impact

Additive Confluence profile/grant/source-binding/sync-lineage schema only. Deployment configuration
adds an empty-by-default network-policy mapping and a secret injection namespace. No existing profile,
source, artifact, gateway, or public API row is rewritten.

## Rollback considerations

Disable the Confluence profile and remove its deployment network policy/firewall permission. Existing
public-only egress remains unaffected. Preserve imported document/version, sync-lineage, and audit
history; do not destructively roll back rows already referenced by document sets or releases.

## References

- [ADR-0005](0005-shared-ssrf-safe-egress-adapter.md) — unchanged public-unicast default.
- [P7.4 task plan](../tasks/phase-2-p7-4-connectors/plan.md)
- [P7.4 threat model](../tasks/phase-2-p7-4-connectors/threat-model.md)
