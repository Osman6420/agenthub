# Threat model — retrieval diagnostics and scenario retrieval evidence

Plan: [`plan.md`](plan.md). Evidence: [`verification.md`](verification.md).

## What changed in the trust picture

One new capability exists that did not before: the **scenario page can display document chunk
text**. Everything else in this task removes a coupling or names a rejection; this is the only
addition that exposes data, and it is the item that most needs review.

## Assets and boundaries

| Asset | Boundary |
| --- | --- |
| Document chunk text | Vector store, per `IndexVersion`, under FORCE RLS with a transaction-local tenant scope |
| Retrieval provenance (source id/uri/title/score) | Already part of the caller-visible output contract |
| Chunk pointers (`document_version_id`, `ordinal`, `index_version_id`, scores) | Run state → operator console only; numeric, carry no text |
| Diagnostic retrieval settings | System-owned immutable artifact, per tenant |

## Controls

**Chunk text is gated twice, and on the document plane.** Asking a scenario a question needs
`SCENARIO_TEST`. Seeing what a source actually said needs `DOCUMENT_SET_CONTENT_READ` on the
document set that owns the index — checked in `resolve_chunk_text`, which returns `""` before
the vector store is consulted at all. A scenario editor with no document-set responsibility
sees provenance and scores and nothing else. This mirrors `question_evaluation_detail`, which
already resolves evidence text only for the document-plane capability.

**Text never enters the session.** The one-off answer stores provenance and numeric pointers;
text is resolved when the page renders, against the authorization held *then*. A session cannot
become a second, unexpiring copy of document content, and an operator who loses the capability
between asking and reloading stops seeing text.

**Text never enters the run projection.** `retrieval_pointers_from_state` accepts only `int`
and `float` (rejecting `bool`), so no string can travel with a pointer — and every string in a
persisted run state is already `[redacted]`. The API contract is unchanged: the gateway still
returns citations without document text.

**Tenant scope.** `resolve_chunk_text` loads the `IndexVersion` filtered by the caller's
organization; a foreign pointer resolves to `""` without reaching the store. Test:
`test_chunk_text_refuses_an_index_from_another_tenant`, which fails the test outright if the
store is consulted.

**Positional pairing cannot mislead.** Sources and state chunks come from the same one-to-one
projection. If the lengths ever disagree, the pointers are dropped and only provenance is shown
— an operator is never told the wrong chunk backed a source.

**Probes are audited.** Both one-off probes record actor, target, authorization decision and
the chunk **count**. Never the question, the answer, the source uri or any chunk content. A
denial records that it happened and carries no payload.

## Deliberate relaxation, and why it is safe

`create_retrieval_evaluation` required the supplied retrieval profile to be the one pinned on
the `IndexVersion`. That condition is removed; tenant ownership and artifact type are still
enforced.

The check conflated build time with query time. A retrieval profile has never influenced how an
index was built — chunking and the embedding profile do that — so matching it proved nothing
about compatibility. It only encoded the ownership model that the scenario's Retrieve node has
taken over, and after that change it made every newly built index unevaluable. The run's
provenance still records the exact profile ref and checksum, so a report always states what it
measured with, and an operator still cannot reach another tenant's profile or pass an artifact
of the wrong type.

## Residual risks

- **A new content surface.** The scenario page can now show document text to an operator who
  holds `DOCUMENT_SET_CONTENT_READ`. That is the intended grant, but it is a surface that did
  not exist, and it should be confirmed in the browser gate with a matched permitted/forbidden
  pair.
- **Chunk text resolution is PostgreSQL-only.** Off PostgreSQL `exact_chunk_text` raises and the
  text is omitted. The authorization gate is proven vendor-independently (the store is not
  consulted when the capability is absent); the successful resolution path against a live
  vector store is covered by the existing `exact_chunk_text` tests and by the browser gate, not
  by a new PostgreSQL test in this task.
- **The diagnostic artifact is created by an operator action.** Starting a batch run may publish
  one immutable artifact version in the operator's own tenant. It is bounded (one logical id,
  reused by checksum), audited by `create_artifact_version`, and never created while rendering a
  page.
- **Diagnostic settings could be mistaken for scenario behaviour.** Mitigated by stating the
  fixed settings next to both surfaces; not enforceable in code.
