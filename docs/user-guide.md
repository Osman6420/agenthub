# AgentHub — Operator & Workflow Builder User Guide

This guide explains how to operate AgentHub through the console: signing in, navigating
the tenant-scoped surfaces, authoring workflows visually with the Sprint 11 builder, and
taking a scenario from draft to a served release. It is written for tenant operators with
explicit organization, project, scenario, or document-set responsibilities.

> AgentHub is a governed, multi-tenant platform for shipping RAG, workflow, and agent
> scenarios behind a single public API. Everything an operator publishes is an **immutable,
> checksummed artifact** compiled into a **release**; nothing reaches a consumer until it
> passes evaluation and is explicitly promoted.

---

## 1. Signing in

1. Open the console at **`/console/`** (locally `http://127.0.0.1:8000/console/`).
2. You are redirected to **`/console/login/`**. Authenticate with your operator account.
   In production this is your **LDAP / directory** identity; in local development it is a
   Django account. There is no separate builder login — the visual builder reuses this
   same session.
3. After login you land on the **Dashboard** for one validated organization. The last valid
   selection is retained; otherwise the first authorized organization is selected deterministically.

**What you can see and do is decided entirely on the server** from active, unexpired,
exact-scope responsibility assignments. The UI never grants access the backend would deny.

### Responsibilities at a glance

| Scope / responsibility | Can do |
| --- | --- |
| Platform / global administrator | Manage platform and organization shells; recovery superuser remains separate |
| Organization / administrator | Manage members, responsibilities, consumers and safe metadata; does not implicitly edit, release, approve, or read protected document content |
| Organization / auditor | Read safe organization metadata and audit records |
| Project / viewer or administrator | View one project; an administrator manages its structure and may delegate scenario viewer/editor responsibility |
| Scenario / viewer or editor | View one scenario, or edit/test that exact scenario |
| Scenario / release manager | Compile/promote/rollback releases for that exact scenario |
| Scenario / runtime operator | View and control runs for that exact scenario |
| Scenario / approver | View and decide approvals for that exact scenario |
| Document set / metadata viewer, content reader, or manager | Increasing access to one exact document set; never grants scenario/release authority |

Organization membership only establishes tenant affiliation and makes the organization shell
visible. It grants no project, scenario, approval, release, runtime, or protected-content access.

---

## 2. Console surfaces

The authenticated sidebar exposes only task-oriented surfaces supported by the operator's active,
unexpired responsibilities. A hidden link is not an authorization decision: direct routes repeat
the same server-side scope and capability checks. The organization selector always selects exactly
one workspace and changes presentation only; there is no cross-organization console view.

| Surface | Purpose |
| --- | --- |
| **Ana Sayfa** | Seçili organizasyonun özeti, dikkat gerektiren sağlık kayıtları ve son işler |
| **Projeler** | Organizasyon içindeki AI projeleri |
| **Dokümanlar** | Doküman setleri; set ayrıntısında içerik, sürüm, indeks ve kaynak görevleri |
| **İstemciler** | API istemcileri, protokol bilgileri, kimlik bilgileri ve senaryo erişim bağları |
| **Çalıştırmalar** | Mevcut agent, workflow ve recovery yüzeylerine tenant-scoped giriş |
| **Kullanıcılar ve yetkiler** | Rol içermeyen üyelik ve ayrı, tam kapsamlı sorumluluk yönetimi; son organizasyon yöneticisi kaldırılamaz |

Platform yöneticisi **Yeni organizasyon** ile organizasyonu, ilk üyeliği ve zorunlu
organizasyon-yöneticisi sorumluluğunu atomik oluşturur. Yeni proje, doküman seti ve istemci seçili
organizasyondan; yeni senaryo ise açıldığı proje URL'sinden türetilir. Bu formlarda parent tenant
seçicisi bulunmaz ve gönderilen ek parent alanları dikkate alınmaz.

