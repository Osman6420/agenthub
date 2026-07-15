# Verification: serena-agent-setup

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| uv installed | `uv --version`; `uvx --version` | Pass | Both report `0.11.28` | User-level developer tool. |
| Serena installed | `serena --version` | Pass | `Serena 1.5.3` | Installed as `serena-agent` with Python 3.13. |
| Serena initialized | `serena init` | Pass | LSP backend; config at `%USERPROFILE%/.serena/serena_config.yml` | No JetBrains backend. |
| Project created and indexed | `serena project create --name agenthub --language python --language typescript --index .` | Pass | 288 Python and 17 TypeScript files indexed | Generated caches are ignored by `.serena/.gitignore`. |
| Claude Code MCP | `claude mcp list` | Pass | `serena ... Connected` using `--context=claude-code --project-from-cwd` | User scope; executable uses an absolute path so VS Code does not depend on a refreshed PATH. |
| Codex MCP | `codex mcp list` | Pass | `serena ... enabled` using `--context=codex --project-from-cwd` | Executable uses an absolute path; stdio auth is not applicable. |
| Secret/config review | `rg` and generated-file inspection | Pass | Versioned Serena files contain project metadata only | Local cache and overrides are ignored. |

## Acceptance criteria mapping
All installation and registration acceptance criteria are met. Python and TypeScript
are explicitly enabled and indexing completed. On 2026-07-15 the Codex app's actual
CLI binary again reported Serena as `enabled`; the already-running task did not expose
Serena tools because its MCP capability set was fixed at task startup.
## Security requirement mapping
Official installation/setup commands were used. MCP startup is scoped from the client's current working directory. No credentials or production endpoints were added.
## Authorization tests
Not applicable; application authorization is unchanged.
## Cross-tenant tests
Not applicable.
## Logging and redaction tests
Generated versioned files contain no secrets. User-level client files were not copied into repository evidence.
## Audit event tests
Not applicable.
## Migration verification
Not applicable.
## Behavior comparison with base branch
Only repository-local Serena metadata and task documentation were added. The pre-existing untracked `.claude/settings.local.json` was left unchanged.
## Checks not run
Application formatter, linter, type checker, tests, database checks, and frontend gates were not run because no application source, dependency manifest, runtime configuration, or schema changed.
## Remaining risks
Serena and its managed language servers are third-party local executables with repository access. First semantic calls may still download managed language-server assets. Indexes can become stale and should be regenerated after unusually large changes.
## Human review required
Restart Codex (or create a fresh task after reloading the app), then confirm the new
task exposes Serena symbol tools before relying on them. Review and approve Serena MCP
actions under the clients' normal permission model. Optional Claude Code hooks were
intentionally not installed.
## Final status
Verified.
