> Superseded: [tek aktif geliştirme görevi](../Agent_Hub_MD/plan.md). Bu belge tarihsel kaynaktır; bağımsız uygulanmaz.

# AgentHub arayüzünü sadeleştirme — Kodlama ajanı talimatı

Tarih: 2026-09-09. Durum: **Uygulama talimatı hazır; kapsamlı arayüz yenilemesi henüz uygulanmadı.**

Bu belgeyi alan kodlama ajanı, aşağıdaki kapsamı güncel repository durumuyla karşılaştırarak
uygulasın. Yalnız öneri veya görsel üretmekle yetinmesin: çalışan ekranlar, doğru geçişler,
testler ve doğrulama kanıtları teslim etsin. Bu dosyanın hazırlanması uygulamanın tamamlandığı
veya canlı veri üzerinde işlem yapılmasının onaylandığı anlamına gelmez.

## 1. Amaç

AgentHub'ın bütün konsol ekranlarını tutarlı, anlaşılır ve görev odaklı hale getir.
Öncelik doküman yükleme/indeks hazırlama ve senaryo yönetimidir. Her ana ekran şu sorulara
ilk bakışta cevap versin: **Neredeyim? Ne durumda? Ben şimdi ne yapabilirim?**

Yalnız renkleri ve boşlukları değiştirme. Aynı sayfaya yığılmış görevleri ayır; uzun teknik
açıklamaları ilgili ayrıntıya taşı; mevcut işlevleri ve güvenlik sınırlarını koru.

## 2. Başlamadan önce ve çalışma sınırları

1. [AGENTS.md](../../../AGENTS.md), [mühendislik kuralları](../../ai/engineering-rules.md),
   [ajan geçiş kaydı](../../ai/agent-handoff.md), bu işin [planı](plan.md) ve
   [tehdit modelini](threat-model.md) oku. Tek ana ajanla çalış; repository işini alt ajanlara devretme.
2. Güncel dalı, commit'i ve çalışma farkını incele. Çok sayıda mevcut yerel değişiklik vardır;
   bunları silme, geri alma veya kendi değişikliğinmiş gibi topluca düzenleme/commit etme.
3. Codebase Memory kullanılabiliyorsa doğru repository kaydını ve indeks sağlığını doğrula;
   Serena varsa sembol/referans teyidi yap. Araç yoksa doğrudan kod, `rg` ve testlerle ilerle.
4. Runtime'a müdahaleden önce [manuel test rehberi bölüm 0](../../manual-testing-guide.md)
   ve [kanonik Compose](../../../deploy/compose/docker-compose.yml) üzerinden canlı durumunu doğrula.
   Önceki test sayıları veya çalışan servis bilgileri bugünkü kanıt değildir.
5. Canlı durum planla çelişirse planı güncelle. Uygulanmış, doğrulanmış ve bekleyen işleri ayrı tut.
6. Üretim bağımlılığı, authentication/authorization, tenant izolasyonu, public API, sır,
   ağ davranışı veya veri silme gerektiren bir değişikliği bu UI talimatından yetki çıkararak yapma.
   Böyle bir ihtiyaç varsa gerekçesi, somut değişikliği ve etkileri hazırlandıktan sonra mevcut
   kullanıcı onayının kapsayıp kapsamadığını kontrol et; kapsam dışı kısım için açık onay gerekir.
   Güvenli ve yetkilendirilmiş arayüz işlerine devam et.

Bu işte başlangıç tercihi mevcut Django şablonları ve React akış düzenleyicisidir. Yeni bir
frontend çatısı, paket veya bütün uygulamanın yeniden yazılması varsayılan çözüm değildir.

## 3. Mevcut çalışmayı koru; aynı işi tekrar yapma

[Gezinme görevi](../console-navigation-2026-09-08/plan.md) ve
[kanıt kaydı](../console-navigation-2026-09-08/verification.md) başlangıç referansıdır.
2026-09-09 incelemesinde aşağıdakiler çalışma ağacında bulunmuş ve gezinme düzeyinde doğrulanmıştır:

