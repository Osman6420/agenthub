# AgentHub v3 Hedef Mimari ve Uygulama Plani

> Bu dokuman, v2 RAGaaS hedef mimarisini Django tabanli bir AgentHub'a donusturen
> hedef mimari ve uygulama planidir. AgentHub; RAG, LLM workflow, kontrollu agent,
> tool entegrasyonu ve ozel adapter senaryolarini ayni yonetisim modeliyle
> calistirir. Amac, farkli is birimlerinin AI projelerini ayri servisler, farkli
> yetki modelleri ve kontrolsuz agent kurulumlari olusturmadan guvenli bicimde
> uretime alabilmesidir.
>
> Tarih: 2026-07-09
> Durum: Hedef mimari

---

## 1. Mimari Karar Ozeti

AgentHub, kurumun AI senaryolari icin hem control plane hem de runtime
gorevi gorur. V2'deki Control Plane, Gateway Plane, Query Runtime, Ingestion
ve Evaluation/Release ayrimi korunur. Bu katmanlar ilk asamada ayri kod
tabanlari veya mikroservisler olarak degil, tek bir Django projesindeki
moduler uygulamalar olarak uygulanir.

Baslangic kararlari:

1. **Django modular monolith:** Tek repo, tek veri modeli ve tek release
   otoritesi kullanilir. HTTP API, Celery worker, scheduler ve eval worker
   ayni Python paketi icinden farkli process olarak calisir.
2. **RAG-first, agent-ready:** Ilk uretim dikey akisi RAG olur. Ancak Project,
   Scenario, Release, Policy, Contract, Tool ve Run modelleri ilk migration'dan
   itibaren workflow ve agent is yuklerini tasir.
3. **Scenario merkezli platform:** Bir AI Project, birden fazla is senaryosu
   barindirabilir. Canliya alinabilen, cagirilabilen ve release edilen birim
   `Scenario` olur.
4. **Config ve veri tabani birlikte:** Django ORM ve Postgres, canli control
   plane gercegidir. YAML artefact'lar GitOps import/export ve code review
   yuzeyi olarak kalir; runtime YAML dosyasi okumaz.
5. **Fail-closed yetkilendirme:** Consumer, project veya tool secimini serbest
   parametreyle yapamaz. Gateway kimlik, scenario binding ve capability
   kontrolunden sonra imzali `ExecutionContext` uretir.
6. **Release ile pinlenen davranis:** Prompt, policy, model profili, contract,
   workflow, tool binding, index ve runtime ayarlari immutable release icinde
   birlikte pinlenir.
7. **Asenkron isler worker'da:** Ingestion, eval, uzun sureli workflow, agent
   calismasi ve approval sonrasi devam etme Celery queue uzerinden calisir.
   Kisa RAG sorgulari ASGI API process'inde senkron tamamlanir.
8. **Tool erisimi merkezi:** Agent veya workflow, secret kullanarak dogrudan
   dis sisteme baglanmaz. Tum tool cagrilari Tool Execution Proxy'den gecer.
9. **Django Admin ile baslama:** Ilk control-plane arayuzu Django Admin ve
   management command'lerdir. Ozel React Flow Agent Builder sonradan ayni
   draft ve release API'lerini kullanacak sekilde eklenir.
10. **Kontrolsuz agent playground kapsam disidir:** Platformda sadece kayitli,
    yetkilendirilmis, degerlendirilmis ve release edilmis scenario'lar
    calistirilir.

---

## 2. Hedefler ve Kapsam Sinirlari

### 2.1 Ana hedefler

- Yeni bir RAG veya basit workflow senaryosu icin yeni Python servisi,
  Dockerfile veya route yazmadan onboarding yapabilmek.
- Is birimlerinin AI senaryolarini sahiplik, risk seviyesi, veri kaynaklari,
  policy, eval ve release bilgileriyle kataloglayabilmek.
- Tum external consumer'lari REST veya MCP uzerinden tek gateway modeline
  baglamak.
- Project, scenario, kaynak, dokuman, tool ve kullanici yetkilerini tenant
  sinirlari icinde zorunlu uygulamak.
- RAG, workflow ve agent davranisini ayni contract, policy, audit, eval ve
  rollback disipliniyle yonetmek.
- Ingestion ve uzun sureli agent islerini request latency yolundan ayirmak.
- Her release'in hangi prompt, model, policy, tool, index ve workflow ile
  calistigini sonradan yeniden uretilebilir bicimde bilmek.
- Yan etkili tool cagrilarini risk sinifi ve insan onayi ile kontrol etmek.
- Project ve scenario bazinda latency, hata, maliyet, retrieval kalitesi,
  tool kullanimi ve eval sonucunu izlemek.

### 2.2 Kapsam ici is yukleri

| Tur | Aciklama | Ornek |
|---|---|---|
| `rag` | Retrieval ve generation ile tek cevap uretir. | Prosedur asistani |
| `workflow` | Sinirli, derlenebilir DAG ile AI akisi calistirir. | Siniflandir, getir, cevapla |
| `agent` | Stateful, cok adimli, tool kullanabilen kontrollu akis. | BT destek triage |
| `adapter` | DSL ile ifade edilemeyen kuruma ozel entegrasyon. | Ozel operasyon servisi |

Saf LLM, siniflandirma, ozetleme veya extraction senaryolari ayri bir runtime
turune gerek duymadan `workflow` olarak modellenir. Ilk v3 runtime'i metin ve
dokuman odaklidir. Gorsel, ses veya video is yukleri sonraki asamada model
profili, input contract'i ve ingestion adapter'i eklenerek desteklenir.

### 2.3 Kapsam disi hedefler

- Kullaniciya keyfi Python kodu, keyfi prompt veya sinirsiz tool ile otonom
  agent olusturma yetkisi vermek.
- Her kurum ici MCP server'ini tek MCP process'inde birlestirmek.
- Dify, RAGFlow veya benzeri bir uygulamayi platformun runtime, authorization
  veya release otoritesi yapmak.
- Ilk surumde chargeback, faturalama veya tum kullanicilar icin self-service
  visual builder zorunlulugu getirmek.
- Uzun sureli insan kaynakli hafiza veya kisiler arasi kalici profil olusturmak.

---

## 3. Hedef Topoloji

```text
                 GitOps / Django Admin / Management Commands
                                      |
                                      v
+------------------------------------------------------------------+
|                         DJANGO CONTROL PLANE                     |
|  Tenant + Identity | Project/Scenario Catalog | Artefact Registry|
|  Source Registry   | Policy + Contract          | Release Registry|
|  Tool Registry     | Eval Suite                 | Audit            |
+------------------------------+-----------------------------------+
                               |
                compiled scenario release / access decisions
                               |
                               v
+------------------------------------------------------------------+
|                           DJANGO GATEWAY                         |
|  REST API | MCP ingress | Consumer AuthN/AuthZ | Rate limit       |
|  Idempotency | ExecutionContext issuer | Error normalization     |
+---------------+-----------------------------+--------------------+
                |                             |
                | short synchronous work      | durable work
                v                             v
+-------------------------------+    +--------------------------------+
|       RUNTIME SERVICES        |    |         CELERY WORKERS         |
| RAG runtime                   |    | ingestion | workflow | agent   |
| workflow compiler/executor    |    | eval | release jobs | scheduler|
| model provider adapters       |    | approval resume                |
| policy + contract enforcement |    +----------------+---------------+
+---------------+---------------+                     |
                |                                     |
                +------------------+------------------+
                                   |
                                   v
+------------------------------------------------------------------+
|                              DATA PLANE                          |
| Postgres + pgvector | Redis | S3/MinIO | Secret manager | LLM API |
| releases/runs/audit | chunks/indexes | raw documents   | tools    |
+------------------------------------------------------------------+
```

Bu topolojide Django, HTTP request yonlendiren ince bir katman degil;
registry, release, authz, audit, worker orkestrasayonu ve runtime servislerinin
ortak uygulama omurgasidir. Plane sinirlari servis sinirindan once kod,
sorumluluk ve deployment siniridir. Yuk ve ekip ihtiyaci olustugunda bu
moduller, davranis sozlesmesi degismeden ayri servisler olarak cikarilabilir.

---

## 4. Kavram Sozlugu

| Kavram | Tanim |
|---|---|
| Organization | Tenant siniri, sahiplik ve uyelik birimi. |
| AIProject | Bir AI urunu veya is biriminin sahip oldugu ust kapsayici. |
| Scenario | Cagirilabilen, release edilen, tek amacli AI davranisi. |
| Consumer | Gateway'i cagirabilen backend, uygulama, MCP client veya agent. |
| Binding | Bir consumer'in hangi scenario alias'ini hangi capability ile kullanabilecegi. |
| Artefact | Prompt, policy, contract, source, model, workflow veya eval gibi surumlu tanim. |
| ScenarioRelease | Tam bir canli davranisi olusturan immutable artefact bilesimi. |
| Source | Ingestion ile okunan veri kaynagi. |
| IndexVersion | Bir source snapshot, parser, chunker ve embedding profiliyle uretilen arama indeksi. |
| ExecutionContext | Gateway'in dogrulanmis cagridan urettigi imzali, kisa omurlu yetki baglami. |
| Run | Asenkron workflow veya agent calismasinin durable kaydi. |
| Tool | Agent/workflow tarafindan cagirilabilen kayitli MCP veya HTTP yetenegi. |
| Approval | Riskli bir adimin durdurulmus ve insan karari bekleyen kaydi. |
| EvalSuite | Release candidate icin calistirilan deterministik ve istege bagli judge testleri. |

---

## 5. Django Uygulama Tasarimi

### 5.1 Proje yapisi

