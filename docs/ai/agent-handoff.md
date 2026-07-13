# Coding Agent Handoff

This is the shared operational handoff for Codex, Claude Code, and other coding
agents working in this repository. It supplements task plans and verification
records; it never replaces them as evidence.

## Sources of truth

- Intended/in-progress scope: `docs/tasks/<task-id>/plan.md`.
- Security assumptions and residual threats: task `threat-model.md`.
- Executed checks and remaining risks: task `verification.md`.
- Current implementation: code, migrations, settings, and tests.
- Cross-task project status: `docs/planning/master-plan.md`.

At handoff, inspect these sources plus `git status`, `git diff`, recent commits,
branches, stashes, and reflog. Do not infer the active task only from open IDE tabs.

## Local runtime snapshot

Last checked: 2026-07-12, Europe/Istanbul.

**Live demo is up and manually smoke-tested (2026-07-12).** Current topology:

- Web: `manage.py runserver 127.0.0.1:8000 --noreload` under `config.settings.local`
  (DEBUG serves the builder static bundle) with `MCP_ENABLED=true` and
  `METRICS_BEARER_TOKEN` set so MCP/metrics are exercisable. **Not uvicorn** — runserver is
  used because plain uvicorn/ASGI does not serve `/static/` (no WhiteNoise).
- One Celery runtime worker: `celery -A config.celery worker --pool=solo -Q runtime,default`.
  **The two stale Sprint-8 workers (PIDs 16732/672 from 2026-07-11) and the stale uvicorn
  (PID 2064) were stopped** — they were running pre-Sprint-9 code and silently failed async
  runs (`WORKFLOW_NODE_UNSUPPORTED` on the tool node). Only run ONE runtime worker.
- Demo tenant seeded via `manage.py seed_demo` (org `demo`, operators one-per-role, RAG +
  workflow-with-approval + agent scenarios with promoted releases, a consumer token).
- Verified live end-to-end: RAG `POST /v1/query` → 200 completed; workflow `POST /v1/invoke`
  → 202 → `waiting_approval` → `decide_tool_approval --approve` → auto-resume → completed
  (redacted output); agent `POST /v1/invoke` → 202 → completed (UUID run id); console login +
  builder bundle (`/static/builder/builder.js` 200); MCP 401 (auth-gated); metrics served.
- Manual test recipe (credentials/token are printed by the seeder, not stored):
  [`docs/manual-testing-guide.md`](../manual-testing-guide.md).

Record only genuinely time-varying facts here (is a server up, which ports, is MinIO
running). Durable facts — what is implemented/verified, the canonical interpreter, and
how to run the gates — belong in the `@`-imported verified-state of
[`engineering-rules.md`](engineering-rules.md) so every session loads them
automatically. This snapshot is not auto-loaded, so it must never be the only place
such a fact is written.

- Application: `http://127.0.0.1:8000`.
- Health: `GET /v1/health/live` returned `200 {"status":"ok"}`.
- Web process: `.venv` Python 3.13 `manage.py runserver` (see the live-demo block above),
  not the Compose `web` service. (Earlier sessions used host Python 3.14 + uvicorn.)
- Infrastructure: Docker Compose PostgreSQL/pgvector and Redis are running on the
  published localhost ports. MinIO was not running at the last check.
- Runtime logs: `.runtime/web.stdout.log` and `.runtime/web.stderr.log` (gitignored).
- Uvicorn is started without `--reload`; source changes require a web-process restart.
- The stale-process hazard from earlier sprints is now **resolved** (see the live-demo
  block above): PID 2064 (uvicorn) and PIDs 16732/672 (Sprint-8 workers) were stopped, and
  the current web + single runtime worker run Sprint 11 code.
- All migrations through Sprint 11 (`tools.0001/0002`, `workflows.0002`, `agents.0001`,
  `artifacts.0003`, `builder.0001`) have now been applied to the standing local `agenthub`
  database via `manage.py migrate`. Re-run `manage.py migrate` after pulling future
  increments before serving them against the persistent local DB.
- Sprint 10 added the approved production dependency `langgraph==1.2.9`. A `.venv` created
  before Sprint 10 lacks it (and its transitive tree) and cannot import
  `apps.agents.langgraph_planner`; re-run `pip install -e ".[dev]"` (or install from
  `requirements.lock`) after pulling Sprint 10. The default `AGENT_PLANNER` is the
  deterministic planner, so the core runtime and gates do not require langgraph to be
  importable, but the LangGraph adapter test does.
