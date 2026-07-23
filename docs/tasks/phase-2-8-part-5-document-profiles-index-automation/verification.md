# Verification: Phase 2.8 Part 5 — Document profiles and index automation

> **Status: Not yet verified.** Destructive cleanup requires a separate approval/evidence section.

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Set-only document lifecycle | To be recorded | Not run | — | Atomic upload/unbound denial |
| Chunking strategy matrix | To be recorded | Not run | — | Bounds and parser compatibility |
| BM25/vector/hybrid PostgreSQL | To be recorded | Not run | — | Ranking, scores and ACL parity |
| Summary generation | To be recorded | Not run | — | Provenance, failures, redaction |
| Build automation | To be recorded | Not run | — | Idempotency and no activation |
| Document-manager authorization | To be recorded | Not run | — | Positive/negative matrix |
| RLS/cross-tenant/grant tests | To be recorded | Not run | — | Non-owner PostgreSQL |
| Cleanup inventory/dry-run | To be recorded | Not run | — | No deletion |
| Cleanup apply/restore | Separate approval required | Not run | — | Exact targets and backups |
| Full quality/migration/browser | To be recorded | Not run | — | Ruff, mypy, Django, UX |

## Required evidence and review

Map profile fingerprints, search diagnostics, summary provenance, historical links, lifecycle truth,
authorization, redaction and audit to acceptance criteria. Staff reviews store/migration design;
AppSec reviews ACL/egress/cleanup; SRE reviews build capacity, retries, activation and recovery.

## Checks not run and remaining risks

None evaluated. Explicitly list unavailable live providers, PostgreSQL extensions, object-store or
browser checks. Do not mark Verified while cleanup evidence is claimed but not actually executed.

## Final status

**Planned / not verified.**
