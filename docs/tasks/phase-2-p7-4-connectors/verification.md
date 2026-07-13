# Verification: Phase 2 · P7.4 connectors

## Status

**P7.4a Confluence implemented and verified offline on 2026-07-13.** P7.4b generic REST remains
contract-gated and unimplemented, so P7.4 as a whole remains open. No live Confluence hostname,
credential, corporate CA, DNS policy, firewall rule, or socket was configured or exercised.

## Acceptance evidence

- ADR-0006 keeps all existing model/embedding/OCR/tool destinations public-only and introduces a
  separate, deployment-owned private-CIDR policy exclusively for immutable Confluence profiles.
- Platform-admin profile registration/grant/disable and same-tenant author source/sync operations
  enforce exact profile + document-set scope. Denials and state changes are audited without endpoint,
  IP/CIDR, secret, title, page body, or upstream error content.
- The stdlib Data Center client constructs only fixed REST paths, validates every DNS answer, pins
  the selected IP while preserving TLS SNI/Host, denies redirects, ignores response links, resolves
  bearer secrets only at call time, and bounds traversal/depth/requests/pages/body/total bytes.
- Incremental snapshot sync reuses unchanged versions, persists changed HTML through the existing
  tenant object-store service, reconciles missing pages only after a complete snapshot, and creates
  a DRAFT document-set candidate without automatic build, publish, or promotion.
- Additive lineage/grant/run tables use FORCE RLS and transaction-local tenant context. A worker
  cannot claim a foreign-tenant run even if handed its primary key.
- The legacy one-shot connector path fails closed, preventing bypass of governed sync lineage.

## Checks and evidence

| Check | Result |
| --- | --- |
| `ruff format --check .` | Pass |
| `ruff check .` | Pass |
| `mypy apps config` | Pass |
| `manage.py check` | Pass |
| `makemigrations --check --dry-run` | Pass — `ingestion.0007` current |
| Targeted SQLite Confluence/egress/legacy ingestion | Pass — 41 passed, 2 skipped |
| Targeted PostgreSQL including FORCE RLS | Pass — 42 passed |
| Full SQLite suite | Pass — 541 passed, 23 skipped |
| Full PostgreSQL suite | Pass — 562 passed, 2 skipped |
| `git diff --check` and final staff/AppSec/SRE diff review | Pass |

Tests cover exact-private allow, public/unlisted/mixed/loopback denial, private corporate FQDNs,
fixed paths, malicious links, retry/redirect behavior, response ID mismatch, governance/redaction,
ungranted and cross-tenant denial, immutable bindings, incremental/partial/recovery behavior, draft
candidates, worker tenant context, PostgreSQL FORCE RLS, and the legacy-path denial.

## Checks not run

- No live Confluence request, corporate DNS lookup, TLS handshake/CA validation, secret-store
  resolution, service-account permission check, firewall verification, Celery broker delivery, or
  production object-store call.
- No browser/console workflow exists for P7.4a; operations use management commands.
- No generic REST implementation or test; its contract is intentionally unknown and disabled.

## Residual risk and rollout gate

The live deployment must record the actual base URL/context path, supported Data Center version,
DNS answers/private CIDRs, corporate CA chain, firewall destination, injected PAT reference,
least-privilege account roots, and operational limits. Test one allowed root and one deliberately
out-of-scope page before enabling scheduled sync. Confluence ACLs are an upstream import boundary;
copied content is subsequently governed by AgentHub document-set/release/consumer ACLs.

## Manual review required

Approve the environment-specific profile/network/CA/secret/service-account configuration before
live rollout. Separately provide and approve the generic REST contract or explicitly re-scope P7.4b
in the authoritative plans.
