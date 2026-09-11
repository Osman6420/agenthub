# Doğrulama: kapsamlı canlı uygulama QA — 2026-09-04

## Yönetici özeti

Değerlendirme mevcut, kirli çalışma ağacına ve çalışan yerel Compose ortamına karşı yapıldı.
Uygulamanın temel mimarisi, operatör yolculukları, doküman/RAG yaşam döngüsü, REST tüketici
sözleşmesi, worker yürütmesi ve responsive arayüzü çalıştırılarak doğrulandı. İzole 64 boyutlu
deterministik bir RAG hattı bir gerçek test PDF'iyle uçtan uca başarıyla tamamlandı.

Uygulama bütünü için sonuç **doğrulanmadı / yayın engelli** durumundadır. Ana nedenler:

1. Canlı KAP doküman seti aktif ve hazır görünmesine rağmen çalışma zamanı embedding sağlayıcısı
   ile indeks geometrisi uyumsuzdur ve tek seferlik retrieval isteği `DIMENSION_MISMATCH` ile
   HTTP 500 üretir.
2. Zorunlu Playwright kapısı 6 testten 4'ünde güncel kullanıcı arayüzü ile eski beklentiler
   uyuşmadığı için başarısızdır.
3. Python type-check 3 dosyada 7 hata vermektedir.
4. Yerel Compose tüm ana portları tüm host arayüzlerine açarken Django `DEBUG=True`, Redis
   parolasız ve MinIO varsayılan geliştirme kimlikleriyle çalışmaktadır. Güvenilmeyen bir ağa
   bağlı hostta bu konfigürasyon yüksek risklidir.

Bu görev ürün kodunu düzeltmemiştir. Bulgular ayrı, onaylı uygulama işleri olarak ele alınmalıdır.

## Uygulamayı anlama

AgentHub, Django 5.2 tabanlı modüler bir monolittir. PostgreSQL/pgvector kalıcı veri ve vektör
katmanını, Redis kuyruk/cache katmanını, MinIO doküman baytlarını ve ayrı Celery runtime,
ingestion ve evaluation worker'ları asenkron işleri sağlar. React/Vite tabanlı Scenario Studio,
Django operatör konsolunun workflow yazım yüzeyidir.

Temel kullanım modeli şöyledir:

1. Organizasyon ve proje içinde bir senaryo tanımlanır.
2. Dokümanlar immutable sürümler halinde setlere alınır; set sürümü yayımlanır.
3. Exact embedding/chunking/retrieval profilleriyle staged indeks oluşturulur ve ayrı yetkiyle
   aktif edilir.
4. Scenario Studio'da `agenthub/v1` workflow hazırlanır; graph ve JSON aynı içeriği temsil eder.
5. Exact artifact sürümlerinden candidate release derlenir, değerlendirilir ve aktif edilir.
6. REST veya MCP tüketicisi yalnız kendi protokolü, senaryo bağı, capability'si ve doküman-set
   grant'i kapsamında çağrı yapar.
7. Run, RunEvent, UsageEvent ve append-only AuditEvent kayıtları operasyon izini oluşturur.

Yetkilendirme organizasyon rolünden ibaret değildir. Proje, senaryo ve doküman seti
sorumlulukları exact kaynak düzeyindedir; örneğin organization admin ham doküman okuma yetkisini
otomatik almaz. Canlı testte bu ayrım gözlendi.

## Ortam ve başlangıç durumu

- Canonical dosya: `deploy/compose/docker-compose.yml`.
- Sağlıklı servisler: PostgreSQL, Redis, MinIO; çalışan roller: web, runtime worker, ingestion
  worker, evaluation worker ve beat.
- Liveness: `GET /v1/health/live` → HTTP 200, `{"status":"ok"}`.
- Ingestion preflight: contract 3, config checksum mevcut, uyumlu worker bulundu.
- Migration `ingestion.0016_scope_staged_job_checksum_constraint_to_active_states` canlı
  veritabanında uygulanmıştı.
- Worker'lar, bind-mounted güncel kaynak kodunu yüklemeleri için veri kaybetmeden yeniden
  başlatıldı; sonrasında health ve preflight tekrar başarılı oldu.
