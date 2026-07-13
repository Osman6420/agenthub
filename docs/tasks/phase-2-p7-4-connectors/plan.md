# Phase 2 · P7.4 — Confluence and generic REST connectors

Authority for scope: [`runtime-and-document-plane-sequence.md`](../../planning/components/runtime-and-document-plane-sequence.md)
§ "P7.4 — Confluence + generic-REST connectors",
[`document-plane-plan.md`](../../planning/components/document-plane-plan.md), and the parent
[`phase-2-p7-parsers-ocr-connectors`](../phase-2-p7-parsers-ocr-connectors/plan.md) task.
Existing public-egress governance is defined by
[ADR-0005](../../adr/0005-shared-ssrf-safe-egress-adapter.md).

## Task summary

Add a governed Confluence Data Center connector that synchronizes pages below configured root page
IDs into the tenant content plane, without letting a tenant or request choose an egress destination.
The owner's Confluence deployment is on-premises (`cloud=False`), resolves through private
corporate DNS, and uses a least-privilege service account scoped to one scenario/dataset/knowledge
base. The registration interface accepts the instance base URL as a **platform-operator input** and
canonicalizes it into an immutable profile; a `Source`, tenant, artifact, or request never carries a
raw base URL, credential, TLS switch, or network policy.

P7.4 also retains the planned generic REST connector, but that increment remains gated until its
response/pagination/identity contract and concrete destination are supplied and approved. The
Confluence increment may be implemented and verified independently; P7.4 as a whole is not complete
until the generic REST gate is either implemented or explicitly re-scoped by the owner and the
authoritative component/phase plans are updated.

## Background

- The Phase 2 content plane already has tenant-scoped `Source`, `Document`, immutable
  `DocumentVersion`, `DocumentSetVersion`, staged index, ACL/RLS retrieval, parser, OCR, and console
  operations.
- The current `HttpsConnector` and ADR-0005 destination validator accept only public-unicast
  addresses. They intentionally reject this private-DNS Confluence deployment.
- The old-project flow used `atlassian-python-api` for root/child traversal and
  `langchain-community` for page loading. Research for this task found that the required Data Center
  flow is only a small, read-only REST surface. The generic packages would duplicate AgentHub's
  parser/document abstractions and would bypass its pinned-IP, redirect-denying transport defaults.
- P7.1–P7.3 are implemented and verified. Their deterministic/offline defaults and serving
  authorization must remain unchanged.

## Confirmed owner decisions (2026-07-13)

1. Confluence is **Data Center/on-premises**, not Cloud (`cloud=False`).
2. Its hostname resolves to a **private corporate address**.
3. Profile registration accepts a **base URL parameter**.
4. The credential belongs to a least-privilege service account scoped to the applicable
   scenario/dataset/knowledge base and should see only that corpus.
5. No additional live endpoint, CA-chain, Data Center version, or generic REST contract is
   available yet.

These decisions unblock detailed planning only. They do **not** by themselves authorize a
production dependency, a global relaxation of private-network blocking, or live egress. The
connector-specific address-policy ADR and the concrete environment profile/secret/CA provisioning
remain change-boundary approvals before implementation/live rollout respectively.

## Scope

### P7.4a — Confluence Data Center connector

- Add an immutable, revisioned, platform-managed `ConfluenceProfile` and a platform-approved grant
  scoped to one tenant **and one document set**, following the existing catalog pattern while making
  the service-account-per-knowledge-base boundary explicit.
- Add `confluence_dc` to the deny-by-default connector registry and exact `Source.connector_config`
  schema.
- Bind each Confluence `Source` to exactly one same-tenant `DocumentSet` and one tenant-granted
  Confluence profile. This binding is server-validated and cannot be widened by connector output.
- Traverse configured root page IDs breadth-first, include roots by default, deduplicate overlapping
  roots/cycles, and fetch bodies only for new or changed page versions.
- Persist fetched page bodies as `text/html` `DocumentVersion` objects through the existing content
  storage service; the existing HTML parser performs inert text extraction and never follows links.
