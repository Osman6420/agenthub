# RAGaaS Hedef Mimari ve Uygulama Planı

> Bu doküman, kurumsal RAG-as-a-Service platformunun tek başına okunabilir
> hedef mimari ve uygulama planıdır. Amaç; farklı iş birimlerinin doküman,
> web sayfası, bilgi bankası ve kurum içi kaynaklardan beslenen RAG tabanlı
> asistanlarını hızlı, güvenli, ölçülebilir ve tekrar kullanılabilir şekilde
> yayına alabileceği bir platform kurmaktır.
>
> Tarih: 2026-07-09

---

## 1. Mimari Karar Özeti

RAGaaS platformu beş ana katmandan oluşur:

1. **Control Plane**
   Proje, kaynak, policy, output contract, consumer yetkisi, release, eval ve
   audit yaşam döngüsünü yönetir.

2. **Gateway Plane**
   REST ve MCP tüketicileri için tek giriş kapısıdır. Kimlik doğrulama, yetki,
   rate limit, tenant context üretimi ve dış sözleşme stabilitesi burada
   sağlanır.

3. **Query Runtime Plane**
   Düşük gecikmeli RAG sorgularını çalıştırır. Retrieval, rerank, generation,
   output validation, policy enforcement, metric ve trace üretimi bu katmanda
   yapılır.

4. **Ingestion Plane**
   Uzun süren kaynak senkronizasyonu ve index üretimini yürütür. Fetch, parse,
   chunk, embed ve blue-green index yazımı query runtime'dan ayrıdır.

5. **Evaluation / Release Plane**
   Her proje release'inin eval, contract, safety, smoke, canary ve rollback
   akışını yönetir. Runtime, prompt, policy, embedding ve index değişiklikleri
   proje bazlı promote edilir.

Bu mimaride yeni bir basic RAG projesi açmanın normal yolu kod yazmak değil,
şu artefact'leri eklemektir:

- Project config
- Source config
- Prompt referansı
- Output contract
- Policy profili
- Eval set
- Consumer credential ve yetki
- İlk ingestion run
- Project release

Adapter servisi yalnız özel iş entegrasyonu, transaction, side effect veya
stateful workflow gerektiğinde kullanılır.

---

## 2. Hedefler

Platformun birinci hedefi çok sayıda RAG projesini tek tek servis yazmadan
üretime alabilmektir. Bunun için RAG davranışı config, contract ve policy ile
tanımlanır.

Ana hedefler:

- **Tek giriş kapısı:** Dış sistemler REST veya MCP Gateway üzerinden bağlanır.
- **Tenant izolasyonu:** Proje seçimi caller'ın serbest parametresine değil,
  doğrulanmış consumer kimliğine ve yetki setine dayanır.
- **Kod tekrarı yok:** Basic projeler için ayrı REST wrapper, Dockerfile,
  Deployment veya Route üretilmez.
- **Sorgu ve ingestion ayrımı:** Query runtime düşük latency için stateless
  ölçeklenir; ingestion worker uzun işleri kontrollü yürütür.
- **Sürümlü release:** Her proje runtime, prompt, policy, output contract,
  embedding modeli ve index version birleşiminden oluşan bir release'e bağlıdır.
- **Eval zorunluluğu:** Her project release, canlıya alınmadan önce project
  eval setinden geçer.
- **Rollback:** Aktif release ve önceki release birlikte tutulur; hata halinde
  hızlı geri dönüş yapılır.
- **Gözlemlenebilirlik:** Request, token, latency, retrieval quality, ingestion
  ve eval metrikleri proje bazında izlenir.
- **Güvenli secret yönetimi:** Config dosyaları secret değeri taşımaz, yalnız
  secret referansı taşır.

Kapsam dışı hedefler:

- Genel amaçlı agent platformu kurmak.
- Tüm kurum içi MCP server'ları tek server altında birleştirmek.
- Her müşteriye özel kod fork'u üretmek.
- İlk sürümde quota billing veya self-service Admin UI zorunlu kılmak.

---

## 3. Hedef Topoloji

```
                          GitOps / CI / Admin CLI
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                               CONTROL PLANE                                 │
│  Project Registry  │ Source Registry │ Policy Registry │ Release Registry  │
│  Output Contracts  │ Eval Suites     │ Consumer AuthZ  │ Audit Events       │
└───────────────┬───────────────────────────────────────┬────────────────────┘
                │ compiled project release               │ eval/release kararları
                ▼                                       ▼
┌──────────────────────────────┐              ┌───────────────────────────────┐
│          GATEWAY PLANE        │              │    EVALUATION / RELEASE       │
│  REST API                     │              │  Golden set runner             │
│  MCP Server                   │              │  Contract snapshot diff         │
│  Consumer auth                │              │  Safety checks                  │
│  Rate limit                   │              │  Shadow / canary promotion      │
│  ProjectContext issuer        │              │  Rollback coordinator           │
└───────────────┬──────────────┘              └───────────────┬───────────────┘
                │ signed ProjectContext                        │ promote/rollback
                ▼                                              │
┌───────────────────────────────────────────────────────────────▼─────────────┐
│                            QUERY RUNTIME PLANE                              │
│  Query Service                                                              │
│  Retrieval Service                                                          │
│  Rerank Service                                                             │
│  Generation Service                                                         │
│  Output Validation + Policy Engine                                          │
│  Metrics / Tracing / Usage Events                                           │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ active release -> active index
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                  DATA PLANE                                  │
│  Postgres control tables          pgvector/vector index                      │
│  Object store raw/parsed docs     Usage, audit, run, eval records            │
│  Locks and durable queue          Index versions and retention metadata       │
└───────────────▲─────────────────────────────────────────────────────────────┘
                │ staged index writes
┌───────────────┴─────────────────────────────────────────────────────────────┐
│                              INGESTION PLANE                                │
│  Scheduler / Run Creator                                                    │
│  Durable queue                                                              │
│  Worker or K8s Job                                                          │
│  Fetch -> Parse -> Normalize -> Chunk -> Embed -> Upsert staged index        │
│  Per-project lock, retry, dead-letter, status reporting                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Kavram Sözlüğü

| Kavram | Tanım |
|---|---|
| Project | RAG hizmeti verilen mantıksal bot/asistan. Örnek: müşteri destek botu, web yönlendirme botu. |
| Consumer | Platformu çağıran sistem veya agent. Örnek: web backend, mobil backend, LibreChat agent. |
| Source | Ingestion ile okunan veri kaynağı. Örnek: web API, filesystem, Confluence, object store. |
| Output Contract | Query response şekli. Örnek: freetext, structured_link, ticket_draft. |
| Policy | Güvenlik ve davranış kuralları. Örnek: grounding zorunluluğu, URL allowlist, PII redact. |
| ProjectContext | Gateway'in doğrulanmış consumer için ürettiği tenant ve yetki bağlamı. |
| Runtime Version | Query runtime imaj/kod sürümü. |
| Index Version | Belirli source snapshot, parser, chunker ve embedding modeliyle üretilmiş vector index. |
| Project Release | Runtime, prompt, policy, output contract, embedding modeli ve index version birleşimi. |
| Eval Suite | Project release'i canlıya almadan önce çalıştırılan test soru ve beklenti seti. |

---

## 5. Component Tasarımı

### 5.1 Control Plane

Control Plane runtime request işlemez. Platformun yönetim ve release otoritesidir.

Sorumlulukları:

- Project registry tutmak.
- Source registry tutmak.
- Consumer ve permission yönetmek.
- Config dosyalarını doğrulayıp compiled release üretmek.
- Output contract ve JSON Schema versiyonlarını yönetmek.
- Policy profilini sürümlemek.
- Prompt referanslarını ve prompt versiyonlarını yönetmek.
- Ingestion run başlatmak.
- Project release promote ve rollback etmek.
- Eval sonuçlarını release kararına bağlamak.
- Audit event üretmek.

İlk sürüm uygulama şekli:

- GitOps tabanlı YAML config.
- `control_plane` CLI ile validate/compile/promote işlemleri.
- Postgres control tabloları.
- Admin UI olmadan başlama.

Önerilen modüller:

```text
control_plane/
  __init__.py
  config_loader.py
  compiler.py
  registry.py
  releases.py
  authz.py
  audit.py
  cli.py
