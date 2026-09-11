# REST Veri Kaynağı Kurulumunu Sadeleştirme — Uygulama Talimatı

## Rolün

Bu repository üzerinde çalışan kıdemli yazılım mimarı, uygulama güvenliği mühendisi ve ürün odaklı full-stack geliştirici olarak hareket et. Repository kökündeki `AGENTS.md` ile daha özel talimatları eksiksiz uygula. Çalışmaya başlamadan önce mevcut kodu, testleri, görev planlarını, aktif handoff'u, çalışma ağacındaki kullanıcı değişikliklerini ve canlı Compose durumunu doğrula. Kullanıcıya ait mevcut değişiklikleri ezme veya geri alma.

Bu talimat bir tasarım önerisi değil, uygulanacak ürün geliştirme kapsamıdır. Önce repository politikasına uygun görev planı ve orantılı tehdit modeli oluştur; ardından en küçük eksiksiz değişikliği, testleri ve kullanıcı dokümantasyonunu birlikte teslim et.

## Amaç

Mevcut Generic REST ingestion kurulumu teknik olarak güvenli fakat kullanıcı açısından parçalıdır. Kullanıcı bugün aşağıdaki iç nesneleri ayrı ekranlarda ve ayrı adımlarla yönetmek zorundadır:

1. `RestPullProfile` oluşturma,
2. `TenantRestPullProfileGrant` verme,
3. `RestPullContract` JSON mapping sözleşmesi hazırlama,
4. `Source` oluşturma,
5. `ConnectorSyncSchedule` yapılandırma,
6. doküman seti sürümünü yayımlama,
7. staged indeks oluşturma ve aktif etme,
8. `ScenarioDocumentSetBinding` ile senaryoya bağlama.

Backend'deki bu ayrımı ve güvenlik sınırlarını koru; ancak normal kullanıcıya tek bir **REST veri kaynağı oluşturma sihirbazı** ve senaryoda tek bir **hazır bilgi kaynağı bağlama** deneyimi sun.

Hedef kullanıcı zihinsel modeli şudur:

```text
REST veri kaynağını oluştur ve test et
→ yenileme/indeksleme ayarını seç
→ kaydet
→ senaryoda hazır bilgi kaynağını seçip bağla
```

Sistem arka planda mevcut yönetilen nesneleri oluşturmaya ve kullanmaya devam etmelidir.

## Temel mimari kararı

REST kaynağını doğrudan senaryoya ait hâle getirme. Doküman seti ve indeks yaşam döngüsünü arka planda koru; çünkü:

- aynı kaynak birden fazla senaryoda tekrar kullanılabilmelidir,
- aynı içerik her senaryo için yeniden çekilmemeli ve embed edilmemelidir,
- ingestion/yenileme senaryo düzenleme yaşam döngüsünden bağımsız olmalıdır,
- release'ler exact doküman seti ve indeks sürümünü sabitleyebilmelidir,
- rollback, audit, tenant izolasyonu ve veri geçmişi korunmalıdır.

Senaryo ekranındaki “REST kaynağını bağla” eylemi gerçekte hazır kaynağın bağlı olduğu `DocumentSet` için mevcut, yetkili `ScenarioDocumentSetBinding` servisini kullanmalıdır. Yeni ve paralel bir bağlantı modeli oluşturma.

## Mevcut kaynakların başlangıç noktaları

En az aşağıdaki alanları incele; isimlere körü körüne güvenme, canlı kod ve referanslarla doğrula:

- `apps/ingestion/models.py`
  - `RestPullProfile`
  - `RestPullContract`
  - `TenantRestPullProfileGrant`
  - `Source`
  - `ConnectorSyncSchedule`
  - `IndexVersion`
- `apps/ingestion/rest_services.py`
- `apps/ingestion/rest_schema.py`
- `apps/ingestion/rest.py`
- `apps/ingestion/rest_sync.py`
- `apps/ingestion/automation.py`
- `apps/ingestion/staged_build.py`
- `apps/documents/models.py`
  - `DocumentSet`
  - `DocumentSetVersion`
  - `ScenarioDocumentSetBinding`
