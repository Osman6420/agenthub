# Verification: phase-2-5-part-5-source-mapping-index-journey

## Status
Verified. Authenticated Turkish owner browser review remains before Completed.

## Evidence
- Final focused connector workspace + Part 4 compatibility: 19 passed in 9.41s.
- Full SQLite: 675 passed, 29 skipped in 35.66s.
- Full PostgreSQL/pgvector/RLS with MCP and metrics enabled: 699 passed, 5 skipped in 102.89s.
- Focused source detail tests cover safe profile/mapping labels, endpoint/credential/input redaction,
  safe failure code/counts, auditor read-only behavior and cross-tenant 404.
- Existing connector tests cover no-egress bounded synthetic preview, exact profile grants, role split,
  IDs-only task dispatch, terminal broker failure and promotion-target scoping.
- Mypy: success across 356 source files.
- Ruff format/check, Django system check, migration drift check, compileall and `git diff --check`
  completed cleanly.
- In-app browser smoke test reached the Turkish `Giriş · AgentHub` page and confirmed the console is
  session-gated. No credentials were requested or created.

## Environment notes
- The repository `.venv` launcher was unavailable because its Microsoft Store Python package returned
  `A specified logon session does not exist`. Tests ran against the mounted workspace in a temporary
  official Python 3.13 container with dependencies resolved from the unchanged `pyproject.toml`.
- The canonical Compose application image cannot currently build because its Dockerfile runs
  `pip install .` before copying the `config` package. This pre-existing infrastructure defect is not
  changed by Part 5; PostgreSQL, Redis and MinIO were independently confirmed healthy.

## Pending manual evidence
- Authenticated Turkish owner review of the source wizard and source detail pages.
