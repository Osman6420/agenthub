# Talimat belgesi doğrulaması — 2026-09-09

## Belge teslimi

Konuşmadaki tasarım hedefleri, iki örnek görsel, gezinme görevi ve güncel master plan okundu.
Mevcut senaryo talimatı ayrı alt iş olarak bağlandı; RAG/vektör/yetki planları kapsam dışı
olarak işaretlendi. Mevcut kirli çalışma ağacı incelendi; uygulama dosyaları değiştirilmedi.

Ana talimat mevcut ve önerilen davranışı ayırır. Önceki 348/1 ve 72 test sonuçları yalnız
tarihli referanstır; bu teslimde yeniden çalıştırılmış test olarak sunulmaz.

## Final report

- Summary: Kodlama ajanı için Türkçe, uygulanabilir arayüz talimatı hazırlandı.
- Files changed: implementation-instructions.md, plan.md, threat-model.md, verification.md;
  master planına bağlantı eklendi.
- Architecture impact: Belge düzeyinde; mevcut Django/React yapısı korunarak hedef tarif edildi.
- Security impact: Uygulama kontrolü değişmedi; sınırlar talimata aktarıldı.
- Authorization impact: İzin veya rol değişmedi; ayrı yetki işi onaylanmış sayılmadı.
- Data and privacy impact: Gerçek kullanıcı verisi/sır eklenmedi; görseller kurgusal.
- Logging, metrics, tracing and audit impact: Değişiklik yok.
- Database and migration impact: Değişiklik yok.
- Tests and verification results: Yerel Markdown/görsel bağlantıları çözümlendi; kod bloğu
  kapanışları, kapsam/durum tutarlılığı ve master plan farkının boşluk kontrolü geçti.
  Uygulama testleri bu yalnız-belge tesliminde uygulanabilir değil. Ana ajan mimari,
  AppSec ve operasyon açısından belgeyi gözden geçirdi; canlı işlem yapılmadı.
- Unverified assumptions: Gelecek uygulamadaki kod/runtime, uygun standart profiller ve
  erişilebilir hazırlanan-indeks testi başlangıçta yeniden doğrulanmalı.
- Remaining risks: Paralel task planları ilerleyebilir; eski varsayımla uygulama yapma riski.
- Manual review required: Uygulama sonrası tam tarayıcı/rol matrisi ve kullanıcı deneyimi kabulü.

Kapsamlı arayüz uygulaması Planned olarak kalır. Bu belge teslimi onun tamamlandığı anlamına gelmez.
