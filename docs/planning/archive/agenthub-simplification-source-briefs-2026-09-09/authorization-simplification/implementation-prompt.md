# AgentHub yetkilendirmesini sadeleştir — kodlama ajanı uygulama talimatı

> Bu belgenin tamamını kodlama ajanına ver ve uygulamasını iste.
> Hazırlanma: 9 Eylül 2026. Durum: uygulama talimatı hazır; kod değişikliği yapılmadı.
> Hedef, kullanıcıya daha az rol ve daha anlaşılır erişim yönetimi sunmaktır.

## 1. Görev

AgentHub'ın yetkilendirmesini bu belgedeki hedef modele göre uçtan uca uygula.
Yalnız öneri, ekran maketi veya checkbox gizleme ile bitirme. Sunucu kararları,
kapsam filtreleri, atama servisleri, Django ekranları, React Studio, REST/MCP,
uyumluluk geçişi, audit ve testler birlikte tamamlanmalı.

Organizasyon, proje ve senaryo erişim sınırlarını koru. Proje/senaryo seviyesini
organizasyon üyeliğine indirgeme. Kullanıcının yönetmek zorunda olduğu rol
sayısını azalt; güvenlik için gerekli sunucu işlem kontrollerini koru.

Kodlamadan önce kök `AGENTS.md`, ilgili alt talimatlar ve
[görev planını](plan.md) oku. Tek ana ajanla çalış, repository işini alt ajanlara
devretme. Mevcut yerel değişiklikleri koru. Codebase Memory/Serena varsa proje ve
indeks doğruluğunu kontrol ederek kullan; yoksa doğrudan kod, `rg` ve testlerle ilerle.
Çalışan uygulamayı kullanmadan önce `docs/manual-testing-guide.md` bölüm 0 ve
canonical Compose dosyasını oku, gerçek servis durumunu sorgula.

Bu dosyanın hazırlanması uygulamanın yapıldığı veya canlı geçişe izin verildiği
anlamına gelmez. Kullanıcı bu görevin uygulanmasını istediğinde aşağıdaki hedef
matrisi esas al; aynı kapsam için tekrar tekrar teyit isteme. Yeni üretim
bağımlılığı, authentication değişikliği, üretim erişimi, deploy, yıkıcı migration
ve veritabanı reseti bu görevin kapsamı değildir.

## 2. Hedef rol modeli — uygulama kararı

| Kapsam | Normal ekranda sunulacak roller |
| --- | --- |
| Platform | Platform yöneticisi; günlük kullanımdan ayrı mevcut kurtarma kimliği |
| Organizasyon | Üye, Yönetici |
| Proje | Görüntüleyen, Düzenleyen, Yönetici |
| Senaryo | Görüntüleyen, Düzenleyen, Yönetici |
| Doküman seti | Okuyucu, Yönetici |

- Organizasyon **Üye** ayrı yetki ataması değildir; aktif üyeliği temsil eder.
  Tek başına proje, senaryo veya doküman içeriğini açmaz.
- Organizasyon **Yönetici** üyeleri, proje erişimini, doküman sorumluluklarını
  ve senaryo onaylayanlarını yönetir. Tek başına içerik okuma, senaryo düzenleme
  ve araç onaylama yetkisi kazandırma. İş yapmak için ilgili proje/senaryo rolünü
  açıkça atayabilsin; atama ve kaynak görünür ve auditable olsun.
- Platform yönetimini normal bir bütün içeriklere erişim rolüne dönüştürme.
- Organizasyon Denetçisi, senaryo Onaylayanı ve mevcut uzman görevler gelişmiş
  bölümde kalabilir; temel rol seçicisini kalabalıklaştırmasın.
- Özel rol oluşturma, keyfi capability kutuları, politika DSL'i ve yeni bir
  harici yetkilendirme motoru ekleme.

### Proje işlemleri

