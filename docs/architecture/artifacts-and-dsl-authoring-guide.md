# AgentHub Artifact ve DSL Yazım Kılavuzu

## 1. Amaç ve otorite

Bu doküman AgentHub artifact registry, release manifest rolleri, workflow DSL, agent tanımı,
tool/custom-node sözleşmeleri, eval suite ve Phase 2.5 transform DSL hedefini ayrıntılı olarak
açıklar. Hedef kitlesi platform geliştiricileri, senaryo editörleri, release yöneticileri ve bir LLM
ile artifact taslağı üreten kullanıcılardır.

Bu kılavuz açıklayıcıdır. Nihai otorite her zaman backend validator/compiler ve veritabanındaki
exact immutable artifact sürümüdür. Kılavuz ile kod çelişirse artifact kabul edilmez; çelişki bir
dokümantasyon hatası olarak düzeltilmelidir.

Mevcut ve planlanan davranışlar özellikle ayrılmıştır:

- **Mevcut:** Kodda validator/compiler/runtime karşılığı vardır.
- **Phase 2.5 Part 1 — implementation in progress:** Kod değişikliği yazılmış olabilir fakat görev
  verification kaydı tamamlanmadan desteklenen güncel davranış sayılmaz.
- **Later Phase 2.5 hedefi:** Planlanmıştır; henüz mevcut artifact sözleşmesi gibi kullanılamaz.
- **Phase 3:** Phase 2.5 dışında bırakılmış discovery veya ileri teslimat konusudur.
- **Henüz sıkı şeması yok:** Registry türü tanır fakat tipe özel alan allowlist’i henüz yoktur.

## 2. Temel model

### 2.1 Scenario, artifact ve release ilişkisi

Bir `Scenario`, çağrılabilir ve release edilebilir AI davranışıdır. Bir workflow node’u artifact
değildir. Workflow’un tüm node ve edge grafiği tek bir `workflow_definition` artifact gövdesidir.

Bir scenario release’i birden fazla artifact rolünü exact sürümleriyle pinleyebilir:

```text
Scenario
└── ScenarioRelease
    ├── input_contract       → customer-query:v3
    ├── output_contract      → customer-answer:v2
    ├── workflow_definition  → support-flow:v7
    ├── prompt               → answer-prompt:v4
    ├── model_profile        → local-model:v2
    ├── retrieval_profile    → hybrid-search:v5
    ├── policy_profile       → cited-output:v1
    ├── search               → search-binding:v3
    └── eval_suite           → support-regression:v6
```

Manifestteki sol taraf **rol**, sağ taraf artifact `logical_id:vN` referansıdır. Rol runtime’ın
artifact’i hangi amaçla kullanacağını söyler. Aynı artifact farklı release’lerde veya uygun olduğu
sürece farklı rollerde pinlenebilir.

### 2.2 Reuse sınırı

Artifact anahtarı şudur:

```text
organization + type + logical_id + version
```

Bu nedenle published artifact’ler aynı organizasyondaki farklı proje ve senaryolar arasında
reusable’dır. Artifact değiştirilmez; değişiklik yeni version üretir. Eski release exact version ve
checksum pinlediği için yeni sürümden etkilenmez.

Cross-organization reuse yoktur. Release compiler artifact’i scenario’nun organizasyonunda arar.
Başka organizasyona aynı içerik aktarılırsa yeni tenant lineage ve yeni artifact sürümü oluşur.

**Later Phase 2.5 · Part 6 hedefi:** Scenario oluşturma/düzenleme akışı aynı organizasyondaki
compatible published artifact sürümlerini arayıp seçtirecektir. Seçim exact type + logical ID +
version + checksum pinler; artifact’i update etmez. Başka organizasyonun artifact’i seçeneklerde
görünmez. Yeni davranış gerektiğinde mevcut sürüm değiştirilmez, yeni immutable version publish
edilir. Bu seçim UI/runtime sözleşmesi uygulanıp doğrulanana kadar bugünkü console capability’si
sayılmaz.

### 2.3 Mevcut standart manifest rolleri

Rol adları genel olarak manifest key’leridir; type ile aynı olmak zorunda olmayan özel roller de
oluşturulabilir. Mevcut runtime’ın doğrudan aradığı standart roller:

| Rol | Kullanım |
| --- | --- |
| `input_contract` | Gateway input doğrulaması ve runtime bundle |
| `output_contract` | Workflow/agent output doğrulaması |
| `workflow_definition` | Workflow scenario compiler/runtime |
| `agent_definition` | Agent scenario compiler/runtime |
| `prompt` | Default RAG/model prompt’u |
| `model_profile` | Default model profile artifact’i |
| `retrieval_profile` | Default retrieval provider ayarları |
| `policy` | Genel orchestration bundle policy’si |
| `policy_profile` | Mevcut workflow/agent citation output kontrolü |
| `eval_suite` | Eval runner vakaları |

Workflow `generate.config.prompt_ref` ve `model_profile_ref`, bu standart roller yerine release’te
pinlenmiş başka rol adlarını seçebilir. Tool/agent role adları scenario’ya özeldir. `policy` ve
`policy_profile` ayrımı mevcut runtime davranışıdır; Phase 2.5 scenario studio/contract çalışmasında
tek ve açık bir role sözleşmesine dönüştürülmesi gerekir.

