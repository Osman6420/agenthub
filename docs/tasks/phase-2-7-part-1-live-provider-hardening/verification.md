# Phase 2.7 Part 1 — Verification

Environment: Windows, repo `.venv` (Python 3.13). Static/unit gates under
`DJANGO_SETTINGS_MODULE=config.settings.test` (in-memory SQLite). Live-provider checks under
`config.settings.local` against Compose PostgreSQL/pgvector/Redis/MinIO with a real Gemini
`ModelProfile` and `MODEL_SECRET_GEMINI` injected from the environment (never committed).

## Automated gates (all pass)

| Gate | Command | Result |
| --- | --- | --- |
| Format | `ruff format --check apps` | 400 files already formatted |
| Lint | `ruff check apps` | All checks passed |
| Types | `mypy apps` | no issues in 400 source files |
| Django check | `manage.py check` | no issues |
| Migration drift | `manage.py makemigrations --check --dry-run` | No changes detected |
| Full suite | `pytest` (config.settings.test) | **942 passed, 37 skipped** (skips = PostgreSQL-only RLS/pgvector) |

Targeted regression tests confirmed:
- `test_openai_provider_sends_user_turn_when_context_is_empty` — empty context ⇒ single `user`
  message (no `system`-only request).
- `test_model_provider_failure_marks_run_failed` — a `ModelProviderError` in the agent loop ⇒ run
  ends `FAILED` with `error_code == "AGENT_MODEL_FAILED"`.

## Live Gemini evidence (config.settings.local, real key)

- **Root cause proof:** a raw `POST /v1beta/openai/chat/completions` with a `system`-only message
  returned HTTP 400 `contents is not specified`; with a `user` turn it returned HTTP 200.
- **RAG end-to-end:** `POST /v1/query` (scenario `customer-information`, release pins the Gemini
  `model_profile` + an authored prompt) returned a real Gemini answer, `fallback_used=false`,
  correct Turkish UTF-8 (verified byte-accurate, no mojibake).
- **Agent end-to-end:** `POST /v1/invoke` (scenario `assistant`, release pins the Gemini
  `model_profile` + authored `system_prompt`) → async run `completed` with a real Gemini answer.
- **Failure path:** before the fix, an agent run with an invalid/absent model profile stayed
  `running`; after the fix it terminates `failed` / `AGENT_MODEL_FAILED` (also cancel-cleanable via
  `DELETE /v1/runs/{id}`).

## Operational note

The local DB required applying pending migrations to reach the current branch state; a divergent
`workflows` history (an orphaned `0004_workflowwait_*` row from a worktree branch vs the trunk's
renumbered `0005`) was reconciled non-destructively with `migrate workflows 0005 --fake` followed
by `migrate` (0006–0008). `showmigrations` and `makemigrations --check` are clean afterward.

## Residual risk / not run

- PostgreSQL-profile full run not repeated for this part (changes are provider/runtime logic with
  no schema or RLS impact; the affected unit tests pass on SQLite).
- The redacted-runtime-input limitation (agent objective reaches a real model as `[redacted]`) is
  recorded as a follow-up, not fixed here.
- No load/soak; single live Gemini calls only.

## 2026-07-22 review correction

- Empty-context requests now contain the authored `system` message plus a fixed user turn.
- The provider regression test asserts both Gemini-compatible user content and preservation of the
  system-prompt role boundary.
- Included in the 2026-07-22 targeted regression run: **55 passed, 2 PostgreSQL-only skipped**.
