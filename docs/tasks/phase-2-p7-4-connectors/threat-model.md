# Threat Model — Phase 2 · P7.4 connectors

Scope: the implemented offline Confluence Data Center connector and the contract gate for generic
REST. This extends the parent P7 threat model; P7.1–P7.3 behavior is unchanged. Live corporate
network/identity rollout remains unverified.

## Assets

- Confluence service-account PAT and its secret reference.
- Corporate Confluence hostname, private network topology/policy, CA trust, and firewall boundary.
- Confidential tenant page content and immutable AgentHub document blobs/versions.
- Source→document-set binding, page/version lineage, sync state, draft candidate versions, and active
  release/index pointers.
- Tenant/document-set/consumer ACL and PostgreSQL RLS isolation.
- Audit, logs, metrics, and traces that must not expose content or infrastructure details.

## Actors

- Platform administrator registering/disabling profiles, selecting deployment-owned network policy,
  and granting profiles to a tenant.
- Tenant author managing same-tenant sources and starting a sync.
- Ingestion worker resolving profiles/secrets, traversing Confluence, and persisting documents.
- Confluence least-privilege service account scoped to one knowledge base.
- Consumer retrieving only release-pinned, granted AgentHub content.
- Malicious/compromised tenant user, Confluence page author, DNS responder, upstream server, service
  account, worker, or operator credential.

## Entry points

- Platform profile registration command/service accepting a base URL and secret/network-policy
  references.
- Tenant source configuration: profile ID, root page IDs, inclusion/exclusion, document set.
- Sync command/Celery task carrying database identifiers only.
- Corporate DNS, TLS handshake, Data Center JSON/HTML responses, status codes, and headers.
- Object-store and database writes for document versions, cursors, runs, and candidates.
- Future generic REST contract/configuration (disabled until approved).

## Trust boundaries

1. Platform operator input → immutable catalog/profile and deployment network-policy resolution.
2. Tenant source input → server-side profile/document-set authorization.
3. Corporate DNS → all-answer address-policy validation → pinned-IP TLS connection.
4. Confluence REST response → bounded JSON/HTML validation → tenant content plane.
5. Completed sync snapshot → reconciliation → draft candidate only.
6. Draft candidate → existing publish/build/eval/promote → release-pinned ACL/RLS retrieval.

No upstream field is an authorization or destination decision. No copied Confluence ACL is assumed to
remain authoritative after ingestion.

## Data classifications

- PAT/secret value: **secret/restricted**; resolve late, never persist outside the secret manager or
  log/audit/trace.
- Page bodies/titles and parsed text: **confidential tenant content**.
- Page/root IDs, version numbers, source/profile/document-set/run IDs: **internal metadata**; page IDs
  may still reveal corpus structure and are not metric labels.
- Base URL, host, private IP/CIDR, CA and firewall data: **restricted infrastructure metadata**.
- Counts, latency, stable status/error codes: **operational metadata** suitable for bounded telemetry.

## Authentication

- AgentHub operator authentication continues to use the existing LDAP/session/machine boundaries.
- Confluence Data Center calls use a Bearer PAT/service-account secret resolved from `secret_ref`.
- Username/password, cookies, client-supplied Authorization headers, and inline tokens are rejected.
- TLS authenticates the canonical corporate hostname through the deployment-installed CA chain; no
  verification opt-out exists.

## Authorization

- Only platform administrators may register/disable profiles, select network-policy references, or
  grant a profile to a specific tenant+document-set pair.
- Tenant authors may configure/start only same-tenant sources bound to same-tenant document sets and
  already granted active profiles.
- The upstream service account limits discoverable/importable pages but does not authorize serving.
  AgentHub scenario binding, release pinning, effective consumer grant, retrieval predicate, and RLS
  remain mandatory.
- A Confluence page becoming readable to the service account cannot select another AgentHub tenant or
  document set; placement comes only from the locked source binding.

## Tenant isolation

- Profile grants, source, document set, sync run/cursor, document, version, membership, and index all
  carry/check organization identity.