- `apps/documents/services.py`
- `apps/console/forms.py`
- `apps/console/views.py`
- `apps/console/urls.py`
- `apps/console/templates/console/platform_setup.html`
- `apps/console/templates/console/platform_profile_form.html`
- `apps/console/templates/console/document_set_connectors.html`
- senaryo detayındaki doküman-seti/bilgi-kaynağı bağlama yüzeyi
- ilgili console, ingestion, authorization, RLS ve browser testleri

## Hedef bilgi mimarisi

### 1. Platform kurulumu altında “Veri kaynakları”

Platform kurulumunda dağınık bir “REST profili” kaydı yerine kullanıcıya **REST veri kaynağı** kavramını göster.

Önerilen giriş noktası:

```text
Platform kurulumu
→ Veri kaynakları
→ Yeni REST veri kaynağı
```

Mevcut platform profil kataloğu gelişmiş/operasyonel görünüm olarak korunabilir. Geriye dönük çalışan rotaları kaldırma.

### 2. Senaryo altında “Bilgi kaynakları”

Senaryo detayında aşağıdaki deneyimi sağla:

```text
Bilgi kaynağı ekle
→ kullanıcının organizasyon ve yetki kapsamındaki hazır kaynakları listele
→ kaynak durumunu göster: hazır / senkron bekliyor / indeks hazırlanıyor / aktif / hatalı
→ seç ve senaryoya bağla
```

Bu ekranda endpoint, credential, secret referansı, ham mapping JSON'u, pagination veya provider altyapısı gösterilmemelidir.

## REST veri kaynağı sihirbazı

Basit mod varsayılan olmalı. Gelişmiş seçenekler progressive disclosure ile açılmalıdır.

### Adım 1 — Kimlik ve kapsam

- Kullanıcı görünen kaynak adını girer.
- Organizasyon seçimi yalnız platform yöneticisine ve yetkili kapsamına göre gösterilir.
- Hedef için:
  - mevcut doküman setini seçme veya
  - sistemin otomatik doküman seti oluşturması
  seçenekleri sunulur.
- `logical_id`, slug ve revision kullanıcıdan istenmez; güvenli ve çakışmasız biçimde sistem üretir.
- Aynı kurulum isteğinin çift tıklama/retry ile mükerrer nesneler üretmesini engelle.

### Adım 2 — Bağlantı ve kimlik doğrulama

Kullanıcı tam endpoint URL'sini tek alanda görür ve yalnız bir kez girer.

- URL
- GET veya desteklenen read-only POST
- authentication türü
- secret değeri yerine onaylı secret referansı/seçimi
- bağlantı testi

`base_url`, `path_prefix` ve contract `request.path` ayrımını kullanıcıya yükleme. Bunları doğrulanmış ve deterministik şekilde sistem içinde ayır veya canonical tam URL modelini kullan. Aynı HTTP methodunu profil ve contract formunda iki kez girdirme; backend uyumluluk kontrolü yine korunsun.

Bağlantı testi:

- yalnız yetkili kullanıcı tarafından başlatılmalı,
- mevcut SSRF-safe egress adapter'ını kullanmalı,
- scheme/domain/IP/redirect/timeout/body-size/request-count sınırlarını korumalı,
- secret veya authorization header göstermemeli,
- güvenli GET/read-only sözleşme semantiğini aşmamalı,
- audit edilmeli,
- hata mesajını uygulanabilir fakat bilgi sızdırmayan şekilde göstermelidir.

### Adım 3 — Örnek cevap ve görsel mapping

Başarılı test cevabından bounded, redacted bir örnek üret veya kullanıcının sentetik örnek JSON yüklemesine izin ver.

Ham RFC 6901 JSON pointer sözleşmesini varsayılan deneyim yapma. Kullanıcıya görsel alan seçimi sun:

- kayıt listesinin bulunduğu alan,
- benzersiz ID,
- başlık,
- içerik,
- isteğe bağlı revision/timestamp,
- isteğe bağlı deleted/tombstone,
- content encoding ve MIME türü,
- gerekiyorsa detail endpoint.

