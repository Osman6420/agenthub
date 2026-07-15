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
- Keep planning, implementation, review, and acceptance in one capable main model.
- Remove the project-specific Claude and Codex implementation workers after the
  Part 2 pilot showed that cross-cutting correction cost outweighed draft savings.
- Do not install CodeStruct or change application/runtime dependencies.

## Acceptance criteria

- [x] Shared instructions define Serena-first semantic navigation with a safe
  text-tool fallback and mandatory diff/test verification.
- [x] Shared instructions prohibit repository delegation and retain the complete
  implementation context in the main agent.
- [x] Project-specific Claude and Codex implementation-worker definitions are removed.
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

Revised and locally verified after the Part 2 pilot. Serena discovery in a fresh
Codex task remains a manual follow-up because MCP tools are fixed when a task starts.