### 2.4 Artifact immutability ve checksum

`ArtifactVersion` oluşturulduktan sonra update ve doğrudan delete kabul etmez. Gövde canonical JSON’a
dönüştürülür:

- Key’ler sıralanır.
- Gereksiz whitespace kaldırılır.
- Unicode ASCII escape’e zorlanmaz.
- SHA-256 checksum canonical UTF-8 byte dizisi üzerinden hesaplanır.

Release compile sırasında artifact yeniden validate edilir ve saklanan checksum tekrar hesaplanan
checksum ile karşılaştırılır. Eksik ref, tenant uyuşmazlığı, invalid body veya checksum drift release
oluşumunu fail-closed durdurur.

### 2.5 Organizasyon sahipliği ve authoring girişleri

**Phase 2.5 Part 1–3 mevcut davranış.** Bilgi mimarisi:

```text
Dashboard
└── Organizasyon overview
    ├── Projeler
    │   └── Senaryolar
    ├── Doküman setleri
    ├── İstemci uygulamalar (teknik model: Consumer)
    ├── Published artifact sürümleri
    └── Release'ler
```

Doküman setleri, istemci uygulamalar ve published artifact sürümleri organizasyon-owned canonical
objelerdir; proje child’ı değildir. Scenario bunlarla binding, grant ve exact release manifest
pinleri üzerinden ilişki kurar. Aynı isimli obje farklı organizasyonda ayrı tenant lineage’dır.

`/console/` dashboard olarak kalır. `/console/o/<organization-slug>/` organizasyon overview’dür.
Mevcut project/scenario/document-set/consumer/artifact/release list, detail ve action URL’leri
canonical kalır; Part 1 bunlar için toplu URL migration veya redirect oluşturmaz. URL veya primary
key yetki değildir: target önce kullanıcının membership kapsamındaki queryset’ten çözülür,
organizasyon server-side objeden alınır ve ilişkisel sorgulardan önce transaction-local PostgreSQL
scope bu tek organizasyona daraltılır.

Authoring yüzeylerinin rolleri:

- Scenario Studio/Builder: mutable taslak ve canonical validation girişidir; doğrudan active runtime
  değiştirmez.
- Artifact detail: bir immutable exact version’ın body/checksum ve pin kullanımını inceler.
- Release detail: scenario runtime’ının exact artifact pinlerini ve manifest checksum’unu inceler.
- Document-set detail: içerik ekleme, immutable replacement, taslaktan çıkarma, tombstone, sürüm,
  parse/normalize, staged/active indeks, kaynak, scenario binding ve istemci retrieval grant
  ilişkilerini tek yaşam döngüsünde gösterir. Published set sürümleri değişmez; replacement yeni
  `DocumentVersion` üretip yalnız manuel taslağın exact pinini günceller. Tombstone baytları veya
  tarihsel pinleri silmez.
- Document-set kaynak workspace'i, upload/Confluence/REST seçimini ve REST için platform profili +
  immutable mapping revizyonu + güvenli input binding ayrımını tek yönlendirmeli akışta sunar.
  Platform profili endpoint, credential reference, network/CA ve response sınırlarının otoritesidir;
  mapping sözleşmesi bounded response'u canonical document biçimine dönüştürür; source instance bu
  iki exact revizyonu sete ve yenileme politikasına bağlar. Sentetik preview egress açmaz ve yalnız
  güvenli türetilmiş metadata gösterir. Source detail; son sync, güvenli hata kodu, değişen/değişmeyen
  sayaçları, draft/published set sürümü ve staged/active index ilerlemesini gösterir. Sync doğrudan
  active index değiştirmez; publish, staged build/evaluation ve promotion ayrı governed kapılardır.
- Tekil document envanteri primary navigation değildir. Yalnız organizasyon/platform yöneticilerinin
  açabildiği gelişmiş saklama alanı tombstone ve purge operasyonlarını sunar. Purge, typed confirmation,
  tombstone ve hiçbir set sürümünde pin bulunmaması koşullarını korur.
- İstemci detail: scenario binding, effective document-set grant ve yalnız güvenli token metadata
  gösterir. Organizasyon yöneticisi ayrı POST aksiyonlarıyla bearer token üretebilir, döndürebilir
  veya iptal edebilir; plaintext yalnız başarılı üretim/döndürme yanıtında bir kez gösterilir.

Proje sahipliği yeni console kayıtlarında serbest metin değildir. Seçilen sahip aynı aktif
organizasyondaki `organization_admin` veya `project_owner` üyeliğine durable FK ile bağlanır;
membership silme, proje yeniden atanmadan `PROTECT` ile engellenir. Eski `owner` metni ve GitOps
string sözleşmesi uyumluluk etiketi olarak korunur ve yetki vermez. Migrasyon yalnız aynı
organizasyonda username'i tam eşleşen eski kayıtları bağlar; eşleşmeyen değerleri tahmin etmez.

## 3. Ortak güvenlik kuralları

### 3.1 Gövde JSON object olmalıdır

Bütün artifact body’leri JSON object/dictionary olmalıdır. Liste, string, sayı veya `null` tek başına
artifact body olamaz.

### 3.2 Inline secret yasaktır

Şu anahtarlar literal secret taşıyamaz:

```text
password, passwd, secret, secret_key, token, access_token,
api_key, apikey, access_key, private_key, client_secret,
authorization, bearer
```