- Canlı dış yetenekler: gerçek model sağlayıcısı kapalı, gerçek embedding sağlayıcısı kapalı,
  AI authoring profili yok, MCP kapalı, LLM judge kapalı. OpenAI-compatible REST açıktır.
- `METRICS_ENABLED=True`, fakat metrics bearer token tanımlı olmadığından endpoint fail-closed
  HTTP 404 döndürmektedir.
- Görev başlangıcında çalışma ağacı zaten kirliydi. Gözlenen davranışlar base commit'e tek başına
  atfedilmemiştir.

## Otomatik doğrulama sonuçları

| Kontrol | Sonuç | Kanıt/yorum |
| --- | --- | --- |
| Ruff format | PASS | `ruff format --check apps config`: 485 dosya zaten formatlı |
| Ruff lint + güvenlik kuralları | PASS | `ruff check apps config`; yapılandırılmış `S`/Bandit-benzeri kurallar dahil |
| Mypy | **FAIL** | 474 dosya kontrol edildi; 3 dosyada 7 hata |
| Django system check | PASS | Explicit `config.settings.test` ile sorun yok |
| Migration drift | PASS | `makemigrations --check --dry-run`: değişiklik yok |
| Python bytecode | PASS | `compileall apps config` |
| SQLite tam pytest | PASS | 1.330 passed, 66 skipped; 251,71 saniye |
| PostgreSQL/pgvector tam pytest | CONDITIONAL FAIL | 1.383 passed, 5 skipped, 8 failed; tüm failure'lar canlı-local kapalı MCP/metrics bayrakları nedeniyle 404 |
| PostgreSQL hedefli MCP/metrics | PASS | Etkin feature-flag konfigürasyonuyla 14 passed; 24,79 saniye |
| Frontend bağımlılık kurulumu | PASS/WARN | `npm ci` başarılı; geliştirme ağacında bir high advisory |
| Frontend Vitest | PASS | 13 test dosyası, 58 test; 5,89 saniye |
| Frontend typecheck/build | PASS | `tsc --noEmit` + Vite build; 187 modül |
| NPM production audit | PASS | `npm audit --omit=dev`: 0 vulnerability |
| NPM full audit | **FAIL** | Dev-only zincirde 1 high `nanoid` advisory |
| Locked Playwright gate | **FAIL** | 6 test: 2 passed, 4 failed; yaklaşık 1,6 dakika |
| Diff whitespace check | PASS | `git diff --check` |

### Mypy ayrıntısı

- `apps/identity/tests/test_assignment_migration.py:48`: lazy model referansı tip uyuşmazlığı.
- `apps/catalog/tests/test_part_3_owner_migration.py:47`: beklenmeyen `role` argümanı.
- Aynı dosyada 64, 66, 68 ve 73. satırlar: `AIProject.owner_membership_id` tipte yok.
- `apps/console/views.py:2442`: `None` olabilen tuple değeri dict anahtarı olarak kullanılıyor.

### Locked Playwright kapısı

Başarılı senaryolar:

- Dar ekranda klavye kullanımı ve responsive akış.
- Atanmamış ve foreign-scope kaynakların non-disclosing biçimde gizlenmesi/reddedilmesi.

Başarısız dört beklenti ürünün gözlenen ana işlevinden ziyade test ile yeni bilgi mimarisinin
uyumsuzluğudur:

- Test `Scenario Studio · Empty Workflow` bekliyor; güncel üst bağlam `Adım 3 · Akış · Empty
  Workflow`.
- Test `Retrieval'a sor` bekliyor; güncel başlık `İndeksi dene`.
- Runtime pause kontrolü güncel arayüzde kapalı `Gelişmiş` bölümü içindeyken test varsayılan
  görünürlük bekliyor.
- AI planner güncel arayüzde kapalı `AI ile taslak oluştur` grubu içindeyken test grubu açmıyor.

Kapı kırmızı olduğu için mevcut çalışma ağacı UI/UX açısından Verified kabul edilmemelidir.

### Bağımlılık incelemesi

Full npm audit, Vite/PostCSS üzerinden gelen `nanoid 3.3.16` için high severity advisory bildirdi.
Advisory geliştirme/build bağımlılık ağacındadır; `npm audit --omit=dev` temizdir. Düzeltme
production dependency değişikliği sayılabileceğinden bu QA görevinde uygulanmadı.

