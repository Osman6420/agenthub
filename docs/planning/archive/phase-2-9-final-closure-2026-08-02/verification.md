# Verification: Phase 2.9 Final Closure

## Result

Completed and verified 2026-08-02. The prior real-Gemini response-shape blocker and all actionable
post-completion audit residues were closed without changing role definitions, tenant boundaries,
public APIs, dependencies, migrations, retry policy, or automatic publication behavior.

## Live Gemini acceptance

- The approved Gemini secret was read environment-only from the external deployment file and
  injected temporarily into the local web service. Its value, endpoint, prompts, responses, and
  candidate content were not printed or recorded.
- An exact scenario editor completed Studio `generate -> inspect -> repair -> accept` using a
  synthetic two-node workflow. Generate returned a valid transient candidate (2,320 input tokens,
  72 output tokens, 268 candidate bytes); repair remained valid (2,539 input tokens, 74 output
  tokens, 268 candidate bytes); explicit accept created one mutable draft at revision 1.
- Safe request identifiers were `req_2b42150b81fe4beda94b04af27031af6` for generate and
  `req_424599b89f3e4697a62af9acb102e0e7` for repair. Diagnostic-code sets were empty.
- Gemini compatibility is restricted to the exact Google API host and to the workflow-envelope
  path. Other providers and direct artifact contracts retain the existing JSON-object mode.
- The temporary QA identity was deactivated and assigned an unusable password. All temporary model,
  embedding, provider and secret environment values were removed; the web service was recreated
  and returned HTTP 200.

## Authorization, browser, and UX evidence

- The deterministic Edge/Chromium gate passed all 6 journeys: responsibility-aware navigation,
  exact scenario/run allow-deny, same-tenant and cross-tenant non-disclosure, scenario callability,
  document retrieval, and keyboard focus.
- Exact scenario operators now receive contextual scenario-control links while organization/global
  emergency controls remain distinct. Release navigation targets the authorized release list and
  reports only the exact missing immutable inputs.
- Missing AI configuration is distinguished from invalid configuration. One-off retrieval results
  omit unavailable technical fields instead of rendering `None`; the fixture represents a parsed
  document, active embedding profile/index, and useful deterministic rank/score metadata.
- Expected Django 4xx warnings remain visible but no longer include exception tracebacks. A focused
  filter test proves Django 5xx and non-Django exception tracebacks are retained.
- Browser console warnings/errors were empty in the live Gemini journey. The responsive/keyboard UX
  baseline from Part 7 remains valid; the changed pages add direct guidance and remove misleading
  states rather than adding interaction steps.

## Automated evidence

| Check | Result |
| --- | --- |
| Focused backend regression | 25 passed |
| Frontend Vitest | 8 files, 33 passed |
| TypeScript and production build | Passed |
| Deterministic real-browser gate | 6 of 6 passed in 32.5 seconds |
| Ruff lint/format | 458 files clean/already formatted |
| Mypy | No issues in 456 source files |
| Django system/schema | `check` clean; no migration changes |
| Full SQLite | 1,106 passed, 61 skipped |
| Full PostgreSQL/RLS/MCP/metrics profile | 1,162 passed, 5 skipped |

After the final compatibility narrowing, the running Compose web service directly asserted that
only the Gemini workflow-envelope path selects JSON Schema while Gemini direct-artifact and other
provider paths retain JSON-object mode; Python compilation and `manage.py check` passed. The host
virtual environment could not launch because of the known Windows logon-session failure, and the
clean runtime image intentionally contains no pytest, so the already-passed full suites were not
duplicated after that one-line narrowing.

The final local Compose topology contained healthy `web`, PostgreSQL, Redis, MinIO,
`worker-runtime`, `worker-ingestion`, `worker-eval`, and beat services. The ingestion preflight
reported a compatible worker. Temporary development tooling installed only inside the local web
container was removed by the final service recreation.

## Security, operations, and data review

- Staff engineering: provider-specific behavior is host-scoped; transport contracts remain aligned
  across generation and repair; UI changes reuse central authorization decisions.
- Application security: all mutations remain independently server-authorized; model output stays
  bounded, exactly-one-object parsed, schema validated, transient until accept, and content-redacted
  from evidence. Denial and cross-scope tests remain green.
- SRE: expected 4xx noise is reduced without hiding warnings or 5xx; worker topology/readiness is
  now part of the documented local gate; health and cleanup were observed after recreation.
- Data/privacy: only synthetic local QA data was used. No production access, database reset,
  destructive migration, plaintext secret persistence, prompt/response logging, or candidate-body
  evidence occurred.

## Checks not independently repeated

The frontend dependency audit was not rerun in this final closure; Part 7's same-day archived
verification records zero vulnerabilities. Hosted CI execution and real connector credential/egress
remain deployment acceptance, not Phase 2.9 product-completion criteria.