Senaryolar yalnız sahip oldukları proje altında listelenir. **Projeler** içinden projeyi, ardından
senaryoyu açarak organization/project path, aliases, active release, bound document
sets, latest index readiness and consumer access in one page. An authorized author can bind/unbind
sets and grant/revoke retrieval there. These are two distinct gates: a consumer must be bound to
the scenario, and it must separately have retrieval access to each document set. Set-binding
changes require a new release compile; consumer grant changes are enforced at retrieval time.
Artifact, release ve DSL ayrıntıları aynı senaryo bağlamındaki görev bölümlerinden açılır; bunlar
global sidebar katalogları değildir. Eski global GET katalog adresleri güvenli bağlamsal sayfalara
yönlenir; detail ve state-changing route'lar korunur.

Yeni senaryo oluştururken üç başlangıçtan biri seçilir: **Empty Workflow**, **Document Answer** veya
**Agent Loop**. Oluşturma yalnız senaryoya bağlı doğrulanmış bir Studio draft'ı hazırlar; release
yayımlamaz. Logical artifact açıklaması workflow'un sürümler boyunca değişmeyen amacını anlatır.
Studio'da **Yayımla** işlemi ayrıca exact version açıklaması ister; bu metin yalnız o immutable
sürümde ne olduğunu veya neyin değiştiğini açıklar.

Scenario Studio'daki **Yeni prompt** alanı prompt metnini doğrudan düzenler; `prompt_ref` veya elle
hazırlanmış bir artifact ID gerektirmez. **Yeni parçalama / arama profili** alanı da canonical
`chunking/v1` ve `retrieval/v1` alanlarını yapılandırılmış kontrollerle oluşturur. Taslak doğrulanıp
değişiklik açıklamasıyla yayımlandığında yeni immutable exact sürüm oluşur.

**Yeni özet model profil referansı** aktif platform model profillerini güvenli provider/model
özetiyle seçtirir. Tenant artifact'ine yalnız `{profile_id: UUID}` yazılır; endpoint, host, path,
secret, TLS, network veya egress ayarı gösterilmez ve girilemez. Artifact type seçicisi her tür için
bu ekranda yapılandırılmış düzenleme, başka ekranda yönlendirilmiş authoring veya salt-okunur/
desteklenmiyor durumunu nedenleriyle gösterir.

Candidate manifest seçicisinde exact sürüm seçilince gövde ayrıca bir “aç” adımı olmadan otomatik
gösterilir. Prompt metni textarea'da; parçalama ve arama profilleri alan bazlı editörde görünür.
İçerik değişmediyse mevcut exact sürüm eklenir; değiştiyse açıklama zorunlu olur ve yeni immutable
sürüm yayımlanıp aynı manifest rolündeki eski seçimin yerini alır. Viewer içeriği salt okunur görür;
oluşturma, düzenleme ve yayımlama scenario author sorumluluğu gerektirir.

Candidate release hazırlanırken seçim sırası **artifact type → logical artifact → exact version**
şeklindedir. Her seviyenin açıklaması, exact checksum ve daha önce kaç release tarafından pinlendiği
seçimden önce gösterilir. Manifest rolü workflow gereksiniminden veya artifact türünden otomatik
türetilir ve primary akışta ayrıca sorulmaz. Senaryo çağrı bölümündeki kopyalanabilir `curl` örneği, aktif
release'in compiler-supported execution mode'larına göre Chat Completions veya background Responses
biçiminde ve dahili ID yerine senaryo alias'ıyla üretilir.

**Minimum release önerisini getir** yalnız senaryoya açıkça bağlı, tek anlamlı mantıksal artifact'ların
en yeni immutable sürümlerini tarayıcıdaki geçici seçime koyar. Bu öneri yetki vermez, candidate
oluşturmaz ve kanonik ön kontrolü atlamaz. Kaydedilmemiş seçim için **Candidate olarak kaydet**,
**Seçimi sil** ve **Düzenlemeye devam et** seçenekleri görünür; candidate başarıyla oluşana kadar
sayfadan ayrılma uyarısı da korunur. İstemci bağındaki capability başlangıç önerileri de yalnız
checkbox'ları doldurur; sunucu gönderilen exact allowlist ile presetin birebir eşleşmesini doğrular.

