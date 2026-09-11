# Tek sabit vektör tablosu değerlendirmesi

2026-09-08. Tasarım önerisidir; uygulama ve veritabanı değiştirilmedi.

## Sonuç ve yeni kısıt

Evet: bütün koleksiyonların parça metinleri ve embedding kayıtları tek sabit tabloda
tutulabilir. Kurumun çalışma sırasında tablo oluşturmayı kabul etmemesi hedef
mimari için bağlayıcıdır. Yeni ekip, koleksiyon, belge veya indeksleme işi yalnızca
veri eklemeli/güncellemelidir. Tablo, partition, politika ve arama indeksi oluşturma
işleri yalnızca kontrollü dağıtım/migration sürecine ait olmalıdır. Her indeksleme
için partition veya kısmi indeks oluşturmak bu kısıta uygun bir çözüm değildir.

Bu sonuç önceki [ürün değerlendirmesindeki](../rag-product-architecture-reassessment-2026-09-08/assessment.md)
fiziksel depolama seçeneğini daraltır. Önceki incelemenin dinamik depoları geçici
olarak koruma seçeneği artık hedef mimari için önerilmez. Mevcut ADR-0003 hâlâ
uygulanan davranışı açıklar; bu belge onu uygulanmış bir değişiklik gibi yenilemez.

## Mevcut kodun yaptığı

- [vector_store.py](../../../../apps/ingestion/vector_store.py): `store_name` her
  `IndexVersion` için `chunk_iv_<id>` üretir; `provision_store` veritabanındaki
  `agenthub_provision_index_store` fonksiyonunu çağırır.
- [0015 migration](../../../../apps/ingestion/migrations/0015_index_store_ddl_functions.py):
  bu SECURITY DEFINER fonksiyonu tablo, HNSW/GIN indeksleri ve RLS politikası oluşturur.
  Uygulama rolünün doğrudan CREATE yetkisi olmaması, çalışma sırasında DDL yapılmadığı
  anlamına gelmez.
- [staged_build.py](../../../../apps/ingestion/staged_build.py): hazırlık provision/copy,
  temizlik drop yolunu kullanır. DAL içindeki vektör, kelime araması, önizleme ve
  kopyalama işlemleri dinamik tablo adına bağlıdır.
- [ADR-0003](../../../adr/0003-vector-storage-blue-green-per-index-version.md), tek tabloyu
  zaten değerlendirmiştir. Ayrı tablo tercihi yaşam döngüsü ve çok boyutlu embedding
  yönetimi için yapılmıştır; güvenli sürüm geçişinin zorunlu şartı değildir.

## Önerilen başlangıç modeli

Sabit `chunks` tablosu için kavramsal alanlar:

| Alan | Amaç |
| --- | --- |
| id | Parça kimliği |
| organization_id | Mevcut ekip/tenant güvenlik sınırı |
| index_version_id | Verinin hangi hazırlık nesline ait olduğu |
| document_version_id | Kaynak belgenin kesin revizyonu |
| ordinal, chunk_kind | Parçanın sırası ve türü |
| text, embedding | Metin ve vektör |

Embedding modeli, model revizyonu, boyutu ve temsil tipi `IndexVersion` üzerinden
çözülebilir. Birden fazla önceden desteklenen embedding uzayı için kısmi indeks
gerekiyorsa sabit, doğrulanan bir `embedding_space` alanı da eklenebilir. Eşit boyutlu
farklı modellerin vektörleri birbirleriyle uyumlu varsayılmaz. Tenant, belge ve
nesil ilişkileri yazma sırasında da doğrulanmalı, mümkün olan tutarlılık kuralları
veritabanı kısıtlarıyla korunmalıdır. Tekrarlanan iş aynı parçaları çoğaltmamalıdır.

Bu, bütün uygulamanın tek tablo olması önerisi değildir. Ekip, belge, bağlantı,
iş ve indeks durumu gibi bağımsız kayıtlar kalır. Mevcut `IndexVersion` ilk aşamada
korunabilir; bütün ürün sürüm sistemini aynı anda yeniden yazmak gerekmez. Eski
statik `Chunk` modeli de incelenip tek yetkili depoya geçiş kapsamına alınmalıdır;
eski ve yeni iki aktif parça deposu bırakmak hedefi karşılamaz.

## Yenileme ve geri dönüş