- Sol menüde bağımsız **Senaryolar**, mevcut yetkiye uygun Testler ve Onaylar girişleri.
- Senaryo listesinde arama, proje/durum filtreleri ve 25 kayıtlık sayfalama.
- Proje detayından proje filtresi seçilmiş senaryo listesine geçiş.
- Etkin menü işaretleri, ilgili üst sayfaya dönüş ve Studio'dan senaryoya dönüş.
- Senaryo/sözleşme/profil formlarında bağlama uygun iptal bağlantıları.
- Mobil menünün açılması, Escape ile kapanması ve klavye odağının geri dönmesi.

Bu davranışlar genel tasarıma taşınacak; kaldırılmayacak. Önce güncel kodda hâlâ geçerli
olduklarını doğrula. Önceki kanıt: 43 sayfa türünde 53 ziyaret; SQLite konsol testlerinde
348 geçti/1 atlandı; seçili PostgreSQL testlerinde 72 geçti. **Bunlar gelecek değişikliğin
test sonucu değildir. Tam yaşam döngüsü tarayıcı kabulü hâlâ açıktır.**

Senaryo alt işinde mevcut
[senaryo sadeleştirme talimatını](../scenario-detail-ux-simplification/implementation-instructions.md)
ve [planını](../scenario-detail-ux-simplification/plan.md) kullan; ikinci, çelişen bir uygulama kurma.
[RAG mimarisi](../rag-architecture-simplification/plan.md),
[vektör deposu](../shared-vector-storage/plan.md) ve
[yetkilendirme sadeleştirme](../authorization-simplification/plan.md) ayrı işlerdir.
Bu UI çalışması onların model, tablo veya izin değişikliklerini kendiliğinden başlatmaz.
Başka bir iş ilerlemişse arayüzü güncel onaylı sözleşmeye uyarla ve planı buna göre güncelle.

## 4. Görsel yön

Referanslar kurgusal verili tasarım konseptleridir; çalışan ekran veya piksel düzeyinde şartname değildir:

![Doküman çalışma alanı](../../../outputs/ui-redesign-concept-2026-09-08/01-dokuman-calisma-alani.png)

![İndeks hazırlama](../../../outputs/ui-redesign-concept-2026-09-08/02-indeks-hazirlama.png)

[İlk değerlendirme](../../planning/archive/ui-redesign-concept-2026-09-08/assessment.md)
bu görsellerin gerekçelerini açıklar.

- Açık yüzeyler, koyu okunaklı yazı, ölçülü yeşil vurgu, ince ayırıcılar ve düzenli boşluklar kullan.
- Başlık, açıklama, durum, ana işlem ve ikincil işlemler arasında belirgin görsel öncelik oluştur.
- İç içe kartları, gereksiz rozetleri, yinelenen özetleri ve sürekli açık oluşturma formlarını azalt.
- Her görev görünümünde tek belirgin ana işlem olsun; yetki veya önkoşul yoksa nedeni görünsün.
- Durumu yalnız renkle anlatma; metin ve uygun simge de kullan. Hata metni yapılabilecek sonraki işi söylesin.
- Logo, tipografi, aralık, buton, alan, tablo ve durum bileşenleri uygulama genelinde tutarlı olsun.
  İki konseptteki farklı logo çizimlerini aynen uygulama; tek mevcut marka bileşenini koru.
- UUID, checksum, ham manifest, JSON ve geliştirici rehberlerini varsayılan iş akışından çıkar;
  gerektiğinde yetkili kullanıcı için ayrıntı/kopyalama görünümünde tut.
- Örnek sayıları, dosyaları, ayar paketlerini veya işlem yüzdelerini gerçek ekranlara sabitleme.

## 5. Sol menü ve sayfalar arası geçişler