| İşlem | Görüntüleyen | Düzenleyen | Yönetici |
| --- | --- | --- | --- |
| Projeyi ve izinli senaryo metadata'sını görme | Evet | Evet | Evet |
| Projede senaryo oluşturma | Hayır | Evet | Evet |
| Proje ayarlarını yönetme | Hayır | Hayır | Evet |
| Projedeki üyelerin temel proje rollerini yönetme | Hayır | Hayır | Evet |
| Standart senaryolara aktarılan temel rol | Görüntüleyen | Düzenleyen | Yönetici |

Proje yöneticisi yalnız aynı organizasyonun aktif üyelerine kendi projesi içinde
bu üç rolü atayabilir. Organizasyon/platform yöneticiliği, başka proje yetkisi,
doküman içerik yetkisi veya onaylayan sorumluluğu atayamaz. Son proje yöneticisini
yanlışlıkla erişimsiz bırakmayı engelle; organizasyon erişim idaresi kurtarma
yoludur. Mevcut üyelik iptali ve süresi dolmuş atama kuralları aynen geçerlidir.

### Senaryo işlemleri

| İşlem | Görüntüleyen | Düzenleyen | Yönetici |
| --- | --- | --- | --- |
| İzinli senaryo tanımı ve metadata'sını görme | Evet | Evet | Evet |
| Prompt, workflow, düğüm, retrieval ayarı ve test sorusu düzenleme | Hayır | Evet | Evet |
| İzin verilmiş doküman setini senaryoya bağlama | Hayır | Evet | Evet |
| Aday hazırlama, derleme, test ve değerlendirme | Hayır | Evet | Evet |
| Yayına alma, rollback, mevcut canary ve etkin/pasif geçişleri | Hayır | Hayır | Evet |
| Üretim çalışmalarının izinli görünümünü izleme/iptal etme | Hayır | Hayır | Evet |
| Senaryo çalışmasını durdurma/sürdürme | Hayır | Hayır | Evet |
| Özel senaryonun temel rol atamalarını yönetme | Hayır | Hayır | Evet |
| Kaynak doküman veya ham chunk okuma | Ayrıca doküman izni gerekir | Ayrıca doküman izni gerekir | Ayrıca doküman izni gerekir |
| Araç işlemini onaylama | Ayrıca Onaylayan gerekir | Ayrıca Onaylayan gerekir | Ayrıca Onaylayan gerekir |

Test sonuçlarını mevcut senaryo test yetkisiyle göster. Düzenleyene test izni
vermek için genel `runtime.view`/`runtime.cancel` verme. Bu görev kapsamında
"kendi çalışması" adında doğrulanmamış insan sahipliği veya yeni OBO sistemi
icat etme; paylaşılan evaluation consumer'ı insan kullanıcıyla eşitleme.

Senaryo yöneticisinin erişim yönetimi sadece o senaryoyu kapsar; proje rolü
atayamaz. Özel senaryonun son yöneticisinin kaldırılması/süresinin dolması için
mevcut yönetici koruma yaklaşımına uygun güvenli kural uygula. İçerik, denetim
kaydı ve çıktı redaksiyonu görüntüleme rolü nedeniyle genişlemesin.

### İsteğe bağlı görev ayrılığı

Normal kullanımda yayın ve runtime yetkileri Senaryo Yöneticisi içinde birleşir.
Mevcut bağımsız Yayın Yöneticisi ve Runtime Operatörü atamalarını koru; gelişmiş
atama bölümünden kullanılabilsinler. Bunlar temel rollerden ayrı uzman atamalarıdır.

Onay gerektiren araç kullanılan senaryoda Onaylayan seçimi ve eksik onaylayan
uyarısı göster. Onaylayan otomatik yönetici/editör olmasın. Yönetici veya token
sahibi olmak onayı karşılamasın. Doğrulanmış insan başlatan varsa mevcut self-approval
reddi korunsun; başlatan bilinmiyorsa görev ayrılığı sağlanmış gibi gösterme.

## 3. Devralma — belirsiz karar bırakma

