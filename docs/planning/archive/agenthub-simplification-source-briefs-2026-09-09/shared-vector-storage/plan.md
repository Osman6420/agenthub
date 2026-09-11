# Uygulama talimatı: Birden fazla embedding boyutunu tek sabit tabloda saklama

Tarih: 2026-09-09

Durum: **Planned**. Talimat hazırlanmıştır; mimari değişiklik uygulanmamış ve çalışma zamanında doğrulanmamıştır. Bu belge uygulama işinin planıdır.

## 1. Amaç ve kesin sınırlar

AgentHub'ın hızlı RAG çözümü geliştirme ve bakım hedefi doğrultusunda, her `IndexVersion` için oluşturulan `chunk_iv_<id>` tablolarını tek, migration ile yönetilen fiziksel chunk/embedding tablosunda birleştir.

Temel gereksinimler:

- Aynı tabloda farklı embedding modelleri, boyutları, tenant'lar ve mantıksal indeks sürümleri bulunabilsin.
- Rutin ingestion, yeniden indeksleme, retry, promotion, rollback ve retention işlemleri **DDL çalıştırmasın**. `CREATE TABLE`, `CREATE INDEX`, partition oluşturma, `ALTER` ve `DROP` bu akışlardan çıkarılsın.
- Desteklenen boyutlar için gerekli fiziksel arama indeksleri kontrollü deployment/migration sırasında oluşturulsun. Her tenant, belge kümesi veya `IndexVersion` için yeni fiziksel indeks oluşturulmasın.
- Yeni sürüm hazırlanırken aktif sürüm hizmet versin. Promotion ve rollback atomik metadata referansı değişimi olarak kalsın.
- Kimlik doğrulama, yetkilendirme, tenant izolasyonu, belge erişimi, audit ve mevcut release kuralları korunmalı. Önceki konuşmadaki governance sadeleştirmeleri bu işin kapsamı değildir.

Bu belgenin hazırlanması veri silme, veritabanını sıfırlama, eski tabloları düşürme veya üretim ortamına erişme yetkisi vermez. Uygulama sırasında gerekli yıkıcı temizlik ayrı, somut envanter ve geri dönüş planıyla ele alınmalıdır. Canlıda olmamak, mevcut geliştirme verisinin değersiz olduğu anlamına gelmez.

## 2. Önce doğrulanacak mevcut yapı

Başlamadan `AGENTS.md`, ilgili alt talimatlar, güncel çalışma ağacı ve aşağıdaki kaynaklar okunmalı. Mevcut, ilgisiz değişikliklerin üzerine yazılmamalı. 2026-09-09 incelemesinde ingestion, release, console ve başka alanlarda önceden mevcut yerel değişiklikler vardır.

| Kaynak | İncelenecek konu |
|---|---|
| [vector_store.py](../../../../../apps/ingestion/vector_store.py) | Provision, write, copy, vector/keyword search, preview, text resolution, existence ve drop işlemleri |
| [models.py](../../../../../apps/ingestion/models.py) | `IndexVersion`, `EmbeddingProfile`, eski `Chunk` ve `IndexedDocument` ilişkileri |
| [staged_build.py](../../../../../apps/ingestion/staged_build.py) | Build, başarısız build temizliği, promotion, rollback, purge |
| [job_lifecycle.py](../../../../../apps/ingestion/job_lifecycle.py) | Retry, eşzamanlılık ve iş durumları |
| [providers.py](../../../../../apps/retrieval/providers.py) | ACL filtreleri, aktif sürüm seçimi, hibrit ve eski retrieval yolları |
| [0015 migration](../../../../../apps/ingestion/migrations/0015_index_store_ddl_functions.py) | DDL yapan `SECURITY DEFINER` fonksiyonları ve yetkiler |
| [ADR-0003](../../../../adr/0003-vector-storage-blue-green-per-index-version.md) | Değiştirilecek fiziksel depolama kararı |
| [ADR-0017](../../../../adr/0017-bounded-halfvec-response-truncation.md) | Boyut ve halfvec davranışının korunması |
| [Önceki değerlendirme](../../fixed-vector-storage-assessment-2026-09-08/plan.md) | Tarihsel değerlendirme; güncel kod yerine kullanılmamalı |

`vector_store` çağıran console, evaluation, belge önizleme, kanıt görüntüleme, CLI ve test yollarını da tara. Sadece ana retrieval fonksiyonunu değiştirmek yeterli değildir.

