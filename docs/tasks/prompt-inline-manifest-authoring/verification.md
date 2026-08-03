# Verification: prompt-inline-manifest-authoring

## Automated evidence

- `npm test -- src/__tests__/scenario_manifest.test.tsx`
  - 5 tests passed.
- `npm test -- src/__tests__/scenario_manifest.test.tsx src/__tests__/ai_authoring.test.tsx src/__tests__/app_deeplink.test.tsx`
  - 14 tests passed across 3 files.
- `npm run typecheck`
  - Passed (`tsc --noEmit`).
- `npm run build`
  - Passed; Vite transformed 183 modules and emitted the builder bundle.
- `git diff --check`
  - Passed.

## Live evidence

- `GET http://127.0.0.1:8000/v1/health/live` returned HTTP 200 with `{"status": "ok"}`.
- Authenticated Scenario Studio loaded the cache-keyed bundle at the target external-demo scenario.
- Selecting `prompt_template` → `wikipedia-brief.prompt` → exact `v1` automatically displayed its
  body in the editable `Seçili prompt metni` textarea.
- The manifest role selector and separate open/edit/close controls were absent.
- A temporary client-only text change revealed the change-description field and `Yeni sürümü yayımla
  ve ekle`; restoring the original text returned to the unchanged exact-version action.
- No live artifact version was published and no manifest candidate was created during acceptance.

## Environment limitation

Docker Compose state could not be queried because this desktop session lacked access to the Windows
Docker named pipe. Live web health and browser behavior were verified; full Compose role health was
not established by this task.

## Review evidence

- Staff-engineer review: one task-oriented action replaces redundant controls; same-role selections
  are deterministic replacements and custom workflow-required roles are preserved.
- Application-security review: preview remains bounded and server-authorized; prompt text is rendered
  as textarea content; capability flags only alter affordances; each mutation stays server-authorized.
- SRE review: no migration or runtime contract change; network failures preserve client text and may
  leave an unpublished reusable draft, as documented in the rollback/residual-risk plan.