Gerekli yerlerde yalnız mantıksal referans kullanılır:

```json
{"secret_ref": "secret:erp-service-token"}
```

Artifact içine gerçek token, parola, private key veya authorization header yazılmaz. Secret resolver
değeri runtime’da yetkili platform profilinden sağlar; export ve UI plaintext değeri göstermez.

### 3.3 Identifier karakterleri

Workflow identifier’ları en fazla 64; agent/tool identifier’ları çoğunlukla en fazla 128 karakterdir.
İzin verilen ortak karakter kümesi:

```text
A-Z a-z 0-9 . _ -
```

Boş string, whitespace, slash, bracket veya shell karakterleri kullanılmaz. Console tarafında bu
identifier’ların kullanıcıdan istenmemesi ve sistem tarafından üretilmesi Phase 2.5 kararıdır;
GitOps gibi declarative yüzeyler idempotency için explicit logical ID kullanmaya devam edebilir.

Phase 2.5 Part 2 ile console organizasyon, proje, senaryo, doküman ve doküman-seti
oluşturma akışları slug/logical ID/API alias istemez. Bu değerler server-side domain
servislerinde bir kez üretilir ve görünen ad değişince değişmez. Senaryonun ilk active
alias'ı normalize proje-senaryo prefix'i ile dört karakterlik kriptografik base32
suffix'ten oluşur. Proje, senaryo, doküman, doküman seti ve istemci uygulama console
linkleri tenant-scoped immutable UUID `public_id` kullanır. Eski integer console
route'ları geçiş uyumluluğu için aynı authorization handler'larına bağlı kalır; UUID,
slug veya route bilgisi hiçbir zaman yetki vermez. Artifact/release locator'ları bu partta
değişmemiştir.

### 3.3.1 Consumer bearer kimliği ve token yaşam döngüsü

Varsayılan bearer modunda normal console akışı `Consumer.subject` istemez. Domain servisi görünen
addan türetilmeyen, organizasyon içinde unique, `consumer-` prefix'li kriptografik opaque subject
üretir. GitOps/import mevcut explicit subject sözleşmesini idempotent deklaratif kullanım için
korur; OIDC/mTLS subject girişi bu modlar ayrıca yapılandırılana kadar console'da gösterilmez.

Bir consumer birden çok adlandırılmış token taşıyabilir. Issue ve rotate yalnız aktif consumer ve
aktif organizasyon için `organization_admin`/platform admin yetkisiyle, login + CSRF + POST
sınırında çalışır. Rotate seçilen aktif tokenı aynı transaction'da revoke edip replacement üretir;
revoke idempotent'tir ve pasif consumer için de savunma amacıyla kullanılabilir. Token mutasyonu ve
başarılı audit kaydı tek transaction'dadır; audit yazılamazsa credential değişikliği rollback olur.

Plaintext token URL, session, message, audit veya veritabanına yazılmaz. Yalnız SHA-256 hash ve
güvenli prefix kalıcıdır. Tek-seferlik HTML yanıtı `Cache-Control: no-store`, `Pragma: no-cache` ve
`Referrer-Policy: no-referrer` taşır. Sonraki detail GET yalnız ad, prefix, status ve last-used
metadata gösterir. Revoked token gateway ve MCP çözümlemesinde fail-closed reddedilir.

### 3.4 Artifact ref biçimi

Exact artifact ref:

```text
<logical_id>:v<pozitif-tamsayı>
```

Örnek:

```text
customer_query:v3
```

`latest`, version range veya floating tag release manifestinde kullanılmaz.

## 4. Artifact türleri ve mevcut validation seviyesi

| Tür | Amaç | Mevcut tipe özel validation |
| --- | --- | --- |
| `input_contract` | Gateway/scenario input şeması | JSON Schema Draft 2020-12 schema-validity |
| `output_contract` | Runtime output şeması | JSON Schema Draft 2020-12 schema-validity |
| `prompt_template` | Model prompt metni | Genel object + inline-secret kontrolü; runtime `template` okur |
| `policy_profile` | Runtime output/policy kısıtları | Genel object; mevcut runtime citation politikasını okur |
| `model_profile` | Platform model profile referansı | Yalnız `profile_id` UUID |
| `source_definition` | Kaynak tanımı için registry türü | Henüz tipe özel sıkı şema yok |
| `chunking_profile` | Chunk davranışı için registry türü | Henüz tipe özel sıkı şema yok |
| `retrieval_profile` | Retrieval davranışı | Henüz tipe özel sıkı şema yok |
| `workflow_definition` | Deterministic DAG | Sıkı compiler |
| `custom_node_definition` | Preinstalled custom node manifesti | Sıkı validator + registration/runtime kontrolleri |
| `tool_definition` | Governed outbound tool | Sıkı validator |
| `tool_binding` | Release/scenario tool daraltması | Sıkı validator + registry resolution |
| `agent_definition` | Bounded agent config | Sıkı validator/compiler |
| `memory_policy` | Memory politikası için registry türü | Henüz tipe özel sıkı şema yok |
| `eval_suite` | Promotion/eval vakaları | Sıkı bounded assertion allowlist’i |