Klavye kullanıcıları sayfanın başındaki **Ana içeriğe geç** bağlantısıyla navigasyonu atlayabilir.
Odak göstergesi tüm link/form kontrollerinde görünürdür; geniş tablolar dar ekranda yatay kaydırılır.
Builder 760 px altında palette, canvas ve config panelini dikey sıraya alır. Bu davranışların son
görsel kabulü hedef tarayıcı ve ekran ölçeklerinde deployment öncesi manuel yapılmalıdır.

### Senaryo release ve artifact görünürlüğü

Senaryo detayında aktif release'in rol bazlı exact immutable artifact sürümleri ve son release
geçmişi görünür. **DSL / detay** bağlantısı canonical JSON'u, checksum/provenance bilgisini ve o
exact sürümü pinleyen release'leri read-only gösterir. Workflow artifact'leri için aynı proje ve
logical ID ile eşleşen bir builder draft'ı varsa **Grafikte aç** bağlantısı kullanılır. Draft mutable
çalışma durumudur; aktif release pini değildir. Builder deep-link'i hem organization hem draft'ı
sunucu tarafında mevcut operator scope'una göre doğrular.

Senaryo ve workflow artifact ekranlarındaki kopyalanabilir DSL rehberi compiler limitlerinden
üretilir. Bu rehber bir artifact oluşturmaz ve doğrulama alternatifi değildir; LLM veya insan
tarafından hazırlanan çıktı yine canonical backend validator/compiler üzerinden publish edilmelidir.

### Doküman seti çalışma alanı

Yeni içerik için **Doküman setleri** ekranından önce seti açın. Set detayındaki toplu yükleme alanı
bir istekte en fazla 20 dosya kabul eder; tekil ve toplam byte sınırları deployment ayarlarından
uygulanır. Dosya adı başlık olur; Türkçe karakterler ASCII karşılıklarına dönüştürülerek güvenli ve
stabil bir logical ID üretilir. Aynı dosya adı yeniden yüklendiğinde yeni bir `DocumentVersion` oluşur ve taslaktaki eski
sürümün yerini alır. Yeni taslak, son yayımlanmış set üyeliğini korur.

Exact **Content Reader** veya **Manager**, sete gerçekten pinlenmiş belge sürümünü güvenli metin
önizlemesiyle açabilir ya da ek olarak indirebilir. Önizleme yalnız sınırlı boyutta UTF-8
`text/plain`, Markdown, CSV ve JSON kabul eder ve aktif içeriği çalıştırmaz. İndirme her zaman
`application/octet-stream` ve `attachment` olarak döner. Her başarılı, reddedilen veya başarısız
okuma içerik/object-key olmadan audit edilir; audit yazılamazsa baytlar döndürülmez.

Yükleme doğrudan serve edilmez. Belge sürümü ve exact taslak üyeliği tek transaction içinde
oluşturulur; set dışı yeni belge oluşturma reddedilir. Operatör taslağı açıkça yayımlar, tenant'a
grant edilmiş embedding profiliyle birlikte immutable parçalama ve arama profillerini, isteğe bağlı
OCR profilini ve birlikte seçilen exact özet model/prompt profillerini kullanarak staged build'i
ingestion kuyruğuna gönderir. Karakter, token, heading, sayfa ve tablo parçalama stratejileri
uyumsuz parser/MIME birleşimlerinde güvenli bir compatibility koduyla durur. Özet etkinse türetilmiş
özet ayrı bir `summary` chunk olarak, checksum ve exact model/prompt provenance ile saklanır; hata
durumunda build bunu sessizce atlamaz.