- Persist source/page/version lineage and a recoverable sync-run state so incremental sync,
  reconciliation, retry, and audit are deterministic.
- After a fully successful snapshot, create a new **draft/candidate** document-set version from the
  current non-tombstoned source documents. Never mutate an active document-set version or active
  index; publish/build/eval/promote stays explicit and uses the existing blue/green path.
- Provide platform-admin profile registration/grant commands and an operator command/task to start a
  source sync. A console extension is a follow-up unless explicitly added to this task; backend
  authorization remains authoritative either way.

### P7.4b — Generic REST connector (contract-gated)

- Record the minimum contract required before implementation: GET/read-only method set, canonical
  profile destination/path prefix, auth scheme, stable item ID/revision fields, MIME/body extraction,
  pagination/termination, deletion semantics, rate limits, response/item/total byte caps, and retry
  semantics.
- Do not introduce a tenant-authored URL, arbitrary headers, arbitrary JSONPath/JMESPath, templates,
  executable transformations, or response-provided next URLs.
- Implement only after the owner supplies/approves the contract and environment-specific profile.

## Non-goals

- Confluence Cloud/v2 APIs, OAuth browser flows, cookies, username/password authentication, writes,
  comments, labels, attachments, CQL search, or space-wide discovery.
- Mirroring Confluence user/group/page ACLs into AgentHub. The service account limits what can be
  imported; AgentHub `DocumentSet` grants remain authoritative for serving copied content.
- Following URLs returned by Confluence, fetching embedded images/links, executing macros, or
  rendering active content.
- Disabling TLS verification or exposing a tenant/request-controlled CA bundle, hostname, port,
  path, CIDR, credential, or retry policy.
- Weakening the public-only policy for model, embedding, OCR, tool, MCP, HTTPS, or generic REST
  destinations.
- Automatically promoting a synchronized corpus into service.

## Proposed interfaces and data model

### `ConfluenceProfile` (platform catalog)

Profile registration accepts `base_url` from a platform administrator, rejects credentials/query/
fragment components, requires HTTPS, and canonicalizes it into separately validated fields:

- `logical_id`, `revision`, `provider="confluence_dc"`, `status`, `created_by`;
- `scheme="https"`, fully qualified corporate `host`, `port`, and normalized `context_path`
  (for example `/confluence`, with no traversal/query/fragment);
- `secret_ref` for the Bearer PAT/service-account token;
- `network_policy_id` referencing a **deployment-owned** private-address allowlist; tenants cannot
  create or edit CIDRs/IPs in a profile;
- timeout, page-size, maximum-pages, maximum-depth, per-response, per-page-body, and cumulative-byte
  limits.

Used profiles are immutable except for disabling. A new base URL, credential reference, context
path, network policy, or limit creates a new revision. The platform command may accept `--base-url`,
but application call sites resolve and use only the profile ID.

### Source contract

The `confluence_dc` source has relational `confluence_profile` and `document_set` foreign keys. The
source-creation service accepts their public IDs, resolves them server-side, verifies the exact
tenant+document-set profile grant, and persists the relations. Its JSON config has only this exact
allowlist:

- `root_page_ids` — bounded, non-empty list of canonical numeric Data Center page IDs;
- `include_root` — boolean, default `true`;
- optional bounded `excluded_page_ids` — canonical IDs whose complete subtree is skipped.

Unknown keys, inline secrets, profile IDs inside JSON, `base_url`, scheme/host/port/path, TLS flags,
network ranges, arbitrary query parameters, regexes, and headers fail validation. Profile grant,
source tenant, document-set tenant, and sync-run tenant must all match.

### Sync lineage

Use additive models (final names may follow repository naming conventions):

- `ConnectorSyncRun`: organization, source, profile revision, status/attempt, stable error code,
  started/finished timestamps, counts/bytes, and `snapshot_complete`.
- `ConnectorDocumentCursor`: organization, source, external page ID, root page ID, Confluence
  `version.number`, `version.when`, linked `Document`, last-seen successful run, and state.