“Henüz tipe özel sıkı şema yok” ifadesi alanların serbest ve production sözleşmesi olduğu anlamına
gelmez. Yalnız registry’nin şu anda generic object ve inline-secret kontrolü uyguladığı anlamına
gelir. Bu türlere yeni alan eklemeden önce validator/runtime sözleşmesi birlikte geliştirilmelidir.

## 5. GitOps belge zarfı

GitOps import/export yüzeyi artifact body’nin üstüne ayrı bir zarf koyar:

```yaml
api_version: agenthub/v1
kind: InputContract
metadata:
  organization: acme
  logical_id: customer-query
  version: 3
spec:
  type: object
  properties:
    query:
      type: string
  required: [query]
  additionalProperties: false
```

- `metadata.organization`: organizasyon slug’ı veya import komutundaki trusted default.
- `metadata.logical_id`: artifact’in versionlar boyunca stable kimliği.
- `metadata.version`: opsiyonel; verilmezse service sıradaki version’ı üretir.
- `metadata.checksum`: exportta bulunabilir; import service gövdeden canonical checksum üretir.
- `spec`: artifact body’nin kendisidir.

Mevcut GitOps kind allowlist’i:

```text
InputContract, OutputContract, PromptTemplate, PolicyProfile,
ModelProfile, SourceDefinition, ChunkingProfile, RetrievalProfile,
WorkflowDefinition, ToolDefinition, ToolBinding, MemoryPolicy, EvalSuite
```

`AgentDefinition` ve `CustomNodeDefinition` mevcut type registry’de bulunmasına rağmen GitOps kind
mapping’inde bugün yoktur. Bunları mevcut GitOps importuna gönderme; destek eklenmeden “çalışıyor”
kabul edilmemelidir.

Workflow artifact body’si de kendi `api_version/kind/metadata/spec` yapısına sahip olduğundan GitOps
zarfında iç içe görünür:

```yaml
api_version: agenthub/v1
kind: WorkflowDefinition
metadata:
  organization: acme
  logical_id: support-flow
spec:
  api_version: agenthub/v1
  kind: Workflow
  metadata:
    id: support-flow.v1
  spec:
    input_node: request
    nodes: []
    edges: []
```

Yukarıdaki boş node listesi yapıyı göstermek içindir ve validator’dan geçmez.

## 6. Input ve output contract

Contract body doğrudan geçerli JSON Schema Draft 2020-12 belgesidir. Gateway input’u aktif
release’teki `input_contract` rolüne, workflow/agent output’u `output_contract` rolüne göre validate
eder.

Önerilen kapalı input örneği:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["query"],
  "properties": {
    "query": {
      "type": "string",
      "minLength": 1,
      "maxLength": 4000
    },
    "locale": {
      "type": "string",
      "enum": ["tr-TR", "en-US"]
    }
  },
  "additionalProperties": false
}
```

Önerilen output örneği:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["answer", "sources"],
  "properties": {
    "answer": {"type": "string", "maxLength": 20000},
    "sources": {
      "type": "array",
      "maxItems": 50,
      "items": {"type": "object"}
    }
  },
  "additionalProperties": false
}
```

Backend bugün schema’nın meta-schema açısından geçerli olduğunu kontrol eder. Güvenli contract için
author ayrıca `type`, `required`, string/array bounds ve çoğu durumda `additionalProperties: false`
yazmalıdır. Sadece `{ "type": "object" }` geçerlidir fakat gereğinden geniş bir sözleşmedir.

## 7. Prompt, policy ve model profile

### 7.1 Prompt template

Mevcut runtime standart `prompt` rolündeki veya generate node’un `prompt_ref` rolündeki body’nin
`template` alanını string olarak okur:

```json
{
  "template": "Yalnız sağlanan bağlamı kullan. Kaynak yoksa bilmediğini söyle."
}
```

`prompt_template` için bugün tipe özel exact-key, uzunluk veya placeholder validator’ı yoktur. Bu
nedenle bu örnek mevcut runtime beklentisini gösterir; genel amaçlı prompt DSL garantisi değildir.

### 7.2 Policy profile

Mevcut workflow/agent runtime şu dar policy biçimini kullanır:

```json
{
  "output": {
    "citations": "required"
  }
}
```

Bu durumda output içindeki `sources` alanı non-empty list değilse run `POLICY_VIOLATION` ile
fail-closed olur. `policy_profile` için bugün daha geniş tipe özel şema yoktur.

### 7.3 Model profile artifact

Artifact endpoint/secret/model bilgisi taşımaz. Yalnız platform tarafından önceden oluşturulmuş
profile’ın UUID’sini referanslar:

```json
{
  "profile_id": "11111111-1111-1111-1111-111111111111"
}
```

Başka hiçbir alan kabul edilmez. Endpoint, host, path, model, `secret:<name>`, timeout ve response
limitleri platform `ModelProfile` kaydındadır. Böylece tenant artifact’i egress hedefi icat edemez.

## 8. Workflow DSL — tam mevcut sözleşme

### 8.1 Top-level yapı

Workflow body exact olarak şu dört alanı taşır:

```json
{
  "api_version": "agenthub/v1",
  "kind": "Workflow",
  "metadata": {
    "id": "support-flow.v1"
  },
  "spec": {
    "input_node": "request",
    "nodes": [],
    "edges": []
  }
}
```

Unknown top-level, metadata veya spec alanı reddedilir.

Hard limits:

- Node: `1..50`
- Edge: `0..100`
- Workflow/node/role identifier: en fazla 64 karakter
- Condition expression: `1..500` karakter
- Node runtime süre kontrolü: 30 saniye
- Graph: acyclic ve bütünüyle input node’dan reachable

### 8.2 Graph invariants

- `spec.input_node`, var olan ve type’ı `input` olan node’u göstermelidir.
- Node ID’leri unique olmalıdır.
- Bütün edge endpoint’leri var olan node ID’leridir.
- Graph cycle içeremez.
- Bütün node’lar input node’dan reachable olmalıdır.
- En az bir reachable `end` node bulunmalıdır.
- `end` dışındaki her node’un en az bir outgoing edge’i olmalıdır.
- `end` node outgoing edge taşıyamaz.
- Runtime’da condition olmayan node’un tam bir outgoing edge’i olmalıdır.
- Condition node’un runtime sonucuna karşılık tam bir `when: true` veya `when: false` edge’i
  seçilebilmelidir; eksik veya birden fazla eşleşme run’ı fail eder.

### 8.3 Ortak node biçimi

```json
{
  "id": "retrieve_context",
  "type": "retrieve",
  "config": {}
}
```

`config` opsiyoneldir ve yoksa `{}` kabul edilir. Node yalnız `id`, `type`, opsiyonel `config`
alanlarını taşıyabilir. Config ağacı içinde şu key adları her seviyede yasaktır:

```text
endpoint, url, entrypoint, package, python, code, secret
```

### 8.4 Built-in node türleri

#### `input`

```json
{"id": "request", "type": "input"}
```

Config kabul etmez. Runtime state başlangıcındaki `input` anahtarı gateway payload’ını temsil eder.

#### `retrieve`

```json
{"id": "retrieve", "type": "retrieve"}
```

Config kabul etmez. Query, `state.input.query` string’inden türetilir. Retrieval scope’u client
belirlemez; active release’in document-set pinleri, consumer grant’i ve tenant sınırı uygulanır.
Sonuç `state.retrieval` alanına yazılır.

#### `generate`

Default binding:

```json
{"id": "answer", "type": "generate"}
```

Per-node release role binding:

```json
{
  "id": "answer",
  "type": "generate",
  "config": {
    "prompt_ref": "answer_prompt",
    "model_profile_ref": "fast_model"
  }
}
```

`prompt_ref` ve `model_profile_ref` artifact ref değildir; release manifestindeki rol adlarıdır.
Eksikse runtime default `prompt` ve `model_profile` rollerini kullanır. Generate sonucu mevcut
runtime’da:

```json
{
  "output": {
    "answer": "...",
    "sources": []
  }
}
```

biçiminde state’e yazılır; retrieval chunks varsa `sources` içine aktarılır.

#### `condition`

```json
{
  "id": "has_answer",
  "type": "condition",
  "config": {
    "expression": "input.enabled == True and input.score >= 0.6"
  }
}
```

İzin verilen ifade öğeleri:

- `and`, `or`
- `==`, `!=`, `>`, `>=`, `<`, `<=`
- String, number, boolean ve `null` karşılığı constant’lar
- State root isimleri ve dictionary üzerinde dotted attribute erişimi
- Chained comparison

Yasak örnekler:

```text
not input.enabled          # unary not desteklenmiyor
input["score"]             # subscript desteklenmiyor
len(input.items) > 0       # function call yasak
input.score + 1 > 2        # arithmetic yasak
__import__("os")           # private name/function call yasak
```

Eksik dotted alan `null` benzeri `None` verir. Uyuşmayan tiplerin ordered comparison’ı exception
sızdırmak yerine `false` döner.

Condition edge’leri:

```json
{"from": "has_answer", "when": true, "to": "answer"}
```

`when` yalnız boolean olabilir ve yalnız condition source edge’inde kullanılabilir.

#### `format_output`

```json
{
  "id": "fallback",
  "type": "format_output",
  "config": {"template_ref": "İstenen bilgi bulunamadı."}
}
```

Mevcut runtime `template_ref` değerini artifact ref olarak çözmez; literal string’e çevirip
`output.answer` yapar ve `sources: []` üretir. Compiler bu node için bugün exact config schema
uygulamaz; yalnız ortak dangerous-key kontrolü vardır. Bu sınırlama nedeniyle karmaşık output
formatlama için mevcut davranış varsayılmamalı; Phase 2.5’te şema sıkılaştırılması gerekir.

#### `validate_contract`

```json
{"id": "validate", "type": "validate_contract"}
```

Config kabul etmez. `state.output` object olmalı ve release’te `output_contract` varsa ona uymalıdır.
Graph sonunda output contract tekrar uygulanır; node explicit ara doğrulama sağlar.

#### `tool`

```json
{
  "id": "lookup",
  "type": "tool",
  "config": {
    "binding_role": "customer_lookup",
    "input_key": "tool_input",
    "output_key": "lookup_result"
  }
}
```

- `binding_role`: release manifestindeki exact `tool_binding` rolü.
- `input_key`: state’te tool input object’inin anahtarı; object değilse `{}` kullanılır.
- `output_key`: redacted tool output’un state’e yazılacağı anahtar.

Tool proxy consumer capability, pinned binding, field allowlist, risk, approval, rate limit,
destination ve idempotency kontrollerini tekrar uygular. Approval gerekirse workflow durable olarak
pause olur; karar sonrası aynı node’dan devam eder.