```text
agenthub/
  manage.py
  config/
    settings/
      base.py
      local.py
      test.py
      production.py
    urls.py
    celery.py
    asgi.py
  apps/
    tenancy/
    identity/
    catalog/
    artifacts/
    releases/
    gateway/
    retrieval/
    ingestion/
    orchestration/
    tools/
    approvals/
    evaluations/
    observability/
    audit/
  contracts/
    openapi/
    json_schema/
    snapshots/
  gitops/
    projects/
    scenarios/
    sources/
    policies/
    prompts/
    contracts/
    workflows/
    tools/
    evals/
  tests/
    unit/
    integration/
    contract/
    e2e/
  deploy/
    compose/
    openshift/
```

### 5.2 Uygulama sorumluluklari

| Django app | Sorumluluk |
|---|---|
| `tenancy` | Organization, membership, tenant context ve tenant-aware queryset kurallari. |
| `identity` | OIDC subject, service account, consumer credential ve rol/capability esleme. |
| `catalog` | AIProject, Scenario, sahiplik, risk seviyesi, alias ve scenario kataloglama. |
| `artifacts` | Versioned prompt, policy, contract, model profile, source ve memory policy kayitlari. |
| `releases` | Release compiler, promotion gate, canary, active-release pointer ve rollback. |
| `gateway` | DRF endpoint'leri, MCP ingress, idempotency, rate limit ve ExecutionContext. |
| `retrieval` | Index, document, chunk, embedding, retriever, reranker ve citation uretimi. |
| `ingestion` | Source connector, parser, chunker, scheduler, Celery task ve index yazimi. |
| `orchestration` | Workflow DSL compiler, node registry, LangGraph adapter, run state ve runtime facade. |
| `tools` | Tool registry, tool binding, execution proxy, schema validation ve tool audit. |
| `approvals` | Approval request, karar, timeout, resume ve ayrik approver yetkisi. |
| `evaluations` | Eval loader, assertion engine, trajectory kontrolleri, rapor ve gate sonucu. |
| `observability` | Metrics, tracing, usage event, latency ve cost toplama. |
| `audit` | Degismez yonetim ve guvenlik olaylari. |

### 5.3 Uygulama ici bagimlilik kurallari

- `gateway`, domain servislerini cagirir; model sorgularini dogrudan daginik
  bicimde yapmaz.
- `releases` release compile eder; `orchestration` ve `retrieval` sadece
  compile edilmis release referansiyla calisir.
- `tools` secret cozumleme ve dis ag erisimini sahiplenir. Agent runtime,
  endpoint veya credential bilmez.
- `ingestion` aktif index'i degistiremez; yalniz staged index uretir.
- `evaluations` candidate release calistirabilir ama active pointer'i
  degistiremez.
- `audit` app'i append-only olay kaydi uretir; is kurali kararlarini geri
  etkilemez.

---

## 6. Control Plane Tasarimi

### 6.1 Organization ve sahiplik modeli

Her kayit bir `organization_id` ile baglanir. Platform operatoru farkli
organization'larin kaynaklarini, tool'larini veya run'larini sorgulayamaz;
bu sinir sadece UI filtresi degil, servis ve queryset katmaninda zorunlu
uygulanan bir kuraldir.

Roller:

| Rol | Yetki |
|---|---|
| `platform_admin` | Platform ayarlari ve organization olusturma. |
| `organization_admin` | Uye, consumer, project ve policy yonetimi. |
| `project_owner` | Kendi project/scenario artefact ve release adaylarini yonetme. |
| `scenario_editor` | Draft artefact ve workflow duzenleme. |
| `release_manager` | Eval sonucu gecen release'i promote veya rollback etme. |
| `approver` | Belirli risk sinifindaki tool approval kararlarini verme. |
| `auditor` | Salt okunur audit, run, eval ve release goruntuleme. |

Rol, global Django `is_staff` alanina indirgenmez. Organization uyeligi, project
sahipligi ve scenario binding ile birlikte degerlendirilir.

### 6.2 Project ve Scenario katalogu

`AIProject` is biriminin urun siniridir. Owner, maliyet merkezi, veri
siniflandirmasi, varsayilan locale ve varsayilan risk sinifi burada tutulur.

`Scenario`, project icindeki davranis birimidir. Ornekler:

- `musteri_bilgi_sorgula`: customer-facing RAG.
- `iade_yonlendirme`: RAG + confidence + structured URL workflow.
- `bt_destek_triage`: agent + runbook tool + ticket taslagi.
- `crm_firsat_olustur`: approval gerektiren adapter scenario.

Scenario alias'i external consumer icin stabil isimdir. Bir scenario yeni
release aldiginda alias degismez. Alias silinmez, kapatilir veya yeni
scenario'ya kontrollu yonlendirilir; boylece consumer contract'i korunur.

### 6.3 Artefact registry

Asagidaki artefact turlerinin her biri immutable version kaydi alir:

- `InputContract`
- `OutputContract`
- `PromptTemplate`
- `PolicyProfile`
- `ModelProfile`
- `SourceDefinition`
- `ChunkingProfile`
- `RetrievalProfile`
- `WorkflowDefinition`
- `ToolDefinition`
- `ToolBinding`
- `MemoryPolicy`
- `EvalSuite`

Artefact version kaydi, canonical JSON/YAML body, checksum, olusturan actor,
olusturulma zamani ve kaynak Git revision bilgisini tasir. Bir version
olustuktan sonra guncellenmez. Degisiklik yeni version ile temsil edilir.

### 6.4 GitOps ve Django Admin iliskisi

Ilk surumde iki kontrollu giris yolu vardir:

1. Django Admin ile draft olusturma veya mevcut kaydi duzenleme.
2. Git repo icindeki YAML dosyalarini `manage.py import_gitops` ile import etme.

Import islemi once Pydantic/JSON Schema ile dogrular, sonra taslagi olusturur.
Secret degeri, import edilen dosyada bulunursa import basarisiz olur. Admin'de
olusan release edilmis artefact, `manage.py export_gitops` ile review edilebilir
YAML'a donusturulebilir. Canli runtime'in config kaynagi her durumda Postgres'tir.

---

## 7. Workload Tipleri ve Runtime Davranisi

### 7.1 Basic RAG scenario

Basic RAG senaryosu retrieval ve generation yapar, tool cagirmaz ve kalici state
uretmez. Tipik kullanimlar prosedur soru-cevap, mevzuat asistani, urun bilgi
botu ve dokuman ozetlemedir.

Zorunlu artefact'lar:

- Input ve output contract
- Prompt template
- Policy profile
- Model ve retrieval profile
- En az bir index version'a bagli source
- Eval suite

### 7.2 Configurable workflow scenario

Workflow scenario, node katalogundan olusan sinirli bir DAG calistirir. RAG
zorunlu degildir; saf LLM extraction veya siniflandirma da workflow olabilir.

Ilk desteklenen node turleri:

- `input`
- `retrieve`
- `generate`
- `condition`
- `tool_call`
- `human_approval`
- `format_output`
- `validate_contract`
- `custom`
- `end`

Workflow DSL, node graph'ini ve node parametrelerini config dosyasinda tanimlar.
`custom` node, config icindeki serbest kod degil, merkezi registry'de kayitli ve
onayli bir CustomNodeDefinition referansidir. Node parametreleri schema ile
dogrulanir, edge'ler acyclic olmalidir ve her akis bir `end` node'una ulasmalidir.
Loop ve paralel branch ilk surumde kapsama alinmaz.

### 7.3 Agent scenario

Agent scenario, LangGraph uyumlu stateful bir graph uzerinde planlama, retrieval,
tool cagrisi ve gozlem dongusu calistirir. LangGraph execution motorudur; tool
yetkisi, approval, release, context imzasi, audit ve policy kontrolu AgentHub'da
kalir.

Her agent release'i su limitleri zorunlu tasir:

- `max_steps`
- `max_tool_calls`
- `max_total_tokens`
- `max_duration_seconds`
- `max_tool_result_bytes`
- izinli tool listesi
- memory policy
- approval policy

Bu limitlerden biri asildiginda run basarisiz olur ve output contract'in izin
verdigi guvenli fallback uretilir. Agent, kendisine izin verilmemis tool'a
erisemez ve ExecutionContext'te olmayan capability elde edemez.

### 7.4 Adapter scenario

Adapter scenario, kuruma ozel is kurali veya network zone entegrasyonu icin
kullanilir. Adapter, AgentHub tarafindan kayitli bir HTTP/gRPC endpoint veya
ayri worker olarak cagirilir. Adapter kendi retrieval, policy veya consumer
authz mantigini tasimaz; AgentHub'in input contract, execution context, output
contract ve audit sozlesmesine uyar.

Adapter ekleme kosullari:

- Workflow DSL ile guvenli bicimde ifade edilememe.
- Sorumlu ekip ve owner bilgisinin kayitli olmasi.
- Input/output schema ve timeout tanimlanmasi.
- Side effect varsa tool risk ve approval politikasinin atanmasi.
- Eval ve canary senaryosunun tanimlanmasi.

---

## 8. Config, Contract ve Release Modeli

### 8.1 Scenario config ornegi

```yaml
api_version: agenthub/v3
kind: Scenario
metadata:
  id: mcm_musteri_bilgi
  organization: mcm
  project: musteri_deneyimi
  owner: ug
spec:
  type: rag
  alias: customer-information
  visibility: customer_facing
  risk_level: medium
  input_contract_ref: contracts/customer_query.v1
  output_contract_ref: contracts/customer_answer.v1
  prompt_ref: prompts/customer_answer.v3
  policy_ref: policies/customer_grounded.v2
  model_profile_ref: models/default_chat.v1
  retrieval_profile_ref: retrieval/customer_top5.v1
  sources:
    - source_ref: sources/mcm_content.v1
  eval_suite_ref: evals/mcm_customer_information.v1
```

