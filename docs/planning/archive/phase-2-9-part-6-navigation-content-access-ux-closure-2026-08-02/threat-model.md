# Threat Model: phase-2-9-part-6-navigation-content-access-ux-closure

## Assets and actors

Responsibility assignments, console route discovery, immutable release pins, consumer capabilities,
document metadata and raw bytes, storage object keys, audit evidence, and browser-transient edits.
Actors include exact scenario/document operators and viewers, organization/platform administrators,
unassigned and foreign users, compromised browsers, and malicious uploaded content.

## Entry points and abuse cases

Sidebar links, console 403/404 responses, manifest/capability preset controls, document detail GET,
version preview/download GET, and browser navigation with dirty transient state. Abuse includes using
hidden links as authorization, forged set/document/version hierarchy, cross-tenant reads, metadata-
viewer content escalation, MIME-sniffed active content, response-header injection, huge object reads,
storage/audit failure leakage, ambiguous preset auto-selection, capability escalation, and silent
loss of manifest choices.

## Controls

- Navigation derives from scoped querysets/exact responsibilities but remains non-authoritative.
- Content endpoints re-resolve set, document, and exact version and require
  `DOCUMENT_SET_CONTENT_READ`; metadata-only actors receive 403 and foreign parents remain 404.
- Byte-size checks precede storage reads; returned bytes are rechecked. Preview is UTF-8 text-only,
  escaped by Django, bounded, and wrapped in a restrictive page. Download uses a server-built safe
  filename, `attachment`, `application/octet-stream`, `nosniff`, `sandbox`, and no range/inline path.
- Success and denial/failure audit contain IDs/counts/MIME/reason only. Audit failure is fail-closed
  before any response containing document bytes.
- Manifest recommendations include only unambiguous scenario-owned immutable versions. Exact IDs,
  versions, checksums and roles remain visible; preflight/compile/promotion stay separate.
- Capability presets are closed server-owned allowlists and must match the visibly submitted exact
  checkbox set; central model validation still rejects unknown values.
- Dirty-state guidance exposes candidate-save, discard, and continue choices and retains the native
  unload guard as defense in depth.

## Failure and residual risk

Authorized Content Readers can intentionally exfiltrate content they are allowed to read; this is a
business permission, not preventable by UI. In-memory response construction is bounded but not
streaming. Browsers control native unload-dialog wording, so visible in-page guidance supplies the
product choices. Recommendation presets reduce clicks but cannot determine operator intent when
multiple logical artifacts exist; those roles remain manual by design. Manual responsive/keyboard
acceptance remains necessary even with DOM and frontend assertions.
