# Claude Code Instructions

@AGENTS.md
@docs/ai/engineering-rules.md
@docs/ai/security-rules.md
@docs/ai/observability-rules.md
@docs/ai/testing-rules.md
@docs/ai/definition-of-done.md

Plan before every non-trivial task. Use separate subagents when useful for research, tests, security, or diff review, but independently verify their output. When a failure repeats, consider proposing a durable, general rule. Keep temporary and task-specific facts out of this file.

When the active main model is Fable or Opus and a bounded implementation plan is stable, prefer the project `implementer` subagent for the mechanical edit phase, then return to the main model for live-diff review and verification. Read `docs/ai/agent-handoff.md` on an actual Codex/Claude transition, not at every session start.

Markdown is guidance, not enforcement: security constraints also require hooks, permissions, sandboxing, and CI. Ask for user approval before destructive or privilege-expanding tool calls.
