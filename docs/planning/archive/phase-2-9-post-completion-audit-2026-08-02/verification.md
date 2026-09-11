# Verification: Phase 2.9 Post-completion Audit

## Closure update — 2026-08-02

The blockers and follow-ups recorded by this audit were subsequently closed. See the
[Phase 2.9 final closure verification](../phase-2-9-final-closure-2026-08-02/verification.md) for the configured
Gemini browser journey, full-suite evidence, role/tenant gate, cleanup and worker-ready topology.
The evidence below is preserved as the original point-in-time audit result.

## Result

Audit completed against committed HEAD `0e70306a829e1bf2d91a035cfaf661413b17908b` on 2026-08-02.
Parts 1-4, 6 and 7 are functionally present and their focused authorization, lifecycle, browser and
repository checks pass. Phase 2.9 cannot yet be marked completed: the required Part 5 configured
live Gemini browser smoke reached the provider but returned `candidate_invalid_json`, so no
transient candidate existed to inspect, repair or explicitly accept.

The earlier audit's three High findings and Medium findings 4, 5 and 7 are closed in product code.
Medium finding 6 is only partially closed: exact-editor visibility is fixed and response-format /
fence handling has automated coverage, but the approved real-provider acceptance still fails.
Medium finding 8 remains an intentionally deployment-dependent connector path; no connector egress
was authorized for this audit.

## Current-build automated evidence

| Check | Result |
| --- | --- |
| Frontend Vitest | 33 passed across 8 files |
| Frontend type/build | TypeScript passed; Vite 8.2.0 production build passed |
| Deterministic browser gate | 6 passed in 37.1 seconds using installed Edge/Chromium |
| Focused Phase 2.9 SQLite | 55 passed, 1 PostgreSQL-only skip |
| Focused Phase 2.9 PostgreSQL | 56 passed |
| Full SQLite | 1,102 passed, 61 skipped |
| Full PostgreSQL | 1,150 passed, 5 skipped; the 8 initial failures were caused by omitting canonical `MCP_ENABLED` / `METRICS_ENABLED` command variables, and all 14 affected tests passed when rerun with the canonical profile |
| Ruff | Lint passed; format check reports 456 files already formatted |
| Mypy | No issues in 443 source files |
| Django/schema | System check passed; migration drift reports no changes |
| Dependency audit | Not independently rerun because external registry metadata access was not approved; Part 7's committed evidence reports zero vulnerabilities |

No assertion was deleted, weakened or bypassed. The corrected PostgreSQL rerun used the canonical
test profile; the original command-profile error is retained here rather than represented as a
product defect.

## Provider and profile evidence

- Active local profiles existed before dependent tests: `audit-gemini-chat` r1 and
  `audit-gemini-embedding` r1 (3,072 dimensions).
- The approved key was read environment-only from the external deployment file and injected only
  into the local web container for the bounded test. Its value was never printed or written.
- AgentHub's model provider seam returned non-empty output with token accounting.
- AgentHub's embedding seam returned one normalized 3,072-dimensional vector.
- The exact scenario editor saw the AI planner on the live 8000 deployment. After entering one
  synthetic description and selecting `Geçici aday üret`, the UI returned the stable safe error
  that the provider did not return one valid JSON object. No prompt, response or candidate content
  is recorded here, and no candidate was persisted.
- Because generation failed, repair and accept were correctly unavailable. Replaying blindly was
  not attempted.
- Temporary provider/profile environment switches were cleared, web was recreated and returned
  HTTP 200; a boolean-only check confirmed all six temporary settings were empty. The temporary QA
  editor was deactivated and assigned an unusable password.

## Authorization and browser evidence

| Identity / journey | Current result |
| --- | --- |
| Scenario viewer | Only Home/Projects navigation; exact scenario readable; lifecycle disabled; direct Studio truthfully distinguishes no draft from active workflow v1 |
| Scenario runtime operator | Only exact scenario appears in runs; exact scenario runtime control is reachable; sibling/cross-tenant objects are 404 in browser/backend gates |
| Scenario release manager | Release detail and exact lifecycle control are reachable; disable produced `SCENARIO_NOT_ALLOWED`, re-enable restored a 200 completed invocation |
| Document content reader | Only Home/Documents navigation; bounded safe preview and attachment download are reachable; scenario access is 404 |
| Document-set manager | Exact retrieval action succeeds in the deterministic browser fixture; adjacent set and foreign tenant are denied |
| Scenario editor | Exact editor sees writable Studio and AI planner; viewer/unassigned/foreign denial remains server-enforced |
| Unassigned / foreign tenant | Direct exact-object probes return non-disclosing 404/403 according to route contract; no false navigation affordance appeared |

The release disable/enable check used only a disposable deterministic fixture. It proved that a
browser lifecycle transition changes gateway admission without direct database/bootstrap edits.

## UX and operational observations

- Responsive paths were reviewed at 390, 900 and 1,440 px; the deterministic gate also passed the
  keyboard skip-focus assertion. No functional horizontal-overflow failure was observed.
- Common exact-scenario lifecycle actions are reachable in at most three primary actions from
  scenario context. Preview and retrieval require about two primary actions after the target page.
- The runs page's organization-wide emergency-control explanation does not tell an exact scenario
  operator to use the scenario page; the distinction is correct but mildly confusing.
- Release detail links `Tüm release'ler` to the generic releases route that redirects to Projects.
  `Eksik release girdileri` is also shown when only the eval suite, rather than all inputs, is
  missing. Both are low-severity comprehension defects.
- The provider-disabled Studio copy calls absent deployment configuration `geçersiz`; `yapılandırılmamış`
  would be more accurate.
- The deterministic document fixture presents an impossible-looking combination: pending document
  parse, active index, deleted-profile label and successful retrieval; result rows also expose
  technical `None` placeholders. Product lifecycle integration tests pass, but this fixture weakens
  the browser proof and creates misleading UX evidence.
- Expected 403 responses still emit full Django tracebacks in local DEBUG logs. A watchfiles
  permission traceback for a nested worktree also remains. No HTTP 500 was observed.
- Canonical Compose inspection showed PostgreSQL, Redis, MinIO and web healthy; worker services were
  not present in the observed `docker compose ps` result, so background-worker readiness was not
  established by this audit.

## Security, data and operations review

- Staff engineering: exact-scope query and lifecycle ownership are covered at UI, service and real
  PostgreSQL layers; the remaining failing acceptance is isolated to real provider response shape.
- Application security: matched allow/deny and adjacency checks pass; raw provider content, secrets,
  tokens and document content were excluded from evidence. Server authorization remains independent
  of visible controls.
- SRE: health recovered after temporary configuration removal. No migration, dependency or lasting
  runtime configuration change was made. DEBUG denial tracebacks and absent worker readiness remain
  operational follow-ups.
- UX: critical controls are discoverable and role-aware, but the low-severity copy/link/fixture
  contradictions above remain.

## Unverified or blocked paths

- Part 5 repair and accept cannot be verified until live generation yields a valid transient
  candidate. This is blocked by observed provider-output compatibility, not missing authorization.
- Real connector profile/credential egress was neither configured nor authorized.
- GitHub-hosted CI execution was not observed; only the committed workflow and local equivalent ran.
- Production identity, data, grants, scale and topology are outside this local audit.
