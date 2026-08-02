# Verification: phase-2-9-part-5-exact-ai-authoring-provider-reliability

## Result

Completed and verified 2026-08-02. Exact scenario editor authority now drives the
Studio AI affordance, while every API remains independently authorized. The OpenAI-compatible
provider requests one JSON object and the bounded parser accepts only raw JSON or one complete
`json` fence before canonical validation. No candidate is persisted or published without explicit
accept.

The approved bounded live Gemini Studio journey passed. Generate and repair both returned valid
schema-constrained candidates, and explicit accept created one existing mutable draft. No secret,
endpoint, prompt, response, or candidate content was emitted into evidence.

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

- The approved secret was read environment-only and injected temporarily into the local web
  service. Generate returned a valid transient candidate (2,320 input tokens, 72 output tokens,
  268 bytes); repair remained valid (2,539 input tokens, 74 output tokens, 268 bytes); accept created
  one workflow draft at revision 1.
- Safe request identifiers were `req_2b42150b81fe4beda94b04af27031af6` and
  `req_424599b89f3e4697a62af9acb102e0e7`. Prompts, responses and candidate bodies were not recorded.
- The exact scenario editor saw and used the panel in the in-app browser; server tests and the
  deterministic browser gate retained viewer, unassigned, sibling-scenario and foreign-tenant
  denial coverage.
- The temporary identity was deactivated, its password made unusable, all temporary provider/profile
  settings were cleared, and web was recreated. Health returned HTTP 200.

## Changes not made

No dependency, migration, public API, role/capability, authentication, secret, destination, network
policy, model token budget, retry policy, or automatic publication change. No production system or
data was accessed.

## Remaining acceptance

None for Phase 2.9 Part 5. Production grants, provider-scale behavior, cost monitoring and hosted
deployment topology remain normal rollout concerns rather than local product-completion blockers.
