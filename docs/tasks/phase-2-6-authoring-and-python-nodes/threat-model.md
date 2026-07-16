# Threat Model: phase-2-6-authoring-and-python-nodes

## Assets

- Tenant Python source, schemas, synthetic test data and review history.
- Application database, object store, secrets, service credentials, network and host runtime.
- Workflow state, document/retrieval data, tool outputs and release integrity.
- Tenant-scoped authoring catalog and immutable artifact/release lineage.
- Model budget, authoring prompt contract and transient candidate output.

## Actors

- Scenario author, organization admin, platform admin/reviewer and auditor.
- Consumer invoking an active release.
- Compromised/malicious tenant author, reviewer account, Python source or model provider.
- External sandbox runner and model/egress infrastructure operators.

## Entry points

- Scenario Studio Python-node draft/edit/test/submit and AI generation/save APIs.
- Platform review/activate/reject/change-request/disable APIs.
- Workflow publish, release compile and runtime isolated-node dispatch.
- Runner request/response channel and model-provider egress.

## Trust boundaries

- Browser/session to Django operator API.
- Tenant-scoped database queries to authoring-context snapshot.
- Django/worker control plane to isolated untrusted-code runner.
- Untrusted source/input to runner interpreter/container/kernel boundary.
- Runner output/model output to canonical validators and workflow state.
- Platform-admin review UI to immutable exact-checksum decision.

## Data classifications

- Python source and test payload: confidential tenant content; may accidentally contain secrets.
- Workflow/document/tool state: confidential, potentially restricted personal/business data.
- Safe catalog names/descriptions/schema summaries: tenant-confidential metadata.
- Checksums, statuses, bounded counts and stable reason codes: audit-safe metadata.

## Authentication

- Console APIs use existing authenticated operator session and CSRF controls.
- Runner channel requires platform service authentication, replay protection and destination pinning;
  tenants cannot call it directly.
- No public consumer endpoint grants authoring/review/source access.

## Authorization

- Scenario authors operate only in authorized active organization/project/scenario scope.
- Organization admin sees safe metadata/status only by default.
- Only platform admin may inspect source for review and decide/activate/disable.
- Auditor is read-only and cannot access source or raw test data.
- Every decision is re-authorized under transaction and binds exact revision/checksum.
- Runtime/release re-resolves active exact revision; workflow JSON is not authority.

## Tenant isolation

- All persistent records carry direct organization lineage and same-tenant constraints.
- Querysets derive tenant from authorized scenario/object, never request body or model output.
- PostgreSQL FORCE RLS/non-owner tests cover drafts, revisions, reviews, tests and activations.
- Context construction and node catalog use one authorized organization/scenario and deny foreign refs.

## External systems

- Isolated Python runner/sandbox and its container/kernel/image supply chain.
- Platform-managed authoring model endpoint through existing SSRF-safe profile transport.
- Optional source blob storage selected by ADR.

## Abuse cases

| Threat | Required mitigation |
| --- | --- |
| Isolation escape via Python/reflection/runtime behavior | No in-process execution; minimum separate non-root credentials-free/network-denied resource-limited runner, patched image, capability denial and escape tests; stronger gVisor/Kata/microVM only if spike/policy requires |
| Source reads DB credentials/env/service token | Runner contains none; minimal one-time request, clean env, no service-account token |
| Network exfiltration/SSRF | Default-deny runner network at infrastructure layer; no proxy/DNS; egress probes in verification |
| Filesystem/host escape | Read-only minimal root, isolated bounded scratch, no host mounts/devices, non-root UID |
| Fork/resource/output bomb | CPU/wall/memory/PID/scratch/output/concurrency limits and forced termination |
| Unsafe module requested/approved | Platform-owned closed module allowlist; requested set must be a subset; review cannot widen deployed policy |
| Automated review misses unsafe behavior | Treat it as defense in depth, pair with human review and runtime isolation/limits, version the rules and maintain adversarial tests |
| Critical finding bypassed by reviewer | Enforce block in service/database transition; warnings alone permit bounded platform-admin rationale |
| Code/schema swapped after review | Immutable revision; decision binds canonical checksum; any edit creates new revision |
| Self-approval or org-admin approval | Platform-admin-only decision and separation-of-duties policy; audited denial tests |
| Disabled/foreign node pinned or run | Compile and runtime active/org/revision/checksum resolution; deny by default |
| Source/secret logged | Content-free errors/events; source and raw IO excluded from logs/audit/traces/model context |
| Malicious runner output overwrites authority state | Output schema plus protected-key typed merge allowlist; runner output untrusted |
| AI context crosses tenant | Server-derived scenario scope, bounded scoped queries, golden non-disclosure/cross-tenant tests |
| AI learns endpoint/source/document content | Explicit context projection allowlist; no generic serializers; response snapshot tests |
| Prompt injection creates authority | System/context/user separation; prompts never authorize; every ref live-validated |
| Model invents node/tool/ref | Strict union schema and membership check against snapshot plus live state |
| Capability changes after generation | Revalidate at response/save/publish/release; return safe capability-drift diagnostic |
| AI generation silently persists/overwrites | Generation service has no persistence path; explicit save intent and expected revision required |
| Browser persistence exposes candidate/source | Memory-only initial design; no local/session storage; dirty-navigation warning |
| Review UI XSS from source/description | Contextual escaping, no HTML rendering, CSP review, bounded plain text/source viewer |
| Runner request replay/substitution | One-time execution ID, request checksum, expiry/idempotency and response binding |
| Ambiguous runner outcome retried | Classify `outcome_unknown`; Python node is pure/no side-effect by policy, but no blind duplicate if protocol cannot prove it |

