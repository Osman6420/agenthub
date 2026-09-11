# Shared connection identity and ingestion job authority

Date: 2026-09-10

Status: Accepted; additive implementation, rollout and remaining adapters open

## Context

REST and Confluence already have governed profiles, exact tenant/document-set grants,
sources, immutable document versions, protocol runs and cursors. Staged indexing has a
durable PostgreSQL job and delivery outbox. Replacing these identifiers or adding a
second independently writable job status would break provenance and recovery.

The approved [combined task](../tasks/Agent_Hub_MD/plan.md) extends these authorities.
This decision composes with ADR-0006, ADR-0007 and ADR-0012.

## Decision

`Connection` identifies one exact immutable platform profile revision. Its closed kind
currently supports REST pull and Confluence Data Center. It stores a protected profile
reference and configuration checksum, not duplicated transport settings, credentials,
status or grants. Registration and migration populate the global identities. Runtime
source creation reads them with SELECT-only catalog privileges. Existing Source IDs,
contracts, cursors and schedules remain; old source pointers require explicit authorized
attachment. A Connection never conveys tenant or document-set access.

The existing `StagedIndexBuildJob` table and public IDs become the shared ingestion job
authority. Closed kinds distinguish index builds, REST sync and Confluence sync. Build
pins remain mandatory only for builds. Connector jobs instead require an exact source,
protocol-run reference and immutable source configuration checksum. Source input changes
invalidate execution; they never redefine an admitted request. Existing protocol runs
retain cursor, counter, candidate and snapshot evidence. Their status, attempt and error
are a compatibility projection, checked by a deferred PostgreSQL constraint at commit.

Admission atomically creates the job, protocol record, outbox and required audit event.
Identical active intent deduplicates; a different active intent returns source busy.
Persisted schedule slots deduplicate across terminal completion as well. A schedule
retains its existing system-delegation semantics; live source/profile/set grants and
quarantine checks still apply. Manual admission and cancellation/retry require the
exact document manager. New live-grant or organization revocations prevent further writes.

The worker durably commits one claim before snapshot I/O. Each database write boundary
checks the current job attempt and state, fresh source checksum and live grants. The
organization precedes job, protocol and source locks so operator changes and document
tenant foreign keys cannot invert the lock order. Remote source reads remain outside
these write transactions. Blob writes use the existing bounded storage adapter. Database
guards reject competing legacy admission and unowned protocol/cursor evidence. A legacy
task cannot claim a run owned by a shared job.

A complete scan commits candidate evidence and job success together. A partial scan is
never a mass-missing signal. Duplicate delivery cannot claim a running/completed job.
Stale owners and unknown external outcomes require reconciliation; no snapshot success
is inferred from partial cursors. Cancelling an in-flight POST also requires outcome
reconciliation. Known transient GET failures can retry within the existing three-attempt
protocol budget; stale attempts cannot publish later results.

Outbox delivery locks job before outbox, routes by kind, and never regresses a running
job to queued. Unclaimed stale deliveries can be redriven without spending an attempt.
Completed scheduled snapshots also retain automation delivery evidence in that outbox,
so broker failure after snapshot commit does not lose the follow-up. Delivery remains
at least once; downstream automation keeps its existing idempotency key.

If cursor persistence rolls back after a new blob upload, cleanup deletes only keys
created by that operation and proven unreferenced. An uncertain database commit or failed
cleanup retains the blob for later orphan reconciliation rather than deleting possibly
referenced data. Process-death orphan retention remains an operational requirement.

## Rollout and consequences

`INGESTION_DURABLE_CONNECTOR_JOBS` defaults to false. Console and schedule admission use
the shared service when enabled; existing bound jobs remain understood regardless of the
flag. Worker contract 9 must be deployed and old ingestion workers drained before enabling
new delivery. A compatible heartbeat alone does not prove all old workers are gone.
Turning admission off does not undo running jobs or permit bypassing their ownership.

No source IDs, live grants, profile settings, document bytes or historical jobs are
rewritten during this task's rollout preparation. Migration reversal must not discard
bound-job authority while jobs or retained provenance still depend on it. Live migration,
worker cutover, browser acceptance, orphan retention, operational fairness beyond the
current bounded organization scan and remaining Connection/MCP adapters are still open.
Organization write locks can limit concurrent ingestion throughput within one tenant;
representative workload verification must precede broad activation.

Verification evidence and remaining acceptance criteria stay in the combined task.

## REST setup and connection checks

