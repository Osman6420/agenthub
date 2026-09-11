> Superseded: [tek aktif geliştirme görevi](../Agent_Hub_MD/plan.md). Bu belge tarihsel kaynaktır; bağımsız uygulanmaz.

# AgentHub RAG mimarisini sadeleştir — kodlama ajanı talimatı

Hazırlanma: 9 Eylül 2026. **Talimat hazır; uygulama henüz yapılmadı.**

Bu dosyanın tamamını kodlama ajanına verip uygulanmasını iste. Hedefi yalnızca
tablo sayısı olarak aktarma; aşağıdaki güvenlik, davranış ve geçiş şartları birlikte geçerlidir.

## 1. Görev

AgentHub'ı hızlı RAG çözümü üretmeye ve bu çözümleri kolayca güncel tutmaya uygun
bir mimariye dönüştür. Mevcut Django/PostgreSQL/pgvector ve kalıcı yürütme altyapısını
başlangıç kabul et. Testlerle kanıtlanan parser, güvenli taşıyıcı, adapter ve yürütme
davranışlarını yeniden kullan. Yalnız model adlarını değiştirmek, bazı ekranları
gizlemek veya eski servislerin önüne yeni bir katman eklemekle bitirme.

Hedef sonuç:

- Organizasyonlar/ekipler birbirinden kapalı veri alanları olarak kalır.
- **Proje ve senaryo bazlı yetkilendirme korunur.** Organizasyon üyeliği bunların yerine geçmez.
- Her indekslemede yeni tablo açılması sona erer. **Bütün chunk/embedding kayıtları tek sabit fiziksel tabloda tutulur.**
- Senaryo yapılandırması tek tutarlı yayın snapshot'ıyla yönetilir. Küçük bir prompt
  değişikliği için kullanıcı bağımsız artifact/workflow/release zincirlerini tek tek yönetmez.
- Veri kaynaklarının yenilenmesi, senaryonun yeniden yayınlanmasını gerektirmez.
- REST ve MCP ile veri alma, çalışma sırasında tool çağırma ve ürünü REST/MCP üzerinden
  sunma ayrı işlevler olarak aynı alan servislerine bağlanır.
- Uzun çalışan ajanlar, insan onayı, paralellik, alt işler ve telafi işlemleri kalıcı,
  yeniden başlatmaya dayanıklı şekilde çalışır.

Uygulama görevi verildiğinde yetkilendirilmiş kapsamda test edilmiş dikey parçalarla
ilerle; yalnız analiz veya ilk prototipi teslim edip bütün işi tamamlandı sayma.
Bu belgenin hazırlanması kendi başına uygulama/deploy başlatma talimatı değildir.

## 2. Kaynaklar ve çakışan planlar

Önce kök ve ilgili alt `AGENTS.md` dosyalarını, [görev planını](plan.md),
[tehdit modelini](threat-model.md), [ana planı](../../planning/master-plan.md),
`docs/ai/` kurallarını ve güncel çalışma ağacını incele. Tek ana ajanla çalış;
repository işini alt ajanlara devretme. Önceden yapılmış yerel değişiklikleri koru.
Kod zekâsı araçları varsa güncel projeyi doğrula; yoksa `rg`, sembol/kaynak incelemesi
ve testlerle devam et. Eski inceleme envanterini güncel runtime kanıtı sayma.

Bu görevle ilişkili belgeler:

| Belge | Bu görevdeki rolü |
| --- | --- |
| [Ürün mimarisi değerlendirmesi](../../planning/archive/rag-product-architecture-reassessment-2026-09-08/assessment.md) | Gerekçe ve başlangıç keşfi; aşağıdaki düzeltmeler önceliklidir |
| [Eski 35-model eşlemesi](../../planning/archive/rag-product-architecture-reassessment-2026-09-08/target-model.md) | Tarihsel taslak; proje sınırını kaldıran ve yetkileri üyeliğe indirgeyen satırları uygulama |
| [Tek tablo uygulama planı](../shared-vector-storage/plan.md) | Depolama fazının ayrıntılı sözleşmesi; aynı iş için ikinci DAL veya rakip migration üretme |
| [Yetkilendirme uygulama talimatı](../authorization-simplification/implementation-prompt.md) | Ayrı rol/devralma/politika değişikliği işi; dosyanın varlığı uygulama onayı değildir |

