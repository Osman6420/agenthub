# Task Plan: local-openai-model-binding

## Task summary
Allow the supported local Compose stack to pass an operator-supplied OpenAI model secret to application roles so the existing governed OpenAI model profile can use the real provider.
## Background
The catalog contains an active OpenAI model profile, but `RUNTIME_MODEL_PROVIDER` is unset and the Compose environment does not pass `MODEL_SECRET_OPENAI`. A credential pasted into chat is considered compromised and will not be used.
## Scope
Add the missing optional environment pass-through to the canonical local Compose file and verify the rendered configuration without using a real secret.
## Non-goals
Do not store, rotate, validate, or expose a real API key. Do not alter model profiles, authorization, egress validation, or production deployment manifests.
## Acceptance criteria
- Every local application role inheriting the shared environment can receive `MODEL_SECRET_OPENAI`.
- The web service's explicit environment override can also receive it.
- An unset secret remains empty and the runtime continues to fail closed.
- No secret value is committed or printed.
## Affected components
Local Docker Compose configuration.
## Interfaces affected
Optional local environment variable `MODEL_SECRET_OPENAI`.
## Data impact
None.
## Security impact
Adds a secret injection path using the existing environment-based resolver; no secret value is stored in source.
## Authorization impact
None. Model-profile authorization and release gates remain unchanged.
## Observability impact
No logging changes; secret values must remain absent from output.
## Migration impact
None.
## Dependencies
Existing `OpenAICompatibleModelProvider` and model environment secret resolver.
## Implementation steps
1. Add optional Compose pass-through in the shared and web-specific environments.
2. Render/validate Compose with a synthetic placeholder and inspect only variable presence, never value.
3. Require the user to revoke the exposed key and enter a fresh key locally outside chat.
## Test plan
Run `docker compose config` with a synthetic value and verify the variable name exists in relevant service environments. Run Django system checks.
## Rollout plan
Operator sets the provider class and fresh secret in an ignored local `.env`, then recreates application services.
## Rollback plan
Unset `RUNTIME_MODEL_PROVIDER` and `MODEL_SECRET_OPENAI`, then recreate application services.
## Risks
Environment variables are visible to sufficiently privileged local container operators. A leaked key must be revoked before use.
## Open questions
Fresh credential creation and billing/quota readiness remain with the user.
## Status
Completed

## Completion criteria
Compose pass-through is implemented. The user rotated and supplied a fresh key through the ignored local environment file, all application roles were recreated, and a redacted live provider smoke test passed.