- Cross-tenant relationships are rejected in services, constrained where possible, and covered by
  FORCE RLS on new tenant tables.
- Celery receives IDs and reloads every authoritative object under transaction-local tenant context;
  task payloads cannot assert organization/profile/destination.
- Deterministic logical identity is namespaced by source; identical page IDs in two sources/tenants do
  not collide.

## External systems

- Corporate DNS resolver and network/firewall.
- Confluence Data Center REST API under a canonical HTTPS context path.
- Corporate PKI/trust store and secret manager/environment injection.
- Existing tenant-prefixed S3/MinIO object store and PostgreSQL database.
- Generic REST endpoint is not yet known and remains disabled.

## Abuse cases

| # | Abuse case | Required mitigation |
| --- | --- | --- |
| T1 | Tenant supplies an internal/admin/metadata URL or changes host/path/TLS | Source accepts profile ID/root IDs only; base URL/network/TLS are platform-only immutable profile policy. |
| T2 | New private support weakens all egress and exposes the corporate network | Separate Confluence-only address-policy seam; existing public-only validator/callers unchanged and regression-tested. |
| T3 | DNS rebinding or split/mixed DNS escapes the approved network | Validate every answer against the deployment-owned allowlist and prohibited-address classes; connect to the validated IP with canonical SNI/Host. |
| T4 | Redirect or response link pivots to another internal host | Deny all 3xx; ignore `_links` URLs and construct fixed paths/pagination locally. |
| T5 | Old `verify_ssl=False` behavior enables MITM | TLS verification mandatory; deploy corporate CA; no profile/source/request opt-out. |
| T6 | Over-privileged PAT imports unrelated confidential pages | Least-privilege account per knowledge base, explicit roots, bounded traversal, excluded IDs, live out-of-scope denial test, rapid secret revocation. |
| T7 | Confluence ACL removal is not reflected in copied data | Document the ACL-authority change; reconcile only after full sync; emergency AgentHub tombstone; explicit candidate/promotion flow. |
| T8 | Cross-tenant/source page ID overwrites another document or a profile is reused for a different knowledge base | Tenant+document-set-scoped profile grant, locked source binding, source-namespaced external identity, unique cursor constraint, service checks + RLS. |
| T9 | Malicious JSON/HTML causes execution, SSRF, traversal, or parser escape | Strict JSON shape/type/size checks; store inert `text/html`; existing stdlib parser executes/fetches nothing; no attachment/macro/link fetch. |
| T10 | Deep/cyclic/overlapping tree exhausts workers | Visited set, bounded roots/depth/pages/requests/bytes, fixed pagination, source lock, task time budget. |
| T11 | Partial outage is interpreted as mass deletion | Persist `snapshot_complete`; reconcile only after complete success; prior content remains on any DNS/TLS/auth/rate/schema/size failure. |
| T12 | Retry duplicates writes or hides uncertain state | GET-only bounded retry; checksum/version idempotency; durable run/cursor; stable dead-letter/recovery. No auto-promotion. |
| T13 | Token, content, base URL, or private topology leaks through telemetry/errors | Stable content-free errors; IDs/counts only; explicit log/audit/metric/trace capture tests; upstream text never logged. |
| T14 | Generic REST becomes a general internal HTTP proxy or execution DSL | Disabled until narrow contract; fixed profile/path/method/schema; no arbitrary URL/header/query/extractor/template/code. |
| T15 | Compromised profile DB row selects a new private range | Profile references deployment-owned network-policy ID; raw CIDRs are not tenant/profile data; firewall is an independent backstop. |
| T16 | Sync silently serves malicious/new content | Sync produces a draft candidate only; explicit publish/build/eval/promote and serving ACL/RLS remain intact. |

## Failure cases

- Missing/disabled/ungranted profile or source, unresolved secret, DNS empty/mixed/out-of-policy,
  connect/TLS/read timeout, redirect, 401/403/404/410/429/5xx, malformed/oversized JSON/body, page/depth/
  byte budget, object-store/database/audit failure, worker crash, source-lock contention, and profile
  disable/revocation during a run.