Sistem seçilen alanlardan mevcut canonical `RestPullContract.definition` JSON'unu üretmelidir. Mevcut validator tek doğruluk kaynağı olarak kalmalıdır; UI doğrulaması backend doğrulamasının yerine geçmemelidir.

Gelişmiş modda mevcut canonical JSON sözleşmesi görüntülenebilir ve düzenlenebilir. Basit ve gelişmiş mod aynı backend schema ve servislere gitmelidir.

### Adım 4 — Pagination ve inputlar

- Cevaptaki yaygın `total`, `limit`, `skip`, `next`, `cursor`, `page` alanlarından pagination önerisi üret.
- Kullanıcıya “yok / sayfa / offset / cursor” seçimi sun.
- Teknik placeholder JSON'u yerine form alanları göster.
- Contract `inputs` şemasından source input formunu dinamik üret.
- URL, header veya secret değerinin source input içine kaçmasını mevcut kapalı şema kurallarıyla engellemeye devam et.

Kök endpoint kullanımını doğru destekle. Mevcut `path_prefix="/posts"` ile contract `path="/"` kombinasyonunun `REST_PATH_INVALID` üretmesi gibi kullanıcıyı yeni revizyon açmaya zorlayan belirsiz durumları ortadan kaldır. Canonical URL birleşimini birim ve entegrasyon testleriyle kanıtla.

### Adım 5 — Yenileme ve indeksleme

Tek akış içinde şu seçenekleri sun:

- yalnız manuel çalıştırma veya periyodik yenileme,
- yenileme aralığı,
- embedding profili,
- chunking profili,
- gerekiyorsa OCR profili,
- değişiklikten sonra yalnız taslak oluşturma,
- staged indeks hazırlama,
- yetki ve mevcut güvenlik kapıları izin veriyorsa açık onayla promotion.

Varsayılan güvenli davranış:

- ilk sync ve build asenkron job olarak çalışır,
- kaynak kurulumu başarılı görünmeden önce job dispatch durumu kalıcılaşır,
- staged indeks otomatik olarak servis edilmeye başlamaz,
- promotion ayrı, görünür ve yetkili bir karardır,
- aktif release etkileniyorsa mevcut explicit confirmation korunur.

### Adım 6 — Özet ve oluşturma

Kaydetmeden önce kullanıcıya gizli olmayan özet göster:

- kaynak adı,
- redacted/canonical hedef etiketi,
- method,
- seçilen alan mapping'i,
- pagination,
- hedef doküman seti,
- yenileme sıklığı,
- embedding/index politikası.

“Oluştur ve test et” eylemi arka planda mevcut domain servislerini orkestre etmelidir. View içinde modelleri doğrudan ve dağınık şekilde kaydetme. Orkestrasyon servisi:

- authorization'ı her nesne/action için sunucu tarafında doğrulamalı,
- `transaction.atomic` sınırlarını doğru kullanmalı,
- dış ağ/queue işlemini açık transaction içinde tutmamalı,
- idempotency/retry davranışı tanımlamalı,
- kısmi başarısızlıkta kullanıcıya hangi aşamanın tamamlandığını göstermeli,
- başarılı config nesnelerini sessizce silmemeli,
- audit olaylarını ortak correlation/request ID ile ilişkilendirmelidir.

## Grant davranışı

- Platform yöneticisi sihirbaz içinde yeni bir kaynağı belirli sete kuruyorsa exact set grant'i güvenli biçimde otomatik oluşturulabilir.
- Platform yöneticisi olmayan kullanıcı endpoint veya secret tanımlayamaz.
- Doküman yöneticisi yalnız kendisine ve exact sete önceden grant edilmiş aktif profilleri seçebilir.
- Grant kapsamını organizasyon geneline sessizce genişletme.
- Disabled/retired profil veya foreign-tenant ID ile kaynak oluşturma fail-closed kalmalıdır.

## Revizyon ve düzenleme deneyimi

Mevcut immutable/revisioned backend kayıtlarını yerinde mutasyona çevirme.

