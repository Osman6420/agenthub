# Threat Model: scenario-studio-authoring-journey-closure-part-2

## Assets and trust boundaries

- Tenant artifact bodies, exact versions, checksums, logical descriptions, document-set form state.
- Platform model/embedding/OCR profile identity and safe operational metadata.
- Restricted provider endpoints, paths, secret references, TLS, network and egress configuration.
- Browser/session/CSRF, tenant/document authorization, tenant-to-platform catalog, mutable author state
  to immutable publication, and staged-index submission boundaries.

## Abuse and failure cases

- Guess a foreign artifact/profile/document-set ID or submit a foreign choice.
- Smuggle endpoint/credential fields into a model reference or advanced JSON.
- Use document management to provision/disable/grant a platform profile.
- Publish invalid retrieval weights/chunk sizes or bypass canonical validation.
- Lose unrelated form selections during inspection, or bind a stale/foreign returned version.
- Leak body/profile secrets in HTML, JSON, diagnostics, logs, audit, or browser storage.
- Publish succeeds while return/selection fails; concurrent authors race on N+1.

## Mitigations

- Exact server-side scope and responsibility checks; non-disclosing foreign-ID handling and CSRF.
- Closed safe serializers and forms; model artifact accepts only a server-selected active UUID.
- Canonical artifact validators, body bounds, inline-secret checks, immutable checksums and tenant-row
  version allocation lock.
- Platform mutations remain on existing platform-admin services/routes.
- State return values are signed/server-validated or kept in the originating browser form; returned
  IDs are re-resolved in exact organization/type scope.
- Safe audit identifiers/checksums only; no body, prompt, endpoint, path, secret, or form payload.
- Transactional publish/audit and explicit reconciliation message after ambiguous client failure.

## Required security tests

- Authentication, CSRF, viewer denial, document-manager allow, missing responsibility, cross-tenant
  and wrong-type IDs.
- Unknown-field, bounds/weight, secret-like value, stale revision, concurrent N+1, immutable source,
  audit rollback/redaction, safe HTML/JSON rendering, and platform-management denial.

## Residual risk

- Safe provider/model names can still be tenant-sensitive operational metadata; access remains scoped.
- Authorized document managers can create new tenant artifact versions that other workflows may later
  choose, but cannot alter existing exact pins or activate an index by publication alone.