Python tarafında repository tarafından yapılandırılmış bağımsız bir CVE/secret scanner bulunmadı;
bu eksik kontrol PASS sayılmamıştır.

## Canlı fonksiyon ve kullanım testleri

### Oturum ve navigasyon

- Oturumsuz console isteği giriş ekranına yönlendirildi.
- Yerel LDAP kapalı açıklaması doğru gösterildi.
- Admin, editor ve auditor oturumları açılıp kapatıldı.
- Dashboard, proje, senaryo, doküman seti, doküman detayı, release/run özetleri ve Studio
  breadcrumb/navigasyonları çalıştı.
- Test sonunda tarayıcı oturumu kapatıldı ve geçici sekme temizlendi.

### Exact sorumluluk ve içerik erişimi

- Organization admin, doküman meta verisini görebildi fakat exact content-reader/manager
  sorumluluğu olmadığı için PDF preview/download ve chunk içeriğini göremedi.
- Exact document-set manager olan editor aynı dokümanda preview/download ve chunk içeriklerini
  görebildi.
- Auditor, KAP senaryosunu okuyabildi; Studio, doküman yönetimi, compile/publish/test ve diğer
  mutation kontrolleri disabled olarak gösterildi.
- Playwright ve Python suite'lerinde same-tenant unassigned/neighbor-role ve cross-tenant denial
  testleri çalıştı. Canlı veritabanında demo dışı bağlı senaryo/doküman-set fixture'ı olmadığı için
  gerçek tarayıcıda ikinci bir foreign-tenant nesne yaratılmadı.

### Scenario Studio

- KAP senaryosundaki aktif workflow canlı Studio'da açıldı.
- Dört düğümlü graph (`input → retrieve → generate → end`) görüntülendi.
- JSON görünümüne geçildi; graph ile aynı düğüm ve kenarlar gözlendi.
- Backend doğrulaması `Workflow geçerli` ve başarılı derleme checksum'u döndürdü.
- Kaydetme/yayınlama yapılmadı; immutable aktif artifact değiştirilmedi.

### REST tüketici sözleşmesi

Test tokenları yalnız işlem belleğinde tutuldu ve test sonunda revoked durumuna geçirildi.

| Yolculuk | Sonuç |
| --- | --- |
| Authorization olmadan `/v1/responses` | HTTP 401 `AUTHENTICATION_REQUIRED` |
| Bağlı `empty-workflow`, sync Responses | HTTP 200, `object=response`, `status=completed` |
| Aynı idempotency key + aynı payload | HTTP 200 ve aynı opaque response id |
| Aynı idempotency key + farklı payload | HTTP 409 `IDEMPOTENCY_CONFLICT` |
| Bağlı olmayan alias | HTTP 403 `SCENARIO_NOT_ALLOWED` |
| Chat Completions + bounded idempotency key | HTTP 200, `object=chat.completion`, 1 choice |
| Chat Completions, idempotency key olmadan | HTTP 400, key zorunlu mesajı |
| `agent-loop`, background Responses | HTTP 202 queued; poll `queued → completed`, terminal GET 200 |

Background run için opaque UUID, sıralı dört RunEvent ve başarılı terminal state kalıcı olarak
doğrulandı.

Dokümantasyon uyumsuzluğu: manual testing guide'ın Chat Completions örneği `Idempotency-Key`
göstermiyor; canlı endpoint seed workflow'larda bu header olmadan 400 döndürüyor.

### MCP, metrics ve health

- MCP kapalı olduğundan `/mcp/`, hem REST hem MCP tokenı ile non-disclosing HTTP 404 döndürdü.
- Metrics token yapılandırılmadığından `/internal/metrics` HTTP 404 döndürdü.
- Liveness HTTP 200 kaldı.
- MCP etkin sözleşme, gerçek metrics scrape ve protokol ayrımı başarı yolu bu konfigürasyonda
  çalıştırılamadı; otomatik test kapsamı başarılıdır.

## RAG ve sağlanan test verisi

`Test Datası/` altında 10 PDF envanterlendi. Canlı Demo Org'da bunların sekizi aktif doküman,
ikisi tombstone durumunda bulundu. Rapor doküman içeriğini, promptu veya cevap metnini içermez.

