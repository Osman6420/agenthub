# AgentHub — Manual Testing Guide

A hands-on checklist for exercising **every** feature of a running local AgentHub. It
assumes the demo tenant seeded by `manage.py seed_demo`. Pair it with the
[user guide](user-guide.md) (how the product works) and the
[security overview](security-overview.md) (why it is safe).

> Credentials and tokens are **generated and printed by `seed_demo`** — they are not stored
> in this document. Run the seeder and copy the values it prints into the `<PASSWORD>` /
> `<TOKEN>` placeholders below.

---

## 0. Bring up the stack

The supported local topology is defined in
[`deploy/compose/docker-compose.yml`](../deploy/compose/docker-compose.yml). Do not
infer service state from an old handoff or PID: query Docker Compose and the health
endpoint each time.

Choose one mode and avoid starting duplicate web or worker processes:

```powershell
# Inspect current infrastructure/application state and health.
docker compose -f deploy/compose/docker-compose.yml ps
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/v1/health/live

# Mode A: run the complete stack in Docker.
docker compose -f deploy/compose/docker-compose.yml up --build

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

# Apply migrations, then seed the demo tenant (prints operator password + API token)
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_demo --password '<PASSWORD>'

# Web (serves the builder static bundle + enables MCP/metrics for testing)
$env:MCP_ENABLED = 'true'; $env:METRICS_BEARER_TOKEN = '<METRICS_TOKEN>'
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload

# In a second terminal: the async runtime worker (Windows -> --pool=solo)
.venv\Scripts\python.exe -m celery -A config.celery worker --pool=solo -Q runtime,default -l info
```

> **Only run one runtime worker.** A stale worker from an earlier session running older code
> will silently grab async runs and fail them (e.g. `WORKFLOW_NODE_UNSUPPORTED`). Kill any
> extra `celery ... worker -Q runtime` processes first.

The seeder provisions:

| Thing | Value |
| --- | --- |
| Organization / project | `demo` / `support` |
| Operators (password `<PASSWORD>`) | `admin` (platform admin), `editor`, `releaser`, `approver`, `auditor` |
| RAG scenario | alias `customer-information` (capability `query`) |
| Workflow scenario | alias `support-flow` (a high-risk tool node → approval) |
| Agent scenario | alias `assistant` |
| Consumer + token | `demo-client` + `<TOKEN>` (bound to all three) |

---

## 1. Operator console + authorization

Open `http://127.0.0.1:8000/console/`.

| # | Test | Expected |
| --- | --- | --- |
| 1.1 | Visit `/console/` while logged out | Redirect to `/console/login/` |
| 1.2 | Log in as `admin` / `<PASSWORD>` | Dashboard with scoped counts |
| 1.3 | Browse Organizations / Projects / Scenarios / Artifacts / Releases | `demo` data appears |
| 1.4 | Log out (top-right, POST) then log in as `auditor` | Read-only: no "New …" create links |
| 1.5 | Log in as `editor` | Can open Scenario/Builder authoring; cannot promote |
| 1.6 | Log in as `releaser`, open Releases | Eval / Promote / Rollback / Canary actions visible |
| 1.7 | (multi-tenant) All lists show only `demo` | No cross-tenant rows |
| 1.8 | Open **Doküman setleri**, then a set | Primary journey shows bulk upload, lifecycle blockers, set versions, sources, scenarios and consumers; no standalone inventory is in primary navigation |
| 1.9 | As `editor`, open a document inside a set and upload a replacement | A new immutable document version is shown and the manual draft pins the new version |
| 1.10 | Remove a document from a draft, then inspect an already published version | Only the draft membership changes; published version lineage remains unchanged |
| 1.11 | Tombstone a set document | New replacement is disabled; historical pins remain visible and the UI states bytes are retained |
| 1.12 | As `admin`, open **Gelişmiş saklama yönetimi** | Admin-only inventory is available; purge requires tombstone, exact ID confirmation and no set-version pins |
| 1.13 | As `editor`, open a document set's **Kaynakları yönet** page | Guided upload/Confluence/REST steps explain profile, immutable mapping, no-egress preview, binding and sync; endpoint/credential/input values remain hidden |
| 1.14 | Open a connected source detail | Last sync time, safe failure code/counts and source → draft → published → staged → active progression appear; sync is not presented as direct activation |
| 1.15 | Repeat source detail as `auditor`, then with a foreign-tenant account | Auditor sees no **Şimdi çalıştır** mutation; foreign source ID returns 404 |
| 1.13 | As `editor` or `auditor`, request `/console/documents/advanced/` | HTTP 403; standalone storage inventory is not disclosed |

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

The published artifact then follows the normal compile → eval → promote path (§4).

---

## 3. Consumer API — RAG query (synchronous)

```bash
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -d '{"scenario_alias":"customer-information","query":"What are your opening hours?"}'
```

Expected: `HTTP 200`, `"status":"completed"`, an `output.answer` and `usage` token counts.
(The answer is a deterministic stub — no real LLM is wired yet.)

Negative checks:
- Omit the `Authorization` header → `401`.
- Wrong alias / an alias the token isn't bound to → `403`.

---

## 4. Consumer API — workflow with human approval (async)

**Invoke** (needs `Idempotency-Key`):

```bash
curl -s -X POST http://127.0.0.1:8000/v1/invoke \
  -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -H "Idempotency-Key: wf-1" \
  -d '{"scenario_alias":"support-flow","input":{"query":"hello"}}'
```

Expected: `HTTP 202`, `"status":"queued"`, a numeric `run_id`.

**Poll** (after the worker runs it):

```bash
curl -s http://127.0.0.1:8000/v1/runs/<run_id> -H "Authorization: Bearer <TOKEN>"
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
curl -s -X POST http://127.0.0.1:8000/v1/invoke \
  -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  -H "Idempotency-Key: agent-1" \
  -d '{"scenario_alias":"assistant","input":{"query":"Summarize the refund policy."}}'
```

Expected: `HTTP 202` + an **opaque UUID** `run_id` (agent ids never collide with workflow
ids). Poll `GET /v1/runs/<uuid>` → `completed`.

Operator side:
- Console → **Agent runs** → open the run → redacted trace (no raw prompt/objective); Cancel.
- CLI: `python manage.py list_agent_runs --organization demo`;
  `python manage.py cancel_agent_run --organization demo --run <uuid>`.

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
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  ```
  Unauthenticated → `401 AUTHENTICATION_REQUIRED` (endpoint enabled only when
  `MCP_ENABLED=true`).
- **Metrics** (Prometheus; needs the bearer token the server was started with):
  ```bash
  curl -s http://127.0.0.1:8000/internal/metrics -H "Authorization: Bearer <METRICS_TOKEN>"
  ```
  Expect `agenthub_gateway_requests_total`, `agenthub_agent_runs_total`, etc.
- **Health**: `GET /v1/health/live` → `200` (unauthenticated).
- **Audit**: after any create/publish/approve, the event is recorded (visible in the DB
  `audit_auditevent` table); no secrets or raw payloads are stored.

---

## 8. Re-seed / reset

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
