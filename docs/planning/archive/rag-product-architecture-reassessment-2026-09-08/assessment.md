# RAG ürün amacından hareketle mimarinin yeniden değerlendirilmesi

Tarih: 2026-09-08. Durum: tasarım önerisi; uygulanmış veya kabul edilmiş mimari kararı değildir. [Plan](plan.md), [35 modellik hedef ve mevcut 80 modelin eşlemesi](target-model.md), [kanıt ve sınırlamalar](verification.md), [risk sınırları](threat-model.md).

## 1. Karar önerisi

**Bu ürün için her küçük konfigürasyon parçasını bağımsız ve katı bir yayın nesnesi olarak sürümlemek gerekli görünmüyor. Çözüm düzeyinde tek yayın snapshot’ı, arka planda teknik veri nesilleri ve sağlam kalıcı yürütme yeterli bir temel olabilir.**

Önceki inceleme mevcut davranışı koruyarak tablo azaltmayı ele alıyordu. Kullanıcı bu kez ürün davranışını yeniden tasarlamayı istiyor; uygulama canlıda değil. Dolayısıyla önceki 80→74 hesabı bu yeni çalışmanın hedefi veya sınırı değil. Geriye uyumluluk için henüz kullanıcıya değer üretmeyen bütün mekanizmaları taşımak zorunda değiliz. Yerel veriyi silmek ise ayrıca kararlaştırılacak bir işlem; bu incelemede hiçbir şema veya veri değişmedi.

Kullanıcının kesinleştirdiği ihtiyaçlar:

- RAG çözümlerini hızla oluşturmak, değiştirmek ve işletmek.
- Farklı ekipler için birbirinden kapalı veri alanları.
- REST ve MCP üzerinden veri/servis bağlantıları, araç kullanımı ve çözüm sunumu.
- İlk kapsamda uzun süren ajanlar, insan onayı, paralel akışlar ve telafi.

Bu kapsamın son maddesi belirleyici: bir kullanıcı tablosu ve vektör deposu basit bir demo için yeterli olabilir; onay beklerken yeniden başlayan, dış sistemde işlem yapan, paralel dalları birleştiren ürün için kalıcı yürütme kayıtları gerekir. Buna rağmen bu ihtiyaç, ayrı prompt/model/retrieval artifact yayın zincirini veya beş düzeyde nesne sorumluluğu atamasını zorunlu kılmaz.

**Önerim: mevcut kod tabanında ürün modelini belirgin biçimde yeniden kurmak; denenmiş veri işleme, güvenli bağlantı ve yürütme bileşenlerini kanıtlarına göre yeniden kullanmak.** Sadece tablo birleştirme yetersiz kalır. Her şeyi yeni teknolojiyle sıfırdan yazmanın da şu an üstün olduğuna dair kanıt yok.

## 2. Karmaşıklığın kaynağı

Tablo çokluğu tek başına yetkilendirme veya sürümlemeden kaynaklanmıyor. Önceki envanterde ingestion 25, documents 10, workflows 9, identity 8, evaluations 7, tools 6 tablo. Diğer uygulama alanlarıyla toplam 80. Ürünün bugünkü tasarımı, genel bir yönetilen AI platformunun katalog, derleme, yayın, trafik, ACL ve yürütme katmanlarını birlikte taşıyor.

Sürümleme karmaşıklığının bir kısmı tablo sayısında görünmüyor: **15 artifact türü zaten tek `ArtifactVersion` tablosunda** tutuluyor. Bunları tek JSON tablosunda daha da birleştirmek asıl sorunu çözmez. Sorun, değişiklik yapmak için çözülmesi gereken bağımlılıkların ve farklı yaşam döngülerinin sayısı.

Somut kaynak kanıtları:

| Kullanıcı amacı | Bugünkü iç mekanizma | Ürün açısından değerlendirme |
|---|---|---|
| Bir generate adımının prompt/modelini değiştirmek | `save_generate_node_binding`, workflow’a ek olarak prompt ve model `ArtifactDraft` kayıtlarını yönetiyor; yayında bunlar ayrı artifact pin’lerine dönüşüyor. | Tek çözüme ait ayarlar için bağımsız yayın birimleri gereğinden ayrıntılı. |
| Çözümü kullanılabilir yapmak | `publish_draft` → manifest türetme → `compile_release` → `run_eval` → release promotion → gerektiğinde ayrı scenario activation. | Tek yayın komutu altında sadeleştirilebilir; güvenlik kontrolleri sunucu tarafında sürer. |
| Dokümanları güncellemek | Release, `DocumentSetVersion` kimliklerini sabitliyor; retrieval o sürümlerin aktif indeksini okuyor. Farklı set sürümü aktive edilince eski release referansları için etki kontrolü var. | Güncel bilgi isteyen RAG ile paket sürümü mantığı birbirine bağlanmış. |
| Ekip arkadaşına çalışma izni vermek | Üyelik yalnızca aidiyet; platform/organizasyon/proje/senaryo/doküman-seti sorumlulukları ve 24 insan-operatör capability tanımı var. | Ekip içi ortak sorumluluk için daha basit rol modeli düşünülebilir. |
| Aynı veri kaynağını bağlamak | REST/Confluence/OCR/embedding katalogları, grant’leri ve farklı senkronizasyon modelleri var. | Bağlantı yönetimi ve iş takibi ortaklaştırılabilir; protokole özgü doğrulama korunur. |
| Uzun işte kaldığı yerden devam etmek | Run, wait, branch/join, child, compensation, event, claim ve checkpoint kuralları. | Kullanıcının açık ihtiyacı; kaldırılması ürün işlevini eksiltir. |

Kaynaklar: [`builder/services.py`](../../../../apps/builder/services.py), [`releases/compiler.py`](../../../../apps/releases/compiler.py), [`releases/lifecycle.py`](../../../../apps/releases/lifecycle.py), [`catalog/lifecycle.py`](../../../../apps/catalog/lifecycle.py), [`identity/authorization.py`](../../../../apps/identity/authorization.py), [`ingestion/staged_build.py`](../../../../apps/ingestion/staged_build.py).

Mevcut `publish_and_verify` zaten bazı adımları tek kullanıcı eyleminde topluyor. Buradaki eleştiri her iç adımın ayrı tıklama olduğu iddiası değildir; içeride ayrı değişmez nesneler, pin çözümü ve hata/yaşam döngüsü sınırlarının kalmasıdır. İnceleme tıklama süresi veya üretim gecikmesi ölçümü yapmadı.

“Vibecoding ile yapılmış” olması tek başına yeniden yazım gerekçesi değildir. Kaynakta hem hedefe göre ağır yönetişim tercihleri hem de değerlendirilebilir retry, ACL, safe-egress ve concurrency testleri var. Karar geliştirme yöntemine değil ürün uyumuna ve bileşen kanıtına dayanmalı.

## 3. Sürümleme dört farklı işi birbirine karıştırmamalı

| Tür | Öneri | Kullanıcıya görünümü |
|---|---|---|
| Düzenleme revision’ı | Eşzamanlı düzenleme çakışması için artan sayı/ETag; her kayıtta yayın yaratmaz. | Normal kaydetme; çakışırsa anlaşılır uyarı. |
| Çözüm yayını | Çalışan ayarların tek değişmez snapshot’ı. Prompt, graph, retrieval, model/araç tanımları birlikte. | Taslak → test et → yayınla; tek sürüm geçmişi. |
| İndeks/veri nesli | Arka planda checksum, kaynak revision ve hazır indeks nesli. | Güncelleniyor / güncel / başarısız; standart güncellemede manuel yayın yok. |
| Yürütme sözleşmesi | Engine/compiler/checkpoint sürümü; uyumsuz worker eski işi yorumlayamaz. | Normal kullanıcıdan gizli işletim ayrıntısı. |

**Sürümleme bütünüyle kalkmamalı; kullanıcıya sunulan bağımsız sürüm birimleri azaltılmalı.** Örneğin kullanıcı bir prompt cümlesini değiştirince prompt sürümü, workflow artifact sürümü, compiled-workflow nesnesi ve release paketini ayrı kavramlar olarak takip etmemeli. Yayın sistemin çözdüğü tek işlem olmalı.

Uzun işler açısından örnek: pazartesi başlayan iş salı insan onayı bekliyor. Bu sırada yeni prompt ve farklı telafi kuralı yayınlandı. Salı devam eden iş pazartesinin graph, araç sözleşmesi ve hazırlanmış işlem girdileriyle sürmeli. Yeni yayın yeni işleri etkiler. Aksi halde kullanıcı onayladığından farklı bir işlem yapılabilir. Bu nedenle tek snapshot ve yürütme contract sürümü korunur.

