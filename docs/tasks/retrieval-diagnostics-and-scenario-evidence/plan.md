# Retrieval diagnostics and scenario retrieval evidence

Status: **Implemented**, automatically verified in [`verification.md`](verification.md). The
mandatory post-development browser gate has not run, so this is **not `Verified`**.

Security boundaries and residual risks: [`threat-model.md`](threat-model.md).

## Problem

The owner asked a one-off question against a document set's new version and got
"Aktif exact index/retrieval profili bulunamadı." The probe had worked on the previous
version of the same set.

The cause is the `scenario-node-bound-authoring-realignment` change, exactly as the owner
suspected: query-time retrieval ownership moved from the document set to the scenario's
`retrieve` node, so `DocumentSetPreparationProfile.retrieval_profile` became nullable
(`ingestion.0014`) and the document-set page stopped offering the picker. What was missed is
that two operator surfaces still required a retrieval profile to exist on the built index.

## Confirmed defects

| Finding | Root cause |
| --- | --- |
| One-off document-set probe refuses on every newly built index | [`views.py:7276-7285`](../../../apps/console/views.py) resolves `set_version.built_index_version.retrieval_profile` and aborts when it is `NULL`; `ask_document_set_once` takes a mandatory `retrieval_profile: ArtifactVersion` ([`question_services.py:1032`](../../../apps/evaluations/question_services.py)). `staged_build` passes the now-`None` preparation value straight through to `IndexVersion.retrieval_profile`, so every index built after the realignment has none. Indexes built before it still do — which is why v1 worked and v2 did not. |
| Retrieval batch evaluation silently loses its targets | `_retrieval_target_choices` filters `retrieval_profile__isnull=False` ([`views.py:6865`](../../../apps/console/views.py)). New indexes disappear from the dropdown with no explanation; when the list empties the page says only "Yetkili, hazır exact retrieval hedefi yok." The profile primary key is also round-tripped through the client as part of the `setversion:index:profile` target value. |
| A scenario answer carries no retrieval evidence | `ask_scenario_once` always returns `chunks=[]` ([`question_services.py:1080`](../../../apps/evaluations/question_services.py)). The author sees an answer and cannot tell whether a bad one came from retrieval, the prompt or the model. This is the gap that matters: the scenario's `retrieve` node holds the real retrieval profile, the pinned document-set versions and the pinned indexes, so it is the only honest place to ask "what did *my scenario* retrieve for this question". |
| Content-exposing probes are not audited | Neither `ask_document_set_once` nor `ask_scenario_once` records an audit event, and both are about to be able to surface document chunks. |

## Design decision

Ownership stays as the realignment left it, and is not reopened:

| When | Owner |
| --- | --- |
| Index time — chunking, embedding | Document set |
| Query time — mode, top_k, weights | The scenario's `retrieve` node (`retrieval_profile_ref`) |

Reintroducing a retrieval picker on the document set would undo that. Instead the two
document-set surfaces become **index diagnostics** and stop pretending to be retrieval
configuration: they run with fixed settings the server owns, and say so on screen.

Those settings are not a new constant. They are read from the single existing source, the
authoring form's own defaults — `profile_defaults(ArtifactType.RETRIEVAL_PROFILE)` in
[`apps/console/profile_fields.py`](../../../apps/console/profile_fields.py) — which today
yields `mode=hybrid`, `top_k=5`, `vector_weight=keyword_weight=0.5`, no threshold. If the form
default changes, the diagnostic changes with it and no second definition can drift.

## Planned work

### A · Document-set probe — transient, persists nothing

- `ask_document_set_once` takes `profile_body: dict` instead of `retrieval_profile:
  ArtifactVersion`; the provider was already given a body, not an artifact.
- The view stops resolving a profile. Its only remaining precondition is the honest one — a
  built, ready index — and the rejection names which precondition failed (no active version vs.
  no ready index) instead of one message for both.
- The form states the fixed settings: *"Sabit tanı ayarıyla çalışır (hibrit, en iyi 5).
  Senaryonuz kendi arama profilini kullanır."*
- No artifact is created. A question must not have registry side effects.

### B · Retrieval batch evaluation — persistent, produces evidence

A persisted run's provenance cannot rest on a code constant: the same report re-run after an
unrelated edit would silently measure something else. So here the body is pinned as an
immutable, checksummed artifact.

- A per-organization system-owned `retrieval_profile` artifact (`sys_diag_retrieval`,
  "Tanı araması") is resolved **when a run is started** — reused when an identical checksum
  already exists, published as a new version otherwise. Nothing is created while rendering a
  page.
