# Scenario and document authoring UX

Status: **Implemented**, automated verification in [`verification.md`](verification.md). The
mandatory post-development browser gate has not run, so this is **not `Verified`**.

Security boundaries and residual threats: [`threat-model.md`](threat-model.md).

## Problem

Sixteen findings from the owner using the previous build. Each was confirmed against code
before any change; three turned out to be defects that made a control unusable rather than
merely awkward, and one was a governance hole.

## Confirmed defects

| Finding | Root cause |
| --- | --- |
| Multiple expected words impossible | `normalize_rows` took one `expected` string → one `answer_contains` |
| The console's own sync curl example fails | The `Idempotency-Key` header was on the background example only; `request_unified_run` refuses an empty key with `IDEMPOTENCY_KEY_REQUIRED` |
| Every run rejection blamed the header | The `except WorkflowRequestError` catch-all answered "A bounded Idempotency-Key is required." for *every* remaining code, including `RUN_RUNTIME_SUSPENDED` and `EXECUTION_CONTEXT_INVALID` |
| Version history behaved backwards | `older_versions` held every version *except the selected one*, so selecting v1 filed the newest version under "Geçmiş sürümler" |
| Adding one document meant starting over | `create_document_set_version` copies nothing; the copying path (`get_or_create_manual_draft`) existed but was reachable only through bulk upload |
| Citation checkbox silently lost | `load_rows` always returned `require_citation=False`, so a reload unticked it and the next save dropped `citations_present` from the author's own gate |
| Ordering contradicted itself | Step 4 (test questions) asked the operator to finish with a control that needs the candidate step 5 produces |
| A stub answer passed the gate and reached consumers | With no `RUNTIME_MODEL_PROVIDER`, a generating workflow answers from `StubModelProvider`; the eval suite passes on it and a consumer cannot tell |

Two findings were **not** defects: the Studio → scenario back link exists
(`frontend/src/App.tsx`) and was missing only from a stale generated bundle; the answers to
test questions were already recorded, just on a separate report page.

One finding could not be reproduced: the staged-index button doing nothing. The İstanbul set's
v2 is `promotable` with no index, no preparation profile and no build job, and the web log had
rotated. The rejection path is now instrumented (below) so the next attempt says why.

## Delivered

### A · Scenario and evaluation

- **One term per line, all required.** Each term becomes its own `answer_contains` /
  `normalized_contains`, so a failing run names the term that was missing instead of failing
  the row opaquely. The closed allowlist is unchanged.
- **Steps 4 and 5 swap.** Preparing the candidate comes first; the test questions follow, on a
  release that exists. This is the owner's fix, and it is smaller than moving the control.
- **The answers appear next to the questions** — the last run's generated answer, assertion
  outcomes and judge verdict, behind the same `SCENARIO_TEST` gate the report uses.
- **The citation flag round-trips**, read back from the current `eval_suite` (the question-set
  vocabulary has no "has any citation" assertion, so it can only live there).

### B · Invocation and honest failure

- `Idempotency-Key: $(uuidgen)` on every generated example, with the reuse and conflict rules
  stated once next to them instead of discovered from a 400.
- Each `WorkflowRequestError` code maps to its own safe message and status
  (`RUN_RUNTIME_SUSPENDED` → 503, `WORKFLOW_STATE_TOO_LARGE` → 413); anything unmapped stays a
  generic rejection rather than a confidently wrong one.
- **A generating release with no real provider cannot be promoted or canaried.** The check
  lives on `_assert_release_gate`, which both traffic paths share: a stub may be *evaluated*,
  never *served*. Hermetic tests are unaffected — they use non-generating workflows — and the
  console names the missing configuration.
- The one-off question answers **on the page that asked**, with the question still editable, so
  a follow-up is one click. The answer is one-shot: a reload does not resurrect it.

### C · Document sets

- **"Diğer sürümler"** lists every other version honestly, marks the newest, and each entry can
  seed a new one.
- **`branch_document_set_version`** opens a draft from any published version's exact
  membership. The source stays frozen; the change becomes a new version (v1 → v3 works). It
  refuses while a draft is already open, so two half-finished versions cannot compete for the
  next publish. "Boş taslak aç" moves under Gelişmiş.
- **Real forms for chunking and retrieval profiles** — strategy/size/overlap/max_chunks and
  mode/top_k/threshold/weights — with choices and bounds read from
  `apps/artifacts/governed_dsl`, so the form cannot offer something the validator refuses. The
  hybrid-only weights are hidden and removed from the body outside hybrid, which is what the
  validator requires.
- **The operator names a profile; the server derives its identity.** Logical ID and permanent
  purpose are allocated with a collision check, as scenario and project creation already do.
- **A reusable info control** (`console/field_info.html`) renders the same schema as inline
  help. Applied to the document-set profile pickers and the generic artifact form; the other
  JSON surfaces (transform DSL, REST mapping) get help, not forms, per the owner's decision.
- The deprecated **"Arama profili (kullanımdan kalktı)"** picker is gone. Stored pins are
  retained as data and still resolve; query-time retrieval is owned by the Retrieve node.
- **Automatic staged preparation defaults on.** Nothing happens between publishing a set
  version and preparing its index except choosing profiles, and those are stored after the
  first build — so the second click was ceremony. A prepared index is staged and never served,
  so this changes no query behaviour. Existing stored preferences are respected; the switch
  moves under Gelişmiş with an explanation of the cost.
- The build rejection **names the fields that failed** instead of answering "tenant'a açık bir
  profil seçin" to every cause.

## Deliberate scope decisions

- Multi-term `contains` uses AND across separate assertions rather than a new
  `answer_contains_any` type: the promotion gate's allowlist stays closed and unchanged.
- The provider check is a *traffic* gate, not a release-quality gate. The same release is
  legitimately evaluated with a stub in CI and served with a real provider in production.
- The expected literal is added to assertion outcomes but rendered only under
  `can_view_content`, matching the existing redaction contract.

## Out of scope

- Forms for the transform DSL and REST mapping contracts (info only, owner's decision).
- Making upstream provider failures readable (`UPSTREAM_STATUS` → status class) and fixing
  their retry classification. Still identified and unapproved; see
  `scenario-publishing-ux-realignment/threat-model.md`.
