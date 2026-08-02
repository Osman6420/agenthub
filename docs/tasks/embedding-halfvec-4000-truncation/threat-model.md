# Threat Model: embedding-halfvec-4000-truncation

## Assets

Embedding integrity, retrieval quality, immutable profile geometry, document-derived vectors, and
provider credentials.

## Actors

Platform administrators configuring profiles, authorized tenants consuming granted profiles, the
ingestion/runtime workers, and an untrusted or faulty external embedding provider.

## Entry points

Platform embedding-profile registration and the HTTPS embedding response body.

## Trust boundaries

External provider to AgentHub adapter; adapter to staged-build/vector-store boundary; platform
catalog to tenant-granted runtime use.

## Data classifications

Input text and embeddings inherit document classification. Dimensions, profile IDs, and stable
error codes are operational metadata.

## Authentication

Unchanged provider credential resolution and platform-admin authentication.

## Authorization

Unchanged platform-only profile registration and explicit tenant profile grants.

## Tenant isolation

Unchanged. Adaptation operates on one response before the existing tenant-scoped store write.

## External systems

Governed OpenAI-compatible HTTPS embedding providers and PostgreSQL/pgvector.

## Abuse cases

- Provider returns a very large vector: existing response-byte cap remains the resource bound.
- Provider returns non-numeric data in the discarded suffix: validate the complete response vector
  before truncating so malformed output cannot hide outside the stored prefix.
- A smaller profile accidentally accepts overlong output: require exact `halfvec(4000)` geometry.
- Operator assumes truncation is lossless: document the quality risk and require staged evaluation.

## Failure cases

Short output, wrong non-max geometry, malformed data, missing fields, and wrong batch cardinality
continue to fail closed with stable codes. Build cleanup remains unchanged.

## Logging and audit risks

Raw vectors, provider response bodies, and discarded components must not be logged or audited.

## Mitigations

Exact opt-in predicate, complete numeric validation, bounded response size, post-truncation
normalization, immutable profile revisions, staged build, explicit promotion, and rollback.

## Residual risks

Prefix truncation may distort semantic neighborhoods or reduce model quality. Only provider-specific
evaluation can quantify this.

## Required security tests

- Overlong `halfvec(4000)` output truncates to the prefix only.
- Malformed discarded-tail data is rejected.
- Short `halfvec(4000)` output is rejected.
- Overlong non-max profile output is rejected.