1. Koleksiyonun kullanılan nesli A olsun. Sorgular A satırlarını okur.
2. Yeni indeksleme B kimliğiyle aynı tabloya yazar. A hizmet vermeye devam eder.
3. B tamamlanıp doğrulanınca, tek işlem içinde kullanılan nesil B yapılır.
4. Geri dönüş gerekiyorsa ve A hâlâ tutuluyorsa aktif seçim A'ya çevrilir.
5. Süresi dolmuş, kullanılmayan nesiller kontrollü küçük DELETE gruplarıyla temizlenir.

Dolayısıyla yeni tablo, tablo adı değiştirme veya yayınlama anında arama indeksi
oluşturma gerekmez. Hazırlık nesli kullanıcıya zorunlu bir yayınlama ritüeli olarak
sunulmak zorunda değildir. Otomatik geçiş politikasını değiştirmek ayrı ürün kararıdır.
Uzun ajanlarda her retrieval adımı seçtiği nesli kaydeder; yeniden denemelerin
gerektirdiği veriler tutulur, fakat güncel belge silme ve erişim iptalleri aşılmaz.

Bu basit model değişmeyen parçaları nesiller arasında kopyalayabilir. İleride maliyet
ölçümü gerektirirse, immutable parçalar ve sabit bir nesil-parça üyelik tablosuyla
yeniden kullanım eklenebilir. O optimizasyon dinamik tablo gerektirmez; ilk değişikliğin
zorunlu kapsamı değildir ve farklı ekipler arasında içerik paylaşımı anlamına gelmez.

## Embedding boyutları ve arama

En sade işletim modeli, kurumca seçilmiş tek embedding ailesi ve boyutudur. Çoklu
model gerekiyorsa desteklenen embedding uzayları sınırlı bir katalog olarak dağıtımda
tanımlanmalıdır. Boyutsuz `vector` sütunu farklı boyutları aynı tabloda tutabilir;
HNSW için aynı boyuta sahip satırlar üzerinde ifade/kısmi indeksler gerekir.
Bunlar her nesle değil, önceden desteklenen uzaylara göre migration ile oluşturulur.
3072 boyut gibi durumlarda halfvec ifade indeksi seçeneklerden biridir; hassasiyet
ve kalite etkisi doğrulanmalıdır. [pgvector v0.8.4 resmi belgesi](https://github.com/pgvector/pgvector/blob/v0.8.4/README.md#can-i-store-vectors-with-different-dimensions-in-the-same-column).

Tek tablo, tek HNSW indeksi ve sınırsız model/boyut desteği aynı vaat değildir.
Yeni geometri desteği kontrollü dağıtım isteyebilir. Veriyi keyfi kesme veya sıfırla
doldurma ile modelleri uyumlu göstermemeliyiz.

Paylaşılan ANN indeksinde tenant/nesil/belge filtreleri sonuç sayısını ve recall'u
etkileyebilir. Küçük yetkili veri alt kümelerinde kesin arama, büyüklerinde ölçülmüş
ANN politikası değerlendirilmeli; iterative scan tek başına kalite garantisi sayılmamalı.
[Filtreleme açıklaması](https://github.com/pgvector/pgvector/blob/v0.8.4/README.md#filtering).
Tek tablo operasyonu sadeleştirir; performansın mutlaka iyileşeceğini göstermedik.

## Uygulama sınırı ve kabul kapıları

Sonraki uygulama planı: sabit şema/indeksler ve tenant kısıtları; DAL geçişi;
mevcut parça kaynaklarının tenant/nesil bazında sayım ve içerik doğrulamasıyla aktarımı;
vektör/kelime/önizleme/kopyalama yollarının doğrulanması; yazıcıların kontrollü
kesimle taşınması; ardından eski DDL fonksiyon erişiminin kaldırılması. Geçiş boyunca
yeni yazıların kaybolmadığı kanıtlanmalı. Eski tabloların silinmesi veya yerel
veritabanının sıfırlanması bu incelemeyle yetkilendirilmiş değildir.

Gerçek PostgreSQL ve non-owner rolle çapraz ekip/belge erişim reddi, eksik scope,
tekrar deneme, eşzamanlı hazırlık/geçiş/temizlik, mevcut alıntı referansları,
rollback ve aktarım eşdeğerliği test edilmelidir. Hazırlık ve temizliğin CREATE/ALTER/
DROP kullanmadan çalıştığı ve ilişki sayısının yeni nesillerle artmadığı doğrulanmalı.
Audit olayları korunmalı; metin/vektörler loglanmamalı. Üretim ölçeğinde recall,
gecikme, veri büyüklüğü ve VACUUM etkisi henüz ölçülmemiştir.
