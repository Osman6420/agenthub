# Task Plan: serena-agent-setup

## Task summary
Install Serena on native Windows and configure this repository for semantic Python and TypeScript navigation from Claude Code and Codex.
## Background
The repository contains a Django/Python backend and a React/TypeScript frontend. Node/npm, Claude Code, and Codex are installed; uv and Serena are not.
## Scope
- Install uv and Serena using the current official installation path.
- Initialize Serena's language-server backend.
- Create and index a repository-local Serena project for Python and TypeScript.
- Register Serena with Claude Code and Codex using their supported setup commands.
- Verify executable, project, index, and MCP registration state without recording secrets.
## Non-goals
- No application, dependency manifest, runtime, database, authorization, or production configuration change.
- No speculative Claude/Codex hooks or shell-profile aliases.
## Acceptance criteria
- `uv`, `uvx`, and `serena` are available and report versions.
- `.serena/project.yml` enables Python and TypeScript and ignores generated/vendor content.
- Serena can index this repository.
- Claude Code and Codex list a Serena MCP server.
## Affected components
Developer tooling; repository-local `.serena` metadata; user-level Claude Code and Codex MCP configuration.
## Interfaces affected
Local MCP tool availability only.
## Data impact
Serena indexes local source metadata. No production or tenant data is accessed.
## Security impact
Installing an external developer tool and allowing it to read/write repository files through MCP expands the local tool trust boundary.
## Authorization impact
None in the application. Local agents retain their own approval and sandbox controls.
## Observability impact
Local Serena logs/cache only; no application telemetry change.
## Migration impact
None.
## Dependencies
uv and `serena-agent` as user-level developer tools; no production dependency.
## Implementation steps
1. Install uv and Serena from their official distribution path.
2. Initialize Serena and create the project configuration.
3. Review generated configuration, apply minimal repository-specific settings, and index.
4. Configure Claude Code and Codex MCP clients.
5. Verify versions, MCP registrations, generated files, and final diff.
## Test plan
Run version checks, Serena project/index checks, and each client's MCP listing command.
## Rollout plan
Local workstation only; restart agent sessions after configuration.
## Rollback plan
Remove Serena MCP registrations, uninstall `serena-agent`, and remove repository-local `.serena` metadata if desired.
## Risks
- Installer/package supply-chain risk.
- MCP server receives repository access when invoked.
- Indexing may be slow or include unintended generated files if ignore settings are wrong.
## Open questions
None; use native Windows because the repository and both clients run on native Windows.
## Status
Verified.

## Completion criteria
Repository configuration and user-level MCP registrations are verified; security implications and the required session restart are reported.
