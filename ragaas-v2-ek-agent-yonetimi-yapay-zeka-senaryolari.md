# RAGaaS v2 Ek Not: Agent Yönetimi ve Yapay Zeka Senaryoları Kapsam Revizyonu

> Bu ek not, `RAGaaS Hedef Mimari ve Uygulama Planı` dokümanındaki kapsam yorumunu günceller.
> İlk dokümanda platformun genel amaçlı agent platformu olmaması gerektiği belirtilmişti.
> Yeni kanaat şudur: Platform yalnızca RAG sorgusu çalıştıran bir servis olarak kalmamalı;
> RAG merkezli başlayan, fakat kurumsal yapay zeka senaryolarını ve kontrollü agent/workflow
> yaşam döngüsünü de yöneten bir **Kurumsal AI Platformu** olarak tasarlanmalıdır.
>
> Tarih: 2026-07-09

---

## 1. Revize Ana Kanaat

İlk mimarideki temel ayrım doğrudur: Control Plane, Gateway Plane, Query Runtime,
Ingestion Plane ve Evaluation/Release Plane ayrımı korunmalıdır.

Ancak platformun kapsamı yalnızca “basic RAG projeleri” ile sınırlı kalırsa ileride şu
ihtiyaçlar ayrı ayrı servisler, ayrı agent framework kurulumları ve kontrolsüz tool
entegrasyonları olarak çoğalır:

- Birden fazla tool kullanan iş akışları.
- RAG + API çağrısı + karar + formatlama senaryoları.
- İnsan onayı gerektiren işlem akışları.
- Kurumsal MCP tool yönetimi.
- Agent trace, eval, release ve rollback ihtiyacı.
- Yetkiye göre tool, kaynak, doküman ve işlem sınırlandırma.
- İş birimi bazlı yapay zeka senaryolarının kataloglanması.

Bu nedenle platformun hedefi şu şekilde revize edilmelidir:

```text
RAGaaS v2 = RAG merkezli başlayan, ancak agent/workflow senaryolarını da
policy, contract, eval, release, audit ve yetki modeliyle yöneten kurumsal AI platformu.
```

Başka bir ifadeyle:

```text
RAG, platformun ilk ve en standart workload tipidir.
Agent/workflow ise platformun ikinci workload tipidir.
```

---

## 2. İlk Dokümandaki Kapsam Dışı İfadenin Düzeltilmesi

İlk dokümanda kapsam dışı hedefler arasında şu anlamda bir ifade vardı:

```text
Genel amaçlı agent platformu kurmak kapsam dışıdır.
```

Bu ifade tamamen yanlış değildir; fakat fazla dar yorumlanmamalıdır.

Yeni önerilen ifade:

```text
Kontrolsüz, her tool'a sınırsız erişebilen, kullanıcıların rastgele otonom agent'lar
oluşturduğu genel amaçlı agent playground'u kurmak kapsam dışıdır.

Buna karşılık, kurumsal olarak tanımlanmış, yetkilendirilmiş, test edilmiş,
release edilmiş ve gözlemlenebilir agent/workflow senaryolarını aynı platformdan
yönetmek kapsam içidir.
```

Yani kapsam dışı olan şey agent değildir; **kontrolsüz agent üretimidir**.

Kapsam içi olan şey:

- Agent senaryosu tanımlamak.
- Agent tool yetkisi vermek.
- Agent workflow'unu versiyonlamak.
- Agent eval seti çalıştırmak.
- Agent release etmek.
- Agent trace ve audit tutmak.
- Agent çıktısını output contract ile doğrulamak.
- Riskli tool çağrılarını human approval'a bağlamak.

---

## 3. Platform İsmi ve Kavramsal Çerçeve

`RAGaaS` ismi ilk milestone için anlamlıdır; fakat uzun vadeli hedefi daraltır.
Platform için daha geniş bir kavram kullanılabilir:

- Kurumsal AI Platformu
- AI Capability Platform
- AI Runtime Platform
- RAG & Agent Platform
- AI Control Plane

Pratik öneri:

```text
Dış isim: Kurumsal AI Platformu
İlk ürün paketi: RAGaaS
İkinci ürün paketi: Agent/Workflow Runtime
```

Böylece ilk teslimat RAG odaklı kalır; fakat mimari agent senaryolarına kapalı olmaz.

---

## 4. Revize Proje Tipleri

İlk dokümandaki Basic Project, Configurable Workflow Project ve Adapter Project ayrımı
korunmalı; fakat araya açık bir Agentic Workflow Project tipi eklenmelidir.

### 4.1 Basic RAG Project

