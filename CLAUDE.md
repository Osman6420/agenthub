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

Markdown is guidance, not enforcement: security constraints also require hooks, permissions, sandboxing, and CI. Ask for user approval before destructive or privilege-expanding tool calls.
