# Verification: sprint-4-rag-runtime

Record every executed command and its result. Do not infer success.

## Environment

- Python (venv): CPython 3.13.14. Django 5.2.16. No new dependency.
- Unit gate settings: `config.settings.test` (SQLite, LocMem cache).
- Integration: `config.settings.local` against real PostgreSQL 16 + pgvector 0.8.5.
- Date: 2026-07-10.

## Commands and results

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| Formatter | `ruff format --check .` | PASS | `107 files already formatted` (after applying format) |
| Linter | `ruff check .` | PASS | `All checks passed!` |
| Type-check | `mypy .` | PASS | `Success: no issues found in 109 source files` |
| Migration drift | `makemigrations --check --dry-run` | PASS | `No changes detected` (new apps have no models) |
| Unit tests (SQLite) | `pytest` | PASS | `65 passed` |
| Integration tests (PostgreSQL) | `DJANGO_SETTINGS_MODULE=config.settings.local pytest --create-db` | PASS | `65 passed` |

## Acceptance-criteria evidence (Sprint 4)

| Criterion | Evidence |
| --- | --- |
| Invalid context / non-active release rejected | `orchestration/tests/test_runtime.py::test_inactive_release_is_rejected` (RuntimeReleaseError); gateway `dispatch` verifies the ExecutionContext and maps `ExecutionContextInvalid` → `EXECUTION_CONTEXT_INVALID` (unit-covered in Sprint 3 context tests). |
| Output outside the contract never reaches the client | `..._test_output_contract_violation_returns_fallback_not_model_output` — the model's raw answer is absent; a server-controlled fallback is returned. |
| Below grounding threshold → policy fallback | `..._test_grounding_fallback_when_no_context`, `..._below_threshold` (fallback_used=true). |
| Grounded happy path with runtime citations | `..._test_grounded_completed_with_runtime_citations` (status completed; citations built by the runtime from retrieved chunks). |
| Citations-required policy | `..._test_citations_required_fallback_when_no_sources`. |
| Gateway returns real governed output | `gateway/tests/test_invoke.py` updated: invoke/query now return `completed` with an `output` object and `usage`. |

## Manual end-to-end (dev PostgreSQL, live HTTP)

Against the `customer-information` release (policy `customer_grounded`:
grounding.required, min_top_score 0.45; output contract `customer_answer`):

- Default retriever (no index yet) → `POST /v1/query` returns
  `{"status":"completed","output":{"answer":"Bu soru icin guvenilir bir yanit
  uretemedim; …","sources":[],"fallback_used":true}}` — grounding fallback, no
  hallucinated answer.
- With `RUNTIME_RETRIEVAL_PROVIDER=apps.retrieval.providers.DemoRetrievalProvider`
  (dev stub) → `{"status":"completed","output":{"answer":"Iade sureci: … 14 gun
  …","sources":[{"source_id":"mcm_content","source_uri":"https://kurum.example/iade",
  "title":"Iade Politikasi","score":0.82}],"fallback_used":false},"usage":{
  "input_tokens":1,"output_tokens":19}}` — grounded answer with a runtime-generated
  citation.

## Notes / skipped checks

- Model and retrieval providers are deterministic defaults; no real LLM/vector call
  is made. The real OpenAI-compatible model provider and the pgvector retriever plug
  in via `RUNTIME_MODEL_PROVIDER` / `RUNTIME_RETRIEVAL_PROVIDER` (Sprint 5+). Their
  timeouts, size limits, and PII redaction must be validated when integrated.
- `DemoRetrievalProvider` is a dev-only aid (canned passage), never for production.
- Prompt-injection defenses are minimal (untrusted-context marking); full policy
  enforcement (PII redaction, instruction-stripping, reranking) is later work.
- The release-bundle cache is keyed by the immutable release id + manifest sha, so it
  cannot serve stale content; the active-release pointer is read fresh per request.
