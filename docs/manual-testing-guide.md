# AgentHub — Manual Testing Guide

A hands-on checklist for exercising **every** feature of a running local AgentHub. It
assumes the demo tenant seeded by `manage.py seed_demo`. Pair it with the
[user guide](user-guide.md) (how the product works) and the
[security overview](security-overview.md) (why it is safe).

> Credentials and tokens are **generated and printed by `seed_demo`** — they are not stored
> in this document. Run the seeder and copy the values it prints into the `<PASSWORD>` /
> `<REST_TOKEN>` / `<MCP_TOKEN>` placeholders below.

---

## 0. Bring up the stack

The supported local topology is defined in
[`deploy/compose/docker-compose.yml`](../deploy/compose/docker-compose.yml). Do not
infer service state from an old handoff or PID: query Docker Compose and the health
endpoint each time.

For the normal full-stack path, use the repository-owned lifecycle command. It builds the frontend
and current application image, applies migrations, starts every role, waits for liveness, and prints
Compose state. It preserves local data by default:

```powershell
.\scripts\local-stack.ps1                 # update/recreate, preserve data
.\scripts\local-stack.ps1 -Action Fresh   # confirmed reset, delete local volumes
.\scripts\local-stack.ps1 -Action Status
```

> **Critical data-loss warning:** `Fresh` deletes all local PostgreSQL and MinIO data after typed
> confirmation. `Fresh -Force` is substantially more dangerous because it bypasses that confirmation
> and performs the irreversible deletion immediately. Do not use `-Force` for normal startup or
> troubleshooting. It is only for a positively identified disposable environment where losing every
> local tenant, document, run, release, audit record, and stored object is explicitly intended.

The complete behavior, destructive reset warning, logs, stop, and troubleshooting commands are in
the [local development stack runbook](operations/local-development-stack.md). The raw commands below
remain useful for inspection and specialist host-mode debugging.

Choose one mode and avoid starting duplicate web or worker processes:

```powershell
# Inspect current infrastructure/application state and health.
docker compose -f deploy/compose/docker-compose.yml ps
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/v1/health/live

# Mode A: run the complete stack in Docker (supported wrapper).
.\scripts\local-stack.ps1

# Mode B: run only infrastructure in Docker; use the host commands below for web/worker.
docker compose -f deploy/compose/docker-compose.yml up -d postgres redis minio
docker compose -f deploy/compose/docker-compose.yml ps postgres redis minio
```

In the health request, connection failure means the web application is not running;
it does not prove PostgreSQL or Redis are down. Compose reports their configured
healthchecks separately. For startup failures, inspect bounded recent logs with
`docker compose -f deploy/compose/docker-compose.yml logs --tail 100 <service>`.

Host-mode prerequisites: healthy Docker Compose PostgreSQL/pgvector + Redis, the
`.venv`, and the built builder bundle.

```powershell
# One-time / after frontend changes: build the workflow-builder SPA
npm --prefix frontend ci
npm --prefix frontend run build

$env:DJANGO_SETTINGS_MODULE = 'config.settings.local'
$env:DATABASE_URL = 'postgres://agenthub:agenthub@localhost:5432/agenthub'
$env:REDIS_URL    = 'redis://localhost:6379/0'
$env:OBJECT_STORE_ENDPOINT = 'http://localhost:9000'
$env:OBJECT_STORE_BUCKET = 'agenthub'
$env:AWS_ACCESS_KEY_ID = '<LOCAL_MINIO_ACCESS_KEY>'
$env:AWS_SECRET_ACCESS_KEY = '<LOCAL_MINIO_SECRET_KEY>'
$env:AGENTHUB_SERVICE_REVISION = 'development'

# Apply migrations, then seed the demo tenant (prints operator password + API token)
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_demo --password '<PASSWORD>'

# Web (serves the builder static bundle + enables MCP/metrics for testing)
$env:MCP_ENABLED = 'true'; $env:METRICS_BEARER_TOKEN = '<METRICS_TOKEN>'
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload

# In a second terminal: the async runtime worker (Windows -> --pool=solo)
.venv\Scripts\python.exe -m celery -A config.celery worker --pool=solo -Q runtime,default -l info

# In separate terminals: ingestion worker and periodic durable reconciler.
.venv\Scripts\python.exe manage.py check_ingestion_preflight
.venv\Scripts\python.exe -m celery -A config.celery worker --pool=solo -Q ingestion -l info
.venv\Scripts\python.exe -m celery -A config.celery beat -l info

# After the worker has consumed a heartbeat/reconciler task:
.venv\Scripts\python.exe manage.py check_ingestion_preflight --require-worker
```