Mevcut `Chunk` modeli sabit boyutlu ve `IndexedDocument` ilişkili; managed-document yolu ise `document_version_id` kullanıyor. Bu iki kimliği körlemesine aynı alana taşıma. Mevcut tabloyu genişletme veya yeni ortak tabloya taşıma kararını gerçek referanslara göre ver; nihai durumda iki bağımsız, aktif vektör deposu bırakma. Geçişte eski tabloların salt okunur tutulması mümkündür.

## 3. Hedef veri modeli

Fiziksel tablo adını repository'nin Django adlandırmasına göre seç. Aşağıdaki alanlar kavramsal sözleşmedir; doğrudan çalıştırılacak migration değildir.

| Alan | Amaç |
|---|---|
| `id` | Satır kimliği |
| `organization_id` | Tenant kapsamı |
| `index_version_id` | Mantıksal build/sürüm kimliği |
| Belge referansları | Managed `DocumentVersion` ve gerekiyorsa legacy `IndexedDocument` kimliği |
| `ordinal`, `chunk_kind` | Parça sırası ve content/summary ayrımı |
| `text` | Chunk içeriği |
| `embedding` | Boyutu sabitlenmemiş `vector` alanı |
| `dimensions` | Gerçek vektör boyutu; fiziksel indeks seçimi ve doğrulama |
| Gerekli zaman alanları | Mevcut bakım ve izlenebilirlik davranışı |

Model/profile revizyonu, embedding geometrisi ve pipeline kimliği `IndexVersion` üzerinden otoritatif olarak çözülmeli. Sorgu için bunları satırda tekrar saklamak gerekirse tutarlılığı nasıl zorunlu kıldığını belgeleyip test et.

Veritabanı ve servis sınırlarında şu garantileri kur:

- Vektör boyutu pozitif, desteklenen aralıkta ve `vector_dims(embedding)` ile eşleşmeli; profile/sürüm geometrisiyle de tutarlı olmalı.
- Tenant, indeks sürümü ve belge sahipliği birbirine uymalı. Tekil foreign key'lerin cross-tenant ilişkiyi kendiliğinden engellemediğini dikkate al; uygun bileşik kısıt/trigger veya mevcut eşdeğer garantiyi tasarla.
- Chunk kimliği sürüm, belge, ordinal ve chunk türü kapsamıyla çakışmasız olmalı. Nullable legacy/managed referanslarının unique ve CHECK davranışını açıkça ele al.
- Aynı boyuttaki farklı modeller uyumlu kabul edilmemeli. Query embedding'i doğru model/revizyon ile üretilmeli; chunk kopyalama mevcut pipeline uyumluluğu kontrollerini korumalı.
- Aktif veya tamamlanmış sürümlere yanlışlıkla yazma, retry sırasında duplicate satır ve geç tamamlanan worker'ın temizlenmiş sürüme yazması engellenmeli.

## 4. Çok boyutlu arama ve sabit fiziksel indeksler

pgvector `vector` kolonunda farklı boyutları saklayabilir. HNSW expression/partial indeksinin kapsadığı satırlar ise aynı boyutta olmalıdır. **Tek tablo, tek HNSW indeksi zorunluluğu anlamına gelmez.**

Önerilen varsayılan: deployment için sonlu bir `(boyut, arama temsil tipi, mesafe metriği)` listesi belirle ve fiziksel indeksleri bu listeye göre migration ile önceden oluştur. Listeyi canlı tenant/profile kayıtlarından dinamik DDL üreterek oluşturma. Yeni boyutun etkinleştirilmesi kontrollü şema değişikliğidir; desteklenen boyuttaki yeni build değildir.

Aşağıdaki SQL yalnızca tasarım örneğidir; tablo adı, tipler ve boyutlar uygulama sırasında doğrulanmalıdır:

```sql
CREATE INDEX chunk_embedding_768_cosine
ON shared_chunk USING hnsw ((embedding::vector(768)) vector_cosine_ops)
WHERE dimensions = 768;

CREATE INDEX chunk_embedding_3072_cosine
ON shared_chunk USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
WHERE dimensions = 3072;
```

