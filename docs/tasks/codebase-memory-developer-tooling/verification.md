# Verification: codebase-memory-developer-tooling

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Initial state | `git status --short`; `codex mcp list`; `claude mcp list` | Passed | Existing unrelated changes recorded; Codex had no MCP server and Claude had a failing Serena entry | No existing user work modified |
| Release integrity | `Get-FileHash -Algorithm SHA256 codebase-memory-mcp-ui-windows-amd64.zip`; compare with v0.9.0 `checksums.txt` | Passed | `9b53ebb86698776c4134747a2285643ce075268df3858f2f4dbb392eede2de17` matched exactly | GitHub release UI Windows AMD64 artifact |
| Installed binary | `codebase-memory-mcp.exe --version` | Passed | `codebase-memory-mcp 0.9.0`; installed executable size `274673664` bytes | User-local install, not committed |
| Codex registration | `CODEX_HOME=C:\Users\kuzuc\.codex codex mcp get/list` | Passed | Enabled stdio server, pinned executable, `--ui=true --port=9749`, redacted environment | Existing Serena and other MCP entries preserved |
| Claude registration | `claude mcp get codebase-memory-mcp` | Passed | User-scoped stdio server reported `Connected` with the same executable, args, root, cache, and diagnostics setting | Existing failing Serena entry was not changed |
| Full index | `codebase-memory-mcp cli index_repository --repo-path ... --mode full --persistence false` | Passed | Status `indexed`; 10,000 nodes and 43,610 edges | Cache DB `31,588,352` bytes; no graph artifact committed |
| Graph status/schema | `index_status`; `get_graph_schema`; `get_architecture(aspects=["overview"])` | Passed | Status `ready`; 2,134 functions, 874 files, 7,221 call edges, 40 routes | Architecture query returned AgentHub packages, routes, hotspots, boundaries, layers, and clusters |
| Semantic index/search | `search_graph(semantic_query=["tenant","authorization","capability"], limit=10)` | Passed | Three-keyword vector query returned scored AgentHub results; graph contains 311 `SEMANTICALLY_RELATED` and 168 `SIMILAR_TO` edges | Confirms full semantic path rather than BM25-only search |
| Local graph UI | Start MCP with `--ui=true --port=9749`; `Invoke-WebRequest http://127.0.0.1:9749/` | Passed | HTTP `200`, `text/html`, then clean MCP exit `0` | Loopback-only functional smoke |
| Instruction formatting | `git diff --check -- AGENTS.md CLAUDE.md` | Passed | No whitespace errors | `.cbmignore` and task files manually reviewed |
| Secret review | `rg -n -i "api[_-]?key|secret|token|password|private[_-]?key" ...` | Passed | Matches were policy prose only; no credential values added | Local MCP inspection redacted environment values |

## Acceptance criteria mapping

- Published checksum matched: verified.
- Both clients use one executable, allowed root, and cache: verified.
- Full graph and semantic index: verified.
- Architecture and semantic queries: verified.
- Durable tool-selection guidance: implemented and reviewed.
- Existing unrelated worktree changes: preserved.

## Security requirement mapping

- `CBM_ALLOWED_ROOT` is exactly `C:\Users\kuzuc\Desktop\agenthub`.
- `CBM_CACHE_DIR` is shared and user-local.
- `CBM_DIAGNOSTICS=false` in both clients.
- UI binds and responds on loopback configuration.
- `.cbmignore` excludes local secrets, keys, uploads, worktrees, caches, databases,
  downloaded tooling, and generated graph artifacts.
- Release SHA-256 matched the publisher manifest.

## Authorization tests

Not applicable to AgentHub runtime.

## Cross-tenant tests

Not applicable; no tenant/runtime integration.

## Logging and redaction tests

MCP list output redacted configured environment values. Diagnostics are disabled.
No application logs or audit events are affected.

## Audit event tests

Not applicable.

## Migration verification

Not applicable.

## Behavior comparison with base branch

Only developer instructions, `.cbmignore`, and this task record are introduced in
the repository. No Python, TypeScript, application configuration, migration, or
runtime behavior changed.