Yetkilendirme işi daha önce uygulanmış/onaylanmışsa gerçek durumu doğrula ve onun
onaylı matrisini koru. Aksi halde mevcut izin davranışı bu dönüşümün başlangıç
sözleşmesidir. Yeni rol birleştirme, otomatik devralma veya ortak veri erişim modlarını
bu görev üzerinden kendiliğinden etkinleştirme. İki planın aynı sembol/şemaya etkisini
tek geçiş sırasıyla uzlaştır; yapılmış işi tekrarlama.

Yerel uygulamayı başlatmadan, durdurmadan veya teşhis etmeden önce
`docs/manual-testing-guide.md` bölüm 0 ve `deploy/compose/docker-compose.yml` dosyasını
oku; güncel Compose/health durumunu sorgula. Handoff'taki çalışma durumuna güvenme.

## 3. Kapsam ve karar sınırları

Yeni üretim bağımlılığı, dış orkestrasyon motoru, authentication değişikliği, yeni ağ
erişimi, üretim erişimi/deploy, veritabanı reseti ve yıkıcı kaynak temizliği bu görevin
varsayılan kapsamı değildir. Migration'ları silip yeniden başlatma; canlıda olmamak
yerel veriyi silme yetkisi vermez.

İlk envanterde her mevcut özellik için **korunuyor / aynı davranışla birleştiriliyor /
değişiklik öneriliyor** ayrımı yap. Önceki değerlendirmede canary, reusable kataloglar,
erişim talepleri veya kalite kapılarının azaltılabilir denmesi kaldırma onayı değildir.
Kullanıcının mevcut oturumda verdiği açık yetkiyi yeniden sorma; kapsamda olmayan
politika/API/güvenlik değişikliği için önce etkiyi, izin farkını ve geri dönüşü somutlaştır.
Yalnız o bağımlı adımı beklet, bağımsız keşif/test/tasarım işini sürdür. Her faz için
rutin onay döngüsü icat etme. Repository'nin açık değişiklik sınırlarını uygula.

## 4. Hedef tablo modeli ve sayım

**44 uygulama tablosu / mevcut 10 Django altyapı tablosuyla yaklaşık 54 toplam**,
temkinli bir tasarım referansıdır. Tablo kotası değildir. Aşağıdaki isimler alan
kavramlarıdır; yalnız estetik için mevcut public kimlikleri, URL'leri ve model adlarını değiştirme.

| Alan | Adet | Kavramsal modeller |
| --- | ---: | --- |
| Organizasyon, üyelik ve proje | 3 | `Organization`, `OrganizationMembership`, `AIProject` |
| İnsan yetki atamaları | 5 | `PlatformResponsibilityAssignment`, `OrganizationResponsibilityAssignment`, `ProjectResponsibilityAssignment`, `ScenarioResponsibilityAssignment`, `DocumentSetResponsibilityAssignment` |
| Senaryo ve tek yayın tanımı | 4 | `Scenario`, `ScenarioRevision`, `ScenarioCollection`, `ScenarioTool` |
| API istemcileri | 3 | `ApiClient`, `ApiCredential`, `ClientScenarioGrant` |
| Bağlantı tanımları | 1 | `Connection` |
| Veri ve indeksleme | 7 | `Collection`, `Source`, `Document`, `DocumentRevision`, `IndexGeneration`, `IndexGenerationDocument`, `Chunk` |
| Belge erişim talepleri/izinleri | 3 | `ScenarioDocumentSetAccessRequest`, `ScenarioDocumentSetGrant`, `DocumentSetGrant` |
| Ingestion işleri | 2 | `Job`, `Outbox` |
| Tool ve insan onayı | 3 | `Tool`, `ToolInvocation`, `ApprovalRequest` |
| Kalıcı yürütme | 8 | `Run`, `RunWait`, `RunBranch`, `RunJoin`, `RunChildLink`, `RunCompensationEntry`, `RunEvent`, `RuntimeControl` |
| Değerlendirme | 3 | `TestCase`, `EvalRun`, `EvalResult` |
| Denetim ve tüketim | 2 | `AuditEvent`, `UsageRecord` |

`Chunk` bu 44'e dahildir; ayrıca vektör tablosu veya runtime partition eklenmez.
İndeksler tablo değildir; migration ile yönetilen sabit arama indeksleri ayrıca envanterlenir.
İzin ilişkilerini veya sınırsız belge/olay listelerini JSON'a gömerek sayıyı tutturma.
Otomatik M2M tablolarını ve legacy tabloları fiziksel sayımdan gizleme.