> **Only run one runtime worker.** A stale worker from an earlier session running older code
> will silently grab async runs and fail them (e.g. `WORKFLOW_NODE_UNSUPPORTED`). Kill any
> extra `celery ... worker -Q runtime` processes first.

The same warning applies to `-Q ingestion`: broker reachability alone is not readiness. The
preflight prints only contract revision, a shortened non-secret configuration fingerprint and a
coarse compatible-worker result. It never prints object-store credentials or endpoints.

### 0.1 Windows Python/test troubleshooting

Use the repository `.venv` first. If `.venv\Scripts\python.exe` fails before Python starts with
`A specified logon session does not exist`, inspect `.venv\pyvenv.cfg`. A Microsoft Store Python
base executable can become unavailable to a non-interactive agent session even while the venv
packages remain intact. This is an environment-launcher failure, not test evidence.

Do not run that Python 3.13 venv with an unrelated Python 3.12 executable by adding
`.venv\Lib\site-packages` to `PYTHONPATH`. Pure-Python imports may appear to work, but compiled
packages such as NumPy, pydantic-core and pgvector will fail because their `cp313` extensions do not
match Python 3.12.

When the host launcher cannot be restored during the task, an isolated Python 3.13 container may be
used as a verification fallback. It mounts the current workspace, installs from the unchanged
`pyproject.toml`, uses no production data/secrets, and is removed after the command:

```powershell
# SQLite test profile. Do not add pytest -q or a pytest timeout.
docker run --rm `
  -v "${PWD}:/app" -w /app `
  -e DJANGO_SETTINGS_MODULE=config.settings.test `
  -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 `
  python:3.13-slim sh -lc `
  "pip install --disable-pip-version-check . pytest pytest-django >/tmp/install.log && python -m pytest -p pytest_django.plugin"

# PostgreSQL/pgvector/RLS profile; first confirm Compose postgres/redis are healthy.
docker run --rm --network agenthub_default `
  -v "${PWD}:/app" -w /app `
  -e DJANGO_SETTINGS_MODULE=config.settings.local `
  -e DATABASE_URL=postgres://agenthub:agenthub@postgres:5432/agenthub `
  -e REDIS_URL=redis://redis:6379/0 `
  -e MCP_ENABLED=true -e METRICS_ENABLED=true `
  -e METRICS_BEARER_TOKEN=test-metrics-token `
  -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 `
  python:3.13-slim sh -lc `
  "pip install --disable-pip-version-check . pytest pytest-django >/tmp/install.log && python -m pytest -p pytest_django.plugin"
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` prevents unrelated globally installed pytest plugins (for
example LangSmith) from importing optional compiled dependencies. Load `pytest_django.plugin`
explicitly so Django setup still occurs. This fallback may require network access to resolve the
declared dependencies; record that fact in verification evidence.

The canonical Compose image copies the declared local Python packages before `pip install .`. If an
older cached build reports `package directory 'config' does not exist`, rebuild the application image
from the current Dockerfile before diagnosing application code.

For type and Django checks in the fallback container, install development-only tooling only inside
that disposable container; do not modify repository dependencies:

```powershell
docker run --rm -v "${PWD}:/app" -w /app `
  -e DJANGO_SETTINGS_MODULE=config.settings.test `
  python:3.13-slim sh -lc `
  "pip install --disable-pip-version-check . mypy django-stubs >/tmp/install.log && python -m mypy apps && python manage.py check && python manage.py makemigrations --check --dry-run && python -m compileall apps config"
```

The seeder provisions:

| Thing | Value |
| --- | --- |
| Organization / project | `demo` / `support` |
| Operators (password `<PASSWORD>`) | `admin` (platform admin), `editor`, `releaser`, `approver`, `auditor` |
| RAG scenario | alias `customer-information` (capability `query`) |
| Workflow scenario | alias `support-flow` (a high-risk tool node → approval) |
| Agent scenario | alias `assistant` |
| REST consumer + token | `demo-client` + `<REST_TOKEN>` (bound to all three) |
| MCP consumer + token | `demo-mcp-client` + `<MCP_TOKEN>` (bound to all three) |

---

## 1. Operator console + authorization

