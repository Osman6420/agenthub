# Threat Model: phase-2-9-part-4-governed-setup-immutable-inputs

## Assets and actors

Immutable contract/eval artifacts, platform model/embedding/connector profiles, endpoint and secret
references, tenant/document-set grants, connector source readiness, and audit evidence. Actors are
exact scenario editors, neighboring roles, tenant administrators, platform administrators,
inactive users, and attackers forging identifiers or form fields.

## Entry points and abuse cases

Artifact create/version POSTs; profile register/disable POSTs; tenant/document-set grant POSTs; and
connector setup GETs. Abuse includes schema/secret injection, arbitrary egress destination setup,
secret-ref disclosure, tenant self-grant, cross-tenant/forged-parent grant, role confusion, mutable
overwrite, duplicate/replayed revision, stale or disabled-profile use, and GET-side mutation.

## Controls

- Exact persisted scenario/document-set resolution and central authorization on every mutation.
- Platform-admin-only profile/grant workspace; tenant surfaces receive readiness labels only.
- Existing canonical profile, network-policy, artifact, JSON Schema, eval-suite, and inline-secret
  validators; no direct model writes in views.
- POST/CSRF, bounded fields/body, immutable revisions, status-only disable, and non-disclosing scope.
- Transactional row locks re-read embedding/connector status during grant, closing disable/grant
  TOCTOU and stale-object races.
- Transactional artifact audit and existing profile/grant audit record stable IDs and safe metadata,
  never destinations, secret refs, contract bytes, prompts, outputs, or tenant source inputs.
- Registration alone never opens egress; deployment, grant, source, allowlist, and runtime gates
  continue to fail closed.

## Failure and residual risk

Platform admins can intentionally configure approved destinations and secret references, so account
compromise remains high impact. Audit/service failures preserve existing fail-closed semantics.
Readiness metadata may become stale between GET and POST; the service revalidates current state.
No live external call was part of this task, so deployment-specific provider/network correctness
remains operational acceptance evidence rather than an application-unit assertion.
