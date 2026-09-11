# Verification

## 2026-09-09 current-worktree revalidation

The Scenarios entry point and most navigation changes below were already present when this
follow-up began. They were verified against current source and runtime, not reimplemented.
Today's four template changes add a project-filtered Scenarios shortcut and bottom cancel
links in scenario artifact, platform profile and profile-grant forms. The shortcut uses the
trusted project UUID and agrees with the active organization; cancel destinations are named
internal routes. The artifact cancel link targets the existing `release-inputs-title` anchor;
the browser opens its enclosing configuration disclosure on arrival.

### Executed today

| Check | Result |
| --- | --- |
| `python -m pytest apps/console/tests/test_navigation.py apps/console/tests/test_console_accessibility.py apps/console/tests/test_console_ux_overhaul.py apps/console/tests/test_phase_2_8_part_1.py --basetemp=.tmp/pytest-navigation-review-20260909` (existing .venv) | 72 passed, 21.20 s; initial current-tree check |
| `.venv/Scripts/python.exe -m pytest apps/console --basetemp=.tmp/pytest-console-navigation-20260909-final` | 348 passed, 1 skipped, 73.97 s; after template edits |
| PostgreSQL selected navigation/accessibility/UX suite | 72 passed, 37.17 s; after template edits |
| `.venv/Scripts/ruff.exe check apps/console` | Passed |
| `.venv/Scripts/ruff.exe format --check apps/console` | 58 files already formatted |
| `.venv/Scripts/mypy.exe apps/console` | Passed, 58 files |
| `manage.py check`, `manage.py makemigrations --check --dry-run` with test settings | No issues; no changes detected |
| `git diff --check` | Passed; Git reported existing scenarios.html line-ending normalization warning |

PostgreSQL invocation: `.venv/Scripts/python.exe -m pytest -p pytest_django.plugin
apps/console/tests/test_navigation.py apps/console/tests/test_phase_2_8_part_1.py
apps/console/tests/test_console_ux_overhaul.py apps/console/tests/test_console_accessibility.py
--basetemp=.tmp/pytest-navigation-pg-20260909`. Used the documented local PostgreSQL profile,
`DJANGO_SETTINGS_MODULE=config.settings.local`, plugin autoload disabled, local Redis/MinIO
settings and a synthetic metrics test value. Tests used their isolated database; no canonical
application records were reset. SQLite's sole skip is the concurrent-writer test at
`test_console.py:271`, requiring PostgreSQL; the selected PG suite does not include that test.

### Current browser evidence

- The live authenticated admin session was available. Followed observed GET links through
  43 normalized page families in 53 page inspections/visits, including the primary menu,
  lists/details, create forms, health reports, project/scenario/Studio/release/artifact,
  documents/source/preview, questions, consumers, runs, approvals and platform forms.
  Different records of the same page type were sampled, not exhaustively traversed.
- No broken local fragment targets, unexpected error-page headings or document horizontal
  overflow found in these inspections. Browser error/warning log review returned an empty list.
  This is not an HTTP/network interception or full release acceptance claim.
- Clicked project shortcut → filtered scenario list (24 project scenarios; canonical creation
  link retains that project) → new scenario → cancel → project scenarios. Each transition is
  one click. Clicked artifact cancel → same scenario's Sözleşmeler section and confirmed its
  enclosing disclosure opens. Profile and grant cancellation each returned to Platform setup.
- At requested 390/900/1440 widths, document client widths were 375/885/1425 (scrollbar
  excluded), with no horizontal page overflow. Mobile menu opened, Escape closed it and
  returned focus to its toggle. Screenshot inspection confirmed visible focus and readable
  list/filter layout. Temporary viewport override was reset; Scenarios was left open.
- Existing samples again exposed no persisted evaluation-result links. Evaluation results,
  transient one-off answers, credential reveal, dormant templates and role-specific forms
  not reachable in this sample remain source/test coverage, not today's browser visits.
