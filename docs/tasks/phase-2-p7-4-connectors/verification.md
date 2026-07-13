# Verification: Phase 2 · P7.4 connectors planning

## Status

**Documentation only — not implemented or runtime-verified.** The Confluence Data Center design,
trust boundaries, approval gates, acceptance criteria, and generic REST contract gate are recorded
in the task plan and threat model. No connector code, migration, dependency, egress rule, secret,
certificate, IAM policy, network policy, or firewall behavior is changed by this task.

## Documentation checks

| Check | Result |
| --- | --- |
| Local Markdown links across P7.4, parent P7, and OCR contract docs | Pass — six files checked |
| `git diff --check` | Pass |
| Trailing-whitespace scan across reviewed docs | Pass |

These checks establish document integrity only; they are not evidence that P7.4 functionality
exists.

## Checks not run

- No Confluence or generic REST unit/integration test: neither connector is implemented.
- No live Confluence request, DNS lookup, TLS handshake, secret resolution, or service-account test.
- No migration, Django, authorization, RLS, object-store, Celery, or UI verification is attributable
  to P7.4 planning.

## Remaining gates

- Accept the narrow private-Confluence egress ADR/change boundary before implementation.
- Record the deployment-specific Confluence base URL/context path, Data Center version, corporate
  DNS/network policy, CA chain, firewall rule, secret reference, service-account scope, and limits
  before live rollout.
- Supply and approve the generic REST contract or explicitly re-scope it in authoritative plans.

## Manual review required

Review and accept the recommendation in the plan's **Manual review recommendation** section. In
particular, confirm that Confluence permissions become an upstream import boundary rather than
per-user serving ACLs after content is copied into AgentHub.