## Failure cases

- Runner unavailable, image mismatch, authentication failure, timeout/OOM, malformed response or
  cancellation race.
- Model timeout/rate limit/invalid JSON/invalid union/`outcome_unknown`.
- Review audit failure, activation race, stale revision or disable during queued execution.
- Context section over budget, schema too deep or capability removed between snapshot and save.
- Browser refresh closes an unsaved candidate.

All failures are fail-closed with stable Turkish-mappable codes. Audit persistence failure for review,
activation and disable is fail-closed.

## Logging and audit risks

- Tracebacks, source excerpts, raw model output, test payloads and runner stderr may contain secrets.
- High-cardinality node/run IDs can overload metrics.
- Review comments may copy sensitive source.

Store only actor/tenant/target IDs, revision/checksum, decision/outcome, bounded counts, resource
usage and safe reason code. Review comments are bounded plain text with explicit warning and access
control; source/test/model content is not an audit field.

## Mitigations

- Minimum-runner spike/ADR is a hard gate; language-level and human review alone are rejected.
- Automated review is mandatory, checksum/rule-set bound and blocks critical findings; human review
  remains mandatory. Stronger sandbox technologies are optional unless the spike/policy requires.
- Separate runner identity/topology, no ambient authority, network deny and resource quotas.
- Immutable checksum-bound revision/review/activation records and server identifiers.
- Explicit role matrix, RLS, same-tenant constraints and live revalidation.
- Closed schemas/module lists/mapping rules and protected workflow state.
- Deterministic bounded context projection and strict model result union.
- Memory-only transient candidate and explicit atomic save/update/copy.
- Independent kill switches for authoring, testing, execution and AI generation.

## Residual risks

- Container/kernel sandbox vulnerabilities cannot be eliminated; patch ownership and defense in depth
  are required.
- Human review may miss malicious logic even when isolation prevents platform compromise.
- Source may encode sensitive literals; detection cannot guarantee absence.
- Model context summaries may omit information and produce lower-quality or missing-capability results.
- Memory-only candidates are lost on refresh/crash by design.

## Required security tests

- Complete role/action matrix, CSRF/authn, disabled-org and cross-tenant object/reference denial.
- Automated review rule-set/checksum binding, critical non-bypass, warning rationale, scanner failure
  fail-closed and rule-set upgrade/re-review behavior.
- Checksum substitution, stale decision, edit-after-review, self-approval and disable race.
- Runner escape corpus covering network, filesystem, env, process, reflection/import, serialization,
  infinite loop, memory/PID/scratch/output bombs and malformed results.
- Runner protocol replay, expiry, idempotency, cancellation and response-checksum binding.
- Protected-state overwrite and schema bypass tests.
- Context foreign-row, secret/endpoint/source/document non-disclosure and size/depth exhaustion.
- Prompt injection, invented/stale refs and user-supplied tenant/authority attempts.
- Assert generation performs no writes and save re-authorizes/validates atomically.
- Logs/audit/traces contain no source, raw IO, raw model output, secret references or endpoints.