The profile grant records both `organization` and `document_set`; a source may use the profile only
for that granted set. Unique `(source, external_page_id)` and same-tenant constraints are mandatory.
Page title/body and raw upstream errors are not stored in run/audit diagnostics. The document
logical ID is derived server-side from source identity + page ID; connector data cannot select
another tenant/document.

## Confluence REST contract

Use fixed, server-constructed Data Center REST paths under the canonical context path:

1. `GET /rest/api/content/{page_id}?expand=version` for root/current metadata.
2. `GET /rest/api/content/{parent_id}/child/page?start=N&limit=L&expand=version` for child pages.
3. `GET /rest/api/content/{page_id}?expand=body.storage,version` only for a new/changed page.

Requirements:

- Bearer PAT from `secret_ref`; no username in the request.
- Accept only `type=page`, `status=current`, canonical IDs, integer `version.number`, bounded title,
  and `body.storage.value` string. JSON shape mismatches fail closed with stable codes.
- Treat response links as untrusted metadata and never follow an absolute or relative `_links.next`.
  Pagination advances a locally constructed numeric `start` and terminates using the validated
  response size/next marker under hard page/request budgets.
- Use `version.number` as the incremental cursor and `version.when` as informational metadata.
- Store `body.storage.value` as inert UTF-8 `text/html`; macro/attachment fidelity is explicitly
  outside v1 and no embedded URL is fetched.
- A `401/403` is terminal authorization failure; `404/410` is handled as missing only within a
  completed snapshot; `429/5xx` follows bounded GET-only retry policy. DNS/connect/TLS failures and
  malformed/oversized responses fail the run without reconciliation.

## Private-corporate egress decision and ADR gate

ADR-0005 currently requires every resolved address to be public unicast. Before connector code is
merged, create and accept a narrowly scoped ADR that preserves that default and adds a separate
**platform-only private destination policy** for the Confluence connector:

- The global/public validator and all existing callers remain unchanged and public-only.
- A Confluence profile references a deployment-owned `network_policy_id`; tenant/source/request data
  can neither select raw CIDRs nor opt a generic caller into private egress.
- Every DNS answer must fall inside the selected corporate allowlist. Mixed allowed/disallowed
  answers fail closed.
- Even inside the corporate allowlist, loopback, link-local, multicast, unspecified, reserved, and
  cloud/container metadata addresses are always denied.
- The transport connects to the already-validated IP while setting SNI/Host to the canonical
  hostname. Redirects remain denied.
- TLS verification is mandatory. The corporate CA is installed in the deployment trust store (or a
  platform-owned trust-bundle policy); no `verify_ssl=False` or per-source opt-out exists.
- Network firewall/egress policy independently permits only the expected Confluence destination and
  port.

This changes network behavior and therefore requires explicit owner/security approval under
`AGENTS.md`. A live profile additionally requires review of the actual base URL, DNS answers,
allowlisted network, CA chain, secret reference, and service-account permissions.

## Data flow and trust boundaries

```text
platform admin base URL + network-policy ID + secret-ref
                 |
                 v
 immutable ConfluenceProfile --tenant grant--> tenant Source --binds--> DocumentSet
                 |                                  |
                 | profile-only resolution          | root page IDs only
                 v                                  v
 private-DNS validate/all-address allowlist -> pinned TLS GET -> untrusted Confluence JSON/HTML
                                                               |
                                                               v
                                           bounded validation -> Document/DocumentVersion
                                                               |
                                                   successful full snapshot
                                                               v
                                             draft DocumentSetVersion candidate
                                                               |
                                             existing build/eval/promote + ACL/RLS
```

Trust decisions are made from database/profile/source state loaded server-side. Confluence IDs,
titles, body, version data, response headers, and links are untrusted inputs and never authorize a
tenant, source, document set, document, or egress destination.

## Acceptance criteria

### Confluence functionality

