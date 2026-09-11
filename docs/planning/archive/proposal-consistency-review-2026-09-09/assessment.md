# AgentHub fikir ve talimat tutarlılığı incelemesi

9 Eylül 2026. **Yalnız değerlendirme; uygulama başlatılmadı.** Kullanıcının verdiği
konum çalışma ağacında `docs/tasks/Agent_Hub_MD` olarak bulundu.

## Sonuç

Fikirlerin ana yönü mantıklı: teknik kurulum adımlarını kullanıcıdan uzaklaştırmak,
senaryo durumunu anlaşılır göstermek, veriyi senaryolarda tekrar kullanmak ve işletim
yükünü azaltmak. Ancak bu yedi klasör tek, uzlaştırılmış uygulama şartnamesi değil.
Mevcut davranışı koruyan arayüz işleri, davranışı değiştiren mimari öneriler ve
önceden uygulanmış gezinme işi aynı pakette bulunuyor.

En önemli sorun fikirlerin kendisinden çok **karar, uygulama kapsamı ve sıra
ayrımının yeterince açık olmaması**. Hepsini birlikte bir ajana “uygula” diye
vermek doğru olmaz. Aşağıdaki değerlendirme önerilerin kabul edildiği anlamına gelmez.

İnceleme sırasında kullanıcı bir tasarım tercihini netleştirdi: **proje/senaryo
yöneticisi düzenleme, yayın ve operasyonu birlikte yönetebilsin**. Bu tercih
uygulama izni değildir. Eski atamaların otomatik yükseltilmesi, doküman okuma,
araç onayı veya ortak istemci verisi için ayrıca karar verilmiş sayılmaz.

## Paket neden tasks içinde ve neden iki yerde?

[Görev belgeleme kuralı](../../../tasks/README.md), çok bileşenli işler için plan,
risk modeli ve doğrulama kaydı ister. Yetkilendirme, RAG ve UI belgelerinin
doğrulama kayıtları da kullanıcı isteğinin “kodlama ajanına verilecek Markdown
talimatı hazırlamak” olduğunu söylüyor. Bunların task biçiminde hazırlanmasını
belgeler bu şekilde açıklıyor. Önceki konuşmanın tamamı veya kopyalama işleminin
kaynağı görülmediği için kimin hangi amaçla kopyaladığını kesin söyleyemem.

SHA-256 karşılaştırması: **7 klasördeki 22 dosyanın tamamı**, doğrudan
`docs/tasks/<aynı-ad>/` altındaki karşılıklarıyla birebir aynı. Mevcut kopyalar
arasında içerik farkı yok. İki yer de Git açısından henüz izlenmeyen dosyalar;
bu durum içeriklerin onaylandığını veya uygulandığını göstermez.

`Planned`, [durum sözlüğünde](../../../ai/definition-of-done.md) kapsam/yaklaşımın
kaydedildiğini ifade ediyor; ayrı bir kullanıcı onayı alanı yok. Dolayısıyla
task klasöründe bulunmak uygulama emri değildir. Yine de kararsız fikirler için
“Öneri — uygulama onayı yok” etiketinin eksikliği yanlış başlangıç riskini artırıyor.

**Belge yerleşimi önerisi:** Tek bir asıl kaynak, diğer yerde sadece bağlantılı
dizin veya açıkça tarihli ve değiştirilmeyen bir paylaşım paketi kullanılsın.
Onaylanmamış tasarımlar için `docs/proposals/` benzeri ayrı bir alan düşünülebilir;
uygulanmış gezinme işi aktif görev kaydında kalsın. Bu incelemede dosyalar
taşınmadı, silinmedi veya özgün talimatlar değiştirilmedi.

## Dosya gruplarının değerlendirilmesi