- PostgreSQL gate gotcha: the Sprint 7 MCP/metrics tests are hard-enabled only under
  `config.settings.test`. When running `--create-db` under `config.settings.local`,
  also export `MCP_ENABLED=true` and `METRICS_BEARER_TOKEN=<any-non-empty>` or 8
  MCP/metrics tests fail spuriously (they 404 the disabled endpoints). Also verified in
  the [`engineering-rules.md`](engineering-rules.md) verified-state.
- Node toolchain (Sprint 11): Node v20.20.0 / npm 10.8.2 available locally. The workflow
  builder frontend lives in `frontend/`; run its gates with
  `npm --prefix frontend ci && npm --prefix frontend run typecheck && npm --prefix frontend test && npm --prefix frontend run build`.
  The build writes the gitignored bundle to `apps/builder/static/builder/`.
- Interpreter: `.venv` (Python 3.13) is canonical and, after Sprint 5, again has all
  dependencies (`boto3`/`pgvector` installed from `requirements.lock`); gates pass in it
  on SQLite and — with the Compose database — on PostgreSQL. `C:\Python314\python.exe`
  (Python 3.14) is a working fallback that was used during Sprint 5 while `.venv` lacked
  those deps. The durable interpreter/dependency contract lives in the verified-state of
  [`engineering-rules.md`](engineering-rules.md), not in this snapshot.

This is an ephemeral snapshot, not a guarantee. Re-check rather than trusting it:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/v1/health/live
netstat -ano | Select-String ':8000'
docker compose -f deploy/compose/docker-compose.yml ps
Get-Content .runtime\web.stderr.log -Tail 50
```

## Starting the local web application

With PostgreSQL and Redis available on localhost:

```powershell
$env:DJANGO_SETTINGS_MODULE='config.settings.local'
$env:DATABASE_URL='postgres://agenthub:agenthub@localhost:5432/agenthub'
$env:REDIS_URL='redis://localhost:6379/0'
$env:OBJECT_STORE_ENDPOINT='http://localhost:9000'
.venv\Scripts\python.exe -m uvicorn config.asgi:application --host 127.0.0.1 --port 8000
```

Never record operator passwords, bearer tokens, cookies, LDAP credentials, or object
store credentials in this document or runtime logs.

## Manual UI smoke checklist

Use `http://127.0.0.1:8000/console/` with an approved local test operator account.
Record results in the affected task's `verification.md`; do not record credentials.

1. Login redirects to the dashboard and logout works via POST.
2. Lists show only organizations/projects/scenarios/consumers in the operator scope.
3. Platform admin can open and submit `/console/organizations/new/`.
4. Project create renders `owner` as a dropdown of organization members; an owner
   outside the selected organization is rejected.
5. Scenario create writes the scenario and optional alias atomically.
6. Consumer and binding create reject cross-organization selections.
7. Confirm the expected audit event after each successful create.

Current UI evidence:

- Automated SQLite full suite: 85 passed, with 2 PostgreSQL-only tests skipped.
- Automated PostgreSQL console suite: 11 passed.
- The organization-form constructor regression and scoped project-owner selection are
  fixed and the web process was restarted afterward.
- Manual browser re-check of those two corrected forms is pending user confirmation;
  do not mark it manually verified until that confirmation is recorded.

Current cross-agent state:

- Claude completed and committed Sprint 6 as `b66843e`.
- Codex implemented Sprint 7 without modifying Sprint 6 implementation files. Automated
  evidence, including parity against the committed Sprint 6 canary routing contract, is
  in the Sprint 7 verification record.
- Codex implemented and automatically verified Sprint 8 on SQLite and PostgreSQL; see
  its verification record. The web is current, but the user-started worker requires a
  restart after the stale-message fix; manual async workflow smoke remains.
- Claude committed Sprint 8 (`b38af35`) after independently re-verifying it, then
  implemented and verified Sprint 9 (tool registry + governed egress + approval
  lifecycle + workflow tool node) across six commits `bb4d675`, `84ffb76`, `47e7321`,
  `39e67d8`, `e2bc174`, and `c68415d`. Automated evidence only (SQLite 275 passed
  / 2 skipped; PostgreSQL 277 passed); no live-egress or live-server smoke was run —
  `TOOL_ADAPTER` defaults to the no-egress deterministic adapter.
