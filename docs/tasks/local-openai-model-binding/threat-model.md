# Threat Model: local-openai-model-binding

## Assets
OpenAI API credential, prompts, retrieved document context, and provider responses.
## Actors
Local platform operator, application services, and OpenAI.
## Entry points
Ignored local environment file and Docker Compose service environment.
## Trust boundaries
Host to Docker Compose, application worker to the governed egress adapter, and adapter to OpenAI HTTPS.
## Data classifications
API credential is secret; prompts and retrieved chunks may contain tenant-confidential data.
## Authentication
Provider authentication uses the existing `secret:openai` environment resolver.
## Authorization
Existing platform profile, scenario, release, and runtime authorization remains authoritative.
## Tenant isolation
No tenant selection or database policy changes.
## External systems
OpenAI API through the existing validated HTTPS egress path.
## Abuse cases
Credential committed to Git, printed in logs, pasted into chat, or exposed through diagnostics.
## Failure cases
Missing/revoked credential, quota failure, provider timeout, or unset runtime provider must fail closed.
## Logging and audit risks
Environment or authorization headers must never be logged.
## Mitigations
Pass only an environment reference, keep `.env` ignored, refuse the exposed credential, retain bounded egress and profile gates, and inspect only boolean secret presence.
## Residual risks
Privileged local host/container users can inspect process environments; OpenAI receives model inputs when the real provider is enabled.
## Required security tests
Confirm no credential appears in Git diff or command output and unset configuration remains fail-closed.
