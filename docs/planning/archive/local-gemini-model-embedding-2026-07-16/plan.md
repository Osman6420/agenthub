# Task Plan: local-gemini-model-embedding

Provision live Gemini chat and embedding through the existing governed profile catalogs without
storing credentials in source control.

## Outcome

- Added deployment environment switches for the existing real providers.
- Registered immutable Gemini chat and 3072-dimension `halfvec` embedding profiles.
- Granted embedding access to `demo`, `ahmet`, and `mcm`.
- Restarted local web/runtime worker processes with environment-injected credentials.
- Verified bounded live calls through AgentHub's governed provider seams.

No dependency, public contract, authorization, tenant-isolation, migration, reindex, index/release
promotion, production deployment, or source-controlled credential was added.

## Rollback

Clear `RUNTIME_MODEL_PROVIDER` and `RUNTIME_EMBEDDING_PROVIDER` and restart. Preserve immutable
catalog and audit history.

## Status

Implemented and verified on 2026-07-16. See [verification](verification.md).