- Claude then implemented and verified Sprint 10 (agent runtime — `apps.agents`):
  the `agent_definition` artifact + compiler, durable `AgentRun` (opaque `public_id`
  UUID) with a guarded decision loop on the Sprint 8/9 Celery/tool-proxy/approval
  contracts, LangGraph integrated only as an `AgentPlanner` adapter behind
  `AGENT_PLANNER` (default deterministic → no graph code in CI), gateway `202` agent
  invoke + workflow/agent dual-dispatch `/v1/runs/{id}`, trajectory eval assertions, and
  role-gated console/command operator surfaces. Automated evidence only (SQLite 337
  passed / 2 skipped; PostgreSQL affected-app run 142 passed); no live-egress or
  live-server smoke was run (default deterministic model provider + no-egress tool
  adapter). One approved production dependency added: `langgraph==1.2.9` (exact pin,
  `requirements.lock` regenerated, `pip check` clean, CI fails closed on lock drift).
  Additive migrations `agents.0001`, `artifacts.0003`. Not delivered (operational
  follow-ups): a global start/resume kill switch, the checkpoint retention/purge job, and
  load/soak tests. Sprint 10 was committed as `9da4282`.
- Claude then implemented and verified Sprint 11 (visual workflow builder): `apps.builder`
  (mutable tenant-scoped `WorkflowDraft` + operator JSON API under `/console/api/builder/`
  for draft CRUD + diagnostics + node-schema + publish, reusing console LDAP/session +
  role/tenant authz, CSRF, audited; additive migration `builder.0001`) and a **React Flow
  SPA** in `frontend/` served same-origin as Django static assets. Committed:
  `36626f3` (backend), `456bd17` (frontend SPA), `cb6874c` (user-guide + security-overview
  docs), and `ddb442c` (the `seed_demo` command + manual-testing guide). Automated evidence
  (SQLite 364 passed / 2 skipped; PostgreSQL `apps/builder`+`apps/console` 46 passed;
  frontend 11 vitest tests + `vite build`) **plus a live end-to-end smoke on 2026-07-12**
  (RAG query, workflow approval pause/resume, agent run, builder bundle, MCP, metrics — see
  the live-demo snapshot above). **New: a Node/npm build toolchain**
  — five approved production frontend deps (Node/npm, Vite, React, React DOM,
  `@xyflow/react`), pinned in `frontend/package-lock.json`, with a Node CI job. The built
  bundle (`apps/builder/static/builder/`) is **gitignored**: run
  `npm --prefix frontend ci && npm --prefix frontend run build` before serving the
  `/console/builder/` page or running `collectstatic`. The Python runtime/gates do not
  depend on the bundle existing. The `builder.0001` migration was exercised via
  `pytest --create-db` but not necessarily applied to the standing local `agenthub` DB — run
  `manage.py migrate` before serving Sprint 11 against the persistent local DB.

- Sprint 11 documentation was consolidated (2026-07-12): the duplicate
  `docs/tasks/sprint-11-builder-expansion/` plan was archived to
  `docs/planning/archive/sprint-11-builder-expansion/` (approved-decision provenance), and
  `docs/tasks/sprint-11-workflow-builder/` is now the single canonical Sprint 11 record with
  a delivered-vs-deferred reconciliation. Deferred builder enhancements moved to the new
  **Phase 2 plan** `docs/planning/phase-2-plan.md` (governed document plane →
  Turkish UI → AI-assisted authoring → personal end-user MCP, in that owner-set priority).
  Phase 2 implementation kickoff is approved; new dependencies/live egress still need their
  milestone-specific explicit sign-off.