Open `http://127.0.0.1:8000/console/`.

| # | Test | Expected |
| --- | --- | --- |
| 1.1 | Visit `/console/` while logged out | Redirect to `/console/login/` |
| 1.2 | Log in as `admin` / `<PASSWORD>` | **Ana Sayfa** opens with scoped health KPIs only; each KPI opens a dedicated exact-record list; username/logout are top-right |
| 1.3 | Use Ana Sayfa / Projeler / Dokümanlar / İstemciler / Çalıştırmalar, then open a project and scenario | Sidebar exposes these five tasks; scenario, artifact, release and DSL details remain contextual |
| 1.4 | Log out (top-right, POST) then log in as `auditor` | Read-only: no "New …" create links |
| 1.5 | Log in as `editor` | Can open Scenario/Builder authoring; cannot promote |
| 1.6 | Log in as `releaser`, open a project → scenario → Release'ler | Eval / Promote / Rollback / Canary detail actions remain visible |
| 1.7 | (multi-tenant) All lists show only `demo` | No cross-tenant rows |
| 1.8 | Open **Doküman setleri**, then a set | Primary journey shows bulk upload, lifecycle blockers, set versions, sources, scenarios and consumers; no standalone inventory is in primary navigation |
| 1.9 | As `editor`, open a document inside a set and upload a replacement | A new immutable document version is shown and the manual draft pins the new version |
| 1.10 | Remove a document from a draft, then inspect an already published version | Only the draft membership changes; published version lineage remains unchanged |
| 1.11 | Tombstone a set document | New replacement is disabled; historical pins remain visible and the UI states bytes are retained |
| 1.12 | Open **Doküman setleri** as an admin | No standalone saklama yönetimi link appears; document work begins from a set |
| 1.13 | As `editor`, open a document set's **Kaynakları yönet** page | Guided upload/Confluence/REST steps explain profile, immutable mapping, no-egress preview, binding and sync; endpoint/credential/input values remain hidden |
| 1.14 | Open a connected source detail | Last sync time, safe failure code/counts and source → draft → published → staged → active progression appear; sync is not presented as direct activation |
| 1.15 | Repeat source detail as `auditor`, then with a foreign-tenant account | Auditor sees no **Şimdi çalıştır** mutation; foreign source ID returns 404 |
| 1.13 | As `editor` or `auditor`, request `/console/documents/advanced/` | HTTP 403; standalone storage inventory is not disclosed |
| 1.16 | Request legacy GET lists `/console/organizations/`, `/console/scenarios/`, `/console/artifacts/`, `/console/releases/` | Internal redirect reaches Ana Sayfa or Projeler; POST to a removed catalogue is not redirected |
| 1.17 | At 390, 900 and 1440 px, scroll a long scenario/document page and use keyboard-only navigation | Sidebar stays dark/readable, tables scroll, focus remains visible and task tabs reach real sections |
| 1.18 | Log in as a multi-org user with no saved selection, then forge/revoke the saved organization | Exactly one deterministic authorized workspace remains active; “Tüm organizasyonlar” never appears |
| 1.19 | As platform admin choose **Yeni organizasyon** | Organization and initial admin are created together and the new workspace becomes active |
| 1.20 | As organization admin open **Kullanıcılar ve yetkiler**; add, change and remove a directory user | Only the active organization changes; `platform_admin` is absent; last organization admin removal/change is rejected |
| 1.21 | Repeat document-set/source/index actions as `document_manager`, then open project/scenario/consumer/release/member mutations | Document-plane actions are available; every non-document mutation is denied |
| 1.22 | Open New Project, New Consumer and New Document Set; open New Scenario from a project | No organization/project selector is present; forged parent POST fields cannot change the trusted context |

Tip: `admin` is a superuser (sees everything); the others are role-scoped to `demo`.

---

## 2. Visual workflow builder (Sprint 11)

Log in as `editor` (or `admin`) and open **Builder** (`/console/builder/`).