Exact document-set manager staged indeks formunu yeniden açtığında son preparation seçimlerinin
altısı da otomatik seçili gelir. Bir seçim değiştirildiğinde yalnız o embedding, parçalama, arama,
OCR, özet model veya özet prompt sürümünün güvenli ayrıntısı açılır. Embedding/OCR kartlarında host,
path, secret, TLS ve egress ayarları hiçbir zaman gösterilmez; yalnız platform yöneticisi ayrı
platform yönetim bağlantısını görür. Exact Document Set Manager parçalama, arama, özet prompt ve
özet model artifact'lerinin seçili içeriğini aynı doküman-seti sayfasında düzenleyebilir veya yeni
logical artifact ekleyebilir. Değişiklik açıklaması zorunludur; yayın yeni immutable exact sürüm
oluşturup yalnız bu açık formda seçer. Bağlı senaryolardaki author sorumluluğu bu yetkiyi vermez ve
gerekli değildir; aynı set birden fazla senaryo tarafından paylaşılabilir. Özet model artifact'inde
yalnız aktif platform profil UUID'si seçilir. Build isteği bütün profil ve artifact kimliklerini
sunucuda tenant ve exact document-set kapsamıyla yeniden doğrular.

Arama profili `keyword`, `vector` veya `hybrid` seçebilir. Keyword ve vector aynı immutable,
tenant-scoped PostgreSQL store ve aynı ACL/tombstone filtresini kullanır. Hybrid sonuçlar sabit
weighted reciprocal-rank fusion sözleşmesiyle birleştirilir; component rank/score ve fused score
teknik tanıda ayrı gösterilir. Ham BM25 ve vector skorları tek bir yüzde gibi sunulmaz.

Arama profiline `summary_document_top_k` eklendiğinde iki aşamalı doküman yönlendirme açılır.
Örneğin değer `10` ise ilk aşama yalnızca özetlerde en alakalı on exact doküman sürümünü seçer;
ikinci aşama aynı sorguyu yalnızca bu dokümanların gerçek içerik parçalarında çalıştırır.
`max_chunks_per_document` (varsayılan `3`, en fazla `10`) tek bir dokümanın sonuçları doldurmasını
önler. Nihai grounding sonuçları her zaman `content` parçasıdır; özet yalnızca güvenli yönlendirme
sinyalidir. Yetkili bir özet eşleşmezse sistem boş sonuç vermek yerine doğrudan content aramasına
döner. Her iki aşama aynı tenant, grant, pinned set-version, active-index ve tombstone kapsamındadır.

Retrieval profile sözleşmesindeki `metadata_filter` alanı Faz 3 için ayrılmıştır ve şu anda
sonuçları değiştirmeyen belgelenmiş bir no-op'tur. Tenant, yetki veya sonuç daraltması yaptığı
varsayılmamalıdır. Metadata şeması, ingestion lineage'ı, PostgreSQL indeksleri ve bütün arama
modlarında ortak uygulama Faz 3'te birlikte teslim edilecektir.

İndeks hazır
olduğunda yalnız exact document-set manager sorumluluğu belge/index adımlarını yürütebilir;
release yaşam döngüsü exact scenario release-manager sorumluluğunda kalır.
Çalışma alanı taslak, yayımlanmış set, building/promotable indeks ve aktif indeks durumlarını gerçek
önkoşullardan hesaplayarak ayrı gösterir. Exact preparation seçimi sonraki yayımlanan sürümler için
otomatik staged hazırlığı açabilir; bu otomasyon aktif indeks pointer'ını değiştirmez. Set, belge ve
indeks geçmiş sürümleri deep link olarak açılabilir. Manuel veya otomatik hazırlık hiçbir zaman
otomatik promotion yapmaz.

### Connector kaynakları ve periyodik güncelleme

Doküman seti çalışma alanındaki **Kaynakları yönet** bağlantısı Confluence ve generic REST
kaynaklarını aynı set altında gösterir. Ekran yalnız güvenli profil/contract kimliğini, son run
durumunu ve değişen/değişmeyen sayaçlarını gösterir; hedef host, credential/secret, REST input
değerleri ve doküman içeriği gösterilmez.

