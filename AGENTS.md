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
[`agent-handoff.md`](docs/ai/agent-handoff.md) checklist and verify its active
handoff against live repository and runtime state before relying on it.

Keep the handoff limited to facts the next agent needs for the current, incomplete
unit: active task, approved scope, decisions, changed files, verification evidence,
runtime/restart state, risks, and the next action. Do not copy project history or
durable behavior into the handoff; link the task record, architecture documentation,
verification evidence, ADR, or commit that owns it.

Before starting, stopping, or diagnosing the local application, follow section 0 of
[`docs/manual-testing-guide.md`](docs/manual-testing-guide.md), inspect the canonical
[`docker-compose.yml`](deploy/compose/docker-compose.yml), and query live Compose and
health state. Never infer that PostgreSQL, Redis, MinIO, web, or workers are running
from a stale handoff.

If reality invalidates the plan, update it before continuing. Do not patch without an accurate plan.

## Code intelligence and editing

Use code-intelligence tools according to the evidence required:

1. **Codebase Memory MCP -- persistent structural and semantic discovery**
   - Prefer it before broad exploration for architecture, packages, routes, graph
     relationships, multi-hop call paths, hotspots, cross-module dependencies,
     semantic code search, and git-diff impact or blast-radius analysis.
   - Before relying on its graph, call `index_status` for the current project and
     confirm the index is present, fresh, and not degraded. Do not rebuild a healthy
     index at every session start; the persisted graph and watcher are designed to
     carry it across sessions.
   - Use `get_architecture` or `get_graph_schema` to orient broad work,
     `trace_path` for callers/callees, `detect_changes` for change impact,
     `search_graph` with `semantic_query` for meaning-based discovery, and
     `search_code` for graph-ranked code text. Semantic and similarity edges require
     a `full` or `moderate` index; `fast` mode is insufficient for semantic work.
   - Treat graph, semantic, similarity, dead-code, and impact results as navigation
     evidence, never as the source of truth. Dynamic dispatch, decorators,
     registries, dependency injection, generated code, framework behavior, and
     runtime configuration may be incomplete or ambiguous.
   - Do not call mutating or data-ingestion tools such as `delete_project`,
     `manage_adr`, or `ingest_traces` unless the active task explicitly requires
     that action and its data and rollback implications have been reviewed.

2. **Serena -- exact semantic symbols, references, and edits**
   - Use symbol overviews and symbol lookup before reading whole source files.
   - Use reference lookup to confirm Codebase Memory candidates before changing a
     public, shared, authorization-sensitive, or security-sensitive symbol.
   - Prefer semantic rename or symbol-body editing when it is safer than text
     replacement.

3. **`rg` -- exact textual and non-semantic search**
   - Use `rg` and `rg --files` for exact strings, settings, URLs, error codes,
     capability names, decorators, registries, templates, documentation,
     configuration, migrations, manifests, generated files, fixtures, and test
     names.
   - Use it to find indirect or string-based references that graph and symbol tools
     can miss.

4. **Direct inspection and tests -- final authority**
   - Read the smallest relevant source regions needed to verify behavior. Code,
     tests, migrations, runtime configuration, authoritative documentation, and
     live runtime evidence remain the sources of truth.
   - Reconcile conflicting tool results before editing. After editing, inspect the
     actual diff and run the same repository-required tests and static checks
     regardless of which discovery or editing tool was used.

For non-trivial code changes, default to:
`Codebase Memory discovery -> Serena symbol/reference confirmation -> rg dynamic
and textual checks -> smallest complete edit -> diff and test verification`.
Skip a tool when it adds no evidence. If Codebase Memory or Serena is unavailable,
stale, degraded, or incomplete, continue with the remaining tools and direct
inspection; never block correctness on a code-intelligence service.

## Agent ownership

Use one main coding agent for planning, implementation, review, and verification.
Do not delegate repository work to subagents. Keep task decomposition inside the
main agent so architecture, security, authorization, migration, compatibility, and
live-diff context remain coherent.

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