- No live POST was submitted, so no document, publication, index, profile, permission or
  credential was changed. Ordinary GET navigation may update the selected workspace/session.
  Retained browser evidence is aggregate navigation information, not document content.

### Runtime and review

Followed manual guide section 0 and canonical Compose before inspection. All app roles were
running and PostgreSQL/Redis/MinIO healthy; liveness returned ok. Template changes initially
remained cached although the container had the updated file. Restarted **web only** with
`docker compose -f deploy/compose/docker-compose.yml restart web`; verified the new links
visibly afterwards. Final Compose roles remained running and liveness returned ok. Workers,
databases and object storage were not restarted. No frontend TS/JS or generated builder
changes were made today; no new build or migrations were required for these template links.

Main-agent staff review: the incremental links fit the existing presentation architecture
and preserve project/scenario identity. AppSec review: anchors submit no form and confer no
authority; existing scoping, CSRF and governed profile/publish controls remain unchanged.
SRE review: only cached web templates needed reload; no new worker/provider/data path.
Existing unrelated working-tree changes were preserved. Final report file set for this
follow-up: four templates above, user guide, master plan, task plan/inventory/verification.

The complete section 10 lifecycle matrix below is still outstanding. Today's browser work
was read-only navigation, not upload/publish/promote/grant/purge testing or a repeated
ten-role browser gate. Existing automated denial/isolation cases passed today on both
SQLite and PostgreSQL. The earlier repository-wide mypy gap was not reassessed; console
mypy passes. No secret/dependency scanner or new lifecycle acceptance claim is made.
Status remains **Implemented**, with navigation evidence; full acceptance and owner UX
review remain required before Verified/Completed. No commit or push performed.

## Previous implementation evidence (2026-09-08)

Status: Implemented; navigation verification below passed. The full repository section 10
lifecycle gate remains incomplete; do not treat these navigation checks as a release pass.

- Existing substantial dirty working tree identified; prior changes preserved.
- Read section 0 and canonical Compose. All app roles running; PostgreSQL/Redis/MinIO
  healthy; `/v1/health/live` returned `{"status":"ok"}`.
- Live in-app browser already authenticated as local admin. Navigation inspection is
  read-only. No credential retrieval/change or test-account creation required.
- Initial finding: scenarios route redirects to projects; no Scenarios sidebar entry,
  no server-rendered current-section markers. Existing scenarios template is unused.

## Implemented behavior and review

- Scenario index uses existing `scoped_scenarios` + validated active organization, optional
  scoped project UUID/search/status filters, stable ordering, 25-row pages, 200-project
  selector cap with visible explanation. Creation affordance uses existing exact
  SCENARIO_CREATE checks and the canonical project creation route.
- Shared presentation context maps route families to sections. Added Scenarios, organization
  administrator Tests and exact-approver Approvals entries without changing authority.
- Parent links in shared shell; corrected project/scenario/release/artifact breadcrumbs;
  Studio returns to its scenario; run detail links its already-authorized scenario;
  scenario-owned evaluation results retain scenario navigation. Platform links retention GET.
- Mobile menu expands into two columns, supports keyboard/Escape, and remains visible without
  JavaScript. Page-section links retain normal anchor behavior with aria-current=location,
  including browser back/forward; no lifecycle forms were hidden or actions combined.
- Staff review: existing Django presentation reused, no package or public API changes.
  AppSec: no scope-policy edits, foreign filters fail closed, names/search escaped, parent
  destinations come from named routes rather than untrusted return parameters. SRE: no
  worker/provider mutation, liveness and compatible ingestion worker verified; rollback
  is restricted to this task's hunks because the working tree contains unrelated work.

## Automated evidence

All commands run from repository root with the existing Python 3.13.5 virtual environment.