Author, platform yöneticisinin exact document-set grant verdiği Confluence/REST profilini seçerek
kaynak oluşturabilir. REST için kapalı JSON mapping sözleşmesi immutable revizyon olarak oluşturulur;
isteğe bağlı sentetik response preview ağ isteği yapmadan pointer/metadata eşleşmesini doğrular ve
içeriği response'a yansıtmaz. Kaynak **Şimdi çalıştır** ile ingestion kuyruğuna alınabilir veya 15
dakika–7 gün aralığında periyodik çalıştırılabilir. Değişiklik sonrası `draft_only` ve `stage_only`
author seçenekleridir; `promote_if_safe` yalnız release manager tarafından, sete zaten bağlı exact
senaryolar için seçilebilir.

---

## 3. The end-to-end scenario lifecycle

A scenario goes from authoring to a served release along one governed path. The visual
builder plugs into the **authoring** step for workflows; everything downstream is
unchanged.

```
 Author artifacts            Compile           Evaluate         Release
 (GitOps import OR    ─▶  candidate release ─▶ run eval  ─▶  promote / canary ─▶  Serve via
  console / builder)       (compile_release)   (run_eval)     (fail-closed)       /v1 API
                                                                   │
                                                                   └─▶ rollback (atomic)
```

1. **Register** an organization, project, and scenario (+ a stable alias).
2. **Author** the scenario's artifacts — input/output contracts, prompt, policy, model
   profile, sources, eval suite, and (for workflow scenarios) the **workflow definition**.
   Author via GitOps import (`import_gitops`), the console create forms, or the **visual
   builder** (workflows).
3. **Ingest** source documents if the scenario uses retrieval; a worker builds a staged
   pgvector index.
4. **Compile** a candidate release (`compile_release`) that pins exact artifact versions
   (and indexes/tool bindings) by role.
5. **Evaluate** the candidate against its pinned eval suite (`run_eval`) — the report is
   redacted and audited.
6. **Promote** (`promote_release`) — fail-closed: requires a passing eval bound to the
   pinned suite and ready, tenant-owned indexes. Or run a **consumer-scoped, time-bounded
   canary**. The release detail page is the contextual surface for eval, canary, promotion, stop,
   and rollback; every action is reauthorized against the exact scenario.
7. **Activate the scenario explicitly** from its scenario page after the active release, alias,
   and release-pinned served indexes are ready. Promotion never activates a draft as a side effect.
8. **Serve**: an authorized consumer calls `POST /v1/responses`,
   `POST /v1/chat/completions`, or `GET /v1/runs/{uuid}`. The gateway issues a signed
   short-lived execution context and the
   runtime answers with the active (or canary) release.
9. **Disable or rollback**: disabling the scenario stops new calls without deleting the release;
   `rollback_release` atomically restores the superseded release if needed.

Scenario runtime operators use the scenario page to pause/resume that exact scenario and run detail
to request cooperative cancellation of one exact run. Platform/organization emergency controls stay
on the Runs page and always dominate narrower controls.

---

## 4. The visual workflow builder (Sprint 11)

The builder is a drag-and-drop canvas for authoring **workflow definitions**. It produces a
**versioned DSL** — not a runtime graph — and publishing routes through the *same* compiler
and release pipeline as GitOps. The builder never exposes tool endpoints or secrets.

Open it from the **Builder** nav entry (`/console/builder/`).

### 4.1 Choosing an organization and draft

- Pick an **Organization** (only those in your scope appear).
- The **Drafts** list shows existing workflow drafts for that org. Click **Open** to edit
  one, or use **New draft** (name + `logical_id`) to start one. `logical_id` is the target
  artifact id used when you publish.
- If you lack the authoring role for the org, the builder loads in **read-only** mode: you
  can view and validate, but Save/Publish and canvas edits are disabled.

### 4.2 Building the graph

