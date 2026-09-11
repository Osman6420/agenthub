# Threat Model: Phase 2.9 Final Closure

## Assets and boundaries

- Provider secrets, profile/destination governance, prompts and model output.
- Tenant/scenario/draft/release/run/document metadata and exact-role authorization.
- Browser as an untrusted client; server services and PostgreSQL RLS as enforcement layers.
- Framework application logs versus durable security/business audit events.

## Threats

- Permissive JSON cleanup accepting prose, multiple objects, wrong language or oversized output.
- Blind provider replay causing duplicate cost or unknown persistence outcome.
- Generated content being persisted/published without explicit authorized acceptance.
- UI copy/navigation exposing or implying actions beyond exact responsibility.
- Test fixtures bypassing lifecycle invariants and giving false-positive browser evidence.
- Logging changes hiding real authorization failures, attacks or unexpected server faults.
- Secrets, prompt/response content or document data leaking into test evidence.

## Controls

- Exactly-one-object bounded parsing and canonical schema validation; no general JSON extraction.
- One-call assertions, safe stable error categories and no automatic retry after send.
- Exact server authorization for generate/repair/accept plus matched denial tests.
- Normal domain lifecycle services in fixtures or explicit invariant assertions.
- Narrow framework log filtering only for expected response warnings; durable audit tests retained.
- Boolean/status/count-only live evidence and immediate temporary-config cleanup.

## Residual risk

Provider behavior can change independently. Production grants, scale, connector egress and hosted CI
remain deployment acceptance concerns even after the local Phase 2.9 gate closes.
