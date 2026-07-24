# Threat Model: Phase 2.8 Part 3 — Unified workflow engine

## Assets and data classification

Tenant/actor/consumer identity, capabilities, exact release/workflow artifacts, retrieval grants and
indexes, tool/approval authority, prompts/model/tool results, checkpoints, Run/RunEvent integrity,
usage/audit and public API compatibility. Prompts, chunks, state and outputs are tenant-confidential;
credentials/secrets are restricted and forbidden from DSL, events and logs.

## Actors and entry points

Authenticated consumers/operators, workers, model/tool/retrieval providers, malicious DSL/document/
prompt authors, replaying clients and stale/compromised workers. Entry points are Responses, Chat
Completions, run status/cancel, MCP, Studio publish, worker tasks, approvals/resume signals, sync
disconnect and recovery tooling.

## Trust boundaries

Client bodies/mode, node config, DSL, model/tool results, provider errors, task payloads and external
Responses IDs are untrusted. Compiler output is trusted only after exact release/checksum/version
verification and is independently revalidated by runtime. Tenant, actor, tool/capability and
retrieval ACL scope always comes from authenticated server state. PostgreSQL FORCE RLS backs direct
tenant tables.

## Principal threats and mitigations

| Threat | Required mitigation |
| --- | --- |
| Client/node widens tenant, actor, tool or retrieval authority | Reject protected fields/mappings; derive and revalidate authority server-side at admission/transition |
| Agent config generalized into unsafe workflow | Closed `agent_loop` schema; exact roles/budgets/timeouts; runtime action revalidation |
| Prompt/document injection obtains tool/capability | Model decisions are untrusted data; immutable compiled allowlist and argument schema every step |
| RAG loses ACL/grounding/citation integrity | Authorized pinned index scope; server grounding/fallback; runtime-generated citations only |
| Client lies about sync capability | Compiler reasons from exact graph/dependencies; runtime checks compiled checksum and requested mode |
| Tool/agent marked sync despite possible pause | Whole-graph reachability, approval/escalation, timeout and bound analysis; stable blocker codes |
| Sync path bypasses persistence/policy | Same transition service and Run/Event/usage/audit boundary as workers |
| Disconnect silently becomes background work | Sync lease and cooperative cancellation; no automatic takeover; explicit recovery state |
| Cancel/completion or late-result race reopens run | Row lock/version token, first terminal transition wins, terminal guard discards late results |
| Concurrent events reorder/collide | Run-row counter allocation in transition transaction plus unique `(run, sequence)` |
| Event payload leaks/DoS | Closed per-event schemas, redaction, 16 KiB/depth caps, forbidden content classes |
| Responses ID confused with authority/run ID | Separate stored opaque `resp_...`; UUID-only run endpoints/header; neither substitutes authorization |
| Cross-tenant run/status/cancel/child access | Exact object predicate, direct tenant lineage, generic denial and FORCE RLS |
| Duplicate/late worker repeats external side effect | Idempotency/transition token; terminal guards; `outcome_unknown` rather than blind retry |
| Transition token is replayed with altered state/counters | Persist a canonical request checksum with the token; exact replay returns the recorded result and mismatched replay fails closed |
| Expired sync lease is claimed by a background worker | Lease resolution requires the exact token and expiry under the Run row lock; it enters recovery/cancelled and never queues work |
| Forged task payload widens tenant/actor/capability/checkpoint authority | Identifier-only delivery; tenant context is required for RLS lookup and all actor/capability/release/checkpoint authority is reloaded from the locked Run |
| Duplicate delivery or competing worker steals an active claim | UUID claim token plus bounded expiry and checkpoint snapshot under the Run row lock; exact replay is inert and a different live token fails closed |
| Stale worker commits after ownership/checkpoint changed | Every background transition proves the unexpired claim token and expected checkpoint version in the same transaction; terminal and waiting transitions clear ownership |
| Worker crashes before versus after external work | External work is forbidden before the `running` transition; an expired queued claim may be replaced, while an expired running claim enters `recovery_required` without automatic takeover |
| Cancellation/deadline races with claim or delivery | Claim and every transition re-check cancellation, terminal state and authoritative deadline under lock before work; cancellation/timeout wins before ordinary progress |
| Broker/task/audit logging leaks confidential state | Task carries identifiers only; events/audit use closed safe reason codes; logs/metrics exclude task bodies, checkpoint, prompt, model/tool results, credentials and raw tokens |
| Stale worker reads new DSL/checkpoint | Atomic fleet cutover and explicit compiler/checkpoint versions |
| Kill-switch race admits/resumes work | Check authoritative control at admission and each transition claim |
| Broker forges a compatible worker/compiler revision | Treat delivery revision as diagnostic only; reload Run/WorkflowVersion checksum and compiler pins and compare with locally supported versions before claim |
| Legacy WorkflowRun executor mutates side tables for a unified Run | Do not register the unified Celery task until branch/wait/recovery persistence is Run-native; fail closed at the adapter boundary |
| Initial Run-native executor accidentally reaches a side effect or durable pause | Default-off gate plus exact node-type allowlist; reject the whole graph before `running`; no fallback to legacy `execute_graph` |
| Redelivery repeats start/completion transitions | Derive stable purpose-separated transition UUIDs from the delivery claim token and reuse transition checksum replay/terminal guards |
| Stale fleet delivery claims a Run | Compare bounded diagnostic message revision with the local immutable service revision, then independently validate stored compiler/checksum pins |
| Worker dies after queued claim but before `running` | `acks_late` redelivery resolves the exact expired queued token, clears ownership with safe audit evidence and reclaims it; no external work is permitted before `running` |
| Worker dies after `running` and lease expires | Exact-token redelivery resolves to `recovery_required`; never auto-take over or blindly repeat potentially ambiguous work |
| Destructive migration deletes real state | Immediate pre-cutover zero-state/consumer proof and separate exact migration approval |
| Rollback cannot restore removed schema | Tested previous-code + empty-database rebuild; stop cutover if environment is not disposable |

## Failure and race cases

Request disconnect before/after headers, process death without disconnect hook, sync lease expiry,
model/tool timeout, cancellation during external call, cancellation versus completion, provider late
result, duplicate task/event, worker crash after side effect, approval/resume race, checkpoint/contract
mismatch, audit/usage outage, migration partial failure and stale worker startup. Every case needs a
defined transactional state/result and safe stable reason; no implicit mode change is allowed.

## Logging and audit risks

Never log DSL bodies, prompts, chunks, model/tool payloads, safe execution-context claims in full,
credentials, external task bodies or event payloads. Audit admission, completion, cancellation,
approval, recovery and denial with safe UUIDs/checksums/counts/reasons. External `resp_...` may appear
only where required for response correlation and never as a metric label or authorization subject.

## Residual risks

One engine concentrates authority and atomic breaking cutover increases rollback cost. Request
disconnect cannot guarantee cancellation of an already-sent external side effect. These risks are
accepted only with bounded timeouts, explicit recovery semantics, semantic parity, concurrency/load
tests, zero-data/consumer proof and the tested empty-database rollback.

## Required security tests

Protected field/mapping injection; forged client mode/compiler reason; sync tool/agent eligibility;
prompt injection/invented tools; ACL/citation/fallback; cross-tenant API/worker/child/approval/tool/
retrieval; concurrent event writers; disconnect/lease/cancel/complete/late-result races; duplicate and
stale transitions; event schema/size/redaction; Responses ID confusion; kill switch; audit/usage
outage; non-owner RLS; zero-state/API-consumer evidence; destructive/empty-rebuild drill and static
removed-reference scan.
