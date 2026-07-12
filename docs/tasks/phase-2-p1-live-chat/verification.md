# Verification: phase-2-p1-live-chat

## Status

Verified 2026-07-12. Implementation kickoff was approved; live environment egress was not approved,
configured, or exercised.

## Acceptance criteria mapping

- Profile-ID-only artifacts: canonical validator rejects every field except UUID `profile_id`;
  GitOps and demo fixtures migrated.
- Platform governance: only a Django superuser/platform admin can register an immutable revision;
  denial and success are audited without endpoint/secret content.
- Safe egress: catalog-resolved HTTPS only, public-unicast DNS validation, pinned-IP TLS transport,
  redirect denial, timeout and response-size caps, late `MODEL_SECRET_*` resolution.
- Provider: opt-in OpenAI-compatible chat provider parses bounded responses and keeps system
  instructions separate from untrusted retrieved text; deterministic remains the default.
- Failure handling: unknown/disabled profile, private DNS, redirect, malformed JSON, malformed model
  response and post-send timeout fail closed; timeout maps to `OUTCOME_UNKNOWN` and is not retried.
- Compatibility: public `/v1/query` and release contracts are unchanged; all existing suites pass.

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Baseline format | `.venv\\Scripts\\python.exe -m ruff format --check .` | Pass — 254 files formatted |
| Baseline lint | `.venv\\Scripts\\python.exe -m ruff check .` | Pass |
| Baseline type check | `.venv\\Scripts\\python.exe -m mypy apps config` | Pass — 253 files |
| Baseline Django | `manage.py check`; `makemigrations --check --dry-run` | Pass |
| Baseline SQLite | `pytest -q` | 365 passed, 2 skipped; one setup error from inaccessible global Windows pytest temp directory, not an application failure |
| Targeted P1 | `pytest -q apps/orchestration/tests ...` | Pass — 35 tests, then 14 orchestration tests after added negatives |
| Final lint/type/Django/migration | Ruff, mypy, `manage.py check`, `makemigrations --check --dry-run` | Pass — Ruff clean; mypy 262 files; no migration drift |
| Final SQLite | `pytest -q --basetemp .tmp/pytest-p1-final-sqlite` | Pass — 375 passed, 2 PostgreSQL-only skipped |
| Final PostgreSQL | `pytest -q --create-db --basetemp .tmp/pytest-p1-final-postgres` with local settings and MCP/metrics flags | Pass — 377 passed |
| Local Markdown links / diff whitespace | local-link scan; `git diff --check` | Pass |

## Security and authorization evidence

Negative tests prove non-platform registration denial, append-only audit outcome, profile
immutability, inline endpoint rejection, unknown profile denial, private-IP DNS rejection before
transport, redirect denial, malformed JSON rejection, and post-send timeout as `OUTCOME_UNKNOWN`.
Audit assertions confirm endpoint and secret reference are absent. No real socket is opened: every
transport test injects an offline resolver/connection.

## Migration verification

`orchestration.0001_modelprofile` is additive. Migration drift is clean and the full PostgreSQL
`--create-db` suite applies it successfully.

## Checks not run

- No live chat endpoint, credential, DNS, TLS, network-policy, cost, latency, or provider-specific
  compatibility test: environment-specific egress is not approved.
- Frontend gates: no frontend files changed.
- Container/secret/dependency scanners: no dependency, image, or lockfile changed.

## Final reviews

- Staff engineer: change is confined to P1; deterministic and public contracts remain compatible.
- Application security: author-controlled endpoint/secret removed; platform authorization, SSRF,
  pinned-IP TLS, redaction, bounds, and no-blind-retry behavior are tested.
- SRE: opt-in rollback is configuration-only; additive catalog is inert when disabled; stable
  failure codes and bounded transport are present. Live rollout still requires endpoint/network
  approval and operational smoke evidence.

## Remaining risks

OpenAI-compatible providers vary in response and token semantics. The stdlib adapter currently
implements bounded non-streaming chat only. Platform-admin compromise remains powerful. Live
network-policy, TLS-chain, provider-rate-limit and cost behavior remain unverified until separately
approved rollout.