### Mevcut KAP hattı — başarısız canlı davranış

- `Kap Kılavuzlar Listesi`: aktif set v3, aktif indeks v1, 8 doküman, 171 chunk.
- Aktif indeks ve profili 1.536 boyutlu.
- Çalışma zamanı sağlayıcısı `DeterministicEmbeddingProvider` ve 64 boyutlu query vektörü
  üretiyor.
- UI seti ve indeksi hazır/aktif gösteriyor ve retrieval butonunu etkin bırakıyor.
- Canlı soru HTTP 500 `DIMENSION_MISMATCH` üretti.
- Aktif KAP scenario release'i ayrıca set v2 ve artık `superseded` olan indeks v1'i pinliyor;
  UI bu divergence'ı açıkça gösterdi.

Bu, canlı KAP retrieval yolunu bloke eden konfigürasyon/veri uyumluluğu hatasıdır. Sağlayıcı ile
indeks boyutu admission/readiness aşamasında karşılaştırılmalı veya kullanıcı güvenli, eyleme
dönük bir hata almalıdır.

### İzole deterministik başarı hattı

Mevcut KAP setini değiştirmemek için ayrı bir QA seti oluşturuldu:

- Profil: `qa-deterministic-64:r1`, 64 boyutlu vector; Demo Org'a granted.
- Set: `QA Deterministik RAG 2026-09-04`.
- Exact sorumluluk: editor document-set manager.
- Kaynak: sağlanan PDF korpusundaki mevcut, parsed bir doküman sürümü.
- Set v1 yayımlandı.
- Ingestion worker staged işi 1 denemede tamamladı: 1 doküman, 13 chunk.
- İndeks v1 atomik olarak active yapıldı.
- Canlı hibrit probe beş yetkili chunk döndürdü; soru seti/aggregate metrik değiştirmedi.
- Audit zinciri create → assignment → publish → job requested → built → worker succeeded →
  promoted → probe success olaylarını içeriyor.

### Tombstone yeniden-yükleme davranışı

Sağlanan fakat canlı veritabanında tombstone olan iki PDF'yi yeni sete tekrar yükleme denemeleri
`DOCUMENT_TOMBSTONED` ile durdu. UI yalnız hata kodunu gösterdi; dokümanı geri getirme, yeni mantıksal
ID seçme veya gelişmiş envantere yönlendirme sunmadı. Taslak güvenli biçimde boş kaldı. Bu davranış
veri bütünlüğünü koruyor, ancak kullanıcı toparlanma yolu yetersizdir.

## UI/UX ve erişilebilirlik incelemesi

- 390, 900 ve 1440 px genişliklerde Studio ölçüldü; document/body yatay taşması yoktu.
- 390 px görünümde sidebar üst navigasyona dönüştü, ana kart ve eylemler tek kolona sarıldı.
- Sayfa başından ilk `Tab`, `Ana içeriğe geç` skip link'ine odaklandı.
- Input, select, textarea ve butonların erişilebilir adları gerçek browser AX ağacında bulundu.
- Browser console error/warn incelemesi temizdi.
- KAP doküman seti yaşam döngüsü yükleme → parse → draft → publish → staged → active sırasını
  anlaşılır biçimde gösterdi.
- Scenario ekranı aktif release'in eski set/index pinini açıkça anlattı; bu güçlü bir operasyonel
  güvenlik/UX sinyalidir.
- Gelişmiş kontrollerin disclosure gruplarına alınması ana sayfayı sadeleştiriyor, fakat Playwright
  kapısının ve keşfedilebilirlik metninin güncellenmesi gerekiyor.
- İki önemli hata yolunda geri kazanım zayıftı: tombstone upload yalnız kod gösteriyor; dimension
  mismatch ise güvenli UI mesajı yerine debug 500 sayfasına düşüyor.

Bu çalışma formal WCAG 2.2 uygunluk denetimi değildir.

## Bulgular ve önem sırası

### F-01 — HIGH — Aktif RAG indeks geometrisi çalışma zamanı sağlayıcısıyla uyumsuz

**Etki:** KAP tek seferlik retrieval çalışmıyor; kullanıcı hazır görünen yüzeyde HTTP 500 alıyor.