```

Control Plane CLI komutları:

```bash
ragctl validate-configs
ragctl compile-project --project mcm_musteri_bot --env staging
ragctl create-ingestion-run --project mcm_musteri_bot --source mcm_content
ragctl promote-release --project mcm_musteri_bot --release rel_20260709_001
ragctl rollback-release --project mcm_musteri_bot --to rel_20260708_003
ragctl list-releases --project mcm_musteri_bot
```

### 5.2 Gateway Plane

Gateway dış tüketici sözleşmesini taşır. Query runtime doğrudan dışa açılmaz.

Gateway yüzeyleri:

1. **REST Gateway**
   Düz backend ve uygulama entegrasyonları için kullanılır.

2. **MCP Gateway**
   Agent/tool-loop kullanan tüketiciler için kullanılır.

Gateway sorumlulukları:

- Consumer credential doğrulamak.
- Consumer -> project permission çözmek.
- Capability kontrolü yapmak.
- Rate limit ve request boyut limiti uygulamak.
- Idempotency key kabul etmek.
- ProjectContext üretmek ve imzalamak.
- Runtime'a yalnız doğrulanmış context göndermek.
- Dış hata formatını sabitlemek.
- Usage event başlatmak.

Önerilen modüller:

```text
gateway/
  __init__.py
  rest_app.py
  mcp_app.py
  auth.py
  project_context.py
  rate_limit.py
  errors.py
  client.py
```

REST endpoint taslağı:

```http
POST /v1/query
Authorization: Bearer <consumer-token>
Idempotency-Key: <uuid>
Content-Type: application/json

{
  "query": "İade süreci nasıl işler?",
  "stream": false,
  "return_sources": true,
  "metadata": {
    "conversation_id": "optional",
    "user_id_hash": "optional"
  }
}
```

REST response taslağı:

```json
{
  "request_id": "req_01H...",
  "project_id": "mcm_musteri_bot",
  "release_id": "rel_20260709_001",
  "answer": "İade süreci ...",
  "sources": [
    {
      "source_id": "mcm_content",
      "source_uri": "https://...",
      "title": "İade Politikası",
      "score": 0.82
    }
  ],
  "usage": {
    "input_tokens": 1200,
    "output_tokens": 220
  }
}
```

MCP tool yüzeyi:

```text
rag__query(query: str, options?: QueryOptions) -> RagResponse
rag__retrieve(query: str, options?: RetrieveOptions) -> RetrievedChunk[]
rag__ingestion_status(run_id?: str, project_alias?: str) -> IngestionStatus
```

MCP tool çağrılarında default davranış consumer context'ten proje çözmektir.
Bir consumer birden fazla projeye yetkiliyse proje alias seçimi allowlist ile
doğrulanır.

### 5.3 Query Runtime Plane

Query Runtime stateless çalışır. Her request için Gateway'den gelen
ProjectContext doğrulanır ve aktif Project Release yüklenir.

Sorumlulukları:

- Project release cache kullanmak.
- Query embedding üretmek.
- Aktif index version üzerinde vector search yapmak.
- Rerank uygulamak.
- Prompt render etmek.
- LLM generation çağırmak.
- Output contract validate etmek.
- Policy engine çalıştırmak.
- Usage event tamamlamak.
- Metric ve trace üretmek.

Önerilen modüller:

```text
runtime/
  __init__.py
  app.py
  service.py
  project_release_cache.py
  retrieval.py
  rerank.py
  generation.py
  output_validation.py
  policy_engine.py
  usage.py
  errors.py
