# Verification: phase-2-9-part-5-exact-ai-authoring-provider-reliability

## Result

Implemented and automated-verified 2026-08-02. Exact scenario editor authority now drives the
Studio AI affordance, while every API remains independently authorized. The OpenAI-compatible
provider requests one JSON object and the bounded parser accepts only raw JSON or one complete
`json` fence before canonical validation. No candidate is persisted or published without explicit
accept.

Operational acceptance is not complete: the running local deployment reports
`profile_configured=False`, `active_profile=False`, and `provider_configured=False`. No secret,
endpoint, profile ID, prompt, or response was inspected or emitted, and no live egress was attempted.

## Automated evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Python | Passed | 10 passed: parser, exact Studio bootstrap, JSON mode, transport failure, and outcome-unknown |
| Broad affected SQLite | Passed | 73 passed across builder API/context/authorization, provider, and Scenario Studio bootstrap |
| Broad affected PostgreSQL/RLS | Passed | Same 73 tests passed against real PostgreSQL using the existing test database with `--reuse-db`; no reset/create |
| Full repository SQLite | Passed | 1,089 passed, 61 PostgreSQL-only skips |
| Frontend target | Passed | 9 tests across AI panel and exact-scenario deep link; TypeScript typecheck passed |
| Frontend full/build | Passed | 31 tests; production Vite build and TypeScript typecheck passed |
| Django/schema | Passed | `manage.py check` clean; `makemigrations --check --dry-run` reports no changes |
| Ruff/diff | Passed | Changed Python formatted/linted; `git diff --check` clean |
| Target mypy | Baseline-limited | No Part 5 error; four unchanged imported baseline errors remain in assignment/tenancy/forms |

The frontend suite emits one pre-existing React `act(...)` warning in the transient-candidate test;
the assertion passes and Part 5 adds no new warning category.

## Authorization and security evidence

- The server resolves the exact scoped scenario before emitting `can_author_scenario`; an exact
  editor receives true while an organization administrator without editor responsibility receives
  false. API fixtures also retain viewer 403 and foreign/unassigned non-disclosure behavior.
- Provider requests keep system/context/user messages separated and now include
  `response_format={"type":"json_object"}`. The caller still cannot supply profile or destination.
- Raw, LF/CRLF fenced, malformed, prose-wrapped, wrong-language, multiple-fence, non-object, deep,
  and oversized fixtures fail or pass as intended. Only one complete JSON fence is normalized.
- Transport failure and outcome-unknown fixtures each prove one provider call and stable safe error
  mapping. The UI explicitly forbids blind replay for outcome unknown and never renders raw provider
  detail.
- Existing audit tests prove descriptions/candidates/prompts/responses remain absent; generation is
  transient and explicit accept remains a separate exact-author mutation without auto-publish.

## Operational and manual evidence

- Compose PostgreSQL, Redis, MinIO, and web were started without reset; health returned HTTP 200.
- Safe boolean-only preflight inspection found no configured AI authoring profile/provider. A live
  Gemini request would therefore be impossible and was not attempted.
- Manual in-app browser acceptance was not available in the final verification session. Frontend
  rendering and interaction are covered by Vitest, server bootstrap tests, and production build,
  but visual/manual acceptance remains open.

## Changes not made

No dependency, migration, public API, role/capability, authentication, secret, destination, network
policy, model token budget, retry policy, or automatic publication change. No production system or
data was accessed.

## Remaining acceptance

Configure the already approved immutable model profile and provider in a controlled local/staging
deployment, then perform exactly one bounded synthetic Gemini generate/inspect/repair/accept smoke.
Record only status, stable error category, request ID, token/byte counts, and persistence outcome.
Never record prompt/response/candidate content or secret/profile destination values. Verify the exact
editor sees the panel and viewer/unassigned actors do not before archiving this task.
