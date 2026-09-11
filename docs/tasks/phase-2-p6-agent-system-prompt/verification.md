# Verification: phase-2-p6-agent-system-prompt

## Status

**P6 Verified 2026-07-13.** Automated evidence only; deterministic providers remain the default so no
socket is opened and no live endpoint is called. The authored system prompt lights up on the same
governed generate seam (P1/P5) when a real provider is configured.

## Acceptance criteria mapping

- **Bounded, governed field:** `spec.system_prompt` is a non-empty string ≤ 8000 chars with no
  control characters; author-time validation via `compile_agent`
  (`test_invalid_system_prompt_is_rejected` covers empty/whitespace/non-string/overlong/control).
- **Pinned into the compiled agent:** `compile_agent` emits `system_prompt` in the checksummed
  config; it changes the agent checksum (`test_compiler_pins_authored_system_prompt`,
  `test_system_prompt_changes_the_checksum`); default is empty (`test_system_prompt_defaults_to_empty`).
- **Runtime uses it as the prompt:** `_respond` passes `config["system_prompt"]` to
  `generate_for_release` when present, else the objective
  (`test_respond_uses_authored_system_prompt`, `test_respond_falls_back_to_objective_without_system_prompt`).
- **Input, never authorization:** the tool proxy, approval, retrieval, and output-contract gates are
  untouched; the shared artifact validator still rejects inline secrets in the body.

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Format / lint / type | `ruff format --check`, `ruff check`, `mypy apps config` | Pass — 299 files |
| Django check / drift | `manage.py check`; `makemigrations --check --dry-run` | Pass — no migration |
| Targeted P6 | `pytest apps/agents/tests/test_system_prompt.py` | 10 passed |
| Affected apps | `pytest apps/agents apps/releases apps/evaluations` | 90 passed |
| Final SQLite | `pytest -q` | 474 passed, 18 skipped (pgvector) |
| Final PostgreSQL | `pytest -q --create-db` under `config.settings.local` + MCP/metrics flags | 490 passed, 2 skipped (off-PG guards) |

## Checks not run

- No live model endpoint exercised (deterministic default); real-provider persona behavior is
  unverified until a separately-approved egress rollout.
- No separate reusable prompt-artifact reference (inline `system_prompt` is used); a shared prompt
  artifact is a possible later enhancement, not required for P6.

## Final reviews

- Staff engineer: additive optional field + compiled-config key + a one-line runtime change; no
  migration; existing agents (no system prompt) behave identically.
- Application security: prompt is bounded, control-char-free, redaction-safe (shared inline-secret
  rejection), checksummed, and release-pinned; it is input to the model and never gates tools or
  decisions (those re-validate independently).
- SRE: no new dependency or egress; deterministic default keeps CI hermetic; reverting is trivial.
