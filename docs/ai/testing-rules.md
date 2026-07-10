# Testing Rules

## Test strategy

Use the lowest-cost layer that proves the behavior, plus real-boundary coverage where risk demands it:

- Unit tests isolate deterministic domain rules.
- Integration tests verify database, queue, cache, provider adapter, authorization, and audit boundaries.
- Contract tests protect public APIs/events/provider assumptions and backward compatibility.
- End-to-end tests cover a few critical user and operational flows.
- Migration tests prove forward transition, compatibility during rollout, data invariants, and rollback/forward-fix strategy.
- Security tests cover abuse cases, validation, injection/SSRF/path/upload controls, privilege escalation, and isolation.
- Performance/load tests are required for latency/throughput objectives, unbounded work risks, concurrency, queues, or material query changes.

Tests must be deterministic, isolated, order-independent, and safe for parallel execution. Use synthetic/anonymized data and no production secrets/data. Mock unstable or expensive edges, not the authorization policy, schema, persistence constraints, or critical integration contract being proved.

## Required cases

For applicable behavior test happy path, invalid/unexpected input, boundary values, authentication failure, authorization denial, cross-user/cross-tenant access, dependency failure/timeout, retries and idempotency, concurrency, audit event content/delivery behavior, sensitive-data redaction, and backward compatibility. Migration changes require representative data and constraint validation.

Quarantine a flaky test only with ownership, evidence, risk, and a removal deadline; never silently rerun indefinitely. Never delete a failing test, weaken its assertion, or bypass a control to make a check green.

## Repository commands

No executable test, formatter, lint, type-check, or migration command is currently repository-verified. The target-plan examples are not runnable evidence. When manifests/configuration are introduced, record canonical local and CI commands here and in [`engineering-rules.md`](engineering-rules.md).
