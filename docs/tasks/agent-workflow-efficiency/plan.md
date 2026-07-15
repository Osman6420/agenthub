# Agent Workflow Efficiency Plan

## Goal

Reduce avoidable agent context and implementation cost without weakening the
repository's security, verification, commit-readiness, or cross-agent handoff
discipline.

## Scope

- Keep engineering, security, observability, testing, and Definition of Done
  guidance in Claude's startup context.
- Load the operational handoff only on a real Codex/Claude transition.
- Prefer Serena for symbol-aware Python and TypeScript navigation and edits.
- Add one lower-cost implementation worker per agent client while retaining plan,
  review, and acceptance in the capable main model.
- Do not install CodeStruct or change application/runtime dependencies.

## Acceptance criteria

- [x] Shared instructions define Serena-first semantic navigation with a safe
  text-tool fallback and mandatory diff/test verification.
- [x] Shared instructions permit only one bounded code-writing subagent and retain
  trust-boundary decisions and final verification in the main agent.
- [x] Claude has a Sonnet implementation worker.
- [x] Codex has a GPT-5.6 Terra implementation worker with bounded nesting.
- [x] Claude no longer imports the large handoff at every session start.
- [x] The shared handoff is a compact, task-local transition record rather than
  a project-history and runtime-evidence archive.
- [x] Durable local startup and live-health discovery remain explicit and are
  linked from the shared agent instructions and handoff.
- [x] Configuration syntax and repository diff checks pass.

## Assumptions and boundaries

- The user explicitly wants the existing security and pre-commit verification
  discipline retained.
- Fable/GPT-5.6 main-model selection remains task-specific rather than a costly
  project-wide default.
- Serena is user-installed for both clients; actual availability still depends on
  each client session loading its MCP configuration successfully.
- CodeStruct is research reproduction code, not an approved project dependency.

## Status

Implemented and locally verified; fresh-client discovery and pilot token measurement
remain manual follow-up items.