| # | Test | Expected |
| --- | --- | --- |
| 2.1 | Select organization `demo`; **New draft** (name + `logical_id`, e.g. `my_flow`) | Canvas opens |
| 2.2 | Drag/click `Input`, `Retrieve`, `Generate`, `Format output`, `End` onto the canvas | Nodes appear |
| 2.3 | Connect Input → … → End by dragging handle to handle | Edges form; can't draw out of End |
| 2.4 | Add a `Condition` node, connect two out-edges | Auto-typed `true` / `false` branches |
| 2.5 | Add a `Tool` node, open the config panel | `binding role` dropdown lists **role names only** — no endpoint/secret |
| 2.6 | Click **Validate** with a broken graph (e.g. no End) | Backend error banner + red node |
| 2.7 | Fix the graph, **Validate** | "Compiles cleanly · checksum …" |
| 2.8 | Edit a node, watch the toolbar | "unsaved changes" badge appears |
| 2.9 | Try to close the browser tab with unsaved edits | Browser warns (beforeunload) |
| 2.10 | **Save**, then **Publish** | Creates a `workflow_definition` artifact (see Artifacts screen) |
| 2.11 | Log in as `auditor`, open the same draft | Read-only: palette/save/publish disabled |
| 2.12 | Open a scenario and choose **Scenario Studio** | Builder opens with that scenario/project context; unrelated drafts are absent |
| 2.13 | Open the same draft in two tabs, save in tab A, then save tab B | Tab B receives a stale-revision conflict and keeps its unsaved candidate |
| 2.14 | As `releaser`, select compatible immutable artifacts on the scenario page and compile | A candidate release shows exact roles, versions and checksums; active release is unchanged |
| 2.15 | Repeat as `auditor`, then forge a foreign/incompatible artifact ID | Auditor has no compile action; forged input fails without creating a release or disclosing the artifact |
| 2.16 | Publish a valid `agenthub/transform/v1` profile and compile a candidate that pins it | Exact immutable version/checksum is retained; active runtime is unchanged |
| 2.17 | Add an unknown operation, code field, malformed pointer or excessive nesting | Publication/compile fails with a stable content-free validation code |
| 2.18 | Replay the same transform input twice | Canonical output and source identity are identical; input is not mutated |
| 2.19 | Use a retrieval profile with top-k, threshold and the reserved `metadata_filter` field | Results remain inside release pins, tenant and consumer ACL; threshold is applied; the reserved metadata expression is explicitly shown/documented as a Phase 3 no-op and is not represented as authorization or result narrowing |
| 2.20 | Forge organization, consumer, index or document-set IDs inside retrieval JSON | Exact-key validation rejects the profile; no authority scope is widened |
| 2.20a | In a published document set choose exact chunking and retrieval profiles, optionally choose both summary model and prompt, then start a staged build | The job records exact profile refs/checksums; summary is visibly ready or fails with a stable code; no content appears in logs/audit |
| 2.20b | Search the same active set with keyword, vector and hybrid profiles | All modes return only the same authorized live corpus; diagnostics distinguish vector rank/score, keyword rank/score and fused score |
| 2.20c | Enable automatic staged preparation, publish the next set version and watch the job | One idempotent staged job is queued; the previously active index remains active until an authorized explicit promotion |
| 2.20d | Open older set, document and index version links | The exact historical version opens without changing the latest draft or active pointer |
| 2.20e | Use a retrieval profile with `summary_document_top_k: 10` and `max_chunks_per_document: 3`, then query a corpus with summaries | Diagnostics show `summary_routed`; returned passages are only source `content` chunks from the selected exact document versions, with at most three per document |
| 2.20f | Repeat with a query that matches content but no summary | Retrieval reports `summary_fallback` and safely returns authorized direct content results instead of an empty answer |
| 2.21 | Open **Scenario Studio** from a new scenario, paste a complete valid `agenthub/v1` Workflow JSON and create the draft | The page names and locks the scenario/project; the JSON opens as the equivalent graph and remains editable in both views |
| 2.22 | In the JSON view enter malformed or compiler-invalid workflow JSON, then attempt to switch/apply/save | The current graph is preserved, save/publish cannot use the unapplied JSON and a stable safe diagnostic is shown |
| 2.23 | Open an existing scenario with a linked draft | Only that scenario's workflow opens; JSON and graph show the same body and graph edits appear in JSON |
| 2.24 | Open an existing scenario with an active workflow but no linked draft, then choose the active-workflow editing action | The exact checksum-matching active body is copied to a new scenario draft; the active release and immutable artifact remain unchanged |
| 2.25 | Repeat 2.21–2.24 as `auditor` and with a foreign-tenant scenario URL | Auditor can inspect but cannot edit/copy; foreign scenario is not disclosed |
| 2.26 | Select every workflow node and inspect its configuration panel | Generate shows optional prompt/model role fields; format output, condition, tool and custom show their supported fields; input, retrieve, validate contract and end correctly state that they have no configuration |