| Grup | Gerçek kayıt durumu | Değerlendirme |
| --- | --- | --- |
| [Gezinme](../../../tasks/console-navigation-2026-09-08/plan.md) | Implemented; tam yaşam döngüsü tarayıcı kabulü açık | Yeniden yapılacak fikir değil. Mevcut sonuç korunmalı; kabul açığı ayrı takip edilmeli. |
| [Senaryo ayrıntısı](../../../tasks/scenario-detail-ux-simplification/plan.md) | Planned; doğrulama dosyası hazırlık incelemesini anlatıyor | En somut ve faydası en kolay ölçülebilir önerilerden. Durum modeli, görev ayrımı ve legacy davranışı iyi düşünülmüş. |
| [Genel UI](../../../tasks/console-ui-redesign/plan.md) | Planned; belge teslimi | Mantıklı çatı; senaryo işi bunun alt işi. Bütün sayfaları tek teslimde yenileme kapsamı fazla geniş. Pilot yaklaşımı korunmalı. |
| [REST sihirbazı](../../../tasks/rest-data-source-wizard/implementation-instructions.md) | Yalnız uygulama talimatı; ayrı plan/risk/doğrulama kaydı yok | Kullanıcı sorunu gerçek; fakat yalnız form birleştirme işi değil. Yetki, canlı önizleme ve kaynak güncelleme tasarımı eksik. |
| [Ortak vektör deposu](../../../tasks/shared-vector-storage/plan.md) | Planned; uygulama/performans kanıtı yok | Teknik olarak uygulanabilir ve sınırları iyi yazılmış. Kazanç, yük ve arama kalitesi ölçümleriyle doğrulanmalı. |
| [Yetkilendirme](../../../tasks/authorization-simplification/plan.md) | Planned | Kullanıcının yönetici rolü tercihiyle uyumlu. Rol görünümü ile gerçek erişim değişiklikleri ayrı aşamalar olmalı. |
| [RAG mimarisi](../../../tasks/rag-architecture-simplification/plan.md) | Planned | Tek yayın deneyimi ve bağımsız veri yenileme güçlü hedefler. 44/54 tablo ve tüm model dönüşümü henüz uygulanabilirliği kanıtlanmış tasarım değil. |

## Somut tutarsızlıklar ve eksikler

### 1. Kopya pakette 26 bağlantı bozuk

22 dosyadaki 64 yerel Markdown/görsel bağlantısının 38'i çözümleniyor, **26'sı
çözümlenmiyor**. Paket bir klasör daha derine kopyalanırken `../../planning`,
`../../ai` ve `../../../apps` gibi yollar güncellenmemiş.

Örneğin paket içindeki UI talimatının `../../../AGENTS.md` bağlantısı repository
köküne değil `docs/AGENTS.md` konumuna gidiyor. Tasarım görsellerinin bağlantıları
da bozulmuş. Yetkilendirme planında 2, talimatında 1; UI talimatında 10; RAG
talimatında 3; senaryo planında 1; vektör planında 9 bozuk bağlantı var.

Bu, yalnız estetik sorun değil: ajanın uyması gereken kurallara ve kararın asıl
kaynağına erişimini zorlaştırır. Özgün konumda başarılı olmuş eski bağlantı
kontrolü, kopyalanmış paket için geçerli değildir.

### 2. Bazı metinler fikirleri uygulama kararı gibi sunuyor

[REST talimatı](../../../tasks/rest-data-source-wizard/implementation-instructions.md)
“bir tasarım önerisi değil, uygulanacak ürün geliştirme kapsamıdır” diyor.
[UI talimatı](../../../tasks/console-ui-redesign/implementation-instructions.md)
dosyayı alan ajana doğrudan uygulama emri veriyor.
[Yetki talimatında](../../../tasks/authorization-simplification/implementation-prompt.md)
“hedef rol modeli — uygulama kararı” başlığı var; aynı belgenin girişinde ise
kullanıcı uygulama görevi verince başlayacağı açıkça belirtilmiş.

Bunlar gelecekte kullanılacak uygulama prompt'u olarak anlaşılabilir, ancak
paketin henüz seçilmemiş fikirlerden oluştuğunu tek başlarına açık anlatmıyor.
Önerilen ortak üst not: “Tasarım adayıdır. İnceleme veya dosyayı okuma isteği
uygulama izni değildir. Uygulama kapsamı ayrıca seçilecektir.” Bu not öneridir;
özgün belgelere bu tur eklenmedi.

