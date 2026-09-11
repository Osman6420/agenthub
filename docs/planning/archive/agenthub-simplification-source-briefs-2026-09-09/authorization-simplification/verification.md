# Doğrulama kaydı

## 2026-09-09 — uygulama talimatının hazırlanması

Bu kayıt belge teslimine aittir. Uygulama başlamadı; plan **Planned** durumundadır.

### İncelenen kaynaklar

- Önceki yetkilendirme değerlendirmesi ve kaynak/test bulguları yeniden okundu.
- Task şablonu ve docs çalışma ağacı durumu kontrol edildi.
- Yeni talimat hedef rol matrisi, delegasyon ve devralma kuralları, mevcut veri
  uyumluluğu, consumer paketleri, veri erişim modları, ortak UI kararları,
  MCP kaynak kapsamı, kabul testleri ve rollout sınırları açısından incelendi.
- Önceki rapordaki açık ürün tercihleri bu uygulama brief'inde somutlaştırıldı;
  mevcut davranış veya yapılmış değişiklik olarak sunulmadı.

### Belge kontrolleri

Uygulama talimatı, plan, risk modeli ve bu kayıt için UTF-8, satır sonu,
Markdown dosya bağlantıları ve sondaki boşluk kontrolleri yapılır. Ana plan
bağlantısı uygulama durumunu Planned olarak belirtir. Sonuç aşağıda kaydedilir.

Sonuç: Dört dosyada UTF-8, satır sonu ve sondaki boşluk kontrolleri geçti;
sekiz yerel dosya bağlantısı çözümlendi. `git diff --check --
docs/planning/master-plan.md` exit 0. Talimat 365 satırdır. Son içerik incelemesi
uygulama/teslim ayrımını, eski erişim korumasını ve kapsam dışı işlemleri doğruladı.

### Teslim raporu

- Summary: Kullanıcının verebileceği, bağımsız okunabilir Markdown uygulama talimatı hazırlandı.
- Files changed: Bu task'ın dört Markdown dosyası ve master-plan bağlantısı.
- Architecture impact: Hedef model belgelendi; mevcut mimari değişmedi.
- Security impact: Doküman içeriği, insan onayı ve güvenilir hedef denetimleri talimatta korundu; kod değişmedi.
- Authorization impact: Rol/devralma/geçiş kuralları yazıldı; gerçek atamalar ve yetkiler değişmedi.
- Data and privacy impact: Canlı veri okunmadı/değiştirilmedi.
- Logging, metrics, tracing and audit impact: Mevcut davranış değişmedi; gelecekteki audit gereksinimleri belirtildi.
- Database and migration impact: Migration veya veri işlemi yapılmadı; gelecekteki eklemeli geçiş tarif edildi.
- Tests and verification results: Belge kontrolleri; uygulama kodu değişmediği için uygulama testleri tekrar çalıştırılmadı.
- Unverified assumptions: Uygulama ajanı dosyaları, canlı runtime'ı ve geçiş öncesi veriyi yeniden doğrulamalı.
- Remaining risks: Gelecekteki rol/devralma ve ortak veri geçişi; otomatik yetki genişlemesini önleyen kabul ölçütleri verildi.
- Manual review required: Talimat uygulanırken gerçek erişim dönüşümleri ve rollout kanıtları incelenmeli; bu tur uygulama/deploy yapılmadı.

## Gelecekteki uygulama

Uygulama ajanı gerçek komutları, sonuçları ve çalıştırılmayan kontrolleri burada
kaydetmeli. Belge hazırlama kontrolü veya önceki 43/15 test sayısı yeni
yetkilendirme uygulamasının doğrulanması olarak kullanılmamalı.