- Failure before `snapshot_complete` retains prior content and records a stable failed/retry/dead-letter
  state. It does not reconcile missing pages, publish a set, promote an index, or broaden access.
- Blob-before-DB and DB-before-cursor crash windows must converge idempotently using checksum,
  external version, unique constraints, and best-effort orphan cleanup/retention.
- Audit persistence failure is fail-closed for state changes; metrics/tracing failure does not block
  document correctness but must not cause content logging fallback.

## Logging and audit risks

- Page titles and raw errors can contain secrets/personal data; never log them.
- URLs and DNS/IP diagnostics reveal infrastructure; use profile/network-policy IDs and stable codes,
  not base URL/host/IP/CIDR.
- Authorization headers/session objects and response bodies must never reach debug logging. This is
  one reason generic Atlassian/LangChain clients are not used.
- Page IDs/root IDs are not suitable metric labels. Audit resource IDs are access-controlled and used
  only when necessary; summary events prefer source/run IDs and counts.
- Required audit: profile create/disable/grant denies/successes, source config/start authorization,
  sync lifecycle, reconciliation, and candidate creation. No content-bearing `before`/`after` data.

## Mitigations

- Profile-ID-only destination resolution and exact source schemas.
- Connector-specific deployment-owned private network policy; public-only defaults preserved.
- All-DNS-answer validation, prohibited-address checks, IP pinning, SNI/hostname verification,
  mandatory CA trust, redirect denial, firewall backstop.
- Fixed REST paths/query allowlists, local pagination, strict bounded JSON/HTML processing.
- Least-privilege per-knowledge-base PAT; live positive/negative permission check.
- Same-tenant constraints/services/RLS and ID-only worker payloads.
- Visited set and hard request/page/depth/body/total/time budgets.
- Durable run/cursor/checksum lineage; full-snapshot-only reconciliation; draft-only candidate.
- Existing explicit blue/green build/eval/promote and ACL/RLS retrieval gates.
- Secure empty defaults, offline injected transport tests, stable redacted errors/audit.

## Residual risks

- The private connector intentionally reaches an internal service; compromise of the application,
  deployment network-policy registry, DNS+CA, or firewall can exceed application-layer protections.
- A least-privilege Confluence account still grants AgentHub a durable copy. Permission removal is not
  instantaneous and Confluence per-user ACLs are not reproduced.
- `body.storage` may omit rendered macro/attachment content or contain text different from the final
  UI. V1 fidelity is bounded and explicit.
- Corporate DNS/IP/CA rotation can cause safe availability failures until a new profile/network policy
  or trust deployment is reviewed.
- Parser and API behavior against all supported Data Center versions is unverified until a concrete
  version/live smoke test is recorded.
- Generic REST risk cannot be fully modeled until its contract is known; it remains disabled.

## Required security tests

- Profile registration/admin/grant allow+deny audit; immutable used profile; secret/base-URL/network
  metadata redaction.
- Same-tenant author success and cross-tenant/ungranted/disabled/forged profile/document-set/source/run
  denial at service, constraint, and RLS layers.
- Existing public-only egress regression plus Confluence exact-private allow, unlisted/mixed/private-
  rebinding deny, loopback/link-local/metadata/multicast/reserved/unspecified deny.
- Redirect and malicious `_links.next` denial; TLS invalid CA/hostname denial; no `verify_ssl` opt-out.
- Root/path/query/ID canonicalization and traversal/header/credential injection denial.
- Malformed/oversized JSON/HTML, deep/cyclic/overlapping traversal, page/depth/request/byte limits.
- Partial failure/no-reconciliation, complete snapshot reconciliation, checksum/version idempotency,
  crash recovery, source-lock contention, dead-letter/re-drive.
- Logs/audit/metrics/traces captured at success/failure/debug configuration and asserted free of token,
  content/title, raw response/error, base URL/host/IP/CIDR, and high-cardinality page labels.
- Live pre-rollout test proves configured-root read success and selected out-of-scope page denial.
- Retrieval remains empty without release-pinned document-set binding/effective consumer grant and
  remains cross-tenant denied by app predicate + RLS.
