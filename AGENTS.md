# AI Coding Agent Standard

## Purpose

This repository uses coding agents to produce safe, reviewable, enterprise-quality changes. Detailed rules are in [`docs/ai/`](docs/ai/engineering-rules.md).

## Instruction priority

Resolve conflicts in this order: (1) security and data protection, (2) correctness and authorization, (3) reliability and auditability, (4) backward compatibility, (5) maintainability and simplicity, (6) performance, (7) delivery speed. Never trade security or correctness for speed. More specific `AGENTS.md` files may strengthen, but never weaken, this file.

## Mandatory workflow

For every non-trivial task:

1. Inspect affected code, configuration, tests, migrations, and documentation.
2. Identify assumptions, trust boundaries, data flows, and authorization requirements.
3. Create or update the applicable [task plan](docs/tasks/README.md).
4. Record security and operational risks.
5. Make the smallest complete change; add tests with it.
6. Run repository-verified checks and record evidence.
7. Review the final diff as a staff engineer, application-security engineer, and SRE.
8. Report evidence, checks not run, assumptions, and residual risks.

For Codex/Claude transitions, follow the shared
[`agent-handoff.md`](docs/ai/agent-handoff.md) checklist and verify its ephemeral
runtime snapshot against live state before relying on it.

If reality invalidates the plan, update it before continuing. Do not patch without an accurate plan.

## Change boundaries

Explicit user approval is required to add/change a production dependency; alter authentication, authorization, tenant isolation, a public API contract, secrets, certificates, IAM, network, or firewall behavior; write a destructive/irreversible migration; weaken audit, logging, rate limits, tests, linters, scanners, or security controls; access production systems/data; force-push/rewrite shared history; delete resources; or reset a database. Never fix a failure by deleting a test, weakening an assertion, or bypassing a control.

## Planning and sources of truth

- [`master-plan.md`](docs/planning/master-plan.md): project scope, milestones, dependencies, risks, and completion criteria.
- `docs/planning/components/<component>-plan.md`: multi-task or independently deliverable component work.
- `docs/tasks/<task-id>/plan.md`: temporary feature, bug, migration, or security implementation plan.
- README/component architecture docs: supported current behavior.
- [ADRs](docs/adr/README.md): reasons for durable technical decisions.
- Task verification records: completion evidence.

Plans are authoritative for intended/in-progress work. Code, tests, migrations, and runtime configuration are authoritative for implementation. Current-behavior docs, ADRs, and verification records are authoritative for their respective concerns. Link to the authority instead of duplicating detail.

Keep plans current at milestone/acceptance-criterion granularity, not as commit diaries. Track `Implemented` and `Verified` separately; never mark work complete without evidence. Transfer durable decisions to ADRs and actual behavior to README/architecture docs. On completion, create verification evidence, update the master plan, and archive the task plan according to [planning policy](docs/planning/archive/README.md).

## Baselines

- [Security](docs/ai/security-rules.md): deny by default; enforce object/action/tenant/field authorization server-side; distrust client roles, owners, tenants, and permissions; use explicit schemas/allowlists and parameterized queries; prevent injection, SSRF, traversal, unsafe deserialization, and command execution; apply least privilege and outbound timeouts/domain/size limits; never log secrets; test authorization denial and cross-tenant/user access.
- [Observability](docs/ai/observability-rules.md): structured stable events with propagated request/trace IDs and safe actor/tenant references. Keep application logs separate from security/business audit. Audit state changes and security-sensitive actions with actor, action, target, authorization decision, outcome, reason, and trace. Define audit persistence failure as fail-open or fail-closed per operation.
- [Testing](docs/ai/testing-rules.md): cover happy path, invalid input, authentication failure, authorization denial, cross-tenant/user access, boundaries, failures, retry/idempotency, audit, redaction, compatibility, and migrations. Do not rely only on mocks at critical boundaries.
- [Definition of Done](docs/ai/definition-of-done.md): completion requires evidence for applicable formatter, linter, type-check, unit/integration/security/migration/secret checks, authorization, observability/audit, and final-diff review. Explicitly report unavailable checks and remaining risk.

## Final report

End every task with: Summary; Files changed; Architecture impact; Security impact; Authorization impact; Data and privacy impact; Logging, metrics, tracing and audit impact; Database and migration impact; Tests and verification results; Unverified assumptions; Remaining risks; Manual review required.