The gated REST setup flow creates a canonical mapping contract and its Source in
one audited transaction. An organization lock serializes identical intents; replays
must match the configuration and pass current collection/profile authority. The
four-step form uses bounded server-side session drafts and signed state digests;
completed drafts retain only a source locator. Synthetic examples are not persisted
or reflected. Visual/JSON conversion uses the canonical validator and rejects a
lossy conversion instead of dropping fields. Existing advanced URLs remain valid.
Explicit save-for-later persists a private RestSetupDraft checkpoint for 30 days,
with at most five open checkpoints per actor/organization and a 160 KB closed payload.
It does not broaden platform catalogue visibility or create a Source, grant, schedule,
job or external request. A name-only first step can wait for a platform grant. A revoked
selected connection keeps the exact step and mapping until it becomes usable again.
Resuming requires the original owner and current document-management authority;
all execution and finalization paths still require the current exact connection grant.
The organization lock and expected draft revision prevent concurrent lost updates.
Source creation and draft completion share a transaction with fail-closed audit;
completion clears the duplicate configuration and retains only source provenance.
The new table has FORCE RLS and immutable tenant/set/owner binding, exact source
completion checks and a nonempty rollback guard. Expiry prevents further editing or
resuming; it is not a physical-erasure job. Content retention/purge is an operational
follow-up; no existing database records are deleted by this migration.
An optional draft-only schedule is part of the same atomic, idempotent bundle;
its first slot is one selected interval after creation. The wizard does not expose
legacy stage/promotion automation until its synchronous preparation path is unified
with durable build jobs and collection preparation policy.

Completed shared REST/Confluence stage-only schedules now reference one exact index-build
job through a write-once PROTECT self-FK. Fetch success remains the source job's result;
preparation state comes only from the referenced build. Publication, build/outbox intent,
the link and audit commit together. The completion outbox records this durable handoff;
broker failure is retried by the build outbox. Admission blockers are safely recorded and
rechecked after five minutes without starting paid work. Redelivered legacy automation
messages for this path are routed before the old inline-build claim.

Current source grants and embedding/OCR grants are rechecked before admission. A document
preparation policy pins the remaining pipeline profiles; a schedule/policy mismatch is
rejected explicitly. Exact terminal builds are reused and require explicit retry, whereas
manual build admission retains its existing fresh-request behavior. A different pipeline
cannot be treated as already prepared. Database guards enforce tenant/candidate/kind,
immutable links and referenced target inputs. Legacy schedules without shared jobs,
promotion automation remain separate migration work. Empty-candidate
publication retains the existing rejection.

The periodic REST wizard offers explicit draft-only or stage-only behavior. Stage-only
requires the existing set preparation policy; it cannot silently replace shared settings.
The reviewed canonical pipeline fingerprint is stored in the private setup state and
compared against the current locked policy at final admission. Live profile grants and
status are rechecked; the schedule receives exact embedding/OCR references atomically
with source, contract and checkpoint completion. Old interval-only checkpoints retain
draft-only behavior. This introduces no second preparation authority or dispatch during
setup. Subsequent staging consults current policy, preserves the exact build lineage and
does not automatically activate data.

Explicit manual preparation of a completed REST, Confluence or MCP snapshot uses the
same write-once source-to-build link, publication and build/outbox transaction. The
current set manager reviews the existing preparation policy; final admission rechecks
actor/set/tenant authority, live source grants, source configuration checksum and the
reviewed pipeline fingerprint under the organization/job/candidate/policy locks. It
creates no schedule, new profile authority or activation. Linked replays cannot rebind
the snapshot or retry paid work; failed/cancelled work uses the existing retry controls.
Actor attribution is preserved on the link audit, and failed audit rolls back the
publication and link. Author-draft selection excludes all three connector candidate
types in SQL; membership mutation services reject an attached connector snapshot,
including before an upload writes its blob. Branching creates a separate author draft.

The setup entry uses an existing actively managed set or an explicitly created new set.
New-set creation retains organization administration and responsibility-management checks.
An eligible organization administrator explicitly accepts management of that new set;
the canonical assignment, set and private checkpoint commit together. This grants neither
an upstream connection nor rights over any existing set. A server-owned UUID intent and
organization serialization prevent duplicate POSTs from creating multiple sets. Entry
state is actor/organization-bound, signed, session-backed and bounded to five one-hour
entries; current authority is rechecked before restoration. Searching existing sets is
scope-filtered and capped at 100 results. Recovery accounts keep their existing explicit
recovery authority, without fabricated normal-user assignments.

Publishing a document-set version with automatic preparation persists the build
job, its exact policy references, outbox and audit in the publication transaction.
Only broker dispatch runs after commit. This closes the process-loss window where
publication could survive without any durable preparation intent. A preparation
record or audit failure rolls publication back; it never flips an active index.

