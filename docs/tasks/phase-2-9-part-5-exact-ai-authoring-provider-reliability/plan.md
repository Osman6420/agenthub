# Task Plan: phase-2-9-part-5-exact-ai-authoring-provider-reliability

## Task summary

Complete Phase 2.9 Part 5 by exposing Studio AI authoring to an exact scenario editor and making
OpenAI-compatible provider JSON responses reliably produce a validated, transient candidate.

## Scope

- Carry the server-authoritative exact scenario author decision into the Studio bootstrap and gate
  the AI panel on that decision instead of organization-level write state.
- Keep the builder candidate, repair, and accept APIs independently authorized against the exact
  persisted organization/project/scenario hierarchy.
- Request JSON-object response mode from the existing OpenAI-compatible provider and normalize only
  a bounded raw JSON object or one unambiguous whole-response JSON markdown fence before strict
  parsing and canonical validation.
- Return actionable, non-sensitive guidance for malformed output, provider failure, timeout, and
  outcome-unknown cases; never blindly retry an unknown post-send outcome.
- Add exact allow/deny, parser/provider, frontend, PostgreSQL, browser, and one approved synthetic
  live Gemini smoke record without prompt, response, endpoint, or secret content.

## Non-goals and approval boundaries

- No new dependency, model/profile schema, role/capability, authentication, public API, secret,
  network policy, provider destination, token budget, or automatic publish behavior.
- No broad organization authoring authority and no authorization decision from model output.
- No retry after an outcome-unknown provider call. The live smoke is one bounded synthetic request
  through the already approved local profile and existing egress controls.

## Trust boundaries and authorization

The browser bootstrap is an affordance, not authority. The server resolves the scenario through the
requester's scoped query and computes exact editor authority from persisted responsibility rows. All
candidate, repair, and accept POSTs re-resolve organization, project, and scenario and enforce the
same central predicate. Provider output is untrusted bytes and cannot select identities, scopes,
destinations, permissions, publication, or release state.

## Data and operational impact

No migration or new durable data. Successful generation remains transient until explicit accept;
accept creates only the existing mutable draft. Audit stores stable IDs, byte/token counts, contract
checksums, result category, and validity, never prompts, responses, candidate bodies, endpoints, or
secret references. Existing profile disable is the rollback/kill switch.

## Implementation steps

1. Confirm Studio bootstrap, API authorization, provider payload, parser, audit, and frontend error
   paths against the Part 5 acceptance criteria.
2. Add the exact-scenario bootstrap decision and gate only exact-context AI authoring affordances.
3. Add JSON response mode and strict bounded raw/whole-fence normalization with matched fixtures.
4. Add actionable error guidance without automatic retry or content disclosure.
5. Run focused/backend/frontend/PostgreSQL and browser/live synthetic verification; update current
   behavior docs, archive evidence, review the final diff, and commit.

## Rollback

Revert the bootstrap/frontend/provider/parser changes. Unsetting `AI_AUTHORING_MODEL_PROFILE_ID` or
disabling its immutable profile immediately hides/denies new generation without changing drafts.

## Risks

Role confusion, forged scenario context, prompt injection, ambiguous JSON extraction, oversized or
deep output, candidate auto-persistence, secret/content logging, provider incompatibility, duplicate
spend after uncertain outcomes, and misleading retry guidance. Controls are exact server-side
authorization, strict one-object parsing, byte/depth/schema limits, canonical compilation, transient
state, redacted audit, response-mode fixtures, and no blind replay.

## Status

Implemented and automated-verified 2026-08-02. The approved live synthetic Gemini smoke and manual
browser acceptance remain pending because the running deployment has no AI authoring profile or
provider configured. See `verification.md`.
