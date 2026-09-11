# Verification: Phase 2.8 Part 4 — Scenario authoring and release experience

> **Status: Automated/offline verified on 2026-07-28.** Live provider and browser acceptance remain
> explicit deployment/manual checks; no code or automated acceptance failure remains.

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Presets, contextual creation, selectors, artifacts and builder | `python -m pytest --reuse-db apps/console/tests/test_phase_2_8_part_4.py apps/console/tests/test_scenario_relationship_console.py apps/artifacts/tests/test_artifacts.py apps/builder/tests/test_api.py apps/builder/tests/test_services.py` in PostgreSQL web container | Pass | 75 passed in 30.85s | All three presets compile; no release is created; audit rollback and release-manager-only selector access pass |
| Broad Part 4 compatibility | Focused PostgreSQL runs across console, builder, artifacts, releases and workflow presets | Pass | 179 passed in 59.57s; final changed-surface rerun above | Includes forged IDs, tenant isolation, exact checksums and publish descriptions |
| Full PostgreSQL/RLS regression | `MCP_ENABLED=true METRICS_BEARER_TOKEN=test-metrics-token python -m pytest --reuse-db` | Pass | 1019 passed, 5 skipped in 206.48s | Five skips are the suite's expected backend-specific guard tests |
| Frontend | `npm --prefix frontend run typecheck`; `npm --prefix frontend test -- --run`; `npm --prefix frontend run build` | Pass | TypeScript clean; 25 tests passed; production build 355.72 kB (113.70 kB gzip) | Existing React `act()` warning remains non-failing; a later redundant rerun was blocked by the managed sandbox's parent-directory `realpath` rule |
| Accessibility/server-rendered console | Full suite including `apps/console/tests/test_console_accessibility.py` | Pass | 5 accessibility tests in the passing full suite | Selector uses native labelled controls and an alert region |
| Formatting and lint | `ruff format --check .`; `ruff check .`; `git diff --check` | Pass | 423 files formatted; all Ruff checks passed; diff check clean | CRLF conversion warnings are informational |
| Type checking | `mypy .` | Pass | 423 source files clean | The historical local document-ingestion smoke was aligned with the unified Scenario model |
| Django/schema/source checks | `python manage.py check`; `python manage.py makemigrations --check --dry-run`; `python -m compileall -q apps config`; `findstatic` | Pass | No Django issues; no migration drift; compile clean; selector and builder static files found | Additive migrations applied successfully to the local PostgreSQL database |
| Runtime health | `docker compose ... ps`; `GET /v1/health/live` | Pass | PostgreSQL/MinIO healthy; Redis, web, beat and workers up; HTTP 200 `{"status":"ok"}` | Runtime was inspected from live Compose state |
| Secret/redaction review | Bounded `rg` scan plus API response assertions | Pass | No key/private-key patterns in changed scope; selector returns no artifact body or foreign descriptions | AI preflight messages omit profile IDs and secrets |

## Required evidence

Preset tests cover canonical compile/no-release behavior and transactional audit rollback. Selector
tests cover tenant and role authorization, bounded metadata, stable logical/exact descriptions,
checksum provenance, closed roles and absence of artifact bodies. Existing and new compiler tests
re-resolve forged IDs and validate immutable pins. Invocation tests create an active compiled
release and derive Chat/Responses examples from its pinned execution-mode analysis and alias.
AI-authoring tests cover disabled preflight, candidate-only generation, explicit acceptance, rate
and audit behavior.

## Checks not run, risks and review

The in-app browser runtime reported no available browser backend, so the authenticated click-through,
responsive visual inspection and copy-button journey were not run. No approved live AI model profile
or provider credential was configured, so no outbound generation smoke was attempted. Both procedures
are recorded in `docs/manual-testing-guide.md`; disabling AI authoring is reversible by unsetting its
profile ID. Application code, PostgreSQL/RLS, migrations, static assets, frontend tests/build and live
health were verified.

Staff review found additive schema only, canonical compiler/publish paths, no moving `latest`
resolution and bounded selector scans. AppSec review confirmed trusted project context, tenant
re-resolution, release-manager authorization, closed role/type choices, body/secret exclusion and
audit rollback. SRE review confirmed bounded queries, additive rollback-compatible fields, safe AI
disable behavior, migration drift absence and healthy web/worker dependencies.

## Final status

**Automated/offline Verified.** Owner acceptance may close after the recorded browser and optional
live-provider journeys; those environment-dependent checks do not block the implemented code path.