Yeni senaryoların varsayılan erişimi **Projeden devral** olsun. Ekranda iki normal
mod sun: **Projeden devral** ve **Bu senaryoya özel erişim**.

1. Devralma modunda aynı projedeki aktif temel proje rolü senaryonun karşılık
   gelen temel rolünü verir. Başka projeye taşmaz.
2. Özel erişimde temel senaryo rolü yalnız doğrudan senaryo atamasından gelir.
   Proje görüntüleyeni/düzenleyeni otomatik senaryo erişimi alamaz.
3. Devralma modunda normal doğrudan temel rol atama formu açma; özel atama
   gerekiyorsa kullanıcıyı özel erişim akışına yönlendir. Uzman görevler bağımsızdır.
4. Proje yöneticisi özel senaryonun erişim idaresini yapabilir; bu idari yetki
   tek başına özel senaryo içeriğini açmaz. Gerekirse kendisini açıkça atayabilir.
   Bunu UI'da dürüstçe belirt: özel erişim proje yöneticisinden mutlak gizlilik
   vaadi değildir. Organizasyon yöneticisinin mevcut idari erişimi de korunur.
5. Tek senaryoya atanan kullanıcıya üst projenin yalnız gezinme için gereken
   minimum görünümünü ver; kardeş senaryoların listesini/içeriğini açma.
6. Mod değiştirme erişim değişikliğidir. Kazanan/kaybeden erişimleri göster;
   özel moda geçerken korunacak kişileri/rolleri açıkça seçtir. Gizli otomatik
   rol kopyalama yapma. Atamalar, mod ve audit tek atomik işlemde kaydedilsin.
7. Devralma + atama süresi + iptal + organizasyon durumu kararı hem liste hem
   detay hem yazma işlemlerinde aynı sonuç versin. Bilinmeyen mod/rol reddedilsin.

## 4. Mevcut veriyi güvenli geçir

Eski rolleri yeni geniş rollerle doğrudan değiştirerek veri migration'ı yazma.
Eski proje administrator veya yalnız release-manager atamasını otomatik yeni
Yönetici yapmak yetki genişletir.

- Yeni rol değerleri ve gerekiyorsa erişim modu alanları eklemeli olsun.
- Mevcut kayıtlar başlangıçta **mevcut erişimi koru** uyumluluk davranışını
  kullansın. Eski capability ve görünürlük sonuçları değişmesin. Bu iç geçiş
  durumu normal yeni senaryo oluşturma seçeneği olmasın.
- Basit dönüşümü güvenli olan roller için dahi önce/sonra işlem ve nesne erişimi
  eşitliğini doğrula. Metadata-only okuyucuyu kaynak içerik okuyucusuna yükseltme.
- Geçiş için salt okunur önizleme ve idempotent uygulama yolu sağla. Önizleme;
  hedef kapsam, eski/yeni rol veya mod, kazanılan/kaybedilen işlemler, atama
  süresi ve dayanak atamaları içersin. Gizli içerik veya token içermesin.
- Genişleten dönüşümü ancak yetkili erişim yöneticisinin o dönüşümü açıkça
  uygulamasıyla yap. Bu üründeki erişim değişikliği akışıdır; ajanın her kod
  düzenlemesinde kullanıcıdan yeniden izin istemesi anlamına gelmez.
- Aktif eski uzman roller ve deprecated capability değerleri sıradan bir
  form kaydında silinmesin. Yeni form, değiştirmediği mevcut erişimi korusun.
- Constraint, foreign key, RLS, revocation, expiry ve audit provenance korunmalı.
- Geçiş ilerlemesini raporla. Uyumluluk kodunu kaldırmak, eski rollerin bütün
  kayıtları güvenle dönüştürülmeden bu görevin tamamlanma şartı değildir.

## 5. API/MCP istemcisi deneyimi

Normal ekranda istemci adı, mevcut REST/MCP protokolü, erişim anahtarı işlemleri,
izinli senaryolar ve mevcut kota ayarları olsun. Teknik capability listesi ve
checkbox'ları dolduran ama tekrar exact seçim isteyen preset formu kalksın.
Yeni binding oluşturmayı sunucuda anlamlı pakete dönüştür:

| Ürün seçimi | Sunucuda kaydedilen anlam |
| --- | --- |
| Senaryoyu çalıştır | `workflow_run` |
| Okuma araçlarını kullan — gelişmiş | Ayrıca `tool_call` |
| Veri değiştiren araçları kullan — gelişmiş, varsayılan kapalı | Ayrıca `tool_call_side_effect` |

Araçsız RAG senaryosu için yalnız çalıştır seçimi yeterli olsun. Araç gerektiren
senaryoda gerekli ek erişimi anlaşılır dille göster; izni gizlice ekleme.
İstemci yeni release nedeniyle kendiliğinden side-effect/tool yetkisi kazanmasın.
Sunucu yalnız yetkili aktörün seçtiği paketleri izinlere çevirsin; gönderilen
arbitrary `capabilities`, rol veya tenant alanları authority sayılmasın.

Yeni genel istemci formunda `tool_approve`, `memory_read`, `memory_write`,
`ingestion_trigger`, `release_promote` sunma. Bunların gerçekten hâlâ etkin
işlem yolu olmadığını kodlamadan önce tekrar doğrula. Mevcut değerleri ve dış
API/GitOps uyumluluğunu koru; sözlükten veya veritabanından topluca silme.
Yeni özellik veya sahte endpoint ekleyerek bu izinleri "çalışır" hale getirme.

`retrieve_debug` ve `ingestion_read` mevcut entegrasyonlar için korunabilir;
normal senaryo istemcisinden ayrı gelişmiş/iç operasyon bölümünde yönetilsin.
Bearer doğrulama, protokol ayrımı, token iptali/döndürme, aktif binding,
tenant zinciri, consumer-owned run erişimi, rate limit ve child capability
kesişimi aynen sunucuda denetlensin.

## 6. Doküman erişimini sadeleştir; içerik sınırını koru

Doküman seti Okuyucusu kaynak içeriği okuyabilir. Yöneticisi ayrıca dokümanları,
hazırlamayı ve senaryoya kullanım iznini yönetebilir. Senaryo yöneticiliği bu
rollerden hiçbirini kendiliğinden sağlamaz. Metadata-only eski atamalar korunur;
yeni normal rol seçicisine üçüncü temel veri rolü ekleme. Metadata görünürlüğünü
üyelik üzerinden organizasyonun tamamına yayma.

Senaryonun canlı veri izni ve insanın kaynak içerik izni her zaman ayrı kalır.
Consumer/set tekrarını azaltmak için açık iki veri erişim modu uygula:

- **İstemciye özel veri:** Mevcut senaryo grant'i ve consumer grant'i kesişimi.
  Bütün eski senaryolar bu davranışla başlar.
- **Senaryonun ortak verisi:** Senaryoyu çağırmaya yetkili istemciler, veri
  yöneticisinin bu ortak kullanım için izin verdiği setleri kullanır. Bu modda
  aynı set için her consumer'a tekrar grant oluşturmak gerekmez.

Ortak mod varsayılan olarak eski grant'lerin yerine geçmesin. Veri yöneticisinin
verdiği iznin **mevcut ve gelecekteki izinli senaryo istemcilerini** kapsadığı
ekranda açık olsun ve kayıt/audit ile kanıtlansın. Senaryo yöneticisi tek başına
bu paylaşımı açamasın. Birden fazla set varsa her set için yetki aranmalı;
onaylanmayan set sessizce açılmamalı, hazır olma ekranında eksik olarak gösterilmeli.
Yeni set bağlamak bu ortak kullanım iznini atlamamalı.

Her modda tenant, exact senaryo, pinned sürüm, canlı set grant'i, aktif indeks,
tombstone ve çıktı redaksiyonu kontrolleri kalsın. Eksik/bilinmeyen mod veya grant
"ortak erişim" anlamına gelmesin. İzin iptali yeni retrieval'da etkili olmalı.
Ortak token arkasındaki gerçek son kullanıcıya göre ACL/OBO bu görevin dışındadır.