The published artifact then follows the normal compile → eval → promote path (§4).

---

## 3. Consumer API — RAG query (synchronous)

```bash
curl -i -s -X POST http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer <REST_TOKEN>" -H "Content-Type: application/json" \
  -H "Idempotency-Key: response-1" \
  -d '{"model":"empty-workflow","input":"hello","background":false}'
```

Expected: `HTTP 200`, `"status":"completed"`, a `resp_...` response ID, and an
`X-AgentHub-Run-Id` UUID header. A canonical `Run` and ordered `RunEvent` trail remain persisted.

Negative checks:
- Omit the `Authorization` header → `401`.
- Wrong alias / an alias the token isn't bound to → `403`.

### 3.1 OpenAI-compatible HTTPS adapters

Local settings enable these routes; other environments must explicitly set
`OPENAI_COMPAT_ENABLED=true`. The consumer must use protocol `REST`.

Default synchronous RAG call:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer <REST_TOKEN>" -H "Content-Type: application/json" \
  -d '{"model":"customer-information","messages":[{"role":"user","content":"What are your opening hours?"}]}'
```

Expected: `HTTP 200`, `object=chat.completion`, an opaque `chatcmpl_…` id and one assistant
message. `model` is the bound scenario alias, not an OpenAI/provider model name.

Responses synchronous RAG alternative:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer <REST_TOKEN>" -H "Content-Type: application/json" \
  -d '{"model":"customer-information","input":"What are your opening hours?"}'
```

For workflow/agent use `/v1/responses`, `"background":true` and a bounded unique
`Idempotency-Key`; expect `HTTP 202`, `status=queued` and an opaque run id under `metadata.run_id`.
`/v1/chat/completions` rejects async scenarios. Both adapters reject streaming, multimodal content,
client tools/functions and request-side contract/model-profile overrides. A token created for MCP
is rejected on these HTTPS routes.

---

## 4. Consumer API — workflow with human approval (async)

**Invoke** (needs `Idempotency-Key`):

```bash
curl -s -X POST http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer <REST_TOKEN>" -H "Content-Type: application/json" \
  -H "Idempotency-Key: wf-1" \
  -d '{"model":"support-flow","input":{"query":"hello"},"background":true}'
```

Expected: `HTTP 202`, `"status":"queued"`, a `resp_...` response ID and a UUID
`metadata.run_id`.

**Poll** (after the worker runs it):

```bash
curl -s http://127.0.0.1:8000/v1/runs/<run_id> -H "Authorization: Bearer <REST_TOKEN>"
```

Expected: `"status":"waiting_approval"` — the high-risk tool node paused the run.

**Approve** (operator side; the requester cannot self-approve):

```bash
python manage.py list_tool_approvals --organization demo
python manage.py decide_tool_approval --approval <id> --actor approver --approve
```

Poll again → `"status":"completed"` with redacted output
(`{"echo":{"query":"[redacted]"},"status":"[redacted]"}`). The run **auto-resumes** on the
approval signal. Try `--reject` on a fresh run instead → the run fails closed with
`TOOL_REJECTED`.

You can also approve in the console: log in as `approver` → **Tool approvals** → Approve.

---

## 5. Consumer API — agent (async)

```bash
curl -s -X POST http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer <REST_TOKEN>" -H "Content-Type: application/json" \
  -H "Idempotency-Key: agent-1" \
  -d '{"model":"agent-loop","input":{"query":"Summarize the refund policy."},"background":true}'
```

Expected: `HTTP 202` with one canonical **opaque UUID** Run ID. Poll
`GET /v1/runs/<uuid>` until a terminal status.

Operator side:
- Console → **Runs** → open the run → redacted trace (no raw prompt/objective); Cancel.
- Consumer API: `POST /v1/runs/<uuid>/cancel` with the same REST bearer token.

---

## 6. Release lifecycle (operator)

As `releaser` (or `admin`) on the **Releases** screen, or via CLI:

- `python manage.py run_eval --release <id>` — runs the pinned eval suite in isolation.
- `python manage.py promote_release --release <id>` — fail-closed (needs a passing eval +
  ready pinned indexes).
- `python manage.py rollback_release --release <id>` — atomically restores the prior release.
- `python manage.py start_canary … / stop_canary …` — consumer-scoped, time-bounded routing.
- GitOps: `import_gitops` / `export_gitops` / `validate_artifacts` / `compile_release`.

