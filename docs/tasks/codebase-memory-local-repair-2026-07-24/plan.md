# Task Plan: codebase-memory-local-repair-2026-07-24

## Task summary
Repair the local Codebase Memory MCP v0.9.0 runtime so one canonical AgentHub index stays current, the background watcher converges, SQLite WAL growth is bounded, and the graph UI listens on port 9749.

## Follow-up: commit-aware refresh
The first supervisor detected dirty-worktree changes, but v0.9.0 could report a
successful incremental index after a commit while retaining the prior graph.
Persist the last successfully rebuilt HEAD, use incremental updates only within
that HEAD, and perform a clean full rebuild whenever HEAD changes or supervisor
state is absent. Resolve and verify the rebuilt project by repository path, exact
HEAD, and non-zero graph counts before recording success.

## Background
The local cache contains duplicate indexes for the same repository, multiple long-lived MCP processes, no listener on port 9749, and a roughly 12 GB WAL beside a roughly 32 MB graph database. `detect_changes` reports 961 changed files after an explicit full index.

## Scope
- Preserve the current cache during repair, then remove obsolete backups after verification and explicit user approval.
- Recreate a clean local cache and one canonical `agenthub` index.
- Enable automatic first indexing and background watching.
- Verify UI reachability, index freshness, process roles, and bounded WAL behavior.

## Non-goals
- Modify AgentHub application behavior.
- Change production dependencies, APIs, authentication, authorization, tenant isolation, or production data.

## Acceptance criteria
- `index_status` reports the canonical `agenthub` index ready.
- A controlled source edit appears in the graph automatically and the final clean rebuild contains no probe nodes.
- `127.0.0.1:9749` accepts HTTP connections.
- No runaway index worker loop is present.
- The active WAL remains bounded and does not grow by gigabytes during verification.
- Obsolete cache, WAL, artifact, and diagnostic backups are removed after successful verification.
- A committed HEAD change is not acknowledged until a clean full rebuild reports
  the expected repository path, exact HEAD, and a non-empty graph.

## Affected components
- Local Codebase Memory MCP process set.
- Local Codebase Memory cache under `%LOCALAPPDATA%\codebase-memory-mcp`.
- Codex MCP configuration pointing to the supervisor-owned loopback HTTP MCP
  endpoint so interactive sessions do not open competing SQLite processes.
- This task record only; no AgentHub source component.

## Interfaces affected
Local MCP stdio and local-only HTTP UI on `127.0.0.1:9749`.

## Data impact
The local derived code graph is rebuilt. Repair backups are removed after successful verification and explicit user approval. Repository source files are not modified by the repair, except for this task documentation and local-state ignore rules.

## Security impact
No network exposure is added beyond the existing loopback-only UI. Cache paths remain under the current user profile.

## Authorization impact
None.

## Observability impact
Record process, port, index status, change count, and WAL-size evidence in `verification.md`.

## Migration impact
No application migration. Local derived cache replacement only.

## Dependencies
Codebase Memory MCP v0.9.0 UI binary and Codex MCP configuration.

## Implementation steps
1. Capture live process, port, cache, index, and configuration evidence.
2. Disable watcher startup while repairing and stop only exact Codebase Memory processes.
3. Move the complete cache directory to a timestamped backup.
4. Create clean configuration with UI, auto-index, and watcher enabled.
5. Build one canonical `agenthub` index.
6. Start/reconnect MCP, verify UI and watcher convergence.
7. Review the task diff and record verification.

## Test plan
- CLI `list_projects`, `index_status`, and `detect_changes`.
- Windows process and TCP listener inspection.
- HTTP request to `http://127.0.0.1:9749`.
- Repeated WAL-size and worker-process observations.

## Rollout plan
Perform locally after recoverable cache backup. Reconnect Codex MCP after the new cache is ready.

## Rollback plan
Before cleanup approval, stop Codebase Memory processes, move the new cache aside, and restore the timestamped backup directory. After approved cleanup, rebuild the derived graph from repository source.

## Risks
- Open MCP clients may respawn processes during repair.
- An uncheckpointed WAL may contain the newest copy of the old derived graph; preserve it until the clean graph is verified and cleanup is approved.
- Other open Codex sessions may keep separate stdio MCP processes, though shared work must not produce duplicate writers.
- The current v0.9.0 binary may contain a watcher/coordination defect that requires an upstream update.

## Open questions
Whether the upstream dirty-state signature and incremental Markdown deletion fixes will be included in the next release after v0.9.0, allowing removal of the local supervisor.

## Status
Completed.

## Completion criteria
Acceptance criteria are verified with recorded commands; approved cleanup is complete; final operational and security review is complete.
