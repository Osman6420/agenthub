# Verification — retrieval diagnostics and scenario retrieval evidence

Plan: [`plan.md`](plan.md). Security boundaries: [`threat-model.md`](threat-model.md).

Status: **Implemented**, automatically verified. The mandatory post-development browser gate
([`manual-testing-guide.md` §10](../../manual-testing-guide.md#10-mandatory-post-development-ui-ux-and-authorization-gate))
has not run, so this is **not `Verified`**.

## Commands executed

Run from the repository root in `.venv` (Python 3.13).

| Command | Result |
| --- | --- |
| `ruff format --check apps` | 471 files already formatted |
| `ruff check apps` | All checks passed |
| `mypy apps` | Success: no issues found in 471 source files |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `pytest` (SQLite, `config.settings.test`) | **1298 passed, 61 skipped** in 194.98s |
| `pytest apps/evaluations apps/console apps/orchestration apps/retrieval apps/ingestion --create-db` (PostgreSQL, `config.settings.local`) | **579 passed, 2 skipped** in 296.66s |

The PostgreSQL run used `MCP_ENABLED=true`, a non-empty `METRICS_BEARER_TOKEN`, and the MinIO
object-store settings; both skips are the tests that deliberately assert the off-PostgreSQL
guard.

No migration was generated and no dependency was added. The frontend was not touched, so the
Node gates are **N/A** for this change.

## Acceptance criteria

| # | Criterion | Evidence |
| --- | --- | --- |
| 1 | A probe succeeds against an index with no retrieval profile | `test_the_probe_runs_against_an_index_that_has_no_retrieval_profile`, `test_the_probe_runs_against_a_profile_less_index` |
| 2 | A rejected probe names the precondition that failed | `test_a_refused_probe_names_the_precondition_that_failed` |
| 3 | The batch dropdown lists profile-less indexes; an empty list states its reason | `test_a_profile_less_index_is_offered_as_a_batch_target`, `test_an_empty_target_list_says_why` |
| 4 | A run pins the diagnostic artifact; a second run reuses the same version | `test_a_batch_run_pins_the_diagnostic_profile_and_reuses_it` |
| 5 | A scenario answer shows sources; text only with `DOCUMENT_SET_CONTENT_READ` | `test_the_scenario_answer_shows_what_it_retrieved`, `test_the_answer_shows_provenance_but_not_text_without_content_access`, `test_chunk_text_needs_document_content_authorization` |
| 6 | Cross-tenant probes and evidence reads are denied | `test_chunk_text_refuses_an_index_from_another_tenant`, `test_another_tenants_index_is_not_a_target` |
| 7 | No document text travels with the pointers | `test_pointers_carry_numbers_only`, `test_pointers_reject_non_numeric_and_boolean_values`, `test_citations_carry_provenance_without_document_text` (unchanged) |
| 8 | Both probes emit an audit event | `test_a_probe_is_audited_when_it_runs_and_when_it_is_denied` |

## How the authorization gate is proven without PostgreSQL

`exact_chunk_text` is PostgreSQL-only, so on SQLite an authorized and an unauthorized read both
return `""` and a bare assertion on the return value would pass vacuously. The tests instead
substitute `exact_chunk_text` with a recorder: the unauthorized and cross-tenant cases assert
the store was **never consulted**, and the authorized case asserts it was consulted with the
exact pointer. The gate is therefore proven independently of the database vendor.

## New tests

- `apps/evaluations/tests/test_retrieval_diagnostics.py` — 9 tests: probe without a profile,
  diagnostic body equals the form default, audit on success and denial, positional pairing,
  length-mismatch fallback, empty sources, content-capability gate, cross-tenant refusal,
  malformed pointer.
- `apps/console/tests/test_retrieval_diagnostics_console.py` — 8 tests: probe through the view,
  named rejection, target listing and its absence reason, artifact pinning and reuse, rendered
  evidence with and without content access, foreign-tenant target exclusion.
- `apps/orchestration/tests/test_rag_parity.py` — 3 added tests for the pointer projection.

## Changed behaviour covered by existing tests

`ask_document_set_once` now takes `profile_body` instead of `retrieval_profile`;
`apps/evaluations/tests/test_question_sets.py::test_one_off_document_retrieval_is_not_persisted`
was updated to the new signature (same assertions, unchanged intent).

## Not verified

- The **browser gate**. Required before `Verified`, and the priority items are: the probe on the
  İstanbul set's new version, the scenario answer's evidence block with a matched
  permitted/forbidden identity pair for document content, and a cross-tenant probe.
- Chunk text resolving from a **live vector store** through the new console path. The
  authorization gate and the plumbing are covered above; the store read itself is covered by the
  existing `exact_chunk_text` tests and belongs to the browser gate.