---

## 7. MCP ingress + observability

- **MCP** (same policy/routing as REST, authenticated):
  ```bash
  curl -s -X POST http://127.0.0.1:8000/mcp/ -H "Content-Type: application/json" \
    -H "Authorization: Bearer <MCP_TOKEN>" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  ```
  Unauthenticated → `401 AUTHENTICATION_REQUIRED` (endpoint enabled only when
  `MCP_ENABLED=true`). A REST token is rejected; create a consumer with protocol `MCP`.
- **Metrics** (Prometheus; needs the bearer token the server was started with):
  ```bash
  curl -s http://127.0.0.1:8000/internal/metrics -H "Authorization: Bearer <METRICS_TOKEN>"
  ```
  Expect `agenthub_gateway_requests_total`, `agenthub_agent_runs_total`, etc.
- **Health**: `GET /v1/health/live` → `200` (unauthenticated).
- **Audit**: after any create/publish/approve, the event is recorded (visible in the DB
  `audit_auditevent` table); no secrets or raw payloads are stored.

---

## 8. Phase 2.5 owner acceptance

Run these checks after the automated Part 9 gates. Record pass/fail, the operator role, scenario or
object ID, and a screenshot or request ID for failures. Do not paste tokens, prompts, document bytes,
provider responses or secrets into the acceptance record.

| # | Owner acceptance test | Expected |
| --- | --- | --- |
| 8.1 | Log in as `admin`, select `demo`, then follow Organization → Project → Scenario → Document set → Consumer → Release and the reverse links | Every page stays in the selected organization, uses Turkish-first labels and exposes no unrelated tenant rows/counts |
| 8.2 | Repeat relevant pages as `editor`, `releaser`, `auditor`, then use a foreign-tenant object URL | Mutations match the role matrix; foreign objects return 404 and do not leak labels/counts |
| 8.3 | Create a project, scenario and REST consumer | System IDs are generated; required ownership is explicit; the token is shown once and never redisplayed |
| 8.4 | Complete upload → draft → publish → staged index → promote for a document set, then inspect its scenario/source cross-links | Immutable versions and pins are visible; no source sync or upload activates content directly |
| 8.5 | Preview Confluence and REST mapping with invalid then valid synthetic input, without live egress | Invalid mapping fails safely; preview reveals no endpoint/credential and does not mutate published/active state |
| 8.6 | Open a new scenario's Studio, paste a complete valid `agenthub/v1` workflow JSON, switch to graph, edit node settings, validate and save | JSON and graph represent the same scenario-isolated draft; all supported nodes expose governed configuration or explicitly valid no-config semantics |
| 8.7 | Reopen the scenario from its own detail page and edit both JSON and graph; attempt stale concurrent save and an unknown/oversized DSL operation | Existing graph remains editable; stale save conflicts; unknown or over-budget DSL fails closed with useful diagnostics |
| 8.8 | Create/compile/evaluate/promote a release with optional output contract, invoke it, then rollback | Exact immutable artifacts and optional contract are pinned; rollback restores the superseded release atomically |
| 8.9 | Invoke the same bound RAG alias through `/v1/chat/completions` and `/v1/responses` with the REST token; try the MCP token and an unbound alias | REST calls return compatible bounded envelopes; MCP token and unbound alias are denied without content leakage |
| 8.10 | Invoke through MCP with the MCP token; try the REST token | MCP succeeds only for the bound MCP consumer; REST credential is denied |
| 8.11 | Inspect audit/usage/metrics after creation, denial, invocation, promotion and rollback | Actor/tenant/action/outcome/request correlation is present; tokens, content, endpoints and credentials are absent |
| 8.12 | Disable the REST/MCP consumer or adapter feature, retry invocation, then restore it | Traffic fails closed while disabled and resumes only after explicit restoration; immutable history remains intact |
| 8.13 | As an authorized author, create a question set, edit its JSON cases, publish it, then edit the draft again | The published version remains immutable and the draft revision advances; stale revision submission is rejected |
| 8.14 | From the question-set page, run retrieval evaluation against an exact document-set version/index | Results identify the pinned target, show separate hit@k/recall@k/MRR denominators, and reveal retained chunk text/scores only to a content-authorized reader |
| 8.15 | Run answer evaluation against an exact release, including a case without applicable assertions | Deterministic answer pass rate is separate from retrieval metrics; non-applicable/judge failures are unscored rather than silently failed |
| 8.16 | Ask a one-off question from a document-set and scenario page, then inspect evaluation run counts | The response/evidence is shown, but no question set, case evidence or aggregate evaluation run is created |
| 8.17 | Repeat question-set/run URLs as auditor, unauthorized author and another tenant; attempt publish/start/cancel POSTs | Auditor output is redacted and read-only; unauthorized/foreign access is non-disclosing; no mutation or content leakage occurs |

