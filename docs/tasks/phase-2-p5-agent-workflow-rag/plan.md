# Task Plan: phase-2-p5-agent-workflow-rag

## Task summary

Phase 2 P5 (WS5 5.3–5.4): replace the deterministic `retrieve`/`generate` stubs in the workflow and
agent runtimes with the **same governed providers** the standalone `run_rag` uses (P1 chat + P4
document-ACL retrieval), and add **per-node prompt/model binding** to the workflow `generate` node so
a workflow with several `generate` nodes runs distinct governed prompts/models. Deterministic
providers remain the default, so CI stays hermetic; the real behavior lights up by configuration.

## Background

P1–P4 are verified: real chat provider, content plane, staged embeddings, and document-ACL retrieval
(deny-by-default + FORCE RLS + pointer-flip). Until now the agent loop's `retrieve` step and the
workflow `retrieve`/`generate` nodes were deterministic stubs, so real pgvector RAG only ran in the
standalone `/v1/query` path — not inside agents/workflows. P5 closes that gap.

## Scope

- New shared `apps/orchestration/rag_steps.py`: `retrieve_for_release` (release-bundle-scoped
  retrieval via `get_retrieval_provider`, carrying `document_set_version_ids` → P4 ACL path),
  `generate_for_release` (`get_model_provider` with the bundle prompt/model_profile, or per-node
  overrides), and JSON chunk⇄state helpers (durable redacted state stays JSON-safe).
- Workflow `retrieve` node → `retrieve_for_release`; `generate` node → `generate_for_release` over
  the retrieved context, with output `{answer, sources}` and stable failure codes
  (`WORKFLOW_RETRIEVAL_FAILED` / `WORKFLOW_GENERATION_FAILED`).
- **Per-node prompt/model binding (P5.2):** the `generate` node accepts optional `prompt_ref` /
  `model_profile_ref` naming release-manifest roles; the compiler validates them; the runtime
  resolves them (falling back to the release-level `prompt`/`model_profile` roles).
- Agent `retrieve` decision → `retrieve_for_release`; agent `_respond` → `generate_for_release` over
  the retrieved context + the release model_profile (previously empty context/profile).

## Non-goals

- An **authored agent system prompt** (the agent still uses the user objective as the prompt) — that
  is **P6**. Parsers/OCR/connectors are P7; console UI is P8. No RLS/binding/promotion changes
  (P4). No new dependency; no live egress (deterministic defaults keep CI hermetic).

## Acceptance criteria

- Workflow `retrieve`/`generate` and agent retrieve/respond call the governed provider seams; with a
  configured retriever they ground generation on real, ACL-scoped, tenant-isolated chunks.
- A workflow `generate` node binds a specific `prompt_ref`/`model_profile_ref` (multi-prompt), and
  the compiler rejects unknown/non-identifier config.
- Redacted run state carries only JSON-safe chunk metadata; failures fail closed with stable codes.
- Deterministic default behavior unchanged for existing suites; no live egress in CI.

## Status

**P5 Implemented and Verified (2026-07-13).** ruff/mypy/check/no-drift clean; SQLite 464 passed / 18
skipped (pgvector); PostgreSQL `--create-db` 480 passed / 2 skipped (off-PG guards). No migration
(behavioral wiring only); no new dependency; no live egress. Next: **P6** (authored agent
system-prompt artifact).

## Test plan

`rag_steps` unit tests (chunk roundtrip; `retrieve_for_release` over the demo provider;
`generate_for_release` grounds on context and defaults to the bundle prompt/profile); compiler tests
(generate accepts/binds `prompt_ref`/`model_profile_ref`, rejects unknown/non-identifier, retrieve
rejects config); full workflow/agent suites unchanged (no regression) on SQLite + PostgreSQL.

## Rollback

Behavioral change only (no migration). Reverting restores the stubs; releases and the public
`/v1/query`, `/v1/invoke` contracts are unchanged. Real providers are opt-in by configuration.
