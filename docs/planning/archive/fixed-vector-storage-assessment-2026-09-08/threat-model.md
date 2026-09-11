# Threat and operational review

- Shared storage increases the consequence of a missing scope predicate. Preserve
  FORCE RLS under a non-owner, non-BYPASSRLS runtime role; absent scope denies access.
  Keep document authorization and deletion checks in addition to tenant isolation.
- Enforce tenant-consistent references and generation/document/model relationships
  on writes, not only reads. Scope preview, copy, keyword and vector paths alike.
- Promotion and cleanup can race with readers and durable jobs. Publish atomically,
  resolve a generation per retrieval step, and retain referenced generations until
  their defined retry/rollback window ends; current revocations still take effect.
- Shared ANN filtering may reduce returned results/recall; shared deletes produce
  vacuum pressure. Validate real PostgreSQL plans, exact-search recall baselines,
  tenant skew, ingestion concurrency, latency and bounded cleanup before rollout.
- Replace runtime DDL capabilities only after the new read/write path is validated.
  Do not leave the old SECURITY DEFINER provisioning path callable as a workaround.
- Chunks and embeddings remain sensitive data. Audit safe identifiers/counts and
  lifecycle outcomes without content or vectors. No cross-tenant deduplication.

Assessment changes none of these controls. Implementation and destructive cleanup
remain separate, reviewable work.