| Check | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest apps/console --basetemp=.tmp/pytest-console-navigation-final` | 348 passed, 1 skipped (concurrent-writer test requires PostgreSQL), 150.71 s |
| PostgreSQL selected navigation/UX/accessibility suite, below | 72 passed, 78.97 s |
| Candidate/artifact regression after type-only cast | 16 passed, 31.90 s |
| `.venv/Scripts/ruff.exe check apps/console` | Passed |
| `.venv/Scripts/ruff.exe format --check apps/console` | 58 files formatted |
| `.venv/Scripts/mypy.exe apps/console` | Passed, 58 files |
| `npm --prefix frontend run build` | TypeScript and Vite passed; current ignored builder bundle rebuilt |
| `manage.py check` with config.settings.test | No issues |
| `manage.py makemigrations --check --dry-run` with config.settings.test | No changes detected |
| `python -m compileall -q apps/console` and `git diff --check` | Passed |
| Compose ingestion preflight with --require-worker | ok; contract=3, compatible_worker=yes |

PostgreSQL profile: `DJANGO_SETTINGS_MODULE=config.settings.local`, local Compose PostgreSQL
at port 5433, Redis at 6379, MCP and metrics enabled with synthetic test-only metrics value,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; `pytest -p pytest_django.plugin` on
`test_navigation.py`, `test_phase_2_8_part_1.py`, `test_console_ux_overhaul.py`, and
`test_console_accessibility.py`; basetemp `.tmp/pytest-console-navigation-postgres`.
Pytest created its isolated test database; application data was not reset.

Initial failures were addressed, not hidden: a new test incorrectly assumed organization
administration allowed scenario creation (fixture corrected to include actual project
administrator duty); two legacy navigation expectations required the retired redirect
(replaced with positive scoped-list/isolation assertions); the new mixed query-value test
was made type-correct. A pre-existing artifact-usage key typing failure was repaired by
an explicit cast after membership succeeds, with no runtime change.

The broader `mypy apps` also reported six errors outside this task, in historical migration
tests: `identity/tests/test_assignment_migration.py:48` (lazy model reference) and
`catalog/tests/test_part_3_owner_migration.py:47,64,66,68,73` (historical role/owner fields).
These untouched files remain a repository-wide type-check gap. The seventh error from that
attempt was in the new query-value test and has been fixed; console-wide type checking passes.

## Browser and page coverage

- All 44 console templates inventoried, including named destinations, shared partials and
  dormant templates: [page-inventory.md](page-inventory.md).
- Traversed 45 normalized live route shapes/variants (including redirects) through observed
  links, selecting representative records rather than every record. Main lists, project,
  scenario, document set, document, preview, source/connectors, consumer, run, Studio,
  scenario tests, question set, release/artifact, health, member and platform forms visited.
- No missing local fragment targets found on visited pages. Live and isolated browser
  console error/warning logs were empty at review. No live form was submitted to create,
  publish, activate, purge, change access or credentials; live inspection was read-only.
- Existing selected samples had no evaluation-result history links. Persisted evaluation
  result and transient one-off-result/token-reveal screens were inspected in source/tests,
  not claimed as live browser visits. Login/404 tested in the synthetic environment.
- Repository-owned `scripts/run_phase_2_9_browser_gate.py` seeded an isolated SQLite fixture
  and ran at 8011. Used `localhost` for its cookies; real application session at 127.0.0.1
  remained intact. The gate was restarted once for fresh Python code; no real account changed.
- Ten synthetic identities exercised: viewer, editor, releaser, runtime operator, approver,
  content reader, document manager, unassigned member, foreign-organization viewer and
  organization admin. Viewer/runtime saw one assigned scenario; content reader/document
  manager/unassigned saw zero; editor/releaser saw their three assigned scenarios; foreign
  viewer saw its one foreign scenario. Menu groups matched these duties. Creation was
  disabled without project-create authority. Organization admin did not gain that authority.
- Viewer direct same-tenant sibling and cross-tenant scenario URLs returned safe 404 screens.
  POST/invalid UUID/forged active-organization/negative creation and scoping regressions
  are covered by real Django test clients; they were not browser-scripted forged POSTs.
- Live `KAP` search produced two matches; pagination rendered 25 of 30 scenarios. Filter
  preservation and invalid inputs passed automated tests. On a synthetic scenario, section
  link changed `#documents` and current location; browser Back restored `Adımlar`; Studio
  mounted current bundle and rendered canonical scenario/list return links without errors.