- **Node palette** (left): drag a node onto the canvas, or click it to add. Node types
  come from the backend and include `input`, `retrieve`, `generate`, `condition`,
  `format_output`, `validate_contract`, `tool`, `custom`, and `end`.
- **Edges**: drag from a node's right handle to another node's left handle. Edges out of a
  **condition** node are auto-typed as the `true` then `false` branch. You cannot draw an
  edge out of an `end` node or a self-loop.
- **Configuration panel** (right): select a node to edit its config. Fields are generated
  from the backend schema:
  - a **tool** node picks a **binding role** from a dropdown (the tool's endpoint and
    credentials are never shown — only the role name and whether it needs approval);
  - a **custom** node picks an organization-allowlisted node ref;
  - a **condition** node takes a bounded boolean expression.

### 4.3 Validate, save, publish

- **Validate** sends the current graph to the backend compiler. Problems are shown as a
  banner and the offending node is highlighted in red. Validation runs the *same* checks as
  publishing (including inline-secret rejection) and never persists anything.
- **Save** stores your draft. An **unsaved changes** badge appears whenever the canvas
  differs from the last save, and the browser warns you before you navigate away with
  unsaved work.
- **Publish** creates an **immutable `workflow_definition` artifact version** through the
  shared authoring path. Publishing does not itself deploy anything — you then compile,
  evaluate, and promote a release exactly as with any other artifact (§3).

> The builder is a convenience layer. All validation, authorization, and publishing happen
> on the server; the canvas cannot bypass a single control.

---

## 5. Serving traffic (consumer API)