## Checks not run

- GitHub/Sigstore attestation verification was not run; SHA-256 verification against
  the release manifest passed.
- Application formatter, linter, type-check, unit, integration, migration, and
  runtime checks were not run because no application code or runtime configuration
  changed.
- A fresh Codex/Claude interactive task was not opened; CLI registration, Claude
  connection, direct MCP CLI queries, and UI transport were verified. Open clients
  still require restart to load the new server.

## Remaining risks

- Codebase Memory v0.9.0 has a built-in non-overridable directory skip list that
  excludes this repository's `deploy/` directory even in full mode. Deployment
  configuration must continue to be inspected with `rg` and direct file reads.
- Graph and semantic results remain advisory and may miss Django dynamic behavior.
- The publisher checksum does not independently establish publisher trust.
- The full graph includes the current dirty worktree state and should be refreshed
  after substantial branch changes.

## Clean reindex investigation — 2026-07-23

- The original database was copied to a recoverable local `.bak` file before any
  cache mutation.
- Re-running `index_repository(mode=full)` against the existing database completed
  as an incremental no-op because all indexed file hashes were already current.
- The MCP/UI processes holding the SQLite files open were stopped, the active
  database and WAL/SHM files were moved to recoverable `.bak` names, and a clean
  full index was built from an empty project cache.
- The clean build completed with `skipped_count=0`,
  `expected_nodes=10000`, `nodes=10000`, `expected_edges=43610`, and
  `edges=43610`. The matching expected and persisted counts pass the v0.9.0 dump
  integrity check.
- Inspection of the pinned v0.9.0 source confirmed that `expected_nodes` is the
  pipeline's committed in-memory node count, not a configured ceiling. The graph
  buffer uses dynamically growing arrays and the index pipeline has no 10,000-node
  cap. The exact count is therefore the deterministic output for the current
  repository and exclusions, not evidence of truncation.
- `index_status` returned `ready`; a direct Cypher count returned 10,000; semantic
  vector search returned scored AgentHub symbols.
- The UI process was restarted on loopback. `/api/project-health` returned
  `healthy` with 10,000 nodes and 43,610 edges, and `/api/repo-info` resolved the
  expected repository and branch. `/api/index-status` returning `[]` means no
  indexing job is currently active; it is not the project inventory endpoint.
- Diagnostics were enabled transiently for the clean build. The build completed
  in under two seconds, before the five-second diagnostics sampling interval, so
  no diagnostics trajectory file was emitted. The configured persistent setting
  remains disabled.

## Node-count mutation experiment — 2026-07-24

- The AgentHub working tree was copied to the local sibling test directory
  `C:\Users\kuzuc\Desktop\.kopyadenemeagenthub`, excluding Git metadata,
  virtual environments, dependencies, worktrees, and runtime caches.
- A separate `kopyadenemeagenthub` full index established the baseline:
  10,001 nodes, 43,471 edges, 874 `File` nodes, 809 `Module` nodes, and
  3,490 `Section` nodes.
- Copying the existing ADR README into the test root as
  `CBM_NODE_COUNT_PROBE.md` added one Markdown document containing two headings.
  Reindexing produced 10,005 nodes and 43,474 edges: exactly +1 `File`,
  +1 `Module`, +2 `Section`, and +3 edges. `search_code` resolved the new
  document's `Architecture Decision Records` section.
- The probe document was then deleted and the test copy was reindexed. Counts
  returned exactly to the baseline: 10,001 nodes, 43,471 edges, 874 `File`,
  809 `Module`, and 3,490 `Section`. A scoped `search_code` query returned zero
  matches for the deleted path.
- The test project reported `ready` with `skipped_count=0`. This controlled
  add/delete experiment demonstrates that node counts can exceed 10,000 and that
  incremental deletion removes the document's nodes and edges without leaving
  stale graph records.

## Human review required

Restart Codex and Claude Code, confirm the MCP appears in each interactive `/mcp`
view, and review future third-party updates before replacing the pinned binary.

## Final status

Verified.