Ana görevler doğrudan bulunabilsin: **Ana Sayfa, Projeler, Senaryolar, Dokümanlar, Testler,
İstemciler, Çalıştırmalar**. Onaylar ve yönetim yüzeylerini mevcut yetkiye göre erişilebilir tut.
Gerekirse günlük işler ile yönetimi görsel gruplara ayır; işlevi görünmez hale getirme.

| Başlangıç | Beklenen geçiş |
| --- | --- |
| Sol menü → Senaryolar | Proje detayına girmeden yetkili senaryo listesi |
| Proje → Senaryolarda ara | O proje filtresi korunmuş senaryo listesi |
| Senaryo listesi → Yeni senaryo | Proje bağlamı biliniyorsa doğrudan form; bilinmiyorsa anlaşılır proje seçimi |
| Senaryo → Studio → Geri | Aynı senaryonun ilgili görünümü |
| Senaryo → Test → Sonuç | Aynı senaryo ve test bağlamı; sonuçtan ilgili teste dönüş |
| Doküman seti → Dosya → Önizleme | Aynı set/dosya/sürüm; güvenli önizlemeden dosyaya dönüş |
| Doküman seti → Kaynaklar → Kaynak ayrıntısı | Aynı set korunur; her seviyede bağlama uygun dönüş |
| Liste → Detay → Liste | Mümkün olduğunda arama, filtre ve sayfa korunur |
| Form → Vazgeç | Kayıt oluşturmadan ilgili üst görünüm; kaydedilmemiş düzenleme varsa anlaşılır davranış |
| Hata/boş görünüm | Yetkili ve uygulanabilir sonraki iş veya güvenli geri dönüş |

Geri dönüş hedeflerini sunucunun ürettiği adlandırılmış rotalarla kur. Serbest `next`/`return_url`
değerlerini güvenilir sayma. Filtreleri kodla ve doğrula; yalnız yetkili sonuç kümesini daraltsın.
Mevcut güvenli URL doğrulamasını yeniden kullan. Doğrudan URL açma, yenileme ve tarayıcı geri/ileri
işlemleri doğru görünümü korusun. Kırık eski bağlantılar bırakma.

Sekme gibi görünen kontroller gerçekten ilgili görünümü değiştirsin. Tercihen mevcut sunucu
şablonlarıyla ayrı görünümler veya erişilebilir sekme/panel yapısı kullan. Tam içeriği alt alta
bırakıp yalnız kaydırmayı kapsamlı sadeleştirme sayma. Normal bölüm bağlantılarında `role=tab`
kullanma; gerçek sekmelerde klavye ve seçim semantiğini doğru uygula. Taşınan eski fragment
bağlantılarına güvenli eşleme/uyumluluk sağla; form hata sonrası doğru bölümü yeniden aç.

## 6. Doküman çalışma alanı — ilk uygulanacak pilot

Doküman setini **Dosyalar / Hazırlama / Sürümler / Erişim** görünümlerine ayır.
Kaynak bağlantılarını Dosyalar altında keşfedilebilir ikincil bir bölüme yerleştir.

### Dosyalar

- Set adı, kullanılan içerik/indeks durumu ve sıradaki işlem en üstte olsun.
- Dosya listesi ana içerik olsun: ad, tür/boyut, anlaşılır işleme durumu, güncelleme ve ilgili eylem.
- Yeni set/yükleme formunu ilgili düğmeyle aç. Dosya seçimi, desteklenen türler, limitler,
  doğrulama ve kısmi başarısızlıklar anlaşılır olsun; mevcut sunucu sınırlarını koru.
- Arama, filtre, sayfalama ve uzun adları ele al. Önizleme, değiştirme ve sürüm bilgisi dosya
  ayrıntısında olsun. İzin verilmeyen belge metnini özet/tooltip/istemci verisiyle dolaylı gösterme.

### Hazırlama

Kullanıcı akışı: **Yükle → Hazırla → Kontrol et → Kullanıma al**.

Bu dört başlık backend işlemlerini birleştirme izni değildir. Taslağı yayımlama,
değişmez set sürümü oluşturma, indeks işi başlatma ve indeks aktivasyonu kendi mevcut
önkoşul, yetki, işlem ve audit sınırlarıyla çalışmaya devam etsin.