Kullanıcıya **Düzenle** dediğinde:

1. mevcut ayarları otomatik doldur,
2. değişiklikleri diff olarak göster,
3. revision numarasını otomatik artır,
4. yeni profil/contract/source revision zincirini oluştur,
5. test ve staged rollout tamamlanana kadar eski çalışan kaynağı koru,
6. açık promotion sonrasında yenisine geç,
7. rollback imkânını koru.

Geçici disable, yeniden etkinleştirme ve kalıcı retirement kavramlarını karıştırma. Bu görev kapsamında durum modeli değişikliği gerekiyorsa authorization ve yaşam döngüsü etkisini plana yaz ve repository kuralı gereği gerekli kullanıcı onayını al.

## Liste ve durum ekranları

Normal kullanıcıya tek bir REST veri kaynağı kartı göster. Kartta:

- görünen ad,
- organizasyon/proje kapsamı,
- bağlı doküman seti,
- bağlı senaryo sayısı,
- son sync zamanı ve sonucu,
- bulunan/değişen/değişmeyen/eksilen kayıt sayıları,
- doküman ve chunk sayısı,
- aktif indeks sürümü,
- sonraki çalışma zamanı,
- son uygulanabilir hata ve “yeniden dene” eylemi
bulunsun.

Geçmişteki failed job ile güncel başarılı/aktif indeks birbirinden net ayrılmalıdır. Eski failed satır kullanıcıya güncel kaynak başarısızmış gibi gösterilmemelidir.

## Adlandırma

Kullanıcı yüzeyinde aşağıdaki terimleri tercih et:

- `REST profili` → **REST bağlantısı**
- `RestPullContract` → **Veri eşleme** veya **API cevap eşleme**
- `Source` → **REST veri kaynağı**
- `Grant` → **Kullanım izni**
- `Staged index` → **Hazırlanan indeks**; teknik durum ikincil rozet olabilir

Teknik model adlarını yalnız gelişmiş/operasyonel görünümde göster.

## Geriye dönük uyumluluk

- Mevcut `RestPullProfile`, `RestPullContract`, grant, source, schedule ve index kayıtlarını geçerli tut.
- Mevcut management command, worker task, API/URL ve gelişmiş console akışlarını gerekmedikçe kaldırma.
- Yeni akış mevcut domain servislerini yeniden kullanmalı; paralel ve tutarsız ingestion uygulaması yazma.
- Mevcut kayıtlar yeni birleşik listede anlamlı şekilde görüntülenmelidir.
- Gerekli migration varsa ileri/geri uyumluluğu ve rollback stratejisini test et.

## Güvenlik gereksinimleri

Aşağıdakiler pazarlık konusu değildir:

- Secret değeri veritabanındaki mapping/source config'e veya audit/loglara yazılmaz.
- Secret, token, password, authorization header ve tam hassas response kullanıcıya geri yansıtılmaz.
- SSRF koruması, TLS doğrulaması, DNS/IP denetimi, redirect limiti, timeout ve response/request/item/page/byte limitleri korunur.
- Tenant, organization, document set, project ve scenario kapsamı istemciden güvenilir kabul edilmez.
- Tüm nesne/action yetkileri sunucu tarafında ve deny-by-default uygulanır.
- Foreign-tenant, aynı tenant içinde yetkisiz neighboring set/scenario ve forged-ID denemeleri reddedilir.
- Mapping ve inputlar explicit allowlist/schema ile doğrulanır.
- Test/preview ağ çağrıları da production egress kontrollerinden geçer.
- State-changing eylemler CSRF, POST-only ve audit kontrollü kalır.
- Hata ekranları secret, credential ref ayrıntısı, iç host/IP, stack trace veya doküman içeriği sızdırmaz.

Authentication, authorization, tenant izolasyonu, secret mekanizması veya public API sözleşmesinde değişiklik gerekecekse repository kuralına uygun biçimde açık kullanıcı onayı almadan bu sınırı değiştirme.

## UX gereksinimleri