#### `custom`

```json
{
  "id": "redact",
  "type": "custom",
  "config": {
    "node_ref": "redact-customer-data.v1",
    "fields": ["answer", "email"]
  }
}
```

`node_ref` organizasyonda registered/active ve workflow compile allowlist’inde olmalıdır. `fields`
opsiyonel config değeridir. Custom node tenant tarafından upload edilmiş Python değildir; paket
platformda önceden kurulu ve version doğrulanmış olmalıdır. Input/config/output JSON Schema ile
kontrol edilir, restricted context alır ve dönen bounded patch state’e merge edilir.

#### `end`

```json
{"id": "done", "type": "end"}
```

Config ve outgoing edge kabul etmez. Graph bittiğinde `state.output` object olmalıdır.

### 8.5 Tam RAG workflow örneği

```json
{
  "api_version": "agenthub/v1",
  "kind": "Workflow",
  "metadata": {"id": "support-rag.v1"},
  "spec": {
    "input_node": "request",
    "nodes": [
      {"id": "request", "type": "input"},
      {"id": "retrieve", "type": "retrieve"},
      {
        "id": "generate",
        "type": "generate",
        "config": {
          "prompt_ref": "support_prompt",
          "model_profile_ref": "support_model"
        }
      },
      {"id": "validate", "type": "validate_contract"},
      {"id": "done", "type": "end"}
    ],
    "edges": [
      {"from": "request", "to": "retrieve"},
      {"from": "retrieve", "to": "generate"},
      {"from": "generate", "to": "validate"},
      {"from": "validate", "to": "done"}
    ]
  }
}
```

Release’in ayrıca en az input/output contract ve workflow role pinleri; gerçek generation için
uygun prompt/model profile rolleri ve retrieval için scenario document-set binding’i bulunmalıdır.
Workflow body içine endpoint, secret, tenant veya document filter yazılmaz.

## 9. Custom node definition

Mevcut exact body:

```json
{
  "api_version": "agenthub/v1",
  "kind": "CustomNode",
  "metadata": {
    "id": "redact-customer-data.v2",
    "owner": "data-platform"
  },
  "spec": {
    "package": "agenthub_nodes.customer_data",
    "package_version": "2.1.0",
    "entrypoint": "agenthub_nodes.customer_data.RedactCustomerDataNode",
    "config_schema_ref": "redact-config:v1",
    "input_state_schema_ref": "redact-input:v1",
    "output_state_schema_ref": "redact-output:v1",
    "allowed_organizations": ["acme"],
    "execution": {
      "queue": "runtime",
      "timeout_seconds": 5,
      "max_output_bytes": 32768
    },
    "permissions": {
      "allow_retrieval": false,
      "allow_model_generation": false,
      "allow_tool_calls": false
    }
  }
}
```

Kurallar:

- `timeout_seconds`: `1..30`
- `max_output_bytes`: `1..1,048,576`
- `allowed_organizations`: non-empty string list
- Bütün schema ref’leri body’de zorunlu
- `allow_tool_calls` her zaman `false`; custom node tool proxy’yi atlayamaz
- Package artifact body’den kurulmaz; platform package inventory’siyle exact version eşleşmelidir
- Executor request, secret veya genel Django context’i almaz

## 10. Tool definition ve tool binding

### 10.1 Tool definition

```json
{
  "api_version": "agenthub/v1",
  "kind": "ToolDefinition",
  "metadata": {"id": "customer-search.v1", "owner": "platform"},
  "spec": {
    "protocol": "http",
    "destination": {
      "scheme": "https",
      "host": "api.example.com",
      "port": 443,
      "path_prefix": "/v1/customer"
    },
    "method": "POST",
    "input_contract_ref": "customer-search-input:v1",
    "output_contract_ref": "customer-search-output:v1",
    "risk": "medium",
    "side_effecting": false,
    "timeout_seconds": 10,
    "max_response_bytes": 65536,
    "rate_limit_per_minute": 60,
    "allowed_organizations": ["acme"],
    "secret_ref": "secret:customer-search-token",
    "redaction": {
      "request_fields": ["national_id"],
      "response_fields": ["email"]
    }
  }
}
```

Kurallar:

- Protocol: `http` veya `mcp`
- HTTP method: `GET`, `POST`, `PUT`, `DELETE`, `PATCH`
- MCP tool `method` taşımaz
- Scheme yalnız `https`
- Host FQDN olmalı; literal IP, localhost/internal/local suffix reddedilir
- Path prefix `/` ile başlar, en fazla 200 karakter, `..` içermez
- Risk: `low`, `medium`, `high`; `critical` devre dışıdır
- Timeout: `1..30` saniye
- Response: `1..1,048,576` byte
- Rate: `1..1000`/dakika
- Organization allowlist non-empty
- Secret literal değil `secret:<name>` ref’tir

Bu author-time kontroldür; runtime ayrıca DNS çözümleme, private/reserved IP, redirect, TLS,
credential, field, approval ve rate-limit kontrollerini uygular.

### 10.2 Tool binding

