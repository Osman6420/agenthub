# Task Plan: embedding-halfvec-4000-truncation

## Task summary

Allow an explicitly configured `halfvec(4000)` embedding profile to accept provider vectors longer
than 4,000 components by retaining the first 4,000 components before normalization and storage.

## Background

pgvector HNSW supports at most 4,000 dimensions for `halfvec`. The current provider adapter rejects
every response whose length differs from the immutable profile dimension. Some governed providers
return vectors longer than 4,000 even though AgentHub must persist a 4,000-dimensional store.

## Scope

- Add bounded response adaptation for active `halfvec(4000)` profiles only.
- Preserve exact-dimension validation for every other vector/halfvec profile and for short output.
- Normalize the retained vector after truncation.
- Update tests and durable architecture documentation.

## Non-goals

- No change to pgvector/HNSW limits or physical store layout.
- No registration of profiles whose stored `dimensions` value exceeds 4,000.
- No automatic mutation or rebuild of existing embedding profiles/indexes.
- No change to authorization, tenant isolation, provider egress, promotion, or retention.

## Acceptance criteria

1. A `halfvec(4000)` profile accepts a numeric provider vector longer than 4,000 and returns exactly
   the first 4,000 components.
2. Normalization, when enabled, runs after truncation and produces a normalized stored vector.
3. Exact 4,000-dimensional output remains accepted.
4. Output shorter than 4,000 is rejected with `EMBEDDING_DIMENSION_MISMATCH`.
5. Overlong output for profiles other than `halfvec(4000)` remains rejected with the same code.
6. Malformed values, including malformed discarded-tail values, remain rejected as invalid output.
7. No migration drift or unrelated behavior change is introduced.

## Affected components

- `apps.ingestion.embedding.OpenAICompatibleEmbeddingClient`
- Embedding adapter unit tests
- ADR-0003 response-dimension rule, refined by ADR-0017

## Interfaces affected

The provider-response contract is broadened only for `halfvec(4000)`. Profile registration and
stored `EmbeddingResult.dimensions` remain 4,000.

## Data impact

Only the first 4,000 components are persisted. The discarded suffix is not stored or logged.
Existing vectors and indexes are unchanged until deliberately rebuilt.

## Security impact

Provider responses remain untrusted, response-size bounded, shape checked, and fully numeric
validated. Truncation is not enabled for tenant-selected dimensions or arbitrary profile geometry.

## Authorization impact

None. Existing platform profile registration and tenant grant rules remain authoritative.

## Observability impact

No raw vector or provider payload is logged. Existing stable provider/build failure codes remain.

## Migration impact

None.

## Dependencies

No dependency changes.

## Implementation steps

1. Add an explicit maximum-halfvec response adaptation helper/branch.
2. Validate all returned components as numeric, then truncate and normalize.
3. Add boundary and negative tests.
4. Update ADR relationships/current behavior documentation.
5. Run focused and repository-required checks; record evidence.

## Test plan

- Focused embedding adapter and schema tests.
- Ingestion test suite.
- Formatter, linter, type-check, Django check, migration-drift check, compileall.
- Full repository suites as time/runtime permits; PostgreSQL and browser rows may be N/A because the
  change is a deterministic provider-response adapter with no database/UI/auth change.

## Rollout plan

Deploy normally. Operators opt in by registering a new immutable `halfvec` profile revision with
`dimensions=4000`, granting it, and performing a staged rebuild before promotion.

## Rollback plan

Revert the adapter change and disable the affected profile revision. Existing prior index versions
remain available for pointer-flip rollback.

## Risks

- Prefix truncation can reduce retrieval quality and is provider/model dependent.
- A provider changing output length from exactly 4,000 to a larger value no longer fails for this
  explicit profile geometry; evaluation before promotion is therefore required.
- The source vector's suffix is irreversibly discarded from the built index.

## Open questions

None. The user explicitly selected prefix truncation to 4,000 while retaining the current storage
architecture.

## Status

Implemented. Backend verification is complete; signed-in browser and live >4,000-provider smoke
remain manual completion gates. See [`verification.md`](verification.md).

## Completion criteria

The acceptance criteria have automated evidence, current behavior and the ADR refinement are
documented, applicable repository checks pass, and final architecture/security/SRE diff reviews are
recorded in `verification.md`.