Mevcut tüm modelleri bu hedefe **tek tek** eşle: alanlar, kimlikler, FK/unique/check
kısıtları, sahiplik, grant'ler, lifecycle, audit, çağıran servisler ve geçiş yöntemi.
Özellikle global profile katalogları ve tenant grant'lerini tek Connection'a taşırken
paylaşım/erişim davranışını kaybetme. Korunması gereken ek ilişki/özellik tablosu varsa
sayımı gerekçesiyle artır; yetkiyi veya özelliği sessizce kaldırma. Geçiş sırasında
eski ve yeni tabloların birlikte bulunması geçicidir; hedef sayı ancak temizlik
tamamlandıysa gerçekleşmiş sayılabilir.

## 5. Yetkilendirme sözleşmesi

Organizasyon, proje, senaryo ve korunan belge kapsamlarını birbirinden ayır.
Senaryo kullanma/düzenleme, yayınlama, runtime yönetimi, içerik okuma ve tool onaylama
aynı işlem değildir. Mevcut veya ayrıca onaylanmış rol matrisini merkezi sunucu
kararlarıyla uygula; geniş bir yeni role otomatik veri migration'ı yapma.

- Aynı organizasyondaki Proje A izni Proje B'ye; tek senaryodaki izin kardeş senaryoya taşmaz.
- UI görünürlüğü, liste sorguları, doğrudan ID erişimi, yazma, REST, MCP ve worker aynı
  güvenilir aktör/hedef/işlem kapsamından karar alır. İstemciden gelen tenant/rol güvenilir değildir.
- Koleksiyon bağlamak veri erişim izni vermek değildir. İnsan belge izni, senaryo
  veri izni ve mevcut consumer veri izinlerinin gerekli kesişimi korunur.
- API anahtarının senaryo çalıştırabilmesi organizasyondaki kaynakları/status kayıtlarını
  tarayabilmesi anlamına gelmez. Kaynak durum sorgularını da izinli ilişkilerden türet.
- Üyelik iptali, süresi dolmuş atama, belge silme, bağlantı/anahtar/tool kapatma eski
  snapshot veya cache üzerinden aşılamaz. Platform/organizasyon idaresini genel içerik iznine dönüştürme.
- Erişim, atama ve audit değişiklikleri mevcut transaction/fail-closed sözleşmesine uyar.

Ortak tabloda FORCE RLS ve transaction-local tenant kapsamı korunur. RLS tek başına
proje/senaryo/belge iznini sağlamaz; servis kapsamları da gerekir. Referansların tenant
tutarlılığını veritabanı ve yazma sınırında zorunlu kıl. Non-owner, non-BYPASSRLS
uygulama rolüyle gerçek PostgreSQL negatif testleri çalıştır.

## 6. Tek sabit vektör deposu

Depolama fazını [mevcut ayrıntılı plan](../shared-vector-storage/plan.md) ile yürüt.
Temel şartlar:

1. Tek migration-managed Chunk tablosu; tenant, mantıksal nesil, doğru belge revizyonu,
   ordinal/kind, text ve embedding kimlikleri. Legacy IndexedDocument ile managed
   DocumentVersion referanslarını kimlik çakışması yaratmadan dönüştür.
2. Normal build/retry/copy/activate/rollback/retention akışlarında **CREATE/ALTER/DROP yok**.
   Eski SECURITY DEFINER DDL fonksiyonlarının runtime erişimi de son durumda kaldırılır.
   İndeksleme başına partition veya HNSW yaratmak kabul edilmez.
3. Birden fazla embedding modeli ve boyutu aynı tabloda desteklenir; sonlu boyut/temsil/
   mesafe listesi ve sabit arama indeksleri dağıtımda tanımlanır. Yeni geometri kontrollü
   migration ister. Kurulu PostgreSQL extension sürümünü ayrıca doğrula.
4. Aynı boyut, aynı embedding uzayı demek değildir. Query modeli ve seçilen nesil birlikte
   çözülür; model/pipeline uyumsuzluğunda reuse yapılmaz. Mevcut boyut/hassasiyet sözleşmesini
   sessizce değiştirme; keyfi padding, kesme veya normalizasyon ekleme.
5. Vector/keyword/hybrid search, summary/content filtreleri, preview, citation çözümleme,
   copy ve evaluation yollarını taşı. Ortak tablonun varlığını her neslin hazır olduğuna kanıt sayma.