**Kanıt:** Aktif index/profile 1.536 boyut, runtime deterministic provider 64 boyut;
`VectorStoreError: DIMENSION_MISMATCH`.

**Öneri:** Aktif indeks ile runtime embedder capability'sini health/admission sırasında fail-closed
karşılaştırın; uyumsuz indeksi sorgulanabilir göstermeyin. Provider değişiminde yeniden indeksleme
ve kontrollü promotion runbook'u ekleyin. Console exception'ı güvenli bir eylem mesajına çevirsin.

### F-02 — HIGH koşullu — Yerel Compose ağ yüzeyi debug ve varsayılan servis kimlikleriyle geniş

**Etki:** Host firewall izin veriyorsa 8000, 5432, 6379, 9000 ve 9001 tüm arayüzlerden erişilebilir.
Unhandled RAG hatası debug sayfasında traceback, container yolları, request alanları, CSRF değeri ve
settings topolojisini gösterdi. Redis parolasız, MinIO varsayılan geliştirme kimlikleriyle tanımlı.

**Öneri:** Local compose portlarını `127.0.0.1:` ile sınırlandırın; debug profilini açıkça yalnız
güvenilir localhost için ayırın; altyapı portlarını gerekmiyorsa publish etmeyin ve varsayılan
kimlikleri environment-secret ile değiştirin. Production config'te `DEBUG=False` zorunlu gate olsun.

### F-03 — MEDIUM — Mandatory Playwright gate güncel UX ile uyumsuz

**Etki:** Browser doğrulaması kırmızı; gerçek regresyon ile beklenen metin/gruplama değişimi ayırt
edilemiyor.

**Öneri:** Dört assertion'ı güncel başlıklar ve disclosure açma adımlarıyla düzeltin; kırılan
semantik davranışları (rol, exact scope, backend denial) koruyun.

### F-04 — MEDIUM — Mypy 7 hata veriyor

**Etki:** Migration-test tipleri ve console'daki optional dict key yolu statik güvence dışında.

**Öneri:** Test historical-model tiplerini doğru protocol/cast ile modelleyin; console optional
tuple değerini guard ederek `None` anahtar ihtimalini kaldırın.

### F-05 — MEDIUM — Background run terminal observability eksik

**Etki:** Canlı background run tamamlandı ve RunEvent'leri doğruydu; buna rağmen yalnız admission
`gateway.unified_run` ve background claim audit'i vardı. Sync yolda bulunan
`gateway.unified_run_completed` audit'i ve terminal UsageEvent background tamamlanmada yoktu;
yalnız `queued` UsageEvent kaldı.

**Öneri:** Terminal background transition'ında idempotent audit + usage finalization ekleyin ve
retry/duplicate worker durumunu test edin.

### F-06 — MEDIUM/LOW — Tombstone upload için kurtarma UX'i yok

**Etki:** Aynı dosya adına karşılık gelen tombstone logical ID yeni sette tekrar kullanılamıyor;
kullanıcı yalnız sabit hata kodu görüyor.

**Öneri:** Yetkiye göre gelişmiş envantere/restore akışına yönlendirin veya güvenli, sunucu-sahipli
yeni logical ID seçme akışı sağlayın. Tombstone varlığını yetkisiz aktöre sızdırmayın.

### F-07 — LOW — Chat Completions örneği idempotency gereksinimiyle uyumsuz

**Etki:** Kılavuzdaki örnek header olmadan 400 dönebiliyor.

**Öneri:** Kılavuz örneğine bounded `Idempotency-Key` ekleyin veya gerçekten sync/RAG özelinde
opsiyonel olması amaçlanıyorsa kod ve test sözleşmesini netleştirin.

### F-08 — LOW — Dev dependency ağacında high advisory

**Etki:** Production npm ağacı temizdir; geliştirme/build zincirinde `nanoid 3.3.16` advisory'si
vardır.

**Öneri:** Ayrı dependency onayıyla Vite/PostCSS/nanoid çözümlemesini güncelleyin, unit/build/browser
kapılarını yeniden çalıştırın.

### F-09 — LOW — PostgreSQL test koşusu canonical MinIO bucket'ında orphan test objeleri bıraktı

