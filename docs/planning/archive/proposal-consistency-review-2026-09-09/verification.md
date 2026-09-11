# Proposal review verification — 2026-09-09

## Scope and evidence

Assessment only, on branch `feat/foundation-sprint-0-1`, HEAD `2c3e959`.
Substantial application and planning edits existed before this task. No commit,
push, application mutation, service operation or data migration was performed.
The historical handoff concerns another incomplete unit and was not adopted as
the current task or as evidence of running services.

Read all 22 Markdown files under `docs/tasks/Agent_Hub_MD`, including plans,
implementation briefs, threat models, navigation inventory and verification
records. Compared their canonical counterparts by SHA-256. Also inspected:

- Root AGENTS.md; engineering/security/observability/testing/definition-of-done
  rules; task template/policy, archive policy, master plan and handoff.
- ADR-0015 and the previous 35-model target mapping; relevant prior assessment
  references and the newer brief's explicit supersession/retention requirements.
- `apps/identity/authorization.py`, `apps/tenancy/services.py`: exact role and
  document-content management rules.
- `apps/ingestion/rest_services.py`, `rest_schema.py`, `rest.py`, `models.py`:
  profile/grant versus contract/source authority; root path validation; synthetic
  preview; Source, cursor and schedule identity; profile/contract revisions.
- `apps/documents/services.py`, `models.py`, `access_services.py`,
  `apps/retrieval/providers.py`, `apps/releases/lifecycle.py`,
  `apps/ingestion/staged_build.py`, `automation.py`: pinned content versions,
  active-index selection, live grants and governed publication/activation.
- `apps/ingestion/vector_store.py`: per-index store names and runtime call into
  the controlled DDL seam. Existing durable workflow model declarations.
- `apps/console/views.py`, scenario detail template, navigation source references
  and diagnostic helper: existing scenario list and continued setup checklist.
- Selected MCP and REST test regions and responsibility-authorization references;
  this is source inspection, not execution of those tests.

Checked upstream primary documentation for technical feasibility:
[pgvector](https://github.com/pgvector/pgvector), including mixed dimensions,
filtering and multitenancy, and
[PostgreSQL partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html).
These sources do not establish the locally installed extension version or local
performance. No source content was treated as an instruction to modify the project.

## Executed checks

Commands ran through PowerShell from the repository root.

| Check | Evidence/result |
| --- | --- |
| `git status --short`; `git branch --show-current`; `git rev-parse --short HEAD` | Existing dirty tree identified; branch/commit above. |
| `rg --files`, bounded `rg -n`, `Get-Content -Encoding utf8` | All proposal documents and relevant source/instruction regions inspected. |
| `Get-ChildItem docs/tasks/Agent_Hub_MD -Recurse -File`, paired `Get-FileHash -Algorithm SHA256` | 7 directories; 22 files; 22 canonical counterparts; all 22 identical. |
| Relative Markdown/image target resolution against each containing directory using `Test-Path -LiteralPath` | Copied package: 64 occurrences, 38 resolve, 26 broken. Canonical and new-report checks recorded below after final validation. |
| Upstream documentation read | Mixed-dimension storage is feasible; shared ANN recall/performance and partial-index query-plan caveats supported. |

The link check parses Markdown links/images, skips HTTP(S) and fragment-only
targets, removes fragment suffixes and tests the resolved local path. It tests
file existence, not heading anchors, external availability or full Markdown
semantics. Broken copied links by file: authorization plan 2, authorization brief
1, UI brief 10, RAG brief 3, scenario plan 1, vector plan 9.

During source navigation one guessed MCP test filename did not exist and Windows
literal wildcard paths were rejected. Re-ran with `rg --files`, the observed
`test_mcp.py` path and `rg -g` filters. One hash-capture JSON parse encountered
Git's pre-existing line-ending warning; reran the read-only collection with stderr
separate. These were tooling/navigation corrections, not application failures.

## Acceptance and review

- Duplicate and broken-link evidence is separated from policy/behavior conflicts.
- Historical implementation and document-preparation evidence is not reused as
  a new passing application check.
- Owner's combined-manager preference is recorded as a design direction only.
- Inheritance, shared data, freshness, REST actor handoff and implementation
  sequencing are left as explicit choices; no unsupported approval inferred.
- Source-backed REST authority/revision gaps and MCP metadata scope risk identified.
- Staff review: avoid redundant UI/storage work and table-count-driven replacement;
  distinguish current behavior, target behavior and staged compatibility.
- AppSec review: preserve server authority, grant/content separation, current
  revocation and audit; no original proposal or protected source altered.
- SRE review: no deployment/data operation; require measured ANN behavior and a
  real transition/rollback contract before structural changes.

## Checks not run

Application pytest, formatter/linter/type checks, migration drift, PostgreSQL/RLS,
browser lifecycle/accessibility, provider tests, dependency/secret scanners and
benchmarks were not executed. This task ships only assessment documents and two
planning-index additions; no executable code, dependencies, configuration or
migrations changed. Application/browser gates are N/A to this assessment, not
passed. No new executable tests were warranted for this document review.

No live Compose/health or database inventory was queried: application diagnosis,
startup/shutdown and runtime validation were outside this review. The historical
80/10/9 table inventory, the 44/54 estimate, page sizes and previous test counts
are not independently revalidated live measurements. No production/private
application data was retrieved. Codebase Memory and Serena were not exposed by
the available tool inventory; bounded direct inspection was used per repository
fallback policy. No subagents were used.

## Final document validation

- Canonical counterparts: 22 files, 64 local link occurrences, zero missing targets.
- Archived review: three Markdown files, 34 local link occurrences, zero missing targets.
- Strict UTF-8 decoding passed; no replacement characters or trailing whitespace
  found in the three review files.
- `git diff --check -- docs/planning/master-plan.md docs/planning/archive/README.md`
  passed with exit 0. New files checked individually with
  `git diff --no-index --check -- NUL <file>`: no whitespace diagnostics;
  exit 1 is expected for a new-file comparison.
- SHA-256 before/after comparison of 98 protected files (44 original/copy proposal
  files and 54 pre-existing modified application/configuration/documentation files)
  found zero changes during report preparation.
- Reviewed the new report and the assessment-only additions to master/archive
  indices. Their other pre-existing uncommitted additions were preserved.
- The assessment is complete and archived. Original proposals and their
  implementation statuses were not rewritten.

## Final report

- Summary: Assessed proposal consistency and feasibility; recorded one owner
  design preference without adopting an implementation plan.
- Files changed: This archive's plan.md, assessment.md, verification.md;
  docs/planning/master-plan.md and docs/planning/archive/README.md gained review links.
- Architecture impact: Documentation only; current architecture unchanged.
- Security impact: Existing MCP metadata scope risk recorded; no controls altered.
- Authorization impact: Combined manager target selected by owner; assignments,
  policy, inheritance and grants unchanged.
- Data and privacy impact: No data read from the running application, moved or
  deleted; no secrets added.
- Logging, metrics, tracing and audit impact: No runtime changes.
- Database and migration impact: None.
- Tests and verification results: File hashes, links, source consistency and
  document diff checks; final numerical results below.
- Unverified assumptions: Local runtime/version/volume, implementation cost,
  performance improvement and unselected target-policy details.
- Remaining risks: Original draft wording and duplicate/broken links deliberately
  remain; future agents must reconcile them with the owner's latest instruction.
  Source findings need targeted tests before a fix can be called verified.
- Manual review required: Owner selects remaining product choices before those
  dependent implementations. This assessment does not require a deployment approval.
