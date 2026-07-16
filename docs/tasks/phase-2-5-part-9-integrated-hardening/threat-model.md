# Threat Model: Phase 2.5 Part 9 integrated hardening

## Assets and boundaries

Tenant-scoped console data, consumer credentials, immutable artifacts/releases, document bytes,
workflow/agent/tool configuration, provider credentials and audit/usage records cross browser,
gateway, worker, PostgreSQL, Redis, object-store and approved-egress boundaries.

## Threats and controls

- Cross-tenant links, counts or mutations: derive scope server-side and retain foreign-object 404 and
  authorization-denial regression evidence.
- Credential or content disclosure: show token plaintext once, redact logs/audit, and never use real
  content in closure smoke tests.
- Protocol/capability bypass: REST and MCP credentials stay non-interchangeable and scenario aliases
  resolve only through authenticated bindings.
- Unsafe workflow/DSL execution: closed node/operation registries, bounded inputs and canonical
  compiler/runtime validation remain mandatory.
- Deployment drift: build the canonical image and verify the documented Compose topology instead of
  relying only on a host process.
- Live SSRF, retention and denial-of-wallet: require immutable allowlisted profiles, network policy,
  time/size/token/cost bounds, synthetic data and explicit owner approval before egress.

## Residual risks

Local and staging-equivalent evidence cannot prove production DNS, CA, firewall, pooling, provider
retention, budget alerts or operational rollback. Upload malware/type scanning remains the explicit
Phase 3 residual risk and must be included in production risk acceptance.