- A granted active Data Center profile + active source can traverse multiple overlapping roots,
  fetch current page bodies, and create/update the correct same-tenant content documents.
- Unchanged `version.number` pages do not create duplicate `DocumentVersion` rows or refetch bodies.
- Changed pages create one new immutable version; duplicate/overlapping roots and graph cycles yield
  one document per external page.
- Root inclusion and excluded-page subtree behavior are deterministic and bounded.
- A complete snapshot marks missing pages for reconciliation and creates a draft candidate set
  version; a partial/failed snapshot never deletes/tombstones missing content and never changes the
  active set/index.
- Existing explicit publish/build/eval/promote is required before changed content can be served.

### Security and authorization

- A source/request cannot set or override base URL, host, path, credential, network policy, CA/TLS,
  headers, or redirect behavior.
- Non-platform administrators cannot register/disable profiles, change private network policies, or
  grant profiles. Tenant authors may manage only same-tenant sources bound to the exact document set
  named by an existing profile grant.
- Cross-tenant profile/source/document-set/cursor/run associations fail at service validation and DB
  constraints; RLS coverage is added where applicable.
- Only profile-pinned corporate IPs are reachable; mixed DNS, unlisted private ranges, public
  rebinding, metadata/link-local/loopback, redirects, and TLS failures are denied.
- The service account is externally verified to be unable to read an out-of-scope page before live
  rollout. AgentHub retrieval still requires the existing release-pinned document set and consumer
  grant.
- Logs, metrics, traces, audit, task results, and errors contain no token, base URL, IP/CIDR, page
  title/body, response body, or raw upstream exception.

### Compatibility and operations

- Existing `https`/`s3`, parser/OCR, deterministic CI, legacy source ingestion, active indexes, and
  gateway/retrieval behavior remain unchanged.
- No new production dependency is added; `langchain-community` and `atlassian-python-api` are absent
  from `pyproject.toml` and the lock file.
- Connector egress is disabled by default. With no profile/network policy/secret, no DNS lookup or
  socket occurs.
- Per-source locking prevents concurrent sync. Retry/dead-letter state and audit are recoverable and
  use stable error codes.

### Generic REST gate

- No generic REST implementation is merged until all contract fields listed in Scope are decided,
  threat-modeled, and approved. A future implementation reuses profile-only destination governance
  and cannot be a general-purpose HTTP client.

## Affected components

- `apps/ingestion`: profile/grant/schema/services, connector client, source config/registry, sync
  state/task/commands, private-policy destination resolution, and tests.
- `apps/documents`: connector-originated upload/version reconciliation and draft candidate assembly
  through existing audited services.
- `apps/tools/egress` / `apps/tools/http_adapter`: only if the accepted ADR introduces a reusable
  server-controlled address-policy seam; existing public-only callers must remain behaviorally
  unchanged.
- `config/settings`: deployment-owned network-policy and secret/trust-store configuration; secure
  empty defaults.
- Migrations: additive profile/grant/source-binding/sync-lineage schema and applicable RLS policies.
- Documentation: ADR, task threat model/verification, current-behavior operations/user guide, parent
  P7 plan, component/phase/master plan, and handoff at completion.

## Interfaces affected

- No public consumer gateway or artifact DSL contract changes.
- New platform management commands for profile registration/grant/disable and a source sync command/
  Celery task carrying identifiers only.
- Any later console source UI calls the same audited services and does not expose endpoint/network/
  secret details.

## Data impact

- Confluence HTML is confidential tenant document content and is copied into the existing tenant-
  prefixed object store as immutable versions.
- Page ID/version/root lineage and safe counts are stored; credentials, network ranges, response
  links, and raw errors are not stored with documents.
- A Confluence restriction/removal is not reflected until a later **fully successful** sync and an
  explicit candidate publish/build/promote. Emergency serving removal still uses the existing
  document tombstone path.
- Physical purge remains elevated, audited, and blocked while a published set version pins content.

## Security impact