A connection check is a separate explicit action. It uses the same first-page
request renderer as ingestion, with one request, no retries, at most 100 KB and a
ten-second upper deadline including DNS. The approved profile can further narrow
these limits. Checks reauthorize before secret access and I/O and before reporting
success; they hold no database transaction across external I/O. Audit admission is
committed first, with per-actor/organization throttling. Only counts and bytes are
returned; response data does not become documents, configuration or session state.
The resolver has four outstanding slots per process, retained until OS lookups
actually return even if their caller times out. This is additive to the MCP pool;
stuck OS resolvers remain a process shutdown/availability consideration.

## Resource-only MCP adapter

MCP resource ingestion uses an immutable platform profile, a separate revocable
tenant/collection approval and a typed Connection. A source can narrow the platform's
approved URI prefixes. MCP tool discovery or tool-use permission never grants resource
ingestion. Resource URI values are opaque identifiers sent only to the pinned endpoint;
they do not cause filesystem reads or secondary HTTP requests. The supported protocol
subset is MCP 2025-06-18 initialize, initialized, resources/list and resources/read.
Server instructions, tool calls and interactive requests cannot create authority.

The adapter shares the ingestion Job and Outbox. ResourceSnapshot has no independent
status; it records the owning job's attempt, bounded scan counts and candidate. Database
guards enforce exact lineage, current attempt context, immutable completed evidence,
and atomic success/candidate consistency. SourceDocumentCursor keeps URI identity,
checksum and last-seen job plus attempt, so a partial earlier retry is never mistaken
for a completed current scan. Completed MCP candidates join the existing trusted
candidate baseline; unchanged content reuses document versions and performs no embedding.

The HTTP deadline retains validated-IP pinning, hostname/certificate checks and bounded
response reads. DNS work is bounded to four outstanding resolver slots per process;
timed-out slots remain occupied until the operating-system resolver returns. Resource
grants are consulted before each remote request and fenced local write. The catalogue,
source, snapshot and gated console admission are tested offline against PostgreSQL.
The console projects job state without another status authority; it shows the latest
successful refresh separately from the latest recorded error and reuses runtime grant
checks for availability. Real-server interoperability and deployment
acceptance remain rollout gates for MCP resources.

MCP refresh plans use the existing ConnectorSyncSchedule and common Job/Outbox. Migration
0032 adds nullable schedule/slot evidence to ResourceSnapshot; manual history is unchanged.
The database prevents schedule rebinding, scope/type mismatches, snapshot schedule mutation
and duplicate schedule slots. Rolling back this lineage requires a privileged migration role
and empty scheduled-resource history. The scheduler skips missed intervals, serializes source
admission, redrives common outbox delivery and never sends MCP to a legacy REST task.

Resource plans support draft-only or stage-only. The collection manager reviews the existing
preparation policy; save rechecks the fingerprint, current source and model grants under the
organization lock. Completion rechecks grants and links the exact candidate to one canonical
preparation job. Disabling remains possible after grant revocation, without cancelling existing
jobs. No-change scans and disabled/draft-only plans create no build. MCP promotion automation
is not enabled by this change. The console separates fetch completion from preparation state.

Initial preparation settings can be saved before any document-set version exists. A reviewed
settings service reauthorizes the collection manager and live model/OCR grants under the
organization lock, checks a token covering the existing pipeline and auto-prepare flag,
and calls the canonical preparation service. The form changes only embedding, OCR, chunking
and auto-prepare; historical retrieval and summary references remain intact. Selecting the
visible standard chunking option creates an immutable artifact through existing document
profile authoring; deterministic set/body identity prevents duplicate default artifacts.
Artifact, settings and success audit are atomic, with no build or network work on save.

The REST wizard's preparation detour first saves inputs and interval in the existing private
checkpoint. The settings page accepts an owned, same-set draft UUID for return, never an
external return URL. Saving resumes step 3 so automatic preparation is explicitly selected
again against the now-current policy. No additional setup or policy table is introduced.

## Reviewed source configuration revisions

An edited REST source is a new immutable Source, contract and SourceConfigurationRevision
under the original source family. The existing writer and schedule remain selected until
explicit activation. Configuration history has one current member, immutable identity and
checksum, tenant RLS and database guards. The server-issued setup intent also identifies
retries; the existing private checkpoint and completion receipt preserve resumable editing.
Editing does not create a platform connection or grant. Configuration tokens cover current
source state, family revision number and actual schedule settings, excluding clock ticks.

Candidate snapshots replace only their source family's document slice. Other sources and
general serving cannot consume unselected revision documents. Selecting or restoring a
revision requires a successful exact snapshot→preparation→index chain, current source/model
grants and preparation policy, no active family work, and unchanged retained documents from
other sources. Organization and collection locks serialize the selection with admission and
serving. Current selection, canonical index activation, schedule transfer and audit commit
together. A deferred SQL guard also rejects selecting an unprepared revision. Old source,
cursor, document, job and schedule identities are preserved; historical data is not deleted.

