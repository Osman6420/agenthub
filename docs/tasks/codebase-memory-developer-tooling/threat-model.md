# Threat Model: codebase-memory-developer-tooling

## Assets

- AgentHub source code and repository metadata.
- Developer MCP configurations.
- Local Codebase Memory graph, embeddings, and logs.

## Actors

- Authorized local developer.
- Codex and Claude Code agents.
- Third-party Codebase Memory release publisher.
- Malicious repository content attempting prompt/tool misuse.

## Entry points

- Downloaded release binary.
- MCP stdio tool calls.
- Repository files consumed by the indexer.
- Local MCP configuration and cache.

## Trust boundaries

- GitHub release artifact to local executable.
- Coding agent to Codebase Memory MCP process.
- Repository source to derived local graph.
- Shared Codebase Memory daemon/cache across Codex and Claude.

## Data classifications

Repository source and derived graph are confidential developer data. Secrets and
uploaded/runtime data must not be indexed.

## Authentication

Local stdio process; no remote authentication is involved.

## Authorization

`CBM_ALLOWED_ROOT` constrains repository access. Client MCP approvals and repository
instructions constrain intended tool use.

## Tenant isolation

No tenant runtime integration. Tenant/customer documents and uploads are excluded.

## External systems

GitHub Releases is used only to download the pinned artifact and verification files.

## Abuse cases

- A compromised binary reads files outside the intended repository.
- An agent invokes project deletion or ADR mutation unexpectedly.
- Indexed source text influences an agent to over-trust incorrect graph output.
- Codex and Claude run incompatible builds against one cache.

## Failure cases

- Checksum mismatch.
- Partial extraction or blocked executable.
- MCP registration points to the wrong executable.
- Full indexing degrades or semantic edges are absent.
- Daemon/cache collision between configurations.

## Logging and audit risks

Debug diagnostics could retain source-derived details. Diagnostics remain disabled.
Local daemon logs are not application audit records.

## Mitigations

- Pin v0.9.0 and verify the published SHA-256 before installation.
- Use the standard local-only stdio transport and loopback UI only.
- Set identical `CBM_ALLOWED_ROOT`, `CBM_CACHE_DIR`, and diagnostics settings.
- Add `.cbmignore` exclusions for secrets, uploads, caches, worktrees, and runtime
  files.
- State that graph/semantic results are advisory and require Serena/`rg`/source/test
  confirmation.
- Require explicit task need for mutating Codebase Memory tools.

## Residual risks

SHA-256 verifies publisher consistency, not publisher trust. Static and semantic
analysis can remain incomplete, particularly around Django runtime registration and
dynamic dispatch.

## Required security tests

- Verify checksum.
- Confirm allowed root and cache settings in both MCP registrations without exposing
  unrelated secrets.
- Confirm ignored sensitive paths are absent from the intended indexing scope.
- Scan changed repository files for accidental credentials.