6. A aktifken B aynı tabloya yazılır; B eksiksiz doğrulanınca kullanılan nesil atomik değişir.
   Başarısız build A'yı bozmaz. Aktif/bitmiş nesle geç worker yazamaz; retry çoğaltmaz.
7. Retention sınırlı DELETE gruplarıdır; aktif/başvurulan nesillerin, çalışan işlerin ve
   retry/rollback pencerelerinin korunması kilit/fencing protokolüyle sağlanır.

Başlangıçta nesil başına chunk satırlarını kopyalamak kabul edilebilir.
IndexGenerationDocument manifest'i hangi belge revizyonlarının seçildiğini ve sıfır
parçalı belgelerin durumunu açıklar; Chunk ile tutarlılığı doğrulanır. Nesiller arasında
chunk paylaşımını ancak ölçülmüş ihtiyaç varsa ayrıca tasarla; manifest'i sınırsız JSON'a taşıma.

Paylaşılan ANN için tenant/nesil/ACL seçiciliğini, exact-search recall referansını,
prepared/generic planları, gecikmeyi ve VACUUM/disk etkisini ölç. Bir indeksin varlığı
doğru plan veya yeterli sonuç kalitesi kanıtı değildir. Desteksiz boyutu build öncesi
anlaşılır hatayla reddet; gizli runtime DDL veya sınırsız full scan ekleme.

## 7. Sürüm yönetimi: tek senaryo snapshot'ı

Üç ayrı kavramı koru:

- **Düzenleme revision'ı:** Taslağın eşzamanlı düzenleme kontrolü. Eski revision ile
  kaydetme çakışma döndürür; başka editörün değişikliği kaybolmaz.
- **ScenarioRevision:** Prompt, doğrulanmış graph, model/tool/retrieval ayarları,
  I/O şeması, ilgili bağlantı tanımları, checksum ve engine contract'ın tutarlı snapshot'ı.
- **IndexGeneration:** Veri hazırlığının teknik nesli. Kullanıcıdan ayrıca veri seti
  sürümü yayınlama ritüeli istemez; senaryo yayınıyla aynı lifecycle'a bağlanmaz.

Tek yayın komutu altında doğrulama/derleme ve mevcut gerekli kontroller çalışır;
başarısız yayın kullanılan revision'ı değiştirmez. Bağımsız ArtifactVersion,
WorkflowVersion ve ScenarioRelease zincirinin görevlerini snapshot ve doğrulama
servislerine taşı. Eski FK/ID/URL ve kanıt referanslarını dönüştürmeden modelleri kaldırma.
Küçük senaryoya ait config JSON olabilir; secret, yetki ilişkisi, büyük içerik,
sınırsız event veya yan etki kayıtları olamaz. Secret yerine güvenli referans tutulur.

Yeni işler kullanılan revision'a, devam eden işler başladıkları snapshot'a bağlıdır.
Taslak önizlemesi de tek snapshot alır; node'lar değişen taslağı tekrar tekrar okumaz.
Snapshot güncel izinleri aşamaz veya çalışan işe daha geniş yeni izin kazandıramaz.

Yayınlama işlemlerini UI'da birleştirmek mevcut kalite/audit/yetki kapılarını kaldırma
izni değildir. Senaryonun acil kapatma kontrolü kalır. Otomatik ilk aktivasyon,
manuel yayın onayını kaldırma veya kalite kapısını opsiyonel yapma gerekiyorsa mevcut
sözleşmeye etkisini açık karar olarak ayır; sırf daha az tıklama için atlama.

Runtime'ın release/artifact ORM bağımlılıklarını doğrulanmış bir resolved snapshot
sözleşmesine taşı. Worker/checkpoint engine sürümünü ayrıca yönet; config snapshot'ının
tek başına yazılım güncelleme uyumluluğu sağladığını varsayma.

## 8. Veri tazeliği, ingestion ve bağlantılar

Senaryo, izinli koleksiyona bağlanır. Her yeni retrieval adımı koleksiyonun o anda
kullanılabilir neslini seçer ve kullandığı nesil/belge revizyonlarını kaydeder.
Kaynak yenilenince senaryoyu yeniden yayınlamak gerekmez. Aynı adımın yeniden denemesi
için kayıtlı nesil/sonuç politikası kullanılır; güncel erişim iptalleri her zaman geçerlidir.
Çok koleksiyonlu adımda seçilen nesil kümesini kaydet. Özel sabitleme ihtiyacı varsa açık
ayar yap; bütün ajanları varsayılan olarak süresiz eski veriye kilitleme.

