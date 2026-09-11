# Task Plan: Phase 2.5 Part 9 integrated hardening

## Objective

Complete the Phase 2.5 code-to-guide drift review, repair repository-owned deployment blockers,
run the integrated regression gates, record residual live-environment gates, and hand the verified
product-coherence scope to the separately approved Phase 2 production-hardening closure.

## Scope and acceptance criteria

- [x] Reconcile Parts 1–8 implementation and verification records with current product and manual
  testing documentation.
- [x] Repair the canonical Compose image build ordering so the supported full-stack topology can be
  built from the repository.
- [x] Run frontend, SQLite, PostgreSQL, static, migration and container-build gates without pytest
  quiet mode or a pytest timeout.
- [x] Exercise safe local synthetic health, authentication, protocol, invocation and rollback/disable
  paths through the integrated regression profiles where the environment permits it.
- [x] Record the Turkish owner acceptance journey separately from automated evidence.
- [x] Update Phase 2.5 and Phase 2 closure sources of truth without representing unavailable live
  provider or production evidence as complete.

## Trust boundaries and assumptions

- Browser and API inputs remain untrusted; server-side tenant, capability, protocol and release
  policy remain authoritative.
- Local demo data is disposable but is not production evidence.
- No real connector/model/OCR endpoint, credential, CA, firewall rule, production role or production
  dataset is created or changed without its concrete owner approval.
- Existing untracked personal tool configuration is outside this task and remains untouched.

## Risks and rollback

- Integrated UI drift can hide authorization or lifecycle controls; verify denial paths as well as
  happy paths and keep the owner journey explicit.
- A container image repair can change packaged content; build and start the canonical image, then
  verify migrations and health. Rollback is the single Dockerfile change.
- Live egress can disclose data or incur cost; use only approved synthetic inputs after concrete
  profiles and spend/retention approvals exist.
- Phase 2.5 may be closed on local evidence, but Phase 2 must remain open until every live closure
  gate has concrete evidence and manual sign-off.

## Verification record

Evidence and remaining manual gates are recorded in `verification.md`.
