# Threat Model: local Gemini model and embedding provisioning

Prompt/context and embedding inputs cross from AgentHub to Google's platform-managed endpoint
through the shared SSRF-safe HTTPS adapter. Host, path, model, and secret selection remain
platform-admin-controlled catalog data.

Controls include audited admin-only registration/grants, public-host validation, pinned-IP TLS,
redirect denial, bounded time/response sizes, namespaced environment secrets, exact dimension
validation, and no blind retry after an uncertain post-send failure.

Residual risks are approved-data processing by Google, spend/quota exhaustion, provider drift,
regional availability, credential rotation, and the staged rebuild still required before the new
embedding profile can back retrieval.
