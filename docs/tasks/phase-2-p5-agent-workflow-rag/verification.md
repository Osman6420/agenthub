# Verification: phase-2-p5-agent-workflow-rag

## Status

**P5 Verified 2026-07-13.** Automated evidence only; deterministic model/retrieval/embedding
providers remain the default, so no socket is opened and no live endpoint is called. The real
providers (P1 chat + P4 ACL retrieval) light up by configuration on the same seams.

## Acceptance criteria mapping

- **Governed seams wired:** workflow `retrieve`/`generate` and agent retrieve/`_respond` route through
  `apps/orchestration/rag_steps` (`retrieve_for_release` / `generate_for_release`), which resolve the
  release bundle and call `get_retrieval_provider()` (carrying `document_set_version_ids` → P4 ACL)
  and `get_model_provider()`.
- **Grounding proven:** `generate_for_release` passes the retrieved context to the provider — the
  default `StubModelProvider` echoes the top chunk (`test_generate_for_release_grounds_on_context`),
  and defaults to the bundle prompt/profile when no per-node override is given.
- **Per-node binding:** the `generate` node accepts `prompt_ref`/`model_profile_ref` (multi-prompt),
  the compiler validates identifiers and rejects unknown keys, and `retrieve` rejects config
  (`test_generate_binding`).
- **JSON-safe state / fail-closed:** chunks round-trip through the redacted state as dicts
  (`chunks_from_state` tolerates malformed input); provider failures raise stable codes
  (`WORKFLOW_RETRIEVAL_FAILED`/`WORKFLOW_GENERATION_FAILED`/`AGENT_RETRIEVAL_FAILED`).
- **No regression:** existing workflow/agent/eval/gateway suites pass unchanged (deterministic
  default behavior preserved).

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Format / lint / type | `ruff format --check`, `ruff check`, `mypy apps config` | Pass — 298 files |
| Django check / drift | `manage.py check`; `makemigrations --check --dry-run` | Pass — no migration (behavioral wiring only) |
| Targeted P5 | `pytest apps/orchestration/tests/test_rag_steps.py apps/workflows/tests/test_generate_binding.py` | 10 passed |
| Affected apps | `pytest apps/workflows apps/agents apps/orchestration apps/evaluations apps/gateway` | 127 passed |
| Final SQLite | `pytest -q` | 464 passed, 18 skipped (pgvector) |
| Final PostgreSQL | `pytest -q --create-db` under `config.settings.local` + MCP/metrics flags | 480 passed, 2 skipped (off-PG guards) |

## Checks not run

- No live model/embedding endpoint exercised (deterministic defaults); real-provider agent/workflow
  RAG quality is unverified until a separately-approved egress rollout.
- No authored agent system prompt (P6): the agent still uses the user objective as the prompt.

## Final reviews

- Staff engineer: behavioral wiring only (no migration); one shared seam reused by both runtimes and
  the standalone `run_rag`; deterministic default and public contracts unchanged.
- Application security: retrieval stays server-side/deny-by-default (P4) — the workflow/agent pass no
  client filter; only JSON-safe chunk metadata is persisted in the redacted state; failures fail
  closed with stable codes; the prompt-injection boundary (system prompt separate from retrieved
  text; citations built after the model) is inherited from the P1/`run_rag` provider.
- SRE: opt-in real providers; stable failure codes; no new dependency or egress; CI hermetic.