- `vector` ve `halfvec` HNSW sınırlarını kurulu PostgreSQL/pgvector sürümünde doğrula. Python paket sürümü, PostgreSQL extension sürümünün kanıtı değildir.
- Halfvec ile arama hassasiyetinin ve skor hesaplamasının mevcut davranışla farkını ölç; sessizce normalizasyon, boyut kesme veya sıfırla doldurma ekleme. ADR-0017'nin mevcut sözleşmesini koru.
- Sorgu, doğru cast/mesafe operatörü ve partial-index predicate'i ile yazılmalı. Boyut/type SQL ifadelerini yalnızca doğrulanmış sunucu allowlist'inden seç; kullanıcı verilerini parametrele.
- Prepared statement ve generic/custom query planlarında indeks kullanımını doğrula. `WHERE dimensions = parametre` ifadesinin her planda partial indeksi kullanacağını varsayma.
- Tenant, model/sürüm ve belge ACL filtrelerini uygula. Aynı boyutlu modellerin aynı fiziksel HNSW'yi paylaşması onların sonuçlarını birbirine karıştırma izni değildir.
- B-tree filtre indekslerini ve mevcut keyword/GIN arama ihtiyacını ayrıca tasarla. Hibrit sıralama, summary/content filtreleri ve citation davranışını koru.
- Dar tenant/sürüm filtrelerinde HNSW sonuçları eksik kalabilir. Kurulu sürüm destekliyorsa bounded iterative scan ve uygun aday bütçesini değerlendir; kapsamlı exact-search referansıyla recall ölç. Küçük filtrelenmiş kümeler için bounded exact-search yolu kullanılabilir.
- Tanımlı fiziksel desteği bulunmayan boyutu build başlamadan güvenli, anlaşılır hata ile reddet. Otomatik DDL veya sessiz, sınırsız full scan fallback'i ekleme.

Sıfır runtime DDL karşılığında sınırsız, önceden bilinmeyen boyutlar için otomatik HNSW desteği vaat etme. Destek listesi deployment sözleşmesidir.

## 5. Yaşam döngüsü değişiklikleri

1. **Build:** Yeni `IndexVersion` kaydı aç, chunk'ları ortak tabloya bu kimlikle yaz. Aktif sürüm satırlarını değiştirme. Batch yazma, retry ve iptal davranışını koru.
2. **Provision:** Tablo oluşturmayı kaldır. Gerekli şema/indeks desteği ve sürümün yazılabilirliğini kontrol eden hazırlık adımına dönüştür veya çağıranları güncelle.
3. **Hazır olma:** `store_exists()` yerine sürüme ait build durumunu ve veri bütünlüğünü kontrol et. Ortak tablonun varlığı her sürümün hazır olduğu anlamına gelmez. Sıfır chunk üreten geçerli build ile yarım kalmış build ayrılmalı.
4. **Copy/reuse:** Uyumlu chunk'ları aynı tabloda yeni sürüm kimliğiyle kopyala. Farklı model/pipeline için yeniden embedding üret; boyut eşitliğini yeterli sayma.
5. **Promotion/rollback:** Metadata seçimini transaction içinde değiştir. Aramanın seçtiği sürüm ile query embedding modeli tutarlı bir snapshot oluşturmalı. Yeni tablo, kopya veya fiziksel indeks oluşturma.
6. **Cleanup/retention:** Sürüm kapsamlı, bounded batch `DELETE` kullan. Aktif, referans verilen veya çalışan bir işin kullandığı sürümü silme. Promotion ile purge yarışını aynı kilitleme protokolüyle önle.
7. **Bakım:** Autovacuum, dead tuple, ortak HNSW büyümesi ve retention disk ihtiyacını ölç. İşlem başına `VACUUM FULL`/`REINDEX` ekleme; gerektiğinde DBA bakım prosedürü tanımla.

## 6. Güvenlik, yetkilendirme ve tehdit modeli

Güven sınırları: API/console girdisi → yetkili servis → worker → PostgreSQL; migration rolü uygulama rolünden ayrıdır.

| Risk | Zorunlu önlem / kanıt |
|---|---|
| Ortak tabloda tenant verisinin karışması | Uygulama filtreleri + `FORCE ROW LEVEL SECURITY`, transaction-local scope ve kapsam yokken red testi |
| Tenant doğru, belge/senaryo izni yanlış | Mevcut ACL/tombstone kontrollerini vector, keyword, preview ve kanıt yollarında koru |
| Yanlış sürüm/modelden cevap | Otoritatif `IndexVersion` çözümü, model uyumluluğu ve eşzamanlı promotion testi |
| Runtime rolünün tablo/indeks oluşturabilmesi | DDL ayrı migration rolünde; eski SECURITY DEFINER çağrı yolunu ve execute grant'lerini geçiş sonunda kapat |
| Geniş DELETE veya FK cascade ile veri kaybı | Tenant+sürüm filtresi, referans denetimi, bounded batch ve yarış testleri |
| Ortak HNSW üzerinde kaynak rekabeti | Query timeout, aday/tarama sınırları, farklı büyüklükte tenant'larla kalite ve gecikme testi |
| Log/audit'e içerik sızması | Metin, vektör, query, token ve secret yazma; güvenli kimlik/sayı/hata sınıfı kullan |