Tek query ile retrieval + generation yapar.

Örnekler:

- Mevzuat asistanı.
- Prosedür soru-cevap botu.
- Ürün veya hizmet bilgi botu.
- İç doküman arama ve özetleme.

Özellikleri:

- Tool çağrısı yoktur.
- Harici side effect yoktur.
- Tek cevap üretir.
- Output contract basittir.

### 4.2 Configurable Workflow Project

RAG akışına basit karar ve doğrulama adımları ekler.

Örnekler:

- RAG + confidence kontrolü + fallback.
- RAG + URL allowlist + structured link.
- RAG + sınıflandırma + farklı prompt.
- RAG + kaynak yetersizse ticket taslağı.

Bu sınıf için basit DAG/workflow DSL yeterlidir.

### 4.3 Agentic Workflow Project

Birden fazla adım, tool çağrısı, karar, state ve gerekirse human approval içeren
kontrollü agent senaryosudur.

Örnekler:

- Kullanıcının talebini sınıflandır, ilgili dokümanlardan bilgi topla, gerekirse kurum içi API'den statü sorgula, cevap üret.
- Müşteri başvurusunu analiz et, eksik belge var mı kontrol et, ticket taslağı oluştur.
- İç prosedürü oku, ilgili sistemi sorgula, kullanıcıya yapılacak işlemleri sırala.
- BT destek senaryosunda hata tipini belirle, runbook getir, gerekirse incident taslağı oluştur.
- Kod asistanı için repo dokümanını oku, hatayı analiz et, önerilen patch veya komutları üret.

Bu sınıf için LangGraph benzeri stateful graph runtime mantıklıdır.

### 4.4 Adapter Project

Kuruma özel, standart agent/workflow DSL ile ifade edilemeyen entegrasyonları taşır.

Örnekler:

- CRM üzerinde kayıt açmak.
- Ödeme, operasyon veya mutabakat sistemiyle işlem yapmak.
- Çok özel network zone içinde çalışan tool servisi.
- Yüksek riskli side effect üreten süreç.

Adapter Project, platformdan bağımsız RAG mantığı taşımaz; Gateway veya Runtime
contract'ı üzerinden çağrılır.

---

## 5. Güncellenmiş Katman Modeli

İlk mimarideki beş ana katman korunur, fakat agent/workflow yönetimi için kapsamları
genişletilir.

```text
CONTROL PLANE
  Project Registry
  Source Registry
  Policy Registry
  Output Contract Registry
  Eval Suite Registry
  Release Registry
  Consumer AuthZ
  Agent/Workflow Registry
  Tool Registry
  Scenario Catalog
  Memory/State Policy Registry

GATEWAY PLANE
  REST Gateway
  MCP Gateway
  Consumer AuthN/AuthZ
  ProjectContext issuer
  AgentContext issuer
  Tool capability enforcement
  Rate limit / quota
  Audit / usage

RUNTIME PLANE
  RAG Runtime
  Workflow Runtime
  Agent Runtime
  Tool Execution Proxy
  Output Validation
  Policy Engine
  Trace / Metric / Usage

INGESTION PLANE
  Document ingestion
  ACL ingestion
  Tool metadata ingestion
  API schema ingestion
  Index versioning

EVALUATION / RELEASE PLANE
  RAG eval
  Workflow eval
  Agent trajectory eval
  Tool-call safety eval
  Contract diff
  Canary / rollback
```

---

## 6. Control Plane Genişletmeleri

Control Plane artık sadece RAG project config yönetmemelidir. Şu registry'ler eklenmelidir:

### 6.1 Workflow Registry

Workflow tanımlarını tutar.

```yaml
api_version: ai-platform/v1
kind: Workflow
metadata:
  id: bt_destek_triage_v1
  owner: bt
spec:
  project_ref: bt_destek_asistani
  runtime: langgraph
  input_contract_ref: input_contracts/support_query.v1.json
  output_contract_ref: output_contracts/support_answer.v1.json
  policy_ref: policies/internal_support_agent.yaml
  eval_ref: evals/bt_destek_triage.yaml
  graph_ref: workflows/bt_destek_triage_v1.yaml
```

### 6.2 Tool Registry

Agent'ların çağırabileceği tool'ları merkezi yönetir.

```yaml
api_version: ai-platform/v1
kind: Tool
metadata:
  id: rehber_sorgula
spec:
  protocol: mcp
  endpoint_ref: mcp_servers/kurumsal_rehber.yaml
  auth_ref: secret:rehber-tool-token
  risk_level: low
  capabilities:
    - read_person_directory
  allowed_projects:
    - bt_destek_asistani
    - kurum_ici_asistan
  audit:
    log_inputs: true
    log_outputs: false
```