### 3. Arayüz talimatı ile yeni yetki hedefi aynı nihai sözleşme olamaz

[Senaryo talimatı](../../../tasks/scenario-detail-ux-simplification/implementation-instructions.md)
editör/yayın yöneticisi/runtime operatörü ayrımını değiştirilemez sınır sayıyor;
örneğin yayın yöneticisinin düzenleme yetkisi kazanmamasını test ettiriyor.
[Yeni yetki talimatı](../../../tasks/authorization-simplification/implementation-prompt.md)
ise normal yöneticiye bunları birlikte veriyor. Kullanıcı ikinci yönü tercih etti.

**Uzlaştırma:** Yeni temel Yönetici rolü birleşik olabilir; eski uzman atamalar
dar yetkileriyle korunabilir. Bu durumda eski Release Manager testi uzman rolü
için geçerli kalır, yeni Yöneticiye uygulanmaz. Senaryo UI planı uygulamadan önce
hangi politika sürümünü hedeflediğini açıkça belirtmeli. Salt UI aşaması mevcut
politika üzerinde yapılabilir; birleşik rol geldiğinde eylem görünümü uyarlanır.

Bu tercih proje devralmasının bütün ayrıntılarını çözmez. Özel senaryoya proje
yöneticisinin kendisini atayabilmesi, varsayılan devralma ve eski kayıtların
taşınması hâlâ açık ürün/geçiş kararlarıdır. Doküman içeriği ve araç onayı için
ayrı sorumluluk korunması doğru.

Kaynak teyidi: [merkezi yetki matrisi](../../../../apps/identity/authorization.py)
ve [ADR-0015](../../../adr/0015-responsibility-based-operator-authorization.md)
bugün dar, ayrı sorumluluklar tanımlıyor. Eski ADR'deki 30 Temmuz'a ait
“demo verisi silinebilir” kararı bu yeni incelemeye reset yetkisi taşımaz.

### 4. Veri sürümü seçimi için tek bir hedef davranış seçilmemiş

UI/REST belgeleri set sürümü, exact release referansı ve mevcut yayın kurallarını
koruyor. [RAG talimatı §7–8](../../../tasks/rag-architecture-simplification/implementation-prompt.md)
ise her yeni retrieval adımında koleksiyonun kullanılabilir neslini seçmek ve veri
yenilemesini senaryo yayınından ayırmak istiyor. Bu yalnız görünüm değişikliği değil.

Güncel kod daha nüanslı: [set sürümü çözümü](../../../../apps/documents/services.py)
release'e belge seti sürümünü sabitliyor; [retrieval](../../../../apps/retrieval/providers.py)
o izinli set sürümünün aktif indeksini seçiyor. Dolayısıyla “bütün indeksler
daima exact sabit” ifadesi de mevcut davranışı tam anlatmıyor. Yeni bir set
sürümüne geçişle aynı set sürümünün indeksini değiştirmek farklı durumlar.
[İndeks aktivasyonu](../../../../apps/ingestion/staged_build.py) aktif release
etkisini ayrıca denetliyor; [connector otomasyonu](../../../../apps/ingestion/automation.py)
belirli yolda yeniden release derleme/değerlendirme/yayınlama yapıyor.

**Önerim:** Hızlı RAG hedefinde en son başarıyla hazırlanıp kullanıma alınmış
veriyi takip etmek varsayılan adayı olsun; belirli veri sürümünü sabitleme açık
seçenek olarak değerlendirilsin. Bu kullanıcı tarafından henüz seçilmedi.
“Güncel veri” yarım sync'in veya yeni taslağın otomatik servis edilmesi değildir.
Yayın geri dönüşünün yalnız yapılandırmayı mı, veriyi de mi geri aldığı ve uzun
işlerde iki retrieval adımının farklı nesil görüp göremeyeceği kabul örnekleriyle
tanımlanmalı. İzin iptali/silinmiş içerik kontrolü her seçenekte canlı kalmalı.

### 5. REST sihirbazının platform yöneticisi kabulü mevcut yetkiyle uyuşmuyor

