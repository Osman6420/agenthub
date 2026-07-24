# Claude Code Instructions

@AGENTS.md
@docs/ai/engineering-rules.md
@docs/ai/security-rules.md
@docs/ai/observability-rules.md
@docs/ai/testing-rules.md
@docs/ai/definition-of-done.md

Plan before every non-trivial task. Use the main agent for planning, implementation,
review, and verification; do not delegate repository work to subagents. When a
failure repeats, consider proposing a durable, general rule. Keep temporary and
task-specific facts out of this file.

Read `docs/ai/agent-handoff.md` on an actual Codex/Claude transition, not at every
session start.

## Codebase Memory usage

Follow the Codebase Memory, Serena, `rg`, source-inspection, and test authority
defined in `AGENTS.md`. At the start of broad or cross-component repository work,
check `index_status`; reuse a healthy persisted index instead of rebuilding it.
Use graph/architecture tools for relationships and impact, and use
`search_graph.semantic_query` for meaning-based discovery. A semantic task requires
an index built in `full` or `moderate` mode, not `fast`.

Codebase Memory results are advisory. Confirm candidate declarations and references
with Serena, check dynamic/string/configuration paths with `rg`, and verify the
actual source, diff, and tests before concluding or editing. Do not use
`delete_project`, `manage_adr`, or `ingest_traces` unless the active task explicitly
requires the mutation or ingestion and its risks have been reviewed.

Markdown is guidance, not enforcement: security constraints also require hooks, permissions, sandboxing, and CI. Ask for user approval before destructive or privilege-expanding tool calls.
