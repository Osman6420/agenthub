> Superseded: [tek aktif geliştirme görevi](../Agent_Hub_MD/plan.md). Bu belge tarihsel kaynaktır; bağımsız uygulanmaz.

# Verification: scenario-detail-ux-simplification

## Planning/instruction evidence — 2026-09-09

This record currently verifies only the planning and coding-agent instruction artifact. Product
implementation has not started and no application acceptance criterion is marked implemented or
verified.

### Inspected sources

- `AGENTS.md`
- `docs/tasks/README.md`
- `docs/tasks/template/plan.md`
- `docs/tasks/template/threat-model.md`
- `docs/ai/engineering-rules.md`
- `docs/ai/definition-of-done.md`
- `docs/manual-testing-guide.md` section 0
- `deploy/compose/docker-compose.yml`
- `docs/user-guide.md`
- `docs/tasks/scenario-publishing-ux-realignment/`
- `docs/planning/archive/ui-redesign-concept-2026-09-08/assessment.md`
- `apps/console/views.py`
- `apps/console/templates/console/scenario_detail.html`
- `apps/console/templates/console/release_detail.html`
- `apps/console/templates/console/base.html`
- `apps/console/static/console/console.js`
- Relevant scenario, release, authorization and navigation tests found by exact text search.

### Live read-only evidence

- Canonical Compose state was queried before browser inspection.
- `postgres`, `redis` and `minio` were running and healthy.
- `web`, `worker-runtime`, `worker-ingestion`, `worker-eval` and `beat` were running.
- `GET http://127.0.0.1:8000/v1/health/live` returned HTTP 200 with `{"status":"ok"}`.
- An authenticated local Document Answer scenario was inspected without submitting any form or
  changing application state.
- At 1280x720, the expanded Advanced block measured approximately 3,616 px and the full document
  approximately 5,539 px.
- At 390x844, the expanded Advanced block measured approximately 5,420 px and the full document
  approximately 8,737 px; no horizontal overflow was observed in that snapshot.
- The release detail page was inspected and confirmed to contain the authoritative exact artifact
  pins already duplicated by scenario detail.
- The current section navigation was confirmed to use same-page anchors; the Advanced anchor does
  not itself open the target disclosure.

### Artifact checks

- The new task directory contains `plan.md`, `threat-model.md`,
  `implementation-instructions.md` and this record.
- Local relative links from the implementation brief to plan/threat model resolve.
- A trailing-whitespace scan of the new Markdown files returned no matches before this record was
  added; rerun it after every edit.
- Existing dirty working-tree files were not modified by this instruction-authoring task.

## Implementation verification checklist

The implementing coding agent must replace this section with exact commands, timestamps, results and
evidence. Do not treat the planning evidence above as product verification.

- [ ] Acceptance criteria mapped to evidence.
- [ ] Focused Python tests.
- [ ] Full applicable Python suite.
- [ ] Ruff format and lint.
- [ ] Mypy.
- [ ] Migration drift check.
- [ ] Frontend type-check, Vitest and build when applicable.
- [ ] Authorization allow/deny and tenant-isolation matrix.
- [ ] Secret/content leakage review.
- [ ] Live Compose/health/preflight on the implemented build.
- [ ] Desktop/mobile/keyboard/screen-reader browser gate.
- [ ] Final architecture, AppSec and SRE diff review.
- [ ] Skipped checks and remaining risks recorded.