- **Phase 2 · Workstream 1 (document plane) — authoritative design landed (2026-07-12), NOT
  approved for implementation.** The owner gave detailed decisions A–E and asked for a component
  plan + threat model before any code. Written and cross-referenced:
  [`docs/planning/components/document-plane-plan.md`](../planning/components/document-plane-plan.md)
  and `document-plane-threat-model.md`. Design in brief: (A) **hybrid isolation** — tenant is the
  physical boundary (app predicate **+ PostgreSQL FORCE RLS**, fail-closed, transaction-local
  `set_config('app.tenant_id',…,true)`), `DocumentSet` version is the logical ACL/retrieval unit,
  each `IndexVersion` is a physically isolated immutable store; no per-scenario physical index;
  `IndexVersion` re-scoped to (org, doc-set-version, embedding-profile). (B) enforce
  consumer+scenario-binding now, forward-ready `principal_type=consumer|service|user|group`
  (user/group in WS4). (C) new content lineage `Source→Document→DocumentVersion→Blob` +
  `DocumentSet/Version/Membership` + soft-delete tombstone vs auditable purge; **rename existing
  index-scoped `apps.ingestion.Document`→`IndexedDocument`** (`RenameModel`, preserve rows/PKs/
  FKs). (D) platform-managed immutable **`EmbeddingProfile`** catalog; embedding egress =
  `OpenAICompatibleEmbeddingClient` over the **Sprint 9 SSRF-safe stdlib transport, NO `openai`
  dependency**, platform-allowlisted endpoint only (no tenant/request `base_url`); **blue/green
  per-`IndexVersion` stores, promotion = single-transaction pointer-flip of the active
  `index_version_id`** (no rename/copy/rebuild), retention/purge only when unreferenced;
  dimension validated up front (`vector`≤2000 / `halfvec`≤4000, no silent truncation). (E) parser
  behind a `DocumentParser` interface, comparison-table before any dependency (format-specific
  pypdf/pdfplumber+python-docx+openpyxl preferred), **OCR NOT in-app** — image PDFs + embedded
  images go to the owner's external OCR endpoint over SSRF-safe egress. **M0 design spikes are now
  DONE, documented as ADRs (2026-07-12):** Spike 1 pgvector multi-dimension storage →
  [ADR-0003], Spike 2 RLS connection-context → [ADR-0004], Spike 3 shared SSRF-safe egress adapter →
  [ADR-0005] (implements [ADR-0002]). Phase 2 kickoff is approved and P1 is complete; continue with
  P2 while preserving per-phase egress/dependency gates. No document-plane code/migration/
  dependency/egress yet.

- **WS5 (live model runtime) P1 verified (2026-07-12).** Owner: "give the app a
  base_url + token and actually reach the LLM — that must exist." Verified today's runtime ships
  an opt-in real `ModelProvider` now exists behind the deterministic default; agent `retrieve` and
  workflow `generate`/`retrieve` remain placeholders; agents carry no system prompt; multi-prompt workflows drawable but
  not runnable). **WS5 is a foundational track interleaved with WS1, not a 5th-in-line priority.**
  Owner delivery order: M0 spikes → shared egress/provider infra → chat provider → embedding/
  indexing → document-ACL retrieval → UI. The interleaved phase plan (P0–P8, with a **serving
  guardrail**: real tenant corpora are not served to consumers until deny-by-default binding + RLS
  are in place) is `docs/planning/components/runtime-and-document-plane-sequence.md`. **Egress
  architecture is now [ADR-0002]** (`docs/adr/0002-...`): chat + embedding via a **platform-managed
  immutable revisioned profile catalog referenced by ID only** — no tenant/artifact/prompt/request
  `base_url`/host/scheme/credential/TLS choice (supersedes inline endpoint/api_key in the
  `model_profile` artifact); a **stdlib OpenAI-compatible adapter, no `openai` dependency** (deferred
  not banned); **no blind retry** (a post-send model/embedding failure is an unknown outcome, not a
  retry); and a **technical prompt-injection boundary** (system instructions server-side + separate
  from doc/user text, tool calls never authorized by model output, citation/policy applied after the
  model). WS1 status is **"architecture scoped; M0 decisions documented; implementation not
  approved"** — the physical index schema, RLS connection-context, and shared egress contract are
  fixed by ADR-0003/0004/0005; changing them requires a superseding ADR.

- **Planning-doc consistency pass (2026-07-12):** a review found `phase-2-plan.md` and
  `master-plan.md` still carried pre-decision statements (stale `openai`-may-be-used note,
  "open questions" already resolved in the component plan, "split into component plans" next-step,
  and a current-state header that only counted Sprints 0–1). Fixed: the phase-2 summary now defers
  to the authoritative component plan, marks WS1 architecture-scoped/implementation-gated-by-M0 with
  a per-workstream status table, and `master-plan.md` reads "Sprints 0–11 implemented and
  verified" with a Document-plane row in the Components table. **These planning/handoff doc edits
  are documentation-only (no code) and are committed on `feat/foundation-sprint-0-1`; nothing was
  pushed.** No runtime/topology change since the Sprint 11 live-demo snapshot above.