```

Runtime internal request:

```json
{
  "project_context": {
    "project_id": "mcm_musteri_bot",
    "tenant_namespace": "mcm_musteri_bot",
    "consumer_id": "ug_backend",
    "capabilities": ["query"],
    "release_id": "rel_20260709_001",
    "expires_at": "2026-07-09T12:05:00Z",
    "signature": "..."
  },
  "query": "İade süreci nasıl işler?",
  "options": {
    "stream": false,
    "return_sources": true
  }
}
```

Runtime response:

```json
{
  "request_id": "req_01H...",
  "answer": "İade süreci ...",
  "output": {
    "type": "freetext",
    "data": {
      "text": "İade süreci ..."
    }
  },
  "sources": [],
  "usage": {
    "input_tokens": 1200,
    "output_tokens": 220,
    "model": "gpt-compatible-model"
  },
  "quality": {
    "top_score": 0.82,
    "retrieved_chunk_count": 5
  }
}
```

Runtime hata sınıfları:

- `AUTH_CONTEXT_INVALID`
- `PROJECT_RELEASE_NOT_FOUND`
- `INDEX_NOT_READY`
- `RETRIEVAL_FAILED`
- `GENERATION_FAILED`
- `OUTPUT_CONTRACT_VIOLATION`
- `POLICY_VIOLATION`
- `RATE_LIMITED`

### 5.4 Ingestion Plane

Ingestion, durable run modeliyle çalışır. Her run kayıtlıdır, izlenebilir,
retry edilebilir ve proje bazında kilitlenir.

Sorumlulukları:

- Schedule veya manuel talep ile ingestion run oluşturmak.
- Aynı proje/source için çakışan run'ları engellemek.
- Fetcher ile kaynakları okumak.
- Raw dokümanı object store'a yazmak.
- Parser ile normalize etmek.
- Content hash ve source fingerprint üretmek.
- Chunk üretmek.
- Embedding üretmek.
- Staging index version'a yazmak.
- Smoke retrieval test çalıştırmak.
- Run sonucunu ve istatistikleri kaydetmek.
- Dead-letter ve retry yönetmek.

Önerilen modüller:

```text
ingestion/
  __init__.py
  scheduler.py
  queue.py
  worker.py
  run_store.py
  locks.py
  fetchers/
    web_api.py
    filesystem.py
    confluence.py
  parsers/
    html.py
    pdf.py
    docx.py
    json.py
  chunkers/
    recursive.py
    markdown.py
    semantic.py
  embedder.py
  index_writer.py
  smoke.py
```

Run lifecycle:

```text
requested -> queued -> running -> staged_index_ready -> smoke_passed -> promotable
requested -> queued -> running -> failed_retryable -> queued
requested -> queued -> running -> failed_terminal -> dead_letter
```

Ingestion statü response:

```json
{
  "run_id": "ing_01H...",
  "project_id": "mcm_musteri_bot",
  "source_id": "mcm_content",
  "status": "running",
  "target_index_version": "idx_20260709_001",
  "stats": {
    "fetched_documents": 120,
    "changed_documents": 8,
    "chunks_written": 342
  },
  "started_at": "2026-07-09T10:00:00Z",
  "finished_at": null,
  "error": null
}
```

### 5.5 Evaluation / Release Plane

Evaluation ve release canlı kalite güvencesidir. Her release bir dizi otomatik
kontrolden geçmeden aktif olmaz.

Sorumlulukları:

- Contract snapshot diff çalıştırmak.
- Project eval suite çalıştırmak.
- Retrieval smoke test çalıştırmak.
- Customer-facing policy testlerini çalıştırmak.
- Shadow query veya canary sonucunu ölçmek.
- Release promote etmek.
- Release rollback etmek.
- Eval history tutmak.

Önerilen modüller:

```text
evaluation/
  __init__.py
  runner.py
  assertions.py
  judges.py
  contract_diff.py
  safety.py
  reports.py

release/
  __init__.py
  promote.py
  rollback.py
  canary.py
  shadow.py
```

Eval case örneği:

```yaml
project_id: web_routing_bot
release_candidate: rel_candidate_20260709_001
cases:
  - id: routing_payment_page
    query: "Kredi kartı ödeme sayfası nerede?"
    expected:
      output_contract: structured_link
      target_url_host_allowlist: ["kurum.com"]
      target_url_contains: "/odeme"
      min_confidence: 0.60

  - id: unknown_question
    query: "Kurumun Mars ofisi nerede?"
    expected:
      behavior: refuse_or_fallback
      must_not_fabricate: true
```

---

## 6. Proje Tipleri

### 6.1 Basic Project

Basic Project tek sorgu ile tek RAG cevabı dönen projedir.

Kriterler:

- Harici transaction veya side effect yoktur.
- Output contract standarttır.
- Policy ile ifade edilebilen davranış yeterlidir.
- Proje özelinde ayrı stateful workflow gerekmez.

Onboarding artefact'leri:

- `configs/projects/<project_id>.yaml`
- `configs/prompts/<prompt_name>.txt`
- `configs/output_contracts/<contract>.json`
- `configs/policies/<policy>.yaml`
- `configs/evals/<project_id>.yaml`
- Consumer secret veya service account kaydı

### 6.2 Configurable Workflow Project

Configurable Workflow Project, tek sorgu akışına ek validation, fallback,
formatter veya basit branching ekleyen projedir.

Örnek workflow:

```yaml
workflow:
  type: rag_then_validate
  steps:
    - retrieve
    - rerank
    - generate
    - validate_output
    - apply_fallback
  validators:
    - type: url_allowlist
      domains: ["kurum.com"]
    - type: confidence_min
      value: 0.60
  fallback:
    type: static_response
    answer: "Bu konuda sizi ana sayfaya yönlendirebilirim."
    target_url: "https://kurum.com"
```

### 6.3 Adapter Project

Adapter Project, RAG cevabından önce veya sonra proje özel entegrasyon yapan
servistir.

Adapter gerektiren durumlar:

- CRM, ticket, ödeme, operasyon sistemi gibi side effect üreten entegrasyon.
- Kuruma özel başka MCP server'larıyla çok adımlı agent akışı.
- Uzun yaşayan session state.
- Özel network zone veya veri sınıflandırması.
- Standart policy/workflow DSL ile ifade edilemeyen business rule.

Adapter servisi yalnız kendi iş entegrasyonunu taşır. Retrieval/generation
mantığını import etmez; Gateway veya Runtime contract'ı üzerinden çağırır.

---

## 7. Config ve Contract Modeli

### 7.1 Project Config

```yaml
api_version: ragaas/v1
kind: Project
metadata:
  id: mcm_musteri_bot
  owner: ug
  environment: prod
  visibility: customer_facing