Owner sign-off for Phase 2.5 means all applicable checks above pass or have an explicitly accepted,
documented residual finding. It does not close Phase 2 live activation.

## 9. Phase 2 live-environment acceptance

Perform this section only with approved synthetic/non-production data and a named change/rollback
owner. Each row requires the exact environment-specific approval described in the Phase 2 closure
plan; local stubs do not count.

| # | Live acceptance test | Expected evidence |
| --- | --- | --- |
| 9.1 | Provision the dedicated production application role and exercise an empty, valid and cross-tenant pooled request/worker context | Role is non-owner, non-superuser and `NOBYPASSRLS`; empty/cross-tenant access denies; pooled context does not leak |
| 9.2 | Register approved Confluence and generic REST profiles, grant only `demo`, run one bounded synthetic preview/sync, then disable each profile | CA/DNS/firewall and redirect controls pass; only the granted tenant receives a draft; audit is redacted; disable stops egress |
| 9.3 | Register approved embedding and OCR profiles and build one bounded synthetic index/document | Retention/privacy and cost ceilings are approved; timeout/size/token/page limits apply; uncertain post-send outcomes are not blindly retried |
| 9.4 | Configure the approved AI-authoring model and run candidate → diagnostics → explicit draft transfer | Candidate remains non-publishing; canonical diagnostics are authoritative; disabling `AI_AUTHORING_MODEL_PROFILE_ID` stops authoring |
| 9.5 | Review dashboards/alerts and audit records for the smoke operations; execute documented disable/rollback drills | Request IDs correlate logs/metrics/audit without secrets/content; rollback owners confirm recovery and residual risks |

Phase 2 closes only after all five rows have attached evidence plus privacy/retention, spend and
residual-risk approval. If a provider is intentionally omitted, the owner must remove that capability
from the approved Phase 2 target or explicitly accept the unverified risk; absence is not a pass.

### 9.4 AI-authoring profile activation

Register a platform-approved immutable profile with synthetic/non-production access. The command
accepts only a secret reference; never put the provider credential in arguments, source or `.env`.

```powershell
.venv\Scripts\python.exe manage.py register_model_profile `
  --actor '<PLATFORM_ADMIN_USERNAME>' `
  --logical-id 'studio-authoring' `
  --revision 1 `
  --host '<APPROVED_PUBLIC_PROVIDER_HOST>' `
  --model '<APPROVED_MODEL>' `
  --secret-ref 'secret:<APPROVED_SECRET_NAME>'
```

Copy the printed public UUID into the deployment environment and restart the web role. Workers do
not generate Studio candidates.

```powershell
$env:AI_AUTHORING_MODEL_PROFILE_ID = '<MODEL_PROFILE_PUBLIC_UUID>'
$env:AI_AUTHORING_PROVIDER = 'apps.orchestration.authoring.OpenAICompatibleAuthoringProvider'
```

Open a scenario's Studio. Preflight must report that AI authoring is ready. Generate a candidate,
inspect diagnostics, explicitly transfer it to a draft, and confirm that no artifact or release was
created. Then unset `AI_AUTHORING_MODEL_PROFILE_ID`, restart web, and confirm the Studio shows the
actionable disabled message while existing drafts and artifacts remain intact.

## 10. Re-seed / reset

```powershell
# Wipe and rebuild the demo tenant (prints a fresh token)
.venv\Scripts\python.exe manage.py seed_demo --reset --password '<PASSWORD>'
```

`--reset` deletes only the `demo` organization's data (leaf-first, because the schema uses
PROTECT foreign keys) and rebuilds it. Publishing a new token each run is expected.

---

## Not exercised by this guide

Real LLM/embedding answers (deterministic stubs today), document ingestion into a live
pgvector index (needs MinIO + the `ingestion` worker), live tool egress
(`TOOL_ADAPTER=deterministic` opens no socket), and a live LDAP directory (local uses Django
accounts). These are tracked in the planning/verified-state records.