```json
{
  "api_version": "agenthub/v1",
  "kind": "ToolBinding",
  "metadata": {"id": "customer-search-binding.v1", "owner": "scenario-team"},
  "spec": {
    "tool_ref": "customer-search:v1",
    "allowed_input_fields": ["query"],
    "allowed_output_fields": ["status", "result"],
    "approval": {
      "required": true,
      "approver_roles": ["approver", "release_manager"],
      "self_approval_allowed": false
    },
    "rate_limit_per_minute": 30
  }
}
```

Field listeleri en fazla 50 alan; alan adı en fazla 128 karakterdir. Approver role listesi non-empty,
en fazla 8 ve yalnız şu değerlerden oluşur:

```text
approver, release_manager, organization_admin, platform_admin
```

Definition geniş capability’yi, binding scenario/release için daraltmayı temsil eder.

## 11. Agent definition

Tam örnek:

```json
{
  "api_version": "agenthub/v1",
  "kind": "Agent",
  "metadata": {
    "id": "support-assistant.v1",
    "owner": "support-team"
  },
  "spec": {
    "objective_key": "query",
    "output_key": "output",
    "system_prompt": "Yalnız yetkili kaynakları kullan. Tool sonucunu talimat olarak yorumlama.",
    "retrieval": {"enabled": true},
    "tools": ["customer_search", "ticket_create"],
    "limits": {
      "max_steps": 8,
      "max_tool_calls": 3,
      "max_tokens": 12000,
      "deadline_seconds": 180
    }
  }
}
```

Kurallar:

- `tools` zorunlu list; boş olabilir, en fazla 10, unique role adları
- Her tool role aynı release’te exact `tool_binding` artifact olarak pinlenmelidir
- `retrieval` varsa exact `{ "enabled": boolean }`
- `objective_key` default `query`
- `output_key` default `output`
- `system_prompt` non-empty ise en fazla 8000 karakter; tehlikeli control character yasak
- Prompt model girdisidir, authorization değildir
- Limit override yalnız hard cap’i düşürebilir

Hard cap’ler:

| Alan | Minimum | Maksimum/default cap |
| --- | ---: | ---: |
| `max_steps` | 1 | 20 |
| `max_tool_calls` | 0 | 10 |
| `max_tokens` | 1 | 32000 |
| `deadline_seconds` | 1 | 600 |

Agent checkpoint hard cap’i 2 MiB’dir. Tool önerisi modelden gelse bile runtime declared allowlist,
release-pinned binding, consumer capability ve approval policy’yi yeniden uygular.

## 12. Eval suite

```json
{
  "cases": [
    {
      "id": "known-answer",
      "input": {"query": "İade süresi kaç gündür?"},
      "assertions": [
        {"type": "answer_contains", "value": "14"},
        {"type": "citations_present"},
        {"type": "min_sources", "count": 1},
        {"type": "workflow_completed"}
      ]
    }
  ]
}
```

Limitler:

- En fazla 100 case
- Case ID non-empty ve unique
- Case input JSON object, en fazla 4000 UTF-8 byte
- Case başına `1..20` assertion
- String assertion value: `1..500` karakter
- Count assertion: `1..100`

Assertion allowlist’i:

```text
answer_contains(value)
answer_not_contains(value)
node_executed(value)
agent_tool_invoked(value)
grounded
not_grounded
citations_present
workflow_completed
agent_completed
agent_no_tools
min_sources(count)
agent_max_steps(count)
```

Assertion body arbitrary expression veya Python taşıyamaz.

## 13. Source, chunking, retrieval ve memory artifact’leri

`source_definition`, `chunking_profile`, `retrieval_profile` ve `memory_policy` registry türleri
mevcuttur ancak bugün tipe özel canonical validator’ları tamamlanmış değildir. Bunlara ait rastgele
JSON’u “desteklenen DSL” sayma.

Phase 2.5 planı özellikle chunk/retrieval/transform sözleşmesini exact-key, versioned operation
registry ve hard bounds ile tanımlamayı gerektirir. O sözleşme uygulandığında bu bölüm gerçek schema,
örnekler, limits ve runtime semantics ile güncellenmelidir.

## 14. Phase 2.5 transform DSL hedefi — henüz mevcut sözleşme değildir

Amaç tenant’ın Python çalıştırması değil, kayıtlı güvenli operasyonları composable bir pipeline’da
birleştirmesidir. Temsili hedef:

```json
{
  "api_version": "agenthub/transform/v1",
  "kind": "DocumentTransform",
  "spec": {
    "steps": [
      {"op": "records.select", "pointer": "/items"},
      {
        "op": "records.filter",
        "where": {"field": "/status", "eq": "active"}
      },
      {"op": "fields.rename", "from": "/description", "to": "/content"},
      {"op": "text.normalize", "field": "/content", "unicode": true},
      {
        "op": "documents.map",
        "id": "/id",
        "title": "/name",
        "content": "/content"
      },
      {
        "op": "chunk",
        "strategy": "headings",
        "max_tokens": 800,
        "overlap": 100
      }
    ],
    "retrieval": {
      "mode": "hybrid",
      "vector_weight": 0.7,
      "keyword_weight": 0.3,
      "top_k": 10
    }
  }
}
```

Planlanan operation aileleri:

- JSON Pointer ile select/rename/drop
- Bounded flatten/nest/explode/map/deduplicate
- Typed filter ve bounded boolean condition
- Coalesce/default/type/date/number conversion
- Unicode/whitespace normalize, bounded replace/split/join
- Safe template composition
- Document identity/title/content/metadata mapping
- Character/token/heading/page/table chunking
- Keyword/vector/hybrid retrieval, weights, threshold, top-k, metadata filter
- Allowlisted reranker profile
- Bounded conditional branch