Collection/Source/Document/DocumentRevision modeli; dış kimlik, checksum, revision,
cursor/checkpoint, tombstone, schedule ve son başarılı durumları açıkça taşır.
Eksik sayfalama veya başarısız kaynak taramasını toplu silme sinyali sayma.
Değişmeyen içerik için mevcut uyumlu parse/embedding yeniden kullanımını koru.

REST/Confluence benzeri kaynakların tekrar eden kayıt/lifecycle kodunu kapalı şemalı
Job ve Outbox ile birleştir. İş niyeti ve outbox aynı transaction'da yazılır;
claim/lease/fencing, retry/idempotency, iptal ve OCR result-before-ACK garantileri sürer.
Bu Job modeli, gelişmiş workflow Run'ın yerine geçen ikinci bir genel motor değildir.

Connection tip doğrulamalı yapılandırma ve secret referansı taşır. Protokol uyumluluğu,
timeout, retry, SSRF, TLS ve private-network kuralları adapter/policy sınırında kalır.
Global sağlayıcı kataloğu ve tenant grant'leri varsa bunların erişim anlamını koru;
tek tabloda birleştirmek bütün tenant'lara bağlantı açmak değildir.

## 9. REST ve MCP kapsamı

Dört ayrı akışı uçtan uca ele al:

| Akış | Beklenen davranış |
| --- | --- |
| REST ingestion | İzinli kaynağı sayfalama/cursor ile çek, belge revizyonuna çevir, idempotent hazırla |
| MCP ingestion | Desteklenen resource keşfi/okumasını belge akışına bağla; içerik türü/boyut/sayfalama/auth sınırlarını doğrula |
| Çalışma sırasında REST/MCP tool | Doğrulanmış şema ve girdiyle çağır; gereken onayı al; sonucu ToolInvocation olarak kalıcılaştır |
| REST/MCP üzerinden senaryo çalıştırma | Ortak admission/yetki/runtime servisi; eşdeğer kapsam, kota, audit ve hata davranışı |

Mevcut MCP server veya tool adapter'ı bulunmasını MCP ingestion'ın hazır olduğuna
kanıt sayma. Mevcut kod ve seçilen protokol sürümünü doğrula; kaynakta desteklenmeyen
özellikleri açık hata ile belirt. Tool çıktısı otomatik belge koleksiyonu değildir;
indekslenecekse açık extraction sözleşmesi gerekir. Harici schema/description güvenilir
talimat, kod veya yetki sayılmaz. Kullanıcı adına downstream OAuth, token depolama veya
yeni egress gerekiyorsa kapsamını ayır; token'ı başka audience'a aktarma.

## 10. Kalıcı ajanlar ve insan onayı

Run, wait, branch/join, child link, compensation, invocation ve approval kayıtları
işletim durumudur; log sayıp kaldırma. Mevcut invariant'ları yeni snapshot modeliyle koru:

- Restart sonrası kaldığı yerden devam; atomik transition, lease/fencing ve tek kullanımlık resume.
- Aynı olayın tekrarı, iki worker veya geç kalan iş ikinci yan etki üretmez.
- Onay; gerçek başlatan, yetkili onaylayan, tool/hedef, exact girdi checksum'ı ve süreye bağlıdır.
  Girdi değişirse eski onay kullanılamaz. Kimliği doğrulanmayan başlatan için görev ayrılığı
  sağlanmış gibi davranma; gerekli onay politikası güvenli biçimde uygulanmalı.
- Yönetici/editör olmak otomatik onay izni değildir; self-approval ve güncel iptal kontrolleri korunur.
- Paralel dallar doğru sayıda ve bir kez birleşir; child run'ın kendi senaryo izni gerekir.
- Timeout sonrası dış işlem sonucu bilinmiyorsa kör retry veya telafi yapma; reconcile/
  operatör müdahalesi durumu açık olsun. Telafi ayrı yan etkidir, kendisi de başarısız olabilir.
- Yeni senaryo yayını eski işin graph/tool/telafi tanımını değiştirmez. Uyumsuz worker için
  compatible worker/drain/migration yolu tasarlanır; checkpoint sessizce dönüştürülmez.