- Kullanılan sürüm ile hazırlanmakta olan sürümü yan yana, açık etiketlerle göster.
  Set sürümü ve indeks sürümü farklı kimliklerdir; tek belirsiz `v4` etiketiyle karıştırma.
- Yayımlanmış içeriği taslak gibi göstermeme ve değişmez sürümü yerinde düzenlememe kuralını koru.
- Profilleri anlaşılır bir özet halinde sun; ayrıntıyı Gelişmiş ayarlarda göster. Konseptteki
  “Standart hazırlama” ancak gerçekten var olan, uygun kapsamda izinli/yayımlanmış profillere
  eşlenebiliyorsa kullanılabilir. Eksik profil varsa bunu söyle; sessizce profil oluşturma.
- İş durumlarını sunucudan türet: sırada, çalışıyor, kontrol bekliyor, başarısız, iptal edildi,
  kullanıma hazır. Desteklenmeyen yüzde/süre/maliyet tahmini uydurma.
- Hata nedeni ve mevcut izinlere göre yeniden dene/iptal eylemi görünür olsun. Yenileme veya
  ikinci tıklama ile mükerrer iş oluşmasına karşı mevcut idempotency kontrollerini koru.
- Kontrol görünümünde mevcut yetkili önizleme, iş özeti ve uygun test yüzeylerini kullan.
  **Mevcut “İndeksi dene” aktif indeks üzerinde çalışır:** bunu hazırlanan indeksin testiymiş
  gibi etiketleme. Henüz kullanıma alınmamış indeks için test desteklenmiyorsa açıkça belirt;
  yeni test sözleşmesi gereğini ayrı değerlendir. İndeks araması senaryo yanıt testinin yerine geçmez.
- Hazırlama çalışan indeksi değiştirmesin. Kullanıma almadan önce hedef sürümü ve etkilenen
  senaryoları göster; mevcut etki onayını ve aktivasyon yetkisini aynen koru.

### Sürümler ve erişim

Geçmişi varsayılan ana sayfadan ayır; kullanılan, hazırlanan ve geçmiş sürümleri anlaşılır listele.
Yeni taslak hazırlama, mevcut geri dönüş ve teşhis yolları kaybolmasın. Senaryo bağları, set
sorumlulukları, içerik okuma ve istemci retrieval izinleri ayrı anlamlarını korusun. Karantina
gibi önemli kontroller yetkili yönetim alanında bulunsun; etkin engel ana durumda görünür kalsın.

## 7. Senaryo deneyimi

Bu bölümün ayrıntı otoritesi mevcut
[senaryo talimatıdır](../scenario-detail-ux-simplification/implementation-instructions.md).
Ortak gezinme ve görsel bileşenleri bu işle uyumlu uygula:

- Senaryoları sol menüde bağımsız tut; proje ilişkisini ve proje düzeyi yetkiyi kaldırma.
- İlk kurulum ile günlük kullanımı ayır. Kullanımda olan senaryoya sürekli uzun kurulum
  listesi gösterme. Geçerli aktif sürümü, mutable Studio taslağı yok diye “tamamlanmamış” sayma.
- Genel görünümde çağrılabilirlik, aktif sürüm, bekleyen değişiklik, test/bilgi kaynağı durumu
  ve kullanıcının yapabileceği bir sonraki işlem yer alsın.
- Genel, bilgi kaynakları, test, entegrasyon, sürümler ve erişim işlerini ayrı anlaşılır
  görünümlere taşı. Retrieval gerekmeyen akışa zorunlu doküman adımı dayatma.
- Kullanımdaki sürüm ile aday/taslak testini ayır. Akış düzenleme, değerlendirme ve yayına alma
  yetkilerini bir “akıllı” düğmeyle aşma. Lifecycle kapatma ve operasyonel durdurma farklı kalsın.
