# ADR 0017: Bounded provider-response truncation for maximum-dimension halfvec stores

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

ADR-0003 fixes each physical vector store to a pgvector HNSW-compatible geometry and originally
required every provider response to exactly match that geometry. pgvector HNSW supports at most
4,000 dimensions for `halfvec`, while a governed provider may return a longer dense vector. Rejecting
that response prevents use of the provider even when the operator deliberately accepts a bounded
4,000-dimensional projection.

## Decision

An immutable embedding profile with `index_type=halfvec` and `dimensions=4000` explicitly opts into
bounded prefix truncation. If its provider returns more than 4,000 numeric components, AgentHub:

1. validates every returned component, including the discarded suffix, as numeric;
2. retains the first 4,000 components;
3. normalizes that retained vector when the profile requests normalization; and
4. reports and stores the result as exactly 4,000 dimensions.

Short responses remain invalid. Every profile geometry other than exact `halfvec(4000)` continues to
require exact response length. Profiles still cannot declare a stored dimension above the pgvector
limit.

This ADR supersedes only ADR-0003's provider-response "never truncated" rule. ADR-0003 remains the
authority for per-`IndexVersion` storage, fixed physical geometry, promotion, rollback, and retention.

## Security, data, and operational review

- The external response remains size-bounded and untrusted; complete numeric validation occurs
  before truncation.
- No raw vector or discarded suffix is logged, audited, or retained.
- Truncation is explicit through immutable maximum-halfvec profile geometry, not tenant input.
- Prefix projection can reduce retrieval quality. A new profile revision must use staged build,
  evaluation, and explicit promotion; the prior store remains the rollback target.

## Consequences

- Providers with native vectors longer than 4,000 can use the existing HNSW halfvec storage path.
- Retrieval quality becomes dependent on the provider's coordinate ordering and the suitability of
  prefix truncation; no mathematical equivalence to provider-native dimensionality is claimed.
- A future provider-specific projection or native dimension-request feature should be represented by
  a new immutable profile revision and, if it changes this contract, a later ADR.

## Alternatives considered

- Continue rejecting overlong responses: safest contract, but does not meet the required provider
  compatibility.
- Ask every provider for exactly 4,000 dimensions: not uniformly supported by OpenAI-compatible
  endpoints and changes outbound-provider semantics.
- Add a learned/random projection: more complexity and provenance requirements than prefix
  truncation, and not requested.

## Rollback

Revert the adapter behavior, disable the opt-in profile revision, and restore the prior active index
through the existing pointer-flip rollback.

## References

- [ADR-0003](0003-vector-storage-blue-green-per-index-version.md)
- [Task plan](../tasks/embedding-halfvec-4000-truncation/plan.md)
