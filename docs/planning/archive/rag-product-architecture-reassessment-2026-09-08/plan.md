# RAG product architecture reassessment

## Task and approved scope

Reassess the architecture from the owner's purpose: rapidly build and maintain RAG solutions, ingest through external connectors including REST/MCP, and expose governed tools and APIs. The owner states the application is not live and permits consideration of major redesign or rebuilding. This authorizes a design assessment, not implementation, database reset or destruction.

The prior database review assessed consolidation while retaining current behavior. This unit explicitly challenges that behavior: versioning granularity, permissions, workflow scope, publishing and data freshness. Do not treat existing services or ADRs as proof of product necessity.

## Acceptance criteria

- [x] Trace current authoring/publishing, ingestion/retrieval, permissions, REST/MCP and tool flows; distinguish product needs from implementation choices.
- [x] Evaluate strict versioning against faster editing, automatic ingestion and maintenance; propose minimum consistency, rollback and audit contracts.
- [x] Compare incremental consolidation, RAG-focused redesign and full rewrite, including what is intentionally lost and retained.
- [x] Produce a concrete target domain/table inventory, user journeys, change-impact rules, failure/security boundaries and transition strategy.
- [x] Ground technical recommendations in current code and primary documentation; record assumptions and verification limitations.
- [x] Archive the assessment and link from the master plan without marking proposals as adopted behavior.

## Assumptions and questions

Owner confirmed mutually isolated teams/data areas AND long-running agents, human approval, parallel workflows and compensation in the first scope. Preserve workspace isolation and durable execution as actual requirements; challenge governance/versioning granularity around them. A bounded-only runtime is not an adequate target. Non-production does not mean local documents/configuration may be discarded without approval.

## Non-goals / interfaces / data / migration

No application, authorization, API, dependency, schema, runtime or data change. No external messages or provider calls. Existing unrelated edits retained. Documentation only; no architecture ADR adopted until the owner chooses a target.

## Work and verification

Single main agent. Read-only code/migration/test analysis, selected structural counts, official protocol/storage/framework references where needed, traceable evidence map and documentation/diff checks. Existing previous-turn tests are historical evidence only. No full runtime suite required absent behavior changes; browser gate N/A. If runtime inspection becomes necessary, re-read startup rules and inspect live Compose/health first.

## Risks

Over-fitting a new design to table count; retaining accidental complexity; silently losing isolation, delivery durability, source lineage or API security; hiding relational state in JSON; treating snapshots as proof of deterministic LLM reproduction; incompatible retrieval embeddings; unsafe write-tool retries; understating rewrite cost.

## Status

Completed 2026-09-08. Implemented: [assessment](assessment.md), [target model](target-model.md) and review records only. Verified: all 80 current models mapped, 35 proposed models enumerated, current model/migration table names reconciled, targeted existing runtime/approval tests (77 passed, 11 PostgreSQL-only skips under explicit offline model-provider selection; initial environment-dependent failures retained), source/primary-reference and documentation review. See [verification](verification.md). No target application, authorization policy, migration or dependency implemented; no ADR adopted. No replacement implementation plan until the owner chooses a direction.
