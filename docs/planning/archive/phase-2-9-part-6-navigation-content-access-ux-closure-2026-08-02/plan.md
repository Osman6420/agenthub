# Task Plan: phase-2-9-part-6-navigation-content-access-ux-closure

## Task summary

Complete Phase 2.9 Part 6 by making the console responsibility-aware, reducing release/client setup
effort, explaining transient state, and adding exact-authorized safe document preview/download.

## Scope

- Show primary navigation only when the actor has an applicable exact responsibility or a creation/
  administration path, while preserving every direct-route server authorization check.
- Correct remaining truthful-state, Turkish-first label/timestamp, duplicate-action, empty/error, and
  local console 403/404 guidance issues verified against current code rather than stale audit state.
- Add a release-manifest recommendation preset that selects only unambiguous scenario-owned latest
  immutable versions, keeps exact IDs/checksums visible, and still requires canonical preflight and
  explicit candidate compilation.
- Explain transient dirty manifest state and expose explicit save-as-candidate, discard, and continue
  choices before the browser unload guard.
- Add reviewed consumer capability presets whose submitted exact capability list remains visible,
  allowlisted, and server-validated.
- Add Content Reader/Manager document-version preview/download with exact set authorization, bounded
  reads, safe textual preview, attachment-only download, conservative MIME/disposition headers,
  no-sniff/sandbox controls, fail-closed audit, and content-free errors.
- Verify keyboard/focus/responsive/error/empty states and measured primary-action counts.

## Non-goals and approval boundaries

- No role/capability vocabulary, authentication, public API, schema migration, dependency, storage
  backend, secret, network, or lifecycle-policy change.
- No inline rendering of PDF, HTML, SVG, XML, Office, executable, or unknown content; download is
  always attachment. No object key, presigned URL, content body, or filename from storage is logged.
- No automatic release compilation/promotion, capability grant, or document access based on a UI
  preset. Recommendations never become authority.

## Trust boundaries and authorization

Navigation and preset state are usability only. Every target is resolved through existing scoped
querysets and every mutation/read invokes the central exact capability decision. Document version
IDs are untrusted and must match the already scoped document and set. Stored bytes, MIME metadata,
filenames, manifests, browser state, and query parameters are untrusted. UI hiding cannot replace a
403/404 boundary.

## Data, privacy, and operational impact

No new durable schema. Content reads create redacted audit events with actor, organization, set,
document version, operation, outcome, byte size, and stable reason only. Preview has a lower limit
and text allowlist; download has a hard size limit and attachment disposition. Storage/audit failure
returns no content. Presets and dirty selections stay browser-transient until existing canonical
mutations succeed.

## Implementation steps

1. Reconcile every Part 6 audit item with current templates, routes, permissions, tests, and styles.
2. Implement responsibility-aware navigation and safe console error guidance.
3. Implement exact Content Reader preview/download service boundary, routes, templates, and tests.
4. Implement manifest recommendations/checklist/dirty choices and consumer capability presets.
5. Normalize touched terminology/timestamps/actions and add keyboard/responsive/error-state tests.
6. Run focused, blast-radius, PostgreSQL/RLS, frontend/build, static/type/schema, and manual browser
   evidence; update current behavior/plans; archive and commit only after applicable acceptance.

## Rollback

Revert navigation/template/frontend routes and remove the two read-only content endpoints. Existing
documents, immutable versions, releases, bindings, capabilities, and audit history remain intact.

## Risks

False affordances, hiding a valid route, authorization drift, cross-set version lookup, content
exfiltration, MIME confusion, active-content execution, response splitting, oversized memory use,
object-key leakage, audit fail-open, ambiguous preset selection, silent capability escalation,
lost transient manifest choices, keyboard traps, and mobile overflow. Controls are central exact
authorization, trusted parent resolution, allowlists/bounds, attachment/no-sniff/sandbox headers,
safe server filenames, fail-closed audit, unambiguous recommendations, explicit review, and matched
allow/deny/cross-scope tests.

## Status

Completed 2026-08-02. Automated role/scope, content-safety, frontend, full SQLite and targeted
PostgreSQL/RLS evidence passed. Part 7 owns the explicitly separate target-browser visual,
keyboard, responsive and manual journey gate.