Mevcut engine'i yeniden kullanmak başlangıç yönüdür; yalnız tablo azaltmak için Temporal
gibi yeni dependency veya ikinci yürütme motoru ekleme.

## 11. Kullanıcı deneyimi ve değerlendirme

Basit RAG yolunu **kaynağı bağla → veriyi hazırla → senaryoyu dene → yayınla** olarak sun.
Proje/senaryo erişimi görünür ve yönetilebilir kalsın. Gelişmiş workflow editörü aynı
yürütme çekirdeğini kullansın. Teknik nesil kimlikleri normal kullanıcıya zorunlu form
alanı olmasın; hata teşhisi ve audit için erişilebilir kalsın.

TestCase/EvalRun/EvalResult ortaklaşmasında amaç, test türü, case snapshot'ı,
senaryo revision'ı, veri nesli, politika sürümü, kanıt ve içerik erişimini koru.
Diagnostic veya LLM-judge başarısı zorunlu yayın kontrolü yerine geçmez. Test sorusu
ve kanıt özelliklerini birleştirme bahanesiyle kaldırma. AuditEvent ile yüksek hacimli
UsageRecord ayrı kalır; trace/request ID taşınır, secret/metin/vektör loglanmaz.

## 12. Uygulama sırası ve veri geçişi

1. **Güncel keşif:** Kod/migration/ayar/test envanteri, bütün model eşlemesi, izin matrisi,
   public sözleşmeler ve çalışan iş referansları. Planı gerçeğe göre düzelt; eski test
   sayımlarını yeniden çalıştırılmış gibi kullanma. Başlangıç kullanıcı adımlarını ölç.
2. **Dikey depolama geçişi:** Yetki/yayın davranışını değiştirmeden sabit Chunk,
   migration-controlled indeksler, tüm DAL yolları ve PostgreSQL kabul testleri.
3. **Senaryo snapshot'ı:** Eklemeli şema ve adapter ile tek ScenarioRevision, yayın
   koordinasyonu ve resolved runtime contract. Devam eden işlerin uyumluluğunu göster.
4. **Veri tazeliği ve ingestion:** Collection nesil seçimi, ortak Connection/Source/Job/
   Outbox, REST/MCP veri alma. Kaynak yenilenmesini senaryo yayınından ayır.
5. **Ürün bütünlüğü:** Console/Studio, tool/onay/parallel/telafi, evaluation ve REST/MCP
   dış sözleşmeleri aynı yeni modele bağla. İzinleri ve mevcut kullanıcı akışlarını doğrula.
6. **Geçiş/temizlik:** Veri ve kimlik doğrulaması, kontrollü yazıcı kesimi, geri dönüş
   provası; yalnız ayrıca yetkilendirilmiş legacy kaldırma. ADR ve güncel davranış belgeleri.

Her faz çalışır ve test edilmiş olmalı. Önceden tamamlanmış eşdeğer fazı yeniden yazma.
Tek seferde tüm modelleri silip testleri sonradan uyarlama yaklaşımını kullanma.

Migration planı her model için aktarılacak içerik/ID/FK/grant/audit ilişkisini, sayım ve
checksum doğrulamasını, batch/resume/idempotency davranışını ve eski/yeni web-worker
uyumluluğunu kapsar. Varsayılan eklemeli ve veriyi koruyan geçiştir. Kaynak/secret gibi
hassas veriler export/log yoluyla sızmamalı. Tek yetkili yazıcı ve kesim anı açık olmalı;
gerekmedikçe çift yönlü dual-write kurma. Yeni yazılardan sonra eski şemaya dönüşün
nasıl veri kaybetmeyeceğini kanıtla; yalnız eski tabloların durması rollback değildir.

Eski tabloların DROP edilmesi veya veri reseti gerektiğinde tam envanter, doğrulama,
saklama/yedek ve geri dönüş sınırı hazır olsun. Onaysız çalıştırma. Geçici read-only
legacy tablolar varsa gerçek toplam sayıda göster; hedef 54 gerçekleşmiş deme.

## 13. Zorunlu kabul kanıtları