**Etki:** Test DB'si temizlenirken S3 objeleri otomatik silinmedi. Final incelemede bucket'ta 55
obje vardı; 16'sı canlı DocumentVersion kayıtlarınca referanslanıyordu. Görev başladıktan sonraki
zaman damgasına sahip 26 küçük obje (toplam 258 bayt) referanssızdı ve PostgreSQL storage testleriyle
zamansal olarak eşleşiyordu. Başlangıç bucket sayımı alınmadığı için kesin sahiplik iddiası yoktur.

**Öneri:** PostgreSQL entegrasyon testlerini benzersiz bir test bucket'ına yönlendirin ve yalnız bu
bucket için güvenli lifecycle cleanup ekleyin. Mevcut 26 obje silme yetkisi olmadığı için korunmuştur;
isim/önek incelemesi sonrası insan onayıyla temizlenmelidir.

## Güvenlik gereksinimi eşlemesi

| Gereksinim | Sonuç | Kanıt |
| --- | --- | --- |
| Authentication denial | PASS | Oturumsuz console redirect; REST 401 |
| Exact responsibility allow | PASS | Editor document manager ve scenario editor akışları |
| Same-tenant neighbor/unassigned deny | PASS | Auditor/editor disabled yüzeyleri + automated direct tests |
| Cross-tenant non-disclosure | PASS (automated) | Python ve locked-browser foreign-scope testi |
| REST alias denial | PASS | 403 `SCENARIO_NOT_ALLOWED` |
| Idempotency replay/conflict | PASS | Aynı payload aynı id; farklı payload 409 |
| MCP protocol/config fail-closed | PASS (disabled path) | `/mcp/` 404 |
| Sensitive log/audit taraması | PASS (bounded) | Son iki saatte Bearer/session/csrf/password/api-key/secret-ref pattern count 0 |
| Safe browser error | **FAIL** | RAG exception debug traceback/settings sayfası gösterdi |
| Audit completeness | **FAIL** | Background terminal audit/usage eksik; failed probe audit olayı yok |

## Log, metrik, tracing ve audit kanıtı

- Worker staged build ve background run işleri terminal duruma geldi.
- Son log taramasında bearer token, session ID, CSRF token, parola, API key veya secret-ref string'i
  bulunmadı.
- Audit JSON `before/after` alanlarında aynı pattern'lerin sayısı sıfırdı.
- Başarılı QA RAG lifecycle ve sync gateway olayları request ID taşıdı.
- `DIMENSION_MISMATCH` web logunda traceback ile görüldü, ancak aynı başarısız probe için append-only
  audit event bulunmadı.
- Browserda gösterilen debug sayfası log/audit redaction'ından ayrı bir bilgi sızıntısı yüzeyidir.
- Metrics fail-closed olduğu için Prometheus içeriği doğrulanmadı; OTLP endpoint yapılandırılmamıştı.

## Migration ve veritabanı doğrulaması

- `showmigrations ingestion`: 0016 applied.
- `makemigrations --check --dry-run`: drift yok.
- SQLite suite migration testleri geçti.
- PostgreSQL tam suite: 1.383 passed, 5 skipped, 8 failed; 403,49 saniye. Sekiz failure'ın
  tamamı `MCP_ENABLED=false` ve metrics bearer token eksikliği altında endpoint'lerin güvenli 404
  döndürmesinden kaynaklandı. Feature'lar etkinleştirildiğinde hedefli MCP/metrics paketi
  14/14 geçti (24,79 saniye).
- Bu QA görevi migration yazmadı, schema/reset/purge uygulamadı.

## Kabul kriteri eşlemesi

| Kriter | Sonuç |
| --- | --- |
| Mimari ve kullanım amacı canlı durumla uzlaştırıldı | PASS |
| Repository-applicable otomatik kontroller sonuçlandırıldı | PASS; type/browser/dependency failure'ları ayrıca kayıtlı |
| Locked Playwright kapısı çalıştırıldı | RUN / FAIL |
| Gerçek browser 390/900/1440, keyboard ve console incelemesi | PASS |
| Sağlanan PDF ile RAG yolculuğu | PASS (izole deterministic set); mevcut KAP yolu FAIL |
| Authentication/authorization/cross-scope | PASS, live foreign fixture N/A |
| REST/MCP/health/metrics representative boundaries | PASS/BLOCKED by config olarak kaydedildi |
| Bulgular, retained state ve residual risk kaydı | PASS |