RLS kanıtı superuser veya `BYPASSRLS` rolüyle verilmemeli. Read/write/delete ve connection reuse sonrası tenant context testleri ayrı yapılmalı. Gereken dar DELETE yetkisi dahil rol değişiklikleri açıkça belgelenmeli; geniş DDL/ownership yetkisiyle sorun çözülmemeli.

Audit'in mevcut actor, target, decision, outcome ve transaction davranışını koru. DDL kaldırıldığı için lifecycle audit'i kaldırma. Metric etiketlerine tenant, chunk veya index-version kimliği gibi yüksek çeşitlilikte değerler ekleme.

## 7. Uygulama ve veri geçiş sırası

1. Canlı çalışma ağacını ve ilgili testleri incele; bu planı gerçek davranışla uzlaştır. Desteklenecek geometri listesi, legacy kapsamı ve performans hedeflerini belirle.
2. Yeni ADR ile ADR-0003'ün fiziksel store kararını değiştir; eski ADR'yi tarihsel kayıt olarak koruyup bağlantı ver. Gerçekleşmemiş davranışı mevcut mimari olarak yazma.
3. Ortak model/kısıtlar/RLS/sabit indeksler için yeni migration'lar ekle. Uygulanmış eski migration'ları yeniden yazma. Güncel son migration numarasını kontrol et.
4. DAL ve tüm çağıran yolları yeni depoya geçir; hazır olma, cleanup ve model seçimini uyumlu hale getir.
5. Mevcut veri için varsayılan veri-koruyan taşıma planını uygula: eski store/legacy envanteri, tenant/sürüm/boyut/satır sayıları, idempotent batch backfill ve içerik/kimlik doğrulaması. Backfill'i kullanıcının provider'ına yeniden embedding çağrısı yapmadan gerçekleştir.
6. Kurulum canlı olmadığından kısa planlı yazma duraklamasını varsayılan geçiş yöntemi olarak değerlendir. Worker'ları drain et; eski ve yeni kodun aynı anda yazmasını engelle. Gereksiz kalıcı dual-write altyapısı kurma.
7. Eşleşme kanıtından sonra okuma/yazmayı yeni depoya geçir. Aktif/staged sürümleri ve geçmiş kanıt referanslarını doğrula. Geçici legacy erişimi sonlandır.
8. Eski tabloların silinmesini ilk cutover'a bağlama. Doğrulanmış envanter, saklama süresi, geri dönüş yöntemi ve yıkıcı işlem yetkisiyle ayrı cleanup migration/operasyonu planla. Nihai şemada eski aktif vektör yolu kalmamalı.
9. Deployment/rol şablonları, runbook, güncel mimari belgeleri ve master plan bağlantılarını güncelle; doğrulama kaydını oluştur.

Uygulama rollback'i ile indeks sürümü rollback'i farklıdır. Eski uygulama sürümüne dönmek, cutover sonrası ortak tabloya yazılan veriyi eski kodun okuyabildiği anlamına gelmez. Geri dönüş sınırını tanımla: yeni yazma öncesi eski depoya dönme; yeni yazma sonrası doğrulanmış ters taşıma veya forward-fix. Veri kaybını kabul eden örtük rollback yazma.

## 8. Kabul kriterleri ve test planı