- Basit bir REST kaynağı ilk kez kuran platform yöneticisi ham JSON yazmadan başarılı olabilmelidir.
- Tam URL ve HTTP methodu yalnız bir kez girilmelidir.
- Manuel `logical_id`, slug veya revision girişi gerekmemelidir.
- Form hata mesajları teknik hata kodunun yanında kullanıcıya düzeltilecek alanı söylemelidir.
- Kullanıcı sihirbazdan çıktığında ilerleme güvenli taslak olarak saklanabilir veya açıkça kaybolacağı belirtilmelidir.
- Geri/ileri gezinme girilen güvenli alanları korumalı; secret yeniden gösterilmemelidir.
- Klavye erişimi, focus yönetimi, ekran okuyucu etiketleri ve responsive görünüm doğrulanmalıdır.
- Gelişmiş JSON modu basit modu bozmayacak biçimde açılıp kapanmalıdır.
- İşlem sonrasında kullanıcı tek ekranda sync → draft → build → promotable → active ilerlemesini görebilmelidir.

## Önerilen uygulama yaklaşımı

Bu bölüm bağlayıcı dosya tasarımı değildir; mevcut kod gerçekliğine göre doğrula ve planı güncelle.

1. Bir application/orchestration service oluştur veya mevcut servisleri tek servis altında bileştir.
2. Ayrı adımları temsil eden açık input dataclass/schema kullan; request nesnesini domain katmanına taşıma.
3. Sihirbaz durumunu server-side, bounded ve secret-free sakla. İstemciye authorization kararı taşıtma.
4. Görsel mapping seçimlerini canonical contract JSON'una dönüştüren saf ve kapsamlı test edilmiş fonksiyon yaz.
5. Existing `validate_contract` son doğrulayıcı olmaya devam etsin.
6. Bağlantı preview'su için mevcut egress client'ını kullan; yeni genel amaçlı HTTP istemcisi açma.
7. Kurulum tamamlanınca idempotent sync/build task'larını mevcut queue'lara gönder.
8. Senaryo bağlama eyleminde mevcut `ScenarioDocumentSetBinding` servisini kullan.
9. Eski gelişmiş ekranlara birleşik kaynaktan erişim ver; normal akışta görünürlüklerini azalt.

## Test kapsamı

Repository kurallarındaki tüm uygulanabilir kontrolleri çalıştır ve kanıtı görev verification kaydına yaz.

En az şu testleri ekle:

### Saf mapping testleri

- root array response,
- nested item list,
- ID/title/content seçimi,
- optional revision/deleted,
- page/offset/cursor pagination,
- detail endpoint,
- root path ve prefix birleşimi,
- invalid pointer/path/placeholder,
- oversized/deep response ve mapping.

### Servis ve transaction testleri

- başarılı birleşik kurulum,
- var olan profile/contract/source reuse,
- çift submit/idempotency,
- her ara adımda validation failure,
- queue dispatch failure,
- dış çağrının transaction dışında olması,
- kısmi başarısızlık ve güvenli retry,
- immutable revision clone/edit,
- eski aktif kaynağın yeni sürüm doğrulanana kadar korunması.

### Authorization ve izolasyon testleri

- anonymous,
- normal üye,
- document-set manager,
- scenario editor,
- platform admin,
- aynı tenant fakat yetkisiz başka set/senaryo,
- cross-tenant ID,
- disabled organization/profile/grant/source,
- forged profile/contract/source/document-set/scenario ID,
- senaryoya bağlama ve kaldırma için ayrı allow/deny kontrolleri.

### Güvenlik testleri

- localhost/private/link-local/metadata hedefleri,
- DNS rebinding/redirect senaryoları,
- HTTP/TLS downgrade,
- credential/header redaction,
- secret'ın form, session, DB, log, audit ve error response'a düşmemesi,
- response/request/item/page/byte/time limitleri,
- GET/POST method mismatch,
- input içine URL/header/secret kaçırma girişimleri.

### UI/browser testleri

