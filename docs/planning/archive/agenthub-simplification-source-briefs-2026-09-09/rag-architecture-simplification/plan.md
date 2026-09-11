# RAG mimarisini sadeleştirme

Tarih: 2026-09-09. Durum: **Planned — uygulama başlamadı.**

## Görev ve yetkilendirilmiş teslim

Kullanıcı tartışılan mimari için kodlama ajanı talimatı istedi. Bu turda teslim
yalnız [uygulama talimatı](implementation-prompt.md), bu plan ve risk/doğrulama
kayıtlarıdır. Talimatın hazırlanması uygulamanın başlatıldığı anlamına gelmez.

## Amaç ve kapsam

Hızlı RAG kurulum/bakımı; organizasyon, proje ve senaryo yetkileri korunarak
tek çözüm snapshot'ı, bağımsız veri yenileme, tek sabit vektör tablosu,
REST/MCP adapters ve kalıcı gelişmiş yürütme. 44 uygulama/54 toplam tablo
tasarım referansıdır; eksiksiz davranış ve güvenlik tablodan önce gelir.

Mevcut [vektör depolama işi](../shared-vector-storage/plan.md) aynı depolama
işinin ayrıntısını taşır; ikinci rakip uygulama yapılmayacak.
[Yetkilendirme işi](../authorization-simplification/plan.md) ayrı politika
değişiklikleri içerir; bu görevle kendiliğinden onaylanmış sayılmayacak.

## Uygulama kilometre taşları

| Ölçüt | Implemented | Verified |
| --- | --- | --- |
| Güncel model/davranış/izin matrisi ve geçiş tasarımı | Hayır | Hayır |
| Sabit vektör deposu ve runtime DDL'nin kaldırılması | Hayır | Hayır |
| Tek ScenarioRevision ve snapshot kullanan runtime | Hayır | Hayır |
| Bağımsız veri tazeliği ve ortak ingestion/bağlantı modeli | Hayır | Hayır |
| REST/MCP veri ve tool yollarının tamamlanması | Hayır | Hayır |
| Basit RAG UI, gelişmiş çalışma ve değerlendirme bütünlüğü | Hayır | Hayır |
| Geçiş, yetki, PostgreSQL, frontend ve tarayıcı kanıtları | Hayır | Hayır |

## Sınırlar, etkiler ve riskler

Bu belge tesliminde kod, şema, güvenlik, yetki, veri, telemetry ve runtime değişmez.
Uygulama başladığında migration, sözleşme, saklama, politika ve worker uyumluluğu
etkileri [talimat](implementation-prompt.md) ve [tehdit modeli](threat-model.md)
esas alınarak güncel kod üzerinde yeniden doğrulanacak. Mevcut yerel değişiklikler
korunacak. Üretim deploy, yeni dependency, reset ve yıkıcı temizlik kapsam dışıdır.

## Kontroller, rollout ve kapanış

Belge hazırlama kontrolleri [verification.md](verification.md) içindedir.
Uygulama için kabul testleri, eklemeli geçiş, geri dönüş ve onay sınırları talimatta
yer alır. Çalışan sistemin tamamlanması ayrı kanıt gerektirir. Uygulama tamamlanınca
ADR/current-behavior belgeleri, master plan ve arşiv politikası uygulanır; plan
yalnız talimat teslim edildi diye tamamlanmış uygulama olarak arşivlenmez.