Consumers authenticate with a **bearer token** (created by an operator via
`create_consumer_token`) and are authorized per scenario alias + capability.

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/responses` | Canonical sync/background workflow invocation; `model` is the bound scenario alias |
| `POST /v1/chat/completions` | OpenAI-compatible synchronous adapter for sync-capable workflows |
| `GET /v1/runs/{uuid}` | Poll a run's redacted status/output |
| `POST /v1/runs/{uuid}/cancel` | Idempotently request cancellation (consumer/tenant scoped) |
| `GET /v1/health/live` | Unauthenticated liveness probe |

Background invokes require an `Idempotency-Key` header. Every call is rate-limited per
consumer, validated against the release input contract, and recorded as a usage event and
audit entry. REST credentials use HTTPS endpoints; MCP credentials use authenticated **MCP**
ingress and cannot be exchanged across protocols. OpenAI-compatible history is text-only, bounded
and not stored as a server-side conversation. Use Responses for every workflow; set
`background: true` plus an `Idempotency-Key` when the compiled graph is background-only. Streaming,
multimodal inputs, client tools/functions and request-side output-contract overrides are rejected.

### Human approval for high-risk tools

If a workflow or agent needs a **high-risk, side-effecting** tool, the run **pauses**
(`waiting_approval`) and an entry appears under **Tool approvals**. An **approver** (a
different person from the requester — separation of duties) approves or rejects it; the run
then resumes or fails closed. Approvals expire after 30 minutes. Operators can also use
`list_tool_approvals` / `decide_tool_approval` / `cancel_tool_invocation`.

---

## 6. Management commands

Run from the repo root in the project virtualenv. Common commands:

| Command | Purpose |
| --- | --- |
| `import_gitops` / `export_gitops` | Import/export artifacts as YAML (GitOps) |
| `import_control_plane` | Idempotently import orgs/projects/scenarios/aliases/consumers/bindings |
| `validate_artifacts` | Validate artifact bodies (schema, secrets, compilation) |
| `compile_release` | Compile a candidate release (`--promote` is fail-closed) |
| `run_eval` | Run a candidate against its pinned eval suite in isolation |
| `promote_release` / `rollback_release` | Promote (fail-closed) / atomically roll back |
| `start_canary` / `stop_canary` | Consumer-scoped, time-bounded canary routing |
| `create_consumer_token` | Mint a hashed consumer bearer token |
| `start_ingestion` / `retry_ingestion` | Drive the ingestion pipeline |
| `register_ocr_profile` / `grant_ocr_profile` | Platform-admin registration and tenant grant for the async OCR endpoint |
| `build_staged_index --ocr-profile-id <uuid>` | Build a document-set index with image-only/mixed-PDF OCR fallback |
| `register_confluence_profile` / `grant_confluence_profile` / `disable_confluence_profile` | Platform-admin lifecycle for an immutable Confluence Data Center profile |
| `create_confluence_source` | Create an author-owned source bound to one granted profile and one document set |
| `sync_confluence_source` | Queue a governed incremental snapshot sync |
| `register_rest_profile` / `grant_rest_profile` / `disable_rest_profile` | Register, grant or disable a public-only immutable REST destination profile |
| `create_rest_contract` / `create_rest_source` / `sync_rest_source` | Validate a closed JSON mapping, bind exact inputs, and queue a REST snapshot |
| `configure_connector_schedule` | Configure periodic Confluence/REST refresh and its on-change action |
| `list_tool_approvals` / `decide_tool_approval` / `cancel_tool_invocation` | Tool approvals |
| `list_agent_runs` / `cancel_agent_run` | Agent run operations |

OCR profiles hold an allowlisted hostname, `/api/v1` base path, bounds and a `secret:<name>`
reference; the real bearer value is injected as `OCR_SECRET_<NAME>`. A build without
`--ocr-profile-id` performs no OCR egress and fails closed on image-only/mixed PDFs. OCR Markdown is
persisted in tenant object storage and checksumed before the remote result is acknowledged.

Confluence is disabled until deployment supplies a `CONFLUENCE_NETWORK_POLICIES` private-CIDR map,
corporate CA trust, and the referenced `CONFLUENCE_SECRET_<NAME>` bearer PAT. Register the immutable
platform profile first, grant it to the exact organization + document set, create the source with
numeric root page IDs, then queue sync. A successful sync creates a **draft** document-set candidate;
it never builds, publishes, or promotes automatically. Copied pages use AgentHub ACLs, not
Confluence per-user ACLs. Its schedule defaults to `draft_only`.

Generic REST is also disabled by default. A platform admin registers a public-HTTPS profile and
injects any credential as `REST_PULL_SECRET_<NAME>`, then grants the profile to one organization +
document set. An author supplies a version-1 JSON contract and exact inputs. The contract maps
bounded GET or profile-approved read-only POST JSON with RFC 6901 pointers, but cannot choose a URL,
header or secret or execute code/templates. Compatible refresh builds reuse unchanged vectors.
`promote_if_safe` is opt-in, release-manager-targeted, eval-gated and candidate-idempotent; failure
leaves the previous active release served. Promotion targets use the exact repeated command form
`--scenario <project-slug>/<scenario-slug>`; a scenario slug alone is intentionally rejected.

---

## 7. Running it locally

Prerequisites: PostgreSQL/pgvector and Redis (the Docker Compose stack), the `.venv`
(Python 3.13) with dependencies installed, and — for the builder UI — the built frontend
bundle.

```powershell
# 1. Build the workflow builder frontend (first time / after frontend changes)
npm --prefix frontend ci
npm --prefix frontend run build   # writes apps/builder/static/builder/

# 2. Apply migrations to the local database
$env:DJANGO_SETTINGS_MODULE = 'config.settings.local'
$env:DATABASE_URL = 'postgres://agenthub:agenthub@localhost:5432/agenthub'
$env:REDIS_URL = 'redis://localhost:6379/0'
.venv\Scripts\python.exe manage.py migrate

# 3. Start the app on port 8000 (runserver serves the static builder bundle in DEBUG)
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Then open `http://127.0.0.1:8000/console/`. Asynchronous workflow/agent runs additionally
require a Celery worker (`celery -A config worker -Q runtime`); the console, builder, and
synchronous RAG work without it.

See [`docs/security-overview.md`](security-overview.md) for how and why the platform is
safe and secure.

# Governed release inputs and platform setup (Phase 2.9 Part 4)

