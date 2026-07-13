# Task Plan: phase-2-p6-agent-system-prompt

## Task summary

Phase 2 P6 (WS5 5.5): give an agent an **authored, governed system prompt** (persona/instructions)
instead of running on the raw user objective. The prompt is *data, not code*: a bounded,
redaction-safe string carried inline in the `agent_definition` artifact, so it inherits the
artifact's validation, checksum, and release pinning. Tool/decision re-validation is unchanged — the
system prompt is **input, never authorization**.

## Background

P5 wired real retrieve/generate into the agent loop, but the agent still used the user objective as
its prompt (`_respond(prompt=objective)`). The `agent_definition` schema historically forbade prompt
text. P6 adds a governed system prompt so an agent runs with an authored persona.

## Scope

- `agent_schema.py`: an optional `spec.system_prompt` — a non-empty string, ≤ 8000 chars, no control
  characters (except common whitespace). Validated at author time; content-free diagnostics.
- `agents/compiler.py`: `system_prompt` is compiled into the immutable, checksummed `AgentConfig`
  (empty when unset), so a run stays pinned to exactly this system prompt.
- `agents/runtime.py` `_respond`: uses `config["system_prompt"]` as the model prompt when present,
  else falls back to the objective (P5 behavior). The objective still drives retrieval.

## Non-goals

No separate reusable prompt *artifact* reference (inline satisfies "governed, validated, bounded,
redaction-safe, checksummed, release-pinned"); no change to the model-provider interface, tool
proxy, approval, retrieval, RLS, or output-contract gates; no per-turn "user message" slot for the
objective (the objective remains the retrieval query, mirroring `run_rag`). No new dependency; no
live egress. Parsers/OCR/connectors are P7; console UI is P8.

## Acceptance criteria

- An `agent_definition` may carry a bounded `system_prompt`; invalid values (empty, too long,
  control chars, non-string) are rejected at author time with content-free diagnostics.
- The compiled agent pins the system prompt (it changes the agent checksum) and the runtime uses it
  as the model prompt; without one, behavior is unchanged (objective fallback).
- The system prompt is input only — tool/decision/output-contract gates are unchanged; inline
  secrets are still rejected by the shared artifact validator.

## Status

**P6 Implemented and Verified (2026-07-13).** ruff/mypy/check/no-drift clean; SQLite 474 passed / 18
skipped (pgvector); PostgreSQL `--create-db` 490 passed / 2 skipped (off-PG guards). No migration
(compiled-config + validation change only); no new dependency; no live egress. Next: **P7**
(parsers + OCR + connectors — carries the parser dependency + OCR/connector egress approval gates).

## Test plan

Compiler pins the system prompt / defaults empty / changes the checksum; schema rejects empty,
overlong, control-char, and non-string prompts; `_respond` uses the authored prompt and falls back
to the objective when absent; full agent/releases/eval and whole suites unchanged on SQLite +
PostgreSQL.

## Rollback

Validation + compiled-config + runtime change only (no migration). An agent without a `system_prompt`
behaves exactly as before; reverting removes the field. Public contracts unchanged.
