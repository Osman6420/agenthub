# Verification: local Gemini model and embedding provisioning

## Results

- Direct compatibility: chat success; embedding success at 3072 dimensions.
- AgentHub provider seam: chat success; one 3072-dimension embedding vector returned.
- Model profile: `14bea436-f71b-4331-8cf9-dbf0026145d3`.
- Embedding profile: `508c82ae-0de1-4dc3-9a13-64663e132e75`; granted to all three local orgs.
- Local web/runtime worker restarted; `/v1/health/live` returned 200.
- Compose config passed; targeted hermetic tests passed (22); `git diff --check` passed.

The first test inherited intentionally set live-provider env and failed the deterministic-default
assertion; after removing those variables all 22 tests passed. A context-free chat probe was safely
rejected upstream; the real RAG system-plus-user-context shape succeeded.

## Not run

Full suite, formatter, type-check, migration drift, PostgreSQL full suite, reindex/retrieval,
evaluation/release promotion, browser, and production deployment checks.

No credential, raw prompt/context, embedding input, raw response, headers, or secret reference was
recorded in tracked evidence.
