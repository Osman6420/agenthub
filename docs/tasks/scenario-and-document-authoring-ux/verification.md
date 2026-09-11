# Verification — scenario and document authoring UX

Date: 2026-08-07. Branch: `feat/foundation-sprint-0-1`.

## Static checks

| Command | Result |
| --- | --- |
| `.venv\Scripts\ruff.exe format --check apps` | pass |
| `.venv\Scripts\ruff.exe check apps` | `All checks passed!` |
| `.venv\Scripts\mypy.exe apps` | `Success: no issues found in 468 source files` |
| `.venv\Scripts\python.exe manage.py check` | no issues |
| `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` | `No changes detected` |

**No migration.** Every change is behavioural or presentational; `branch_document_set_version`
uses the existing version/membership tables.

## Tests — SQLite (`config.settings.test`)

Full suite: **1276 passed, 61 skipped**, 0 failed (257s).

## Tests — PostgreSQL (`config.settings.local`, `--create-db`, pgvector Compose)

Scope `apps/console apps/documents apps/ingestion apps/releases apps/evaluations apps/gateway`:
**648 passed, 2 skipped**, 0 failed (427s). Both skips assert the off-PostgreSQL guard itself.

Required environment: `MCP_ENABLED=true`, a non-empty `METRICS_BEARER_TOKEN`, **and** the MinIO
variables (`OBJECT_STORE_ENDPOINT=http://localhost:9000`, `OBJECT_STORE_BUCKET=agenthub`,
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY=minioadmin`).

## Frontend (Node v20 / npm 10)

| Command | Result |
| --- | --- |
| `tsc --noEmit` | pass |
| `vitest` | **53 passed** (12 files) |
| `vite build` | pass |

The generated bundle under `apps/builder/static/builder/` is gitignored and was rebuilt. A
stale bundle previously hid a shipped fix (the Studio back link), so rebuilding after any
frontend change is not optional.

## New tests

- `apps/console/tests/test_profile_fields.py` (6) — the offered defaults validate; every
  offered choice is one the validator allows; the stated bounds are the enforced bounds; the
  hybrid-only weights are marked conditional and the validator rejects them elsewhere; every
  field carries actionable help; a type without a description reports as absent.
- `apps/releases/tests/test_lifecycle.py` (+3) — **a stub answer may be evaluated but never
  served**: promotion *and* canary are refused with `MODEL_PROVIDER_NOT_CONFIGURED` and the
  denial is audited; the same release promotes once a provider is configured; a non-generating
  release needs none.
- `apps/gateway/tests/test_canonical_api.py` (+2) — a missing key is named as a key problem; a
  suspended runtime is not reported as a header problem and answers 503.
- `apps/console/tests/test_document_sets_console.py` (+3) — a published version seeds the next
  one with its exact membership while staying frozen, audited; branching refuses while a draft
  is open; cross-tenant branch returns 404.
- `apps/console/tests/test_document_workspace_console.py` (+1) — a new profile is **named**,
  not identified: the server derives a collision-free logical id and purpose.
- `apps/console/tests/test_scenario_step_actions.py` (+2) — every generated curl example
  carries `Idempotency-Key` and the reuse rule is stated; the one-off answer returns to the
  page that asked, keeps the question editable, and does not survive a reload.
- `apps/evaluations/tests/test_scenario_test_questions.py` (+5) — one term per line, all
  required, on both consumers; only `contains` splits; too many terms is refused with a stable
  code; terms and the citation flag round-trip into the editor; a failing term is named in the
  assertion outcome.
- `frontend/src/__tests__/app_deeplink.test.tsx` (+1) — Studio offers a way back to the
  scenario it was opened from.

Updated to intended new behaviour (**not weakened**):
`test_scenario_setup_steps.py` (steps 4 and 5 swapped), `test_console_ux_overhaul.py`
("Diğer sürümler" replaces the misleading "Geçmiş sürümler"), `test_document_workspace_console.py`
(the deprecated retrieval picker is gone; the stored pin is asserted on the preparation profile
instead of in the HTML), `test_scenario_step_actions.py` (promotion message wording).

## Live evidence (running Compose stack)

```
profil varsayılanları → validate_body OK for chunking_profile and retrieval_profile
"bizans\nosmanlı"     → [answer_contains "bizans", answer_contains "osmanlı"]
İstanbul set v2 (promotable) → branch → draft v3 with 1 document copied
                              source still promotable (frozen)
```

The verification draft was removed afterwards, because the single-open-draft rule would
otherwise have blocked the owner from branching.

## Not run / open

- **Mandatory browser gate** (`manual-testing-guide.md` §10) — the blocker for `Verified`. It
  now also covers: the reordered steps, the multi-term expected-answer field, the answers panel,
  the in-page one-off question, "Diğer sürümler" + branching, the rendered profile forms, and
  the info controls. Matched permitted/forbidden identities and cross-tenant probes included.
- **The staged-index report is still unreproduced.** İstanbul set v2 is `promotable` with no
  index, no preparation profile and no build job; the web log had rotated, so the original
  attempt cannot be inspected. The rejection path now names the failing fields, so a repeat
  will say why. This needs a live attempt with the owner.
- Redis and MinIO remain unexercised by the automated suite (pre-existing).

## Residual risks

Recorded in [`threat-model.md`](threat-model.md#residual-risks). The material ones:

- `MODEL_PROVIDER_NOT_CONFIGURED` keys on the deployment setting, not on whether the pinned
  profile is reachable; a configured but broken provider still promotes and fails at request
  time.
- Upstream provider failures remain collapsed into one code and misclassified as transient
  (carried over from the previous task, still unapproved).
- The generated frontend bundle is gitignored; a stale bundle can hide a shipped fix.