- **Authoring-capability ground truth (verified by code inspection 2026-07-12, for the next
  session):** a scenario = catalog `Scenario` + immutable **artifacts** referenced by role,
  compiled into a `ScenarioRelease` and promoted (fail-closed via eval). Authoring is **GitOps/
  CLI**, not the UI: write artifact YAML (`api_version: agenthub/v1`) and `manage.py import_gitops`
  / `compile_release` / `promote_release` (see the real example under `gitops/mcm/`). Release-bundle
  roles the runtime resolves: `prompt` (`spec.template` → `bundle.prompt_text`), `model_profile`
  (provider/endpoint/model/`secret:<name>`), `policy`, `retrieval_profile`, `input_contract`,
  `output_contract`, plus manifest-pinned `index_versions`; agents/workflows/tools have their own
  artifacts. **The system prompt is the `prompt` artifact + `model_profile` — there is no console
  field for it (the Sprint 11 builder was deliberately trimmed to exclude system-prompt entry /
  model selection).** Important honest caveats for anyone asked "can we serve MCP+RAG+agent-loop
  today": the plumbing exists and is served end-to-end, but by default (i) `RUNTIME_MODEL_PROVIDER`
  is a deterministic stub (no real LLM), (ii) the **agent loop's retrieve step and the workflow
  `generate`/`retrieve` nodes are deterministic stubs** — real pgvector RAG is wired only in the
  standalone `run_rag` (`/v1/query`) path, not inside the agent/workflow, (iii) real tool egress
  incl. the `McpToolAdapter` is opt-in behind `TOOL_ADAPTER` (default no-egress), and (iv) an
  `agent_definition` carries **no prompt text** (the loop uses the user objective as the prompt).
  So "several different LLM prompts per step against a real model" is expressible in the workflow
  DAG (multiple `generate` nodes) but **not yet functional** — wiring generate/retrieve/model
  providers and per-node prompt/model binding is future work that Phase 2 (real providers +
  AI-assisted authoring + artifacts-visible-in-UI) is meant to unlock.

