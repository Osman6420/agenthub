# Verification: workflow authoring guide unification

- Detailed `artifacts-and-dsl-authoring-guide.md` retained and linked to the concise guide.
- Concise `workflow-dsl-llm-guide.md`: 2,833 UTF-8 bytes.
- Backend workflow system prompt and both console copy surfaces use the exact same text.
- Prompt tests preserve trusted-system/untrusted-user separation and contract checksum behavior.
- Targeted backend/builder/console run: 165 passed, one stale literal assertion identified.
- Updated focused run: 12 passed; Ruff passed; `git diff --check` passed.
- Live Gemini workflow candidate: success and canonical diagnostics valid.
- Current web/runtime worker restarted; readiness HTTP 200.

Full suite, mypy, migration drift, PostgreSQL full suite, browser automation, and production deploy
checks were not run. No prompt response or credential was recorded.