Talimat, platform yöneticisinin kaynağı tek sihirbazda oluşturmasını bekliyor.
[REST servisleri](../../../../apps/ingestion/rest_services.py) profil oluşturma/grant
için platform idaresi, contract/source oluşturmak için ise exact set içerik
yönetimi arıyor. [Yetki matrisi](../../../../apps/identity/authorization.py) günlük
global yöneticiye bu içerik yetkisini vermiyor;
[can_manage_documents](../../../../apps/tenancy/services.py) de bu ayrımı koruyor.

Yalnız platform yöneticisi rolü olan bir kullanıcıyla vaat edilen yol tamamlanamaz.
Kurtarma superuser'ıyla test etmek bu açığı örter.

**Önerim:** Platform yöneticisi bağlantıyı ve kullanım iznini hazırlar; set
yöneticisi eşleme, kaynak ve hazırlama kısmını tamamlar. Her iki açık sorumluluğu
taşıyan kişi aynı sihirbazı kesintisiz bitirebilir. Alternatif, platform rolüne
yeni içerik yetkisi vermektir; mevcut ayrı yetki hedefiyle uyumlu bulmadığım için
önermiyorum. Kaynak cevabını görsel eşleme için göstermek de veri erişimidir:
yalnız bağlantı yönetebilmek örnek içeriği okuyabilmek sayılmamalı. İlk sürümde
sentetik örnek kullanımı bu sınırın tasarımını kolaylaştırır.

### 6. REST kaynağı düzenleme, tarif edildiğinden daha büyük bir iş

REST talimatı “yeni profil/contract/source revision zinciri” ve eski kaynağı
koruyarak staged geçiş istiyor. [Source modeli](../../../../apps/ingestion/models.py)
revision alanı taşımıyor; profil ve contract taşıyor. Cursor kimliği
`(source, external_id)`, schedule ise source'a bire bir bağlı. Kaynağı klonlamak
yeni revision yaratmakla eşdeğer değil; checkpoint, belge kimliği, takvim ve
aynı kaynağı iki kez çekme davranışı tasarlanmalı.

Kök path sorunu da gerçek bir kod koşuluna dayanıyor:
[REST validator](../../../../apps/ingestion/rest_schema.py) `/` için boş segment
ürettiğinden reddediyor. Çözüm, serbest URL kabul etmek değil mevcut allowlist
ve URL birleşimi güvenliğini koruyan dar sözleşme düzeltmesi olmalı.

**Önerim:** İlk dilim mevcut grant edilmiş profillerle kaynak oluşturma ve
sentetik görsel eşleme; sonraki dilim canlı preview; ayrı dilim revizyon/geçiş.
“Tüm modeller korunacak” REST hedefi, RAG'ın bunları Connection/Job altında
birleştirme hedefiyle aynı anda nihai şart olamaz. Sihirbazın kullanıcı akışı
kalabilir; dayandığı model sözleşmesinin hangi aşamaya ait olduğu belirtilmeli.

### 7. Tek sabit vektör tablosu mantıklı, kesin performans kazancı değil

[Plan](../../../tasks/shared-vector-storage/plan.md) aynı boyutu aynı model saymama,
runtime DDL kaldırma, RLS, atomik nesil seçimi ve veri koruyan geçiş konularını
iyi ele alıyor. Güncel [vector_store](../../../../apps/ingestion/vector_store.py)
hâlâ `chunk_iv_<id>` ve kontrollü DDL fonksiyonu kullanıyor; öneri uygulanmış değil.

