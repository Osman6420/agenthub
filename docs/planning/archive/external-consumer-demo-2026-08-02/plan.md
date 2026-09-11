# Task Plan: external-consumer-demo

## Task summary
Create a standalone localhost demo client, comprehensive served scenarios, and least-privilege consumers that exercise AgentHub through its public consumer APIs.

## Background
The demo must look like an external integration, not an AgentHub console feature. It must include a real Wikipedia-backed RAG question-answer flow and disclose the local operator login created for the demo.

## Scope
- Add an idempotent local-only bootstrap command for demo operators, scenarios, releases, document/index data, consumers, grants, and one-time credentials.
- Add a standalone HTML/CSS/JavaScript demo served by its own localhost process.
- Exercise synchronous OpenAI-compatible requests, background runs and polling, authorization isolation, and RAG citations.
- Add automated tests and operator documentation.

## Non-goals
- No production endpoint, authentication, authorization, tenant, migration, or dependency changes.
- No browser storage of bearer tokens and no source-controlled secrets.
- No automatic production deployment or destructive reset.

## Acceptance criteria
1. Several representative scenarios are active and callable through `/v1/responses` or `/v1/chat/completions`.
2. At least three REST consumers have different, least-privilege scenario bindings.
3. A real Wikipedia page is downloaded with a fixed allowlisted HTTPS origin, stored as a managed document, indexed, bound, granted, and used for grounded Q&A.
4. Gemini is selected through the existing immutable model-profile and environment-secret seams; the key is never persisted or printed.
5. The standalone demo page can run all scenarios together, poll background runs, display safe output/citations, and demonstrate a denied cross-consumer call.
6. A local operator username/password and consumer credentials are generated/reported once by bootstrap.
7. Unit/integration checks and manual browser verification pass.

## Affected components
- `apps/console/management/commands/`: local demo bootstrap.
- `apps/console/tests/`: bootstrap authorization/data tests.
- `examples/external-consumer-demo/`: standalone demo server and UI.
- `docs/`: setup, threat model, and verification evidence.

## Interfaces affected
Existing public interfaces only: `/v1/responses`, `/v1/chat/completions`, `/v1/runs/{id}`. No HTTP contract changes. The internal model-provider seam gains an optional untrusted user-query field so RAG generation answers the retrieval question instead of merely summarizing the selected passage.

## Data impact
Creates local `external-demo` tenant data, immutable artifacts/releases, a Wikipedia-derived document/index, grants/bindings, consumers, hashed token rows, and audit events. Re-running is idempotent except explicit token rotation.

## Security impact
Bearer tokens remain local and are never committed. Wikipedia retrieval is HTTPS-only, host allowlisted, response-size bounded, timeout bounded, and redirects denied. Demo server binds to loopback and returns restrictive security headers.

## Authorization impact
Consumers receive scenario-specific `workflow_run` bindings only. Document retrieval requires both consumer and scenario grants. Negative isolation is explicitly tested.

## Observability impact
Existing gateway/run/audit events are reused. Bootstrap output contains credentials by explicit local-demo design and must not be copied to shared logs.

## Migration impact
None.

## Dependencies
No new production or development dependency. Uses Python standard library and existing repository services.

## Implementation steps
1. Confirm runtime/provider configuration and exact service APIs. Live evidence found that the existing generate seam omitted the retrieval query from the model turn; include it as untrusted user content without changing authorization or the public contract.
2. Implement bootstrap and standalone demo assets/server.
3. Add focused tests for data topology, idempotence, least privilege, URL controls, and secret redaction.
4. Bootstrap live data, run automated checks, and verify all scenarios in the standalone browser page.
5. Record evidence and final diff review.

## Test plan
- Focused Django tests for bootstrap helpers and resulting bindings/grants/releases.
- Static/unit checks for the standalone server and JavaScript where practical.
- Live HTTP success, background polling, denied alias, and Wikipedia grounding checks.
- Browser visual/interaction verification on the standalone localhost origin.

## Rollout plan
Local development only: run the bootstrap, inject existing Gemini secret into Compose if absent, recreate only application roles if required, then launch the loopback demo server.

## Rollback plan
Stop the standalone server. Demo data is isolated under the `external-demo` organization and can be removed only with a separate explicit destructive action; no automatic deletion is provided.

## Risks
- Third-party Wikipedia/Gemini availability can make live setup fail.
- Browser-to-API CORS is intentionally avoided by a same-origin local reverse proxy; the proxy must restrict upstream paths and headers.
- Plaintext demo credentials are sensitive while active; disclosure is limited to one-time local bootstrap output/config with restrictive git-ignore coverage.

## Open questions
None; the user explicitly authorized creation of local users, consumers, scenarios, and use of the identified local Gemini key if needed.

## Status
Implemented and verified on 2026-08-02.

## Completion criteria
All applicable Definition of Done evidence is recorded in `verification.md`, including three-role final review.
