# AgentHub arayüz değerlendirmesi

Bu belge bir tasarım önerisidir. Örnekler çalışan uygulama ekranları değildir.

## Bulgular

- Doküman setinde dosyalar, erişim, karantina, tek seferlik test, yaşam döngüsü,
  profil formları, işler, sürüm geçmişi, kaynaklar ve senaryo bağları aynı uzun sayfadadır.
  `document_set_detail.html` içindeki sekmeler ayrı görünüm yerine sayfa içi bağlantıdır;
  `console.js` de bunları ayrı panel haline getirmemektedir.
- Doküman/indeks bölgesindeki iki sütun; dosya satırlarını, birden fazla işlem düğmesini
  ve beş profil seçimini yan yana sıkıştırmaktadır. Bu kaynak yapısından çıkarımdır;
  oturum açılmış ekranın farklı genişliklerde görsel incelemesi yapılmamıştır.
- "Staged indeks oluştur", "Retrieval çalıştır", "Release derlemesinde pinlenir"
  gibi ifadeler kullanıcının sistem içi kavramları öğrenmesini gerektirmektedir.
- `documents.html` liste öncesinde sürekli açık bir oluşturma formu göstermektedir.
- Senaryo detayında da sözleşmeler, yaşam döngüsü, çalışma zamanı, test, sürümler,
  çağırma ve erişim ilişkileri aynı sayfada bulunmaktadır.

## Önerilen deneyim

Doküman seti için Dosyalar / Hazırlama / Sürümler / Erişim gerçek ayrı görünümler olsun.
Kaynak bağlantıları Dosyalar altında ikincil bir bölümde erişilebilir kalsın. Ana görünüm
dosya adını, anlaşılır durumunu ve sıradaki işi öne çıkarsın. Oluşturma/yükleme formu
ilgili eylemle açılsın. Teknik kimlikler ayrıntıda kopyalanabilir olsun.

Hazırlama akışı: Yükle → Hazırla → Kontrol et → Kullanıma al. Bu kullanıcı anlatımı
sunucudaki taslak yayımlama, değişmez içerik sürümü, indeks oluşturma ve aktivasyon
işlemlerini birleştiren yeni bir API sözleşmesi değildir. Her geçiş mevcut önkoşulları
korumalıdır. Kontrol adımında içerik önizlemesi, hatalı dosyalar ve örnek arama; son adımda
etkilenen senaryolar ve mevcut onay gereklilikleri gösterilmelidir. İndeks testi,
senaryonun gerçek yanıt kalitesi testi olarak sunulmamalıdır.

Görsellerdeki standart ayar paketi öneridir. Mevcut yayımlanmış ve yetkili profillere
eşlenmeden varsayılan seçilemez. Gerçek tasarımda set sürümü ile indeks sürümü ayrı
kimliklerle gösterilmelidir. İkinci görseldeki "Taslak v4" etiketi hazırlama başlamadan
önceki durumu anlatır; yayımlama sonrası aynı etiketi tutmak hatalı olur.

Görsel dil: açık yüzeyler, koyu okunaklı metin, sınırlı yeşil vurgu, ince ayırıcılar,
daha az iç içe kart ve her görünümde belirgin bir ana işlem. Durumlar renk yanında
metin/simge içermeli. Gelişmiş ayarlar ihtiyaç halinde açılmalı.

## Önerilen uygulama sırası

1. Ortak gezinme, tipografi, form ve durum bileşenleri; doküman çalışma alanı pilotu.
2. Gerçek durumlara bağlı hazırlama, hata/retry ve aktivasyon akışı.
3. Senaryo oluşturma/düzenleme ve test deneyimi.
4. Çalıştırmalar, istemciler, bağlantılar ve yönetim ekranları.

Console şu anda Django şablonları, akış düzenleyici React kullanıyor. İlk pilot mevcut
sunucu işlemleri üzerinde yapılabilir. Tüm arayüzü yeni bir teknolojiye taşımak için
bu inceleme yeterli gerekçe sağlamaz. Yeni bağımlılıklar veya sözleşme değişiklikleri
uygulama kapsamı belirlenirken ayrıca değerlendirilmelidir.

## Final report

- **Summary:** Kaynak temelli UX değerlendirmesi ve iki Türkçe görsel konsept hazırlandı.
- **Files changed:** Bu arşivde plan, değerlendirme ve doğrulama; master-plan ve arşiv
  dizininde bağlantılar; `outputs/ui-redesign-concept-2026-09-08/` altında iki PNG ve
  tam üretim promptları. Uygulama kaynaklarına bu görevde değişiklik yapılmadı.
- **Architecture impact:** Yalnız öneri; çalışma mimarisi değişmedi.
- **Security impact:** Güvenlik kontrolleri değişmedi; karantina gibi işlemler yetkili
  yönetim görünümünde bulunabilir kalmalı.
- **Authorization impact:** Rol, organizasyon ve nesne yetkileri değişmedi.
- **Data and privacy impact:** Görseller kurgusal verilerle üretildi; gerçek belge,
  kullanıcı kimliği veya sır görsel üretim aracına verilmedi.
- **Logging, metrics, tracing and audit impact:** Değişiklik yok.
- **Database and migration impact:** Değişiklik yok.
- **Tests and verification results:** Kaynak incelemesi, canlı Compose/health kontrolü,
  üretilen iki görselin görsel incelemesi ve dosya doğrulaması; ayrıntı verification.md.
  Kod değişmediği için uygulama test paketleri çalıştırılmadı.
- **Unverified assumptions:** Onaylı bir standart profil paketi bulunabilirliği;
  gerçek kullanıcı görevleri ve sık kullanım dağılımı; oturum açılmış ekran davranışı.
- **Remaining risks:** Statik görseller responsive davranışı veya erişilebilirliği
  kanıtlamaz. Bağımsız üretimde logo biçimi farklılaştı; uygulamada tek marka bileşeni
  kullanılmalı. Konseptler tüm hata/yetki/boş durumlarını kapsamıyor.
- **Manual review required:** Tasarım yönü kullanıcıyla değerlendirilmeli; uygulama
  aşamasında mobil, klavye, uzun dosya adları, yetki reddi, yarım kalan işler ve
  etkilenen senaryo onayı gerçek tarayıcıda doğrulanmalı.

## Görseller

- [Doküman çalışma alanı](../../../../outputs/ui-redesign-concept-2026-09-08/01-dokuman-calisma-alani.png)
- [İndeks hazırlama](../../../../outputs/ui-redesign-concept-2026-09-08/02-indeks-hazirlama.png)
- [Tam üretim promptları](../../../../outputs/ui-redesign-concept-2026-09-08/prompts.md)
