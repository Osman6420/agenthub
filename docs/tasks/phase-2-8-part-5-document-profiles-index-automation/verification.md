# Verification: Phase 2.8 Part 5 — Document profiles and index automation

> **Status: Implemented and repository/PostgreSQL verified.** Destructive cleanup remains a
> separate approval and was not performed. The requested authenticated browser walkthrough is
> pending because the in-app browser transport could not be reconnected in this session.

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Set-only lifecycle, profiles, summaries, automation and dry-run | `pytest` over the Part 5 console/document/ingestion/retrieval targets with test settings | Pass | 24 passed, 1 PostgreSQL-only skip on SQLite; covered again by both full suites | Covers atomic membership, standalone denial, all five chunk strategies and bounds, exact profile fingerprints, summary provenance/provider/size failure, idempotent staging and no activation |
| PostgreSQL pgvector/FTS, hierarchical/hybrid and ACL/RLS | Part 5 PostgreSQL targets with local PostgreSQL settings | Pass | 35 passed, 2 off-PostgreSQL-guard skips | Exercises real per-index pgvector/full-text stores, exact document/kind filters, summary-to-document-to-content routing, per-document cap, safe fallback, shared ACL/tombstone scope, staged preparation and non-owner FORCE-RLS isolation |
| Full SQLite repository regression | `.venv\Scripts\python.exe -m pytest --basetemp .pytest-tmp-part5-close-sqlite -q` | Pass | 985 passed, 59 PostgreSQL-only skips | Clean repository-wide regression after the final failure-matrix additions |
| Full PostgreSQL repository regression | Full `pytest` suite with local PostgreSQL settings | Pass | 1039 passed, 5 guard skips in 428.03s | Repository-wide real PostgreSQL, pgvector, constraint, locking and FORCE-RLS coverage |
| Formatter/linter/type check | `ruff format --check .`; `ruff check .`; `mypy .` | Pass | 429 files formatted; lint clean; 429 source files type-clean | Repository-wide |
| Django and migrations | `manage.py check`; `manage.py makemigrations --check --dry-run` with test settings | Pass | No system issues; no missing model changes | New migrations are additive and include FORCE RLS |
| Local rollout | Compose migration, application-role provisioning, `check_tenant_rls`, container preflight and health | Pass | Migrations `documents.0007` and `ingestion.0012` applied; 60 protected tables; preflight contract 2/config `95f1792b9591`; health HTTP 200 | Ingestion worker was restarted and reported ready; automatic preparation remains staged-only |
| Authenticated browser walkthrough | In-app browser against `http://127.0.0.1:8000/` | Blocked | Browser transport retained an obsolete runtime and closed during the safe reconnect attempt | No visual, responsive or keyboard claim is recorded |
| Cleanup inventory/dry-run | Part 5 unit coverage for `inventory_unbound_documents` | Pass | Exact safe IDs/counts only; `cleanup_authorized=false` | No content, object keys or secrets emitted; no mutation |
| Cleanup apply/restore | Separate approval required | Not run | No deletion performed | Retention/legal-hold and backup/object-store proof remain prerequisites |

## Acceptance evidence

- Every new normal upload path supplies an exact draft set version; document/version creation and
  membership are one transaction. The standalone console/API path fails with
  `UNBOUND_DOCUMENT_DENIED`.
- New staged indexes pin exact chunking and retrieval artifacts/checksums. Optional summaries pin
  exact model and prompt artifacts, store a checksum and stable failure code, and never place
  content in audit events.
- PostgreSQL keyword and vector retrieval use the same immutable per-index FORCE-RLS store and the
  same tenant, consumer grant, scenario grant, active-index and tombstone intersection. Hybrid
  ranking exposes vector, keyword and fused diagnostics without pretending raw scores are directly
  comparable.
- Opt-in `summary_document_top_k` routing searches only authorized summary chunks to select exact
  live document versions, then searches only their source `content` chunks. Results persist
  `summary_routed`/`summary_fallback` diagnostics and routing scores, never return a summary as
  grounding in this mode, and enforce the bounded `max_chunks_per_document` diversity cap.
- Automatic preparation is idempotent and creates only a staged build job. Activation remains a
  separate authorized action.
- Historical set/document/index versions have exact deep links, and lifecycle readiness is derived
  from actual upload, parse, publish, staged and active state.

## Staff engineer, AppSec and SRE review

- **Staff engineer:** additive nullable provenance fields preserve historical indexes; fingerprints
  version the new exact-profile contract; migrations, role grants and current-state docs agree.
- **AppSec:** set-bound creation is fail-closed; profile tenant/type checks and shared retrieval ACL
  scope prevent authority widening; SQL relation names remain integer-derived and values bound;
  summaries/audits are content-free. No critical/high finding remains.
- **SRE:** duplicate auto-preparation is idempotent, failures remain visible, and workers never
  change the active pointer. Existing active indexes survive staged-build failure. No critical/high
  operational finding remains.

## Checks not run and residual risk

No live external LLM/embedding provider, completed authenticated browser walkthrough, object-store
reconciliation, destructive cleanup, backup or restore drill was run. Provider quality/capacity and
manual responsive/accessibility behavior therefore remain deployment review items. The local
PostgreSQL migrations, application-role grants, RLS readiness, ingestion preflight, worker restart
and health check passed; production rollout remains an operator-controlled deployment step.
Runtime metadata filtering is intentionally not part of Part 5: the owner moved it to Phase 3 on
2026-07-28. The accepted `metadata_filter` contract field is documented as a reserved no-op and
cannot be treated as an authorization or result-narrowing control.

## Final status

**Implemented and repository/PostgreSQL verified; browser acceptance remains pending. Destructive
cleanup apply was not authorized or run.**
