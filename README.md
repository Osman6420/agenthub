# agenthub

AI agent yönetim platformu — Django modular monolith (RAG, workflow, agent, tool).

## Durum

Sprint 0 (temel) tamamlandı ve doğrulandı: bootable Django iskeleti, settings
ayrımı, Celery rol tanımları, health probe'ları, bağımlılık manifesti + lockfile,
Docker Compose (pgvector/Redis/MinIO) ve CI. Domain modelleri, kimlik/yetki, public
API ve runtime henüz yok — sonraki sprint'lerde geliyor. Ayrıntı:
[master plan](docs/planning/master-plan.md) ve
[Sprint 0 görev kaydı](docs/tasks/sprint-0-foundation/plan.md).

## Getting started (local)

Gereksinim: Python 3.13, Docker (opsiyonel, tam ortam için).

```bash
py -3.13 -m venv .venv
./.venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python

# Testler ve kalite kapıları (harici servis gerektirmez, SQLite test ayarları):
./.venv/Scripts/python -m pytest
./.venv/Scripts/python -m ruff check .
./.venv/Scripts/python -m mypy .

# Tam yerel ortam (Postgres+pgvector, Redis, MinIO, web + worker'lar):
docker compose -f deploy/compose/docker-compose.yml up --build
# Sağlık kontrolü: GET http://localhost:8000/v1/health/live  (ve .../ready)
```

## Public API (gateway)

Consumer'lar tek giriş noktası olan gateway'i kullanır. Önce bir consumer token'ı
oluşturun (düz metin bir kez gösterilir), sonra `POST /v1/invoke` çağırın:

```powershell
.\.venv\Scripts\python manage.py create_consumer_token --organization mcm --subject ug-backend --name demo
# curl (bash):
# curl -X POST http://localhost:8000/v1/invoke \
#   -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
#   -H "Idempotency-Key: <uuid>" \
#   -d '{"scenario_alias":"customer-information","input":{"query":"Iade nasil yapilir?"}}'
```

Kimlik yoksa `401`, yetkisiz alias/capability'de `403`, aynı idempotency key farklı
gövdeyle `409` döner. Cevap üretimi (RAG runtime) Sprint 4'te geliyor; şu an gateway
imzalı `ExecutionContext` üretip `accepted` döndürür.

## Control-plane authoring

Yetkili operatorler `/console/` altinda organization, project, scenario/alias,
consumer ve binding kayitlarini tenant-scope create formlariyla olusturabilir.
Reviewed YAML icin ayni create-only akis management command ile kullanilir:

```powershell
python manage.py import_control_plane --path gitops/control-plane --actor <operator-id>
python manage.py import_control_plane --path gitops/control-plane --actor <operator-id> --dry-run
```

Ayni icerigin tekrar importu no-op'tur; ayni kimlikte farkli icerik conflict olarak
reddedilir. Import tek transaction'da calisir ve olusturulan her kaydi audit eder.

## Ingestion and pgvector retrieval

Sprint 5 adds tenant-owned sources/runs, staged promotable indexes, bounded HTTPS/S3
connectors, Celery retry/dead-letter processing, and pgvector cosine retrieval:

```powershell
python manage.py start_ingestion --organization mcm --source policies
python manage.py retry_ingestion --run 42
```

Indexes are not activated automatically. Retrieval filters the signed-context tenant
and explicitly pinned index versions.

## MCP and operations

Sprint 7 provides an internal/VPN MCP endpoint at `/mcp/` using the same bearer-token,
binding, capability, release-routing, contract, runtime, usage, and audit path as REST.
Prometheus scrapes `/internal/metrics` with a secret-backed bearer token through private
cluster networking. Optional OTLP export is configured with an allowlisted
`OTEL_EXPORTER_OTLP_ENDPOINT`; an empty value disables export without affecting requests.
MCP is default-off and must be enabled only in an approved internal/VPN overlay. Draft
OpenShift, monitoring, and runbook assets are under `deploy/openshift`,
`deploy/monitoring`, and `docs/operations`.

## Workflow runtime

Sprint 8 adds compiled asynchronous workflows. A workflow scenario invoked through
`POST /v1/invoke` requires the `workflow_run` capability and an `Idempotency-Key`; the
gateway returns `202` with a `run_id`. Read or cancel the same consumer's run through
`GET` or `DELETE /v1/runs/{run_id}`. Runtime executes only release-pinned immutable
compiled graphs; arbitrary Python, endpoints, package uploads, and direct custom-node
tool calls are rejected.

## Belgeler

- [Django hedef mimari planı — doküman revizyonu 3](agenthub-v3-django-plan.md)

## Engineering and AI agent documentation

- [Coding-agent instructions](AGENTS.md)
- [Claude Code instructions](CLAUDE.md)
- [Engineering rules](docs/ai/engineering-rules.md)
- [Security rules](docs/ai/security-rules.md)
- [Testing rules](docs/ai/testing-rules.md)
- [Definition of Done](docs/ai/definition-of-done.md)
- [Coding-agent handoff and local UI smoke](docs/ai/agent-handoff.md)
- [Master plan](docs/planning/master-plan.md)
- [ADR index](docs/adr/README.md)
- [Task documentation and templates](docs/tasks/README.md)