### 8.2 Input contract

```json
{
  "$id": "contracts/customer_query.v1",
  "type": "object",
  "required": ["query"],
  "properties": {
    "query": {"type": "string", "minLength": 1, "maxLength": 8000},
    "conversation_id": {"type": "string", "maxLength": 128},
    "user_id_hash": {"type": "string", "maxLength": 128},
    "locale": {"type": "string", "maxLength": 16}
  },
  "additionalProperties": false
}
```

### 8.3 Output contract

```json
{
  "$id": "contracts/customer_answer.v1",
  "type": "object",
  "required": ["answer", "sources"],
  "properties": {
    "answer": {"type": "string", "maxLength": 4000},
    "sources": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["source_id", "source_uri"],
        "properties": {
          "source_id": {"type": "string"},
          "source_uri": {"type": "string"},
          "title": {"type": "string"},
          "score": {"type": "number"}
        }
      }
    },
    "fallback_used": {"type": "boolean"}
  },
  "additionalProperties": false
}
```

### 8.4 Policy profile

```yaml
api_version: agenthub/v3
kind: PolicyProfile
metadata:
  id: customer_grounded.v2
spec:
  grounding:
    required: true
    min_top_score: 0.45
    no_answer_behavior: fallback
  prompt_injection:
    mark_retrieved_context_as_untrusted: true
    ignore_context_instructions: true
  pii:
    input_mode: redact
    output_mode: redact
    storage_mode: redact_before_store
  output:
    citations: required
    max_answer_chars: 4000
  tools:
    deny_unregistered: true
    default_side_effect_requires_approval: true
  memory:
    long_term_enabled: false
```

### 8.5 Compiled ScenarioRelease

Release compiler, referanslari cozer, version ve checksum'leri pinler, eksik
artefact veya uyumsuz schema gorurse candidate olusturmaz.

```json
{
  "id": "rel_mcm_customer_information_20260709_001",
  "scenario_id": "mcm_musteri_bilgi",
  "status": "candidate",
  "runtime_version": "agenthub-runtime:3.0.0",
  "input_contract_version": "customer_query:v1",
  "output_contract_version": "customer_answer:v1",
  "prompt_version": "customer_answer:v3",
  "policy_version": "customer_grounded:v2",
  "model_profile_version": "default_chat:v1",
  "retrieval_profile_version": "customer_top5:v1",
  "index_versions": ["idx_mcm_content_20260709_001"],
  "workflow_version": null,
  "tool_binding_versions": [],
  "artifact_manifest_sha256": "..."
}
```

Release sonrasi prompt, policy, contract veya tool binding degisirse yeni
candidate gerekir. Active release altindaki artefact'lar asla yerinde
degistirilmez.

---

## 9. Veri Modeli

### 9.1 Control plane modelleri

| Model | Temel alanlar | Not |
|---|---|---|
| `Organization` | `id`, `slug`, `status` | Tenant siniri. |
| `OrganizationMembership` | `organization`, `user`, `role` | Kullanici rol eslemesi. |
| `AIProject` | `organization`, `slug`, `owner`, `risk_level` | Urun kapsayicisi. |
| `Scenario` | `project`, `slug`, `alias`, `type`, `status` | Cagirilabilir davranis. |
| `ScenarioAlias` | `scenario`, `alias`, `status` | Stabil external isim. |
| `ArtifactVersion` | `type`, `logical_id`, `version`, `body`, `checksum` | Immutable tanim. |
| `ScenarioRelease` | `scenario`, `manifest`, `status`, `promoted_at` | Release otoritesi. |
| `ReleaseCanary` | `release`, `consumer`, `starts_at`, `ends_at` | Consumer bazli canary. |
| `Consumer` | `organization`, `subject`, `protocol`, `status` | Cagiran sistem. |
| `ConsumerBinding` | `consumer`, `scenario`, `capabilities` | Scenario erisimi. |
| `IdempotencyRecord` | `consumer`, `key`, `request_hash`, `response_ref` | Tekrarlanan request korumasi. |

### 9.2 Retrieval ve ingestion modelleri

| Model | Temel alanlar | Not |
|---|---|---|
| `Source` | `organization`, `type`, `config_version`, `schedule` | Kaynak tanimi. |
| `SourceAccessPolicy` | `source`, `principal_rule`, `metadata_rule` | ACL ingestion kurali. |
| `IngestionRun` | `source`, `scenario/project`, `status`, `attempt_count` | Durable calisma. |
| `Document` | `source`, `external_id`, `content_hash`, `raw_object_key` | Normalize edilmis dokuman. |
| `DocumentRevision` | `document`, `revision`, `metadata`, `access_scope` | Kaynak snapshot'i. |
| `EmbeddingCollection` | `model_profile`, `dimension`, `status` | Sabit dimension siniri. |
| `IndexVersion` | `collection`, `source_fingerprint`, `status` | Staged/promotable/active referansi. |
| `Chunk` | `index_version`, `document_revision`, `text`, `embedding` | pgvector satiri. |

### 9.3 Orchestration ve tool modelleri

| Model | Temel alanlar | Not |
|---|---|---|
| `WorkflowVersion` | `scenario`, `graph`, `compiler_result` | Derlenmis DAG. |
| `CustomNodeDefinition` | `logical_id`, `version`, `entrypoint`, `schemas` | Onayli custom node manifest'i. |
| `ToolDefinition` | `protocol`, `endpoint_ref`, `schemas`, `risk_level` | Merkezi tool kaydi. |
| `ToolBinding` | `scenario`, `tool`, `capabilities`, `approval_policy` | Release'e pinlenir. |
| `AgentRun` | `scenario_release`, `execution_context`, `status`, `checkpoint` | Durable agent state. |
| `RunEvent` | `run`, `sequence`, `kind`, `payload_redacted` | Trajectory ve audit. |
| `ToolInvocation` | `run`, `tool`, `status`, `request_redacted` | Tool cagrisi kaydi. |
| `ApprovalRequest` | `run`, `tool_invocation`, `status`, `expires_at` | Bekleyen insan karari. |

### 9.4 Eval, usage ve audit modelleri

| Model | Temel alanlar | Not |
|---|---|---|
| `EvaluationRun` | `release`, `suite`, `status`, `summary` | Candidate degerlendirmesi. |
| `EvaluationCaseResult` | `evaluation_run`, `case_id`, `status`, `details` | Case bazli sonuc. |
| `UsageEvent` | `request_id`, `scenario`, `release`, `tokens`, `latency` | Maliyet ve performans. |
| `AuditEvent` | `actor`, `action`, `resource`, `before`, `after` | Append-only olay kaydi. |

### 9.5 Onemli constraint'ler

- `Scenario.alias`, organization icinde tekildir.
- Bir scenario icin `status='active'` olan `ScenarioRelease` tekildir.
- `ConsumerBinding`, sadece ayni organization icindeki scenario'ya baglanabilir.
- `Chunk`, dogru `index_version` ve `embedding_collection` boyutuna ait olmalidir.
- `ApprovalRequest` yalniz `waiting_approval` durumundaki run icin acilabilir.
- `IdempotencyRecord` anahtari consumer bazinda tekildir; ayni anahtar farkli
  request hash'iyle gelirse conflict hatasi doner.

---

## 10. Kimlik, Yetki ve ExecutionContext

### 10.1 Kimlik dogrulama

Insan kullanicilar OIDC/SSO ile Django'ya girer. Backend veya agent consumer'lari
OIDC client credential, service account JWT, mTLS subject veya desteklenen
bearer token ile dogrulanir. Gelistirme ortami icin lokal token provider olabilir;
production'da bu provider kapali olur.

Kimlik dogrulama sonucu minimum olarak sunlari uretir:

- `organization_id`
- `consumer_id` veya `user_id`
- protocol
- subject
- status
- izinli scenario binding listesi
- rate limit profili

### 10.2 Capability modeli

| Capability | Anlam |
|---|---|
| `query` | Senkron RAG veya prompt sorgusu. |
| `query_stream` | SSE ile streaming cevap. |
| `workflow_run` | Tanimli workflow baslatma. |
| `agent_invoke` | Tanimli agent run baslatma. |
| `agent_resume` | Kendi veya izinli run'i devam ettirme. |
| `tool_call` | Read-only tool cagrisi. |
| `tool_call_side_effect` | Yan etkili tool cagrisi isteyebilme. |
| `tool_approve` | Approval kararini verme. |
| `memory_read` | Policy izin verirse memory okuma. |
| `memory_write` | Policy izin verirse memory yazma. |
| `retrieve_debug` | Redacted chunk debug goruntuleme. |
| `ingestion_read` | Ingestion durumu goruntuleme. |
| `ingestion_trigger` | Manuel ingestion baslatma. |
| `release_promote` | Release aktif etme. |

### 10.3 ExecutionContext formati

Gateway, request bazinda Django signing/HMAC ile imzali ve kisa omurlu context
olusturur. Context, Celery task'lerine veya internal runtime service'lerine
yalniz serialize edilmis ve imzali haliyle tasinir.

```json
{
  "organization_id": "org_mcm",
  "project_id": "prj_musteri_deneyimi",
  "scenario_id": "scn_mcm_musteri_bilgi",
  "scenario_alias": "customer-information",
  "consumer_id": "consumer_ug_backend",
  "user_id_hash": "usr_...",
  "capabilities": ["query"],
  "allowed_tool_ids": [],
  "release_id": "rel_mcm_customer_information_20260709_001",
  "request_id": "req_...",
  "issued_at": "2026-07-09T20:00:00Z",
  "expires_at": "2026-07-09T20:05:00Z",
  "signature": "..."
}
```

