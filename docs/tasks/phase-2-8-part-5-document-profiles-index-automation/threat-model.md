# Threat Model: Phase 2.8 Part 5 — Document profiles and index automation

## Assets and classification

Document bytes/text/metadata, set memberships/versions, chunks, embeddings, keyword indexes,
LLM summaries, model/profile provenance, grants, active-index pointers and object-store/database
consistency. Content and derived summaries are tenant-confidential; credentials are restricted.

## Actors, entry points and boundaries

Document managers, org/platform admins, scenario/release roles, auditors, consumers, workers,
connectors, parsers and model/embedding providers. Entry points include set upload/replace/publish,
source sync, profile selection, summary/build jobs, retrieval and cleanup. Files, parsed text,
queries, profile refs, provider responses and task payloads are untrusted.

## Principal threats and mitigations

| Threat | Required mitigation |
| --- | --- |
| Unbound document bypasses governance | Set-context atomic service; deny standalone creation |
| Keyword path bypasses ACL/RLS | One shared authorized candidate set before all ranking modes |
| SQL/identifier injection in BM25 store | Parameterized query; closed validated physical names only |
| Hybrid score manipulation/misrepresentation | Fixed weighted RRF contract; component diagnostics; bounded inputs |
| Malicious/huge content exhausts parser/chunker/model | Existing upload/parser limits plus per-profile chunk/input/output/time caps |
| Summary leaks content to arbitrary endpoint | Platform-managed granted model profiles; SSRF/TLS/secret controls |
| Hallucinated summary presented as source | Mark as derived summary, retain provenance and cite original document |
| Tombstoned/foreign content retrieved | Tenant/grant/pinned active index/live document intersection and FORCE RLS |
| Auto build silently activates | Separate prepare and activate state/actions; no pointer flip in worker |
| Cleanup deletes pinned/held/unknown bytes | Dry-run inventory, refusal checks, exact approval, backup and reconciliation |
| Document manager gains broader authority | Dedicated predicate and negative tests across non-document actions |

## Logging, audit and failure cases

Never log document/chunk/summary/query/provider bodies. Audit lifecycle and cleanup with safe IDs,
counts, checksums, profile refs, outcomes and reason codes. Handle provider timeout, partial store,
worker loss, duplicate job, fingerprint mismatch, DB/object-store divergence and audit outage with
idempotent cleanup or visible failed state; activation and deletion fail closed.

## Residual risks and required security tests

Summaries are inherently lossy and keyword ranking may expose term relevance to authorized users.
Require cross-tenant/grant/tombstone tests for all modes, SQL/identifier fuzzing, malicious content
bounds, summary SSRF/redaction/provenance, job duplication, no-auto-activation, role matrix, cleanup
refusals/restore and PostgreSQL non-owner RLS.