Harici motor kullanmak bu gereksinimi ortadan kaldırmaz. Örneğin Temporal replay sırasında workflow komutlarını geçmişle karşılaştırır ve çalışan workflow kodu değişimleri için versioning stratejisi ister. Bu, bu projeye Temporal ekleme kararı değil; uzun yürütme tutarlılığının ürün bağımsız bir ihtiyaç olduğuna örnektir. [Temporal workflow definition](https://docs.temporal.io/workflow-definition#deterministic-constraints).

## 4. Daha hafif yayın modeli

`Solution` düzenlenebilir taslağı, sabit erişim kimliğini, etkinlik durumunu ve `active_revision_id` işaretçisini taşır. `SolutionRevision` tek yayın kaydıdır. Bunun içindeki kapalı şemalı konfigürasyon:

- Graph ve adımlara ait prompt/retrieval/model seçenekleri.
- Derlenmiş graph veya derlenebilir kaynak ile compiler/engine sözleşme sürümü.
- İzin verilen koleksiyon/araç bağları; ilişkisel bağlar `SolutionCollection` ve `SolutionTool` ile bu revision’a ait olur.
- Kullanılan bağlantı/araçların güvenlik dışı davranış tanımları ve checksum’ları; secret değerleri içermez.
- I/O şemaları ve varsa test politikası.
- Gerekirse alt çözüm revision pin’leri; üst işin ortasında yeni child graph’a atlanmaz.

Yayın komutu taslağın beklenen revision’ını kontrol eder, şemayı/graph’ı doğrular, kaynak ve araç erişimini çözer, immutable snapshot’ı oluşturur ve aktif işaretçiyi atomik değiştirir. Sonuçla audit aynı transaction’da tutulur. Derleme/uzun test işlemleri transaction dışında hazırlanır; sonuç uygulanırken taslak revision’ı tekrar doğrulanır. Aynı yayın isteğinin tekrarı çift sürüm oluşturmaz.

Taslak önizlemesi de tek seferlik tutarlı snapshot üzerinden çalışır; her node güncel taslak metnini tekrar okumaz. Başarısız yayın aktif çözümü değiştirmez. İlk başarılı yayın çözümü erişime açabilir; erişimi kapatmak ayrı acil durdurma eylemi olarak kalır. “Release aktif ama scenario kapalı” gibi iki ayrı yayın statüsünün normal akışta yönetilmesi gerekmez.

Paylaşılan prompt örnekleri varsayılan olarak **şablondan kopyalama** olabilir. Şablon değişince tüm çözümler kendiliğinden değişmez; kullanıcı “güncellemeyi al” diyerek yeni çözüm sürümü çıkarır. Bağımsız reusable artifact kütüphanesi, gerçekten merkezi ve kontrollü dağıtım ihtiyacı oluşursa eklenir.

**Snapshot güvenlik izni değildir.** Bir bağlantı kapatılırsa, anahtar iptal edilirse, ekip üyeliği kalkarsa veya araç kullanımına yasak gelirse eski snapshot bunu aşamaz. Endpoint/metot/araç şeması gibi güvenlik etkili değişiklikler yeni onay/yayın gerektirir; credential aynı secret referansı altında döndürülebilir. Bekleyen işler daha geniş yeni yetkiyi otomatik kazanmaz. Runtime, snapshot’ın izin sınırı ile güncel izinlerin kesişimini kullanır.

## 5. RAG bakımını hızlandıran asıl değişiklik: veri tazeliğini çözüm yayınından ayırmak

Önerilen varsayılan: çözüm bir koleksiyona bağlanır ve o koleksiyonun **son başarıyla hazırlanmış verisini** kullanır. Veri kaynağındaki rutin değişiklik yeni çözüm yayını istemez.

Bugünkü compiler `document_set_versions` pin’liyor; `pinned_document_set_version_ids` en yeni published set sürümünü seçiyor. Retrieval ise bu pin içindeki aktif indeksleri arıyor. Aynı set sürümünün indeksini yenilemek ile koleksiyonun yeni doküman-seti sürümüne geçmek farklı sonuçlar üretiyor. `ACTIVE_RELEASES_AFFECTED` kontrolü bu bağın somut kanıtı. Bu çalışmada hatalı davranışa dair yeni bug iddiası değil, ürün amacına göre değiştirilmesi önerilen sözleşme olarak ele alındı.

Yeni veri akışı:

1. REST/MCP/dosya kaynağı taranır; kararlı external ID, revision/ETag ve içerik checksum’ı karşılaştırılır.
2. Değişen içerik için teknik `DocumentRevision` oluşturulur; aynı veri yeniden embed edilmez.
3. `IndexGeneration` için hangi doküman revision’larının kullanılacağını `IndexGenerationDocument` sabitler. Bu küçük ilişkisel manifest, vektörleri her güncellemede kopyalamadan yeniden kullanmaya olanak verir; gerçekten gereken bir tablodur.
4. Parse, chunk, OCR ve embedding tamamlanır; boyut, eksik belge ve sınır kontrolleri yapılır.
5. Hazır generation’ın koleksiyon işaretçisi atomik değiştirilir. Başarısız hazırlıkta eski hazır veri hizmet vermeye devam eder.
6. Sonraki retrieval yeni generation’ı görür; normal senkronizasyon için manuel set yayınlama/promote işlemi yoktur. Belirli koleksiyonlarda isteğe bağlı veri onayı uygulanabilir.

İlk uygulama daha basit per-generation fiziksel store ile de kurulabilir; `IndexGenerationDocument` düzeyinde vektör tekrar kullanımı sorgu planı/recall ölçümüne bağlıdır. Ortak Chunk deposunda generation üyeliği filtresi yaklaşık arama sonucunu etkileyebilir. Büyük veri için yeniden kullanım, bakım hızı ve query-plan testi gerektirir; sadece tablo azaltma için zorlanmamalı.

Uzun işte iki veri politikası açık olmalı: varsayılan olarak **her yeni retrieval adımı güncel hazır generation’ı seçer**; o adımın yeniden tesliminde aynı kayıtlı seçim/sonuç kullanılır. Bağımsız yeni adım daha taze veri görebilir. Tutarlı dosya/olay incelemesi gereken akış, başlangıçta sabit generation seçebilir. Kullanılan generation ve belge revision kimlikleri sonuç kanıtına yazılır; retention bunları hesaba katar.

Silme veya erişim iptali, eski snapshot saklama tercihini geçersiz kılabilir. Tombstone canlı retrieval filtresinde hemen uygulanmalı; eski generation’a geri dönmek silinmiş/yetkisi alınmış içeriği görünür yapmamalı. Kaynak taraması yarım kaldıysa görülmeyen bütün belgeler “silindi” sayılmaz. Toplu kayıp/boş snapshot için kaynak politikasına göre inceleme gerekir. Bunlar katı manuel sürüm sistemi olmadan da uygulanabilir.

## 6. Değişikliğe göre hangi işlem gerekir?

| Değişiklik | Kullanıcı işlemi | Arka plan etkisi |
|---|---|---|
| Prompt metni, temperature, top-k, retrieval modu | Kaydet/test/yayınla | Tek çözüm revision’ı; parse/re-embed yok. Hybrid için gerekli fiziksel indeks mevcut değilse ayrıca teknik hazırlık gerekir. |
| Modelin cevap üretme ayarı/modeli | Tek çözüm yayını | Yeni işler yeni model spec ile; çalışan işler eski spec ile. Provider erişilebilirliği ayrıca kontrol edilir. |
| REST/MCP kaynak içeriği | Otomatik veya “şimdi eşitle” | Değişen belgelerin işlenmesi, hazır veri generation geçişi; çözüm yayını yok. |
| Chunking, parser, OCR veya embedding modeli | Koleksiyon ayarını kaydet | Yeni teknik index generation; embedding uyumluluğuna göre yeniden işleme. Hazır olana kadar eski indeks çalışır. |
| API/sağlayıcı secret rotasyonu | Bağlantıda credential döndür | Secret snapshot’a kopyalanmaz; çözüm sürümü zorunlu değil. Eski yetki geri getirilmez. |
| Tool endpoint/metot/input şeması değişikliği | Bağlantı/araç doğrulaması ve etkilenen çözümlere güncelleme | Yeni snapshot; bekleyen onay eski işlem hash’ine bağlı kalır veya açıkça iptal edilir. |
| Ekip üyeliği/anahtar iptali | Üyelik/anahtarı iptal et | Sonraki yetki sınırında geçerli; release beklenmez. Cache ve worker kapsamı dahil. |
| Graph, paralellik, telafi adımları | Tek çözüm yayını | Yeni işler yeni graph; mevcut işlerin engine/schema uyumluluğu korunur. |

Snapshot, LLM cevabının bit düzeyinde yeniden üretileceğini garanti etmez. Harici model davranışı, dinamik REST/MCP verisi ve rastlantısallık değişebilir. Doğru iddia: hangi ayar/veri/işlem ile çalışıldığını izlemek ve devam eden işi tutarlı sürdürmek. İşlem sonucu kayıtlıysa yeniden yürütme yerine o sonuç kullanılmalı; dış yan etkiler tekrar edilmemeli.

## 7. Ekip izolasyonu ile ayrıntılı yönetişimi ayırmak

Önerilen temel sınır `Workspace`. Kullanıcının üye olduğu ekipten organizasyon kapsamı sunucu tarafında türetilir. Veri, bağlantılar, araçlar, çözümler, işler ve kayıtlar bu kapsama ait olur. Sorgu, nesne deposu yolu, cache anahtarı, görev mesajı ve vektör retrieval aynı sınırı taşır. PostgreSQL tenant/RLS arka koruması korunabilir; üyelik tablosunun az olması bu denetimi gereksiz kılmaz.

Ekip içinde `owner`, `builder`, `operator`, `viewer/auditor` gibi az sayıda rol ve gerekiyorsa ayrıca sınırlı onay yetkisi yeterli olabilir. Rol sayısı tablo sayısı değildir: enum/allowlist ve bir membership modeliyle uygulanabilir. Kimse yalnızca ekip yöneticisi olduğu için secret metnini görmez; platform işletmecisi de otomatik içerik okuyucusu sayılmamalı. Kurtarma erişimi açık ve denetimli kalmalı.

Proje ayrı yetki sınırı olmadan etiket/klasör olabilir. Aynı çalışma alanında bir koleksiyonu çözüme bağlamak, yetkili builder’ın tek işlemi olabilir; ayrı erişim talebi + senaryo grant’i + binding yönetimi gerekmeyebilir. API müşterileri ise yalnızca açıkça atanan çözümleri çalıştırır. `ClientSolutionGrant` ve yayınlanmış çözüm-koleksiyon/araç bağları erişimi sınırlar; API anahtarı bütün çalışma alanını tarama hakkı vermez.

Bu, mevcut yetki davranışının bilinçli değişimidir. Ekip içindeki herkesin aynı veri sınıfına yetkili olduğu varsayımı açık olmalı. Aynı ekipte bazı belgeler gizliyse ayrı workspace veya ek koleksiyon/doküman ACL gerekir. Kaynak sistemde sadece belirli insanlara açık içerik ortak servis hesabıyla çekilip bütün ekibe açılmamalı: ingest kapsamı gerçekten ortak erişimli veriyle sınırlandırılır ya da kaynak ACL devralma ayrı özellik olarak tasarlanır. Kullanıcı yalnız ekipler arası kapanmayı doğruladı; kişi bazlı kaynak ACL kapsamı hâlâ ürün kararıdır.

## 8. REST ve MCP tablo hiyerarşisi gerektirmez; farklı kullanım yolları gerektirir

| Kullanım | Örnek | Tasarım |
|---|---|---|
| Kaynak ingestion | REST endpoint’inden kayıt veya MCP resource içeriği alıp indeksleme | `Source → adapter → DocumentRevision → index job` |
| Çalışma anında canlı veri | Stok, sipariş durumu, güncel müşteri kaydı | REST/MCP Tool; sonucu otomatik kalıcı bilgi tabanına koyma |
| Yan etkili işlem | Kayıt açma/güncelleme/silme | ToolInvocation, gerektiğinde ApprovalRequest, idempotency ve belirsiz sonuç yönetimi |
| Ürünü dışarı sunma | Çözümü REST endpoint’i veya MCP tool olarak çağırma | Aynı Solution/Run admission servisine iki protokol adaptörü |

`Connection` ortak bağlantı kaydı olabilir; provider/connector türüne göre kapalı şemalar ve güvenli transport kullanılır. Tek tablo, tek gevşek URL/credential politikası anlamına gelmez. Kaynak cursor/checkpoint ve takvim alanları `Source` üzerinde, doküman dış kimliği/revision bilgisi `Document` üzerinde tutulabilir; REST/Confluence/MCP için ayrı run ve cursor tabloları zorunlu değil.

Mevcut kodda MCP çözüm çağırma sunucusu (`apps/mcp`), outbound tool çağrısı (`tools/mcp_adapter.py`) ve tool discovery (`tools/catalog_sync.py`) var. **Buna karşılık `ConnectorType` içinde MCP ingestion türü yok; `resources/list/read` kaynak ingestion akışı bulunmadı.** “MCP desteği var” bütün bu kullanımların hazır olduğu anlamına gelmiyor. Yeni tasarımda bu ihtiyaç açık bir adapter kabul ölçütü olmalı.

MCP resources veri sunumu, tools ise işlem çağrısı sağlar; pagination/kimlik/şema sözleşmesi kaynağa göre ele alınmalı. Her MCP tool’un çıktısı indekslenebilir doküman listesi değildir. Harici sunucunun schema/description metni otomatik güvenilir kod veya izin sayılamaz. Protokol sürümü de açıkça seçilmeli: mevcut adapter 2025-06-18’e bağlı; 2026-07-28 specification bulunuyor, buradan otomatik uyumluluk sonucu çıkarılamaz. [MCP Resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources), [MCP Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

MCP OAuth veya kullanıcı adına downstream erişim gerekiyorsa token yaşam döngüsü ayrıca ele alınmalı; bir sistem için verilmiş token’ı başka hedefe aktarmak çözüm değildir. Yeni protokol bağlantısı mevcut public/private ağ izinlerini genişletmek için gerekçe olamaz. Mevcut sürümün [MCP authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) kuralları hedef/audience bağını ve token passthrough yasağını açıklıyor.

## 9. Uzun ajan, insan onayı, paralellik ve telafi nasıl korunur?

Mevcut çalışma çekirdeği bu ihtiyaçlara özgü bir yatırım. Kalıcı `Run`, checkpoint, atomik transition, claim lease/fencing, tek kullanımlık wait correlation, branch/join, child link ve compensation intent kayıtları korunmalı veya eşdeğer bir motor tarafından sağlanmalı. `ToolInvocation` da salt log değildir: yinelenen teslimde aynı dış işlemin tekrar yapılmasını önlemek için durum tutar.

Araç onayı için önerilen sadeleşme, yayın onaylarının varsayılan olmaması; riskli dış işlemin somut girdilerine bağlı insan onayının sürmesidir. Onaylayan gerçek kişi, başlatan kişi, araç kimliği, girdi checksum’ı, karar/expiry ve tek kullanımlık devam kuralı gerekir. `ApprovalRequest` bu referans tasarımda korunuyor; bir tablo kazanmak için generic wait payload’ına taşımak önerilmiyor. Mevcut kodda initiator kimliğinin gerçek trafiğe bağlanmasına dair sınırlama yorumu var; yeniden kullanımda self-approval testinin bulunması tek başına uçtan uca uygulandığını kanıtlamaz.

Telafi “veritabanını geri almak” değildir. Önceden gerçekleşen dış işleme karşı ayrı bir eylemdir; o da hata verebilir. Gerçek işlemden dönen dış kimlik, telafi girdileri, işlem sırası ve sonuç tutulmalı. Timeout sonrası karşı tarafın işlemi yapıp yapmadığı bilinmiyorsa otomatik tekrar veya kör telafi yapılmamalı; reconcile/operatör kararı gerekir. Yeni çözüm yayını eski işin telafi tanımını değiştirmez; güncel güvenlik iptalleri yine uygulanır.

Worker yazılımı güncellenirken yalnız config snapshot yeterli değildir. Checkpoint’i hangi engine contract’ın okuyabildiği doğrulanmalı; eski işler için uyumlu worker sürümü tutulmalı veya açık drain/migration yolu kullanılmalı. Runtime yükü Redis/Celery görev zincirlerine dağıtılıp bütün kalıcı kontrol kaldırılmamalı.

Basit RAG ekranı bu ayrıntıları göstermek zorunda değil: “Dokümanla cevapla” bir hazır akış olabilir; gelişmiş editör aynı yürütme çekirdeğinde tool/approval/parallel adımları açar. Böylece basit kullanım hızlı olurken iki ayrı motorun bakımı oluşmaz.

## 10. Örnek hedef büyüklüğü

[Hedef model belgesindeki](target-model.md) somut tasarım **35 uygulama modeli** içeriyor: ekip 2, çözüm 4, API erişimi 3, bağlantı 1, bilgi tabanı 7, arka plan işi 2, araç/onay 3, kalıcı yürütme 8, değerlendirme 3, audit/tüketim 2.

Bu bir 35 tabloya ulaşma talimatı değildir. Ekipler arası paylaşım, per-document ACL, OAuth token deposu, canary veya ayrı reusable katalog gibi kapsamlar ek tablo gerektirir. Django ve fiziksel vektör partition/store tabloları ayrıca sayılır. Her eski modelin yeni sorumluluğu veya bilinçli kapsam kararı, 80 satırlık eşlemede açık; hiçbir davranış “tabloyu sildik, kod halleder” diye gizlenmiyor.

Snapshot gövdesinde gömülmesi uygun şeyler: tek çözüme ait küçük prompt, top-k/temperature, kapalı graph config ve I/O şeması. JSON içine gömülmemesi gerekenler: sınırsız event geçmişi, çok sayıda doküman üyeliği, araç yan etki sonuçları, büyük içerik/vektörler ve sorgulanabilir yetki ilişkileri. Bu yüzden generation membership, audit ve runtime child tabloları hedefte duruyor.

Vektör deposunda tek tablo şartı koymuyorum. Mevcut PostgreSQL/pgvector korunabilir; model/boyut/embedding space bazlı depolama veya mevcut per-generation DAL karşılaştırılır. Aynı boyuttaki farklı model vektörleri birbirinin yerine kullanılamaz. Karma boyutları tek kolonda tutmak mümkün olsa da yaklaşık arama indeksinin uygun boyut grubuyla sınırlandırılması gerekir. [pgvector 0.8.4](https://github.com/pgvector/pgvector/blob/v0.8.4/README.md#can-i-store-vectors-with-different-dimensions-in-the-same-column). Ortak depoda workspace/generation filtrelerinin recall ve plan etkisi ölçülmeli. Tablo sayısını başka servise taşımak toplam işletim maliyetini azaltmış sayılmaz.

## 11. Kalite kontrolü daha hafif olabilir

Şema, yetki, eksik bağlantı, güvenli tool parametreleri, kaynak erişimi ve bozuk graph kontrolleri her yayında otomatik ve zorunlu kalmalı. LLM kalite benchmark’ı ise varsayılan olarak çözüm editöründe çalıştırılabilen testler ve önceki sürüm karşılaştırması olmalı. Riskli kullanımda politika yayın öncesi kalite kapısını zorunlu kılabilir.

Mevcut deterministik `EvalRun` yayın kapısı ile soru seti/retrieval/LLM judge değerlendirmeleri aynı başarı kavramına sahip değil. Ortak EvalRun/EvalResult modellerine geçilirse `purpose`, değerlendirme türü, immutable case snapshot’ı, çözüm/generation pin’i ve politika sürümü açık tutulmalı. Bir keşif testi veya LLM judge “passed” olduğu için zorunlu güvenlik/publish kontrolleri geçmiş sayılmamalı. Varsayılan kalite kapısının hafifletilmesi mevcut yönetişim sözleşmesini değiştirir; yalnızca öneridir.

## 12. Sadeleştirme mi, yeniden yazım mı?

| Seçenek | Kazanım | Bedel / değerlendirme |
|---|---|---|
| Mevcut davranışı koruyup birkaç tablo birleştirme | Dar değişiklik, az geçiş riski | Bağımsız artifact pin’leri ve veri/yayın bağı sürer; yeni soruyu yeterince çözmez. |
| Aynı stack üzerinde yeni ürün modeli, kanıtlı bileşenleri yeniden kullanma | Tek SolutionRevision, workspace rolleri, otomatik veri güncelleme; testli parçaları koruma | Yetki/publishing/runtime resolver sınırları yeniden yazılır. **Önerilen başlangıç yönü.** |
| Baştan kod ve yeni orkestrasyon motoru | Mevcut mimari borçtan daha geniş kopuş | Connector, ACL, onay, recovery ve test yatırımı yeniden değerlendirilir; toplam teslim/işletim maliyeti belirsiz. Somut prototype üstünlüğü gösterirse seçilmeli. |

Mevcut motor tek bağımsız paket gibi sökülüp takılacak durumda değil: `workflows/runtime.py`, `run_children.py`, `services.py`, `orchestration/rag_steps.py` ve `tools/proxy.py` release/artifact modellerine doğrudan bağlı. Yeniden kullanım planı bu bağımlılıkların yerine bir çözülmüş yürütme snapshot sözleşmesi koymayı içermeli. Sadece sınıf isimlerini değiştirmek yeterli olmaz.

Güvenli bağlantı taşıyıcısı, parsers, REST/Confluence adapters, pgvector DAL, graph validation/state mapping ve mevcut invariant testleri ilk yeniden kullanım adayları. Her biri kaynak bağları ve test sonucu ile ele alınır; “varsa iyidir” kabulü yok. Ürünü canlıya alma baskısı olmadığı için yeni model ayrı geliştirme alanında kurulabilir; eski uygulamayla iki yönlü dual-write zorunlu değil. Fakat gerekiyorsa yerel doküman/çözüm tanımları dışa aktarılır; korunacak/kaldırılacak veri açık listelenir.

Temporal benzeri harici durable engine, karmaşık runtime bakımının baskın maliyet olduğu görülürse ayrı spike adayıdır. Replay, worker uyumluluğu, insan onayı, unknown outcome, telafi, tenant scope ve işletim maliyeti aynı örneklerde karşılaştırılmalı. Yeni servis/dependency adoption’ı şu an önerilmiş bir karar değildir. [Temporal yürütme yaklaşımı](https://docs.temporal.io/workflow-execution).

## 13. Uygulama kararı öncesi somut doğrulama paketi

Üç dikey örnek aynı hedef modelde gösterilmeli:

1. Ekip A dosya/REST kaynağı bağlar, RAG hazır akışı kurar, prompt değiştirip tek işlemle yayınlar; Ekip B bütün okuma/yazma/preview/retrieval yollarında reddedilir.
2. Kaynakta belge değişir; yalnız gerekli içerik işlenir ve yayınlanmış çözüm yeniden yayınlanmadan yeni bilgiyi kullanır. Başarısız ve yarım senkronizasyonda eski hazır veri korunur; silme/ACL iptali eski generation’dan sızmaz.
3. Agent tool çağırır, insan onayı bekler, uygulama/worker yeniden başlar; iki paralel dal bir kez birleşir; yeni solution revision yayınlansa da eski iş kendi snapshot’ıyla devam eder. Dış işlem timeout’u çoğaltılmaz, gerektiğinde telafi/operatör recovery görünür olur.

Ölçütler tablo sayısı yanında: ilk çalışır RAG’a kadar kullanıcı adımları ve süre; prompt değişikliği için yönetilen yayın nesnesi sayısı; veri güncellemesinde yeniden yayın gerekip gerekmediği; yeni REST/MCP adapter eklerken yeni model sayısı; başarısız işi teşhis ve kurtarma adımları; aynı invariant’ı uygulayan servis sayısı; yeterli gerçek veriyle retrieval doğruluğu/latency ve eşzamanlı güncelleme davranışı. Bu raporda süre veya kapasite vaat edilmiyor; başlangıç ölçümü yapılmalı.

Seçilen prototype hedefleri sağlarsa yeni mimari için ADR ve uygulama planı yazılır; erişim modeli, API, saklama ve geçiş değişiklikleri somut diff üzerinden onaylanır. Değerlendirme tamamlanması, bu dönüşümün uygulanmış veya onaylanmış olduğu anlamına gelmez.

## Rapor kapanışı

- **Summary:** Ayrıntılı artifact sürümlemesi yerine tek çözüm yayını; bağımsız veri tazeliği; ekip izolasyonu ve advanced runtime korunarak daha küçük ürün modeli önerildi.
- **Files changed:** Bu incelemenin plan/risk/değerlendirme/hedef model/doğrulama belgeleri ve arşiv/master-plan bağlantıları.
- **Architecture impact:** Tasarım önerisi; mevcut uygulama değişmedi.
- **Security impact / Authorization impact:** Mevcut kontroller değişmedi. Hedef workspace rolleri mevcut nesne bazlı sorumluluk modelinin yerine geçecek bir ürün kararıdır, henüz uygulanmadı.
- **Data and privacy impact:** Kullanıcı kapsam cevapları ve kaynak kodu incelendi; canlı içerik veya üretim verisi okunmadı.
- **Logging, metrics, tracing and audit impact:** Değişiklik yok; hedefte runtime ve audit ayrımı korunuyor.
- **Database and migration impact:** Değişiklik yok; hedef 35 model DDL/migration değildir.
- **Tests and verification results:** Bu turdaki yapısal ve hedef eşleme kontrolleri ile mevcut runtime/onay testlerinin sonuçları verification kaydındadır; yeni tasarım test edilmiş bir uygulama değildir.
- **Unverified assumptions:** Ekip içi veri paylaşım sınırı, kaynak ACL devralma, MCP auth türleri, bekleyen işlerin azami süresi, veri hacmi/saklama ve korunacak yerel veri henüz kesin değil.
- **Remaining risks:** Yeni model/retrieval/topoloji çalışır prototype ile kanıtlanmadı; eski runtime release modellerine bağlı; üçüncü taraf side-effect işlemlerinde tam olarak bir kez çalışma her zaman sağlanamaz.
- **Manual review required:** Ürün sahibi hedef davranış ve kapsam kararlarını seçmeli; mevcut sistem üzerinde uygulama veya silme başlatılmadı.