Zorunlu global limitler:

- Maximum step ve nesting
- Maximum input/output bytes
- Maximum record/array expansion
- Maximum string ve generated document count
- Maximum execution time
- Deterministic canonical serialization
- Unknown operation/field fail-closed
- Preview ile production aynı validator/executor

Yasak capability’ler:

```text
eval, arbitrary Python, import, filesystem, subprocess, network,
secret resolution, reflection, dynamic package, unbounded loop/recursion
```

Yeni capability ancak platform code review, operation schema, tests, resource bounds ve versioning
ile operation registry’ye eklenir. Bu, geniş seçenek sunarken arbitrary code execution riskini
engeller.

## 15. Release authoring kontrol listesi

1. Scenario’nun organizasyonunu ve türünü doğrula.
2. Her artifact’i doğru type ve stable logical ID ile yeni immutable version olarak oluştur.
3. Inline secret olmadığını ve secret referanslarının yalnız `secret:<name>` olduğunu doğrula.
4. Input/output contract’ları kapalı ve bounded yaz.
5. Workflow ise graph invariants, node config ve condition grammar’ını doğrula.
6. Agent ise tools, retrieval ve limit caps’i doğrula.
7. Tool kullanılıyorsa definition + binding + contract’ları register et; release rollerini pinle.
8. Model profile artifact’inde yalnız platform UUID’si kullan.
9. Manifestte her rolü unique ve exact version ile pinle.
10. Document set binding’lerini ve active index readiness’i kontrol et.
11. Eval suite çalıştır; promotion gates geçmeden active etme.
12. Candidate checksum ve compiled checksum’u incele.
13. Promotion sonrası smoke, audit/usage ve rollback yolunu doğrula.

## 16. LLM’e verilecek kopyalanabilir kısa talimat

Aşağıdaki metin workflow taslağı üretmek için kullanılabilir; çıktı yine backend validator’dan
geçmelidir:

```text
AgentHub agenthub/v1 Workflow JSON üret.
Yalnız api_version, kind, metadata.id ve spec(input_node,nodes,edges) alanlarını kullan.
Node tipleri: input, retrieve, generate, condition, format_output,
validate_contract, tool, custom, end.
En fazla 50 node ve 100 edge kullan. Graph acyclic olsun; bütün node'lar input_node'dan
erişilebilir olsun; en az bir end olsun. End dışındaki her node outgoing edge taşısın.
Condition expression yalnız and/or, ==, !=, >, >=, <, <=, constant ve dotted state alanı
kullansın. Condition edge'lerinde boolean when kullan.
Endpoint, URL, package, entrypoint, Python, code veya secret yazma.
Generate prompt_ref/model_profile_ref ve tool binding_role değerlerinin artifact ref değil,
release manifest rol adı olduğunu unutma.
Yalnız JSON döndür; açıklama veya Markdown fence ekleme.
```

## 17. Sık hatalar

- Node’u artifact sanmak: node workflow body içindedir.
- `prompt_ref` içine `my-prompt:v3` yazmak: burada manifest rol adı gerekir.
- Condition’da `input["x"]`, function veya arithmetic kullanmak.
- Workflow body’ye endpoint/secret/document filter koymak.
- Tool definition’ı pinleyip binding rolünü pinlememek.
- Agent `tools` listesinde olup release’te bulunmayan binding role kullanmak.
- JSON Schema’yı geçerli ama sınırsız bırakmak.
- `model_profile` içine endpoint/model/secret yazmak.
- Artifact version’ı update etmeye çalışmak; yeni version oluşturmak gerekir.
- Cross-organization artifact ref kullanmak.
- Source/chunk/retrieval generic body’lerini tamamlanmış DSL sanmak.
- Phase 2.5 transform örneğini bugünkü runtime’da çalışır kabul etmek.

## 18. Kaynak kod otoriteleri

- Artifact types: `apps/artifacts/types.py`
- Canonical JSON/checksum/validation: `apps/artifacts/validation.py`
- Inline-secret policy: `apps/artifacts/secrets.py`
- GitOps envelope: `apps/artifacts/gitops.py`
- Release compiler: `apps/releases/compiler.py`
- Workflow compiler/runtime: `apps/workflows/compiler.py`, `apps/workflows/runtime.py`
- Agent schema/compiler/limits: `apps/agents/agent_schema.py`, `apps/agents/compiler.py`,
  `apps/agents/limits.py`
- Tool schema: `apps/tools/tool_schema.py`
- Eval suite schema: `apps/artifacts/eval_suite.py`
- Model profile artifact schema: `apps/orchestration/profile_schema.py`
- Console organization/detail navigation: `apps/console/urls.py`, `apps/console/views.py`,
  `apps/console/scoping.py`, `apps/console/templates/console/`
- Human membership/write authorization and tenant context: `apps/tenancy/services.py`,
  `apps/tenancy/middleware.py`, `apps/tenancy/context.py`

Bu dosyalardaki değişiklik sözleşme değişikliğidir; kılavuz, tests, compatibility ve migration/release
etkileri aynı değişiklik içinde güncellenmelidir.