An exact Scenario editor opens the scenario page and uses **Input contract**, **Output contract**,
or **Eval suite** under **Governed release girdileri**. The form starts with a safe example, validates
canonical JSON/JSON Schema/eval rules, rejects inline secrets, and creates the next immutable version
in that exact scenario's namespace. Success returns to the scenario and shows type, version,
description, and a short checksum. It does not create or promote a release; the release manager pins
an exact version in the separate candidate-release flow.

Only a platform administrator sees **Platform kurulumu**. That workspace can register immutable
model, embedding, Confluence, and REST profile revisions, disable an active revision, grant an
embedding profile to an organization, or grant a connector profile to an exact document set.
Destinations and secret references are deliberately absent from the inventory. A profile row alone
does not authorize egress: deployment allowlists/network policy, secret resolution, explicit grants,
tenant source configuration, and runtime gates must still pass. Model selection remains the existing
platform/deployment-governed flow rather than tenant self-service.

Embedding profiles continue to declare the exact stored vector geometry. A profile configured as
`halfvec` with `dimensions=4000` explicitly accepts provider vectors longer than 4,000 by validating
the full response, retaining the first 4,000 components, and then normalizing the retained vector.
Short output and every other dimension mismatch fail closed. Operators must use a new immutable
profile revision and staged evaluation before promoting a truncated index because prefix truncation
can change retrieval quality.

On a document set's **Kaynaklar** page, a manager sees an actionable readiness warning for each
missing connector grant. After a platform grant, only the logical profile/revision label becomes
selectable. The manager may validate/create a closed REST mapping and bind a source without exposing
the endpoint, credential reference, or bound input values. **Şimdi çalıştır** is the separate action
that can initiate egress; profile registration, grant, preview, mapping creation, and source creation
do not call the external system.
# Live chat provider (Phase 2 P1)

The default runtime remains deterministic. An operator may opt into the real
`apps.orchestration.providers.OpenAICompatibleModelProvider` only after an environment-specific
egress approval. Platform admins register an immutable profile with
`manage.py register_model_profile`; scenario artifacts contain only the returned profile UUID.
They never contain a URL, credential, secret selector, or TLS option. Credentials are injected at
runtime through the corresponding `MODEL_SECRET_<NAME>` environment variable. Do not enable the
provider until the approved endpoint/network policy and secret are present.

# AI-assisted artifact authoring (Phase 2 P10.1/P10.2)

The builder can generate an untrusted workflow, input-contract or output-contract candidate from a
bounded description. This feature is disabled unless operations sets
`AI_AUTHORING_MODEL_PROFILE_ID` to an approved active immutable model profile. Authors select an
exact project and type, generate the candidate, inspect canonical diagnostics, then use the separate
transfer action. Workflow candidates enter `WorkflowDraft` and open in the graph editor. JSON Schema
input/output candidates enter a tenant/project-scoped `ArtifactDraft` and open in the Turkish JSON
editor, where they can be revalidated, updated or deleted.

An exact Scenario editor sees the Studio AI planner even without organization-wide write authority.
Generation and repair produce only an in-memory candidate; explicit accept is required before a
mutable draft exists, and publish remains a separate action. A malformed, ambiguous, deep, or
oversized provider response creates nothing. If the UI says the provider result is unknown, do not
retry blindly; use the request ID to ask an operator to check the audit/transport outcome first.

Each type uses a server-owned immutable prompt contract with a stable ID, revision and SHA-256
checksum. `AI_AUTHORING_CONTRACT_REVISION` can select only a reviewed revision present in the code
registry; callers cannot submit prompt text or select a revision. Tool, binding, model, source,
custom-node and agent candidates are denied before model egress. Generic artifact drafts have no
publish endpoint in P10.2. Generation and transfer do not create an immutable artifact, compile a
release, run an evaluation, promote, or execute anything. Descriptions and raw model responses are
transient and excluded from audit/log content. Live activation still requires the environment's
endpoint, CA, secret, firewall, privacy and cost approval.