| Test | Beklenen kanıt |
| --- | --- |
| Basit RAG | Kaynak bağlama, hazırlama, soru, citation ve tek senaryo yayını gerçek akışta çalışır |
| Tenant/proje/senaryo izolasyonu | Aynı tenant'ta farklı proje/senaryo ve farklı tenant için liste/detail/POST/API/MCP/preview/retrieval/status erişimi reddedilir |
| Yetki eşdeğerliği | Mevcut atama/grant'ler dönüşümle genişlemez veya kaybolmaz; onaylı politika farkları ayrı test edilir |
| Tek sabit depo | Tekrarlanan build, retry, rollback, cleanup ve farklı destekli modeller sırasında tablo/index/partition sayısı artmaz; normal yol DDL çağırmaz |
| Model/boyut | Doğru modelden query, mismatch reddi, uyumlu reuse, desteklenmeyen geometride build öncesi ret |
| Kalite/performans | Exact-search referansına göre recall, yetkili sonuç sayısı, p95 gecikme, tenant seçiciliği ve vacuum/disk ölçümü; kabul eşikleri kaydedilir |
| Veri yenileme | Yeni belge bilgisi senaryo republish olmadan gelir; yarım sync eski hazır veriyi bozmaz |
| Silme/iptal | Eski nesil/snapshot veya rollback silinen/yetkisi alınan içeriği geri açmaz |
| Snapshot | Eşzamanlı edit çakışması, başarısız yayın, yeni yayın sırasında eski işin tutarlı devamı |
| Durable runtime | Restart, duplicate delivery, lease kaybı, tek resume, tek join ve child yetki kontrolü |
| Tool/onay/telafi | Exact girdi onayı, gerçek initiator, iptal/expiry/self-approval, unknown outcome ve başarısız telafi |
| Migration/rollback | Tekrarlanan aktarım, tenant bazlı sayım/checksum/ilişki eşitliği, eski citation ID'leri ve kesim sonrası veri kaybetmeyen dönüş |
| Observability | Güvenli audit karar/sonuç/trace, mevcut audit hata politikası, secret/chunk/vektör redaksiyonu |

Güncel repository CI/manifest/test belgelerindeki doğrulanmış komutları kullan.
İlgili backend unit/integration/contract/security testleri; gerçek PostgreSQL RLS,
constraint, concurrency ve migration testleri; frontend test/typecheck/build;
formatter/linter/type-check, migration drift ve secret/security kontrollerini çalıştır.
Gerekli kapsama göre genişlet; aynı geçen testleri gerekçesiz tekrar çalıştırma.
SQLite veya mock sonucu PostgreSQL kanıtı değildir. Test ortamını bilinçli izole et;
yerel provider ayarlarının testleri dış servise yönlendirmediğini doğrula. İlk hatayı
ve düzeltme/izolasyon gerekçesini kaydet; testi silerek veya kontrolü gevşeterek geçirme.

Güncel build üzerinde repository'nin zorunlu browser gate'ini uygula. İzinli kullanıcı,
başka proje/senaryo kullanıcısı ve başka tenant ile temel RAG/yayın/erişim/onay yolunu
dene. Erişilemeyen runtime, gerçek provider, kapasite veya tarayıcı kontrolünü açık
eksik kanıt olarak raporla; passing/Verified sayma.

## 14. Teslim ve tamamlanma

Plan, riskler, model/davranış eşlemesi, migration/rollback ve verification kayıtları
güncel olsun. Uygulanan durable kararlar için eski ADR geçmişini silmeden yeni ADR
oluştur; hangi kararın hangi bölümünün değiştiğini belirt. Ana plan, gerçek davranış
belgeleri, kullanıcı kılavuzu ve işletim adımlarını güncelle. Uygulama bitince arşiv
politikasını uygula; aktif handoff'u yalnız devam edecek iş varsa gereken bilgilerle güncelle.

Son diff'i mimari, uygulama güvenliği ve SRE açısından incele. Başarıyı yalnız tablo
azalmasıyla ölçme: ilk RAG'a ulaşma adımları, prompt yayını, veri yenileme, adapter
ekleme ve başarısız işi kurtarma maliyetindeki değişimi somut örneklerle raporla.

Son rapor şu alanları içersin: **Summary; Files changed; Architecture impact;
Security impact; Authorization impact; Data and privacy impact; Logging, metrics,
tracing and audit impact; Database and migration impact; Tests and verification
results; Unverified assumptions; Remaining risks; Manual review required.**
Uygulama, Django ve geçici legacy fiziksel tablo sayılarını ayrı ver. Implemented
ve Verified durumlarını ayır; geçiş/temizlik veya zorunlu kanıt eksikken bütün
mimari dönüşümü tamamlandı olarak işaretleme.