- Responsive synthetic page checked at requested 390/900/1440 widths; reported document
  client widths 375 (scrollbar excluded), 900, 1440, with no document horizontal overflow.
  Menu toggle visible only at small breakpoints; open/Escape/focus return worked. The live
  visible Codex panel remained about 443 px despite requested viewport overrides, so the
  exact breakpoint evidence comes from the hidden synthetic page, not that visible panel.
- Click assessment: desktop sidebar → scenario list is one click; a scenario opens in one
  further click. Mobile adds one menu expansion. Parent and Studio-return actions are one
  click. Contextual new-scenario path retains project selection and server authorization.

## Section 10 matrix: limits of this increment

| Row | Evidence / remaining work |
| --- | --- |
| 10.2.1 Shell | Logged-out/login/logout and ten role menus exercised; active scope tested with database fixtures |
| 10.2.2 Membership | Forms visited; automated denial/last-admin regressions passed; browser create/change/revoke not rerun |
| 10.2.3 Project/scenario | Lists/details/create forms/navigation and allow/deny exercised; browser lifecycle writes not rerun |
| 10.2.4 Studio | Editor opened current bundle and returned to scenario; edit/publish/AI lifecycle not rerun |
| 10.2.5 Artifacts/releases | Forms/detail/return routes visited, automated tests passed; browser compile/promote/rollback/canary not rerun |
| 10.2.6 Consumers | Lists/detail/forms visited; no credential issuance/binding mutation in browser |
| 10.2.7 Documents/index | Set/document/source/preview visited; upload/build/promotion not triggered in browser |
| 10.2.8 Runtime | Lists/details/parent routes visited and tests passed; live pause/cancel not triggered |
| 10.2.9 Approvals/destructive | Exact approver entry verified; no approve/reject/purge performed; destructive actions outside user task |
| 10.2.10 Profiles | Platform profile/grant forms and worker prerequisite checked; no new egress/profile mutation |
| 10.2.11 Routes/errors | Safe synthetic 404, no browser console errors; server-client negative tests passed; not every forged POST browser-run |
| 10.2.12 Audit | Existing console audit regressions passed; no new mutation/audit contract; full browser action/audit pairing not rerun |

Because shared navigation falls under the entire mandatory matrix, these gaps are retained
explicitly. Full lifecycle/browser acceptance remains pending; task is Implemented, not Verified.

## Final report

- Summary: real scenario entry point and cross-page navigation delivered.
- Files changed: navigation.py, context.py, targeted views.py hunks, console.js, shared shell;
  scenario/list/create, project, Studio, document section markers, release/artifact, run and
  platform templates; three navigation/UX test files; user guide, task records and master plan.
- Architecture impact: presentation-only module; Django/React split and existing URLs retained.
- Security impact: no controls relaxed; menu actions retain server checks.
- Authorization impact: existing scope/capability functions reused, no permissions granted.
- Data and privacy impact: no real records changed; synthetic browser/test databases retained.
- Logging, metrics, tracing and audit impact: no contract changes or sensitive logging added.
- Database and migration impact: none; migration drift check passed.
- Tests and verification results: results above; full matrix and repository-wide mypy gap explicit.
- Unverified assumptions: no claim that every data-dependent screen or lifecycle was browser-run.
- Remaining risks: 200-project selector cap; full lifecycle gate pending; six unrelated historical
  migration-test typing errors. Existing unrelated dirty changes were neither reverted nor adopted.
- Manual review required: owner UX acceptance and remaining section 10 lifecycle matrix before
  marking the increment Verified/Completed. No commit or push performed.