High. The task intentionally opens a narrowly governed route to a private corporate service. It
must not turn the generic egress adapter into an internal-network client. The companion
[`threat-model.md`](threat-model.md) is mandatory and the private-egress ADR gate precedes code.

## Authorization impact

- Platform admins own profiles, grants, network-policy references, and live provisioning.
- Tenant authors can operate only sources and document sets in their authorized organizations.
- The Confluence service account is an upstream least-privilege boundary, not a substitute for
  AgentHub tenant/document-set/consumer authorization.
- Confluence per-user/group ACLs are not propagated. Copied content is served according to AgentHub
  ACL/RLS; this semantic difference must be accepted in manual review.

## Observability impact

- Structured events: profile create/disable/grant, sync queued/started/succeeded/failed/dead-letter,
  reconciliation summary, and candidate creation.
- Safe fields only: tenant/source/profile/run IDs, stable error/reason code, page counts, changed/
  unchanged/missing counts, bounded byte count, latency, retry count, and trace/request ID.
- Metrics labels stay low-cardinality and never include host, URL, IP, source slug, page ID/title, or
  content. Page IDs may appear only as access-controlled resource IDs where operationally necessary,
  never titles or bodies.
- Audit persistence failure is fail-closed for profile/grant/source/reconciliation state changes.

## Migration impact

- Additive migrations only: immutable Confluence profile, tenant+document-set-scoped grant,
  source→document-set/profile binding (nullable for existing connector types), sync run, and page
  cursor/lineage.
- Preserve all existing `Source`, `IngestionRun`, `Document`, and index rows. Do not repurpose the
  legacy source-to-index run in a way that changes existing HTTPS/S3 behavior.
- Add database constraints for unique revisions/cursors and same-tenant relations where expressible;
  service validation and PostgreSQL FORCE RLS backstop the remainder.
- Migration tests cover fresh install, upgrade with legacy sources/runs, reverse migration before any
  new rows, constraints, and PostgreSQL RLS behavior.

## Dependencies

- **No new production dependency.** Use the existing stdlib pinned-IP TLS transport, JSON/URL
  utilities, content-plane services, and HTML parser.
- A new/superseding ADR is required for connector-specific private-address policy because ADR-0005
  is currently public-only.
- Live rollout depends on the actual canonical base URL/context path, DNS answer allowlist, corporate
  CA installation, Bearer PAT secret reference, Data Center version compatibility, firewall rule,
  and least-privilege service-account verification.
- Generic REST remains dependent on its missing contract and endpoint sign-off.

## Implementation steps

1. Write/accept the connector-specific private-egress ADR; prove existing public callers keep their
   exact denial behavior.
2. Add profile/grant/source-binding/sync-lineage migrations, validation, authorization services, RLS,
   management commands, and audit events.
3. Add a profile-only Confluence Data Center client over the existing bounded transport with fixed
   path construction, PAT injection, JSON schema validation, GET retry policy, and stable errors.
4. Add bounded BFS discovery with local pagination, visited-set/cycle handling, root/exclusion rules,
   and version-based body fetch.
5. Add content-plane synchronization: deterministic page identity, immutable version creation,
   checksum/idempotency, source lineage, complete-snapshot reconciliation, and draft candidate set
   assembly under locks.
6. Add Celery/management entry points using ID-only payloads and secure no-egress defaults.
7. Add the full offline test matrix and a deployment-gated live smoke test procedure; do not require
   live Confluence in CI.
8. Run repository checks, review the final diff as staff engineer/AppSec/SRE, record verification,
   update current-behavior docs/plans/handoff, and archive only when P7.4 scope is actually complete.
9. Keep P7.4b disabled until its separate contract addendum and approval are recorded.

## Test plan

### Unit and contract tests (offline injected DNS/transport)

- Profile/base-URL canonicalization, immutability, exact source schema, root/exclusion bounds, and
  inline URL/secret/TLS/network-policy rejection.
- Data Center page/child/body JSON happy path plus malformed JSON, wrong content type/status/type,
  missing fields, invalid IDs/versions, invalid UTF-8, and per-response/body/cumulative size limits.