Farklı boyutları bir `vector` kolonunda saklamak ve aynı boyutlu satırlara ayrı
indeksler kurmak destekleniyor. Bununla birlikte ortak yaklaşık arama indeksinde
bir tenant'ın verileri diğerinin recall ve hızını etkileyebilir; filtreler daha
az sonuç dönmesine yol açabilir. Bu, tek başına veri sızıntısı tespiti değildir;
erişim izolasyonu ile kalite/kapasite izolasyonu ayrılmalıdır.
[pgvector resmî belgeleri](https://github.com/pgvector/pgvector#multitenancy),
[farklı boyutlar](https://github.com/pgvector/pgvector#can-i-store-vectors-with-different-dimensions-in-the-same-column).
Partial indeksin sorgu koşuluyla planlama aşamasında eşleşmesi de gerekir;
prepared/generic sorgu yolları ayrıca kontrol edilmeli.
[PostgreSQL belgeleri](https://www.postgresql.org/docs/current/indexes-partial.html).

**Karar öncesi kanıt:** Hedef boyut/model listesi, örnek tenant/nesil dağılımı,
recall ve p95 sınırları, eşzamanlı build yükü, disk/retention maliyeti. Bir tablo
isteğinin teknik bedeli kabul edilebilir çıkarsa ayrı ve sınırlı bir depolama
işi olarak uygulanabilir; bütün RAG modellerini değiştirmek önkoşul değil.
Kurulu extension sürümü ve gerçek veri hacmi bu incelemede sorgulanmadı.

### 8. 44/54 tablo hesabı doğru sayım olabilir; tamlık kanıtı değil

Yeni RAG listesi 44 uygulama kavramı içeriyor ve 10 Django tablosuyla 54 diyor.
Fakat [eski 35-model eşlemesi](../rag-product-architecture-reassessment-2026-09-08/target-model.md)
canary, reusable kataloglar ve bazı grant yapılarını azaltma varsayımları içeriyor.
[Yeni talimat](../../../tasks/rag-architecture-simplification/implementation-prompt.md)
bunların sessizce kaldırılmasını yasaklıyor ve gerektiğinde sayının artırılmasına
izin veriyor. Bu koruma doğru; ancak eski listeye dokuz yetki tablosu eklemek,
bütün kalan özelliklerin korunabildiğini henüz göstermiyor.

Tek Connection altında global profil kataloğu ile tenant/set grant'leri; ortak
değerlendirme altında soru seti paylaşımı/sürümleri; release snapshot'ı altında
canary, alias ve geçmiş kanıt referansları tek tek eşlenmeli. UI sadeleşmesi
bağımsız reusable bileşenleri veritabanından kaldırmayı zorunlu kılmaz.

**Önerim:** Tablo sayısı başarı ölçütü olmasın. İlk RAG kurulum süresi, prompt
değişikliğini güvenle yayına alma, veri yenileme ve başarısız işi kurtarma adımları
ölçülsün. Tek yayın deneyimi önce mevcut servisleri koordine ederek sağlanabilir;
sonra gerçekten maliyet yaratan model sınırları değiştirilebilir. Mevcut kalıcı
wait/branch/join/child/compensation modellerini yeniden yazmak gerekçelendirilmiş değil.

### 9. MCP durum kapsamı bulgusu büyük dönüşümü beklememeli

Yetki belgesindeki [MCP _ingestion_status](../../../../apps/mcp/service.py) bulgusu
güncel kaynakta mevcut: sorgu organizasyonun ingestion run'larıyla başlıyor;
izin kontrolü ise herhangi bir aktif binding'de `ingestion_read` bulunmasına
bakıyor. Yorum kaynak projesi diyor, kod o ilişkiyi sınamıyor. Bu, aynı
organizasyondaki ilgisiz kaynak metadata'sına erişim riski; cross-tenant ihlali
veya doküman içeriği sızıntısı olarak sunulmamalı.

**Önerim:** Bunu rol sadeleştirmesinden bağımsız, küçük bir güvenlik işi olarak
ele al. İlgisiz kaynağı hedefleyen negatif test, kaynak seçilmeden önce yetkili
ilişki filtresi ve güvenli hata davranışı gereksinimi netleştirilsin. Bu tur
kod değişmedi ve çalışma zamanında exploit/negatif test çalıştırılmadı.

## Çelişki olmayan örtüşmeler

- UI çatısı → senaryo ayrıntısı → mevcut gezinme sonuçları hiyerarşisi belgelerde
  zaten kurulmuş. Bunları üç bağımsız yeniden tasarım olarak başlatmamak yeterli.
- RAG → ortak vektör depolama ilişkisi açıkça alt iş olarak yazılmış; ikinci
  depolama katmanı veya ikinci migration dizisi gerekmiyor.
- Tek senaryo yapılandırma snapshot'ı ile ayrı veri nesli kavramı birbiriyle
  uyumlu. Eksik olan seçim zamanı, aktivasyon ve geri dönüşün kesin sözleşmesi.
- Üç görünür temel rol, sunucuda yalnız üç izin bulunması demek değil. Ayrıntılı
  eylem kontrollerini koruyup kullanıcıya basit rol paketleri sunmak mantıklı.
- Eski uzman rollerin uyumluluk için kalması doğru; kısa vadede iç karmaşıklık
  artabilir. Bu geçici maliyet, kullanıcı arayüzünün sadeleşmesine engel değil.

## Önerilen karar ve çalışma sırası

1. **Belge statüsü:** Tek asıl kaynak ve açık öneri/onay durumu seç; uygulanmış
   gezinme işini fikirlerden ayır. Mevcut talimatların topluca yürütülmesini önle.
2. **Bağımsız mevcut kusur:** MCP kaynak durum kapsamı için dar düzeltme işini
   ayrıca değerlendir; büyük mimari onayı beklemesin.
3. **Ürün sözleşmeleri:** Birleşik yönetici tercihi kaydedildi. Veri tazeliği,
   özel senaryoya idari erişim, ortak istemci verisi ve REST kurulum aktörlerini seç.
4. **Düşük geçiş maliyetli fayda:** Senaryo durum ekranı ve doküman pilotu;
   kaynakta mevcut servisler üzerinden REST oluşturma/eşleme deneyimi. RAG
   dönüşümü yakında seçilecekse aynı modeller için büyük revizyon altyapısını ertele.
5. **Depolama kanıtı:** Ortak tablo için sınırlı, temsili kalite/kapasite deneyi.
6. **Ayrı uygulama kararları:** Birleşik rol ve devralma geçişi; veri tazeliği;
   gerekçelendirilirse model/snapshot dönüşümü. Her birinin kabulü ve geri dönüşü ayrı.

Bu sıra benim önerimdir; kullanıcı tarafından bir uygulama takvimi olarak onaylanmadı.

## Kullanıcıda kalan kararlar

| Karar | Önerim | Anlamı |
| --- | --- | --- |
| Yönetici yetkileri | **Kullanıcı birleşik yönü seçti** | Düzenleme + yayın + operasyon; uygulama/geçiş henüz yok. |
| Veri yenileme | Son başarılı ve kullanıma alınmış veriyi takip etme varsayılan adayı | Yapılandırma rollback'i veriyi otomatik geri almayabilir; sabitleme seçeneği ayrıca tanımlanır. |
| İstemciler aynı veriyi mi görür? | Önce mevcut istemciye özel kesişim; ortak mod yalnız ihtiyaç varsa | Ortak mod gelecekte eklenecek izinli istemcileri de kapsar; rol sadeleştirmesinin doğal sonucu değildir. |
| Özel senaryonun proje yöneticisine sınırı | İdari erişim/kendini atama açıkça anlatılsın | Mutlak gizlilik bekleniyorsa mevcut öneri o beklentiyi sağlamaz. |
| REST kurulumu | Bağlantı idaresi ve veri yönetimi iki sorumluluk; aynı kişide açıkça birleşebilir | Platform rolüne örtük içerik yetkisi verilmez. |
| Mimari yatırım | Önce ölçülebilir UX ve depolama adımları | 44 tablo hedefiyle bütün sistemi dönüştürmek şu an gerekçelendirilmiş değil. |

## İnceleme sınırları

22 dosya ve ilgili asıl kayıtlar, kök talimatlar, master plan, ilgili ADR/önceki
eşleme, seçili kaynak ve test bölgeleri incelendi. Bu bütün repository'nin
güvenlik denetimi veya mevcut uygulamanın tam doğrulaması değildir. Önceki test
sayıları yeniden çalıştırılmış sayılmadı; runtime, PostgreSQL, provider, tarayıcı
ve performans testleri yapılmadı. Kod, migration, veri, çalışan servis ve özgün
öneriler değişmedi. Ayrıntılı kanıt ve nihai etki raporu [verification.md](verification.md)
dosyasındadır.