- basit sihirbazı baştan sona tamamla,
- örnek response alanlarını görsel seç,
- gelişmiş moda geç ve geri dön,
- refresh/back/error recovery,
- hazır kaynağı senaryoya bağla,
- bağlı kaynağın durumunu senaryoda gör,
- failed geçmiş job ile aktif indeksin ayrımını gör,
- keyboard/focus/responsive/console-network hata kontrolü,
- yetkili ve yetkisiz kimliklerle görünürlük ve doğrudan URL/POST kontrolleri.

PostgreSQL RLS, pgvector, queue ve gerçek object-store sınırları için yalnız SQLite testlerine güvenme. Repository'nin öngördüğü PostgreSQL ve zorunlu browser doğrulama kapılarını uygula.

## Kabul kriterleri

İş aşağıdaki koşulların tümü karşılanmadan tamamlanmış sayılmaz:

1. Platform yöneticisi basit bir GET REST kaynağını ham JSON yazmadan tek sihirbazda oluşturabilir.
2. URL ve HTTP methodu kullanıcıdan yalnız bir kez alınır.
3. Mapping örnek response üzerinden görsel olarak oluşturulur; advanced JSON seçeneği korunur.
4. `logical_id`, slug ve revision otomatik yönetilir.
5. Exact document-set grant gerekli yetkiyle otomatik veya tek adımlı oluşturulur.
6. Mevcut profile/contract/source/schedule/index modelleri ve güvenlik sınırları korunur.
7. Kaynak sync/build ilerlemesi tek durum yüzeyinde izlenebilir.
8. Staged indeks açık yetkili karar olmadan aktif olmaz.
9. Senaryo yazarı hazır, yetkili bilgi kaynağını tek seçimle senaryoya bağlayabilir.
10. Senaryo ekranı endpoint, credential ve mapping teknik ayrıntılarını göstermez.
11. Aynı kaynak birden fazla senaryoda yeni ingestion/index kopyası oluşturmadan kullanılabilir.
12. Mevcut kayıtlar ve gelişmiş akış geriye dönük çalışır.
13. Cross-tenant, same-tenant cross-scope, disabled ve forged-ID testleri fail-closed geçer.
14. Secret ve hassas response hiçbir kalıcı/telemetri yüzeyine sızmaz.
15. Kök path/prefix ve pagination senaryoları otomatik testlerle kanıtlanır.
16. İlgili unit, integration, PostgreSQL, security ve browser gate testleri geçer ve verification kaydında raporlanır.
17. Kullanıcı dokümantasyonu yeni basit akışı, gelişmiş modu, rollback ve operasyonel sınırları açıklar.

## Kapsam dışı

- Mevcut tenant/RLS modelini kaldırmak,
- secret değerlerini uygulama veritabanında saklamak,
- senaryo başına ayrı doküman/vektör kopyası üretmek,
- otomatik ve kontrolsüz indeks/release promotion,
- mevcut güvenli egress adaptörünü bypass etmek,
- bütün connector türlerini aynı anda yeniden yazmak,
- public API sözleşmesini gerekçesiz kırmak,
- yalnız mock veya yalnız SQLite ile işi doğrulanmış saymak.

## Teslimat beklentisi

Sonunda şunları teslim et:

- güncel görev planı ve tehdit modeli,
- birleşik REST veri kaynağı sihirbazı,
- görsel mapping ve gelişmiş JSON modu,
- güvenli application/orchestration service,
- senaryoda hazır bilgi kaynağı seçme/bağlama deneyimi,
- idempotent async sync/build ilerleme görünümü,
- gerekli migration'lar ve rollback stratejisi,
- kapsamlı unit/integration/security/PostgreSQL/browser testleri,
- güncellenmiş kullanıcı ve operasyon dokümantasyonu,
- verification kaydı,
- final diff için staff engineer, AppSec ve SRE incelemesi.

Final raporunda repository `AGENTS.md` tarafından istenen bütün başlıkları kullan; çalıştırılmayan kontrolleri açıkça belirt, varsayımları ve kalan riskleri gizleme. Güvenlik veya doğruluk pahasına yalnızca daha az tıklama hedefleme.