- **P8.1 COMPLETE — document-plane console UI (P8.2–P8.4 planned, no gate).** P8.1 is implemented and
  verified in `docs/tasks/phase-2-p8-console-ui/`: a server-rendered `/console/documents/` page —
  tenant-scoped list of documents + document sets (`scoping.scoped_documents`/`scoped_document_sets`),
  an author-gated multipart **upload** (`DocumentUploadForm` scoped to `author_organization_ids`; the
  view re-checks `can_author_scenarios` server-side and calls `upload_document`), and a cross-tenant-
  safe **soft-delete** (scoped queryset → 404 for another tenant's doc). Nav link added; all writes
  audited by `apps.documents.services`. **Non-authoritative, no dependency/egress/migration.** Test
  gotcha (fixed): the autouse fixture must force `settings.DOCUMENTS_OBJECT_STORE_BACKEND="memory"`
  (config.settings.local defaults to "s3" → uploads need MinIO otherwise). Evidence: SQLite 497
  passed / 20 skipped; PostgreSQL 515 passed / 2 skipped. **P8.2 (sets: create/version/membership/
  publish), P8.3 (scenario binding + ACL grants), P8.4 (elevated purge)** are planned console UI over
  the existing P2/P4 services — **no approval gate**. Committed on `feat/foundation-sprint-0-1`; not
  pushed. P7 provenance follows.
- **P7.1 + P7.2 COMPLETE — P7.3/P7.4 deferred by owner.** P7 (parsers) is implemented and
  verified in `docs/tasks/phase-2-p7-parsers-ocr-connectors/`.
  - **P7.1 (stdlib parsers):** new `apps/ingestion/parsers.py` — a deny-by-default, MIME-keyed
    `DocumentParser` registry (`ParsedContent`/`ParserError`/`get_parser`/`parse_document`) with
    **stdlib-only, deterministic** parsers (text/plain, text/markdown, text/csv, application/json,
    text/html), wired into `staged_build._embed_into_store` (replacing the hardcoded UTF-8-only path).
    Governance: bounded output (`MAX_PARSED_CHARS`/`MAX_ELEMENTS`), counts-only telemetry, content-free
    stable-code errors, HTML drops `<script>`/`<style>` and fetches nothing. `text/html` added to the
    `DOCUMENTS_ALLOWED_MIME_TYPES` upload default. Commit `485748b`.
  - **P7.2 (local binary parsers):** `PdfParser`/`DocxParser`/`XlsxParser` on the same interface,
    registering pdf/docx/xlsx MIME types. The owner **approved the dependencies (2026-07-13)** —
    **pdfplumber + python-docx + openpyxl** (baseline + pdfplumber for PDF tables; pypdf omitted as
    redundant). Pins in `pyproject.toml`; `requirements.lock` regenerated (`pip check` clean; langgraph
    trio unchanged). Heavy imports are **deferred** so importing `parsers.py` needs only the stdlib;
    parsing is **local/in-process — no network egress**. An image-only PDF fails closed
    (`EMPTY_DOCUMENT`; its OCR is P7.3). **No migration.** A `.venv` created before P7.2 must re-run
    `pip install -e ".[dev]"` to run the pdf/docx/xlsx tests.
  - **Evidence (P7 cumulative):** SQLite 492 passed / 20 skipped; PostgreSQL `--create-db` 510 passed /
    2 skipped; `pip check` clean. Both P7.1 and P7.2 committed on `feat/foundation-sprint-0-1`; **not
    pushed.**
  - **Next: P7.3** (external OCR egress for image-only pages) and **P7.4** (Confluence + generic-REST
    connectors) — **both deferred by the owner (2026-07-13)**, blocked on their environment-specific
    OCR/connector endpoint + secret egress sign-off. No code/endpoint/egress for these yet.
  P6 provenance follows.
- **P6 COMPLETE.** P6 (authored, governed agent **system prompt**) is implemented
  and verified in `docs/tasks/phase-2-p6-agent-system-prompt/`: `agent_definition` accepts an optional
  bounded (≤8000 chars, no control chars), redaction-safe `spec.system_prompt` (data, not code); the
  agent compiler pins it into the checksummed config; `agents/runtime._respond` uses it as the model
  prompt (objective fallback). It is input, never authorization — the tool proxy/approval/retrieval/
  output-contract gates are unchanged. **No migration** (compiled-config + validation change only), no
  new dependency, no live egress; deterministic default keeps CI hermetic. Evidence: SQLite 474 passed
  / 18 skipped; PostgreSQL `--create-db` 490 passed / 2 skipped. Next: **P7** — `DocumentParser`
  interface + selected parsers (pdf/docx/xlsx→markdown), external OCR egress for image-only pages, and
  upload/Confluence/generic-REST connectors. **P7 gates:** document-parser dependency approval (post
  comparison table — format-specific pypdf/pdfplumber + python-docx + openpyxl is the preferred
  baseline; OCR is NOT in-app) + OCR endpoint + connector-endpoint egress sign-off. P5 provenance follows.
- **P5 COMPLETE.** P5 (real retrieve/generate wired into the agent loop + workflow
  nodes) is implemented and verified in `docs/tasks/phase-2-p5-agent-workflow-rag/`: a shared
  `apps/orchestration/rag_steps.py` (`retrieve_for_release` → P4 ACL retrieval; `generate_for_release`
  → P1 chat, over the release bundle) now backs the workflow `retrieve`/`generate` nodes and the
  agent retrieve step + `_respond` (previously stubs). The workflow `generate` node gained optional
  per-node `prompt_ref`/`model_profile_ref` binding (compiler-validated) → multi-prompt/multi-model
  workflows. **Behavioral wiring only — no migration, no new dependency, deterministic default keeps
  CI hermetic.** Evidence: SQLite 464 passed / 18 skipped; PostgreSQL `--create-db` 480 passed / 2
  skipped. The agent still uses the user objective as its prompt — an **authored agent system-prompt
  artifact is P6** (extend `agent_definition` to reference a governed, validated, release-pinned
  system-prompt/instruction artifact; tool/decision re-validation unchanged). P4 provenance follows.
- **P4 COMPLETE.** P4 (document-ACL retrieval + RLS + pointer-flip promotion — the
  security core) is implemented and verified in `docs/tasks/phase-2-p4-acl-rls/` across four
  increments: P4.1 binding + ACL grant foundation (`80d140f`); P4.2 the release compiler pins
  `document_set_versions` deny-by-default from `ScenarioDocumentSetBinding`s, the resolver/runtime
  carry them, and `PgvectorRetrievalProvider._retrieve_acl` serves `/v1/query` only from the pinned
  versions' **active** per-`IndexVersion` stores (tenant + not-tombstoned, no client filter); P4.3
  each store is provisioned with `FORCE ROW LEVEL SECURITY` + a transaction-local `app.tenant_id`
  policy (ADR-0004, `apps/ingestion/vector_store.set_tenant_context`), proven fail-closed under a
  NOSUPERUSER role; P4.4 `promote_staged_index`/`rollback_staged_index` do the metadata-only
  pointer-flip (+ `promote_staged_index [--rollback]` command). Additive migrations `documents.0002`,
  `ingestion.0005` (`IndexStatus.superseded`). Evidence: SQLite 454 passed / 18 skipped (pgvector);
  PostgreSQL `--create-db` 470 passed / 2 skipped (off-PG guards). **The serving guardrail is now
  satisfiable** — a bound + promoted scenario serves real ACL-scoped RAG. **Remaining P4 hardening
  (follow-up):** `FORCE` RLS on the Django-managed tenant tables + a dedicated non-owner app role
  (CI/local run as the superuser owner which bypasses RLS; the mechanism is proven on the served
  stores under `SET ROLE`). Next: **P5** — replace the agent `retrieve` stub and the workflow
  `retrieve`/`generate` stubs with the governed real providers, and add per-node prompt/model binding
  to the workflow `generate` node (multi-prompt/multi-model workflows).
- **PHASE 2 provenance — P1 + P2 + P3 COMPLETE (P4 complete, see above).** **P3 (real embeddings + staged
  blue/green indexing) is implemented and verified** in `docs/tasks/phase-2-p3-embeddings/`, in two
  increments: P3.1 — a platform `EmbeddingProfile` catalog + per-tenant grants + opt-in
  `OpenAICompatibleEmbeddingClient` over the shared SSRF-safe transport (profile-id-only,
  deterministic default, no `openai` dep, no live endpoint); P3.2 — the ADR-0003 per-`IndexVersion`
  blue/green vector-store DAL (`apps/ingestion/vector_store.py`, system-generated `chunk_iv_<pk>`
  names, `vector(D)`/`halfvec(D)`, **PostgreSQL-only**) + a re-scoped `IndexVersion` (migration
  `ingestion.0003` catalog, `0004` re-scope) + `build_staged_index` over managed documents that
  leaves a **`promotable` (never served)** index. New settings knob `RUNTIME_EMBEDDING_PROVIDER`
  (default deterministic). New management commands: `register_embedding_profile`,
  `grant_embedding_profile`, `build_staged_index`. Evidence: SQLite 440 passed / 10 skipped
  (pgvector); PostgreSQL `--create-db` 448 passed / 2 skipped (off-PG guards). **The served
  `/v1/query` retriever and the legacy `Chunk` table are untouched** — pointer-flip promotion,
  document-ACL retrieval, RLS, and the legacy-chunk data-migration cutover are **P4** (they cross the
  serving guardrail). Continue at **P4** honoring the guardrail. Older P1/P2 provenance follows.
- **P1 + P2 provenance.** P1 is implemented and verified in
  `docs/tasks/phase-2-p1-live-chat/` (platform `ModelProfile` catalog, profile-ID-only shared
  SSRF-safe egress, opt-in real chat provider; deterministic default; no live endpoint opened).
  **P2 (content plane & storage) is implemented and verified** in
  `docs/tasks/phase-2-p2-content-plane/`: new `apps/documents`
  (`Document→DocumentVersion` + `DocumentSet/Version/Membership`), an object-store abstraction
  (real S3 + hermetic in-memory backend), upload/soft-delete/auditable-purge services, a
  role/tenant-scoped operator JSON API under `/console/api/documents/`, and the data-preserving
  `ingestion.Document → IndexedDocument` `RenameModel`. Migrations `ingestion.0002` (rename) and
  `documents.0001` (additive) apply on SQLite and PostgreSQL. Evidence: SQLite 410 passed / 2
  skipped; PostgreSQL `--create-db` 412 passed. No new dependency, no live egress, no retrieval
  behavior change; scenario binding + retrieval ACL + RLS remain P4, real embeddings remain P3.
  **Run `manage.py migrate` before serving P2 against the standing local `agenthub` DB** (the two
  new migrations were exercised via `pytest --create-db` but not necessarily applied to the
  persistent DB), and export `DOCUMENTS_OBJECT_STORE_BACKEND`/an object store if exercising
  uploads locally (MinIO was not running at last check). The next planned increment is **P3 real
  embeddings + indexing (staged)** — a new external egress (embedding endpoint) approval gate. The
  original P1 kickoff checklist is retained below as completed provenance.
- **STARTING PHASE 2 — completed P1 kickoff provenance.**
  - **Entry point:** M0 (design spikes) is **done** — [ADR-0003] vector storage, [ADR-0004] RLS,
    [ADR-0005] shared egress (implements [ADR-0002]). Begin at **P1 — shared SSRF-safe egress
    adapter + real chat `ModelProvider`** and follow the phase order in
    [`../planning/components/runtime-and-document-plane-sequence.md`](../planning/components/runtime-and-document-plane-sequence.md)
    (P1 chat → P2 content plane → P3 embeddings/indexing staged → P4 ACL+RLS serve → P5 wire
    agent/workflow → P6 agent prompt → P7 parsers/OCR/connectors → P8 console UI). Do **not** jump
    ahead; honor the **serving guardrail** (no real tenant corpus served to consumers until P4).
  - **What "start Phase 2" does and does not authorize:** it authorizes beginning *implementation*;
    it does **not** waive the remaining gates. Before opening any **live egress** (chat P1,
    embedding P3, OCR + Confluence/REST P7) get the owner's **environment-specific endpoint/profile
    + secret** sign-off; before adding the **document-parser dependency** (P7) get supply-chain
    approval. **No `openai` dependency** — stdlib adapter only (ADR-0002/0005). The planning docs
    still read "not approved for implementation"; treat the owner's kickoff as the approval to begin
    at P1 and update those status lines in the same change that lands P1.
  - **Non-negotiable design constraints (change only via a new ADR):** egress is **profile-ID-only**
    — an artifact carries only a `ModelProfile`/`EmbeddingProfile` id; `base_url`/host/scheme/secret/
    TLS are **not** in the artifact (ADR-0002). **Migrate the existing `gitops/mcm/artifacts/
    model_profile_default_chat.yaml`** (which still inlines `endpoint`/`api_key`) to a profile-ID
    reference as part of P1. Reuse `apps/tools/egress`; **no blind retry** (post-send failure =
    `outcome_unknown`; HTTP 429/503 retries require a documented idempotency guarantee); keep the
    **deterministic providers as the default** so CI/gates run no live
    egress. `run_rag` (`/v1/query`) already calls the model seam, so P1 lights it up once the
    provider + catalog exist. Blue/green per-`IndexVersion` stores + pointer-flip promotion
    (ADR-0003); `FORCE` RLS + transaction-local tenant context (ADR-0004).
  - **First actions:** create `docs/tasks/phase-2-p1-live-chat/plan.md` + `threat-model.md` +
    `verification.md`; re-establish a green gate baseline (`ruff format --check`, `ruff check`,
    `mypy`, `makemigrations --check`, `manage.py check`, `pytest` on SQLite, and PostgreSQL with
    `MCP_ENABLED=true` + `METRICS_BEARER_TOKEN`) **before** changing code; verify `.venv` deps.
    Additive migrations only; never weaken an existing control. Ignore the untracked `.serena/` and
    `docs/tasks/serena-agent-setup/` — unrelated tooling, not Phase 2 work.

## Agent transition checklist

Before yielding work to another agent:

1. Update the active task plan status and assumptions.
2. Update threat-model mitigations/residual risks when boundaries changed.
3. Record exact commands/results and manual UI evidence in `verification.md`.
4. State whether localhost services are running and whether a restart is required.
5. Report uncommitted and intentionally excluded files (for example local agent
   settings); never overwrite them without authorization.
6. Distinguish implementation complete, automated verification complete, and manual
   UI verification complete.
7. If work is committed, record the commit id; otherwise explicitly say uncommitted.

At the next agent's start, verify this snapshot against live state before acting and
update it when the local runtime topology or common handoff procedure changes.