spec:
  tenant_namespace: mcm_musteri_bot
  default_locale: tr
  sources:
    - ref: sources/mcm_content.yaml
  pipeline:
    chunker_ref: chunkers/recursive_512_64.yaml
    embedding_ref: embeddings/default_bge_m3.yaml
    retrieval_ref: retrieval/customer_support_top5.yaml
    reranker_ref: rerankers/listwise_v1.yaml
    generation_ref: generation/customer_facing_v1.yaml
  output_contract_ref: output_contracts/freetext.v1.json
  policy_ref: policies/customer_facing_grounded.yaml
  eval_ref: evals/mcm_musteri_bot.yaml
  consumers:
    - ug_backend
```

### 7.2 Source Config

```yaml
api_version: ragaas/v1
kind: Source
metadata:
  id: mcm_content
spec:
  type: web_api
  base_url: https://mcm.kurum.com/api/content
  auth_ref: secret:mcm-api-token
  pagination:
    type: cursor
    param: next_token
  schedule:
    interval: daily
    timezone: Europe/Istanbul
  parser_ref: parsers/html_default.yaml
```

### 7.3 Pipeline Config

```yaml
chunker:
  type: recursive
  size: 512
  overlap: 64

embedding:
  provider_ref: default_embedding
  model: bge-m3
  dimension: 1024

retrieval:
  top_k: 5
  min_score: 0.25

reranker:
  type: listwise
  enabled: true

generation:
  model_ref: default_chat
  prompt_ref: prompts/customer_facing_freetext.v3.txt
  temperature: 0.2
  max_tokens: 512