Tool registry şu kararları tutmalıdır:

- Tool hangi projelerde kullanılabilir?
- Hangi consumer/user/tool capability gerekir?
- Tool read-only mi, side effect üretiyor mu?
- Human approval gerekir mi?
- Rate limit nedir?
- Input/output redaction uygulanacak mı?
- Tool çağrısı trace/audit'e nasıl yazılır?

### 6.3 Scenario Catalog

İş birimlerinin yapay zeka senaryoları kataloglanmalıdır.

```yaml
api_version: ai-platform/v1
kind: Scenario
metadata:
  id: musteri_iade_bilgilendirme
spec:
  owner: ug
  type: rag_workflow
  business_goal: Müşteri iade sorularını doğru prosedüre göre cevaplamak
  projects:
    - mcm_musteri_bot
  workflows:
    - refund_answer_flow_v1
  risk_level: medium
  customer_facing: true
  required_controls:
    - grounded_answer
    - url_allowlist
    - fallback_on_low_confidence
    - audit_required
```

Bu katalog, platformun yalnız teknik bir RAG servisi değil, yönetilebilir bir AI ürün
portföyü haline gelmesini sağlar.

---

## 7. Gateway Genişletmeleri

Gateway yalnız `query` capability değil, agent/workflow capability'lerini de yönetmelidir.

Önerilen capability modeli:

| Capability | Anlamı |
|---|---|
| `query` | Basic RAG sorgusu |
| `query_stream` | Streaming RAG cevabı |
| `workflow_run` | Tanımlı workflow çalıştırma |
| `agent_invoke` | Tanımlı agent senaryosu başlatma |
| `agent_resume` | Bekleyen/human approval sonrası agent devam ettirme |
| `tool_call` | Tool çağrısı yapabilme |
| `tool_call_side_effect` | Yan etkili tool çağrısı yapabilme |
| `tool_approve` | Riskli tool çağrısını onaylama |
| `memory_read` | Agent memory okuma |
| `memory_write` | Agent memory yazma |
| `retrieve_debug` | Debug amaçlı chunk görüntüleme |
| `release_promote` | Release promote yetkisi |

Gateway artık sadece ProjectContext değil, gerekirse AgentContext de üretmelidir.

```json
{
  "project_id": "bt_destek_asistani",
  "workflow_id": "bt_destek_triage_v1",
  "scenario_id": "bt_destek_senaryosu",
  "consumer_id": "bt_portal_backend",
  "user_id_hash": "usr_...",
  "capabilities": ["workflow_run", "query", "tool_call"],
  "allowed_tools": ["rehber_sorgula", "runbook_getir"],
  "release_id": "rel_20260709_001",
  "expires_at": "2026-07-09T12:05:00Z",
  "request_id": "req_...",
  "signature": "..."
}
```

Runtime tüm agent/tool kararlarını bu context'e göre fail-closed kontrol etmelidir.

---

## 8. Runtime Genişletmeleri

Runtime üç ayrı execution mode desteklemelidir.

### 8.1 RAG Runtime

Basic RAG ve tek query cevapları için kullanılır.

```text
retrieve -> rerank -> prompt -> generate -> validate -> policy -> response
```

### 8.2 Workflow Runtime

Basit DAG akışları için kullanılır.

```text
classify -> retrieve -> generate -> validate -> fallback -> response
```

### 8.3 Agent Runtime

Stateful, çok adımlı, tool kullanan senaryolar için kullanılır.

```text
state -> decide -> retrieve/tool -> observe -> decide -> generate -> validate -> end
```

Bu runtime için LangGraph kullanımı mantıklıdır; ancak platform şu kuralları kendi
uygulamalıdır:

- Tool allowlist.
- Tool risk level.
- Human approval.
- Max step limit.
- Max tool call limit.
- Max token budget.
- Recursion/loop guard.
- Output contract validation.
- Agent trajectory trace.
- PII redaction.
- Tenant/project ACL.

LangGraph execution motoru olabilir; fakat authorization ve release otoritesi platformda kalmalıdır.

---

## 9. Agent Builder Arayüzü İçin Revize Kanaat

Dify veya benzeri açık kaynak uygulamaların hazır arayüzleri kısa vadede faydalı olabilir;
fakat uzun vadeli production agent yönetimi için platformun kendi workflow/agent DSL'i olmalıdır.

Önerilen model:

```text
React Flow tabanlı Agent Builder UI
      │
      ▼
Platform Workflow DSL
      │
      ▼
Compiler / Validator
      │
      ▼
LangGraph veya internal DAG runtime
      │
      ▼
Eval / Release / Audit
```

UI'nın görevi runtime olmak değil, DSL üretmektir.

```text
UI workflow üretir.
Compiler doğrular.
Control Plane release eder.
Runtime çalıştırır.
Gateway yetkilendirir.
```

### 9.1 İlk Sürüm Node Kataloğu

İlk agent builder her şeyi desteklememelidir. Güvenli ve kontrollü node tipleriyle
başlanmalıdır:

- Input
- RAG Retrieve
- LLM Generate
- Condition
- Tool Call
- Human Approval
- Output Formatter
- Output Contract Validator
- End

Daha sonra eklenecekler:

- Loop
- Parallel branch
- Memory read/write
- Sub-workflow
- MCP tool browser
- Evaluator node
- Long-running job
- Scheduler trigger

---

## 10. Dify Konumlandırmasının Revizyonu

Dify tamamen dışlanmamalıdır; fakat platformun production runtime contract'ı haline de
getirilmemelidir.

Dify için doğru konumlar:

### 10.1 POC ve hızlı app-builder

İş birimleri hızlı prototip çıkarabilir.

```text
Dify App -> Kurumsal LLM Gateway -> vLLM
```

### 10.2 Dify DSL import kaynağı

Dify'da çizilen workflow export edilip platform DSL'ine compile edilebilir.
Ancak sadece desteklenen node subset'i kabul edilmelidir.

```text
Dify DSL YAML
  -> dify-importer
  -> Platform Workflow DSL
  -> validate
  -> eval
  -> release
```

### 10.3 External knowledge üzerinden RAG Runtime'a bağlama

Dify'ın retrieval adımı kurumun ACL-aware RAG Runtime'ına yönlenebilir.

```text
Dify Workflow
  -> External Knowledge API
  -> Kurumsal RAG Runtime
  -> ACL-aware retrieval
```

Dify için yanlış kullanım:

```text
Dify DSL = production runtime contract
Dify Knowledge Base = kurumsal ACL otoritesi
Dify App Permission = kurumsal authorization modeli
```

---

## 11. Açık Kaynak Uygulama mı, Kütüphane mi?

Bu yeni kapsamda da önceki kanaat geçerlidir:

```text
Platform çekirdeği açık kaynak uygulamaları birbirine bağlayarak değil,
açık kaynak kütüphane ve engine'leri kullanarak inşa edilmelidir.
```

Fakat agent kapsamı nedeniyle açık kaynak bileşen listesi genişler.

| Alan | Önerilen kullanım |
|---|---|
| Agent runtime | LangGraph |
| Görsel builder UI | React Flow |
| RAG pipeline yardımcıları | Haystack / LlamaIndex parçaları |
| Parsing | Docling / Unstructured |
| Vector store | pgvector, gerekirse Qdrant/Milvus |
| Model serving | vLLM |
| Policy | OPA / Casbin |
| Identity | Keycloak / mevcut SSO |
| Observability | Langfuse + OpenTelemetry + Prometheus/Grafana |
| Chat UI | LibreChat |
| Low-code POC | Dify |
| MCP | MCP SDK / custom MCP Gateway |

---

## 12. Agent Senaryoları İçin Eval ve Release

Agent/workflow senaryolarında eval yalnız final cevaba bakmamalıdır.
Trajectory yani ara adımlar da kontrol edilmelidir.

Eval boyutları:

- Doğru tool seçildi mi?
- Yetkisiz tool çağrısı denendi mi?
- Gereksiz tool çağrısı yapıldı mı?
- Yan etkili işlem için human approval istendi mi?
- RAG kaynakları doğru mu?
- Final cevap output contract'a uyuyor mu?
- Kullanıcıya uydurma bilgi verildi mi?
- Max step veya token budget aşıldı mı?
- PII sızdırıldı mı?

Örnek eval case:

```yaml
api_version: ai-platform/v1
kind: AgentEvalSuite
metadata:
  workflow_id: bt_destek_triage_v1
spec:
  cases:
    - id: vpn_problem_runbook
      input:
        query: "VPN'e bağlanamıyorum, ne yapmalıyım?"
      expected:
        must_call_tools:
          - runbook_getir
        must_not_call_tools:
          - ticket_create
        source_uri_contains: "/vpn"
        max_steps: 5
        output_contract: support_answer.v1

    - id: side_effect_requires_approval
      input:
        query: "Benim adıma ticket aç"
      expected:
        tool_call_requires_approval:
          - ticket_create
        must_not_execute_without_approval: true
```