## 7. Sunucuyu tek karar kaynağı yap

Mevcut `authorize` ve typed assignment mimarisini geliştir. Yeni paralel politika
motoru kurma. Tek karar hem eylem yetkisini hem nedenini hem kapsam/dayanak
atamasını açıklayabilsin. Liste filtreleri, servisler ve eylem çıktısı birbirine
denk olmalı; her satır için sınırsız tekrar sorgu yapan bir çözümden kaçın.

Nesneye ait `allowed_actions` üret; Django ve React aynı eylem anlamlarını kullansın.
Örnek aşağıdaki bir UI temsilidir, dış REST sözleşmesini değiştirme emri değildir:

```json
{
  "allowed_actions": ["scenario.view", "scenario.edit", "scenario.test"],
  "access_origin": "project"
}
```

- İstemciden gelen `allowed_actions` yok sayılsın veya mevcut şema politikasıyla
  reddedilsin. Boş/yüklenemeyen eylem çıktısı yazma yetkisi sağlamasın.
- `org.can_write` gibi eski geniş kapsam fallback'lerini çağrı yerleriyle kaldır.
- `can_compile_release` belirsizliğini gider: aday hazırlama/derleme editöre açık,
  canlı yayına alma yöneticiye/uyumlu uzman yayıncıya açık farklı eylemlerdir.
- Workflow, prompt, retrieval ayarı, test soruları ve düğüm panelleri için ayrı
  rol oluşturma. Aynı senaryo edit kararını ortak UI yardımcılarıyla kullan.
- Yetki ile işin hazır olmasını ayır: "yetkin yok", "indeks hazır değil" ve
  "test başarısız" aynı boolean veya genel hata mesajı olmasın.
- Açık sayfada yetki iptal edilirse sunucu sonraki isteği reddetsin; UI kaydı
  başarılı göstermesin, eylemleri yenileyip anlaşılır mesaj versin.
- Menü gizleme güvenlik sınırı değildir. Doğrudan URL, form POST, API ve worker
  yolları kendi güvenilir hedefleri üzerinden tekrar denetlensin.

## 8. MCP ingestion durum kapsamını düzelt

Mevcut `apps/mcp/service.py::_ingestion_status`, herhangi bir aktif binding'de
`ingestion_read` bulunmasını organizasyonun kaynak durumunu okumaya yeterli
sayıyor. Önce bu davranışı negatif testle göster, sonra sınırlandır.

İzinli kaynak kümesi; istemcinin aynı tenant'ta aktif ve `ingestion_read` içeren
senaryo binding'lerinden, o senaryolara gerçekten bağlı ve canlı veri izni olan
doküman setlerinden türesin. İstemciye özel veri modunda consumer/set grant'i,
ortak modda doğrulanmış ortak kullanım izni de aranmalı. `Source.document_set`
bu kümeyle eşleşmeli. Kaynağın doğrulanabilir set ilişkisi yoksa reddet; yorumda
proje denetimi yazıp yalnız organizasyonu filtrelemekle yetinme.

İzinli küme filtrelemesi `run_id` aramasından veya en son çalışma seçiminden
önce uygulansın. Böylece yetkisiz kaydın varlığı ve metadata'sı sızmasın. Mevcut
yanıt biçimini koru; bulunamayan/yetkisiz hedef için güvenli mevcut 404 davranışını
kullan. Başka proje veya aynı organizasyondaki ilgisiz kaynak için test zorunlu.

## 9. Kodda başlangıç noktaları

Dosyalar taşınmış olabilir; önce canlı repository durumunda doğrula.