## Retained yerel test durumu

Veri silme/purge yetkisi verilmediği için aşağıdakiler açıkça etiketlenmiş biçimde korunmuştur:

- `qa-deterministic-64:r1` embedding profili ve Demo Org grant'i.
- `QA Deterministik RAG 2026-09-04` document seti, v1 ve active index v1 (1 doküman, 13 chunk).
- Editor için exact document-set manager assignment.
- QA run, usage ve append-only audit kayıtları.
- `seed_demo --no-print-secrets` mevcut demo kullanıcı parolalarını test değeriyle yeniden ayarladı
  ve iki local demo token kaydı oluşturdu; bu iki token doğrulama sonunda desteklenen lifecycle
  servisiyle revoked edildi ve hiçbir plaintext değer rapora yazılmadı.
- API probe'ları için oluşturulan geçici tokenların tamamı revoked edildi; bir probe exception'ı
  sonrasında kalan token ayrıca bulunup revoked edildi.
- MinIO final sayımında görev başlangıcından sonraki zaman damgasına sahip, canlı DB'de referansı
  olmayan 26 küçük obje (toplam 258 bayt) vardı. Bunlar muhtemelen PostgreSQL storage testlerinden
  kaldı; başlangıç envanteri olmadığı için otomatik silinmedi.

Mevcut dokümanlar, KAP seti, release'ler, tombstone kayıtları ve kullanıcıya ait çalışma ağacı
değişiklikleri silinmedi veya geri alınmadı.

## Çalıştırılmayan veya bloke kontroller

- Gerçek model/embedding/OCR/Confluence/REST connector/tool egress: profil veya onaylı secret yok.
- MCP enabled success ve REST↔MCP token ayrımı: MCP kapalı.
- Authenticated Prometheus scrape: metrics token yok.
- Live LDAP: LDAP kapalı.
- LLM judge: kapalı.
- Production/OpenShift deployment, gerçek non-owner DB role RLS, load/soak/chaos ve uzun süreli
  concurrency: kapsam dışı.
- Formal WCAG/yardımcı teknoloji denetimi: kapsam dışı.
- Python CVE ve repository-wide secret scanner: yapılandırılmış araç bulunmadı.
- Canonical MinIO bucket'ındaki 26 yeni-zamanlı orphan test objesi: silme yetkisi olmadığı için
  manuel inceleme/temizlik bekliyor.

## Doğrulanmamış varsayımlar

- Yerel debug/varsayılan servis kimliklerinin production'a taşınmadığı varsayılmıştır; deployment
  bu görevde doğrulanmadı.
- Gerçek provider secret ref'lerinin çalışma ortamında güvenli secret store'dan çözüleceği
  varsayılmıştır.
- İlk tam PostgreSQL koşusundaki 13 storage hatasının eksik test ortamı credential'larından
  kaynaklandığı doğrulandı. Credential'lı tekrar 1.383 pass üretti; kalan 8 failure kapalı canlı
  MCP/metrics feature konfigürasyonuna aitti. Etkin bayraklarla hedefli paket 14/14 geçti.

## Kalan riskler ve insan incelemesi

- F-01, F-02, F-03, F-04 ve F-05 çözülmeden çalışma ağacı release-ready sayılmamalıdır.
- Ürün sahibinin KAP seti için doğru embedding stratejisini seçmesi gerekir: gerçek 1.536 boyutlu
  sağlayıcıyı hazır etmek veya kontrollü 64 boyutlu yeniden indeks/promotion yapmak.
- Güvenlik/SRE incelemesi Compose port bağlarını ve production `DEBUG` gate'ini onaylamalıdır.
- UI sahibi disclosure tasarımını koruyacak şekilde Playwright kapısını güncellemelidir.
- Doküman sahibi tombstone restore/re-upload davranışını ve kullanıcı mesajını onaylamalıdır.
- Observability sahibi background terminal audit/usage sözleşmesini kararlaştırmalıdır.

## Final statü

**Değerlendirme tamamlandı; ürün doğrulaması başarısız.** Uygulama mevcut durumda **Verified
değildir**. Zorunlu browser kapısı, mypy ve canlı KAP RAG yolu düzeltilip yeniden doğrulanmalıdır.
