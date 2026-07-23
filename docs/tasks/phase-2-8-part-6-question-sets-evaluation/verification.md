# Verification: Phase 2.8 Part 6 — Question sets and evaluation

> **Status: Not yet verified.**

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Question-set lifecycle | To be recorded | Not run | — | Draft/version/publish/concurrency |
| Retrieval metric fixtures | To be recorded | Not run | — | hit@k, recall@k, MRR, denominators |
| Answer assertion fixtures | To be recorded | Not run | — | Deterministic and schema/citation |
| LLM judge behavior | To be recorded | Not run | — | Optional provenance/error states |
| One-off question behavior | To be recorded | Not run | — | No aggregate mutation |
| Authorization/RLS | To be recorded | Not run | — | Set/run/evidence cross-tenant |
| Redaction/retention/audit | To be recorded | Not run | — | Content-free telemetry |
| Full quality/migration/browser | To be recorded | Not run | — | Ruff, mypy, Django, accessibility |

## Required evidence and human review

Record exact fixture calculations, numerator/denominator/error counters, immutable provenance,
provider failure behavior and browser evidence for chunks/scores. Staff reviews schema/aggregation;
AppSec reviews confidentiality/judge boundary/RLS; SRE reviews worker limits/retry/cost/retention; UX
reviews metric comprehension.

## Checks not run and remaining risks

None evaluated. Explicitly record unavailable live judge/model/browser/PostgreSQL checks and any
accepted nondeterminism before Verified.

## Final status

**Planned / not verified.**