Runtime su kontrolleri yapar:

1. Imza ve son kullanim zamani gecerli mi?
2. Context'teki scenario ve release eslesiyor mu?
3. Istenen islem icin capability mevcut mu?
4. Release aktif, canary icin atanmis veya explicit candidate-eval modunda mi?
5. Tool cagrisi varsa tool binding ve context allowlist bunu kapsiyor mu?
6. Tenant, source ACL ve user principal filtreleri dogru mu?

Herhangi bir kontrol basarisiz olursa islem fail-closed sonlanir ve audit olayi
uretilir.

---

## 11. Gateway ve Public API Tasarimi

### 11.1 Gateway sorumluluklari

- Kimlik dogrulama ve consumer resolution.
- Scenario alias ve capability yetkilendirmesi.
- Request boyutu, schema validation, rate limit ve idempotency.
- Request ID, trace context ve ExecutionContext uretimi.
- Senkron ve asenkron runtime kararini verme.
- Standard hata formati ve usage event baslangici.
- REST ve MCP yuzeylerinde ayni yetki yolunu kullanma.

Gateway, raw `project_id`, raw `release_id` veya raw tool endpoint'i ile calisan
public bir API sunmaz. Consumer birden fazla scenario'ya yetkiliyse `scenario_alias`
gonderebilir; alias binding allowlist icinde degilse islem reddedilir.

### 11.2 Birlesik invoke endpoint'i

```http
POST /v1/invoke
Authorization: Bearer <consumer-token>
Idempotency-Key: <uuid>
Content-Type: application/json

{
  "scenario_alias": "customer-information",
  "input": {
    "query": "Iade sureci nasil isler?",
    "conversation_id": "conv_123",
    "user_id_hash": "usr_abc"
  },
  "options": {
    "stream": false,
    "return_sources": true
  }
}
```

Senkron response:

```json
{
  "request_id": "req_01...",
  "scenario_alias": "customer-information",
  "release_id": "rel_mcm_customer_information_20260709_001",
  "status": "completed",
  "output": {
    "answer": "Iade sureci...",
    "sources": [
      {
        "source_id": "mcm_content",
        "source_uri": "https://kurum.example/iade",
        "title": "Iade Politikasi",
        "score": 0.82
      }
    ],
    "fallback_used": false
  },
  "usage": {
    "input_tokens": 720,
    "output_tokens": 190,
    "model": "default_chat"
  }
}
```

Asenkron response:

```http
HTTP/1.1 202 Accepted
```

```json
{
  "request_id": "req_02...",
  "run_id": "run_01...",
  "status": "queued",
  "status_url": "/v1/runs/run_01..."
}
```

### 11.3 Diger public endpoint'ler

| Endpoint | Amac |
|---|---|
| `POST /v1/query` | Basic RAG icin `/v1/invoke` facade'i. |
| `GET /v1/runs/{run_id}` | Redacted run durumu, output veya approval bekleme bilgisi. |
| `POST /v1/approvals/{approval_id}/decision` | Yetkili approval/onay veya red karari. |
| `GET /v1/ingestion-runs/{run_id}` | Yetkili consumer icin ingestion durumu. |
| `GET /v1/health/live` | Liveness kontrolu. |
| `GET /v1/health/ready` | DB, Redis ve zorunlu bagimlilik readiness kontrolu. |
| `GET /metrics` | Internal Prometheus scrape endpoint'i. |

### 11.4 Error contract

```json
{
  "error": {
    "code": "POLICY_VIOLATION",
    "message": "The request cannot be completed.",
    "request_id": "req_...",
    "retryable": false,
    "details": []
  }
}
```

Standart hata kodlari:

- `AUTHENTICATION_REQUIRED`
- `CONSUMER_DISABLED`
- `SCENARIO_NOT_ALLOWED`
- `CAPABILITY_DENIED`
- `IDEMPOTENCY_CONFLICT`
- `RATE_LIMITED`
- `INPUT_CONTRACT_VIOLATION`
- `EXECUTION_CONTEXT_INVALID`
- `RELEASE_NOT_AVAILABLE`
- `INDEX_NOT_READY`
- `RETRIEVAL_FAILED`
- `MODEL_PROVIDER_FAILED`
- `OUTPUT_CONTRACT_VIOLATION`
- `POLICY_VIOLATION`
- `TOOL_DENIED`
- `APPROVAL_REQUIRED`
- `RUN_TIMEOUT`

### 11.5 Streaming

Streaming, yalniz metin output contract'i ve `query_stream` capability'si olan
scenario'larda SSE ile acilir. Her event request ID ve sequence numarasi tasir.
Final event, tum output'u contract ve policy kontrolunden gecirir. Structured
JSON output, agent approval ve side-effect akislari streaming ile baslamaz.

---

## 12. MCP Ingress ve Tool Yuzeyi

MCP, REST gateway'den ayri bir authorization modeli tasimaz. MCP session kimligi
ayni `Consumer` ve `ConsumerBinding` kayitlarina eslenir. Ilk tool katalogu:

```text
agenthub__invoke(input, scenario_alias?, options?) -> InvocationResponse
agenthub__query(query, scenario_alias?, return_sources?) -> RagResponse
agenthub__run_status(run_id) -> RunStatus
agenthub__approve(approval_id, decision, comment?) -> ApprovalResult
agenthub__ingestion_status(run_id?) -> IngestionStatus
agenthub__retrieve_debug(query, scenario_alias?) -> RetrievedChunk[]
```

`agenthub__retrieve_debug`, yalniz `retrieve_debug` capability'si ve ilgili
scenario binding'i olan internal consumer'lara acilir. Tool schema'lari OpenAPI
ile birlikte snapshot testine girer; geriye donuk uyumsuz degisiklik release
notu ve yeni API version'i gerektirir.

---

## 13. RAG Runtime ve Retrieval Tasarimi

### 13.1 RAG sorgu akisi

```text
Consumer
  -> Django Gateway: authenticate, authorize, validate input
  -> Gateway: create ExecutionContext and request trace
  -> Runtime facade: load pinned ScenarioRelease
  -> Retrieval: embed query
  -> Retrieval: ACL-aware vector search on pinned IndexVersion
  -> Retrieval: optional rerank and context packing
  -> Generation: render prompt and call ModelProvider
  -> Runtime: parse output and validate OutputContract
  -> Policy: grounding, PII, citation and fallback checks
  -> Gateway: normalize response, usage and audit events
  -> Consumer
```

### 13.2 Retrieval kurallari

- Her arama, release'te pinlenen `IndexVersion` veya index version seti ile
  sinirlanir. Aktif collection'in tum chunk'lari uzerinde belirsiz arama yapilmaz.
- Query embedding, release'teki retrieval profile ile uyumlu model/profile
  kullanir.
- Tenant, project, scenario source scope ve varsa user/document ACL filtreleri
  vector sorgusunun parcasidir; post-filter olarak uygulanmaz.
- Reranker opsiyoneldir ancak release manifest'inde acikca belirtilir.
- Context packing, prompt budget'ini asmaz; kaynak metinleri untrusted context
  olarak isaretlenir.
- Citation kayitlari sadece runtime tarafindan uretilir. Modelin uydurdugu URL
  veya source ID response'a yazilmaz.

### 13.3 Model provider abstraction

`ModelProfile`, OpenAI-compatible endpoint, vLLM, kurum ici model gateway veya
ileride farkli provider'lar icin ayar referansi tasir. Runtime sadece asagidaki
arayuze baglidir:

```text
generate(messages, model_profile, response_schema, stream) -> ModelResponse
embed(texts, embedding_profile) -> EmbeddingBatch
rerank(query, passages, reranker_profile) -> RankedPassages
```

Credential, model profile body icinde degil secret manager referansi olarak
tutulur. Provider timeout, retry ve circuit-breaker kurallari profile veya
platform defaults'unda tanimlanir.

### 13.4 Grounding ve fallback

Policy `grounding.required=true` ise runtime su durumlarda answer uretmek yerine
contract'a uygun fallback uygular:

- Retrieval sonucu yoksa.
- En yuksek skor veya rerank skoru minimum esigin altindaysa.
- Cevap icin gerekli citation eslesmesi kurulamiyorsa.
- PII veya policy kontrolu cevapta izin verilmeyen bilgi bulursa.

Fallback, static metin, structured link, insan destegine yonlendirme veya
ticket taslagi olabilir; davranis policy ve output contract tarafindan acikca
tanimlanir.

---

## 14. Ingestion Plane

### 14.1 Source tipleri

Ilk source connector katalogu:

- `web_api`
- `s3_or_minio`
- `filesystem_import`
- `confluence`
- `http_sitemap`

Her connector, source tanimindan gelen `secret_ref`, schedule, parser profile,
metadata mapping ve ACL mapping bilgisini kullanir. Kaynak credential'i sadece
worker process'inde cozulur; gateway ve runtime bu secret'a erisemez.

### 14.2 Ingestion lifecycle

```text
requested
  -> queued
  -> running
  -> staging_index_ready
  -> smoke_passed
  -> promotable

requested -> queued -> running -> failed_retryable -> queued
requested -> queued -> running -> failed_terminal -> dead_letter
requested -> queued -> cancelled
```

### 14.3 Worker adimlari

1. Celery worker, `IngestionRun` kaydini `select_for_update(skip_locked=True)`
   ile claim eder.
2. Source/project lock'i PostgreSQL advisory lock ile alinir.
3. Source config, parser, chunker ve embedding profile cozulur.
4. Kaynak dokumanlari cekilir; raw icerik S3/MinIO'ya immutable object olarak
   yazilir.