- Pagination at 0/1/limit/limit+1 pages, overlapping roots, duplicate children, cycle, maximum depth,
  maximum pages, and response-provided malicious next links (never followed).
- New/unchanged/changed page idempotency and checksum behavior.
- Complete-snapshot missing-page reconciliation versus partial-failure no-delete behavior.
- `401/403/404/410/429/5xx`, DNS/connect/TLS/read timeout, retry bounds, dead-letter, and recovery.

### Security/authorization tests

- Platform-admin allow and non-admin deny for profile/network-policy/grant operations, including deny
  audit.
- Tenant author allow for same-tenant granted source and deny for cross-tenant/ungranted/disabled
  profile, foreign document set, forged profile ID, and client-supplied organization.
- Existing public-only validator regression matrix; private connector exact allow, out-of-policy
  private deny, mixed DNS deny, public/private rebinding deny, loopback/link-local/metadata/reserved/
  multicast deny, redirect deny, and TLS hostname/CA failure.
- RLS missing/foreign tenant context denial on all new tenant tables.
- Capture logs/audit/metrics/traces and assert token, base URL, host/IP/CIDR, page title/body, upstream
  response/error, and content fragments are absent.
- Verify retrieved content remains deny-by-default without scenario binding/effective consumer grant.

### Integration/migration tests

- Object-store write + document version + cursor/run + candidate set transaction/failure behavior.
- Worker crash after body storage, after DB version, and before/after snapshot completion converges
  without duplicate versions or unsafe reconciliation.
- PostgreSQL advisory/source locking and FORCE RLS with the non-owner application role where
  available.
- Fresh and upgrade migrations on SQLite; PostgreSQL `--create-db` migration/RLS gate.
- Existing HTTPS/S3 ingestion, P7 parsers/OCR, staged build/promotion, console documents, retrieval,
  and full regression suites remain green.

### Deployment-gated live review

- Confirm Data Center API compatibility and context path with a non-production instance/profile.
- Confirm corporate DNS resolves only to the approved network policy and the pinned TLS handshake
  validates through the installed corporate CA.
- Confirm the service account can read every configured root and **cannot** read a selected
  out-of-scope page.
- Sync a bounded test subtree, verify counts/checksums/candidate membership, then revoke/restore the
  secret and verify safe failure/recovery without deletion.

## Rollout plan

1. Merge with connector disabled, no profile, no network policy, and no live secret; CI remains
   hermetic.
2. Deploy migrations and management surfaces; verify existing public egress denial regression tests.
3. Install/review the corporate CA and firewall policy.
4. Register one non-production immutable profile revision, bind its deployment-owned network policy,
   inject the PAT secret, and grant it to one tenant.
5. Create one disabled/bounded source for a test knowledge base; enable and run discovery/sync without
   publishing the candidate.
6. Review imported page set, out-of-scope denial, audit/redaction, limits, and rollback; then follow
   the existing publish/build/eval/promote path.
7. Expand per knowledge base through separate least-privilege service-account profiles. Generic REST
   remains disabled.

## Rollback plan

- Disable the source/profile or revoke its tenant grant/network policy; absent an active granted
  profile, the connector opens no socket.
- Revoke the PAT/firewall rule for emergency egress stop.
- Do not promote the candidate, or roll the active index pointer back through the existing metadata-
  atomic mechanism. Previously active immutable content/indexes remain available.
- Connector-created documents remain governed content and are not destructively deleted on rollback;
  operators may tombstone/purge them through existing audited controls.
- Reverse additive migrations only before dependent rows are created; otherwise use a forward fix and
  retain lineage/audit history.
- A defect in private-address validation disables only the private Confluence policy; never relax the
  existing public-only validator as a workaround.

## Risks

- **Internal-network SSRF expansion:** mitigated by a separate platform-only network policy, all-DNS-
  answer validation, IP pinning, fixed server paths, and no tenant URL/CIDR control.
