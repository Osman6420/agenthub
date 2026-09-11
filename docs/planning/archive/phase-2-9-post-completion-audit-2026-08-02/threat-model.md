# Threat Model: Phase 2.9 Post-completion Audit

## Assets and trust boundaries

- Tenant/scenario/run/document/release metadata and document bytes.
- Operator sessions, consumer credentials, provider secrets, and profile/grant configuration.
- Browser/UI as an untrusted client; server authorization and PostgreSQL RLS as enforcement layers.
- External Gemini egress through governed provider profiles only.

## Threats under test

- Same-tenant cross-scenario or cross-set disclosure.
- Cross-tenant object discovery or mutation.
- UI-hidden action invoked by forged URL/POST.
- Partial scenario/index lifecycle state reported as successful.
- Secret, prompt, provider output, document content, traceback, or route-list leakage.
- Tenant-controlled provider destination or unsafe active-content preview.

## Controls

- Matched allow/deny actors, exact adjacent objects, cross-tenant probes, and direct route requests.
- Synthetic data, no database reset, no destructive operation, and no uncontrolled egress.
- Secret-safe prerequisite checks and bounded provider smoke.
- Current-build browser console/network inspection plus PostgreSQL non-owner tests.

## Residual risk

Production identity, deployment grants, live connector endpoints, and production-scale behavior are
outside this local audit and remain deployment acceptance concerns.