- Uzun DSL yardımı Studio yardımında; exact artifact/manifest ayrıntıları sürüm ayrıntısında olsun.

## 8. Diğer bütün sayfalar

[Mevcut sayfa envanterini](../console-navigation-2026-09-08/page-inventory.md) güncelle.
Yalnız bu listedeki sayıyı tamamlamaya çalışma; güncel rotalar, ortak şablonlar ve yeni ekranlar
nihai kapsama dahildir.

| Ekran ailesi | Beklenen düzen |
| --- | --- |
| Ana Sayfa | Dikkat isteyen işler ve sonraki eylemler; ayrıntılı envanter ilgili listelerde |
| Projeler | Senaryoların gruplandığı bağlam; proje/senaryo geçişleri ve erişim anlaşılır |
| Testler | Soru seti, çalıştırma, sonuç ve senaryo bağlamı net; başarısızlık kanıtı erişilebilir |
| Çalıştırmalar / Onaylar | Durum, bekleme/hata nedeni, ilgili senaryo ve yetkili sonraki işlem |
| İstemciler / Entegrasyon | Bağlı senaryolar, protokol ve erişim durumu; sırların mevcut güvenli gösterimi korunur |
| Kaynaklar / Bağlantılar | Set bağlamı, yenileme durumu ve hatanın çözüm yolu; sır/ham bağlantı verisi sızmaz |
| Kullanıcılar / Platform | Günlük işlerden ayrı yönetim; mevcut kapsam ve onay kontrolleri korunur |
| Sürüm / Artifact / Önizleme | Ayrıntı sayfası amacı net; ilgili üst nesneye dönüş mevcut |
| Giriş / Hata / Boş durum | Tutarlı dil, erişilebilirlik ve güvenli yönlendirme; özel veri veya teknik traceback yok |

Her aile için liste, detay, form, boş, yükleniyor/işleniyor, doğrulama hatası, yetki reddi ve
başarısız işlem durumlarını değerlendir. Verisi olmadığı için görülemeyen ekranı tamamlandı sayma;
izole sentetik test verisiyle doğrula veya eksik önkoşulu somut olarak kaydet.

## 9. Güvenlik, mimari ve işletim değişmezleri

- Organizasyon, proje ve senaryo düzeyindeki sunucu yetkileri korunur. Menü görünürlüğü izin vermez.
- Doküman yönetimi, içerik okuma, senaryo düzenleme/yayınlama, runtime ve araç onay yetkileri
  birbirinin yerine geçirilmez; sadece daha anlaşılır sunulur.
- CSRF, POST ile durum değişikliği, input validation, nesne kapsamı, güvenli çıktı kodlama,
  audit, retry/idempotency ve değişmez sürüm kuralları zayıflatılmaz.
- Gizlenen panelde yetkisiz veri DOM/JSON olarak gönderilmez. Filtre ve sayaçlar da yetkilidir.
- Yeni sağlayıcı çağrısı, otomatik yayın/aktivasyon, erişim genişletme veya veri silme eklenmez.
- Mevcut işlevleri kaldırarak sadeleştirme yapma; ayrıntıyı doğru yere taşı.

## 10. Uygulama sırası ve doğrulama

1. Güncel envanter, görev/durum/rol matrisi ve önce ekran görüntülerini çıkar; planı güncelle.
2. Ortak görsel bileşenleri ve gezinme sözleşmesini kur. Mevcut Senaryolar girişini koru.
3. Doküman çalışma alanı ve hazırlama pilotunu uçtan uca uygula/doğrula.
4. Mevcut senaryo alt planıyla senaryo deneyimini uygula/doğrula.
5. Diğer tüm ekran ailelerini ortak düzene geçir; eski ve yeni bağlantıları kontrol et.
6. Son farkı mimari, AppSec ve SRE açısından incele; kullanım belgeleri ve kanıtları tamamla.

