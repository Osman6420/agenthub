# Task Plan: codebase-memory-developer-tooling

## Task summary

Install Codebase Memory MCP as local developer tooling for Codex and Claude Code,
enable persistent graph and semantic search for this repository, and document the
required code-intelligence workflow.

## Background

The repository already uses Serena for precise symbol intelligence and `rg` for
exact textual search. Codebase Memory adds persistent structural, impact, and
meaning-based discovery, but its index is advisory and must not replace source,
authorization, migration, or test verification.

## Scope

- Install the signed/checksummed Windows UI binary outside the repository.
- Restrict indexing to this repository and use one shared local cache.
- Register the same stdio MCP server with Codex and Claude Code.
- Build a full index so graph and semantic relationships are available.
- Add durable usage guidance to `AGENTS.md` and `CLAUDE.md`.
- Add repository-specific indexing exclusions.

## Non-goals

- No AgentHub runtime or production dependency.
- No tenant/customer code indexing.
- No application API, authentication, authorization, or database changes.
- No committed graph database or downloaded binary.

## Acceptance criteria

- The installed release artifact passes its published SHA-256 check.
- Codex and Claude Code list the MCP server with the same executable, allowed
  root, and cache root.
- A full repository index completes successfully.
- Architecture/graph and semantic queries both return AgentHub results.
- Instructions clearly separate Codebase Memory, Serena, `rg`, direct inspection,
  and tests.
- Existing unrelated worktree changes are preserved.

## Affected components

- Local developer MCP configuration for Codex and Claude Code.
- `AGENTS.md`
- `CLAUDE.md`
- `.cbmignore`
- Task documentation

## Interfaces affected

Local MCP stdio tooling only.

## Data impact

A derived source-code graph and embeddings are stored in a user-local cache. No
application or tenant data is intentionally indexed.

## Security impact

The binary can read indexed source and modify its local graph. Installation must
verify release integrity, constrain `CBM_ALLOWED_ROOT`, keep diagnostics disabled,
and exclude secrets, runtime state, uploaded data, worktrees, and caches.

## Authorization impact

None in AgentHub. MCP tool authorization remains local to Codex/Claude.

## Observability impact

No application logging, metrics, tracing, or audit changes. Local Codebase Memory
daemon logs remain under its private cache.

## Migration impact

None.

## Dependencies

Developer-only Codebase Memory MCP v0.9.0 UI Windows AMD64 binary.

## Implementation steps

1. Inspect current instructions, worktree, and MCP registrations.
2. Download the pinned UI release plus checksums and attestation bundle.
3. Verify SHA-256 and install to a user-local tools directory.
4. Register identical constrained configurations in Codex and Claude Code.
5. Add `.cbmignore` and durable usage guidance.
6. Build a full index and verify graph plus semantic queries.
7. Review configuration, logs, diff, and residual risks.

## Test plan

- Release checksum comparison.
- Binary version/help smoke check.
- `codex mcp list/get` and `claude mcp list/get`.
- `index_repository` in full mode.
- `get_architecture` or graph schema query.
- `search_graph` with `semantic_query`.
- Instruction/diff review and secret-pattern scan of changed files.

## Rollout plan

Local developer installation only. Restart Codex and Claude Code after registration.

## Rollback plan

Remove the two MCP registrations and delete the explicitly installed tool/cache
directories after resolving their absolute paths. Revert only the files introduced
or edited by this task.

## Risks

- Third-party binary supply-chain compromise.
- Stale or incomplete graph results being treated as authoritative.
- Indexing secrets, uploads, worktrees, or runtime artifacts.
- Configuration drift between Codex and Claude causing incompatible cache use.
- Mutating MCP tools being invoked without a task requirement.

## Open questions

None; the user explicitly requested installation and both client integrations.

## Status

Verified.

## Completion criteria

Acceptance criteria are verified and recorded in `verification.md`; final diff and
local configuration are reviewed for security, correctness, and operability.