- `retrieval_profile__isnull=False` is removed from `_retrieval_target_choices`. The target
  value narrows to `setversion:index`; the profile primary key no longer travels through the
  client at all.
- An empty target list states its reason (no authorized set, or no ready index) instead of
  disappearing.
- `QuestionEvaluationRun.retrieval_profile` stays `NOT NULL` and `_retrieval_case` is unchanged
  — **no migration**.

### C · Scenario retrieval evidence — the actual gap

- `execute_release_input` returns `metadata["retrieval"]`: **numeric pointers only**
  (`document_version_id`, `ordinal`, `index_version_id`, scores) projected from
  `run.redacted_state["retrieval"]["chunks"]`. Strings there are already `[redacted]`
  ([`workflows/services.py:282-291`](../../../apps/workflows/services.py)) and none are carried.
- `ask_scenario_once` pairs those pointers with `output["sources"]` — source id, uri, title and
  score, already part of the caller-visible output contract — **by position**, because
  `citations_from_state` projects the chunk list one-to-one. If the two lengths disagree the
  pairing is skipped and only the sources are shown; no invented alignment.
- Chunk **text** is a separate authorization: asking needs `SCENARIO_TEST`, seeing text
  additionally needs `DOCUMENT_SET_CONTENT_READ` on the document set that owns the version.
  Text is resolved from the vector store with `exact_chunk_text`, the same governed path
  [`question_evaluation_detail`](../../../apps/console/views.py) already uses. Without that
  capability the operator sees provenance and scores, never text.
- The gateway boundary is untouched: document text still never leaves through the API. This
  surfaces it only in the tenant-scoped operator console, to an operator who holds the
  document-content capability.
- `scenario_detail.html` renders the evidence under the answer; the existing chunk markup in
  `one_off_question_result.html` is extracted so both surfaces render one shape.

### D · Audit

Both probes record an audit event with actor, target, authorization decision and the chunk
**count** — never chunk content, source uri or question text beyond what audit already permits.

## Found during implementation

A third instance of the same coupling, not visible from the console: `create_retrieval_evaluation`
required the supplied profile to be **the one pinned on the index**
(`index_version.retrieval_profile_id != retrieval_profile.pk`). With a profile-less index this
always raised `RETRIEVAL_PROFILE_NOT_EVALUABLE`, so removing the dropdown filter alone would have
moved the failure from a missing option to a 404. The condition is removed; tenant ownership and
artifact type are still enforced, and the run's provenance still records the exact profile ref and
checksum. Reasoning and safety argument: [`threat-model.md`](threat-model.md).

## Acceptance criteria

1. A one-off probe succeeds against an index built with no retrieval profile.
2. A rejected probe names which precondition failed.
3. The retrieval batch dropdown lists profile-less indexes; an empty list states its reason.
4. A retrieval run pins the system diagnostic artifact; a second run reuses the same checksum.
5. A scenario one-off shows sources and scores; text appears only with
   `DOCUMENT_SET_CONTENT_READ` and never without it.
6. Cross-tenant probes and evidence reads are denied.
7. The gateway response for the same question still contains no document text.
8. Both probes emit an audit event.

## Risks

- **Content exposure.** The scenario page becomes a new surface that can show document text.
  Mitigated by requiring the document-plane capability in addition to `SCENARIO_TEST`, by
  resolving text from the store rather than from run state, and by leaving the API contract
  alone. This is the item that most needs review in the final diff.
- **Positional pairing.** Sources and state chunks are aligned by index. The guard is a length
  check with a fall back to sources-only; a regression test covers the mismatch.
- **PostgreSQL-only text.** `exact_chunk_text` requires PostgreSQL. On SQLite it raises and the
  text is omitted — the same behaviour the existing evidence view already has. Verification
  must run the PostgreSQL profile for criterion 5.
- **Diagnostic settings misread as scenario behaviour.** Mitigated by stating the fixed
  settings on screen next to the probe.

## Out of scope

- Any change to query-time retrieval ownership.
- Letting an operator choose probe settings. Whatever they chose would not be what the scenario
  uses; if a transient advanced control is ever wanted, it is a later addition.
- Backfilling `retrieval_profile` onto indexes built before the realignment. Existing pins are
  retained as historical provenance and still resolve.
- The unapproved `UPSTREAM_STATUS` retry-classification defect carried in
  [`scenario-publishing-ux-realignment/threat-model.md`](../scenario-publishing-ux-realignment/threat-model.md).

## Cost

No migration, no new dependency, no gateway contract change. Touched:
`apps/evaluations/question_services.py`, `apps/evaluations/services.py`,
`apps/console/views.py`, `apps/console/forms.py`, `apps/console/profile_fields.py`
(one export), and two console templates.