- [ ] Tek fiziksel aktif chunk/embedding deposu; aynı tabloda en az iki farklı boyut ve aynı boyutlu iki farklı model test edilir.
- [ ] Tekrarlanan build/reindex/retry/promotion/rollback/retention sonrası tablo ve indeks envanteri değişmez. Başarısız DDL girişimleri de sorgu yakalama/uygun gözlem ile tespit edilir.
- [ ] Runtime rolünün schema CREATE veya eski DDL fonksiyonlarını çalıştırma yetkisi olmadan akışlar tamamlanır.
- [ ] Desteklenmeyen boyut erken reddedilir; yanlış uzunluk/model, null/geçersiz değerler mevcut sözleşmeye göre doğrulanır.
- [ ] Tenant dışı okuma/yazma/silme, scope eksikliği, connection reuse ve yanlış tenant FK bağları gerçek PostgreSQL rolüyle test edilir.
- [ ] Belge ACL, tombstone, boş izin listesi, content/summary, keyword/vector/hybrid, preview ve evaluation evidence davranışları korunur.
- [ ] Yarım build sunulmaz; boş geçerli build ayırt edilir; retry chunk çoğaltmaz; worker iptal/cleanup yarışı test edilir.
- [ ] Reindex sırasında eski sürüm yanıt verir; promotion model ve veri seçimini birlikte değiştirir; rollback eski sonuçlara döner.
- [ ] Aktif veya referans verilen sürüm retention ile silinmez; diğer sürümler/tenant'lar etkilenmez.
- [ ] Yeni kurulum ve mevcut legacy/dinamik veri üzerinden yükseltme test edilir. İkinci backfill çalışması duplicate üretmez; halfvec taşınan değerler ve geçmiş referanslar doğrulanır.
- [ ] Temsili veriyle `EXPLAIN (ANALYZE, BUFFERS)`, prepared query planı, p50/p95 gecikme ve recall@k kaydedilir. Küçük tenant/büyük tenant, çok sayıda eski sürüm ve build altında okuma ölçülür.
- [ ] Recall referansı aynı yetkili veri/model kapsamındaki exact-search sonucudur. Kabul eşikleri ölçümden önce plan kaydına yazılır; ölçmeden performans eşdeğerliği iddia edilmez.
- [ ] Audit/redaction testleri geçer; başarısız işlemlerin kaydı mevcut garantiyle uyumludur.
- [ ] Repository'nin güncel formatter, linter, type-check, ilgili unit/integration/security/migration ve secret kontrolleri çalıştırılıp sonuçları kaydedilir. SQLite, PostgreSQL/pgvector testlerinin yerine geçmez.
- [ ] Nihai diff mimari, uygulama güvenliği ve operasyon açısından ana agent tarafından incelenir; zorunlu manuel testler ve çalıştırılamayan kontroller raporlanır.

Başlangıç test kapsamı: ingestion `test_vector_store`, `test_staged_build`, `test_promotion`, `test_job_lifecycle`; retrieval `test_pgvector_provider`; ilgili document ACL, console, evaluation ve migration testleri. Gerçek test komutlarını güncel repository/CI ayarlarından türet. Uygulamayı başlatmak veya durumunu incelemek gerekirse önce manual-testing-guide bölüm 0 ve canonical Compose talimatlarını izle.

## 9. Tamamlama ve teslim raporu

`Implemented` ile `Verified` ayrı tutulmalı. Testler ve geçiş kanıtları olmadan mimari tamamlandı sayılmamalı. Uygulama sırasında `verification.md` oluştur; bu belgedeki tehdit modelini gerekirse ayrı `threat-model.md` ile detaylandır. Tamamlanınca planlama/arşiv politikasını uygula.

Teslim raporu şu başlıkları kapsamalı: Summary; Files changed; Architecture impact; Security impact; Authorization impact; Data and privacy impact; Logging, metrics, tracing and audit impact; Database and migration impact; Tests and verification results; Unverified assumptions; Remaining risks; Manual review required.

## 10. Bu talimatın hazırlık kanıtı ve kaynakları

2026-09-09: Task şablonu/kuralları, agent handoff, git durumu, ADR-0003, mevcut vector DAL, legacy Chunk modeli, migration 0015 ve çağıran referanslar incelendi. Aktif handoff başka bir işe aittir; runtime bilgileri bu belgeye taşınmadı. Kullanılabilir araçlarda Codebase Memory/Serena görünmediğinden doğrudan kaynak ve metin araması kullanıldı.

Bu teslim yalnızca yeni Markdown belgesidir. Uygulama kodu, migration, bağımlılık, auth/RLS, veri, log veya çalışan servis değiştirilmedi. Uygulama testleri ve performans ölçümü yapılmadı; bunlar yukarıdaki uygulama kabul kriterleridir. Kurulu extension sürümü, gerçek veri hacmi ve desteklenecek boyut listesi henüz doğrulanmadı.

Doküman kontrolü: PowerShell ile tüm göreli Markdown bağlantıları çözümlendi, kırık bağlantı bulunmadı. `git diff --no-index --check -- NUL docs/tasks/shared-vector-storage/plan.md` whitespace tanısı üretmedi (yeni dosya karşılaştırması çıkış kodu 1). İçerik; kapsam, tenant/model ayrımı, sıfır runtime DDL, veri-koruyan geçiş ve geri dönüş sınırları açısından gözden geçirildi.

Teknik kaynaklar (önceki teknik değerlendirmede kontrol edildi; uygulama sırasında kurulu sürümle eşleştir):

- [pgvector: aynı kolonda farklı boyutlar](https://github.com/pgvector/pgvector#can-i-store-vectors-with-different-dimensions-in-the-same-column)
- [pgvector: filtreleme](https://github.com/pgvector/pgvector#filtering)
- [pgvector: iterative index scans](https://github.com/pgvector/pgvector#iterative-index-scans)
- [pgvector: half-precision indexing](https://github.com/pgvector/pgvector#half-precision-indexing)