- **Over-privileged service account or copied ACL drift:** least-privilege account per knowledge base,
  out-of-scope live denial check, explicit AgentHub ACL authority, safe reconciliation, emergency
  tombstone.
- **Corporate CA pressure leading to `verify_ssl=False`:** prohibited; rollout blocks until the CA
  trust chain validates.
- **Partial crawl interpreted as deletion:** reconciliation only after a persisted complete snapshot;
  partial failures retain prior content.
- **Huge/deep/overlapping trees and rate limiting:** hard root/page/depth/request/byte budgets,
  visited set, local pagination, bounded GET retry, source lock.
- **Macro/attachment content loss:** v1 stores `body.storage` text only; fidelity limitation is
  visible and tested, not silently presented as attachment-complete ingestion.
- **Candidate accidentally served:** sync creates only a draft candidate; existing explicit
  publish/build/eval/promote and ACL/RLS gates remain mandatory.
- **Generic REST becoming an HTTP proxy:** keep disabled until a narrow endpoint-specific contract is
  approved; no arbitrary URL/path/header/extractor DSL.

## Open questions and explicit gates

Not required to finish the plan, but required before the corresponding stage:

- **Before private-egress implementation:** accept the narrow ADR/change-boundary decision.
- **Before live Confluence rollout:** actual base URL/context path, Data Center version, corporate DNS
  allowlist/network-policy ID, CA chain, firewall rule, secret reference, page/request/byte limits,
  and service-account out-of-scope denial evidence.
- **Before P7.4b implementation:** generic REST endpoint, auth, item identity/version, body/MIME,
  pagination, deletion, rate/size, retry, and data-classification contract.
- Decide whether connector-source CRUD/sync controls belong in a P8.5 console increment or remain
  platform command/API-only for the first rollout. This does not change backend authorization.

## Manual review recommendation

The recommended and, given the repository's current trust boundaries, **correct design** is:

1. Implement Data Center only; do not add `langchain-community` or `atlassian-python-api`.
2. Accept `base_url` only during platform-admin profile registration, canonicalize it, and let every
   runtime/source reference only the immutable profile ID.
3. Do not weaken ADR-0005 globally. Add a connector-specific, deployment-owned private network
   policy that validates every DNS answer and retains pinned-IP TLS, redirect denial, hard bounds,
   and redaction.
4. Keep TLS verification mandatory and install the corporate CA; never carry forward
   `verify_ssl=False` from the old project.
5. Use one least-privilege service-account profile per scenario/dataset/knowledge base, bind the
   source to one same-tenant document set, and still treat AgentHub ACL/RLS as the serving authority.
6. Reconcile missing pages only after a fully successful snapshot and never auto-promote synchronized
   content.
7. Leave generic REST disabled until its concrete contract is known rather than inventing a
   general-purpose HTTP/extraction DSL.

Any review outcome that permits tenant-controlled base URLs/CIDRs/TLS switches, global private-
network access, redirect following, disabled certificate validation, content-bearing logs, dynamic
Confluence ACL bypass, or automatic promotion should be rejected.

## Status

**Documentation-only plan.** P7.4a's contract and recommended design are documented; this task does
not claim connector implementation. Implementation is gated by the private-egress ADR/change-boundary
approval, and live rollout has additional environment gates. P7.4b generic REST remains
contract-gated.

## Completion criteria

- All applicable [Definition of Done](../../ai/definition-of-done.md) checks are recorded in a task
  `verification.md`, including format/lint/type/unit/integration/security/migration/secret checks,
  SQLite and PostgreSQL evidence, authorization/RLS denial, redaction, and final-diff review.
- The private-egress ADR is accepted and the concrete live deployment review is recorded separately
  from offline implementation verification.
- Confluence acceptance criteria pass without a new dependency or live call in default CI.
- Generic REST is implemented under an approved contract or explicitly re-scoped by the owner in all
  authoritative plans; it is not silently omitted.
- Current behavior docs, parent P7/component/phase/master plans, handoff, and verification are updated
  before the task is marked Completed or archived.