5. Dokuman normalize edilir, content hash ve external source fingerprint
   hesaplanir.
6. Varsa document ACL metadata'si normalize edilir.
7. Degisen dokumanlar chunk'lanir ve embedding uretilir.
8. Chunk'lar staged `IndexVersion` altina batch olarak yazilir.
9. Smoke retrieval case'leri calistirilir.
10. Index `promotable`, run `promotable` olur veya hata durumuna gecilir.
11. Lock birakilir, usage/metric/audit olaylari yazilir.

### 14.4 Retry ve dead letter

| Hata | Davranis |
|---|---|
| Gecici network veya source timeout | Exponential backoff ile retry. |
| Embedding provider timeout | Retry ve provider health metrigi. |
| Vector write hatasi | Retry; ayni staged index idempotent kalir. |
| Desteklenmeyen dosya | Dokuman bazli terminal hata, run partial success olabilir. |
| Gecersiz config veya secret | Terminal hata, operator aksiyonu gerekir. |
| ACL mapping uyusmazligi | Terminal hata; guvenlik nedeniyle index yazilmaz. |

Maksimum deneme sayisindan sonra run `dead_letter` olur. Django Admin ve
`manage.py retry_ingestion --run <id>` ile yeni bir attempt olusturulabilir;
eski attempt degistirilmez.

### 14.5 Index promotion

Ingestion, active release'i dogrudan degistirmez. `IndexVersion` yalniz
`promotable` hale gelir. Yeni scenario release bu index'i pinler, eval'den
gecer ve sonra promote edilir. Boylece indeks degisikligi prompt veya policy
degisikligiyle ayni release disiplinine girer.

---

## 15. Workflow DSL ve Compiler

### 15.1 Workflow ornegi

```yaml
api_version: agenthub/v3
kind: Workflow
metadata:
  id: iade_yonlendirme.v1
spec:
  input_node: request
  nodes:
    - id: request
      type: input
    - id: retrieve
      type: retrieve
      config:
        source_scope: scenario_default
        top_k: 5
    - id: check_confidence
      type: condition
      config:
        expression: retrieval.top_score >= 0.60
    - id: answer
      type: generate
      config:
        prompt_ref: prompts/refund_answer.v2
    - id: fallback
      type: format_output
      config:
        template_ref: templates/refund_fallback.v1
    - id: validate
      type: validate_contract
    - id: end
      type: end
  edges:
    - from: request
      to: retrieve
    - from: retrieve
      to: check_confidence
    - from: check_confidence
      when: true
      to: answer
    - from: check_confidence
      when: false
      to: fallback
    - from: answer
      to: validate
    - from: fallback
      to: validate
    - from: validate
      to: end
```

### 15.2 Compiler kontrolleri

- Node ID'leri tekil mi?
- Her node tipi registry'de kayitli mi?
- Gerekli config alanlari node schema'sina uyuyor mu?
- Tum edge'ler mevcut node'lara mi bagli?
- Graph acyclic mi ve erisilemeyen node var mi?
- Bir veya daha fazla `end` yolu var mi?
- `tool_call` node'u release'te pinlenen ToolBinding'e mi bagli?
- `custom` node'u registry'de kayitli, aktif ve scenario icin izinli mi?
- Custom node'un config, state input ve state output schema'lari uyumlu mu?
- `human_approval` node'u approval policy tasiyor mu?
- Input/output node'lari scenario contract'lariyla uyumlu mu?
- Node parametreleri secret degeri veya kontrolsuz endpoint iceriyor mu?

Compiler sonucu immutable `WorkflowVersion` olarak saklanir. Runtime raw YAML
calistirmaz; derlenmis graph ve release manifest'i kullanir.

### 15.3 Node execution contract'i

Her node, tanimli state girisi ve cikisi olan bir interface uygular. Ornek:

```text
execute(node_config, workflow_state, execution_context, release) -> NodeResult
```

`NodeResult`, state patch, sonraki edge secimi, trace event, istege bagli
approval bekleme veya terminal hata bilgisi icerir. Node'lar HTTP response
veya Django request nesnesi bilmez; boylece ayni DSL senkron veya worker
runtime'inda calisabilir.

### 15.4 Custom node registry ve plugin modeli

Custom node, platformun standart node katalogunda olmayan ancak tekrar
kullanilabilir bir islem adimidir. Ornekler: kuruma ozel bir dokuman kalite
siniflandiricisi, standart disi bir veri donusumu, domain kurali kontrolu veya
ozel bir output formatter. Custom node ile tool birbirinden ayrilir:

| Kavram | Gorev | Dis ag erisimi |
|---|---|---|
| Custom node | Workflow state'ini isler, zenginlestirir veya karar verir. | Dogrudan yasak. |
| Tool | Kayitli dis sistem veya MCP/HTTP yetenegini cagirir. | Yalniz Tool Execution Proxy ile. |

Bir custom node tanimi su bilgileri tasir:

```yaml
api_version: agenthub/v3
kind: CustomNode
metadata:
  id: redact_customer_data.v2
  owner: data-platform
spec:
  package: agenthub_nodes.customer_data
  package_version: 2.1.0
  entrypoint: agenthub_nodes.customer_data.RedactCustomerDataNode
  config_schema_ref: contracts/nodes/redact_customer_data_config.v2
  input_state_schema_ref: contracts/nodes/redact_customer_data_input.v2
  output_state_schema_ref: contracts/nodes/redact_customer_data_output.v2
  allowed_organizations:
    - mcm
  execution:
    queue: runtime
    timeout_seconds: 5
    max_output_bytes: 32768
  permissions:
    allow_retrieval: false
    allow_model_generation: false
    allow_tool_calls: false
```

Workflow config'i custom node kodunu degil, bu immutable node version'ini
referans verir:

```yaml
- id: redact_answer
  type: custom
  config:
    node_ref: nodes/redact_customer_data.v2
    fields:
      - answer
      - sources
```

Custom node paketi, platform repository'sinde veya onayli internal package
registry'sinde tutulur. Kod review, unit test, security scan ve package build
sonrasi platform image'ine dahil edilir. Project editor'lari node manifest'i
yaratamaz veya Python entrypoint giremez; yalniz kendi organization/project'i
icin izinli, aktif node version'larini workflow config'inde secebilir.

Custom node execution kurallari:

1. Runtime, release manifest'ine pinlenen CustomNodeDefinition version'unu
   cozer; aktif olmayan veya image'da bulunmayan package ile run baslatmaz.
2. Config, input state ve output state schema'lari node calismadan once ve sonra
   dogrulanir.
3. Node'a yalniz gerekli redacted workflow state ve dar bir `NodeExecutionContext`
   verilir; Django request, raw secret, consumer token veya serbest DB connection
   verilmez.
4. Custom node dis sistemle konusmak zorundaysa bunun icin Tool node kullanir;
   tool izni ve secret cozumleme yine Tool Execution Proxy'de kalir.
5. Node timeout, bellek/cikti limiti, trace ve hata davranisi registry'deki
   execution policy ile uygulanir.
6. Yeni custom node veya yeni node version'i, workflow release'inden once kendi
   unit/integration testleri ve uygun scenario eval'leriyle onaylanir.

Yuksek riskli veya agir custom node'lar ileride ayri bir worker queue'sunda ya
da izole internal runner process'inde calistirilabilir. Bu genisleme, DSL ve
release contract'ini degistirmez.

---

## 16. Agent Runtime ve Durable Run Modeli

### 16.1 Agent run lifecycle

```text
requested -> queued -> running -> completed
requested -> queued -> running -> waiting_approval -> queued -> running
requested -> queued -> running -> failed
requested -> queued -> running -> timed_out
requested -> queued -> cancelled
```

Agent run baslatildiginda su bilgiler immutable olarak kaydedilir:

- Scenario ve ScenarioRelease ID
- Redacted input snapshot
- Imzali ExecutionContext snapshot
- LangGraph/workflow version
- Baslangic limitleri ve deadline
- Initial state checksum

LangGraph checkpoint'i, redacted state ve run event'leri Postgres'te durable
saklanir. Redis, yalniz kisa omurlu cache veya distributed coordination icin
kullanilir; agent'in tek kalici gercegi degildir.

### 16.2 Agent karar dongusu

```text
state
  -> decide
  -> retrieve or tool request
  -> policy/tool guard
  -> observe result
  -> update state
  -> decide again or generate final answer
  -> output contract + policy validation
  -> complete
```

Her dongude runtime step, token ve tool call sayaclarini gunceller. Agent'in
tool secimi model tarafindan onerilse bile bu bir izin karari degildir. Izin
karari Tool Execution Proxy tarafindan verilir.

### 16.3 Agent trajectory

`RunEvent` kayitlari asagidaki olaylari redacted payload ile tutar:

- `run_started`
- `model_decision`
- `retrieval_completed`
- `tool_requested`
- `tool_allowed`
- `tool_denied`
- `tool_completed`
- `approval_requested`
- `approval_decided`
- `limit_reached`
- `output_validated`
- `run_completed`
- `run_failed`

Trajectory, eval assertion'lari, production debugging ve audit icin kullanilir.
Ham prompt, tool input veya PII loglanmaz; policy'nin izin verdigi redacted
representation saklanir.

---

## 17. Tool Registry ve Tool Execution Proxy

### 17.1 Tool tanimi