Her aşamada en küçük eksiksiz değişikliği yap. Kontroller başarısızsa nedeni gider;
test/iddia/güvenlik kontrolünü silerek yeşil sonuç üretme. Davranış değişiklikleri için anlamlı
testler ekle/güncelle; düşük etkili yalnız metin/link düzenlemeleri için uygulamayı tekrar eden
yapay testler yazma, mevcut test ve gerçek tarayıcı kontrolünü kullan.

[Test kuralları](../../ai/testing-rules.md) ve [manuel test rehberi bölüm 10](../../manual-testing-guide.md)
zorunludur. Gezinme/ortak şablon değişikliği bütün matrisi etkiler; yalnız ekran açılmasını
yaşam döngüsü/authorization kabulü olarak raporlama.

- İzinli, aynı tenant içinde yanlış kapsamlı/komşu rollü ve başka tenant'taki kimliklerle
  görünür eylemi doğrudan GET/POST reddiyle eşleştir; yetki kontrolünü mock etme.
- Doküman yükleme → hazırlama → kontrol → kullanıma alma ve senaryo düzenleme → test → yayın
  yolunu, mevcut izin/önkoşullara uyarak izole test ortamında doğrula.
- Model/embedding/connector/worker gereken yolun önkoşulunu önce kanıtla. Hazır değilse
  desteklenmeyen sonraki adımı başarılı sayma; eksikliği ve sonraki işi kaydet.
- Canlı kullanıcı verisi üzerinde deneme için set/hesap sıfırlama, izin değiştirme veya yayınlama
  yapma. Repository'nin izole sentetik ortamını kullan; destructive testler açık kapsam gerektirir.
- 390, 900, 1440 px; klavye/focus, Escape, sekmeler, dialog odağı, uzun adlar, tablo taşması,
  tarayıcı geri/ileri, deep link, form hata sonrası görünüm ve iptal davranışını kontrol et.
- Tarayıcı konsolu ve başarısız ağ isteklerini incele. Kanıtlarda token, cookie, parola,
  ham sağlayıcı yanıtı veya gerçek belge içeriği saklama.
- İlgili pytest, formatter/linter, type-check ve PostgreSQL profilini çalıştır. Frontend
  değiştiyse ilgili testleri ve güncel build'i çalıştır; eski Studio bundle'ını doğrulama sanma.
- Çalıştırılmayan kontrolü gerekçesiyle kaydet; önceki kanıtı yeni çalıştırma diye sunma.

## 11. Kabul ölçütleri ve teslim

- [ ] Senaryolar sol menüden doğrudan ve mevcut yetkiyle erişilebilir.
- [ ] Sayfa/alt görünüm/ana eylem açık; yeni kullanıcı işini iç mimariyi öğrenmeden bulabilir.
- [ ] Doküman dosyaları, hazırlık, sürümler ve erişim tek uzun sayfada yığılmıyor.
- [ ] Kullanılan içerik ile yeni hazırlık ayrı; hazırlama sessizce aktivasyon yapmıyor.
- [ ] Senaryo ilk kurulum ve günlük kullanım durumları tutarlı ve yetkiye uygun.
- [ ] Tüm sayfa aileleri, geçişler, form iptali, hata dönüşü ve eski deep link'ler değerlendirildi.
- [ ] Mobil/klavye ve yetki reddi dahil testler güncel build üzerinde kanıtlandı.
- [ ] İşlev, izin, audit, geçmiş veya güvenlik kontrolü kaybolmadı.
- [ ] Önce/sonra ekran görüntüleri ve tıklama sayıları; test komut/sonuçları; kalan riskler kayıtlı.

Teslimde değişen dosyaları ve **Implemented / Verified** durumlarını ayrı raporla. Mimari,
güvenlik, yetki, veri/gizlilik, log/metrik/trace/audit, veritabanı/migration etkilerini;
testleri, doğrulanmamış varsayımları ve gereken manuel incelemeyi açıkla.
Planları/master planı/kullanım belgelerini güncel tut. Kapanış için repository'nin Definition
of Done ve arşiv politikasını uygula; eksik tarayıcı kabulünü tamamlandı diye işaretleme.
