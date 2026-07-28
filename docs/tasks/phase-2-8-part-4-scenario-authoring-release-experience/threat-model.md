# Threat Model: Phase 2.8 Part 4 — Scenario authoring and release experience

## Assets and actors

Scenario/project tenancy, mutable drafts, immutable artifacts/releases, aliases, AI descriptions and
candidates, model-profile provenance and release authority. Actors are scenario authors, release
managers, auditors, platform/org admins, malicious members and the configured model provider.

## Entry points and trust boundaries

Project-context scenario create, preset choice, Studio/AI APIs, dependent artifact selectors,
compile/release actions and invocation-copy surfaces. Browser IDs, query strings, preset names, AI
output and artifact selections are untrusted; target objects, compiled contracts and role predicates
are authoritative server-side.

## Abuse and failure cases

| Threat | Required mitigation |
| --- | --- |
| Foreign project injected into create | Project comes from authorized route target; no submitted parent field |
| Preset bypasses compiler or activates release | Create draft through canonical service; publish/promote remain separate governed actions |
| Artifact dropdown leaks another tenant | Server-scoped bounded options and generic foreign-ID denial |
| Artifact descriptions leak bodies, prompts or secrets | Bounded plain text, no body-derived defaults, output encoding and no description payloads in logs/audit |
| Free-text/mismatched manifest role | Closed role/type contract and exact published version validation |
| “Latest” changes between review and compile | Persist exact version/checksum selection; revalidate under transaction |
| AI prompt/output leaks content | Bounded context, approved provider, no logs/audit content, redacted errors |
| AI output introduces tool/secret/code | Canonical DSL validation, inline-secret denial, closed node/action schemas |
| AI generation auto-publishes | Candidate is transient; explicit acceptance creates/updates draft only |
| Audit outage leaves mutation | Existing fail-closed audit/transaction behavior |
| Curl example encourages unsupported route/mode | Generate from compiled execution modes and canonical alias |

## Residual risks and required tests

Logical descriptions can become stale, version descriptions can be misleading and AI provider
configuration remains environment-specific. Require length/encoding tests, cross-tenant/role/disabled
tests, selector forgery, compile checksum, candidate validation, rate limits, audit rollback, content
redaction, prompt-injection samples, guide/compiler parity and accessible keyboard/browser journeys.