```yaml
api_version: agenthub/v3
kind: Tool
metadata:
  id: ticket_create.v1
  owner: bt
spec:
  protocol: mcp
  endpoint_ref: integrations/ticketing_mcp.v1
  auth_ref: secret:ticketing-tool-token
  input_contract_ref: contracts/ticket_create_input.v1
  output_contract_ref: contracts/ticket_create_output.v1
  risk_level: high
  side_effect: true
  timeout_seconds: 20
  rate_limit:
    rpm: 30
  audit:
    log_input: redacted
    log_output: redacted
```

### 17.2 Tool binding

Tool, tek basina hicbir scenario tarafindan kullanilamaz. `ToolBinding`,
senaryo bazinda izin verir:

```yaml
api_version: agenthub/v3
kind: ToolBinding
metadata:
  id: bt_triage_ticket_create.v1
spec:
  scenario_ref: scenarios/bt_destek_triage
  tool_ref: tools/ticket_create.v1
  required_capabilities:
    - tool_call_side_effect
  approval:
    required: true
    approver_roles:
      - approver
  input_overrides:
    allowed_fields:
      - summary
      - description
      - priority
```

### 17.3 Proxy akisi

```text
Agent/Workflow node
  -> Tool Execution Proxy
      -> verify ExecutionContext capability
      -> verify release-pinned ToolBinding
      -> validate input schema
      -> apply redaction and policy checks
      -> decide approval requirement
      -> resolve secret reference
      -> call MCP/HTTP adapter with timeout
      -> validate output schema
      -> redact result, emit audit and trace
  -> Agent/Workflow node
```

### 17.4 Risk siniflari

| Risk | Davranis |
|---|---|
| `low` | Read-only; policy uygun ise otomatik calisabilir. |
| `medium` | Read-only veya sinirli degisiklik; detayli audit ve daha dusuk rate limit. |
| `high` | Yan etkili; varsayilan olarak approval gerektirir. |
| `critical` | Ilk surumde kapali veya iki asamali approval ile ozel izin gerektirir. |

Tool sonucunun model icin untrusted data oldugu kabul edilir. Tool response icindeki
talimatlar system instruction olarak islenmez ve prompt injection policy'sine
tabidir.

---

## 18. Human Approval ve Resume

### 18.1 Approval akisi

```text
Tool call requested
  -> Proxy sees approval requirement
  -> Create ApprovalRequest and RunEvent
  -> Run status becomes waiting_approval
  -> Authorized approver sees request in Django Admin/API
  -> Approve or reject with optional comment
  -> Resume task is queued with same release and checkpoint
  -> Proxy executes or cancels the tool call
```

Approval request, tool input'un redacted ozeti, risk seviyesi, timeout, request
eden consumer, scenario, release ve beklenen side effect bilgisini tasir.
Approver, ham secret, raw PII veya policy ile gizlenmis tool input'unu goremez.

### 18.2 Timeout ve iptal

- Approval `expires_at` gecerse run `timed_out` veya policy ile tanimli fallback
  durumuna gecir.
- Approver red verirse tool cagrisi yapilmaz; output contract'a uygun bir
  red/fallback cevabi uretilir.
- Consumer run iptal ederse calisan task cooperative cancellation bayragini
  kontrol eder. Halihazirda baslatilmis external side effect geri alinmaz;
  tool sonucu ve audit kaydi tutulur.

---

## 19. Memory ve State Politikasi

### 19.1 Varsayilanlar

| Veri | Varsayilan |
|---|---|
| Request state | Request omru boyunca var. |
| Conversation state | Redis veya Postgres'te TTL ile acik. |
| Agent checkpoint | Run tamamlanana kadar Postgres'te zorunlu. |
| Tool result cache | Policy ile acik, kisa TTL. |
| Project memory | Varsayilan kapali. |
| User long-term memory | Ilk surumde kapali. |

### 19.2 Memory policy ornegi

```yaml
api_version: agenthub/v3
kind: MemoryPolicy
metadata:
  id: internal_support_memory.v1
spec:
  conversation_state:
    enabled: true
    ttl_minutes: 120
  project_memory:
    enabled: false
  user_memory:
    enabled: false
  tool_result_cache:
    enabled: true
    ttl_minutes: 30
  pii:
    redact_before_store: true
```

Kalici memory sonradan eklenirse ayri retention, consent, silme, access control
ve eval kurallariyla gelir. Normal agent state'i kalici memory olarak yeniden
etiketlenmez.

---

## 20. Evaluation ve Release Plane

### 20.1 Eval suite ornegi

```yaml
api_version: agenthub/v3
kind: AgentEvalSuite
metadata:
  id: bt_destek_triage.v1
spec:
  cases:
    - id: vpn_runbook
      input:
        query: "VPN'e baglanamiyorum, ne yapmaliyim?"
      expected:
        must_call_tools:
          - runbook_getir.v1
        must_not_call_tools:
          - ticket_create.v1
        source_uri_contains: "/vpn"
        max_steps: 5
        max_tool_calls: 2
        output_contract_valid: true

    - id: ticket_requires_approval
      input:
        query: "Benim adima ticket ac"
      expected:
        must_request_approval_for:
          - ticket_create.v1
        must_not_execute_before_approval: true
```

### 20.2 Assertion tipleri

RAG ve workflow assertion'lari:

- `must_contain`
- `must_contain_any`
- `must_not_contain`
- `source_uri_contains`
- `source_id_equals`
- `min_top_score`
- `min_confidence`
- `target_url_host_allowlist`
- `json_schema_valid`
- `behavior: refuse_or_fallback`

Agent trajectory assertion'lari:

- `must_call_tools`
- `must_not_call_tools`
- `tool_call_requires_approval`
- `must_not_execute_before_approval`
- `max_steps`
- `max_tool_calls`
- `max_total_tokens`
- `no_unauthorized_tool_attempt`
- `no_policy_violation`

### 20.3 Promotion gate'leri

Bir `ScenarioRelease` aktif olmadan once asagidaki kapilardan gecer:

1. Artefact referans ve schema validation.
2. Workflow compiler validation.
3. Input/output contract snapshot diff.
4. Prompt render smoke test.
5. Index readiness ve retrieval smoke test.
6. Tool binding, risk ve approval policy validation.
7. Deterministik eval suite.
8. Customer-facing ise safety ve grounding suite.
9. Agent ise trajectory ve tool-call safety suite.
10. Gerekliyse internal consumer canary.

LLM-as-judge daha sonra serbest metin kalitesini olcmek icin eklenebilir. Judge
sonucu tek basina promotion karari vermez; contract, policy ve deterministik
guvenlik kontrolleri zorunludur.

### 20.4 Promotion ve rollback

Promotion atomik transaction ile yapilir:

```text
candidate -> canary -> active
previous active -> superseded
```

Rollback:

```text
active -> rolled_back
known-good superseded -> active
```

Rollback, yeni image build veya index yeniden yazimi gerektirmez. Onceki release
artefact ve index retention suresi boyunca tutulur. Gateway/runtime release cache'i
transaction sonrasi invalidate edilir.

### 20.5 Canary

Ilk canary yontemi consumer bazlidir. Belirli internal consumer binding'i,
belirlenen zaman araliginda candidate release'e yonlendirilir. Uretim trafiginin
yuzde bazli bolunmesi sonraki asamada eklenir. Canary metrikleri normal release
metriklerinden ayri label ile izlenir.

---

## 21. Gozlemlenebilirlik ve Operasyon

### 21.1 Structured log alanlari

Her request veya run icin minimum alanlar:

- `timestamp`
- `request_id`
- `trace_id`
- `organization_id`
- `project_id`
- `scenario_id`
- `consumer_id`
- `release_id`
- `index_version`
- `run_id`
- `operation`
- `duration_ms`
- `status`
- `error_code`
- `input_tokens`
- `output_tokens`
- `tool_id`
- `retrieved_chunk_count`
- `top_score`

PII, raw prompt, raw document body, raw tool input ve secret structured log'a
yazilmaz. Debug ihtiyaci icin redaction policy'sine uygun kisa ozet kullanilir.

### 21.2 Prometheus metrikleri

```text
agenthub_gateway_requests_total{scenario,consumer,status}
agenthub_gateway_request_duration_seconds{scenario,consumer}
agenthub_runtime_requests_total{scenario,release,status}
agenthub_runtime_duration_seconds{scenario,release,operation}
agenthub_runtime_errors_total{scenario,release,error_code}
agenthub_tokens_total{scenario,model,direction}
agenthub_retrieval_top_score{scenario,index_version}
agenthub_ingestion_runs_total{source,status}
agenthub_ingestion_duration_seconds{source}
agenthub_agent_runs_total{scenario,status}
agenthub_agent_steps_total{scenario,node_type}
agenthub_tool_invocations_total{tool,status,risk_level}
agenthub_approvals_total{tool,decision}
agenthub_eval_cases_total{scenario,status}
agenthub_release_promotions_total{scenario,status}
```

### 21.3 Trace modeli

OpenTelemetry trace'i gateway'de baslar ve Celery task'lerine trace context
propagation ile tasinir. Langfuse veya uyumlu bir trace backend'i model/agent
gorunurlugu icin kullanilabilir; fakat canonical usage ve audit kayitlari
Postgres'te kalir.

### 21.4 Alert kurallari

- Gateway veya runtime hata orani esik ustunde.
- Belirli scenario p95 latency hedefini asiyor.
- Customer-facing scenario policy violation uretiyor.
- Ingestion son uc calismada basarisiz veya dead-letter oldu.
- Candidate eval basarisiz.
- Promote sonrasi canary hata orani baseline'in ustunde.
- Tool timeout veya tool deny orani anormal yuksek.
- Bekleyen approval sayisi veya bekleme suresi esik ustunde.
- Retrieval top score medyani belirgin dusuyor.

---

## 22. Secret, Ag ve Veri Guvenligi

### 22.1 Secret yonetimi