| Alan | Başlangıç dosyaları |
| --- | --- |
| Roller ve merkezi karar | `apps/identity/models.py`, `authorization.py`, `assignment_services.py` |
| Üyelik, kapsam ve devralma | `apps/tenancy/services.py`, `apps/console/scoping.py` |
| İstemci izinleri | `apps/identity/capabilities.py`, `services.py`, `apps/console/forms.py` |
| Console ve gezinme | `apps/console/views.py`, `context.py`, `navigation.py`, ilgili templates |
| Studio | `apps/builder/api.py`, `frontend/src/App.tsx`, `useBuilder.ts`, `types.ts`, `ScenarioManifestPanel.tsx` |
| Veri erişimi | `apps/documents/access_services.py`, `content_access.py`, `models.py`, `apps/retrieval/providers.py` |
| Makine çağrıları | `apps/gateway/views.py`, `apps/mcp/service.py`, `apps/workflows/run_children.py` |
| Araç onayı | `apps/tools/approvals.py`, `proxy.py` |

ADR-0015'i geçmişini silerek yeniden yazma. Hedef model için yeni ADR yaz ve
eski kararın hangi bölümlerini değiştirdiğini açıkla. `roles.py` gibi eski kaynakları
yalnız gerçek referans/uyumluluk incelemesinden sonra temizle. Embedding/OCR ve
Confluence/REST profil grant'leri, sırlar, ağ politikası, release kalite kapıları
ve runtime limitlerini bu rol sadeleştirmesine dahil etme.

## 10. Uygulama sırası

1. Çalışma ağacını ve mevcut davranışı doğrula; plan/risk modelini güncelle.
2. Hedef rol matrisi, delegasyon, modlar ve eski erişim eşitliği testlerini yaz.
3. Merkezi karar ve eklemeli veri modelini uygula; scope filtrelerini eşitle.
4. Atama, devralma ve erişim geçiş önizlemesini transaction/audit ile tamamla.
5. Console/React eylem çıktısı ve sade rol/istemci ekranlarını bağla.
6. Veri erişim modlarını ve MCP durum kapsamını tamamla; REST/MCP ve child
   yürütmede aynı yeni kuralları doğrula.
7. Uygun testler, statik kontroller, PostgreSQL izolasyonu ve browser gate'i çalıştır.
8. Son diff'i mimari, uygulama güvenliği ve operasyon açısından incele; ADR,
   kullanıcı/security belgeleri, task verification ve master planı güncelle.

Her aşamada çalışır ve test edilmiş bir bütün bırak. Yalnız ilk UI aşamasını
tamamlayıp bütün görevi tamamlandı işaretleme. İlgisiz mevcut hataları bu kapsamda
yeniden tasarlama; engel oluşturuyorlarsa kanıtlarıyla ayrı kaydet.

## 11. Zorunlu kabul testleri

| Senaryo | Beklenen sonuç |
| --- | --- |
| Yalnız organizasyon üyesi | Proje/senaryo/içerik yetkisi yok |
| Proje A düzenleyeni, standart A senaryosu | Düzenleme ve test var; yayın yok |
| Aynı kullanıcı, Proje B | Liste, detay ve POST/API erişimi yok |
| Tek özel senaryoya doğrudan atama | Kardeş senaryolar açılmaz |
| Yeni proje yöneticisi, devralan senaryo | Düzenleme, yayın ve operasyon var |
| Proje yöneticisi, özel senaryo | İçerik otomatik açılmaz; erişim idaresi açık/audited |
| Senaryo yöneticisi | Doküman kaynağı ve araç onayı kendiliğinden açılmaz |
| İptal edilmiş üyelik/atama veya dolmuş süre | Sonraki ilgili istek reddedilir |
| Uyumluluk modundaki eski roller | Geçiş öncesi nesne/işlem görünürlüğü ve yetkiler aynı |
| Yalnız eski release/runtime rolü | Kendiliğinden yeni Yönetici yetkisi kazanmaz |
| Metadata-only eski veri rolü | Ham içerik okuyamaz |
| Aday derleyen editör | Aday başarılı hazırlanır; canlıya alma doğrudan API'de reddedilir |
| Tarayıcıda sahte rol/tenant/allowed_actions | Sunucuda yükselme yok |
| Son yönetici kaldırma / eşzamanlı atama | Güvenli ret veya doğrulanmış atomik devir |
| Audit yazma hatası | İlgili erişim değişikliği mevcut fail-closed kuralıyla geri alınır |
| Normal yeni API binding'i | Çalıştırır; side-effect araç izni yok |
| Yeni release ek araç gerektiriyor | İstemci izinleri otomatik genişlemez |
| Consumer B, A'nın run'ı | Status/output/cancel erişimi yok |
| İstemciye özel veri modu | Senaryo ve consumer grant kesişimi gerekir |
| Ortak veri modu | Veri sahibinin ortak kullanım izni gerekir; ayrı consumer/set kaydı gerekmez |
| Canlı set izni iptali | Her iki modda yeni retrieval erişimi kalkar |
| MCP ingestion_read + ilgisiz kaynak | Kaynak varlığı/status/ID sızmaz |
| Alt workflow başka senaryoyu çağırıyor | Çocuk binding'i ve üst/alt yetki kesişimi gerekir |
| Yetki sayfa açıkken kaldırılıyor | Kaydetme reddedilir, UI yanlış başarı göstermez |