The selected revision restores the refresh plan recorded when that revision was created;
later schedule-only edits are not silently folded into immutable configuration history.
The console previews this plan before selection. Current-source schedules remain editable.
Source revisions support manual, draft-only and stage-only plans; editing a source
with an enabled legacy promote-if-safe plan is rejected until the common promotion path is
implemented. Confluence and MCP now use the same family, isolated snapshots, exact prepared
selection and historical schedule restoration. They preserve connector kind within the family.
Their edit form binds actor/source/intent/current token to a one-hour signed submission and
requires a signed review of the normalized configuration before saving. Current grants are
rechecked on review, save, replay and selection. Existing unmapped sources are not materialized
by opening the form. No endpoint or grant is created by editing.
Migration 0037 extends the deferred proof to exact Confluence runs and MCP ResourceSnapshot
attempts. It also fences legacy REST/Confluence writers against active work in the same family.
It changes neither the private setup retention guard nor source data. Rollback requires a
privileged role and no non-REST revision history. Worker contract 11 requires draining old
workers before enabling this path; historical profile, source, document and audit IDs remain.
Migration 0033 requires draining old workers (job contract 10). Reverse migration requires a
privileged role and no revision/checkpoint history; it never removes saved history to proceed.

## Typed model catalogue identities

Migration 0034 extends Connection with exact, mutually exclusive model, embedding and OCR
profile references. The original global profile tables remain the authority for configuration,
status and existing grants. Registration calls the common materializer inside the profile/audit
transaction. Read-only app roles resolve an existing identity without catalogue writes or row
locks. Existing typed provider and grant checks are unchanged; an identity alone permits no
model execution, embedding, OCR, document ingestion or tool call.

Historical mapping uses frozen checksum fields and bounded iteration, preserves every profile
PK/revision and never reads a credential value. Database guards reject identity mutation,
cross-type provenance and changes to mapped profile configuration; status-only disable remains
valid. A different model or endpoint requires another profile revision. Empty migration rollback
is supported; rollback with mapped model identities requires a separate reviewed transition and
is rejected without discarding history. Invalid historical configuration is not silently repaired:
the strict runtime profile validator still rejects it.

## Tenant tool identities

Migration 0035 adds a seventh `tool` kind over an exact tenant-owned ToolDefinition.
Global profiles retain a null organization; a tool identity must carry its definition's
organization. Separate global/tenant uniqueness and a closed profile/type/scope constraint
allow the same tool name/version in two organizations without sharing identity or authority.
HTTP and MCP tool manifests remain in the original immutable registry. Their validated
checksum, organization and version determine the identity; credentials and manifests are
never copied into Connection or its audit metadata. ToolBinding, approval, execution and
egress policies remain authoritative and unchanged.

Canonical definition registration atomically materializes the identity and audit record.
Concurrent registration and historical materialization return one verified winner, including
a winner committed between Django's lookup and uniqueness validation. Tool bodies are sealed
by SQL except status/updated_at; tool identity creation requires no new UPDATE permission on
the tool registry. Existing global profile registration locks are unchanged.

Connection now has FORCE RLS with exactly two policies: global-or-current-tenant SELECT and
current-tenant tool-only INSERT. The app role gains INSERT only after provisioning verifies
these policies and FORCE RLS. Deployment readiness treats the nullable tenant column as an
explicit mixed catalogue, checks both exact policies and rejects additional permissive ones.
Neither service derives or broadens tenant scope from a supplied profile object.

Historical mapping is bounded and uses a frozen checksum contract. Mismatched manifest
checksums, mirrors or organization allowlists fail migration without silently repairing data.
Deferred FK checks are enforced before Django's deferred index DDL. Reversal requires a
privileged migration role, no tool identity history, and revocation of ordinary-role/PUBLIC
table or column INSERT grants before removing RLS. Existing owner privileges are unchanged.
Mapped history is never deleted to make reversal pass; a populated installation needs a
separately reviewed transition or forward fix. Apply schema migrations before provisioning
the updated app role. This increment adds no tool catalogue UI or provider call.

## Private setup expiry maintenance

Migration 0036 adds a nullable purge marker and partial expiry queue index over
existing private REST checkpoints. The fixed 30-day access deadline is unchanged.
An explicit table-owner maintenance command previews one organization and clears
only a bounded batch of expired, unfinished payloads and free-text names. It retains
identity, original expiry and audit evidence. Organization→draft locking, PostgreSQL
time and atomic per-batch audit prevent save/complete races and unaudited partial loss.
SQL rejects early/non-owner clearing and modification after clearing. A nonempty purge
history blocks reverse migration. The [operations runbook](../operations/rest-setup-retention.md)
owns the command, irreversible apply behavior and deployment cadence; no background
scheduler, source mutation or privilege grant is introduced.