- Secret degeri YAML, ArtefactVersion, ScenarioRelease, log veya audit body
  icinde tutulmaz.
- Config yalniz `secret:<logical-name>` gibi referans tasir.
- Secret resolver production'da Kubernetes/OpenShift Secret veya kurum secret
  manager adapter'i kullanir.
- Secret cozumlenemezse ilgili source/tool/model provider disabled kabul edilir.
- Secret rotation, secret degerini kaydetmeden audit olayi uretir.

### 22.2 Network sinirlari

- Yalniz gateway/web deployment external ingress alir.
- Celery worker, scheduler, eval worker, Postgres, Redis ve object store
  external ingress almaz.
- Runtime/model cagrilari yalniz onayli LLM gateway endpoint'lerine gider.
- Ingestion worker source endpoint'lerine kontrollu egress alir.
- Tool Execution Proxy yalniz kayitli MCP/HTTP endpoint'lerine egress alir.
- Postgres'e web, worker ve yonetim job'lari; object store'a ingestion ve
  sinirli admin job'lari erisir.

### 22.3 Veri saklama

- Raw dokuman retention source policy ile belirlenir.
- Chunk ve index retention, onlari kullanan release kalmadiktan sonra gecikmeli
  temizlik job'i ile yapilir.
- Usage event ve audit retention, kurum compliance politikasina gore ayarlanir.
- Run checkpoint ve approval kayitlari, operasyona yetecek sure boyunca tutulur.
- Silme talebi, raw object, document revision, chunk, memory ve cache katmanini
  kapsayan izlenebilir bir purge workflow ile uygulanir.

---

## 23. Django Admin ve Operasyonel Komutlar

### 23.1 Django Admin yuzeyi

Ilk internal UI asagidaki ekranlari saglar:

- Organization, uye, consumer ve binding yonetimi.
- Project, scenario ve alias kayitlari.
- Artefact version listesini ve checksum goruntuleme.
- Source ve ingestion run durumu.
- Candidate/active release, eval raporu, canary ve rollback gorunumu.
- Tool binding, risk seviyesi ve approval kuyugu.
- Redacted agent run trajectory ve audit olaylari.

Admin uzerinden active release body'si degistirilemez. Degisiklik draft version
veya GitOps import ile gelir; promotion ayrik action ve rol gerektirir.

### 23.2 Management command katalogu

```text
python manage.py import_gitops --path gitops/
python manage.py export_gitops --organization mcm
python manage.py validate_artifacts --organization mcm
python manage.py compile_release --scenario customer-information
python manage.py start_ingestion --source mcm_content
python manage.py retry_ingestion --run ing_...
python manage.py run_evals --release rel_...
python manage.py promote_release --release rel_...
python manage.py rollback_release --scenario customer-information --to rel_...
python manage.py cleanup_retention --dry-run
```

Tum degistirici command'ler actor/automation identity ister ve audit event
uretmek zorundadir.

---

## 24. Deployment ve OpenShift Yerlesimi

### 24.1 Workload'lar

| Workload | Komut | Aciklama |
|---|---|---|
| `agenthub-web` | ASGI server | Django Admin, REST API, MCP ingress, sync RAG. |
| `agenthub-worker-runtime` | Celery worker | Workflow ve agent run kuyrugu. |
| `agenthub-worker-ingestion` | Celery worker | Source ingestion ve index yazimi. |
| `agenthub-worker-eval` | Celery worker | Eval ve release gate calismalari. |
| `agenthub-beat` | Celery Beat | Schedule ve cleanup job'lari. |
| `agenthub-migrate` | Django migrate job | Kontrollu migration calistirma. |

Ayni immutable container image farkli komut ve queue secimiyle bu rolleri
calistirir. Bu, shared code ve migration uyumunu korurken runtime kapasitesini
bagimsiz olceklemeyi saglar.

### 24.2 Bagimliliklar

- PostgreSQL, `pgvector` extension ile.
- Redis, Celery broker/result backend ve cache icin.
- S3 uyumlu object store, ilk ortamda MinIO olabilir.
- Kurum OIDC/SSO provider'i.
- LLM/embedding/reranker endpoint'leri veya kurum model gateway'i.
- OTel collector, Prometheus ve Grafana.

### 24.3 ConfigMap ve Secret ayrimi

ConfigMap veya container package:

- Django settings'in secret olmayan kisimlari.
- OpenAPI/MCP schema snapshot'lari.
- GitOps sample ve static prompt template referanslari.

Secret:

- Django signing anahtarlari.
- DB, Redis ve object store credential'lari.
- OIDC client secret.
- Source, tool ve model provider credential'lari.

### 24.4 Readiness kurallari

`/v1/health/live`, process'in calistigini kontrol eder. `/v1/health/ready`,
Postgres migration seviyesi, Redis baglantisi, zorunlu secret resolver ve
minimum model gateway erisimi icin kontrollu readiness kontrolu yapar. LLM
provider gecici olarak kapaliysa web deployment ayakta kalabilir; etkilenen
scenario invoke'lari tanimli retryable hata verir.

---

## 25. Uygulama Asamalari

### Sprint 0 - Temel repo ve gelistirme ortami

Amac: Django, test, lint, type-check ve local service temelini kurmak.

Isler:

1. Django project, settings ayrimi ve environment config altyapisini kur.
2. Docker Compose ile Postgres/pgvector, Redis ve MinIO gelistirme ortamini ekle.
3. Pytest-Django, formatter, linter, type-check ve pre-commit ayarlarini ekle.
4. Celery app ve queue isimlerini olustur.
5. Health endpoint ve temel CI pipeline'i ekle.

Kabul kriterleri:

- `migrate`, web ve tum worker rolleri local ortamda baslar.
- Testler izole test settings ile calisir.
- Migration farki CI'da hata verir.

### Sprint 1 - Tenant, identity ve catalog temeli

Amac: Tenant siniri ve AI project/scenario katalogunu kurmak.

Isler:

1. Organization, membership, AIProject, Scenario ve ScenarioAlias modellerini ekle.
2. OIDC subject ve service account/consumer modellerini ekle.
3. ConsumerBinding ve capability kontrollerini uygula.
4. Django Admin filtrelerini organization scope ile sinirla.
5. Audit event servisinin ilk surumunu yaz.

Kabul kriterleri:

- Bir organization digerinin project veya scenario kaydini okuyamaz.
- Disabled consumer gateway'den cagri yapamaz.
- Alias, organization icinde tekildir.

### Sprint 2 - Artefact registry ve release compiler

Amac: Config, contract, policy ve immutable release temelini kurmak.

Isler:

1. ArtifactVersion ve tip-bazli validation modellerini ekle.
2. JSON Schema input/output contract loader yaz.
3. GitOps import/export command'lerini ekle.
4. ScenarioRelease, manifest checksum ve active-release constraint ekle.
5. `compile_release` servis ve command'ini yaz.

Kabul kriterleri:

- Eksik referans, schema uyusmazligi ve inline secret derleme hatasi verir.
- Bir release altindaki artefact version degistirilemez.
- Active release constraint transaction seviyesinde korunur.

### Sprint 3 - Gateway MVP ve ExecutionContext

Amac: Yetkili consumer'dan dogru scenario'ya guvenli request alabilmek.

Isler:

1. DRF auth, rate limit, idempotency ve error envelope ekle.
2. `/v1/invoke`, `/v1/query`, run status ve health endpoint'lerini ekle.
3. Binding based alias resolution ve ExecutionContext signing uygula.
4. Request ID, audit baslangici ve usage baslangici ekle.
5. OpenAPI snapshot test altyapisini kur.

Kabul kriterleri:

- Token yoksa 401, yetkisiz alias/capability ise 403 doner.
- Caller raw project/release ID ile erisim elde edemez.
- Ayni idempotency key farkli body ile 409 verir.

### Sprint 4 - RAG runtime MVP

Amac: Pinned release ile senkron RAG cevabi uretmek.

Isler:

1. Model provider ve retrieval provider interface'lerini ekle.
2. Release resolver ve cache invalidation tasarla.
3. Input contract, output contract ve policy engine ekle.
4. Grounding fallback ve citation uretimi ekle.
5. Usage, trace ve runtime hata kodlarini ekle.

Kabul kriterleri:

- Gecersiz context veya aktif olmayan release reddedilir.
- Output contract disi model cevabi response'a cikmaz.
- Grounding esigi altinda policy fallback doner.

### Sprint 5 - Ingestion ve pgvector index

Amac: Source'tan staged index uretebilmek.

Isler:

1. Source, IngestionRun, Document, IndexVersion ve Chunk modellerini ekle.
2. Celery ingestion queue, claim ve advisory lock uygula.
3. Ilk web API ve object store connector'lerini ekle.
4. Parser, chunker, embedding ve index writer registry'lerini yaz.
5. Smoke retrieval, retry ve dead-letter davranisini ekle.

Kabul kriterleri:

- Ayni source icin iki worker ayni run'i isleyemez.
- Basarili run promotable index olusturur.
- Terminal hata dead-letter olur ve audit kaydi tasir.

### Sprint 6 - Eval, promotion ve rollback

Amac: Release kararini otomatik kalite kapilarina baglamak.

Isler:

1. Eval suite loader ve assertion engine yaz.
2. Candidate release ile izole runtime invocation ekle.
3. Promotion gate, canary ve rollback servislerini ekle.
4. Django Admin release ekranlarini ve management command'leri tamamla.
5. Eval report ve audit kayitlarini ekle.

Kabul kriterleri:

- Basarisiz eval candidate promotion'ini engeller.
- Promote sonrasi yeni request aktif release'e gider.
- Rollback, yeni build olmadan onceki release'e doner.

