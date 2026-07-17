# Threat Model: Phase 2.6 second-wave integration gate

## Assets and trust boundaries

- Tenant workflow state, child-run lineage, wait payloads, release pins and capability envelopes are
  protected assets.
- Broker delivery, event payloads, child output, workflow DSL and scenario-authored Python remain
  untrusted inputs.
- PostgreSQL RLS, server-side tenant context, immutable release pins and runtime terminal guards are
  independent enforcement boundaries.

## Integration threats and controls

- **Migration collision weakens RLS:** keep one linear workflow migration chain and prove PostgreSQL
  application plus inventory/provisioning coverage.
- **Late work resurrects a cancelled parent:** terminal guards win over branch completion, timer
  reconciliation and child results; verify cancellation and late-result cases together.
- **Duplicate delivery mutates state twice:** branch completion, wait consumption and child
  admission/result transitions remain idempotent under row locks and stable keys.
- **Cross-tenant child or wait substitution:** all lookups bind organization and parent lineage;
  database RLS provides defense in depth for direct tenant tables.
- **Capability amplification through child execution:** retain the four-source capability
  intersection and fresh child execution context; no parent authority object is inherited.
- **Unreviewed Python executes in the web/runtime process:** production execution remains disabled
  and fails closed without explicit isolated resolver and runner adapters.
- **Sensitive code or payload enters logs:** stable reason codes and checksums are recorded; Python
  source, secrets and raw tenant payloads are excluded.

## Residual risks

- Local Compose is a development topology, not the production P2.6.8 isolation target.
- Crash/restart and broker-outage drills with live workers remain part of activation/P2.6.11 closure.
- PostgreSQL superuser test connections can bypass RLS; explicit non-superuser probe roles are
  required for database-level tenant-isolation evidence.
