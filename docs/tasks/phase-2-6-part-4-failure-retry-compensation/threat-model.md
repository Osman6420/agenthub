# Threat Model: P2.6.4 failure, retry and compensation

## Protected assets and boundaries

- External side effects, tenant workflow state, release pins, capability decisions, compensation
  inputs and operator decisions are protected assets.
- Provider/tool responses, broker delivery, author DSL, browser input and late worker results are
  untrusted.
- Compiler validation, immutable release manifests, runtime transition services, tool proxy,
  PostgreSQL RLS and operator authorization are independent enforcement boundaries.

## Threats and controls

- **Duplicate destructive side effect:** retry requires explicit idempotency plus a server-verified
  contract; stable attempt/idempotency keys and terminal records suppress redelivery.
- **Ambiguous dispatch blindly repeated:** `outcome_unknown` is terminal for automation and requires
  reconciliation; no author policy can override it.
- **Compensation becomes a second attack path:** compensation targets are compile-time pinned,
  capability-checked through the normal proxy, input-mapped and independently audited.
- **Wrong-order or repeated compensation:** durable reverse sequence, row locks and terminal entries
  make execution ordered and idempotent.
- **Author relabels permanent/auth failure as transient:** classification is server-owned and unknown
  codes fail closed as permanent.
- **Error payload exfiltrates secrets:** only stable class/code and checksums enter state/audit; raw
  exception text, tool payloads, source code, endpoint and credentials are excluded.
- **Retry budget exhaustion/DoS:** attempts, backoff, jitter, state/output size and run deadline are
  capped; cancellation wins.
- **Late work resurrects terminal run:** every transition locks and rechecks run/attempt/entry terminal
  state before mutation.
- **Cross-tenant recovery decision:** direct organization lineage, scoped lookup, platform-admin role
  check, exact revision and FORCE RLS all must agree.
- **CSRF or replayed operator action:** POST-only CSRF-protected action, optimistic checksum/revision,
  terminal guards and audited idempotent decisions.
- **Operator uses recovery as arbitrary state editor:** fixed action enum only; no arbitrary node,
  payload, capability or state mutation fields.

## Audit policy

Audit attempt scheduled/claimed/completed/failed, compensation pushed/claimed/completed/blocked,
operator allow/deny/decision and terminal recovery outcome. Audit metadata contains tenant-safe ids,
stable action/class/code, attempt number, checksums and trace id only. Automatic transitions remain
fail-open on audit persistence consistently with current workflow runtime; operator ambiguity
decisions are proposed fail-closed if their security audit cannot be persisted.

## Residual risks

- A remote system without idempotency or reconciliation cannot be made safe by workflow retries; its
  failure remains operator-required.
- Compensation is a new side effect and can itself become ambiguous; automation stops rather than
  guessing.
- Live broker/process-kill drills are required in addition to unit tests before activation.