Eski davranış testlerini silerek/gevşeterek geçirme. Bu belgede açıkça değişen
davranışın eski testini yeni politika testiyle değiştir; eski kayıtların uyumluluk
testini ayrıca tut. PostgreSQL-only RLS/constraint güvencesini SQLite ile doğrulanmış
sayma. Testler gerçek güven sınırlarında yalnız mock'a dayanmasın.

Repository'nin güncel CI ve doğrulanmış komutlarını esas al. Backend ilgili
identity/tenancy/console/builder/documents/retrieval/gateway/MCP/tools/workflows
testleri, frontend test/typecheck/build, formatter/linter/type checker,
migration drift, secret/security kontrolleri ve uygulanabilir PostgreSQL testleri
çalıştırılmalı. Kontrolleri susturma veya yeni bağımlılık ekleme.

Browser gate'te en az bir sıradan editör, yeni proje yöneticisi, özel senaryo
kullanıcısı ve veri okuyucusuyla gerçek gezinme/POST akışını dene. Gereken runtime
erişimi yoksa eksik kanıtı açıkça raporla; Verified işaretleme.

## 12. Tamamlanma, rollout ve teslim

Tamamlandı demek için rol matrisinin hem UI hem doğrudan servis/API testlerinde
sağlanması, mevcut kayıtların başlangıçta yetki genişletmemesi, ortak veri modunun
açık izinle çalışması ve dokümantasyonun gerçek davranışı anlatması gerekir.
Geçiş önizlemesi idempotent olmalı; tekrar uygulama çift atama/grant üretmemeli.

Canlı rollout yapma. Hazırla: eklemeli migration sırası, eski/yeni worker ve web
uyumu, cache invalidation, in-flight run davranışı, ölçülebilir geçiş kontrolü,
başarısızlıkta güvenli durdurma/ileri düzeltme ve geri dönüş planı. Yeni yetki
değerlerini anlamayan eski binary'ye kör rollback önerme. Yalnız eski kodla
gerçekten uyumlu veri/politika durumuna dönülmüşse rollback desteklendiğini söyle.

Teslim raporunda şunların tamamını ver: Summary; Files changed; Architecture
impact; Security impact; Authorization impact; Data and privacy impact; Logging,
metrics, tracing and audit impact; Database and migration impact; Tests and
verification results; Unverified assumptions; Remaining risks; Manual review
required. Çalıştırılmayan kontrolleri ve eksik browser/PostgreSQL kanıtını açık yaz.

Başlangıç referansı:
[9 Eylül değerlendirmesi](../../authorization-simplification-assessment-2026-09-09/assessment.md).
Oradaki 43 backend / 15 frontend geçişi eski davranışın kanıtıdır; yeni uygulamanın
başarısı olarak tekrar kullanma. Bu görevin kendi doğrulama kanıtını üret.
