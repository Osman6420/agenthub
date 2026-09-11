# Verification: codebase-memory-local-repair-2026-07-24

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Baseline index status | `codebase-memory-mcp cli index_status --project agenthub` | Failed freshness gate | Ready graph with 10,048 nodes and 44,096 edges, but 961 detected changes | `ready` alone does not prove freshness |
| Baseline UI | TCP connection test to `127.0.0.1:9749` | Failed | No listener | Configuration requested UI on 9749 |
| Baseline WAL | Inspect canonical cache files | Failed bounded-growth gate | WAL grew from about 9.6 GB to 11.9 GB | Base graph database was about 32 MB |
| Baseline processes | Inspect exact executable process tree | Investigating | Multiple persistent stdio MCP processes plus transient index workers | No process stopped yet |
| Recoverable cache replacement | Exact-process stop, same-volume cache moves | Passed | Original cache preserved through repair | Backup existed until clean-index verification and cleanup approval |
| Approved cleanup | Exact-path removal and remaining-size inspection | Passed | Old cache/WAL, failed-repair indexes, artifact backup, and prior diagnostic logs removed | Active cache remains about 31 MB |
| Canonical project | `cli list_projects` | Passed | Exactly one project: `C-Users-kuzuc-Desktop-agenthub` | Removed the conflicting explicit `agenthub` name |
| Configuration | `config list` | Passed | `auto_index=true`, `auto_watch=false`, file limit 50,000 | Built-in watcher disabled because v0.9.0 reindexed an unchanged dirty tree |
| Automatic update | Controlled heading/section probes plus `search_graph` | Passed | Added probe appeared automatically; final clean rebuild reports zero probe nodes | Local supervisor polls the Git dirty-state signature every 6 seconds |
| Idle stability | Inspect supervisor signature log after controlled edit and repeated polls | Passed | One change, one committed signature, then zero additional changes/commits/warnings | Native Git stderr is excluded and malformed Windows status JSON is handled |
| WAL stability | Inspect canonical DB sidecars | Passed | Final WAL size 0 bytes | Canonical DB is about 32.5 MB |
| UI | HTTP request and listener inspection | Passed | HTTP 200 on loopback port 9749 | Loopback-only binding |
| Stale committed graph reproduction | Git diff, project inventory, and scoped graph searches | Failed freshness gate as expected | Project metadata reported HEAD `be7958c` and 10,197 nodes while new committed symbols were absent | Confirmed v0.9.0 incremental success was a false freshness signal |
| Commit-aware clean rebuild | Supervisor restart without prior indexed-HEAD state | Passed | Exact HEAD `be7958c`, 10,263 nodes, 44,684 edges | State is persisted only after repository-path, HEAD, and non-zero-count verification |
| New-symbol freshness | Scoped `search_graph` over the rebuilt graph | Passed | `renew_sync_lease` and `_transition_checksum` are present with current signatures | Both symbols were absent before the clean rebuild |
| Single-writer MCP topology | Codex config and live process inspection | Passed | Codex uses `http://127.0.0.1:9749/rpc`; supervisor owns the only graph process | Removed per-session `--ui=false` SQLite writers |
| Rebuild WAL | Inspect canonical SQLite sidecars after rebuild | Passed | WAL is 0 bytes | Canonical database is about 32.6 MB |
| Startup persistence | Windows scheduled task inspection | Passed | `AgentHub-CodebaseMemory-Supervisor`, user logon, limited run level, ignore duplicate instances | Named mutex also rejects duplicate supervisors |
| Script validation | PowerShell parser and `git diff --check` | Passed | No syntax or whitespace errors | Application test suite not applicable |

## Acceptance criteria mapping
Canonical index, bounded update behavior, UI availability, WAL stability, approved cleanup, and startup persistence are verified.

## Security requirement mapping
The repair is local-only, retains no obsolete source-derived backup after approved cleanup, and confirms loopback binding.

## Authorization tests
Not applicable.

## Cross-tenant tests
Not applicable.

## Logging and redaction tests
Supervisor logs contain local paths and lifecycle events only; no secrets or repository contents were observed.

## Audit event tests
Not applicable.

## Migration verification
Not applicable.

## Behavior comparison with base branch
No AgentHub application behavior change is intended.

## Checks not run
AgentHub application tests were not run because no application runtime behavior changed.

## Remaining risks
Codebase Memory v0.9.0 incremental Markdown deletion left stale section nodes
during probing. The final graph was rebuilt from source without the artifact, so
it is clean now. The local supervisor remains a workaround until upstream
incremental commit freshness and Windows multi-process coordination are reliable.

## Human review required
None.

## Final status
Completed.