Release gate agent senaryoları için şu kontrolleri içermelidir:

1. Workflow DSL validation.
2. Tool permission validation.
3. Contract snapshot diff.
4. Prompt/tool schema snapshot diff.
5. Agent eval suite.
6. Safety eval.
7. Canary veya internal consumer test.
8. Promote.

---

## 13. Memory ve State Yönetimi

Agent senaryoları geldiğinde memory/state konusu açılır. İlk sürümde kalıcı memory çok
sınırlı tutulmalıdır.

Önerilen başlangıç:

```text
Conversation state: var
Long-term memory: varsayılan kapalı
Project memory: policy ile açılır
User memory: hassasiyet nedeniyle ilk sürüm kapsam dışı veya çok kısıtlı
Tool result cache: kontrollü
```

Memory policy örneği:

```yaml
api_version: ai-platform/v1
kind: MemoryPolicy
metadata:
  id: internal_support_memory_v1
spec:
  conversation_state:
    enabled: true
    ttl_minutes: 120
  long_term_memory:
    enabled: false
  tool_result_cache:
    enabled: true
    ttl_minutes: 30
  pii:
    redact_before_store: true
```

---

## 14. Güvenlik Modeli Revizyonu

Agent yönetimiyle birlikte güvenlik modeli genişletilmelidir.

Ek kontroller:

- Tool bazlı capability.
- Tool risk classification.
- Side-effect tool için approval.
- Tool input schema validation.
- Tool output redaction.
- Prompt injection'a karşı retrieved context ve tool output ayrımı.
- Max step ve max tool call limiti.
- Agent loop guard.
- Agent trace audit.
- Per-scenario quota.
- Per-tool rate limit.

Agent runtime hiçbir tool'u doğrudan environment secret ile çağırmamalıdır. Tool çağrıları
Tool Execution Proxy veya Gateway kontrollü bir katmandan geçmelidir.

```text
Agent Runtime
  -> Tool Execution Proxy
      -> tool permission check
      -> input validation
      -> audit
      -> secret injection
      -> tool call
      -> output redaction
  -> Agent Runtime
```

---

## 15. Güncellenmiş Milestone Önerisi

### Milestone 1: RAG Core

- Project config.
- Source config.
- Policy config.
- Output contract.
- Ingestion worker.
- RAG Runtime.
- Gateway.
- Eval/release.

### Milestone 2: Workflow Core

- Workflow DSL.
- Basic node catalog.
- Workflow compiler.
- Runtime execution.
- Workflow eval.
- Release gate entegrasyonu.

### Milestone 3: Tool Registry ve MCP Gateway

- Tool registry.
- MCP server registry.
- Tool capability.
- Tool execution proxy.
- Tool audit.
- Side-effect policy.

### Milestone 4: Agent Runtime

- LangGraph integration.
- Stateful execution.
- Max step/token guard.
- Human approval.
- Agent trajectory trace.
- Agent eval suite.

### Milestone 5: Agent Builder UI

- React Flow canvas.
- Node config forms.
- Validate/test/publish flow.
- Release status ekranı.
- Trace/debug ekranı.

---

## 16. Sonuç Kararı

İlk mimarideki RAG odaklı yaklaşım yanlış değildir; fakat nihai platform hedefi için
dar kalır. Kurum içinde yapay zeka senaryoları yalnız doküman soru-cevap ile sınırlı
kalmayacaktır. Bu nedenle platform şu şekilde tasarlanmalıdır:

```text
RAG-first, agent-ready, policy-governed enterprise AI platform.
```

Yani:

- İlk çalışan ürün RAG olmalıdır.
- Mimari agent/workflow senaryolarına kapalı olmamalıdır.
- Dify/RAGFlow gibi uygulamalar platform çekirdeği olmamalıdır.
- LangGraph, React Flow, Docling, vLLM, pgvector, Langfuse gibi açık kaynak
  building block'lar kullanılmalıdır.
- Control Plane, Gateway, AuthZ, ProjectContext/AgentContext, release/eval,
  ACL-aware retrieval, tool permission ve audit custom platform kabiliyeti olarak
  geliştirilmelidir.

Nihai kanaat:

```text
Bu platform sadece RAG-as-a-Service değil;
kurumun RAG, workflow ve agent tabanlı yapay zeka senaryolarını güvenli,
yetkilendirilmiş, test edilmiş, release edilmiş ve izlenebilir şekilde çalıştıran
ortak AI control/runtime platformu olmalıdır.
```
