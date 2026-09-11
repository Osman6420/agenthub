# Threat Model: serena-agent-setup

## Assets
Repository source, local developer configuration, and uncommitted work.
## Actors
The local user, Claude Code, Codex, Serena, uv, and Serena-managed language servers.
## Entry points
Serena CLI, MCP stdio processes, language servers, and generated project configuration.
## Trust boundaries
External package distribution to local executable; agent client to Serena MCP; Serena to repository filesystem and language servers.
## Data classifications
Repository code and local metadata; no production credentials or tenant data are intentionally involved.
## Authentication
Not applicable to local stdio MCP.
## Authorization
Client sandbox/approval policies remain authoritative; Serena must be scoped to the current project.
## Tenant isolation
No application requests or databases are involved.
## External systems
Official uv installer/package indexes and Serena-managed language-server downloads.
## Abuse cases
Compromised packages, excessive filesystem scope, accidental edits, secret exposure through indexing/logging, or duplicate MCP definitions.
## Failure cases
Partial installation, PATH not refreshed, language-server bootstrap failure, stale index, or one client not loading updated configuration.
## Logging and audit risks
Local tool logs may contain paths or snippets; never add credentials to project configuration or verification evidence.
## Mitigations
Use official documented commands, project-from-current-directory client setup, Git ignore rules, review generated files, and avoid unverified hooks/profile modifications.
## Residual risks
Serena and downloaded language servers are third-party executables with repository access; users must keep them updated and review MCP tool actions.
## Required security tests
Inspect generated configuration for secrets and unintended absolute paths; confirm no application security controls changed.
