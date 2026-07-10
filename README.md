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

## Belgeler

- [v3 Django Planı](agenthub-v3-django-plan.md)

## Engineering and AI agent documentation

- [Coding-agent instructions](AGENTS.md)
- [Claude Code instructions](CLAUDE.md)
- [Engineering rules](docs/ai/engineering-rules.md)
- [Security rules](docs/ai/security-rules.md)
- [Testing rules](docs/ai/testing-rules.md)
- [Definition of Done](docs/ai/definition-of-done.md)
- [Master plan](docs/planning/master-plan.md)
- [ADR index](docs/adr/README.md)
- [Task documentation and templates](docs/tasks/README.md)
