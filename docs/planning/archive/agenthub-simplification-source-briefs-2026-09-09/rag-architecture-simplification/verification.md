# Talimat hazırlama doğrulaması

2026-09-09 — Bu kayıt yalnız kodlama ajanı talimatının hazırlanmasına aittir.
**Belge teslimi hazır; uygulama Planned, Implemented/Verified değil.**

## İncelenen kaynaklar

- Kök AGENTS.md, görev/arşiv politikası, Definition of Done ve güncel master plan.
- Önceki ürün değerlendirmesi ve 35-model eşlemesi; sahibin proje/senaryo yetkilerini
  koruma düzeltmesi ve 44/54 tablo hesabı.
- shared-vector-storage/plan.md ve authorization-simplification plan/talimatı.
  Bunlar güncel keşifte bulundu; yeni talimat mevcut alt işleri ilişkilendirir,
  ayrı yetkilendirme politikasını kendiliğinden onaylanmış saymaz.
- Git çalışma ağacında önceden var olan çok sayıda değişiklik. Bunlar korunmuştur;
  bu teslim yalnız bu görev dizini ve master-plan.md eklemesinden oluşur.
- Codebase Memory/Serena araçları kullanılabilir listede bulunmadı. Bu belge işi
  için doğrudan kaynak/belge incelemesi ve metin araması yeterliydi.

## Hazırlık kontrolleri

- Dört görev Markdown dosyasındaki göreli dosya bağlantıları ve trailing whitespace
  kontrol edildi; hata bulunmadı.
- Talimattaki 12 model grubunun sayıları, açık model isimleri ve tekillikleri
  programatik sayıldı: **44 uygulama modeli**, bir Chunk; 10 varsayılan Django
  altyapı tablosuyla **54**. Gizli M2M/dinamik tablo hariç tutulması yasaklandı.
- master-plan.md değişikliği için git diff --check temiz.
- Talimat elle şu açılardan incelendi: proje/senaryo sınırı, tek fiziksel vektör
  tablosu, sıfır runtime DDL, yeni izin kazandırmayan snapshot, korunmuş advanced
  runtime, ayrı onaylı politika kapsamı, veri koruyan geçiş ve dürüst hedef sayım.

## Çalıştırılmayan kontroller

Uygulama testleri, migration/şema uygulaması, canlı DB/Compose/health sorguları,
provider çağrıları, browser testi ve performans ölçümü yapılmadı. Yalnız talimat
yazıldığı için bunlar bu belge tesliminde uygulanabilir değildir; gelecekteki
uygulamanın zorunlu kabul kanıtları talimatta açıkça yer alır. Yeni teknik sürüm
iddiası üretilmedi; uygulayıcıya kurulu sürümü ve resmi sözleşmeyi doğrulama görevi verildi.

## Etkiler, varsayımlar ve kalan inceleme

- Mimari: hedef ve fazlar tarif edildi; uygulanan mimari değişmedi.
- Güvenlik/yetkilendirme: hiçbir atama, grant, politika veya runtime yetkisi değişmedi.
- Veri/gizlilik, log/metrik/trace/audit: veri okunmadı/taşınmadı/silinmedi; davranış değişmedi.
- Veritabanı/dependency/deploy: değişiklik yok.
- Varsayımlar: güncel şema sayımı, model boyut kataloğu, workload/recall/latency eşikleri,
  retention, korunacak tüm katalog özellikleri ve başka görevlerin uygulama onayları
  henüz yeniden doğrulanmış değildir.
- Kalan risk: 44 sayısını zorlamak davranış/izin kaybına yol açabilir; talimat bunu
  yasaklar ve gerekçeli ek tabloya izin verir. Geçici legacy tablolar toplamdan gizlenemez.
- Manuel inceleme: kullanıcı talimatı uygulama görevi olarak verdiğinde kapsam ve
  mevcut onaylar canlı kaynakla uzlaştırılmalı; kodlama öncesi tam eşleme ve yıkıcı
  temizlik öncesi ayrı, somut geçiş incelemesi yapılmalıdır. Bu teslim deploy/reset onayı değildir.

Plan uygulama beklediği için arşivlenmedi. Arşivleme uygulama biriminin tamamlanmasından sonradır.
