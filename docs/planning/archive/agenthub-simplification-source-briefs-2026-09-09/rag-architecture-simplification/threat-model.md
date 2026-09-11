# Risk ve güven sınırları

Bu kayıt önerilen uygulamaya aittir; mevcut uygulamada kontrol değişmedi.

| Sınır / risk | Gereken önlem ve kanıt |
| --- | --- |
| İnsan/istemci → API/console/MCP | Kimliği güvenilir kaynaktan çöz; mevcut nesne/işlem/proje/senaryo izinlerini koru; liste ve doğrudan ID yollarında negatif test |
| API → worker → ortak tablo | Transaction-local tenant scope, FORCE RLS, non-owner/non-BYPASSRLS rol; tenant tutarlı FK/yazma doğrulaması; eksik kapsamda ret |
| Koleksiyon → senaryo | Binding'i grant sayma; güncel belge/istemci izinleri, tombstone ve kaynak erişim sınırları korunmalı |
| Snapshot → çalışan iş | Snapshot yetki kaynağı değil; güncel iptaller geçerli; yeniden deneme ve worker sürüm uyumluluğu kontrollü |
| Tool → dış sistem | Mevcut SSRF/egress/secret sınırları, gerçek initiator, girdiye bağlı onay, idempotency; bilinmeyen yan etki sonucu için reconcile |
| Veri yenileme → yayın | Nesil/model aynı snapshot'tan seçilir; yarım veri aktifleşmez; yayından bağımsız yenileme veri erişimini genişletemez |
| Retention → aktif okuma/iş | Referans ve retry/rollback pencereleri; purge/promotion/late worker yarışlarını önleyen kilit ve fencing; bounded DELETE |
| Eski şema → yeni şema | İzin ve içerik eşdeğerliği, açık kimlik haritası, tekrarlanabilir aktarım, tek yetkili yazıcı ve test edilmiş geri dönüş |
| Paylaşılan ANN | Tenant/nesil seçiciliğiyle recall ve gecikme; prepared/generic query planları; exact-search referansı ve vacuum/disk ölçümü |
| Katalogları birleştirme | Global/tenant sahipliği ve mevcut profile grant'lerini kaybetme; gerekiyorsa 44 sayısını artır |
| UI sadeleştirme → güvenlik | Düğme gizlemeyi sunucu yetkisi sayma; yayın kontrolü ve tool onayı ayrımı; mevcut zorunlu kapıları sessizce kaldırma |
| Audit/telemetry | Aktör, hedef, karar, sonuç, trace ve güvenli IDs; secret/chunk/vektör loglama; audit hata politikasını koru |

Varsayımlar: proje canlıda değil fakat yerel verinin silinmesine izin verilmedi.
Kurumsal model boyut listesi, veri hacmi, saklama süreleri, kabul edilen kalite/latency
eşikleri ve ayrı yetkilendirme talimatının uygulama onayı bilinmiyor. Bunlar testten
geçmiş veya onaylanmış gibi gösterilmeyecek. Onay gerektirmeyen kod keşfi, test ve
tasarım devam eder; yalnız bağımlı sınır için somut karar gerekir.