```

### 7.4 Output Contract

Freetext:

```json
{
  "$id": "output_contracts/freetext.v1",
  "type": "object",
  "required": ["answer"],
  "properties": {
    "answer": {"type": "string"},
    "sources": {
      "type": "array",
      "items": {"$ref": "#/$defs/source"}
    }
  },
  "$defs": {
    "source": {
      "type": "object",
      "required": ["source_id", "source_uri"],
      "properties": {
        "source_id": {"type": "string"},
        "source_uri": {"type": "string"},
        "title": {"type": "string"},
        "score": {"type": "number"}
      }
    }
  }
}
```

Structured link:

```json
{
  "$id": "output_contracts/structured_link.v1",
  "type": "object",
  "required": ["answer", "target_url", "confidence"],
  "properties": {
    "answer": {"type": "string"},
    "target_url": {"type": "string", "format": "uri"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "fallback_used": {"type": "boolean"}
  }
}
```

### 7.5 Policy Config

```yaml
api_version: ragaas/v1
kind: Policy
metadata:
  id: customer_facing_grounded
spec:
  grounding:
    required: true
    no_answer_behavior: fallback
  prompt_injection:
    ignore_context_instructions: true
    mark_retrieved_context_as_untrusted: true
  pii:
    mode: redact
  output:
    citations: optional
    max_answer_chars: 4000
  url:
    allowlist_domains: ["kurum.com"]
```

### 7.6 Consumer Config

```yaml
api_version: ragaas/v1
kind: Consumer
metadata:
  id: ug_backend
spec:
  protocol: rest
  auth:
    type: bearer
    secret_ref: secret:ug-backend-ragaas-token
  permissions:
    - project_id: mcm_musteri_bot
      capabilities: [query]
  rate_limit:
    rpm: 120
    burst: 30
```

---

## 8. Veri Modeli

### 8.1 Control Plane Tabloları

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    tenant_namespace TEXT NOT NULL UNIQUE,
    owner TEXT NOT NULL,
    environment TEXT NOT NULL,
    visibility TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE consumers (
    id TEXT PRIMARY KEY,
    protocol TEXT NOT NULL,
    auth_subject TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE consumer_project_permissions (
    consumer_id TEXT NOT NULL REFERENCES consumers(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    capabilities TEXT[] NOT NULL,
    PRIMARY KEY (consumer_id, project_id)
);

CREATE TABLE project_releases (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    runtime_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    output_contract_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    index_version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    promoted_at TIMESTAMPTZ
);
```

### 8.2 Ingestion Tabloları

```sql
CREATE TABLE ingestion_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    source_id TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,
    target_index_version TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE index_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL,
    chunker_fingerprint TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    promoted_at TIMESTAMPTZ
);
```

### 8.3 Vector Tabloları

```sql
CREATE TABLE chunks (
    id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL,
    tenant_namespace TEXT NOT NULL,
    index_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    title TEXT,
    text TEXT NOT NULL,
    embedding vector(1024) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, index_version, chunk_id)
);

CREATE INDEX chunks_project_index_idx
    ON chunks (project_id, index_version);

CREATE INDEX chunks_tenant_index_idx
    ON chunks (tenant_namespace, index_version);
```

Embedding dimension farklı modellerde değişebileceği için ilk production
tasarımında şu iki seçenekten biri seçilmelidir:

1. Model/dimension başına ayrı vector table.
2. pgvector dışı bir vector store kullanılıyorsa collection/index başına dimension.

MVP için tek embedding dimension seçilip tablo o dimension ile başlatılabilir.
Farklı dimension ihtiyacı roadmap'e model routing ile alınır.

### 8.4 Usage ve Audit Tabloları

```sql
CREATE TABLE usage_events (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    consumer_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    runtime_version TEXT NOT NULL,
    index_version TEXT NOT NULL,
    operation TEXT NOT NULL,
    token_in INTEGER,
    token_out INTEGER,
    latency_ms INTEGER,
    status TEXT NOT NULL,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    before JSONB,
    after JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 9. Güvenlik Modeli

### 9.1 Kimlik Doğrulama

REST consumer'ları bearer token veya mTLS/service account kimliğiyle doğrulanır.
MCP consumer'ları da aynı consumer registry'sine bağlanır.

Token doğrulama sonucu:

- `consumer_id`
- `protocol`
- `auth_subject`
- `status`
- izinli project/capability listesi

### 9.2 ProjectContext

Gateway her doğrulanmış request için imzalı ProjectContext üretir.

```json
{
  "project_id": "mcm_musteri_bot",
  "tenant_namespace": "mcm_musteri_bot",
  "consumer_id": "ug_backend",
  "capabilities": ["query"],
  "release_id": "rel_20260709_001",
  "expires_at": "2026-07-09T12:05:00Z",
  "request_id": "req_01H..."
}
```

Runtime şu kontrolleri yapar:

- İmza geçerli mi?
- `expires_at` geçerli mi?
- `query` capability var mı?
- `release_id` project ile eşleşiyor mu?
- Project release aktif mi?

### 9.3 Capability Modeli

| Capability | Kullanım |
|---|---|
| `query` | Normal RAG sorgusu |
| `query_stream` | Streaming response |
| `retrieve_debug` | Debug amaçlı chunk görüntüleme |
| `ingestion_read` | Ingestion status okuma |
| `ingestion_trigger` | Ingestion run başlatma |
| `release_read` | Release bilgisi okuma |
| `release_promote` | Release aktif etme |
| `admin` | Control Plane yönetim |

### 9.4 Network Güvenliği

Production NetworkPolicy:

- Gateway dış ingress alabilir.
- Runtime'a yalnız Gateway, Eval runner ve gerekli admin job'ları erişebilir.
- Ingestion worker dış ingress almaz.
- Postgres/vector store'a yalnız Runtime, Ingestion ve Control Plane erişebilir.
- Object store'a yalnız Ingestion ve sınırlı admin job'ları erişebilir.

### 9.5 Secret Yönetimi

Kurallar:

- Config dosyalarında secret değeri bulunmaz.
- Config yalnız `secret_ref` taşır.
- Secret çözümleme fail-closed çalışır.
- Secret okunamazsa ilgili source veya consumer disabled kabul edilir.
- Secret değişimi audit event üretir.

---

## 10. Query Akışı

### 10.1 REST Query Sequence

```text
Consumer
  -> Gateway: POST /v1/query
  -> Gateway: authenticate consumer
  -> Gateway: authorize project + query capability
  -> Gateway: create request_id + ProjectContext
  -> Runtime: POST /internal/query
  -> Runtime: validate ProjectContext
  -> Runtime: load active Project Release
  -> Runtime: embed query
  -> Runtime: vector search active index_version
  -> Runtime: rerank
  -> Runtime: render prompt
  -> Runtime: generate
  -> Runtime: validate output contract
  -> Runtime: apply policy/fallback
  -> Runtime: write usage event
  -> Gateway: normalize response
  -> Consumer: RagResponse
```

### 10.2 Runtime Processing Steps

1. Request parse ve validation.
2. ProjectContext validation.
3. Release load.
4. Query preprocessing.
5. Query embedding.
6. Vector search.
7. Rerank.
8. Context packing.
9. Prompt rendering.
10. LLM generation.
11. JSON/output parsing.
12. Output contract validation.
13. Policy validation.
14. Fallback veya response finalize.
15. Metrics, traces, usage event.

### 10.3 Streaming

Streaming ilk MVP'de opsiyonel olabilir; public contract baştan yer bırakmalıdır.

REST:

```http
POST /v1/query
{
  "query": "...",
  "stream": true
}
```

Streaming transport:

- REST için SSE.
- MCP için progress/streaming response desteği.

Policy ve output contract streaming sonunda final response üzerinde tekrar
validate edilir. Structured output contract'larında streaming kapalı tutulabilir.

---

## 11. Ingestion Akışı

### 11.1 Schedule

Scheduler her çalıştığında source schedule'larını değerlendirir ve due olanlar
için ingestion run oluşturur.

```text
Scheduler
  -> Control Plane: due source list
  -> Control Plane: create ingestion_run
  -> Queue: enqueue run_id
  -> Worker: claim run
```

### 11.2 Worker Steps

1. Run claim.
2. Project/source config load.
3. Per-project/source lock acquire.
4. Fetch documents.
5. Raw object write.
6. Parse and normalize.
7. Content hash diff.
8. Chunk.
9. Embed.
10. Upsert chunks into staging index version.
11. Smoke retrieval.
12. Mark index `promotable`.
13. Mark run `promotable` or `failed`.
14. Lock release.

### 11.3 Retry

Retry policy:

- Network/fetch transient error: retry.
- Parser unsupported format: terminal fail for document, run partial success.
- Embedding provider timeout: retry.
- Vector DB write failure: retry.
- Contract/config error: terminal fail.

Retry alanları:

- `attempt_count`
- `next_retry_at`
- `last_error_code`
- `last_error_message`

### 11.4 Dead Letter

Run belirlenen deneme sayısından sonra `dead_letter` durumuna alınır. Alert
üretilir. Operator `ragctl retry-ingestion --run <id>` ile yeniden deneyebilir.

---

## 12. Release ve Rollout

### 12.1 Project Release İçeriği

```json
{
  "id": "rel_20260709_001",
  "project_id": "mcm_musteri_bot",
  "runtime_version": "rag-runtime:2.1.0",
  "prompt_version": "customer_facing_freetext:v3",
  "policy_version": "customer_facing_grounded:v1",
  "output_contract_version": "freetext:v1",
  "embedding_model": "bge-m3",
  "index_version": "idx_20260709_001",
  "status": "active"
}
```

### 12.2 Promotion Gates

Bir release aktif olmadan önce şu gate'lerden geçer:

1. Config validation.
2. Contract snapshot diff.
3. Prompt render smoke.
4. Index readiness.
5. Retrieval smoke.
6. Project eval suite.
7. Customer-facing safety suite.
8. Canary veya shadow check.

### 12.3 Rollback

Rollback yalnız `project_releases.status` değiştirerek yapılmalıdır.

```text
active -> rolled_back
previous_active -> active
```

Index ve prompt artefact'leri retention süresi boyunca silinmez.

### 12.4 Canary

Canary iki şekilde uygulanabilir:

- Consumer bazlı: belirli internal consumer yeni release'e gider.
- Trafik yüzdesi: Gateway belirli yüzdeyi candidate release'e yönlendirir.

MVP için consumer bazlı canary daha basittir.

---

## 13. Eval Stratejisi

### 13.1 Eval Dosyası

```yaml
api_version: ragaas/v1
kind: EvalSuite
metadata:
  project_id: mcm_musteri_bot
spec:
  cases:
    - id: refund_policy
      query: "İade süreci nasıl işler?"
      expected:
        must_contain_any:
          - "iade"
          - "başvuru"
        source_uri_contains: "/iade"
        min_top_score: 0.45

    - id: unsupported_question
      query: "Kurumun Mars ofisi nerede?"
      expected:
        behavior: refuse_or_fallback
        must_not_contain:
          - "Mars ofisimiz"
```

### 13.2 Assertion Tipleri

- `must_contain`
- `must_contain_any`
- `must_not_contain`
- `source_uri_contains`
- `source_id_equals`
- `target_url_contains`
- `target_url_host_allowlist`
- `min_confidence`
- `min_top_score`
- `behavior: refuse_or_fallback`
- `json_schema_valid`

### 13.3 LLM-as-Judge

İlk sürümde deterministik assert'ler tercih edilir. Serbest metin kalitesi için
LLM-as-judge sonradan eklenebilir. Judge output'u release kararında tek kaynak
olmamalıdır; deterministik safety ve contract kontrolleri her zaman çalışır.

---

## 14. Gözlemlenebilirlik

### 14.1 Structured Log Alanları

Her request için:

- `timestamp`
- `request_id`
- `trace_id`
- `project_id`
- `consumer_id`
- `release_id`
- `runtime_version`
- `index_version`
- `operation`
- `duration_ms`
- `status`
- `error_code`
- `token_in`
- `token_out`
- `retrieved_chunk_count`
- `top_score`

### 14.2 Prometheus Metrikleri

```text
rag_gateway_requests_total{project,consumer,status}
rag_gateway_request_duration_seconds{project,consumer}
rag_runtime_requests_total{project,release,status}
rag_runtime_duration_seconds{project,release,operation}
rag_runtime_errors_total{project,release,error_code}
rag_tokens_total{project,model,direction}
rag_retrieval_top_score{project,index_version}
rag_ingestion_runs_total{project,source,status}
rag_ingestion_duration_seconds{project,source}
rag_eval_cases_total{project,status}
rag_release_promotions_total{project,status}
```

### 14.3 Alert Kuralları

- Runtime error rate son 5 dakikada eşik üstünde.
- Belirli projede p95 latency eşik üstünde.
- Customer-facing projede policy violation.
- Ingestion son 3 koşuda başarısız.
- Eval suite başarısız.
- Token tüketimi günlük beklenen bandın üstünde.
- Retrieval top score medyanı belirgin düşmüş.

### 14.4 Dashboard

Minimum dashboard panelleri:

- Project bazlı QPS.
- Project bazlı p50/p95 latency.
- Runtime error rate.
- Token usage.
- Ingestion run status.
- Active release listesi.
- Eval pass/fail trend.
- Retrieval top score trend.

---

## 15. Repo ve Dosya Yerleşimi

Hedef repo düzeni:

```text
control_plane/
  config_loader.py
  compiler.py
  registry.py
  releases.py
  authz.py
  audit.py
  cli.py

gateway/
  rest_app.py
  mcp_app.py
  auth.py
  project_context.py
  rate_limit.py
  errors.py
  runtime_client.py

runtime/
  app.py
  service.py
  project_release_cache.py
  retrieval.py
  rerank.py
  generation.py
  output_validation.py
  policy_engine.py
  usage.py

ingestion/
  scheduler.py
  queue.py
  worker.py
  run_store.py
  locks.py
  fetchers/
  parsers/
  chunkers/
  embedder.py
  index_writer.py
  smoke.py

evaluation/
  runner.py
  assertions.py
  contract_diff.py
  safety.py
  reports.py

contracts/
  openapi/
  json_schema/
  snapshots/

configs/
  projects/
  sources/
  prompts/
  policies/
  output_contracts/
  evals/

openshift/
  gateway.yaml
  runtime.yaml
  ingestion-worker.yaml
  scheduler.yaml
  networkpolicy.yaml
  secrets.example.yaml

tests/
  control_plane/
  gateway/
  runtime/
  ingestion/
  evaluation/
```

İmajlar:

- `rag-gateway`
- `rag-runtime`
- `rag-ingestion-worker`
- `rag-control-cli`

MVP'de aynı Python package içinden birden fazla entrypoint build edilebilir.
Runtime process ve ingestion worker process ayrı çalışmalıdır.

---

## 16. OpenShift Yerleşimi

### 16.1 Deployment'lar

| Workload | Tip | Replica | Açıklama |
|---|---|---:|---|
| `rag-gateway` | Deployment | 2+ | REST/MCP giriş kapısı |
| `rag-runtime` | Deployment | 2+ | Stateless query runtime |
| `rag-ingestion-worker` | Deployment veya Job | 1+ | Queue tüketen worker |
| `rag-scheduler` | CronJob | 1 | Due source'lardan ingestion run yaratır |
| `rag-eval-runner` | Job | talep bazlı | Release candidate eval koşar |

### 16.2 Service'ler

- `rag-gateway`: dış Route alır.
- `rag-runtime`: cluster internal.
- `postgres`: cluster internal.
- `object-store`: cluster internal veya managed servis.

### 16.3 NetworkPolicy

Minimum policy:

- Internet/kurum ingress -> yalnız Gateway.
- Gateway -> Runtime.
- Eval runner -> Runtime.
- Runtime -> Postgres/vector store + LLM endpoint.
- Ingestion worker -> Postgres/vector store + object store + source endpoints +
  embedding endpoint.
- Scheduler -> Control Plane DB veya Control CLI job.

### 16.4 ConfigMap ve Secret

ConfigMap:

- compiled project configs
- prompt templates
- policy configs
- output contracts

Secret:

- consumer tokens
- source credentials
- DB credentials
- LLM credentials
- ProjectContext signing key

---

## 17. Uygulama Planı

Bu plan, ilk çalışan platformu üretmek için PR/sprint şeklinde uygulanabilir.

### Sprint 1 - Contract ve Config Temeli

Amaç: Platformun artefact modelini ve validation katmanını kurmak.

İşler:

1. `configs/projects/`, `configs/sources/`, `configs/policies/`,
   `configs/output_contracts/`, `configs/evals/` dizinlerini oluştur.
2. Pydantic config modellerini yaz.
3. JSON Schema output contract loader yaz.
4. `control_plane config_loader` ve `compiler` modüllerini yaz.
5. `ragctl validate-configs` komutunu ekle.
6. Örnek üç proje config'i ekle.
7. Config validation testlerini yaz.

Kabul kriterleri:

- Eksik `source_ref`, `policy_ref`, `output_contract_ref` validation hatası verir.
- Secret değeri config içinde bulunursa validation hata verir.
- Eval dosyası olmayan project validation'dan geçmez.
- `pytest tests/control_plane -q` geçer.

### Sprint 2 - Control DB ve Release Modeli

Amaç: Project, consumer, release, ingestion ve usage tablolarını kurmak.

İşler:

1. DB migration mekanizmasını seç.
2. `projects`, `consumers`, `consumer_project_permissions` tablolarını ekle.
3. `project_releases`, `ingestion_runs`, `index_versions` tablolarını ekle.
4. `usage_events`, `audit_events` tablolarını ekle.
5. Registry repository sınıflarını yaz.
6. `ragctl compile-project` ve `ragctl list-releases` komutlarını ekle.
7. DB integration testlerini yaz.

Kabul kriterleri:

- Project config compile edilip DB'ye yazılır.
- Consumer permission sorgusu capability bazlı sonuç döner.
- Active release tekil constraint ile korunur.
- Audit event oluşur.

### Sprint 3 - Gateway MVP

Amaç: REST Gateway üzerinden tenant-aware query request alabilmek.

İşler:

1. `gateway/rest_app.py` Starlette/FastAPI uygulamasını oluştur.
2. Bearer token auth yaz.
3. Consumer -> project permission çözümünü ekle.
4. ProjectContext üretimi ve imzalamayı ekle.
5. Runtime client stub yaz.
6. Dış hata formatını standartlaştır.
7. Gateway unit/integration testlerini yaz.

Kabul kriterleri:

- Token yoksa 401.
- Yetkisiz project/capability 403.
- Geçerli consumer için ProjectContext üretilir.
- Gateway runtime'a `project_id`'yi raw caller input olarak değil context içinde
  gönderir.

### Sprint 4 - Query Runtime MVP

Amaç: Gateway'den gelen context ile tek query response üretebilmek.

İşler:

1. `runtime/app.py` internal endpoint'i oluştur.
2. ProjectContext validation yaz.
3. Active release cache yaz.
4. Retrieval service'i index_version filtresiyle yaz.
5. Generation service'i prompt/output contract ile yaz.
6. Output validation ekle.
7. Usage event yazımını ekle.
8. Runtime tests yaz.

Kabul kriterleri:

- İmzasız context reddedilir.
- Active release yoksa `PROJECT_RELEASE_NOT_FOUND`.
- Index ready değilse `INDEX_NOT_READY`.
- Output contract dışı response `OUTPUT_CONTRACT_VIOLATION`.
- Başarılı query usage event üretir.

### Sprint 5 - Ingestion Queue ve Worker

Amaç: Source'lardan staged index üreten güvenilir worker kurmak.

İşler:

1. `ingestion_runs` queue claim mekanizmasını yaz.
2. Advisory lock veya transaction lock ekle.
3. Fetcher registry oluştur.
4. Parser registry oluştur.
5. Chunker registry oluştur.
6. Embedder abstraction yaz.
7. Staged index writer yaz.
8. Smoke retrieval ekle.
9. Worker CLI entrypoint ekle.
10. Retry/dead-letter state'lerini ekle.

Kabul kriterleri:

- Aynı proje/source için iki worker aynı run'ı işlemez.
- Başarılı run `promotable` index üretir.
- Retry edilebilir hata tekrar kuyruğa girer.
- Terminal hata dead-letter olur.

### Sprint 6 - Eval Runner

Amaç: Release candidate'i project eval setine karşı koşturmak.

İşler:

1. Eval YAML loader yaz.
2. Assertion engine yaz.
3. Runtime'a candidate release ile query çalıştırma desteği ekle.
4. Eval report formatı oluştur.
5. `ragctl run-eval --project ... --release ...` komutu ekle.
6. CI job taslağı ekle.

Kabul kriterleri:

- Eval case pass/fail raporu üretir.
- JSON Schema assertion çalışır.
- Source assertion çalışır.
- Failed eval release promotion'ı engeller.

### Sprint 7 - Release Promote ve Rollback

Amaç: Project release yaşam döngüsünü operasyonel hale getirmek.

İşler:

1. `ragctl promote-release` yaz.
2. Promotion gate kontrollerini bağla.
3. `ragctl rollback-release` yaz.
4. Release audit event ekle.
5. Gateway/Runtime active release cache invalidation ekle.
6. Rollback testlerini yaz.

Kabul kriterleri:

- Eval geçmeyen release promote edilemez.
- Promote sonrası query yeni release'e gider.
- Rollback sonrası query önceki release'e gider.
- Release değişimi audit event üretir.

### Sprint 8 - MCP Gateway

Amaç: Agent/tool-loop tüketicileri için MCP yüzeyi açmak.

İşler:

1. `gateway/mcp_app.py` ekle.
2. `rag__query` tool'unu REST Gateway ile aynı auth/authz path'e bağla.
3. `rag__retrieve` debug tool'unu capability kontrollü ekle.
4. `rag__ingestion_status` tool'unu ekle.
5. Tool schema snapshot testlerini ekle.

Kabul kriterleri:

- MCP tool isimleri namespace'li.
- Tool şeması snapshot değişimi CI'da görünür.
- `retrieve_debug` capability yoksa chunk dönmez.

### Sprint 9 - Observability ve Operasyon

Amaç: Prod izlenebilirliğini tamamlamak.

İşler:

1. Structured logging formatını standardize et.
2. Prometheus `/metrics` endpoint'lerini ekle.
3. Trace context propagation ekle.
4. Dashboard JSON veya Grafana panel taslağı ekle.
5. Alert rule dosyalarını ekle.
6. Runbook dokümanı ekle.

Kabul kriterleri:

- Project bazlı request, latency, error ve token metrikleri görülebilir.
- Ingestion run başarısızlığı alert üretir.
- Release sonrası error artışı alert üretir.

### Sprint 10 - OpenShift Manifests ve Prod Hazırlık

Amaç: Platformu OpenShift üzerinde çalışır hale getirmek.

İşler:

1. `openshift/gateway.yaml` ekle.
2. `openshift/runtime.yaml` ekle.
3. `openshift/ingestion-worker.yaml` ekle.
4. `openshift/scheduler.yaml` ekle.
5. `openshift/networkpolicy.yaml` ekle.
6. `openshift/secrets.example.yaml` güncelle.
7. Resource request/limit değerlerini belirle.
8. Health/readiness endpoint'lerini doğrula.

Kabul kriterleri:

- Gateway Route üzerinden query alınır.
- Runtime dışa expose edilmez.
- Worker dış ingress almaz.
- NetworkPolicy beklenen trafiği sınırlar.

---

## 18. İlk Milestone Tanımı

İlk milestone sonunda şu senaryo uçtan uca çalışmalıdır:

1. `mcm_musteri_bot` project config'i validate edilir.
2. Consumer token tanımlanır.
3. Ingestion run oluşturulur.
4. Worker source'u okur, chunk üretir, embedding yazar.
5. Index smoke test geçer.
6. Eval suite geçer.
7. Project release promote edilir.
8. REST Gateway üzerinden query gönderilir.
9. Runtime aktif release/index ile cevap üretir.
10. Usage event ve metrics oluşur.

Milestone kabul testi:

```bash
ragctl validate-configs
ragctl create-ingestion-run --project mcm_musteri_bot --source mcm_content
ragctl wait-ingestion --project mcm_musteri_bot
ragctl run-eval --project mcm_musteri_bot --release rel_candidate
ragctl promote-release --project mcm_musteri_bot --release rel_candidate
curl -X POST "$RAG_GATEWAY_URL/v1/query" \
  -H "Authorization: Bearer $UG_BACKEND_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"İade süreci nasıl işler?","return_sources":true}'
```

---

## 19. Test Stratejisi

### 19.1 Unit Tests

- Config schema validation.
- Policy validation.
- Output contract validation.
- ProjectContext signing/verification.
- Capability checks.
- Chunker behavior.
- Eval assertions.

### 19.2 Integration Tests

- Gateway -> Runtime happy path.
- Unauthorized consumer.
- Permission denied.
- Runtime active release load.
- Vector search index_version filter.
- Ingestion run claim and lock.
- Worker staged index write.
- Eval runner against test runtime.

### 19.3 Contract Tests

- REST OpenAPI snapshot.
- MCP tool schema snapshot.
- Output contract JSON Schema validation.
- Internal Runtime API schema snapshot.

### 19.4 End-to-End Tests

- Project onboarding to query.
- Ingestion to release promotion.
- Failed eval blocks release.
- Rollback changes active release.
- Customer-facing policy fallback.

---

## 20. Başlangıç Backlog'u

İlk uygulama için önerilen issue listesi:

1. `contracts`: JSON Schema ve OpenAPI snapshot altyapısı.
2. `control_plane`: Project/Source/Policy/Eval config modelleri.
3. `control_plane`: Config compiler ve `ragctl validate-configs`.
4. `db`: Control, release, ingestion, usage, audit tabloları.
5. `gateway`: REST app, bearer auth, ProjectContext.
6. `runtime`: Internal query endpoint ve context validation.
7. `runtime`: Release cache ve output contract validation.
8. `data`: `chunks` tablosuna `index_version` ve `embedding_model` modeli.
9. `ingestion`: Queue, worker, lock ve staged index writer.
10. `evaluation`: Eval suite loader ve assertion engine.
11. `release`: Promote/rollback CLI.
12. `mcp`: MCP Gateway ve tool schema snapshot.
13. `observability`: Metrics/logging/tracing.
14. `openshift`: Gateway/runtime/worker/scheduler manifests.
15. `docs`: Onboarding runbook ve operasyon runbook'u.

---

## 21. Başarı Kriterleri

Platform aşağıdaki kriterleri sağladığında hedef mimari ilk üretim seviyesine
ulaşmış kabul edilir:

- Yeni basic project açmak için Python modülü veya Dockerfile eklenmez.
- Her query doğrulanmış ProjectContext ile runtime'a ulaşır.
- Runtime query path'te aktif `project_release` ve `index_version` kullanır.
- Ingestion query runtime process'inde çalışmaz.
- Her project release eval suite geçmeden active olamaz.
- Rollback DB release state değişimiyle yapılabilir.
- Project bazlı latency, error, token ve ingestion metrikleri görülebilir.
- Contract değişiklikleri CI'da snapshot diff olarak görünür.
- Customer-facing projelerde grounding/policy fallback çalışır.

---

## 22. Karar Bekleyen Noktalar

Uygulamaya başlamadan netleştirilmesi gereken kararlar:

1. **DB migration aracı:** Alembic mi, SQL migration dosyaları mı?
2. **Object store:** İlk sürümde MinIO/S3 mü, filesystem mi?
3. **Embedding modeli:** MVP'de tek dimension hangi modelle sabitlenecek?
4. **Runtime internal protokol:** HTTP JSON yeterli mi, gRPC gerekli mi?
5. **ProjectContext imzası:** HMAC secret mı, mTLS/service mesh kimliği mi?
6. **Canary yöntemi:** Consumer bazlı mı, trafik yüzdesi bazlı mı?
7. **Admin yüzeyi:** İlk sürüm yalnız CLI mı, basit internal UI gerekir mi?

Önerilen başlangıç kararları:

- Migration: Alembic.
- Object store: MinIO/S3 uyumlu arayüz.
- Runtime internal protokol: HTTP JSON.
- ProjectContext imzası: HMAC + kısa TTL.
- Canary: consumer bazlı.
- Admin: CLI.

---

## 23. Sonuç

Bu mimari, RAG platformunu proje bazlı kod kopyaları yerine config, contract,
policy, ingestion run, eval ve release etrafında kurar. Dış tüketici sözleşmesi
Gateway'de, düşük latency RAG çalışması Runtime'da, uzun kaynak işleme
Ingestion'da, kalite ve canlıya alma disiplini Evaluation/Release katmanında
toplanır.

Başlangıç için en doğru yol, önce config/contract ve release temelini kurmak,
ardından Gateway + Runtime query path'i çalıştırmak, sonra ingestion worker ve
eval/promotion hattını bağlamaktır. Bu sıra tamamlandığında platform yeni RAG
projelerini ayrı servis yazmadan, kontrollü ve ölçülebilir şekilde yayına
alabilecek duruma gelir.