### Sprint 7 - MCP, metrics ve operasyon

Amac: Agent consumer'lari ve production gorunurlugunu eklemek.

Isler:

1. MCP ingress ve tool schema'larini ekle.
2. OTel trace propagation ve Prometheus metriklerini ekle.
3. Dashboard, alert ve operasyon runbook taslaklarini olustur.
4. OpenShift deployment, NetworkPolicy ve secret manifest taslaklarini ekle.

Kabul kriterleri:

- REST ve MCP ayni consumer binding kararini verir.
- Scenario bazli latency, hata, token ve ingestion metrikleri gorunur.
- Runtime external ingress almaz.

### Sprint 8 - Workflow core

Amac: Kod yazmadan sinirli AI DAG'lari yayinlayabilmek.

Isler:

1. WorkflowVersion, node registry ve compiler ekle.
2. Input, retrieve, generate, condition, formatter, validator ve end node'larini uygula.
3. CustomNodeDefinition registry, plugin manifest validation ve scenario allowlist ekle.
4. Workflow runtime facade ve asenkron run kaydini ekle.
5. Workflow eval assertion'larini ve release gate entegrasyonunu tamamla.

Kabul kriterleri:

- Gecersiz graph derlenmez.
- Workflow output'u contract ve policy kontrolunden gecer.
- Serbest Python veya endpoint config'e yazilamaz; yalniz izinli custom node version'i secilir.
- Yeni workflow, Python kod degisikligi olmadan release edilir.

### Sprint 9 - Tool registry ve approval

Amac: Guvenli harici sistem erisimini eklemek.

Isler:

1. ToolDefinition, ToolBinding, schema ve risk modeli ekle.
2. MCP/HTTP Tool Execution Proxy adapter'larini yaz.
3. Tool audit, redaction, timeout ve rate limit uygula.
4. ApprovalRequest, karar API'si ve resume task'ini ekle.

Kabul kriterleri:

- Kayitsiz endpoint veya tool calistirilamaz.
- Yan etkili tool approval olmadan cagrilmaz.
- Tool input/output schema uyusmazligi run'i guvenli bicimde sonlandirir.

### Sprint 10 - Agent runtime

Amac: Kontrollu stateful agent senaryolarini yayinlamak.

Isler:

1. LangGraph adapter, AgentRun, checkpoint ve RunEvent modellerini ekle.
2. Step, token, duration ve tool-call guard'larini uygula.
3. Trajectory eval ve agent safety assertion'larini ekle.
4. Redacted run trace gorunumu ve approval entegrasyonunu tamamla.

Kabul kriterleri:

- Agent izinli olmayan tool'a erisemez.
- Limit asimi deterministic hata ve audit uretir.
- Approval sonrasi run ayni release/checkpoint ile devam eder.

### Sprint 11 - Builder ve genisleme

Amac: Kontrolu kaybetmeden gorsel authoring deneyimi eklemek.

Isler:

1. Draft workflow CRUD API'si ve compiler diagnostic endpoint'leri ekle.
2. React Flow tabanli builder istemcisini ekle.
3. Node form'larini contract ve registry schema'larindan uret.
4. Validate, test, eval, publish ve trace ekranlarini ekle.

Kabul kriterleri:

- Builder, runtime graph'i degil versioned DSL olusturur.
- Publish, ayni compiler/eval/promotion yolunu kullanir.
- UI, tool endpoint veya secret degerini gostermez.

---

## 26. Ilk Milestone Tanimi

Ilk milestone sonunda asagidaki senaryo uctan uca calismalidir:

1. Bir organization, project ve `customer-information` RAG scenario'su kaydedilir.
2. Input/output contract, prompt, policy, model profile, source ve eval suite
   GitOps import veya Admin ile olusturulur.
3. Consumer ve `query` capability binding'i tanimlanir.
4. Ingestion run baslatilir; worker dokumanlari isler ve staged index uretir.
5. Candidate release, bu index ile compile edilir.
6. Retrieval smoke ve eval suite basarili olur.
7. Release promote edilir.
8. Yetkili consumer `POST /v1/query` ile sorgu gonderir.
9. Gateway imzali context uretir, runtime aktif release/index ile cevap verir.
10. Citation, usage, metric, trace ve audit kayitlari gorunur.
11. Release rollback edilirse yeni request onceki release'e gider.

Milestone sonrasi, yeni bir basic RAG scenario onboarding'i kod degisikligi
gerektirmemelidir.

---

## 27. Test Stratejisi

### 27.1 Unit testler

- Tenant-aware queryset ve organization scope.
- Role/capability karar fonksiyonlari.
- Artefact schema ve checksum validation.
- Release compiler ve active-release constraint.
- ExecutionContext signing/verification/expiration.
- Policy, grounding, PII redaction ve fallback.
- Workflow compiler ve node validation.
- Custom node manifest, config/state schema ve allowlist validation.
- Tool risk/approval karar mantigi.
- Eval assertion engine.

### 27.2 Integration testler

- DRF gateway -> runtime facade happy path.
- OIDC/service account subject -> Consumer binding cozumu.
- Postgres/pgvector ile index-version filtreli retrieval.
- Celery ingestion claim, lock, retry ve dead-letter.
- S3/MinIO raw object yazimi.
- Candidate eval -> promote -> runtime cache invalidation.
- Tool proxy -> mock MCP/HTTP endpoint -> schema validation.
- Custom node package -> runtime execution -> input/output state validation.
- Approval -> resume -> run completion.

### 27.3 Contract testler

- REST OpenAPI schema snapshot.
- MCP tool schema snapshot.
- Input/output JSON Schema validation.
- Standard error envelope snapshot.
- GitOps YAML import/export round-trip.
- Adapter input/output contract snapshot.

### 27.4 End-to-end testler

- Project/scenario onboarding'den RAG response'a tam akis.
- Tenant izolasyonu ve yetkisiz alias reddi.
- Failed eval'in promotion'i engellemesi.
- Canary consumer'in candidate release'e gitmesi.
- Rollback sonrasi release degisimi.
- Side-effect tool'un approval olmadan calismamasi.
- Agent tool limitinin ve loop guard'in run'i sonlandirmasi.
- Source ACL degisikliginin retrieval sonucuna yansimasi.

---

## 28. V2'den V3'e Gecis

V2 dokumanlari planlama kaynagi olarak korunur. V3 import/migration modeli
asagidaki eslemeyi kullanir:

| V2 kavrami | V3 karsiligi |
|---|---|
| Project | `AIProject` + varsayilan `Scenario` |
| Project Release | `ScenarioRelease` |
| ProjectContext | `ExecutionContext` |
| Config YAML | Versioned `ArtifactVersion` + GitOps kaynak dosyasi |
| Query Runtime | `retrieval` + `orchestration` runtime facade |
| Ingestion worker | `ingestion` Django app + Celery worker |
| Consumer permission | `ConsumerBinding` + capability listesi |
| Agentic workflow ek notu | `workflow`, `agent`, `tools`, `approvals` app'leri |

V2 basic RAG config'i import edildiginde tek bir project ve onun varsayilan RAG
scenario'su olusur. V2 release'i varsa yeni `ScenarioRelease` manifest'ine
cevrilir; yoksa yeniden compile edilir. Bu gecis, mevcut endpoint veya consumer
credential'ini sessizce degistirmez; public endpoint compatibility facade'i
release notlariyla birlikte korunur.

---

## 29. Basari Kriterleri

Platform ilk production seviyesine ulastiginda su kosullari saglamalidir:

- Yeni bir RAG veya sinirli workflow scenario'su icin yeni Python modul, route
  veya deployment gerekmez.
- Her external invocation dogrulanmis consumer binding ve imzali
  ExecutionContext ile calisir.
- Runtime, request path'inde yalniz release'e pinlenen prompt, policy, model,
  workflow, tool binding ve index version kullanir.
- Ingestion, eval ve agent islemleri web request process'inde calismaz.
- Her release eval ve zorunlu guvenlik gate'lerini gecmeden aktif olamaz.
- Rollback yalniz release pointer degisimiyle yapilabilir.
- Yan etkili tool cagrilari kayitli binding, capability ve gerekli approval
  olmadan yapilamaz.
- Tenant, source ACL ve tool izinleri hem RAG hem agent yollarinda fail-closed
  uygulanir.
- Scenario bazli latency, error, token, retrieval, tool, approval, ingestion
  ve eval metrikleri gorunur.
- Contract degisiklikleri CI'da snapshot diff olarak gorunur.
- Agent trajectory, policy ihlali ve approval kararlari audit edilebilir.
- Custom node'lar yalniz registry'de kayitli, review edilmis ve release'e pinlenmis
  package/version ile calisir; config uzerinden serbest kod calistirilamaz.

---

## 30. Sonuc

AgentHub v3, v2'nin RAG odakli control-plane disiplinini korur; ancak onu
kurumun tum kontrollu AI senaryolari icin genisletir. Django modular monolith
yaklasimi, baslangicta tek bir veri modeli, tek bir authorization otoritesi ve
operasyonel basitlik saglar. Celery worker ayrimi ise ingestion, eval, workflow
ve agent yuklerini API latency yolundan uzak tutar.

Platformun temel ilkesi sudur:

```text
RAG-first, workflow-enabled, agent-ready, policy-governed enterprise AI hub.
```

Bu ilke ile RAG, workflow, agent ve adapter senaryolari ayni contract, release,
eval, audit, tool permission ve tenant izolasyonu modelinde calisir. Yeni AI
projeleri teknik olarak hizli, operasyonel olarak izlenebilir ve guvenlik
acisindan yonetilebilir bicimde canliya alinabilir.
