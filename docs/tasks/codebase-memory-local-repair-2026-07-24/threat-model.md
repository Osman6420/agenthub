# Threat Model: codebase-memory-local-repair-2026-07-24

## Assets
AgentHub source code, local derived graph, local disk capacity, and Codex MCP availability.

## Actors
Current Windows user, Codex MCP clients, and the local Codebase Memory binary.

## Entry points
MCP stdio, Codebase Memory CLI, local cache files, and loopback HTTP port 9749.

## Trust boundaries
Repository to local graph parser; Codex client to MCP process; MCP processes to shared SQLite cache; browser to loopback UI.

## Data classifications
Repository source and structural metadata are local confidential development data.

## Authentication
The loopback UI has no separate authentication and must remain bound to `127.0.0.1`.

## Authorization
Repair commands target only the current user's Codebase Memory processes and cache.

## Tenant isolation
Not applicable.

## External systems
None.

## Abuse cases
Binding the UI externally, deleting the wrong cache, or stopping unrelated processes.

## Failure cases
Process respawn during repair, incomplete cache move, failed re-index, runaway watcher, or continued WAL growth.

Codebase Memory v0.9.0 can advance project Git metadata without applying committed
structural changes. The supervisor must retry rather than persist the new HEAD
unless a clean rebuild resolves the exact repository path, expected HEAD, and
non-zero graph counts.

## Logging and audit risks
Logs may contain local paths but must not contain repository contents or secrets in the task record.

## Mitigations
Resolve exact executable paths and process names, preserve the complete cache via same-volume rename, bind only to loopback, avoid wildcard deletion, and verify after each state transition.

Use one supervisor-owned Codebase Memory process. Codex sessions connect through
its loopback HTTP MCP endpoint instead of spawning additional stdio processes that
hold the Windows SQLite database open.

## Residual risks
An upstream v0.9.0 coordination defect may remain after clean initialization.

## Required security tests
Confirm listener address is loopback-only and no unrelated process is stopped.
