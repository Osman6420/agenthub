# Task Plan: Phase 2.9 Final Closure

## Task summary

Close the configured Gemini Studio acceptance blocker and the remaining browser-fixture,
observability, UX-copy/link, and local-topology quality gaps identified by the committed-build
post-completion audit.

## Scope

- Make the approved Gemini provider path reliably yield one strictly validated transient workflow
  candidate without weakening the untrusted-output boundary.
- Preserve exact scenario-editor authorization, explicit repair/accept persistence, bounded output,
  safe error mapping, and no prompt/response logging.
- Make the deterministic document browser fixture reflect a possible parsed/published/active
  lifecycle and render useful result metadata rather than technical null placeholders.
- Correct release-list navigation, exact missing-input wording, scenario-operator guidance, and
  missing-versus-invalid provider configuration copy.
- Reduce expected local authorization-denial traceback noise without weakening security audit events.
- Include worker presence/readiness in the documented post-development local gate.
- Re-run role/tenant denial, lifecycle, repository quality, real-browser, and one bounded live
  Gemini generate/inspect/repair/accept acceptance journey.

## Non-goals

- Change role definitions, authentication, tenant isolation, public API contracts, model token
  budgets, retry policy, connector egress, or production deployment configuration.
- Relax JSON/schema validation, trust provider-authored authorization data, auto-publish generated
  content, log model content, or blind-retry unknown outcomes.
- Reset the database or access production systems/data.

## Affected components

Builder AI authoring provider/parser and Studio UI; release/runs console navigation and copy;
deterministic browser-gate fixture; local logging/test settings; manual testing documentation and
Phase 2.9 planning evidence.

## Security and authorization requirements

- Server-side exact-object authorization remains authoritative and deny-by-default.
- Provider destination/profile remain deployment-controlled; user input cannot select either.
- Model output remains size-bounded, parsed as exactly one object, schema-validated, transient until
  explicit accept, and excluded from logs/evidence.
- Expected-denial log changes must not suppress security/business audit records or unexpected 5xx.

## Data, privacy, observability, and migration impact

Only synthetic local candidates/fixtures may be created. Secrets remain environment-only. No
migration is expected. Logging changes, if needed, are limited to framework request-traceback noise;
stable authorization/audit outcomes remain intact.

## Implementation steps

1. Trace the live Gemini response-format request and parser failure through current provider code.
2. Inspect browser fixture construction and affected UI routes/copy/logging configuration.
3. Add failing regression tests, then implement the smallest complete fixes.
4. Run focused SQLite/PostgreSQL/frontend/browser checks followed by repository quality gates.
5. Configure the approved local profile temporarily and complete one bounded live acceptance.
6. Restore temporary state, update verification/component status, and review the final diff.

## Test plan

- Provider request/response/parser fixtures for raw/fenced/malformed/oversized/error/real Gemini
  compatibility and single-call behavior.
- Exact editor allow plus viewer/unassigned/foreign denial and accept/repair authorization.
- Browser fixture lifecycle assertions, non-null retrieval metadata, release/runtime navigation and
  provider-copy tests.
- Ruff, mypy, Django/schema, frontend type/build/tests, SQLite/PostgreSQL and deterministic browser.
- Manual responsive/keyboard/console review and bounded live provider acceptance.

## Risks and rollback

The principal risk is accepting ambiguous or unsafe model output while trying to improve provider
compatibility. The rollback is confined to the provider normalization/request change and associated
UI/fixture/logging changes; no schema/data rollback is expected.

## Status

Completed and verified 2026-08-02. The configured Gemini Studio journey, deterministic role/UI
gate, complete SQLite/PostgreSQL suites, repository quality gates, worker-ready local topology, and
temporary-secret cleanup are recorded in `verification.md`.
