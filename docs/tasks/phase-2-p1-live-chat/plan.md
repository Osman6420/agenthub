# Task Plan: phase-2-p1-live-chat

## Task summary

Implement Phase 2 P1: a platform-managed immutable `ModelProfile` catalog, a profile-ID-only
shared SSRF-safe JSON egress adapter, and an opt-in OpenAI-compatible chat provider. Keep the
deterministic provider as the default and perform no live network call in CI or local verification.

## Background

Sprints 0–11 are verified. The runtime model seam currently resolves an artifact body containing
author-controlled endpoint/model/secret fields and defaults to `StubModelProvider`. ADR-0002 and
ADR-0005 replace that design with a platform-administered profile catalog and one centrally governed
stdlib transport. The owner explicitly approved beginning Phase 2 implementation on 2026-07-12.

## Scope

- Add an immutable, revisioned platform `ModelProfile` model and additive migration.
- Add a governed service/command to register profiles with platform-operator authorization and
  redacted audit.
- Change the `model_profile` artifact contract to reference a catalog profile by ID only.
- Add the shared JSON egress adapter using validated, IP-pinned, redirect-free HTTPS.
- Add an `OpenAICompatibleModelProvider` behind `RUNTIME_MODEL_PROVIDER`.
- Preserve the deterministic default and migrate GitOps/demo/test fixtures.
- Add security, authorization, migration, provider, redaction, and compatibility tests.

## Non-goals

Live endpoint/credential provisioning; opening production or test egress; embeddings; document
models/indexing/RLS; workflow/agent generation wiring; streaming, multimodal, realtime, or tool
calling; UI profile administration; adding the `openai` SDK.

## Acceptance criteria

- Artifacts/runtime accept a `ModelProfile` reference only and reject endpoint, URL, credential,
  secret-selection, or TLS fields.
- Only a platform-admin-authorized service path can create an immutable profile revision.
- The real provider resolves endpoint/model/secret only from the platform catalog and applies the
  shared egress controls from ADR-0005.
- Private/rebinding destinations, redirects, oversized/non-JSON/malformed responses, raw URLs from
  callers, and blind post-send retry fail closed with stable codes.
- Secrets, prompt, context, endpoint, and response text are absent from audit/log evidence.
- Default configuration remains deterministic and hermetic.
- Existing consumer `/v1/query` contract and governed fallback/output validation remain unchanged.

## Affected components

`apps.orchestration`, artifact validation/compiler fixtures, settings, GitOps/demo data, audit,
tests, migration, Phase 2/master/current-state documentation.

## Interfaces affected

Internal `model_profile` artifact schema changes from inline provider configuration to catalog
profile reference. New internal profile registration service/management command. No public API
contract change.

## Data impact

Add a platform-scoped immutable/revisioned profile table holding endpoint, model, secret reference,
timeouts, and response/token bounds. Prompt/response content is not persisted by P1.

## Security impact

Removes author-controlled model destinations and credentials. Centralizes SSRF, DNS-rebinding,
redirect, TLS, timeout, response-size, retry classification, and redaction controls. Full analysis
is in `threat-model.md`.

## Authorization impact

Profile creation is platform-admin-only and audited. Runtime reads active catalog profiles by ID;
tenant/artifact/request input cannot alter destination, secret, or TLS policy.

## Observability impact

Audit profile registration and stable egress outcomes using IDs, status, latency/count metadata
only. Never log prompts, responses, endpoints, headers, tokens, or secret references.

## Migration impact

One additive migration for the profile catalog. Artifact examples/fixtures migrate to a reference;
no destructive data migration and no public consumer schema change.

## Dependencies

No new production dependency. Reuse stdlib HTTPS and Sprint 9 egress/secret seams. Live egress
requires a separate environment-specific owner sign-off and is outside this task.

## Implementation steps

1. Capture baseline gates and affected-code inventory.
2. Add catalog model, validation, registration authorization/audit, and migration.
3. Change artifact validation/resolution to profile-ID-only.
4. Add shared egress adapter and OpenAI-compatible response parser/provider.
5. Update GitOps/demo/test fixtures and add negative/security tests.
6. Run SQLite/PostgreSQL and repository quality gates; update verification/current-state docs.
7. Review final diff as staff engineer, application-security engineer, and SRE; commit P1.

## Test plan

Happy path with injected offline transport; invalid profile/reference; non-platform registration;
immutability; unknown/disabled profile; cross-tenant steering attempt; private/rebinding DNS;
redirect; TLS/connection/timeout classifications; post-send unknown outcome with no retry; 429/503
without idempotency guarantee; response size/JSON/schema bounds; secret/prompt/endpoint redaction;
default deterministic compatibility; migration drift and PostgreSQL migration/test execution.

## Rollout plan

Ship additive catalog and opt-in provider while deterministic remains default. Populate approved
profiles through the governed operator command only after a separate environment-specific egress
approval. Enable the real provider by configuration after negative tests and network policy review.

## Rollback plan

Set `RUNTIME_MODEL_PROVIDER` empty to return immediately to the deterministic provider. The catalog
table is additive and inert. Do not delete profile/audit history; reverse the additive migration
only before data is relied upon.

## Risks

SSRF/DNS rebinding; credential leakage; prompt/response leakage; ambiguous retry causing duplicate
cost/divergent answers; provider response incompatibility; artifact migration breaking compiled
releases; audit persistence semantics; transport reuse accidentally weakening Sprint 9 controls.

## Open questions

Environment-specific endpoint/profile/secret values remain intentionally unresolved and require
separate approval before live egress. P1 will define the contract without provisioning them.

## Status

Implemented and Verified (2026-07-12). Live environment egress remains separately gated and was
not opened or exercised.

## Completion criteria

Acceptance criteria mapped in `verification.md`; applicable formatter, linter, type, migration,
SQLite/PostgreSQL, authorization, SSRF, redaction, and final-diff reviews pass.
