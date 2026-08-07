# Scenario publishing UX realignment

Status: Implemented. Automated verification complete (`verification.md`); the mandatory
post-development browser gate remains outstanding, so this is **not yet `Verified`**.

## Problem

Making a scenario work required seven screens and two returns, and the operator had to
re-select in a manifest panel the artifacts they had just authored inside their workflow
nodes — by raw logical id. The panel defaulted each artifact's manifest **role** to the
artifact *type*, so a `retrieve` node referencing `ret_<identity>_profile` was pinned as
`retrieval_profile`. The compiler accepted it, preflight reported success, and the release
only failed at request time.

Owner-reported symptom: `EvalRun#6` → `status=error`,
`error_code=WORKFLOW_RETRIEVAL_BINDING_INVALID`, `0/1`, no assertion evaluated — displayed
as a **green success message**.

## Root causes (all confirmed in code)

1. `frontend/src/ScenarioManifestPanel.tsx:115` — `effectiveRole = requiredRole || roles[0]
   || artifactType`; the normal selection path produced the type name as the role.
2. `apps/console/views.py` `preset=minimum` never included node-derived roles and assigned
   `role = type`; the panel cleared the requirement list when the preset loaded.
3. `compile_release` never consulted `analyze_workflow_requirements`, so a manifest missing
   a node's required role compiled successfully.
4. `apps/workflows/runtime.py:83-85` fails closed at request time — correct, but far from
   the cause.
5. `apps/console/views.py` `release_run_eval` — `run_eval` returns (not raises) on runtime
   failure, so `except EvalError` was dead code and every outcome hit `messages.success`.
   `EvalRun.error_code` was rendered nowhere.
6. `prepare_scenario_contract_defaults` prepared no `eval_suite`, so a first candidate could
   never pin one, forcing: compile → author suite → return → compile a *second* candidate →
   return → run.

## Key insight

The manifest is a pure function of the scenario and its published workflow. Node-owned
artifacts, tool bindings and transform profiles name their artifact's `logical_id`
verbatim; the scenario contracts and eval suite use `scenario_artifact_logical_id`. Nothing
required an operator decision. Reuse of *shared* resources (tool bindings, model profiles,
custom nodes, subworkflows) already happens inside the node config, not the manifest, so
deriving the manifest removes no capability.

## Delivered

- **A** `derive_manifest()` (`apps/releases/authoring.py`) + fail-closed
  `_assert_workflow_roles_pinned` in `apps/releases/compiler.py`, both reading one shared
  `workflow_manifest_requirements()` so advice and enforcement cannot drift.
- **B** `eval_suite` added to `prepare_scenario_contract_defaults` (idempotent).
- **C** `POST /console/api/builder/drafts/<pk>/publish-and-verify/` — publish → derive →
  compile → evaluate in one operator action; Studio button "Yayımla ve test et".
- **D** Scenario page leads with six ordered, state-badged steps; the remaining operator
  sections moved into a collapsed "Gelişmiş" block.
- **E** Studio landing lists (workflow drafts, artifact drafts, "Yeni draft", new-prompt
  form) suppressed in scenario context — scenario creation already creates the one draft.
- **F** Eval outcome reported at its real severity (`summarize_eval_run`) with `error_code`
  and per-case reason codes rendered.
- **G** Node-owned artifact version history + "bu sürüme dön", "mevcut profilden kopyala"
  (`node-artifact-library`), and the missing `transform_profiles` picker.
- **H** Manifest panel becomes a read-only derived summary with human labels
  (`release-manifest/derived/`).

## Deliberate scope decisions

- The compile gate requires every **workflow-derived** role; additional pins (release-level
  fallbacks, scenario contracts) remain allowed, so legacy releases still compile.
- The manual manifest path remains for a scenario with no published workflow. It can no
  longer produce a broken release because A rejects a role mismatch at compile time.
- Reverting to an older artifact version republishes the old body *forward* as a new
  immutable version; no mutation, no pinning of a superseded version.

## Authorization

Unchanged. `publish-and-verify` requires exact Scenario Editor authority (the same as
`draft_publish`); promotion, rollback, canary and scenario activation remain
release-manager-only and are unreachable from the new endpoint.
