# AgentHub birleşik geliştirme görevi

Tarih: 2026-09-09. Güncellendi: 2026-09-11. Durum: **Implemented — güvenlik düzeltmeleri ve yerel ana ortam geçişi doğrulandı; harici ortam kabulü ayrı**.

Güncel devam noktası: R2 kaynak düzenleme/yayın uyumu, R4 yük/plan/retention ve
R5 doküman ayrıntısı/aktif yayın sunumu uygulandı. R6 gerçek sınırlı PG rolüyle
yayın, Redis background yürütme, idempotent tekrar ve MinIO önizleme geçti.
Kullanıcının seçtiği OpenAI ile gerçek belge hazırlama, shared index aktivasyonu,
Studio ayarı, tek eylemli yayın ve 1 referans parçalı yanıt yolu geçti.
Aşağıdaki güncel durum,
tarihî devam notlarındaki eski “açık” ifadelerin önüne geçer. Bütün paket henüz
Completed değildir; geçen test sayısı bitiş yüzdesi olarak kullanılmaz.


### GitHub teslimi

Kullanıcı uygulama projesinin `https://github.com/Osman6420/agenthub` reposuna
push edilmesini istedi. Hedef main yalnız bağımsız başlangıç commit'i içeriyor;
mevcut geçmişi değiştirmeden `codex/agenthub-security-rollout` dalına teslim edilir.
Uygulama kodu, migration, test ve dokümanlar dahil; yerel yedek/credential, outputs,
yüklenmiş Test Datası PDF'leri ve bağımsız README2 teslim dışında. Güncel staged
snapshot secret taraması 0 bulgu; geçmiş taramasındaki üç belge eşleşmesi daha önce
incelenen yanlış pozitiflerdir. Önceki doğrulamalar kullanıldı, testler tekrarlanmadı.

### Güvenlik ve yerel geçiş kapanışı — doğrulandı

Kullanıcının açık onayıyla dört Python güvenlik sürümü ve Vitest 4.1.11/nanoid
3.3.18 güncellemeleri uygulandı. Docker ve CI, requirements.lock kısıtlarıyla
kurulur; yeni application image'daki kurulu paketlerde lock sapması yok ve
`pip check` temiz. `.dockerignore` yerel `.tmp` kanıt/yedeklerini build context'inden
çıkarır. Üretim API/yetki sözleşmesi, audit ve veri erişimi değiştirilmedi.

| Kontrol | Sonuç / kanıt |
| --- | --- |
| Python bağımlılık taraması | 0 bilinen açık; `.tmp/security-fixed-audit.json` |
| Frontend tam bağımlılık taraması | 0 açık; `.tmp/security-fixed-npm-audit.json` |
| Docker frontend typecheck/test/build | 13 dosya, 59 test geçti; `.tmp/security-build.log` |
| API/MCP/revision/console testi | 58 geçti, 4 PostgreSQL-only atlandı; `.tmp/security-upgrade-tests.xml` |
| PostgreSQL revision/MCP yetki testleri | 26 geçti, atlama yok; `.tmp/security-upgrade-pg.xml` |
| Django check / migration drift / pip check | Temiz; yeni image kullanıldı |
| Nihai diff | Whitespace kontrolü temiz; dependency/build/doküman kapsamı incelendi |
| Güncel image browser | Manager #7 yayını ve active-generation etiketi görünür; atanılmamış senaryo 404; ana 8000 giriş ekranı çalışıyor |

Yerel ana DB `agenthub` için custom-format yedek:
`.tmp/agenthub-pre-security-20260911.dump` (özel yerel dosya, Git/build dışında).
SHA256 `28511758411AFD17A4AEE91ACB76283AFD454BA944FBDEE0CCF6B4E28BB40AB1`.
Yedek `agenthub_rollout_20260911` ayrı DB'sine pg_restore --exit-on-error ile geri
yüklendi; tüm migration'lar önce bu kopyada geçti. Mevcut 99 tablonun hiçbirinde
kayıt sayısı azalmadı. Bu satır sayısı kanıtıdır, tüm içeriklerin hash karşılaştırması
değildir. `.tmp/security-rehearsal-counts.json` ve rehearsal migration log'u mevcut.

Ardından canonical `scripts/local-stack.ps1 -Action Update` çalıştı. Ana DB tüm
güncel migration'ları aldı; `migrate --check` geçti. Ana ortamda da aynı eski
99 tabloda kayıt sayısı azalmadı (`.tmp/security-main-counts.json`). Reset, tablo
silme, seed veya kaynak içerik taşıma yapılmadı. MinIO volume'u korundu ve healthy.
Web, runtime/ingestion/eval worker ve beat çalışıyor; liveness 200 ve
`check_ingestion_preflight --require-worker`: contract 12, compatible_worker=yes.
Kullanıcı ana konsolu: `http://127.0.0.1:8000/console/`.

Geri dönüş: yedek ayrıca geri yükleme provasıyla doğrulandı; mevcut verinin üstüne
otomatik restore yapılmaz. Sorunda worker/beat durdurulup yeni yazılar korunarak
forward fix tercih edilir. Eski uyumlu acceptance image elde tutuldu; eski binary'nin
yeni veri sözleşmelerine körlemesine geri alınması güvenli kabul edilmez.

Kalan sınırlar: bu kapanış **yerel ana ortama** aittir; uzak üretim/OpenShift
geçişi yapılmadı. Mevcut legacy indexler ve runtime layout tercihi korundu; toplu
shared-only backfill veya eski vektör silme uygulanmadı. Yerel geliştirme Compose'u
mevcut owner DB bağlantısını korur; üretimde restricted-role provisioning şartı
sürer ve bu rolün davranışı ayrı PostgreSQL/kabul ortamında test edildi. Harici
REST/Confluence/MCP sunucularına canlı uçtan uca kabul yapılmış sayılmaz. Bütün
paket için bu sınırlar nedeniyle global Completed/arşiv uygulanmadı; bağımlılık
onayı veya yerel geçiş artık açık iş değildir.

### Önceki kapanış planı (uygulandı)


Kullanıcı güvenlik ve geçiş kapanışını açıkça onayladı. Dört Python düzeltmesi ve
frontend dev bağımlılığı düzeltmeleri uygulanacak. Docker/CI kurulumları mevcut
lock kısıtlarını kullanacak; aksi halde güncelleme yeniden sürüm sapmasına dönüşür.
Doğrulama: bağımlılık taramaları, frontend test/build, API/security ve migration
kontrolleri. Yerel ana DB önce yedeklenecek; migration planı incelenip veriler
korunarak ilerletilecek. Reset/silme yok; dış production erişimi yok. Ana veri
geçişinden önce restore edilebilir yedek ve eski image geri dönüş referansı şart.
Harici sağlayıcı eksikleri doğrulanmadan canlı kabul tamamlandı denmeyecek.

### 2026-09-11 — bağımsız taramalar ve somut düzeltme kapsamı

Bu kayıt önceki “tarayıcı çalıştırılmadı” notlarının önüne geçer. Mevcut kabul
ortamının beş uygulama rolü çalışıyor; PostgreSQL/Redis/MinIO healthy ve 8110
liveness 200. Önceden geçen uygulama testleri yeniden çalıştırılmadı.

- `pip-audit -r requirements.lock --no-deps --disable-pip --format json`:
  dört pakette 14 ham kayıt, tekrarlar ayrıldığında 9 benzersiz advisory.
  Kanıt: `.tmp/final-pip-audit.json`. Bu tarama başarısız güvenlik kapısıdır;
  bulguların tamamının uygulamada istismar edilebilir olduğu iddia edilmez.
- `npm --prefix frontend audit --json`: 3 etkilenen paket (1 high, 2 moderate).
  `npm --prefix frontend audit --omit=dev --json`: 0 bulgu. Etkilenenler mevcut
  geliştirme araçlarıdır: vitest, @vitest/mocker ve nanoid.
- Gitleaks 8.24.3, `git ls-files --cached --others --exclude-standard` ile alınan
  1479 dosyalık güncel snapshot üzerinde, yüzde 100 redaction ile çalıştı.
  `.tmp/final-gitleaks-scoped.json`: 3 generic-api-key eşleşmesi; üçü de eski
  görev belgelerindeki doğal dil cümleleri, satır incelemesinde yanlış pozitif.
  Gerçek credential bulunmadı. Otomatik exit 1 gizlenmedi, allowlist eklenmedi.
  Kapsam güncel takip edilen/edilmeyen teslim dosyalarıdır; Git geçmişi ve ignored
  yerel secret/runtime dosyaları bu taramanın kanıtı değildir. İlk tüm klasör
  taraması durduruldu, onun sonucu kullanılmadı.

Üretim bağımlılığı değişikliği için hazırlanmış öneri (henüz uygulanmadı):

| Paket | Mevcut lock | Tarayıcının düzeltme sürümü |
| --- | --- | --- |
| Django | 5.2.16 | 5.2.17 |
| djangorestframework | 3.17.1 | 3.17.2 |
| cryptography | 49.0.0 | 50.0.0 |
| sqlparse | 0.5.5 | 0.6.0 |
| vitest / @vitest/mocker (dev) | 4.1.10 | 4.1.11 |
| nanoid (dev, dolaylı) | 3.3.16 | 3.3.18 veya uyumlu düzeltme |

Django bulgusu GeoDjango, cryptography bulgusu PKCS7 decrypt, sqlparse bulguları
saldırgan SQL ayrıştırma/formatlama yollarıyla ilgilidir; uygulama kaynaklarında
bu doğrudan kullanım noktaları bulunmadı. DRF `request.data` gateway/MCP'de
kullanılıyor; request parsing uyarıları bu yüzden özellikle değerlendirilmelidir.
Bu inceleme bulguları düşürmez veya güvenlik kontrolünü geçer saymaz.

Aday Python lock yalnız `.tmp/proposed-security-requirements.txt` içine hazırlandı.
Aday lock için izole image içinde `pip install --dry-run --ignore-installed`
başarılı: dört hedef sürüm birlikte çözümlendi; hiçbir paket kurulmadı.
Kanıt `.tmp/proposed-security-resolution.json`. Bu çözümleme kanıtıdır,
çalışma zamanı testi değildir. Uygulama lock/manifest dosyaları değişmedi. Onay sonrası bu dört sürümün resolver
uyumu, request boyutu/parsing, API yetkilendirme ve ilgili migration/system check
kontrolleri ile tarama tekrarları uygulanacak; yeni özellik kapsamı açılmayacak.
Geri dönüş eski lock ve image'dır; veri migration'ı gerektiren bir öneri değildir.
Root AGENTS.md Change boundaries açık onayı nedeniyle üretim bağımlılığı
uygulaması bekliyor. Ana DB migration/cutover ve harici connector sağlayıcılarının
canlı kabulü ayrıca açık; yerel OpenAI kabulü bunların yerine geçirilmez.

### Güncel uygulama ve doğrulama

OpenAI seçimi kullanıcı tarafından da doğrulandı. Gerçek worker 1 belge/1 parçayı
hazırladı, UI'dan index v1 active oldu; yeni özel Document Answer senaryosu Studio'da
model/prompt/retrieval ayarıyla doğrulandı ve tek eylemle #7 yayımlandı. Gerçek soru
1 referans parçasından yanıtlandı. Canlı sunum bulgusu: active-generation yayını
legacy set-version pini olmadığı için yanlışlıkla “seti içermiyor” gösteriyordu.
Yayın manifestindeki logical set kapsamı ayrı etiketle gösterilir; eski pin görünümü
korundu. `.tmp/active-generation-presentation.xml`: 1 geçti (37.27 s); sonraki
bağlanan setin yanlışlıkla yayında gösterilmediği de doğrulandı. Son browser'da yeni
etiket var, yanlış “seti içermiyor” yok. Serving kararı veya snapshot değişmedi.

R5/R6 canlı belge lifecycle bulgusu: set yöneticisi senaryo bağlama listesinden
atanmadığı senaryoları görebiliyor, set tarafındaki bind/unbind endpoint'i yalnız
set yönetimini kontrol ediyordu. Bağ değişikliği senaryo yapılandırması olduğundan
exact SCENARIO_EDIT de zorunlu; adaylar aynı kapalı yetki sorgusundan gelir.
Mevcut bağların ayrıntı bağlantısı okuma yetkisiyle, kaldırma eylemi iki yetkiyle
gösterilir. Veri sahibinin retrieve grant iptali ayrı kalır ve daraltılmaz.
`.tmp/document-binding-authority-pg.xml`: 6 geçti (43.17 s), doğrudan ret/audit,
çift yetkiyle bind/unbind, yetki süresi dolunca buton/POST kapanması ve cross-tenant
koruması dahil. Son browser'da atanılmamış Agent Loop/Document Answer seçenekleri yok.

Sağlayıcı devamı: kullanıcıya seçenek sunulduktan sonra yanıt gelmedi; mevcut
OpenAI profilleri ve kullanılabilir yerel credential ile ilerleme varsayımı açıklandı.
Yalnız ayrı acceptance DB'de platform görevlisi ve bounded OpenAI model/embedding
profili mevcut servislerle oluşturuldu; embedding grant yalnız demo sentetik tenant'a.
Kısa gerçek model ve 1×1536 embedding çağrısı geçti. İlk SECRET_UNAVAILABLE, izole
Compose'un boş environment değerinin yerel .env yüklemesini engellemesiydi; sadece
ignored test settings, mevcut dotenv okuyucusuyla credential'ı süreç belleğinde
kullanır. Değer dosyaya/DB'ye/loga kopyalanmadı. Bağımlı belge lifecycle kabulü geçti.

Bağımlılık kilidi kontrolü: mevcut host ve eski application image'da
langgraph-checkpoint 4.2.0 (lock 4.1.1), langchain-core 1.6.1 (lock 1.4.9).
Langgraph 1.2.9 eşleşiyor; pip check ayrı olarak temiz. Lock/pyproject/Dockerfile bu
görevde değiştirilmedi. Bu baseline farkı geçer sayılmadı; üretim bağımlılığı/pin
güncellemesi yapılmadan ayrı değerlendirilmelidir. Ayrı local acceptance image
`agenthub-acceptance-locked:20260911`, mevcut lock'taki iki sürüme hizalandı;
pip check ve CI'nın üç paket lock kontrolü geçti. `.tmp/locked-revision-runtime.xml`:
12 geçti/2 PG-only atlandı (39.90 s). Aynı #7 yayını bu image üzerinde tekrar gerçek
OpenAI yanıtı ve 1 referans parçası üretti; browser warn/error boş. Ana host/image,
production dependency dosyaları ve pinler değiştirilmedi. Geniş host suite kanıtı,
kilitli runtime kontrolünden ayrı tutulur.

R6 background claim artık yalnız Run'ı kilitler; immutable join kayıtlarının yazma
iznini istemez. `.tmp/background-claim-privilege-pg.xml`: 10 geçti (40.82 s),
claim/replay/rekabet/süre/audit ve non-owner readonly workflow sınırı dahil.
Gerçek HTTP kabulü 202, Redis worker terminal durumu completed ve idempotent tekrar
aynı Run: `3f999794-ed1a-428f-9184-0e66967753aa`. Önceki başarısız deneme queued
kaydı yalnız sentetik ortamda tanı kanıtı olarak kaldı; başarılı sayılmadı.
R5 metadata görüntüleyicisine açamayacağı belge bağlantısı gösterilmesi düzeltildi.
Sayfalı üyelerde mevcut scoped_documents kararı kullanılır; yetkisiz kullanıcı
başlığı metin görür. `.tmp/document-link-scope.xml`: 1 geçti (37.24 s).
Gerçek browser'da viewer bağlantıyı görmedi, doğrudan adres 404; manager aynı belge
ve MinIO güvenli önizlemesini açtı. Sunucu erişim kararı genişlemedi.

R5 canlı konsol bulgusu: legacy aktif release'i olup editlenebilir draft'ı olmayan
senaryo, ana ekranda ilk kurulum adımlarıyla açılıyor ve canlı yayın bilgisi
Gelişmiş altında kalıyordu. Ana ekrana mevcut yayın/çağrı durumu eklendi;
sonraki yayın hazırlıkları ayrı disclosure altında. İlk kurulumun dört
adımı, URL'ler ve bütün yetki/serving kararları korundu. Bu bir sunum düzeltmesidir.
R6 için ayrı `agenthub-acceptance-20260911` Compose projesi, yeni PG/MinIO volume'ları
ve yalnız localhost:8110 oluşturuldu. Ana veriler taşınmadı/resetlenmedi.
Güncel migration graph, sınırlı app rolü (`--shared-vectors-only`, 78 tablo),
pgvector 0.8.4 ve contract 12 uyumlu gerçek Redis/worker heartbeat doğrulandı.
Tüm deneme verileri sentetik; dış model/embedding yalnız kullanıcı seçimiyle OpenAI.
R6 gerçek sınırlı rol bulgusu: snapshot capture, immutable WorkflowVersion için
SELECT FOR UPDATE istediğinden canonical SELECT/INSERT-only app rolünde yayın
500 dönüyordu. Mutable org/scenario/release kilitleri korundu, immutable workflow
yalnız exact scope ile okunur; runtime UPDATE izni genişlemedi. Gerçek browser
yayını #6 başarılı. `.tmp/revision-capture-final-pg.xml`: 14 geçti (41.38 s).
SQL guard da aynı immutable workflow üzerinde SHARE kilidi kullanıyor. Bu yarış
koruması kaldırılmayacak: eklemeli releases 0008 yalnız statik, exact scope/snapshot
doğrulayan trigger'ı owner yetkisinde çalıştırır; search_path yalnız pg_catalog,
PUBLIC doğrudan EXECUTE kapalıdır. Trigger başka satır yazmaz; INSERT üzerindeki
FORCE RLS ve tüm kaynak/tenant/checksum doğrulamaları aynen korunur. Uygulama rolüne
workflow UPDATE verilmez. Geri alma fonksiyonun eski çağıran yetkisini geri getirir;
veri silmez. Önce çalışan invoker scope guard, tenant ve exact workflow lineage'ını
kontrol eder; kapsam dışı satıra elevated kilit alınamaz. Eksik/başka tenant scope ve
doğrudan EXECUTE reddi testlendi. İzole, dolu acceptance DB'de forward/reverse/forward
geçti; ana DB'ye uygulanmadı. Üretim rollout'unda dar definer sınırı incelenmelidir.

Son geniş kontrol: `.tmp/agenthub-consolidated-final-sqlite.xml` 1865 geçti,
335 atlandı, 1 eski yetki beklentisi başarısızdı (618.54 s). İlgili test, set
yöneticisinin ayrıca senaryo yetkisine ihtiyaç duyduğunu önce ret sonra açık atama
ile doğrulayacak şekilde düzeltildi. `.tmp/final-console-findings.xml` bu test ve
dört senaryo sunum kontrolüyle 5 geçti (39.79 s). Tam suite tekrar çalıştırılmadı;
ilk kırmızı sonuç saklıdır. Frontend typecheck/59 test/build, Django check,
migration drift, pip check ve ruff temiz. Full mypy'daki iki test-fixture tipi
düzeltildi; değişen views/test/revision/claim dosyalarının Linux mypy kontrolleri
temiz. Ayrı dependency/secret scanner çalıştırılmadı.

R6 browser kanıtı: project-admin özel senaryo oluşturdu, atanmış manager yayınladı;
viewer yalnız atanmış legacy senaryoyu gördü, Studio/yayın kapalıydı. Atanmamış özel
senaryo, aynı tenant özel set ve başka tenant set doğrudan adresleri içerik sızdırmadan
404 verdi. Senaryo 390/900 genişliklerinde taşmadı; mobil menü Escape ile kapanıp
odağı menüye taşıdı; bölüm bağlantısı kapalı Gelişmiş'i açtı. Doküman 390/900/1440
kanıtı aşağıda. Son başarılı önizlemede browser warn/error boş. Yayın tek ana eylem;
liste→senaryo→yayın 2, set→belge→önizleme 2 tıklama. İlk kurulumda 4 adım korunur.

- **R2:** REST/MCP/Confluence kaynak revision'ı mevcut periyot, hazırlama
  fingerprint'i ve onaylı otomatik yayın hedeflerini korur. Aday yalnız exact
  SourceJob üzerinden değerlendirilir; normal serving güncel olmayan kaynağı
  reddeder. Final CAS, canlı yetki ve audit kontrolünden sonra kaynak lineage,
  indeks, hedef yayınlar ve schedule aynı transaction'da değişir. Başarısızlık
  önceki canlı durumu korur; tekrar giriş tamamlanmış değerlendirmeyi kullanır.
  Eklemeli 0041 revision schedule şemasını genişletir; immutable geçmiş korunur.
  Kanıt: `.tmp/revision-publication-pg.xml` 8; schema PG 6; audit PG 4;
  `.tmp/revision-publication-confluence-pg.xml` 6 geçti (148.11 s). Üç adapter,
  legacy/active-generation ve başarı/evaluation-fail/audit-fail kapsandı.
  İlgili 11 kaynak dosyasında Linux mypy ve ruff temiz.
- **R4:** 0040 parent ve 0042 selected-set/question-evaluation referansları
  retirement ile aynı satır kilidinde sıralanır; emekli/tenant dışı/başka set
  sürümüne ait nesil reddedilir. Değerlendirme stale caller nesnesi yerine kilitli
  güncel index'i okur. `.tmp/shared-retention-race-pg.xml` 7 geçti;
  `.tmp/retained-selection-final-pg.xml` 6 geçti (106.82 s): iki gerçek bağlantı,
  iki işlem sırası, stale admission ve referansı başka set sürümüne taşıma reddi.
- **R4 kapasite/izin kesimi:** ANN yolu transaction-local custom plan kullanır.
  Gerçek PREPARE/EXECUTE altında 2200 seçili 64d vektör, her oturum tercihinde
  4300 eşzamanlı başka-generation yazımı: recall@10 1.0; p50 7.90/8.00 ms;
  p95 32.96/30.15 ms; iki tercihte de 43 custom/0 generic ve shared ANN index.
  `.tmp/shared-vector-cutover-pg.xml` 2 geçti (105.27 s); ikinci test doğrudan
  ve NOINHERIT/SET ROLE DDL ile schema CREATE iznini algılama/iptal durumudur.
  Grant template `legacy_vector_ddl=false` ve readiness `--shared-vectors-only`
  seçeneği eklendi; gerçek uygulama rolünde revoke yapılmadı. Operasyon koşulları
  [shared-vector-storage](../../operations/shared-vector-storage.md) belgesinde.
  Ölçümler sentetik yerel örnektir, üretim kapasitesi garantisi değildir.
- **R5:** Seçili sürümde 25 belge/10 indeks, diğer sürümlerde 20 kayıt sayfalama;
  toplam ilerleme aggregate üzerinden hesaplanır. Mevcut belge araması en fazla
  100 sonuç ve CONTENT_READER/MANAGER kapsamı kullanır. Liste ve doğrudan POST
  başka özel setin okunamayan belgesini kopyalayamaz; ret generic ve audited.
  `.tmp/document-detail-pagination.xml` 13 geçti (91.79 s). İlgili views için
  Linux mypy temiz. Son sınır/boş arama kontrolleri: `.tmp/document-detail-final.xml`, 2 geçti (109.05 s).
  Güncel 8109 fixture'da arama, boş sonuç ve toplam sayımı gözlendi;
  390/900/1440 genişliklerinde yatay taşma yok; Tab ile Ara düğmesinde görünür
  odak var; tarayıcı uyarı/hata kaydı boş. Tam rol/provider/worker gate değildir.

### Son inceleme ve kalan kabul sınırı

Bu devamın diff incelemesi tek ana ajan tarafından mimari, güvenlik ve operasyon
açısından yapıldı: join kilidi yalnız otorite Run satırına daraltıldı; snapshot
kilidi SQL guard'da korundu, scope guard önce çalışır, broad UPDATE/EXECUTE eklenmedi.
Üye bağlantısı scope kararıyla eşleşir; sayfalama toplamları ve doğrudan ret korunur.
Audit, retry/idempotency, tenant ve immutable geçmiş kontrolleri gevşetilmedi.
Yeni bağımlılık, API sözleşmesi, ana veri taşıma/silme veya secret/log payload yok.

Ana yerel katalog salt okunur incelendi; kullanıcı OpenAI seçti. İzole acceptance
DB'de aynı endpoint/model ailesini kullanan sınırlı profiller servis üzerinden
oluşturuldu; kaynak verileri veya credential değerleri DB'ye kopyalanmadı.
Hazırlama→indeks→retrieval→yanıt yolu gerçek sağlayıcı/worker üzerinde geçti.
Harici REST/Confluence/MCP sunucularının tamamıyla canlı operasyon bu son OpenAI
denemesinin kapsamı değildir; adapter/SQL/rol matrisi önceki hedefli kanıtlardadır.
Bağımsız secret/dependency tarayıcı sonucu ve rollout insan incelemesi yok; bu
sınırlar nedeniyle bütün paket için Verified/Completed veya görev arşivi uygulanmadı.
Üretim migration, izin kesimi ve 90 günlük gerçek veri purge ayrı operasyon kararıdır.

### Sınırlar, riskler ve son ortam

Gerçek veri temizliği, ana DB migration'ı, uygulama rolünde izin iptali veya
üretim kesimi yapılmadı. 90 günlük retention varsayımı hâlâ kullanıcı tercihine
açık; otomatik sweep yok. Yalnız owner tarafından exact kimliklerle ve preview
sonrası çalıştırılır. Metadata/release/audit/geçmiş referanslar korunur.
Yeni üretim bağımlılığı yok; güvenlik veya test kontrolü gevşetilmedi.
Runtime schema ve grant template değişiklikleri rollout öncesi operator review
ister. Yeni guard'lar disposable PG test DB'sine ve ayrı 8110 acceptance DB'ye
uygulandı; 8109 sentetik SQLite fixture da ana DB değildir. Son kontrolde ayrı
acceptance web, Redis, PG, MinIO ve üç worker/beat çalışıyor; preflight contract 12
uyumlu. Ana Compose PG healthy; ana web başlatılmadı. Yeniden başlatmadan önce manual guide §0 uyarınca canlı
sorgula. Commit/push yok. Django check, migration drift ve pip check temiz.

## 1. Yetkilendirilmiş kapsam ve tek kaynak

Kullanıcı bu konuşmada yedi tasarım grubunun geliştirilmesini, önce tek görev
dosyasında birleştirilmesini istedi. Bu dosya bütün uygulamanın tek aktif görev
planı, risk modeli ve doğrulama kaydıdır. Ayrı yedi uygulama işi yürütülmez.
Kullanıcının tek dosya tercihi nedeniyle normal task şablonundaki threat-model
ve verification kayıtları bu dosyanın ilgili bölümlerindedir.

Kaynak gruplar: authorization-simplification, console-navigation-2026-09-08,
console-ui-redesign, rag-architecture-simplification, rest-data-source-wizard,
scenario-detail-ux-simplification, shared-vector-storage. Eski paket
[kaynak arşivinde](../../planning/archive/agenthub-simplification-source-briefs-2026-09-09/README.md)
tarihsel referans olarak korunur. Eski metinlerdeki çelişen emirler bu planın
yerine geçmez; eski test kayıtları yeni geliştirme kanıtı değildir.

Bağlayıcı kaynaklar: [AGENTS.md](../../../AGENTS.md),
[mühendislik](../../ai/engineering-rules.md), [güvenlik](../../ai/security-rules.md),
[test](../../ai/testing-rules.md), [observability](../../ai/observability-rules.md),
[Definition of Done](../../ai/definition-of-done.md),
[manuel test rehberi](../../manual-testing-guide.md),
[Compose](../../../deploy/compose/docker-compose.yml).

Tek ana ajan planlama, uygulama, inceleme ve testleri yapar; alt ajan yok.
Mevcut yerel değişiklikler korunur. Yeni üretim bağımlılığı, authentication,
yeni egress/secret mekanizması, üretim deploy/erişimi, reset veya yıkıcı temizlik
bu onayın varsayılan kapsamı değildir. Yetki sadeleştirmesi ve veri-koruyan
eklemeli mimari geçiş bu görev kapsamında onaylıdır; rutin aşamalar için tekrar
onay istenmez. Eski tabloları düşürme için envanter/geri dönüş hazırlandıktan
sonra ayrıca somut yetkilendirme gerekir. Başarısız testi/kontrolü gevşetme.

## 2. Hedef ve uzlaştırılmış kararlar

Ürün hedefi: kaynağı bağla → veriyi hazırla → senaryoyu dene → yayınla.
Kullanıcı teknik artifact, set-version, manifest ve indeks kimliği yönetmek
zorunda kalmaz; teşhis ve geçmiş yetkili ayrıntılarda erişilebilir kalır.

| Konu | Bu görevde esas alınan karar |
| --- | --- |
| Mimari | RAG hedefi: tek tutarlı senaryo yayın snapshot'ı, ayrı veri nesli, ortak bağlantı/iş modeli. |
| Depolama | shared-vector-storage, RAG'ın ilk depolama dilimidir; ikinci DAL veya migration yok. |
| Yetki | Yeni rol/devralma matrisi esas; eski UI'daki rol varsayımları buna uyarlanır. |
| Arayüz | console-ui-redesign çatı; senaryo, REST sihirbazı ve gezinme onun bölümleridir. |
| Veri yenileme | Yeni hedef senaryolar kullanılabilir aktif veri neslini takip eder. Retry aynı adımın seçimini korur; mevcut legacy pin'ler açık geçiş yapılmadan değişmez. |
| Yayın | Tek kullanıcı eylemi mevcut doğrulama, değerlendirme, yetki ve audit sınırlarını koordine eder; başarısızlık canlı revision'ı değiştirmez. |
| Yönetici | Kullanıcının açık seçimi: proje/senaryo yöneticisi düzenleme + yayın + operasyonu birlikte yönetir. |
| Özel senaryo | Doğrudan atama; proje yöneticisi erişim idaresi yapabilir ve açık/audited atamayla kendisini ekleyebilir. Mutlak gizlilik vaadi verilmez. |
| Doküman ve onay | Yönetici rolünden ham doküman okuma veya tool onayı türemez. |
| Ortak istemci verisi | Açık, veri yöneticisince verilen ortak kullanım izniyle opsiyonel mod; eski kayıtlar consumer/set kesişimiyle başlar. |
| REST aktörleri | Platform bağlantı/grant idaresi ile set içeriği yönetimi ayrı. İki yetkisi olan kullanıcı tek akışı bitirir; diğerine yetkili devretme gösterilir. |
| Sayım | 44 uygulama/54 toplam tablo tahmini kota değildir. Davranış, FK/grant ve katalog gerekleri nedeniyle artırılabilir. |
| Geri dönüş | Yapılandırma rollback'i ile veri nesli rollback'i ayrıdır; canlı izin iptali/silme geçmişten geri açılamaz. |

## 3. Sıra ve kabul matrisi

Her dilim en küçük çalışan bütün olarak uygulanır; değişen davranışla birlikte
anlamlı testler yazılır. Aşağıdaki M matrisi ilk dilimlerin tarihsel kaydıdır;
güncel uygulama ve kabul durumu üstteki kayıt ve R teslim matrisindedir.

| Dilim | Kapsam / kabul | Implemented | Verified |
| --- | --- | --- | --- |
| M0 | Tek görev, kaynak arşivi, çelişki çözümü, baseline ve geçiş envanteri | Kısmi | Hayır |
| M1 | MCP ingestion durumunun exact izinli kaynaklarla sınırlandırılması | Evet | Otomatik testler evet; bütünleşik browser gate M8 |
| M2 | Ortak vektör modeli, sabit indeksler, bütün DAL yolları ve aktarım | Kısmi: eklemeli şema, DAL ve staged build | İlk şema/DAL dilimi PG testli; backfill/retention/cutover açık |
| M3 | Birleşik roller/devralma, erişim geçişi ve ortak eylem kararları | Kısmi: roller, devralma, önizleme, oluşturma, ortak veri, consumer paketleri ve scenario actions | İlgili PG ve UI testleri geçti; kapsamın bütünleşik kabulü açık |
| M4 | Tek ScenarioRevision, runtime snapshot ve bağımsız veri tazeliği | Kısmi: snapshot, runtime, kalıcı adım/agent/branch veri seçimi, tek eylemli yayın ve evaluation resume | PG snapshot/ACL/resume ve atomik yayın testli; bütünleşik kabul ve varsayılan geçiş açık |
| M5 | Connection/Source/Job/Outbox; REST/MCP ingestion ve uyumluluk | Kısmi: yedi tür Connection, ortak Job/Outbox, REST/Confluence/MCP adapter ve source revision, exact stage-only ve elle hazırlama bağı; MCP periyodik yenileme | Üç adapter snapshot/hazırlama/revision ve typed Connection PG testli; promotion ve rollout açık |
| M6 | REST sihirbazı, mapping, güncelleme ve ilerleme | Kısmi: dört adım, typed input, sentetik preview, atomik/idempotent manuel/periyodik kayıt, bounded test, kalıcı izin-bekleme taslağı, mevcut/yeni set girişi, ilk hazırlama ayarları ve kuruluma kayıpsız dönüş | PG ve izole browser dilimleri testli; gerçek provider, revision edit/cutover ve tam gate açık |
| M7 | Ortak UI, doküman ve senaryo deneyimi; gezinmenin korunması | Kısmi: kaynak listesi/ayrıntısı, Türkçe durumlar, son başarı/hata, readiness, sayfalama ve gelişmiş ayrıntılar | Kaynak/REST/MCP PG kontrolleri ve dar browser dilimi; ortak konsol/senaryo kabulü açık |
| M8 | Entegre migration/rollback, PostgreSQL, performans, browser ve doküman kapanışı | Hayır | Hayır |

### Kalan teslimler — 2026-09-10 durum düzeltmesi

Kullanıcı toplam sürenin uzadığını belirtti. İlerleme bundan sonra aşağıdaki mevcut
kapsam teslimleri üzerinden raporlanır; geçen test sayısı tüm paketin bitiş yüzdesi
olarak kullanılmaz. Ara altyapı diliminin testli olması ürün kabulünün tamamlandığı
anlamına gelmez. Toplam bitiş saati henüz güvenilir biçimde hesaplanamıyor.

| Sıra | Somut teslim | Kapanış ölçütü | Durum |
| --- | --- | --- | --- |
| R1 | Kaynaktan elle hazırlama | REST/Confluence/MCP için exact build bağı, snapshot değişmezliği, rol/CSRF/concurrency ve browser kanıtı | Implemented; PG 194 + düzeltilmiş son 39 test geçti, dar browser kanıtı tamam; tam provider/runtime kabulü R6 |
| R2 | Kaynak kurulum ve yenileme akışının kalanları | Yeni setin ilk hazırlama ayarları, config revision edit/lineage geçişi, MCP periyodik yenileme, legacy promotion ile ortak hazırlama/activation devamı ve kalan typed bağlantı eşlemeleri | İlk hazırlama, üç adapter config revision, yedi tür Connection ve ortak otomatik publication uygulandı. REST/MCP/Confluence iki runtime sözleşmesinde PG testli; kaynak düzenleme uyumu tamam, gerçek sağlayıcı kabulü R6 |
| R3 | Senaryoyu tek eylemle yayınlama | Revision konsolu, evaluation işlem sınırı, runtime geçiş uyumluluğu ve başarısızlıkta canlı yayının korunması; birleşik rol/devralma matrisiyle kabul | Tek eylemli yayın, exact resume, geçmiş, prepared evaluation, ortak source publication, yeni konsol varsayılanı ve mevcut senaryo açık geçişi uygulandı. Doğrudan PG, gerçek sınırlı rol browser yayını ve background yürütme kanıtı var; sağlayıcı kabulü R6, üretim rollout kapsam dışı |
| R4 | Veri saklama ve geçiş kabulü | Build altında okuma, generic/custom plan ve kapasite ölçümleri; referans koruyan retention/purge, expired kurulum payload saklama politikası, veri-koruyan geçiş/geri dönüş kanıtı | Depolama/backfill, expired REST payload ve owner-only referans koruyan shared retention uygulandı/testli. 90 gün varsayımı kullanıcıya bildirildi; concurrent build, custom/generic plan ve readonly rol ölçümleri geçti; gerçek veri kesimi kapsam dışı |
| R5 | Ortak konsolun tamamlanması | Senaryo/doküman ekranlarının ana akışa uyarlanması, büyük listeler/arama, hata/boş durumları, klavye ve mobil kullanım kabulü | Kaynak/REST, yayın ve geçiş ekranları; senaryo/doküman listesi arama-sayfalama uygulandı. Aktif yayın sunumu, detay sayfalama, izinli belge bağlantıları tamamlandı; değişen ekranlarda mobil/klavye ve rol kabulü geçti; sağlayıcı bağımlı yollar R6 |
| R6 | Bütünleşik son kabul ve kapanış | Güncel sürümün tüm kontrolleri, migration/rollback, gerçek yerel runtime ve rol/tenant browser matrisi, nihai diff incelemesi, doküman/ADR ve görev arşivi | Yerel PG/Redis/MinIO/OpenAI hazırlama, yayın ve yanıt; locked runtime, rol/scope browser ve final diff kanıtı tamam. Harici connector sunucuları, bağımsız tarayıcılar ve rollout insan incelemesi sınırları kayıtlı; global Verified/Completed ve arşiv uygulanmadı. |

Canlı veri silme veya üretim kesimi, R4'teki kod/deney kanıtından ayrı olarak somut
envanter ve geri dönüş hazırlanıp yetkilendirildiğinde yapılır. Mevcut görev bu
işlemlerin kendiliğinden çalıştırılması anlamına gelmez.

M1 bağımsız mevcut kapsam kusurudur; kapsamlı dönüşümden önce giderilir.
M3 ilk eklemeli dilimi: mevcut atama servisiyle organizasyon yöneticisinin
açıkça atayabildiği exact Senaryo yöneticisi rolü; düzenleme/test/yayın/operasyon
birleşir, içerik ve approver yetkisi eklenmez. Eski kayıtları dönüştürmez.
Proje devralması, erişim idaresi ve geçiş önizlemesi sonraki M3 dilimleridir.
Bu dilimler artık uygulandı; ayrıntılı kanıt bölüm 11'de. M3'ün ortak consumer
veri izni/paketleri ve tüm eylem/readiness kararlarının bütünleşik kabulü açık.
M2–M5 şema ve servis işleri aynı hedefe göre ilerler; M6/M7 eski model
zincirlerine göre tamamlanıp tekrar yazılmaz. Her dilim desteklenen ara sürümde
çalışır; geçiş uyumluluğu tamamlanmadan varsayılan veri/politika kesimi yapılmaz.

## 4. Depolama sözleşmesi — M2

İlk migration'ın kapalı geometri listesi: cosine vector(64/768/1536),
halfvec(3072/4000). İlk dört geometri canlı profil envanterini; 4000 ADR-0017
sözleşmesini kapsar. Başka geometri sessiz fallback/DDL yerine erken ret verir.
Test için özel yeni üretim geometrisi açılmaz. Legacy store'lar aktarılana
kadar kendi eski geometri ve veri kimlikleriyle okunur.

M2 ölçüm eşiği, deneyi görmeden belirlenmiştir: her tenant/nesil alt kümesinde
exact cosine top-10 referansına göre recall@10 >= 0.95; sabit yerel 20.000 chunk
workload'unda p50 <= 80 ms, p95 <= 200 ms ve aynı makinede legacy baseline'a
göre p95 <= 1.5 kat. ACL/tenant sızıntısı 0; boş/yarım nesil yanlış sunumu 0;
backfill kimlik/sayı/checksum ve halfvec taşınmış değerleri birebir eşleşmeli.
Build altında p95 <= 400 ms. Ölçüm küçük sentetik ortam kabulüdür;
production SLO/kapsitesi anlamına gelmez. Generic/custom plan ve scan bütçeleri
ayrıca kaydedilecek; eşik başarısızlığı tamamlandı olarak raporlanmayacak.

Eklemeli sıra: ortak chunk şeması/RLS/indeksler → testli DAL dalı → eski
store'lardan idempotent veri aktarımı → caller ve worker uyumu → writer drain
ve kontrollü kesim. Ara sürümde eski kayıtlar layout kimliğiyle tanınır;
aynı nesle dual-write yok. Eski tablolar tarihsel/veri-koruyan olarak tutulur,
son aktif okuma/yazma yolu yalnız ortak depoya gider.

- Tek migration-managed aktif chunk/embedding tablosu; tenant, mantıksal nesil,
  managed DocumentVersion veya legacy IndexedDocument, ordinal/kind, text,
  embedding ve doğrulanmış boyut. Legacy/managed kimlikleri karışmaz.
- Boyut belirtilmemiş vector saklama; sonlu boyut/temsil/mesafe allowlist'i,
  sabit migration-managed HNSW expression/partial ve keyword/filtre indeksleri.
  Yeni geometri kontrollü migration ister; her tenant/nesil için DDL yok.
- Aynı boyut aynı embedding uzayı değildir. Query modeli/nesil aynı güvenilir
  seçimden gelir. ADR-0017 halfvec davranışı korunur; yeni padding/truncation yok.
- DB ve servis tenant/nesil/belge uyumunu, tekilliği, pozitif/doğru boyutu,
  writable build durumunu ve geç worker fencing'ini birlikte zorunlu kılar.
- Build/retry/copy/activate/rollback/retention normal yollarında CREATE/ALTER/DROP
  yok. Son geçişte eski DDL fonksiyonlarına runtime erişim kapatılır.
- Vector/keyword/hybrid, content/summary, preview, citation, evidence, copy,
  evaluation ve legacy yolları taşınır. Tablo varlığı nesil hazır demek değildir.
- A servis ederken B hazırlanır; eksiksiz B atomik etkinleşir; başarısız B A'yı
  etkilemez. Sıfır chunk'lı geçerli build ile yarım build ayrılır.
- Bounded batch DELETE, aktif/referanslı/in-flight nesil koruması, purge/promotion
  kilidi, retry/rollback saklama pencereleri. Autovacuum/bloat/disk ölçülür.
- Non-owner/non-BYPASSRLS ile FORCE RLS; eksik tenant ve connection reuse ret
  testleri. Referanslı nesiller veya kaynaklar cascade ile silinmez.
- Veri-koruyan idempotent backfill; provider yeniden çağrılmadan eski vektörler
  taşınır. Sayım/checksum/kimlik/boyut kanıtı; kontrollü writer drain/kesim.
  Eski store'ları ilk cutover'da silme; yeni yazılardan sonra dönüş ayrıca kanıtlanır.
- Performans deneyi: exact-search recall@k, p50/p95, küçük/büyük tenant,
  çok eski nesil, model karışımı, build altında okuma, prepared/generic plan,
  EXPLAIN BUFFERS, vacuum/disk. Eşikler deneyden önce bu plana kaydedilir.

### M0/M2 geçiş kimliği ve referans envanteri

Canlı model metadatası ve JSON okuyucularından doğrulanan eşleme (2026-09-09):

| Mevcut kayıt | Ara/hedef karşılığı ve kimlik kuralı | Bağımlılık / kaldırma engeli |
| --- | --- | --- |
| `IndexVersion` | Aynı PK, yeni layout/state ve job/attempt; mantıksal veri nesli | Parent, IngestionRun, job result, set built-index ve evaluation FK'ları korunur. |
| `Chunk` / `chunk_iv_<id>` | `SharedVectorChunk`; eski chunk PK taşınmaz, kimlik `(nesil, belge türü+ID, ordinal, kind)` | Eski kaynak silinmez; exact text/vector/sayı/checksum backfill kanıtı gerekir. |
| `IndexedDocument` | Eski kaynak belgesi aynı PK ile kalır; shared nullable FK bu kimliği taşır | Managed `DocumentVersion` ile sayısal ID çakışması ayrı FK/check ile ayrılır. |
| `Document` / `DocumentVersion` | Aynı mantıksal belge, sürüm, checksum ve object_key | Membership PROTECT ve shared chunk PROTECT; tombstone canlı uygulanır. |
| `DocumentSet` / Version / Membership | M2'de aynı ID ve üyelik; M4 veri nesli seçimi ayrıca geçer | Built-index FK bugün SET_NULL; release JSON pin'i SQL FK değildir. |
| `Source` + REST/Confluence profile/contract | M5 ortak Connection/Source'a eklemeli eşleme; mevcut source PK korunacak | Document.source, connector run/cursor/schedule ve profile grant'ları incelenmeden kaldırılmaz. |
| `StagedIndexBuildJob` / Outbox | M2 mevcut job PK + attempt; M5 ortak iş modeline kalıcı eski-yeni eşleme | Job→result PROTECT, generation→job PROTECT; broker ID iş kimliği değildir. |
| `ScenarioRelease` / `ArtifactVersion` / WorkflowVersion | M4 ScenarioRevision eski release/artifact/checksum kökenini saklayacak | Run.release ve workflow FK PROTECT; eski manifest ve canary/rollback çözücüleri korunur. |
| `DocumentSetGrant` / ScenarioGrant / Binding | Aynı ID ve iptal durumu; M3 açık mod geçişi | Principal string'i consumer kimliğidir; üyelik/rol ile eşitlenmez. |
| Run checkpoint / execution_context / Node result, QuestionEvaluation evidence | JSON içindeki nesil, belge ve citation referansları korunur | Salt FK envanteri yeterli değildir; retention bu alanları da dikkate almalı. |

M2'nin doğrudan IndexVersion FK tüketicileri: parent_index_version (SET_NULL),
IngestionRun.index_version (SET_NULL), IndexedDocument/Chunk (CASCADE),
SharedVectorChunk (PROTECT), StagedIndexBuildJob.result (PROTECT),
DocumentSetVersion.built_index_version (SET_NULL), QuestionEvaluationRun (PROTECT).
Bu liste mevcut on_delete davranışını kaydeder; herhangi bir cascade çalıştırma
onayı değildir. Shared PROTECT sayesinde nesil/belge silme sessiz veri kaybı yapamaz.
M4/M5'in ayrıntılı field/backfill/JSON uyumluluk eşlemeleri kendi uygulamalarından
önce bu tek dosyada genişletilecek; M0 henüz bütünüyle tamamlanmış sayılmaz.

Envanterde purge boşluğu bulundu: set üyeliği kaldırılmış ama ortak chunk'ta
referanslı belge için object-store silme, DB PROTECT hatasından önce çalışabilir.
M2 düzeltmesi: belge/sürümleri kilitle, shared referansı dahil bütün mevcut kullanım
kontrollerini blob silmeden önce yap; `DOCUMENT_IN_USE` ile reddet. Bu uygulama
değişikliğinin testleri yalnız sentetik belgelerdir, gerçek purge yapılmayacak.

## 5. Yetkilendirme sözleşmesi — M1/M3

Temel roller: platform yönetimi + ayrı recovery; organizasyon üyelik/yönetim;
proje ve senaryoda Görüntüleyen/Düzenleyen/Yönetici; dokümanda Okuyucu/Yönetici.
Üyelik tek başına içerik/senaryo açmaz. Organizasyon idaresi senaryo işi, kaynak
okuma veya tool onayı sağlamaz. Keyfi capability editörü/DSL/harici motor yok.

- Proje düzenleyeni senaryo oluşturur. Yönetici proje ayarları ve üç temel
  rolün kendi projesindeki atamasını yönetir. Başka proje/org/platform/content/
  approver atayamaz. Senaryo yöneticisi proje rolü atayamaz.
- Senaryo düzenleyeni prompt/workflow/retrieval/test düzenler, aday derler/test
  eder; yönetici ayrıca yayın/rollback/canary/callability/run izleme-iptal ve
  pause/resume yapar. Editör testi genel runtime yetkisi gerektirmez.
- Eski Release Manager ve Runtime Operator gelişmiş uzman ataması olarak dar
  kalır. Araç onayı exact approver ve doğrulanmış insan/self-approval sözleşmesine
  bağlıdır; paylaşılan consumer insan başlatan sayılmaz.
- Yeni senaryoda projeden devral veya özel erişim. Devralmada karşılık rol;
  özelde doğrudan atama. Uzman roller bağımsız. Tek senaryo kullanıcısına yalnız
  gezinme için üst proje kabuğu; kardeşlerin metadata'sı açılmaz.
- Mod/atama geçişi kazanan-kaybeden önizlemesi, açık seçim, transaction/audit,
  son yönetici koruması, expiry/revocation/concurrency. Bilinmeyen rol/mod ret.
- Eski kayıtlar compatibility modunda aynı nesne/işlem izinlerini korur;
  geniş Yöneticiye otomatik çevirme yok. Önizleme + idempotent uygulama;
  doküman metadata okuyucusu içerik okuyucusuna dönüşmez. Eski uzman/capability
  sıradan form kaydında silinmez; geçiş tamamlanmadan uyumluluk kodu kaldırılmaz.
- Consumer paketleri: çalıştır=workflow_run; gelişmiş okuma araçları=tool_call;
  gelişmiş varsayılan kapalı yan etki=tool_call_side_effect. Release değişimi
  kendiliğinden yeni izin vermez. Eski API/GitOps/capability değerleri korunur.
  Etkin yolu olmayan teknik capability'ler normal formdan çıkarılır; gelişmiş
  retrieve_debug/ingestion_read ayrıdır. Token/protokol/kota/child kesişimi korunur.
- Veri modu: istemciye özel senaryo+consumer grant kesişimi; ortak modda her set
  için veri yöneticisinin mevcut/gelecekteki senaryo istemcilerini kapsayan açık
  izni. Bağlamak izin vermek değildir; yeni set grant'i atlanamaz.
- Tenant, exact scenario, seçilen nesil, canlı grant, aktif indeks, tombstone,
  içerik okuma ve redaksiyon bütün yollarda kalır. İptal sonraki retrieval'da etkili.
- authorize tek karar kaynağı; kapsam listeleri ve UI allowed_actions eşdeğer.
  Yetki ile readiness ayrı; sahte client actions/tenant/role kabul edilmez.
  Geniş fallback yerine exact karar. Açık sayfada yetki kaybı sonraki POST'u reddeder.

M3 eylem dilimi: aday hazırlama mevcut builder'da editor veya release manager
kararıyla açıkken Django candidate POST'u ve minimum öneri release-only idi.
Bu fark kapalı scenario action eşlemesiyle giderilecek: compile=edit veya release;
release/lifecycle ayrı kalacak. Django/React aynı sunucu `allowed_actions` verisini
gösterecek; organization can_write fallback'i kaldırılacak. Aday kaydı org→scenario
kilidi altında yeniden yetkilendirilecek ve audit ile atomik kalacak. Yetki kararı
hazırlık durumundan bağımsız; boş/eksik workflow yetkiyi genişletmeyecek.
- M1 ingestion status: aktif ingestion_read binding → gerçek senaryo/set bağı
  → canlı senaryo grant → veri modunun consumer/shared izni → Source.document_set.
  İzinli kaynak filtresi run_id/latest seçilmeden uygulanır; seti olmayan veya
  ilgisiz kaynak güvenli 404. Tenant ve kaynak metadata'sı sızmaz. Ortak veri
  modu M3'te geldikten sonra aynı merkezi kapsam fonksiyonu genişletilir.

## 6. RAG ve kalıcı yürütme — M4/M5

M3 consumer paket dilimi: normal binding formu çalıştırma seçimini sunucuda
`workflow_run` olarak kaydeder; gelişmiş açık seçimler okuma aracı, yan etkili
araç, debug retrieval ve ingestion status değerlerine dönüşür. Teknik capability
kutuları ve preset→exact tekrar seçimi kaldırılır; arbitrary capabilities POST
reddedilir. Inert sözlük/API/GitOps değerleri korunur, mevcut kayıtta normal
form onları silmez. Kaydetme org kilidinden sonra aktörü ve consumer/scenario
tenant/aktif durumunu yeniden doğrular; audit aynı transaction. Kapsam ve
capability eşlemesi testli, normal yeni ekran inactive teknik izin sunmaz.

M3 ortak veri uygulama sırası: Scenario `consumer_specific` (mevcut varsayılan)
ve `scenario_shared` kapalı modu; her mevcut ScenarioDocumentSetGrant üzerinde
ayrı, aktör/zaman içeren ortak-istemci onayı. Normal senaryo/set grant onayı bu
onayı üretmez. Grant iptalinde ortak onay temizlenir; eski grant'i yeniden açmak
ortak onayı geri getirmez. Ortak onay yalnız exact veri yöneticisinin açık
mevcut/gelecekteki istemciler seçimiyle ve fail-closed audit ile verilir.
Merkezi canlı retrieve-grant kapsamı normal modda consumer kesişimini, ortak
modda ayrıca etkin exact consumer binding + her setin ortak onayını zorunlu
kılar. Retrieval ve MCP ingestion aynı kararı kullanır; pinned veri nesli,
tombstone/aktif indeks/RLS ve operator-test kapsamı korunur. Eksik/bilinmeyen
mod veya onay hiçbir fallback açmaz. Konsolda eksik set onayları gösterilir.
PG negatifler iki storage layout'ta ve MCP exact-source seçiminden önce çalışır.

- Tek ScenarioRevision: doğrulanmış graph/prompt/model/tool/retrieval/I-O/connection
  config ve engine contract/checksum snapshot'ı. Draft optimistic revision ayrı;
  IndexGeneration ayrı. Immutable geçmiş ve safe secret referansları korunur.

M4 ilk eklemeli dilim ve eşleme: ScenarioRevision, eski ScenarioRelease ve
WorkflowVersion kimliklerini PROTECT referanslarla koruyan immutable snapshot
kaydıdır. Her rolün ArtifactVersion ID/ref/type/checksum/body kökeni, compiled graph,
compiler contract, runtime version ve eski veri pinleri aynı checksum'a girer.
Yeni role/body eksikliği veya köken checksum çelişkisi kapalı hata verir; sessiz
latest/fallback yok. 50 rol ve 4 MiB snapshot üst sınırı; inline secret validator
yeniden çalışır. Snapshot'a kaynak doküman içerikleri, token veya çözülmüş sırlar
konmaz. Başlangıçta veri seçimi legacy_pinned olarak açık kaydedilir; aktif nesil
seçimi ve adım retry evidence'i ayrı sonraki dilimdir.

Yakalama org→scenario→release kilit sırası, exact compile yetkisi ve atomik audit
ile yapılır; aynı release tekrarında aynı kayıt döner. DB FORCE RLS, tenant/scope
eşitliği ve UPDATE/DELETE ret trigger'ı uygulanır. Bu ilk dilim runtime'ı henüz
snapshot'a yönlendirmez; resolver, admission/Run, wait/child ve evaluation yolları
geçirilmeden yeni varsayılan veya canlı backfill açılmaz. Eski IDs/URL/manifest/
run/checkpoint kalır. Kaynak release'in geri alınması snapshot'ı değiştirmez.

M4 veri seçimi sonraki dilim: yeni snapshot'ta kapalı `active_generation` modu
mantıksal set kimliklerini tutar; `legacy_pinned` aynı çözümlemeyi korur. Yeni
`RunRetrievalSelection` adım kimliği + revision + sorgu/profil checksum'ını,
`RunRetrievalGeneration` exact set-version/index FK'larını PROTECT ile tutacak.
Boş seçim de kayıtlıdır; retry güncel başka nesle sıçramaz. İki ilişkisel tablo,
retention'ın JSON içinde görünmeyen referansları silmesini engellemek içindir.
Bir seçim en çok 200 nesil, bir Run en çok 2048 seçim taşır; içerik veya sorgu
metni kayda/audit'e kopyalanmaz. Scope/immutable/RLS hem DB hem serviste korunur.
Seçim set promotion kilit sırasıyla atomik yapılır; sunum anında consumer/grant/
tombstone yine canlı denetlenir. Seçilmiş superseded nesil yalnız exact kayıtla
okunabilir; retired/building/failed nesil veya eksik kayıt fail-closed kalır.

Mevcut ana executor ve branch node işi dış çağrıları transaction içinde tutuyor.
Bu yüzden yeni seçim kaydını o transaction'a basitçe eklemek yeterli değildir:
worker kaybı seçimi geri alabilir. Önce model ve bağımsız, commit garantili seçim
servisi; ardından ana/branch/embedded-agent sınırında seçim-before-I/O ve retry
testleri uygulanacak. Bu entegrasyon bitmeden aktif nesil modu/console varsayılanı
açılmaz. Mevcut çalışan legacy ve snapshot/legacy_pinned davranışı korunur.

Ana yürütücü entegrasyonu: yeni aktif-veri retrieval düğümüne gelince önce mevcut
checkpoint/cursor/sayaçlar aynı sahiplik altında `running→running` olarak commit
edilecek; olay `run.checkpointed` olacak. Seçim dış transaction'da durable olarak
kaydedilecek, ardından aynı düğüm devam edecek. Eksik seçimde arama/provider
çağrısı yapılmayacak. Seçim hatası mevcut telafi/failure yoluna dönecek; önceki
yan etki tekrar yürütülmeyecek. Branch ve embedded-agent alt adımları da ayrı
kararlı kimlik/commit sınırı kullanacak; tüm yollar test edilene kadar opt-in kalır.
- ArtifactVersion/WorkflowVersion/ScenarioRelease görevleri tek resolved snapshot
  sözleşmesine taşınır; eski public IDs/URLs/FK/citation/audit referansları uyumluluk
  olmadan kaldırılmaz. Katalog reusable özelliklerini sayı için silme.
- Yeni run kullanılan revision'a, devam eden run başladığı snapshot'a bağlıdır.
  Preview de tek snapshot kullanır. Güncel iptaller geçerli. Worker/checkpoint
  engine sürümü ayrıca uyumluluk/drain ile yönetilir.
- Yeni hedef senaryolar koleksiyonun aktif neslini her retrieval adımı başında
  seçer; seçilen küme ve evidence kaydedilir. Aynı adım retry'sı kaydedilmiş
  seçimle gider. Açık pin modu desteklenir; legacy kayıtlar korunarak taşınır.
- Veri yenileme scenario republish istemez. Yarım tarama toplu silme sinyali
  değildir. Source external_id/checksum/revision/cursor/tombstone/schedule;
  DocumentRevision ve nesil manifest'i ilişkisel ve sınırlıdır.
- Connection tip doğrulamalı global/tenant katalog ve grant anlamlarını korur.
  Shared Job/Outbox yalnız ingestion'dır; ayrı workflow motoru kurulmaz.
  Atomik niyet/outbox, claim/lease/fencing, cancel, retry/idempotency, OCR
  result-before-ACK ve legacy job/run referansları korunur.
- REST ingestion, MCP resource ingestion, runtime REST/MCP tool çağrısı ve
  REST/MCP scenario serving ayrı adapter'larla ortak domain servislerini kullanır.
  MCP resource desteğini tool/server varlığından çıkarma; seçilen protokol,
  mime/boyut/sayfalama/auth/timeout doğrulanır. Tool çıktısı açık extraction
  olmadan belge olmaz. Harici açıklama/schema yetki veya talimat değildir.
- Mevcut kalıcı Run/wait/branch/join/child/compensation/invocation/approval
  kayıtları korunur. Restart, duplicate delivery, single-use resume, tek join,
  child binding kesişimi ve geç worker ret. Approval exact girdi checksum/hedef/
  insan/expiry'ye bağlı; unknown external outcome kör retry/telafi edilmez.
- Evaluation ortaklaşmasında purpose, case snapshot, revision/generation/policy,
  evidence ve içerik izni kalır. LLM judge/diagnostic zorunlu yayın gate'i değildir.
  Audit ile yüksek hacimli Usage ayrı; secret/chunk/vector telemetry'ye yazılmaz.
- 44-model kavramsal grupları: org/proje 3, typed yetki 5, senaryo 4, consumer 3,
  connection 1, veri 7, veri grant/request 3, ingestion 2, tool/onay 3, run 8,
  evaluation 3, audit/usage 2. Her mevcut model alan/ID/FK/unique/check/izin/
  lifecycle/caller bakımından eşlenir; eksik ilişki/katalog sayısı gerekçeyle eklenir.

## 7. REST sihirbazı — M6

Yeni mimarinin servislerine bağlanan tek akış; eski modele ikinci backend yok.
Kaynak koleksiyona aittir, çok senaryoda tekrar kullanılır; senaryo başına yeniden
çekme/embedding yapılmaz. Mevcut gelişmiş yollar/URL/kayıtlar geçerli kalır.

1. Ad ve kapsam; yetkili mevcut veya yeni set; logical_id/slug/revision otomatik.
2. Tek URL/method, desteklenen GET/read-only POST, onaylı secret referansı.
   Güvenli bağlantı testi SSRF/TLS/DNS/redirect/time/byte/request sınırlarıyla,
   yetki ve audit ile; dış çağrı DB transaction'ı içinde tutulmaz.
3. Sentetik örnek veya yetkili bounded/redacted response; görsel items/ID/title/
   content/revision/deleted/encoding/MIME/detail eşleme. Canonical validator tek
   kaynak; gelişmiş JSON ile görsel mod aynı sözleşmeyi kullanır.
4. None/page/offset/cursor pagination önerisi + açık seçim; inputs'tan form;
   URL/header/secret input'a kaçamaz. Root/prefix birleşimi güvenli ve testli.
5. Manuel/periyodik sync; embedding/chunking/OCR; draft/stage/izinli promotion
   seçimi. Dispatch niyeti kalıcı; asenkron ilerleme ve ayrı aktivasyon kararı.
6. Güvenli özet, idempotent oluşturma, kısmi başarısızlığın kesin aşaması,
   güvenli retry; başarılı config kaydı sessizce silinmez.

Düzenle: ön doldurma/diff, yeni immutable config revision'ı, tek aktif writer,
cursor/document/schedule lineage koruması, test/stage/kesim ve rollback. Disable,
restore ve retirement ayrıdır. Kartta son başarılı sync ve son hata ayrı; kaynak
durumu, yetkili bağlı senaryo sayısı, index/doküman/chunk ve sonraki çalışma.
Endpoint/credential/mapping senaryo ekranına taşınmaz. State bounded/server-side/
secret-free; keyboard/back/refresh/error recovery ve gelişmiş mod round-trip testli.

## 8. Konsol, senaryo ve gezinme — M7

Mevcut Django/React korunur; yeni framework/dependency yok. Tek marka, okunaklı
açık yüzeyler, ölçülü yeşil vurgu, tutarlı spacing/form/tablo/button/status.
Her görevde bir ana işlem; blocker renk yanında metinle. UUID/checksum/DSL/ham
manifest detayda; sahte yüzde/süre/maliyet yok. Gizli panel yetkisiz veri taşımaz.

- Senaryolar sidebar girişi, scoped searchable/project-filtered sayfalı liste,
  project shortcut, role-honest Test/Onay menüleri, parent/cancel/Studio dönüşü,
  mobil menü/Escape/focus korunur. Arama/sayfa bağlamı güvenli named routes ile;
  açık return_url redirect yok. Deep link, back/forward, form hata bölümü çalışır.
- Gerçek alt sayfa/panel; anchor ise tab rolü verilmez. Eski fragment'ler
  eşlenir; disclosure hedefe gelişte açılır. Bütün listeler bounded/scoped.
- Doküman Dosyalar/Hazırlama/Sürümler/Erişim; kaynaklar keşfedilebilir.
  Yükleme/preview/değiştirme/filter/partial failure; aktif ve hazırlanan veri
  ayrı. Hedef lifecycle'a uygun tek hazırlama deneyimi; explicit activation,
  uygun gerçek profiller, retry/cancel ve karantina engelleri görünür.
- Senaryo: ilk kurulum en fazla dört hedef aşaması, yalnız retrieval gerekiyorsa
  kaynak zorunlu. Yayın sonrası canlı durum/draft divergence/test/veri/consumer
  özeti; tek authoritative ana eylem. UI yeni role ve ScenarioRevision'a bağlıdır.
- Genel/Bilgi kaynakları/Test/Entegrasyon/Sürümler/Ayarlar-operasyon ayrımı;
  tam artifact/manifest ayrıntıları sürüm detayına, DSL Studio yardımına.
  Legacy aktif release + mutable draft yok, temiz/kirli draft, aday running/
  fail/pass, viewer/editor/manager, inactive org, disabled scenario, broader
  suspension, checksum mismatch, superseded/rollback durumları ayrı test edilir.
- Callability kapatma ile acil runtime durdurma ayrı; broader suspension exact
  resume ile aşılamaz. İçerik evidence ayrı doküman okuma kontrolünden geçer.
- Dashboard, projects, tests/results, consumers/token, runs/approvals, platform,
  source, artifact/release, login/error/empty durumları aynı tasarım diline alınır.
  Token reveal mevcut güvenli sözleşmesi dışında credential gösterilmez.
- 390/900/1440 ve desktop viewport; keyboard/screen-reader/focus, uzun Türkçe
  adlar, taşma, loading/empty/error, console/network, önce/sonra click ve uzunluk.

## 9. Tehdit modeli, veri akışı ve operasyon riskleri

Aktörler: insan kullanıcı, platform/org/proje/senaryo/set yöneticileri, approver,
machine consumer, worker, migration operator ve dış provider. Kimlik sınıfları
karıştırılmaz. Korunan varlıklar: tenant metadata/content, credentials, geçmiş
release/index/evidence, approval, side effect, audit ve ücretli kullanım.

| Güven sınırı / risk | Kontrol ve kanıt |
| --- | --- |
| Browser/API → domain | Exact object/action/tenant/field authorize, kapalı şema, CSRF/POST; sahte ID/role/actions reddi. |
| Domain → DB | Parametreli sorgu, FK/unique/check ve tenant-consistency, FORCE RLS, kısa transaction-local kapsam. |
| Web → worker | Kalıcı niyet/outbox, trusted IDs, reauthorization, lease/fencing, duplicate/cancel/crash testleri. |
| Ortak heap/ANN | Tenant ACL filtreleri + non-owner RLS; recall/noisy-neighbor/disk/latency ölçümü. |
| Snapshot → live data | İzin/tombstone kontrolleri canlı; seçilen revision/nesil trace/evidence'e kaydedilir. |
| Dış bağlantı/tool | SSRF/TLS/auth audience ve boyut/zaman limitleri; exact approval, unknown outcome reconciliation. |
| UI gizleme | Gizli HTML/JSON içinde yetkisiz metadata/content yok; action ile readiness ayrıdır. |
| Erişim geçişi | Otomatik yetki genişlemesi yok; diff/explicit apply, atomik audit/last-admin, compatibility. |
| Veri geçişi/retention | İdempotent batch/hash/count/lineage, tek writer, referenced generation guard; ayrı destructive cleanup. |
| Audit/telemetry | Actor/action/target/decision/outcome/reason/request/trace, redaksiyon; kritik erişim idaresi fail-closed. |

## 10. Doğrulama ve bitiş koşulları

Her dilimde happy/invalid/boundary/auth/deny/same-tenant neighbor/cross-tenant,
revocation/expiry, retry/idempotency, concurrency/failure ve audit/redaction
testleri. Ortak yetki fonksiyonunu kritik testte mock etme. PostgreSQL RLS,
pgvector, locking, migration ve gerçek persistence sınırları SQLite ile kanıtlanmaz.

Repository doğrulanmış komutları: `.venv/Scripts/python.exe -m pytest` (sessiz
mod/time limit yok), ruff format/check, mypy, manage.py check, makemigrations
--check --dry-run, compileall. Frontend değişirse tsc/Vitest/build; güncel
generated Studio bundle. İlgili suite sonrası gerekli kapsamlı suite; aynı
geçen suite'i değişiklik/gerekçe yokken tekrarlama. Mevcut CI secret/security/
dependency/migration kontrolleri uygulanır; çalışmayanlar açık kaydedilir.

M8: yeni kurulum ve veri-koruyan upgrade, tekrar backfill, old/new web-worker,
restart/rollback, model/geometri negatifleri, tüm retrieval/evidence yolları,
değerlendirme ve onay/parallel/child/telafi testleri. Browser §10 gerçek rol
allow/deny, direct URL/POST, same/cross tenant, affected/adjacent journeys,
accessibility ve console/network kanıtı. Provider/worker önkoşulu başarısızsa
downstream geçiş başarılı raporlanmaz. Kullanıcı verisinde test reset/yayın yok;
izole sentetik ortam. Kapasite ve kurulu extension sürümü canlı kanıtla doğrulanır.

Rollout: eklemeli şema → doğrulanmış migration/backfill → uyumlu writer drain →
kontrollü reader/writer kesimi → eski referans/izin/kanıt eşitliği → ayrı legacy
temizlik kararı. Rollback yeni yazıları kaybetmemeli; gerekirse forward-fix.
Sırf eski tablolar duruyor diye eski binary'ye dönüş güvenli sayılmaz.

Her kilometre taşı sonunda staff/AppSec/SRE diff incelemesi ve kanıt; durable
kararlar yeni ADR'de, gerçek davranış README/architecture/user/runbook'ta.
Master plan güncel tutulur; bütün kabul ölçütleri kanıtlanınca arşivlenir.
Tamamlanma ölçütü yalnız tablo azalması veya ekran kısalması değildir.

## 11. Doğrulama kaydı ve devam noktası

2026-09-09 başlangıç: dal `feat/foundation-sprint-0-1`, HEAD önceki incelemede
`2c3e959`; mevcut status tekrar okundu. Çok sayıda önceden değişmiş source/test/
config ve öneri dosyası mevcut; topluca commit/reset yapılmaz. Aktif handoff
başka işe ait; onun eski runtime veya test sayıları yeni kanıt sayılmadı.
Codebase Memory/Serena araç listesinde yok; doğrudan rg/kaynak/test kullanılıyor.

Runtime başlangıcı: canonical Compose okundu; `docker compose -f
deploy/compose/docker-compose.yml ps` bütün web/worker/beat rollerini çalışır,
PostgreSQL/Redis/MinIO'yu sağlıklı gösterdi. Liveness HTTP 200, status ok.
Host `.venv/Scripts/python.exe --version`: Python 3.13.5. Bu snapshot kalıcı
sağlık garantisi değildir; runtime'a müdahaleden önce yeniden kontrol edilir.

Birleştirme: Agent_Hub_MD altında yalnız plan.md kaldı. Yedi kaynak klasörü
(22 belge) kaynak arşivine taşındı. Eski canonical task belgelerinde tek aktif
göreve yönlendiren Superseded notu var. Arşiv bağlantıları canonical konuma
göre yeniden bağlandı: 81 yerel bağlantı, 0 eksik hedef. Kaynaklar silinmedi.

M1: apps/mcp/service.py izinli setleri exact senaryo/set grant korelasyonu ile
seçiyor; kaynak/run tenant koşulları ve consumer retrieve grant'i birlikte
uygulanıyor. Bu filtre run_id/latest seçiminden önce. Eksik/yetkisiz kaynak
aynı RUN_NOT_FOUND 404; izin iptali sonraki istekte etkili. Başarı yanıt alanları
aynı. Dış çağrı, migration, bağımlılık veya worker restart gerekmedi.

- Red: yeni 10 MCP scope testi eski kodda 8 failed, 2 passed (18.68 s).
- Green: `.venv/Scripts/python.exe -m pytest apps/mcp/tests
  --basetemp=.tmp/pytest-simplification-m1`: 19 passed (18.73 s).
- PostgreSQL: test ayarlarının hermetik provider/cache/object-store değerleri
  korunarak yalnız izole test DB bağlantısı değiştirildi; gerçek uygulama DB'si
  test edilmedi/resetlenmedi. MCP + tenancy context: 27 passed, 1 SQLite-only
  skipped (35.76 s). Yeni non-owner/NOBYPASSRLS testinde eksik tenant ret,
  scope yeniden kurma, exact izin ve grant iptali kanıtlandı.
- Ruff check/format ve mypy ilk iki M1 dosyasında geçti; son test ekinden sonra
  final kontroller yeniden yapılacak. Scoped git diff --check geçti.
- Staff/AppSec/SRE ara inceleme: senaryo bağı ve grant'i aynı iki anahtarda
  eşlenir; aynı organizasyondaki başka senaryo yetkisi birleştirilemez. İçerik,
  endpoint veya yetkisiz source kimliği yanıta/audite eklenmez; kısa transaction.
  Bu MCP API düzeltmesinin görsel UI'sı yok; bütünleşik browser gate M8'de açık.

M2 başlangıç envanteri (yalnız metadata/count; 2026-09-09): PostgreSQL pgvector
0.8.4. Profil geometrileri vector/64, vector/768, vector/1536 ve halfvec/3072;
her birinden bir profil. IndexVersion geometrileri vector/64:2,
vector/1536:9, halfvec/3072:7. Legacy Chunk satırı 0; dinamik store tablosu 9,
toplam relation boyutu 9,363,456 byte. Bunlar küçük yerel örneklerdir;
production kapasite/performance kanıtı sayılmaz.

M3 ilk dilim: `scenario_manager` açık yeni atama olarak eklendi; mevcut dar
roller dönüştürülmedi. Exact edit/test/release/runtime birleşir, içerik ve onay
ayrı kalır. Mevcut org-admin atama formu yeni rol için exact senaryo ister.
Run listesi/boş durum menüsü ve author kapsamı yeni rolle uyumlu. Yayın için
yanlış global/org-admin yönlendirmesi exact senaryo/yayın yöneticisi olarak
düzeltildi. Durable karar ADR-0019; identity/0013 yalnız choices migration'ı.
Gerçek uygulama DB'sine migration henüz uygulanmadı.

- İlk rol/MCP testi: 48 passed, 1 PG-only skipped (19.16 s).
- UI/rol/aday/navigation: 55 passed, 1 yeni testte yanlış URL argümanı;
  test canonical integer detail URL ile düzeltildi, iki gerçek yayın testi
  tekrar 2 passed (19.85 s). Ürün endpoint sözleşmesi değiştirilmedi.
- PostgreSQL rol/assignment RLS/gerçek console yayın: 18 passed (25.78 s).
- Ruff check, 19 dosya format ve 11 dosya mypy geçti; Django check ve
  makemigrations --check --dry-run temiz.
- Browser: yalıtılmış .tmp SQLite fixture ve port 8109; manager own scenario
  listesi tek kayıt, Studio ve yayın/test kontrolleri yetkili. Gerçek pause ve
  resume POST'ları başarılı. Same-tenant sibling ve cross-tenant direct URL
  güvenli 404. Viewer'da Studio/publish/test disabled, runtime menüsü yok;
  approvals/content ayrıca açılmadı. Console warning/error listesi boş.
  Ana sayfa → senaryo listesi → detay 2 tıklama; operasyon için disclosure
  + eylem + onay. Bu yalnız ilk rol diliminin browser kanıtıdır, M8 tam gate değil.
- 482 testlik geniş regresyon kullanıcı devam mesajıyla kesildi; tamamlandı
  sayılmadı. Yayın grubunda bağımsız tekrar 16 passed/2 failed: test profili
  geliştiricinin .env içindeki gerçek model sağlayıcısını devralıyordu ve
  sentetik değerlendirme EVAL_REQUIRED'e düşüyordu. Test ve browser_gate
  profilleri model/embedding/AI provider'larını açıkça hermetik seçime sabitledi;
  production/local provider veya yayın kontrolü değiştirilmedi. Hermetik tekrar:
  473 passed, 9 PG-only skipped (142.88 s); `.tmp/simplification-hermetic.xml`.

2026-09-09 devam: yalnız PostgreSQL ve MinIO canlı; web health bağlantısı kapalı.
Bu çalışmada servis kapatılmadı. İzole test DB kullanılıyor; uygulama DB'sine
yeni migration/backfill veya ayar kesimi henüz uygulanmadı.

M2 ilk dilim: 0017 eklemeli shared chunk + layout/state, 0018 beş sabit HNSW,
FTS, FORCE RLS, dimension/tenant/document/generation/write/immutability trigger'ları.
DAL provision/write/copy/vector/keyword/count/preview/evidence nesil kapsamlı;
başarısız build cleanup önce kalıcı fence, sonra 1000'lik DELETE. Sealed nesil
henüz emekliye ayrılamaz: tam reference-aware retention ve saklama penceresi
bitene kadar tarihsel evidence korunur. Bu konservatif geçiş kalıcı retention
özelliği olarak tamamlandı sayılmaz. Yeni build seçimi deployment ayarıyla;
varsayılan legacy, shared seçimi yalnız testte etkin. Worker contract 4 ve
layout fingerprint uyumluluğu ayrıştırır. Geçişten önce worker drain zorunlu.

- İlk DB bütünlük dilimi: 5 passed (21.57 s), `.tmp/shared-foundation.xml`.
- Genişletilmiş schema/DAL + legacy DAL: 17 passed, 1 SQLite-only skipped
  (22.65 s), `.tmp/shared-dal.xml`.
- Build/promotion/job/retrieval regresyonu: 58 passed, 1 skip, 1 yeni testin
  yanlış helper argümanı; canonical `source=` ile düzeltildi, tekrar yapılacak.
- Ruff geçti; migration drift yok. Host mypy DLL'i Windows Uygulama Denetimi
  tarafından engellendi; policy değiştirilmedi. Alternatif doğrulama açık.

Sıradaki iş: tam model/ID/FK eşlemesini tamamla; M2 geometri ve workload
eşiklerini deneyden önce kaydet, eklemeli ortak depolama geçişini test et.

### Kullanıcı isteğiyle duraklama — 2026-09-09

Kullanıcı internet kesileceği için çalışmayı açıkça durdurdu; yalnız kullanıcı
"devam et" dediğinde yeniden başlatılacak. Otomasyon veya arka plan geliştirmesi yok.
Son pytest işlemi (shared-workload-exact, PID 18080/18588) kullanıcı isteğiyle
durduruldu. İzole `test_agenthub_simplification_probe` DB'si yarım test verisiyle
kalmış olabilir; devamda canlı durum doğrulanıp yalnız bu test ortamı ele alınmalı.
Uygulama DB'si/migration/servisleri değiştirilmedi; son görülen Compose yalnız
PostgreSQL ve MinIO çalıştırıyordu, web health kapalıydı. Bu eski sağlık snapshot'ıdır.

Son uygulanan M2 kapsamı: owner-only idempotent `shared_backfill.py` ve
`backfill_shared_vectors` komutu; source ORM + managed DAL aynı ortak tabloya
uyumlu. Source okuyucu layout'a göre eski veya ortak veriyi seçer. Runtime grant
şablonuna shared SELECT/INSERT/guarded DELETE eklendi; canlı role uygulanmadı.
ADR-0020 ve `docs/operations/shared-vector-storage.md` ara davranışı belgeliyor.

Son kanıtlar:
- Backfill + gerçek shared build: 14 passed (19.38 s), `.tmp/shared-backfill.xml`.
- Eski/yeni source + DAL + ingestion: 35 passed, 1 skip (23.53 s),
  `.tmp/shared-paths.xml`.
- Host mypy Windows tarafından engellendiği için mevcut uygulama image'ında
  geçici dev araçlarıyla aynı mypy 1.15.0 / django-stubs 6.1.0 çalıştırıldı:
  9 source dosyası temiz. Daha sonraki bulk/exact-search/test ekleri henüz tekrar
  type-check edilmedi; üretim bağımlılığı veya host güvenlik politikası değişmedi.
- İlk 20k test: ANN ef_search=100 büyük kümelerde recall 0.8125–0.87; başarısız.
  Satır-satır yazma 47 dakika sürdü. Parametreli 100'lük INSERT batch sonrası
  veri hazırlama yaklaşık 30–33 saniyeye indi; bütün suite yaklaşık 55 saniye.
- ef_search=800 ve 400 recall 1.0 sağladı, fakat bazı p95 oranları 1.5 sınırını
  aştı. Eşikler düşürülmedi. Önceki ölçümler `.tmp/shared-vector-workload-first.json`,
  `...-ef800.json`, `...-ef400-open.json` altında; bunlar open nesil ölçümleriydi.
- Son düzeltme: küçük sealed nesillerde en fazla 1,280,000 vektör elemanına
  bounded exact cosine/B-tree yolu; diğerlerinde bounded ANN ef_search=400.
  Benchmark gerçek sealed/count metadata'sı ve redakte EXPLAIN planlarını kaydeder;
  referans hesap tek thread olduğundan arama ölçümüne BLAS işçisi karışmaz.
  SQL alias ifadesi hatası düzeltildi. Son koşuda 15 schema/DAL ve 5 backfill
  testi yürüdü, workload seed aşamasında kullanıcı durdurdu: bütün suite ve
  exact-path performansı tamamlandı sayılmaz.

Devamda ilk iş: son kod/diff ve runtime durumunu doğrula; yarım izole test DB'sini
kontrollü yeniden kullan/kur; yeni 21-test PG grubunu ve workload'u tamamla.
Ardından son M2 dosyalarının formatter/linter/mypy/migration/system check ve
ilgili geniş regresyonu. Model/ID/FK envanteri, worker attempt fencing, kapsamlı
retention, mixed geometry/old-generation/build-load/generic-plan kanıtı, rollback,
legacy DDL erişimini kesme ve default cutover hâlâ açık. M3'ün kalan devralma/
geçiş/UI işleri ve M4–M8 bu tek görevde bekliyor; bütün geliştirme bitmedi.

### Kullanıcı devam onayı — 2026-09-09

Kullanıcı "devam et" dedi; görev yeniden aktif. Compose canlı kontrolünde
PostgreSQL ve MinIO sağlıklı, web/worker/Redis kapalı. Yarım testin yalnız
`test_agenthub_simplification_probe` veritabanı doğrulanarak yeniden kurulacak;
uygulama verileri bu testin dışında. Öncelik kesilen PG doğrulaması ve workload.

M2 devam dilimi: kalıcı işin `attempt` numarası generation'a bağlanacak.
Claim/progress/final/failure aynı denemeyi doğrular; cancel/retry sonrası eski
işçi yeni denemeyi değiştiremez. Ortak chunk INSERT/copy ve seal DB/servis
sınırında job→generation kilit sırasıyla bunu zorunlu kılar. Doğrudan senkron
build'ler jobsuz kalabilir; mevcut ID/referanslar silinmez. Migration eklemeli.
Kritik testler: cancel+retry sonrası stale progress/fail/final/write, yeni deneme
başarısı, geç seal, duplicate teslim, gerçek non-owner PG ve eşzamanlı iptal.

M2 son doğrulama: attempt fence + job lifecycle 19 passed (24.16 s),
`.tmp/attempt-fence-fixed.xml`. Geç worker progress/fail/complete/write/seal ve
eşzamanlı iptal testli. Worker contract artık 5. Son workload 20 fonksiyonel
test geçti; recall bütün kümelerde 1.0, fakat 10k kümesinde p95 6.912 ms / eski
3.863 ms = 1.789 olduğundan göreli performans kapısı başarısız, açık kalıyor.

Devam incelemesinde completed legacy job neslinin backfill geçişi ile yeni
attempt fence çakışması bulundu: yalnız migration owner, yalnız doğrulanmış
legacy→shared/sealed geçişi ve işin tam başarılı result/attempt eşleşmesi için
dar istisna uygulanıyor. Runtime yazarı bu istisnayı kullanamaz. Gerçek non-owner
worker testi iki layout'ta çalıştırılacak; legacy sonucu owner backfill ile
aktarılacak. Canlı uygulama verisi/rolü üzerinde işlem yok.

40 PG test geçti (25.90 s), `.tmp/shared-attempt-backfill.xml`: iki layout'ta
gerçek non-owner worker, başarılı legacy iş sonucunun aktarımı, DAL/backfill ve
attempt fence birlikte doğrulandı. Hız iyileştirme deneyi: exact yolu yalnız
128,000 vektör elemanına kadar; büyük kümelerde ANN ef_search=200. Amaç küçük
kümelerde tam doğruluğu koruyup büyük kümelerde gereksiz tam taramayı azaltmak.
Kabul eşikleri değişmedi; bu ayar henüz doğrulanmış sayılmaz.

Son performans düzeltmesi tenant scope ve ANN ayarlarını aynı transaction-local
DB çağrısında kurar; normalizer/RLS/predicate korunur. 16 test geçti (80.99 s),
`.tmp/shared-workload-batched-context.xml`. 100/1900/8000/10000 kümelerinde
recall 1.0/1.0/0.965/0.9625, p95 yaklaşık 2.82/4.51/4.58/24.12 ms;
legacy oranları 0.97/1.07/1.24/1.13. Tek sentetik koşu kabul eşiklerini geçti;
10k ölçümündeki sistem varyansı nedeniyle production SLO olarak kullanılmaz.
Mixed geometri/old-generation/build-load/generic-plan gate hâlâ açık.
15 değişen M2 source/test dosyası container fallback mypy ile temiz; migration
drift ve system check temiz. Geniş 340 testlik PG regresyonu sürüyor.

Geniş PG regresyonu: 337 passed, 3 skipped (215.10 s),
`.tmp/shared-integration.xml`; iki SQLite guard ve ayrı opt-in workload skip.
Purge düzeltmesi, non-owner bağlantı tekrar kullanımında ANN kapsamı ve iki
layout'ta gerçek ACL retrieval için sonraki test grubu sürüyor.

M3 sıradaki eklemeli politika dilimi: `project_editor`/`project_manager`,
Scenario `legacy`/`inherit`/`private` modu. Mevcut kayıtlar ve model varsayılanı
legacy kalacak; yeni oluşturma varsayılanı ancak erişim-geçiş servisi/UI hazır
olunca inherit'e alınacak. Legacy administrator dar kalır. Inherit temel rolü
projeden alır, doğrudan temel atama etkin olmaz; bağımsız uzmanlar korunur.
Private projeden içerik devralmaz; yalnız ayrı access-manage kararı proje
yöneticisinin idaresine izin verir. Liste ve tekil karar aynı kapalı rol/mode
matrisinden türetilir. Önizleme/son yönetici/audit geçişi tamamlanmadan canlı
kayıtların erişim modu değiştirilmeyecek; fixture'larda üç mod negatiflerle testli.

M3 politika/delegasyon PG kanıtı: 53 passed (30.00 s),
`.tmp/inheritance-postgres.xml`. Kapsamlı role/mode/list-detail eşitliği,
expiry/üyelik/user/org durumu, açık private self-assignment, uzman retleri,
son kalıcı yönetici, audit rollback ve gerçek release akışı kapsanır.
Üyelik iptali kaynak talimatındaki gibi güvenlik amacıyla korunur: son proje/
özel senaryo yöneticisinin rutin rol silmesi engellenir; organizasyon yöneticisi
offboarding yapabilir ve yönetimi başka aktif üyeye geri atayabilir. İptal
yetkisi de organizasyon kilidi alındıktan sonra tekrar doğrulanır.

M3 geçiş servisi: bounded aktif üye/atama snapshot'ından önce/sonra erişim
önizlemesi; actor+scenario+temel durum checksum'ına bağlı 10 dakikalık imzalı
onay verisi. Uygulamada org→scenario kilidi, tekrar yetki/kapsam/snapshot
doğrulaması, explicit private temel atamalar, uzmanları koruma, kalıcı yönetici
koruması ve tek transaction audit. Stale/tampered/cross-target ret; aynı değişikliği
yeniden gönderme idempotent. Yeni access_revision/change_id yalnız bu geçişin
eşzamanlılık ve tekrar kanıtıdır; içerik sürümü yerine geçmez. Canlı mod değişimi yok.

Erişim geçişi ilk servis dilimi: 7 PG test geçti (20.63 s),
`.tmp/access-transition-postgres.xml`; readonly delta, imza/süre/actor/hedef/stale,
explicit kalıcı yönetici, uzman koruma, audit rollback, idempotent replay ve
iki eşzamanlı farklı önizlemenin yalnız birinin uygulanması kanıtlandı.
31 PG purge/fencing testi geçti (23.87 s), `.tmp/shared-purge-verified.xml`.
ACL retrieval aynı testleri iki layout'ta çalıştırarak 20 geçiş/ret testini geçti;
ilk birleşik 51'lik koşuda yalnız yeni purge testinin exception-message/code
karşılaştırması hatalıydı; gerçek `.code` ile kontrol edilerek yukarıdaki tekrar geçti.

M3 konsol incelemesi: project_detail doğrudan bütün proje senaryolarını listeliyordu.
Tek senaryo kullanıcısına parent-shell açılması bu yolu genişleteceği için liste
merkezi scope'a geçirildi; shell'de proje sahip/sınıflandırma/atama bilgileri
render edilmez. Bu ekran ve normal erişim yönetimi bağlantıları için HTTP/browser
kanıtı aşağıda. Senaryo önizleme/uygulama ekranı eklendi; proje delegasyonu sırada.

M3 konsol kanıtı: 469 passed, 9 PG-only skipped (155.47 s),
`.tmp/access-broad-regression.xml`; console/identity/catalog/tenancy regresyonu.
Son form düzeltmesi 5 passed (18.98 s), `.tmp/access-console-selection.xml`.
17 ilgili dosyada container mypy, ruff ve migration drift temiz.
İzole SQLite browser fixture, 8109: proje yöneticisi legacy→inherit→private
önizleme/uygulaması; özel seçimlerden önce eski etkisiz atamaların boş başlaması;
görüntüleyenin yalnız izinli senaryo+üst proje kabuğu; erişim yönetiminde güvenli
404. 390/900/1440 genişlikleri, görünür klavye odağı, yatay taşma yok, console
warn/error yok. Bu dar M3 browser kontrolüdür; bütünleşik M8 gate yerine geçmez.
Canlı uygulama DB'sine migration veya atama yapılmadı.

M3 sıradaki dilim: proje temel rollerinin açık seçim + kazanan/kaybeden
önizlemesi + imzalı actor/target/stale kontrolüyle atomik uygulanması. Etki tüm
devralan/özel/legacy senaryolarda gösterilir; eski project administrator ve uzman
roller korunur. Üye/senaryo/atama sayısı kapalı sınırlarla kontrol edilir; son
süresiz proje yöneticisi zorunlu, audit fail-closed. Yeni konsol senaryosu açık
inherit/private seçimiyle yaratılacak; mevcut GitOps/model legacy varsayılanı
korunacak. Inherit için kalıcı proje yöneticisi, private için aktif üyeden açık
ilk yönetici gerekir; oluşturma anında yetki ve üyelik org kilidi altında yeniden
doğrulanacak. Testler deny/cross-scope/stale/expiry/audit rollback ve eşzamanlı
değişiklikleri kapsayacak.

## 12. Sürekli teslim raporu

M3 ortak veri uygulandı: catalog/0011 `data_access_mode` kapalı alanı ve
documents/0011 her senaryo/set grant'inde explicit ortak-consumer onayı,
onaylayan/zaman ve DB tutarlılık constraint'i. Varsayılan consumer-specific;
eski kayıtta onay false. Merkezi `documents.retrieve_scope` canlı normal grant
kesişimi veya açık shared consent + etkin exact consumer binding kararını
retrieval ve MCP ingestion kapsamına uygular. Shared geçişte ordinary consumer
grant eksik shared onayın yerine geçmez. İptal onayı temizler; regrant geri açmaz.
Senaryo veri düzeni ve veri yöneticisi ortak kullanım ekranları ayrı; imzalı
veri-modu formu actor/target/süre ve atomik expected-mode kontrolüyle stale ret.
Onay ekranı mevcut/gelecekteki izinli istemcilerin kapsamını açıkça bildirir.

Kanıt: `.tmp/shared-consent-foundation.xml` 25 passed/1 PG skip (20.93 s).
`.tmp/shared-consent-postgres.xml` 36 passed/1 failed (36.97 s); iki layout'ta
22 ACL retrieval testi geçti. Yeni MCP testinde hatayı yanlış JSON seviyesinde
arayan assertion düzeltildi, mevcut protokol değiştirilmedi.
`.tmp/shared-consent-http-pg.xml` 18 passed (30.32 s): MCP gerçek HTTP allow/deny,
RLS, shared grant ve konsol stale/forged/actor/cross-scope/ack testleri.
12 ilgili source/test dosyada container mypy temiz; ruff/migration drift/system
check temiz. `.tmp/shared-consent-broad.xml`: 536 passed, 8 PG-only skipped
(199.35 s), console/documents/catalog/identity. İzole browser: senaryo yöneticisi
veri modunu değiştirir ama veri onayı ekranında güvenli 404 alır; exact veri
yöneticisi mevcut/gelecek istemci kapsamını işaretleyerek yalnız seçili seti
onaylar. Diğer set eksik onay olarak kalır. 390px yatay taşma yok; düğmenin
renk kontrastı düzeltildi. İzin iptali sonrası iki set de eksik onay durumuna
döndü; desktop/390px kontrolü tamamlandı, browser console warn/error yok.
Bu eklemeli migrations yalnız izole test ortamında; canlı cutover yok.

M3 önceki dilimin ek PG HTTP/duplicate-submit/initial-access doğrulaması:
`.tmp/access-create-pg-http.xml` 11 passed (26.87 s). Devralınan kişilerin
senaryo sayfasında listelendiği ayrıca gerçek browser ile görüldü.

M3 proje/oluşturma son durumu: proje temel rol önizleme ve atomik uygulama;
scenario/project actor-target-baseline imzası, 10 dakika, kalıcı yönetici ve
org kilidi. catalog/0010 proje receipt alanları eklemeli; canlı uygulamaya
uygulanmadı. Yeni konsol senaryoları açık inherit/private seçer. GitOps/model
legacy kalır; özel ilk yönetici oluşturandan bağımsız açık seçimdir. Senaryo
sayfası etkin devralınan temel atamaları ve ayrı uzman görevlerini gösterir.
Eski sürüme dönüşte mode-aware yetki katmanı korunmalı: eski binary private
modu yok sayarak görünürlüğü genişletebilir. ADR-0019 ve kullanıcı/güvenlik
rehberleri bu davranışla güncellendi.

Kanıt: `.tmp/project-access-postgres.xml` 14 passed (321.99 s), gerçek proje ve
senaryo eşzamanlı önizleme; `.tmp/project-access-create.xml` 9 passed/1 PG-only
skip. Geniş `.tmp/project-create-broad.xml` 478 passed/10 skipped/1 failed;
tek hata yeni fixture'ın 403/404 beklentisiydi, önceki dar 403 kontrolü korunarak
düzeltildi. `.tmp/access-ui-final.xml` 48 passed (21.54 s), ilgili ekranlar ve
gezinti tekrar geçti. Container mypy 10 dosyada temiz; ruff, migration drift ve
system check temiz. Ek PG HTTP/duplicate-submit/initial audit doğrulaması da
`.tmp/access-create-pg-http.xml` kaydında 11 passed ile tamamlandı.
Test fixture'ları yeni formda açık ilk yönetici seçer; bu ayrı kullanıcıdır,
eski dar editor/release deny testleri geniş manager ile maskelenmez.

İzole browser: proje yönetimi linkinden yeni proje düzenleyeni önizleyip uygulama;
yeni inherit senaryosu oluşturma, yetkili detay ve operasyon gezinmesinin görünmesi
başarılı. Ana uygulama web/worker/Redis kapalı; PostgreSQL/MinIO healthy olarak
yeniden kontrol edildi. Bu runtime kaydı gözlem anına aittir, devamda yeniden
sorgulanır. Tam M8 gate hâlâ açık.

M3 consumer paketleri: normal form yalnız kapalı ürün seçeneklerini kabul eder;
ham capabilities/preset POST'u ret. Varsayılan yalnız workflow_run; araçlar ve
yan etki açık seçim, yan etki için tool_call zorunlu. Eski kayıtların teknik
değerleri korunur, sunucu yeniden org/kapsam yetkisi denetler ve binding+audit
atomiktir. İstemci/senaryo seçenekleri insan tarafından okunabilir adları gösterir.
`.tmp/consumer-packages.xml`: 46 passed. Gerçek izole browser'da eksik araç
seçimi kaydı engelledi; düzeltme sonrası yalnız workflow_run bağı oluşturuldu.

M3 ortak eylemler: `identity.scenario_actions` yetkiyi readiness'ten ayrı türetir.
Compile=edit veya release; publish/lifecycle=release olarak ayrı kalır. Django
ve React aynı allowed_actions kullanır; React org.can_write fallback'i kaldırıldı.
Kanonik aday kaydı org→scenario kilidinde tekrar yetkilendirilir; audit atomik.
`.tmp/action-unification-postgres.xml`: 85 passed (40.25 s), gerçek PG üzerinde
editor candidate/denied traffic, açık sayfadan sonra rol iptali, audit rollback,
foreign hedef, paketler ve builder regresyonu. İlk SQLite koşusunda iki yeni
testin enum yazımı ve audit mock'un eski konumu düzeltildi; kontroller korunur.
9 dosyada container mypy temiz; frontend tsc + 59 Vitest + build başarılı.
Geniş `.tmp/action-broad.xml`: 621 passed, 5 PG-only skip, 1 eski minimum öneri
yetki beklentisi. Bu artık onaylı editor candidate akışıdır; test yeni allow +
rol iptali sonrası deny ile güncellendi. `.tmp/action-final-regression.xml`:
31 passed (24.30 s). Browser'da devralınan düzenleyen aday önerisini yükledi;
yayın düğmesi kapalı kaldı, console warn/error yok. Geçici seçim temizlendi.
Koşunun duvar zamanı oturum kesintisi içeriyor; performans kanıtı değildir.

M4 temel: releases/0004 ScenarioRevision + FORCE RLS ve insert provenance /
UPDATE-DELETE ret trigger'ı. Snapshot 50 rol/4 MiB/1000 veri piniyle sınırlı;
artifacts, workflow, legacy veri pinleri ve tam scope doğrulanır. Kaynak release /
workflow korunur; reusable artifact kayıtları kaldırılmaz. Bu aşamada kayıt
hazırlanabilir, runtime seçimi değişmedi. Rol veya audit hatası kayıt bırakmaz;
aynı release için eşzamanlı hazırlama tek revision/receipt üretir.
`.tmp/revision-scope-verified.xml`: 22 passed, 2 SQLite-branch skipped (25.86 s),
PG immutability, RLS, concurrency, foreign pin, scope/checksum ve provisioning
envanteri. Önceki geniş 50 testte compiler/authoring de geçti; test fixture'ındaki
DocumentSet alan adı ve yeni tablonun grant-template envanteri düzeltildi.
Grant template yalnız SELECT/INSERT verir; hiçbir canlı rol/grant uygulanmadı.
İlk 4 dosya mypy temiz; son scope/exception ekleri sonrası tekrar bekliyor.

M4 sonraki bağlama: Scenario/Release için kapalı execution_contract işareti;
eski kayıt legacy kalır. Run yeni revision'a PROTECT FK ile bağlanır. Snapshot
modunda manifest/rol/body/compiled graph tek kayıttan okunur, eksik kayıtta legacy
fallback yapılmaz. Yeni snapshot workflow'ları ayrı compiler sözleşmesiyle eski
worker tarafından reddedilir; yeni worker mevcut legacy sözleşmesini korur.
Wait/branch/child/compensation yolları aynı Run pin'ini kullanır. Yeni varsayılan,
runtime ve restart/mixed-worker testleri geçmeden açılmaz; canlı backfill yok.

M4 bağlama kanıtı: `.tmp/revision-execution-postgres.xml` 71 passed (38.12 s);
`.tmp/revision-resume-postgres.xml` 12 passed (27.14 s), yayın sonrası wait/child
devamı ve deferred revision zorunluluğu; `.tmp/revision-parallel-postgres.xml`
32 passed (31.22 s), paralel join ve compiler uyuşmazlığında claim ret.
14 runtime dosyada container mypy temiz; 512 dosyada ruff/format, migration drift
ve Django system check temiz. `.tmp/revision-runtime-broad-postgres.xml` 299 passed,
1 yeni test helper çağrı hatası (rollback parametre adı); uygulama API'si korunup
test düzeltildi ve tekrar kontrol ediliyor. Snapshot bundle tek snapshot okumasıyla
hazırlanır; her rol için aynı kayıt tekrar okunmaz. Capture-workflow yazma yarışı
satır kilidiyle kapatıldı. Tüm migrations yalnız test veritabanlarında uygulandı.

M4 snapshot son regresyonu `.tmp/revision-final-pg.xml`: 72 passed (29.73 s),
evaluation/promotion/rollback ve snapshot başına tek bundle okuması dahil.
M4 veri seçimi temeli: catalog/0013 kapalı opt-in; workflows/0020 iki immutable,
FORCE RLS tablo, exact FK/scope, deferred completeness ve seçilmiş nesil koruması.
Servis gerçek durable transaction ister; mevcut node transaction'ına gömülemez.
`.tmp/retrieval-selection-retry-pg.xml`: 11 passed (26.52 s). Yeni test fixture'ının
olmayan grant alanı ve fazla lease süresi düzeltildi. `.tmp/retrieval-selection-acl-pg.xml`:
35 passed/1 test rolü EXECUTE grant eksikliği; yalnız geçici test rolü düzeltildi.
`.tmp/retrieval-selection-final-pg.xml`: 23 passed, 2 SQLite-branch skip (32.51 s),
iki layout'ta gerçek keyword okuma, superseded exact seçim, canlı grant iptali,
tombstone, korumalı cleanup, RLS, concurrency ve grant-template envanteri.
10 ilgili dosyada container mypy temiz. Runtime/branch/agent entegrasyonu sonraki
dilimde uygulandı: `.tmp/retrieval-boundary-pg.xml` 76 passed (42.11 s),
`.tmp/retrieval-branch-pg.xml` 49 passed (39.37 s),
`.tmp/retrieval-agent-first-pg.xml` 67 passed (32.81 s),
`.tmp/retrieval-agent-boundary-pg.xml` 1 passed (24.96 s).
Provider I/O öncesi ayrı bağlantıdan receipt görünürlüğü, transient retry'da
aynı seçim, sonraki adımda yeni nesil; agent planner kararının yeniden
üretilmemesi kanıtlandı. Branch process kaybı mevcut recovery-required
politikasını korur; geç worker reddedilir. Yeni test önce otomatik retry
varsaymıştı; uygulama politikası değiştirilmeden test düzeltildi.

2026-09-10 devam incelemesi: HTTP gateway admission/execution sınırı ayrı;
konsol middleware'i, evaluation worker ve bazı otomasyon çağrıları ise geniş
transaction içinde çalışıyor. Active-generation durable receipt bu sınırın
içinde oluşturulamaz. Yeni varsayılan açılmadan evaluation admission, execution
ve sonuç/audit işlemleri kısa tenant-scope transaction'larına ayrılacak; konsolun
ilgili girişlerinde aynı ayrım uygulanacak. RLS tenant bağlamı session-wide
yapılmayacak, durable kayıt savepoint'e indirgenmeyecek. Auth/audit ve başarısız
evaluation'ın canlı yayını değiştirmemesi testlerle korunacak. Bu açık kusur
nedeniyle M4 tamamlandı sayılmaz. Agent süre bütçesi selection checkpoint'leri
boyunca birikir; sonlu sayı doğrulaması ve gerçek HTTP/branch commit testleri
devam ediyor. Canlı PostgreSQL/MinIO healthy; web/worker/Redis çalışmıyor,
8000 health erişilemedi. Migration yalnız izole test DB'lerinde uygulanıyor.

M4 devam kanıtı: `.tmp/retrieval-resume-pg.xml` 27 passed (37.36 s), gerçek
sync HTTP commit/replay, parallel/for_each veri yenilemesi ve agent süre bütçesi.
`.tmp/evaluation-durable-pg.xml` 207 passed, 1 SQLite-only skip (72.22 s):
evaluation/builder/konsol/tenant/runtime regresyonu. `.tmp/operator-selection-pg.xml`
4 passed (30.52 s), `.tmp/operator-worker-selection-pg.xml` 6 passed (33.30 s):
konsol soru/değerlendirme ve gerçek Celery task girişinde owner/non-owner RLS,
ayrı bağlantıdan receipt görünürlüğü, duplicate delivery ve üyelik iptali.
`.tmp/evaluation-owner-pg.xml` 9 passed, 1 SQLite-only skip (25.96 s):
evaluation sahipliği commit'ler boyunca korunur, hata/reconnect sonrası eski
owner durur. Tek/son case sırasında gelen iptal finalization'da yeniden okunur.

Uygulanan sınır düzeltmesi: `operator_transaction` her kısa bölümde üyelik
kapsamını yeniden türetir; yalnız açıkça işaretli ask/eval/Studio candidate/
scenario candidate view'ları geniş middleware transaction'ından ayrılır.
Candidate hazırlama, evaluation admission, çalışma ve sonuç/audit ayrı commit'ler.
Question worker tenant/run session advisory lock kullanır; session değişiminde
işlem reddedilir. Tenant RLS bağlamı hâlâ transaction-local. Yeni servis DB
bağlantı affinity gereksinimini mevcut ingestion modeliyle paylaşır.
Kısıtlı rol testi Studio sonuç-projection'ında eksik tenant scope'u ortaya
çıkardı; sonuç okuması ayrı operator scope + tekrar yetki kontrolüne alındı.
İlk `.tmp/candidate-selection-pg.xml` 2 passed/2 yeni test status beklenti
hatası (mevcut API başarılı create=201); API korunup test düzeltildi ve cases
listesinin de dolu olması açıkça kontrol ediliyor.
Kalıcı karar [ADR-0021](../../adr/0021-scenario-revision-and-durable-data-selection.md).
Son `.tmp/evaluation-selection-final-pg.xml`: 196 passed, 1 SQLite-only skip
(88.85 s); beş operator/worker yolunun owner/non-owner gerçek HTTP/task testi
dahil. 13 dosyada container mypy temiz. Geniş
`.tmp/revision-runtime-final-pg.xml`: 389 passed, 1 yeni snapshot testinde
eksik `document_set_ids` beklentisi (113.00 s); kapalı sözleşmeye alan eklenip
`.tmp/revision-cancel-final-pg.xml` 26 passed (28.96 s) ile düzeltme ve son-case
iptali doğrulandı. Ruff, 516 dosyada format, migration drift, system check ve
diff whitespace kontrolü temiz. M4 son diff incelemesi: yeni execution/receipt
metadata'sı yetki vermez; projection dahil kısa scope'lar testli; node bütçesi
yenilenmez; candidate audit hatasında canlı yayın etkilenmez. Connection-affinity
ve receipt retention gereksinimi ADR'de. Canlı geçiş/bütünleşik browser gate açık.

M5 ilk dilim tasarımı: REST/Confluence global platform kataloglarını ortak,
immutable `Connection` kimliği altında birleştir; her connection exact eski
profile revision'ına PROTECT referans ve doğrulanmış config checksum taşır.
Config/secret veya grant'in ikinci kopyası oluşturulmaz. Kaynakların mevcut PK,
profile/contract/cursor/schedule ve document-set bağlantıları korunur; eklemeli
connection pointer aynı profille eşleşmek zorundadır. Global profile kayıtları
global kalır; connection varlığı tenant/set grant'inin yerine geçmez. Ortak
resolver mevcut typed validator/status/tenant-set grant kontrollerini kullanır.
Source oluşturma bu kimliği bağlar; eski kaynaklarda açık, bounded ve idempotent
eşleme gerekir, sessiz kaynak/credential değişimi yok. REST/MCP araç profilleri,
model/OCR/embedding ve MCP resource türleri ayrı typed adapter dilimlerinde
incelenecek; ilk iki ingestion türünden genel yetki türetilmeyecek. Ardından
mevcut staged job/outbox kimliklerini koruyan ortak ingestion iş sözleşmesi ve
REST/Confluence dispatch geçişi yapılacak; iki bağımsız status otoritesi kurulmaz.
Yeni üretim bağımlılığı, canlı egress, grant, source veya DB değişimi yok.

M5 Connection ilk uygulama: ingestion/0021 global, immutable ve typed profile
OneToOne kimliği, Source nullable PROTECT pointer, exact SQL lineage/config
koruması ve downgrade ret. Global profile'ların tarihsel kimlikleri migration'da
200'lük okuma parçalarıyla eşlenir; config checksum hesabı migration içinde
sabitlenmiştir, runtime koduna bağımlı değildir. Profile'lar kopyalanmaz;
kimlikteki referanslar korunur. Kaynaklar migration'da sessizce değiştirilmez.
Yeni platform profile kaydı kimliğini atomik oluşturur. Normal uygulama rolü
Connection/global profile için yalnız SELECT kullanır; Source oluşturma global
profile'a FOR UPDATE veya INSERT yetkisi gerektirmez. Exact eski kaynağı bağlayan
servis org→source kilidi, veri yöneticisi kontrolü, idempotency ve fail-closed
audit içerir; canlı grant/disabled kontrolleri halen uygulanır.

`.tmp/connection-integration-first-pg.xml`: 44 passed, 2 SQLite-only skip
(30.89 s). `.tmp/connection-identity-pg.xml`: 4 passed/2 yeni testin SQLSTATE
55000 için yanlış IntegrityError beklentisi; OperationalError + aynı kesin hata
kodu ile düzeltilmiştir. `.tmp/connection-verified-pg.xml`: 43 passed (31.94 s),
gerçek concurrency, migration mapping replay/checksum, readonly global catalog
rolüyle kaynak oluşturma, canlı grant iptali ve profile disable dahil.
Konsol genişlemesi: `.tmp/connection-console-final-pg.xml` 20 passed/2 skip/7
fixture hatası; eski fixture auth_mode=none iken secret_ref taşıyordu. Gerçek
profile validator'ı korunup fixture'ın mevcut secret-ref niyetine uygun açık
bearer modu seçildi; tekrar sürüyor. Üretimde benzer eski tutarsız profiller yeni
bağlantı akışına geçmeden düzeltilmeli; legacy kaynaklar sessizce yükseltilmez.
İlk mypy nullable profile ID uyarıları kapalı tür koşuluyla giderildi; tekrar
sürüyor. İlk konsol komutundaki bulunmayan ek test yolu collection yapmadı;
geçerli test yollarıyla yeniden başlatıldı. Canlı migration/grant uygulanmadı.

Connection kapanan otomatik dilim: `.tmp/connection-console-verified-pg.xml`
18 passed (28.51 s); permission/audit rollback, exact source mapping, non-owner
readonly katalog, migration replay ve konsol komşu yolları. 7 dosyada container
mypy temiz. Yeni schema sadece test DB'sinde; Source pointer'ın canlı toplu
eşlemesi yapılmadı. Global katalogdaki eksik kimlikleri üretim uygulama rolüne
yazma izni vererek telafi etmeme kararı alındı: migration ve platform profile
kaydı kimlik oluşturur, runtime rolü yalnız okur. Bu aşama bağlantı kimliğini
ortaklaştırır; diğer profile türleri ve UI migration kabulü hâlâ açık.

M5 ortak Job/Outbox uygulama sözleşmesi: mevcut staged job/outbox tablosu,
PK/public_id/FK ve legacy task adları korunacak; kapalı `kind` ile index_build,
rest_sync, confluence_sync ayrılacak. Build alanları yalnız build türünde zorunlu;
connector işinde exact source ve eski protokol-run kimliği zorunlu olacak.
Eski Run kayıtları cursor/snapshot/protokol evidence'i olarak kalır; ortak işe
bağlananlarda status artık ortak işin atomik uyumluluk projection'ıdır. Bağlı
legacy task kendi başına claim/yazma yapamaz. SQL guard ve her snapshot write
sınırı job→protocol-run kilidi, kind/scope/attempt/state kontrolü uygular.
Request checksum source/profile/contract ve source-input checksum'unu içerir;
aktif aynı intent dedup, başka intent busy ret; tek aktif source writer.
Outbox aynı admission transaction'ındadır; mesajda yalnız kimlik bulunur.
Eski build claim/complete/retry/reconcile yolları connector türünü reddeder;
connector dispatcher ayrı adapter üzerinden aynı job/outbox otoritesini kullanır.
Worker contract yeni türlerden önce yükseltilir; mevcut iş türü uyumu korunur.
Belirsiz/expired owner kör yeniden çalıştırılmaz; reconciliation_required;
cancel/retry ve eski response/error kontratları compatibility projection'ıyla
korunur. Connector/source/profile grant ve belge quarantine kontrolleri her
gerçek okuma/yazmada geçerlidir. Legacy job/run geçmişi/backfill canlıda otomatik
taşınmaz; yeni admission geçişi izolasyon/duplicate/lost-message/stale-worker ve
rollback testlerinden önce varsayılan yapılmaz.

M5 Job uygulama ilerlemesi: ingestion/0022 kapalı job kind ve exact nullable
target şeması; ingestion/0023 tenant/source/run lineage, immutable iş kimliği,
transaction sonunda protocol status/attempt/error projection ve snapshot evidence
guard'ı. Mevcut build girişleri connector kind'ını reddeder; konsol build listesi
nullable connector hedeflerini indeks işi diye göstermez. Worker contract 6.
Outbox artık kind üzerinden adapter seçer, job→outbox kilit sırası kullanır;
çalışan işi yeniden queued yapmaz. Explicit connector admission exact veri yöneticisi,
canlı profile/grant, immutable Connection ve source-input checksum ile sınırlandırılır.
Her snapshot yazımı job/attempt sahipliğini ve güncel kaynak/grant'i doğrular;
candidate ve başarı projection'ı aynı transaction'dadır. Legacy task bağlı run'ı
claim edemez; timeout/unknown owner reconciliation_required olur. REST/Confluence
manuel UI ve schedule hâlâ legacy admission kullanır; geçiş henüz etkin değildir.

`.tmp/typed-job-build-compat-pg.xml`: 21 passed (32.13 s). İlk yeni adapter
`.tmp/connector-job-first-pg.xml`: 43 passed / 1 Confluence fixture network policy
eksikliği; test fixture düzeltildi. İkinci `.tmp/connector-job-authority-pg.xml`:
25 passed / 1 yeni testte beklenen immutable hata kodundan önce evidence guard
çalıştı; lineage trigger sırası açıkça öne alındı, yeniden doğrulanacak. İlk
8-file mypy yalnız connector_jobs nullable ID ve enum-map tiplerini bildirdi;
explicit kapalı dallarla düzeltildi, tekrar bekliyor. Bu aşamada otomatik suite
başarısı veya M5 tamamlanması iddia edilmez. Canlı DB/grant/source değiştirilmedi.

Geniş M5 regresyon `.tmp/ingestion-common-job-regression-pg.xml`: 218 passed,
3 beklenen skip, 2 hata (73.74 s). Ortak job/connector testleri geçti. Bir shared
vector test rolü yeni M4 receipt tablosunun production template'te mevcut SELECT
iznini taşımıyordu. Diğer hata gerçek M4 uyumsuzluğu: legacy store silmede eklenen
Python row lock SELECT-only DDL caller kontratını bozuyor ve doğrudan migration-
owned SQL çağrısını receipt kontrolü dışında bırakıyor. Düzeltme planı: receipt
kontrolü + index row lock + store_ready düşürme aynı migration-owned DDL function'a
taşınacak. Runtime'a ek UPDATE/schema yetkisi verilmeyecek; direct SQL bypass ve
mevcut readonly caller birlikte test edilecek. Bu bulgu M4/M5 tamamlanmasını
iddia etmeden önce giderilecek.

M5 otomatik doğrulama ilerlemesi: `.tmp/connector-job-integration-pg.xml` 65 passed /
1 testte Django cached related run yeniden okunmadığı için eski snapshot_complete
beklentisi; fixture refresh ile düzeltildi. `.tmp/connector-job-verified-pg.xml`
25 passed (51.77 s): gerçek concurrent admission/claim, non-owner RLS, console
opt-in, scheduler ve broker sonrası automation delivery dahil. Son
`.tmp/connector-job-final-pg.xml` 53 passed (60.31 s); rollback sonrası yeni blob
cleanup, metadata commit belirsizliğinde referanslı blob'u koruma ve legacy
REST/Confluence birlikte testli. Ortak claim durable commit ister. Yazma kilitleri
org→job→protocol→source sırasına, eski/yeni scheduler admission da org-first
sırasına getirildi; tenant içi yazma throughput etkisi workload gate'inde açık.
Cancel/retry exact veri yöneticisinde; çalışan POST iptali unknown outcome olarak
reconciliation ister. İşletim kararı [ADR-0022](../../adr/0022-shared-connection-and-ingestion-job-authority.md).

M4 koruma düzeltmesi ingestion/0025: legacy DDL function receipt ve row lock'u
kendi yetkili sınırında kontrol eder, başarılı drop sonrası store_ready=false
yazar. Readonly DDL caller ve direct-SQL bypass testleri aynı anda korunur.
İlk migration denemesi PostgreSQL format `%I` ifadesinin parametre placeholder'ı
sayılmasıyla test setup'ta durdu; schema execute params=None ile düzeltildi.
`.tmp/ingestion-selection-verified-pg.xml`: 80 passed / 1 beklenen SQLite guard
skip (74.94 s). 10-file container mypy temiz. Ruff ve migration drift temiz.
Canlı DB uygulanmadı; browser ve worker cutover kabulü açık.

M5 MCP sonraki adapter tasarımı: mevcut tools/call/catalog discovery, resource
ingestion yetkisi değildir. MCP 2025-06-18'in açıkça desteklenen bounded HTTP
alt kümesi seçilecek: initialize/capability + version doğrulama, initialized,
resources/list sayfalama ve resources/read. Sunucunun `resources` capability'si
zorunlu; dosya/HTTP resource URI yalnız opaque kimlik, host filesystem veya URI'ye
ayrı HTTP erişimi yok. Tam scan bitmeden missing reconciliation yok; text/blob
decoded boyut/MIME/URI eşleşmesi sınırlandırılır. Server instructions, tool
results, roots/sampling/elicitation yetki ya da workflow talimatı üretmez.
İlk transport saf typed client olarak test edilecek; ardından exact katalog/grant,
Source ve ortak Job/cursor bağlamına bağlanacak. Kaynaklar:
[Resources](https://modelcontextprotocol.io/specification/2025-06-18/server/resources),
[Lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle),
[Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).

MCP resource transport uygulandı (`mcp_resources.py`): pinned endpoint, kaynak URI
scope'u, handshake/capability/version, exact JSON-RPC ID, JSON/SSE, text/base64 ve
decoded MIME/boyut sınırları; her request öncesi canlı authorization callback.
Client tek snapshot attempt'tir, yalnız generator tamamen bitince snapshot_complete
olur. Henüz hiçbir public source/job admission'a bağlı değildir. `.tmp/mcp-resource-
transport-first.xml`: 48 passed (0.14 s); mevcut MCP tools adapter ile birlikte.
Shared HTTP adapter'a yalnız opt-in absolute deadline eklendi; TLS doğrulaması
korunarak socket shutdown ile header/body bekleme kesilir. Eski çağrılar deadline
vermez ve kontratları korunur. MCP DNS lookup dört worker/slot ile sınırlıdır;
timeout sonrası slot gerçek resolver bitmeden yeniden kullanılmaz, kuyruk birikmez.
OS resolver zorla sonlandırılmaz; proses shutdown süresi için resolver davranışı
operasyonel risktir. `.tmp/mcp-resource-deadline-verified.xml`: 82 passed (0.31 s),
stalled DNS/capacity, stalled HTTP abort, MCP tool ve mevcut HTTP/egress testleri.
Deadline öncesi MCP client mypy temizdi; genişletilmiş HTTP/client mypy tekrar bekliyor.

MCP katalog/Source eşleme sözleşmesi: platform-owned immutable
`McpResourceProfile` (closed destination, protocol, secret reference, MIME ve limits)
ortak Connection'a exact OneToOne bağlanacak. Tenant/document-set grant'i yalnız
resource okumaya izin verir; tools katalog/grant'i devralınmaz. Yeni MCP Source
profile'a ikinci pointer taşımayacak; Connection üzerinden çözülecek, URI prefix
kapsamı source config'inde kapalı ve sınırlı olacak. Profile register/disable/grant
yalnız platform admin, source oluşturma exact data manager; audit fail-closed.
SQL immutable profile/Connection, source scope/lineage ve grant tenant/set eşleşmesi
uygular; tenant grant RLS FORCE ve default deny. Yeni tablolar için runtime role
template sadece gerekli izinlerle güncellenecek, canlı grant uygulanmayacak.
Bu katalog dilimi hazır olsa bile ortak job/snapshot/cursor ve cancel/fencing
entegrasyonu test edilmeden kaynak için çalıştırma UI/admission açılmayacak.

MCP katalog ilk doğrulama `.tmp/mcp-catalog-first-pg.xml`: 91 passed / 1 failed
(30.85 s). Non-owner test yeni grant politikasının eski app.tenant_id ayarını
kullandığını ortaya çıkardı; mevcut bounded tenant_scope helper'ına düzeltildi.
Yetkisiz erişim açılmadı, yetkili runtime read yanlışlıkla reddediliyordu.
Kaynak yetkisi live/revoke, platform sınırı, immutable SQL, audit rollback, TLS
handshake deadline ve eski REST/Confluence Connection testleri diğer kontrollerde
geçti. Mypy iki nullable model relation'ını bildirdi; explicit relation guard ile
düzeltildi. Tekrar doğrulama bekleniyor, canlı migration/grant uygulanmadı.

MCP snapshot/job tasarımı: yeni `mcp_resource_sync` aynı Job/Outbox'a eklenecek;
ikinci bağımsız run status tablosu yaratılmayacak. `ResourceSnapshot` işin exact
OneToOne kanıtı (attempt, tam tarama, sayaçlar, candidate) olacak; state Job'dan
okunur. `SourceDocumentCursor` exact source/opaque URI hash ve URI, checksum,
document/version, last-seen job+attempt tutar. Kısmi scan missing üretemez;
başarı + candidate + snapshot kanıtı aynı fenced transaction'dadır. MCP remote
okumaları ve secret çözümü öncesinde canlı kaynak/grant/job-attempt kontrolü,
her belge/cursor yazımında tekrar kontrol zorunlu. Retry aynı job'ın yeni attempt'i
ile eski last-seen işaretlerini ayırır. Yeni UI/schedule admission bu sınırlı
adapter ve non-owner/failure/duplicate testleri bitmeden açılmayacak.

MCP katalog doğrulaması: `.tmp/mcp-catalog-verified-pg.xml` 113 passed / 1 testte
beklenen DB exception sınıfı uyuşmazlığı (31.99 s); runtime izin yazımı gerektiği
gibi PostgreSQL ProgrammingError ile reddedildi, assertion bu exact sınıfa
düzeltildi. `.tmp/mcp-catalog-authority-pg.xml`: 19 passed (28.08 s).
6-file mypy temiz. ingestion/0026–0027 additive katalog/grant ve scope guard'ları;
Source yalnız Connection pointer'ı kullanır, platform sınırının altına daralır.

MCP ortak iş adapter'ı uygulandı: ingestion/0028–0029 ResourceSnapshot kanıtı,
SourceDocumentCursor ve DB owner/provenance/deferred completion guard'ları.
Worker contract 7; resource işinde status yalnız ortak Job'da. Snapshot attempt
ve cursor last-seen attempt ayrı denemeleri fence eder. İzin iptali her MCP
request öncesinde, yerel yazım ve final snapshot transaction'ında yeniden okunur.
Tam tarama candidate/no-op üretir; yarım scan missing üretmez, belge checksum+MIME
aynıysa mevcut version yeniden kullanılır. Ortak candidate baseline MCP'nin
başarılı kanıtını da içerir. `.tmp/mcp-snapshot-first-pg.xml`: 49 passed (92.68 s),
9 MCP snapshot testi + eski ortak job/REST regresyonu; gerçek non-owner RLS,
duplicate/partial/retry/cancel/revoke ve SQL bypass negatifleri dahil. 4-file mypy
temiz. Katalog ve snapshot doğrudan servis seviyesinde hazır; konsol/schedule,
worker rollout ve gerçek MCP server testi tamamlanmadı. Canlı DB değişmedi.

MCP konsol admission dilimi: etkin ortak-job geçiş bayrağı altında yalnız exact
koleksiyon yöneticisine onaylı bağlantıdan kaynak oluşturma sunulacak. Görüntüleme
mevcut doküman seti metadata yetkisini kullanacak; source detail'in eski yalnız
organization filtresi set filtresiyle daraltılacak. Kaynak adı ve bağlantı seçimi
normal akış; opsiyonel URI alt kapsamı gelişmiş alanda, credentials/host/örnek içerik
HTML'e taşınmayacak. Form hata değerleri korunacak. Ortak job iptal/yeniden deneme
aynı exact source/set yetkisiyle; mevcut REST/Confluence URL'leri geçerli kalır.
MCP schedule desteği henüz yoksa bu eylem gösterilmez ve POST server-side reddedilir.
Bayrak kapalıyken MCP oluşturma/başlatma sunulmaz, mevcut kaynak/job okunabilir ve
çalışan job yönetimi korunur. Browser kabulü ve tam sihirbaz M6/M7'de ayrıca açık.

MCP konsol dilimi uygulandı ve doğrulandı: kaynak oluşturma/idempotent tekrar,
exact set erişimi, ortak iş iptal/yeniden deneme ve bayrak kapalı yönetimi.
Aktif işi olan kaynakta ikinci başlatma eylemi gizlenir; sunucu admission kontrolü
korunur. `.tmp/mcp-ingestion-regression-pg.xml`: 193 passed (110.09 s);
`.tmp/mcp-console-first-pg.xml`: 35 passed (34.19 s);
`.tmp/mcp-console-final-pg.xml`: 17 passed (33.63 s);
son readiness/redirect düzeltmesi `.tmp/mcp-console-busy-pg.xml`: 17 passed
(61.87 s). Console/service beş dosya mypy temiz. Ruff temiz; views formatlandı.
İzole SQLite 8109 browser denemesinde uzun Türkçe ad, hatalı kapsam ve değerlerin
korunması, onaylı bağlantıyla kayıt, queued/cancel/retry gözlendi. 390/900/1440
genişliklerinde yatay taşma yok; hata özetine klavye odağı doğrulandı. Menü kökü
ve form hata odağı düzeltildi. Son busy-button düzeltmesinin browser tekrarı açık.
Bu fixture memory broker kullanır; gerçek MCP sunucusu veya worker/full-stack
kanıtı değildir. Canlı uygulama DB'si ve izinleri değiştirilmedi.

M6 ilk uygulama dilimi: onaylı REST bağlantısı → görsel/ileri mapping → şemadan
typed input → güvenli özet/kayıt. Aynı canonical REST validator ve Connection/Source
servisleri kullanılacak. Tenant yöneticisi endpoint/credential otoritesi kazanmaz;
platform bağlantı kaydı mevcut yetkili yoldadır. State sunucu session'ında en çok
beş taslak ve bir saat ile sınırlı; örnek response veya credential saklanmaz.
Contract+Source+audit tek transaction; org kilidi altında canlı grant/set/profile
yeniden doğrulaması ve aynı intent için exact-payload idempotency. Kayıt tek başına
network veya embedding başlatmaz. Görsel/ileri dönüşüm bilinmeyen alanları sessizce
atmayacak; canonical schema tam temsil edilecek. Bu ilk dilimden sonra güvenli
bağlantı testi, periyodik/hazırlama seçenekleri, yeni koleksiyon, immutable revision
edit/cutover ve tam browser kabulü M6 kapsamında açık kalır.

M6 ilk kurulum uygulandı: `rest_setup.py`, `rest_setup_forms.py`,
`rest_setup_views.py` ve iki template. Kaynak yetkisi mevcut canonical servislerden;
sunucu session'ında actor/set/draft özeti imzalı, beş taslak/bir saat/160 KB sınırı.
Cookie session backend'i bu ekranı açmaz. Onaylı profil listesi exact set/active,
her adımda tekrar doğrulanır. Görsel/ileri mapping aynı validator, kayıpsız dönüşüm
sağlanamıyorsa ileri görünümde devam zorunluluğu; dört pagination ve typed input.
Sentetik preview en çok 100 KB/20 item/16 JSON depth; içerik session'a, audit'e
veya HTML'e yansıtılmaz. Genel JSON field'a opt-in depth limiti ve parser recursion
hatasını validation'a çevirme eklendi; eski alanların depth davranışı değişmez.
Atomik kayıt ve source audit failure rollback, exact intent conflict/replay,
iki gerçek PG connection ile eşzamanlı aynı intent testi ve non-owner read-only
katalog yolu geçti. Dış bağlantı testi henüz yok; kayıt network/dispatch yapmaz.

M6 kanıtı: `.tmp/rest-setup-first-pg.xml` 20 passed / 2 failed (38.81 s): ayrı
belge placeholder örneği canonical `{input:id}` biçimine düzeltildi; test rolüne
mevcut tenant helper EXECUTE izni eklendi (canlı izin değişmedi).
`.tmp/rest-setup-verified-pg.xml` 39 passed (52.88 s), MCP ve eski connector UI dahil.
`.tmp/rest-setup-preview-pg.xml` 32 passed / 1 failed (52.87 s): Python 3.13 parser'ı
2000 seviyeli JSON'u kabul ettiği için yeni setup alanlarına explicit depth sınırı
eklendi; `.tmp/rest-setup-preview-final-pg.xml` 33 passed (51.27 s).
`.tmp/rest-setup-atomic-pg.xml` 26 passed (48.96 s), audit ve concurrent replay dahil.
Üç yeni source dosyası `mypy --check-untyped-defs` temiz; son opt-in depth değişikliği
sonrası dört dosya type check tekrar açık. Ruff/format ve system/migration drift
kontrolleri temiz (views son format düzeltmesi dahil). Yeni migration yok.
İzole 8109 browser: onaylı profil → hatalı path/value recovery/focus → dört adım
→ Source 2 kaydı; 390 ve 900 genişlikte scrollWidth=clientWidth, 1440 görsel özet
incelemesi, uzun Türkçe adlar. Viewport override sıfırlandı. MCP busy-action browser
tekrarı da geçti. Son sentetik-preview eklemesinin browser tekrarı ve tam stack/rol
matrisi açık; fixture memory broker'dır ve gerçek egress yapılmadı.

Sonraki M6 dilimi güvenli bağlantı testidir: aynı REST request renderer üzerinden
tek bounded istek; SSRF/TLS/IP pinning, DNS dahil absolute deadline, canlı exact
grant ve audit. Dış I/O boyunca DB transaction tutulmayacak. Response saklanmayacak,
yalnız güvenli sayı/durum; POST sonucu belirsizse otomatik retry olmayacak. Mevcut
REST sync adapter sözleşmesi korunarak opt-in hook/deadline ve ilk sayfa okuması
ayrıştırılacak; test servisi tamamlanmadan UI çağrısı açılmayacak.

M6 bağlantı testi uygulandı: `rest_probe.py`, `deadline_dns.py`, REST client'ta
paylaşılan ilk-sayfa renderer ve opt-in authorization/deadline hook'ları. Tek istek,
profil sınırından daha dar 100 KB/10 saniye ve no-retry; ayrı dört-slot DNS havuzu.
Başlangıç audit'i commit olmadan network yok; actor için 10 saniye, tenant için
20 kontrol/dakika üst sınırı org kilidi altında audit üzerinden kontrol edilir.
İzinler secret erişimi/request ve sonuç öncesi canlı okunur; ham response hiçbir
kalıcı kayda/HTML'e gitmez. Ayrı POST console route'u durable_operator_view ile
middleware outer transaction'ını atlar; kendi kısa scope transaction'larını kullanır.
Form fingerprint/expiry/actor/set/step/CSRF aynı şekilde zorunlu. Multipart CSRF
sonrası body tekrar okunmaz; Content-Length ve alan/parser sınırları korunur.
Başarılı kaynak kayıt taslağı sadece locator'a indirgenir; refresh/back/replay
mevcut kaynağa döner, input/config artık session'da tutulmaz.

`.tmp/rest-probe-first-pg.xml`: 48 passed (56.15 s), gerçek grant/audit boundary,
özel IP, iptal, DNS deadline/capacity, tek-attempt, mevcut REST/common-job regresyonu.
`.tmp/rest-probe-console-pg.xml`: 75 passed (72.16 s), gerçek CSRF multipart POST
ve HTTP → transaction dışı real-client/fake-transport dahil.
`.tmp/rest-setup-completion-pg.xml`: 36 passed (55.55 s), tamamlanan formun locator'a
indirgenmesi ve eski connector UI. REST probe/client/DNS/console dört dosya mypy
check-untyped-defs temiz; setup/forms dört dosya depth güncellemesi sonrası temiz.
Ruff/format 76 ilgili dosyada temiz. 8109 browser sentetik örneği 1 belge olarak
doğruladı, sample ve content tekrar gösterilmedi; önceki adımlar korundu. Gerçek
harici bağlantıya browser isteği yapılmadı. Full-stack ve uygun gerçek profile/grant
ile kabul açık; yeni migration veya canlı DB/runtime grant değişikliği yok.

Sonraki M6 incelemesinde dependency: mevcut schedule `stage_only/promote_if_safe`
otomasyonu hâlâ synchronous `build_staged_index` çağırıyor ve koleksiyonun
publish-triggered preparation policy'sinden bağımsız. Bunu yeni sihirbaza bağlamak,
tek Job/hazırlama yolu hedefiyle çelişebilir ve çift build üretebilir. Önce manuel/
periyodik draft-only kayıt exact/idempotent bundle'a bağlanacak; otomatik stage/
activation için M5/M6 ortak durable preparation/continuation tasarımı ve testleri
tamamlanmadan yeni wizard seçeneği açılmayacak. Eski URL ve schedule davranışı
bu ara dilimde korunur; hedef acceptance kapsamı daraltılmıyor.

M6 manuel/periyodik draft-only seçimi eklendi. Yenileme aralığı kapalı beş seçenek;
formdan automation/promotion alanı kaçırılamaz. Contract+Source+Schedule+audit aynı
bundle transaction'ında; idempotent tekrar schedule payload'ını da eşleştirir.
İlk slot kayıt anı + seçilen aralık; kayıt doğrudan dispatch etmez. Kurulum özeti
gerçek aralığı gösterir, geri dönüşte seçim korunur. Sadece taslak aday üretme
sunulur; ortak durable hazırlama bağımlılığı çözülene kadar otomatik stage/promotion
yeni sihirbazda yok. `.tmp/rest-setup-schedule-pg.xml`: 48 passed (69.58 s),
ilgili common-job regresyonu dahil. Üç dosya mypy check-untyped-defs temiz.
Schedule ile non-owner ek test ve bu seçeneklerin browser tekrarı açık.

Non-owner manuel/periyodik kayıt ek kanıtı: `.tmp/rest-setup-schedule-role-pg.xml`
2 passed / 29 deselected (83.42 s); canlı izin değişikliği yok. Browser tekrarı açık.

M7 kaynak ekranı dilimi: kurulumdan sonraki ekranın teknik etiketleri sadeleşecek;
source kimliği/mapping revizyonu ayrıntıda, iş/sync durumu Türkçe, son başarı ve son
hata birbirinden ayrı gösterilecek. Ortak koleksiyon hazırlık durumu kaynak-job
kanıtı gibi sunulmayacak. Kaynak listesi 20 kayıtla sayfalanacak; mevcut set kapsamı
ve URL/POST yetki sınırları korunacak. Eski advanced kayıt/plan formları erişilebilir
kalacak; bu dilim tüm konsol yenilemesi veya lifecycle birleşmesi değildir.

M7 ilk kaynak görünümü kontrolleri `.tmp/source-presentation-pg.xml`: 50 passed
(46.03 s). Type check, farklı model sorgularının aynı değişkene atanmasını buldu;
ayrı isimlerle düzeltilecek. Readiness görünümü mevcut canonical runtime grant
validator'larını salt okunur kullanacak; source/set/tenant kapalıysa, izin kalktıysa
veya ortak/legacy iş sürüyorsa çalıştırma düğmesi gizlenecek. HTTP POST authority
aynı kalır; görünüm kararı hiçbir işlem yetkilendirmez. Son hata mevcut iş/run
kayıtlarından gelir; retry ile silinmiş eski attempt hatası için immutable history
olduğu iddia edilmez. Yeni ekranlarda kullanıcı terimi doküman seti olacak.

Ürün kararı (10 Eylül): kullanıcı bağlantı izni beklenirken kurulumu kaydetmeyi,
platform yöneticisi izin verdikten sonra kaldığı yerden sürdürmeyi seçti.
İzin kendiliğinden verilmez; kayıt bağlantı çalıştırmaz veya periyodik iş yaratmaz.

M7 kaynak dilimi uygulandı: exact liste 20 kayıt, ayrı son başarı/hata, Türkçe durumlar,
readonly canonical runtime-grant readiness (MCP/REST/Confluence), busy kaynakta run
düğmesi yok; POST authority değişmedi. Gelişmiş kaynak/plan/eşleme formları açılır
ayrıntılarda ve kendi hata durumlarında erişilebilir. Kaynak ayrıntısında periyodik
planın sonraki slotu gösterilir. `.tmp/source-readiness-pg.xml`: 55 passed (54.04 s);
`.tmp/source-presentation-final-pg.xml`: 55 passed (61.47 s).
`.tmp/rest-periodic-detail.xml`: SQLite 1 passed / 30 deselected (24.54 s).
Dört console source dosyası mypy check-untyped-defs temiz; ilgili Ruff temiz,
views CRLF format farkı düzeltildi. User guide/ADR güncellendi; yeni migration yok.
İzole 8109 browser'da Source 3 saatlik kurulumdan oluşturuldu, liste sonraki slotu
gösterdi; kaynak ayrıntısı 390 ve 900 genişlikte yatay taşma göstermedi. Viewport
sıfırlandı. Son gelişmiş-disclosure görünümünün browser tekrarı devam ediyor.

Son M7 browser tekrarı: Türkçe plan seçenekleri disclosure açılınca erişilebilir,
kapalı durumda uzun formlar ana listeyi uzatmıyor; 390 genişlikte yatay taşma yok.
Kaynak listesinde son slot ve MCP sırada durumu görüldü. Viewport yeniden sıfırlandı.

Sonraki bağımsız M2 doğrulama dilimi: aynı ortak tabloda beş destekli geometri,
aynı tenant'ın 16 eski nesli ve yabancı tenant satırları varken gerçek arama
kalitesi/gecikmesi ölçülecek. Yalnız `test_` PostgreSQL veritabanı ve açık benchmark
bayrağı; sentetik içerik, gerçek belge/provider yok. Her geometride top-10 exact
cosine referansına recall >= 0.95, p50 <= 80 ms, p95 <= 200 ms; önceki 20k
legacy karşılaştırma eşiği korunur. Bu yeni küçük karışık workload, üretim kapasitesi
veya henüz ölçülmeyen build-load/generic-plan/retention kabulü sayılmaz. Üretim DAL
değiştirilmeden önce başarısız ölçüm varsa plan ve nedeni ayrıca kaydedilecek.

M2 karışık workload kanıtı `.tmp/shared-vector-mixed-pg.xml`: 1 passed / 1 deselected
(80.69 s), `.tmp/shared-vector-mixed-workload.json` ölçüm ve EXPLAIN özeti. Aynı
tabloda 64/768/1536 vector ve 3072/4000 halfvec; her geometride 16 superseded nesil,
ayrı tenant, toplam 9624 sentetik chunk. Beşinde recall@10=1.0; p95 sırasıyla
24.42/4.92/5.13/10.79/16.36 ms. Planner bu küçük seçili kapsamda nesil B-tree +
exact sort kullandı; bu kanıt büyük ANN/yoğun-yazma/üretim SLO kabulü değildir.
Üretim DAL ve migration değişmedi; yalnız opt-in doğrulama genişletildi.

M5/M6 ortak hazırlama öncesi bulunan kalıcılık boşluğu: set sürümü yayınlandıktan
sonra auto-preparation Job kaydı `on_commit` callback'inde yaratılıyor. Commit ile
callback arasında süreç kaybı, yayınlanmış sürümü hazırlama işi olmadan bırakabilir;
hazırlama politikasının pin'leri de daha sonra okunuyor. İlk düzeltme yayını, exact
hazırlama Job/Outbox kaydını ve audit'i aynı DB transaction'ında oluşturur; yalnız
broker dispatch commit sonrasında kalır. Profil/iş/izin kararları ve aktif nesil
aynı servislerde kalır. Hata tüm DB değişikliğini geri alır. Real-PG commit/rollback,
audit failure ve mevcut publish/job regresyonu kanıtlanacak. Bu ara düzeltme legacy
schedule'ın synchronous build yolunu veya otomatik activation'ı birleşmiş saymaz.

M5/M6 yayın–hazırlama kaydı atomik hale getirildi; `publish_document_set_version`
exact Job/Outbox'u kendi transaction'ında yaratır, broker commit sonrasındadır.
Gerçek DB'de commit öncesi durable kayıt/dispatch yokluğu, job-audit hatasında ve
dış işlem rollback'inde yayın+Job+Outbox geri alma testi geçti. Mevcut profil/publish,
job lifecycle ve REST otomasyon regresyonuyla `.tmp/preparation-publication-pg.xml`
50 passed (38.77 s). System check ve migration drift temiz; yeni migration yok.
Staff/appsec/SRE incelemesi: mevcut caller authorization ve profile validation
korunuyor; veri/audit birlikte commit; provider/broker I/O yayın transaction'ına
taşınmadı. Legacy synchronous schedule birleşmesi ve otomatik activation hâlâ açık.

M8 ara geniş kontrol: tüm Ruff kontrolleri geçti (556 dosya biçimi temiz), 1781
testli SQLite suite devam ediyor. Runtime source'ları daha sıkı untyped-body kontrolü
ile tarandı; bildirilen 79 hata 18 test dosyasındaki type daraltmaları ve iki tarihsel
migration registry eşlemesindeydi, runtime dosyalarında hata bildirilmedi. Repository
varsayılan mypy ayrıca çalıştırıldı: 6 hata yalnız iki tarihsel migration testinde;
django-stubs eski schema modellerini güncel modellere eşliyor. Registry'nin tarihsel
dinamik model sınırı açık tiplenerek yanlış güncel-model varsayımı giderilecek;
migration/asser­tion/check kapsamı değişmeyecek. Sıkı test-body temizliği ayrı açık
kanıt olarak izlenir, genel type check geçmiş sayılmaz.

Sıkı test-body daraltmaları da bu doğrulama diliminde ele alındı: REST/Confluence
protokol tipi, nullable relation/audit payload varlığı explicit assertion; gerçek
Run sınıfının kaydedilmemiş instance'ı ile bütçe unit sınırı; typed sentetik JSON
ve request gövdesi. Kontrol/asser­tion kaldırılmadı, type-ignore veya checker ayarı
eklenmedi. Tarihsel migration registry'sinin dinamik tipi güncel schema sınıflarını
yanlış varsaymayı önler. Mypy ve etkilenen PG testlerinin tekrarı devam ediyor.

Geniş SQLite sonucu `.tmp/simplification-full-sqlite.xml`: **1629 passed, 152 skipped**
(302.03 s). Skip'ler PG locking/RLS/vector ve opt-in workload gerektiren kayıtlar;
PG kanıtlarının yerine geçmez. Son assertion/tip daraltmaları için etkilenen 208
test ayrıca PG'de çalışıyor. **Mypy check-untyped-defs apps/config 549 dosyada temiz**;
önceki 79 test hatası ve varsayılan kontroldeki altı tarihsel registry hatası giderildi.
Ruff check/format yeniden temiz; ana plan güncellendi. Proje bütünü tamamlanmış değil.

Son doğrulama: **`mypy --check-untyped-defs .` 556 dosyada temiz**.
`.tmp/simplification-type-boundaries-pg.xml`: **208 passed** (121.37 s), daraltılmış
testler ve gerçek iş/snapshot/izin/RLS sınırları dahil. Sonrasında bütün PostgreSQL
suite `.tmp/simplification-full-pg.xml` için başlatılacak; opt-in benchmark normal
suite'e eklenmeyecek. Test DB dışına migration veya veri yazımı yapılmıyor.

M5 hazırlama bağlama tasarımı (aşağıdaki dilimde uygulamaya alındı): tamamlanmış connector
Job, aynı tenant ve exact aday sürümünün index-build Job'una nullable PROTECT FK
ile bağlanacak; ikinci hazırlama status tablosu olmayacak. Link bir kez kurulur,
INDEX_BUILD üstüne link kurulamaz; DB trigger tenant/kind/tamamlanmış snapshot/
aday eşitliğini doğrular, link'i silme veya değiştirme reddedilir. Source Job'un
başarısı belge alma başarısı kalır; hazırlama başarısı yalnız bağlı build Job'dan
okunur. İlk davranış dilimi ortak Job'a bağlı REST/Confluence stage-only planıdır;
MCP schedule ve otomatik activation ayrıca tamamlanacak.

Admission org→source Job→set/policy→build Job sırasıyla kısa transaction'dadır;
mevcut exact runtime source/grant doğrulaması tekrarlanır. Doküman seti preparation
policy'si varsa schedule embedding/OCR seçimleriyle çelişki sessiz override yerine
açık ret olur. Auto-prepare yayınıyla oluşturulan aynı exact build Job'a bağlanılır;
eşleşen önceki terminal iş varsa yeni ücretli retry kendiliğinden üretilmez.
Belirsiz/başarısız/iptal işler kendi mevcut bounded retry/reconciliation akışında
kalır. Source Job link'i, yayın ve build intent/audit atomiktir; broker/outbox
commit sonrasında. Aday boşsa mevcut publish kuralı korunur ve aşama açık engel
olarak kalır; boş snapshot aktivasyonu bu dilimde yanlış başarılı gösterilmeyecek.
Mevcut legacy schedule yolu ve promotion sözleşmesi bu ilk adımda korunur.
PG link-scope/immutability/RLS, concurrent replay, policy conflict, crash/audit
rollback, broker failure ve terminal-job reuse kanıtı olmadan stage UI açılmayacak.

Geniş PostgreSQL sonucu `.tmp/simplification-full-pg.xml`: **1774 passed, 7 skipped**
(547.79 s). Beş skip SQLite/non-PG davranışı, iki skip ayrı opt-in workload'dur.
Bu kanıt mevcut 0029'a kadar eklemeli schema ve yukarıda uygulanmış dilimler içindir;
sonraki hazırlama link'i tasarımı henüz kod/migration değildir. `pip check` temiz.
Repository'de ayrı secret/dependency vulnerability scanner adımı bulunmadı;
Ruff security kuralları ve mevcut redaction/secret-rejection testleri çalıştı.

M6 sıradaki uygulama dilimi: oturumdan bağımsız, kullanıcı + tenant + doküman seti
kapsamlı REST kurulum taslağı. Onaysız platform kataloğu açılmaz; henüz bağlantı
seçilemeyen ilk adımda kaynak adı saklanabilir. Sonradan izni kalkan seçili bağlantıda
eşleme/değişkenler ve mevcut adım korunur. Taslak yetki sağlamaz: devam, kayıt ve
kontrolde mevcut actor/set yetkisi ile exact aktif bağlantı izni yeniden doğrulanır.
Taslak 30 gün geçerlidir, kullanıcı/organizasyon başına en çok 5 açık kayıt ve 160 KB kapalı
schema sınırı vardır. Ham örnek yanıt, credential veya probe sonucu saklanmaz;
config/inputs mevcut kaynakla aynı hassasiyette korunur, audit'e yalnız metadata
yazılır. Yeni eklemeli tablo PostgreSQL FORCE RLS + tenant/set/owner immutable
binding + completed-source scope guard kullanır; dolu tabloyu geri alma engellenir.
Revision karşılaştırması eski sekmenin daha yeni kaydı ezmesini önler. Kaynak,
contract, schedule, taslak tamamlama ve audit atomik; hata hepsini geri alır.
Save/resume/grant-revoke/idempotency, actor/tenant/scope/CSRF, size/expiry/limit,
concurrency, audit rollback, PostgreSQL RLS/migration ve browser kanıtı alınacak.
M5 hazırlama link'i tasarımı korunuyor; bu onaylı M6 diliminden sonra devam eder.

M6 izin bekleyen kurulum uygulandı: RestSetupDraft + eklemeli 0030, kapalı payload,
actor/set/tenant ve revision denetimi, source tamamlamasında config kopyasını boşaltma,
fail-closed allow/deny audit. İzin yoksa kaynak adıyla kayıt; izin kaldırılırsa aynı
adım/eşleme/değişkenler korunur. Yeni oturumda yalnız sahibi ve güncel set yöneticisi
devam edebilir. Kaynaklar ekranı yalnız sahibinin açık kayıtlarının metadata'sını
gösterir; kaydetmek Source/Contract/Schedule/Job yaratmaz. Mevcut bir saatte sona
eren session ve signed-digest/CSRF kontrolleri korunur. Runtime role provisioning'e
yalnız yeni tablo SELECT/INSERT/UPDATE eklendi; canlı DB'ye uygulanmadı.

`.tmp/rest-setup-drafts-boundaries-pg.xml`: **28 passed, 2 skipped** (38.50 s),
gerçek eşzamanlı revision yarışması, RLS/non-owner runtime, row-scope/source lineage,
yetki kaybı, immutable binding, audit rollback ve migration geri-alma koruması dahil.
İlk geniş PG diliminde 93 passed / 2 fixture hatası vardı; revocation fixture'ının
zorunlu zaman/actor alanları ve test rolünün mevcut scope fonksiyonu izni düzeltilip
yukarıdaki testlerde yeniden doğrulandı. Kontrol veya assertion zayıflatılmadı.
`.tmp/rest-setup-drafts-final-sqlite.xml`: **53 passed, 8 skipped** (30.89 s).
İlgili altı dosya `mypy --check-untyped-defs` temiz; Ruff/system/migration drift temiz.
Tarayıcı fixture DB'si 0030'a yükseltildi; ana uygulama DB'sine migration yapılmadı.
8109 fixture sunucusu güncel kodla yeniden açıldı; gerçek provider/worker çalıştırılmadı.
30 gün yeniden açılma sınırıdır; süresi dolan DB payload'ları bu dilimde otomatik
silinmez. Retention/purge operasyon kabulü açık, ürün tamamlandı sayılmaz.

M6 son kanıt: `.tmp/rest-setup-drafts-final-pg.xml` **19 passed** (34.26 s), FORCE
RLS altında tabloyu boş sanarak migration geri alınmasını engelleyen ayrıcalıklı
migration rolü koruması dahil. Tarayıcıda izin yokken ad kaydı, logout/login sonrası
aynı kaydı açma, başka kullanıcıya listelememe, izin sonrası ikinci adım eşlemesini
kaydetme ve tekrar açma, ardından kaynak oluşturma doğrulandı. Source 4 fixture'da
oluştu; belge alma/probe/provider isteği yapılmadı. 390 genişlikte taşma yok; viewport
sıfırlandı. Ara tarayıcı aracı zaman aşımı sonrasında bağlantı yeniden kuruldu.

M5 ilk hazırlama birleştirmesi uygulandı: 0031 self-FK ve direct-SQL lineage guard;
ortak REST/Confluence stage-only completion outbox'u artık canonical build/outbox'a
bağlar. Policy pin'leri kilit altında karşılaştırılır, çelişki/izin engeli 5 dakika
sonra aynı niyet için tekrar kontrol edilir; yeni ücretli iş/retry yaratılmaz. Aynı
pipeline'ın terminal işi reuse edilir; explicit retry aynı job üzerinden kalır.
Eski task redelivery'si inline-build claim'inden önce yeni yola yönlendirilir.
Worker sözleşmesi **8**; canlı worker/cutover yapılmadı. Legacy/PROMOTE_IF_SAFE ve
MCP schedule birleşmesi hâlâ açık; yeni REST sihirbazı henüz stage seçimi sunmaz.
`.tmp/connector-preparation-pg.xml`: **37 passed** (46.52 s), gerçek REST/Confluence
snapshot, atomic yayın/link/audit, broker failure, terminal reuse, concurrent replay,
policy conflict, eski mesaj ve job/publication regresyonları dahil. Kaynak ayrıntısı
bağlı hazırlamayı ayrı gösterir; cancel/retry mevcut yetkili endpoint'leri kullanır.
Yeni UI/RLS/cross-candidate ve geniş job regresyonunun son tekrarı devam ediyor.

M5 ek doğrulama tamamlandı: `.tmp/connector-preparation-final-pg.xml` 77 passed /
1 fixture hatası; DocumentSetVersion fixture'ındaki olmayan created_by argümanı
kaldırıldı, `.tmp/connector-preparation-boundaries-pg.xml` **20 passed** (41.68 s).
İlgili dokuz dosya sıkı mypy temiz. Tarayıcıda Source 4 yenilemesi tamamlanmışken
bağlı hazırlama ayrı gösterildi; iptal sonrası aynı iş yeniden denenip sıraya girdi.
Bu kontrol sentetik fixture ve gerçek canonical POST servisleriyle yapıldı;
provider/worker çalıştırıldığı veya gerçek hazırlama tamamlandığı iddia edilmez.

M6 sıradaki dilim: periyodik REST kurulumunda draft-only veya stage-only açık
seçimi. Stage-only setin mevcut hazırlama politikasını kullanır; ikinci profil
otoritesi veya sessiz set ayarı değişikliği yok. Kullanıcıya embedding, chunking,
OCR ve özetleme seçiminin güvenli özeti gösterilir. İncelenen politika fingerprint'i
kurulum state'ine kaydedilir; son kayıt mevcut exact politika/aktif profil/grant
ve actor/set yetkisini kilit altında yeniden doğrular. Değişmiş politika kullanıcıyı
yeniden incelemeye döndürür; başka tenant/pin veya promotion POST'u kabul edilmez.
Source/Contract/Schedule, seçilen embedding/OCR ve saved-draft completion aynı
transaction'da; ağ/iş dispatch yok. Eski interval-only taslaklar draft-only kalır.
Mevcut schedule servisine opsiyonel OCR seçimi eklenirken parametreyi vermeyen
eski caller'ın OCR kaydı korunur. Stage-only, manuel veya otomatik aktivasyon
yerine geçmez. Manuel kaynak ve yeni setin ilk hazırlama ayarları sonraki dilimdir.
Kaynak listesi de detail ile aynı exact hazırlama durumunu yansıtacak; devre dışı
schedule için henüz oluşmamış hazırlama 'bekliyor' diye yanlış gösterilmeyecek.
Risk/kanıt: stale policy, grant revocation, cross-tenant, eski saved payload,
idempotent replay, audit rollback ve no-dispatch; PG + browser kontrolü.

M6 periyodik hazırlama uygulandı. `.tmp/rest-stage-setup-pg.xml` 88 passed / bir
test beklentisi hatası: tamamlanmış özel taslak tekrar tüketilemez, locator olarak
açılır. Test bu mevcut güvenlik sözleşmesine düzeltildi; checkpoint'siz servis
replay'i ayrıca test edildi. `.tmp/rest-stage-setup-final-pg.xml` **42 passed**
(60.15 s), yeni kurulumdan gerçek snapshot/admission ve exact build bağına kadar,
OCR seçimi/legacy caller korunması ve önceki REST regresyonu dahil. İlgili 10 dosya
sıkı mypy temiz; Ruff 562 dosya, system check ve migration drift temiz.
Tarayıcıda eksik periyodik seçim alan hatası ve odak, ayar özeti ve kayıt doğrulandı;
Source 5 yalnız sentetik fixture'da oluştu, provider çağrısı veya build yürütülmedi.
Source 4 listesinde exact hazırlama sırası gösterildi. 390 px viewport'ta taşma yok,
tarayıcı hata log'u boş; viewport sıfırlandı. Tam PG/SQLite suite 1841 test ile ve
tam mypy kontrolü bu sürüm için sürüyor. Sonraki dilimlerin kanıtı ayrı eklenecek.

M6 set seçimi/oluşturma tasarımı: Dokümanlar ekranından REST kurulumuna giriş,
mevcut yönetilebilir aktif seti seçme veya mevcut organizasyon idare yetkisiyle
yeni set oluşturma. Metadata görme yetkisi içerik yöneticiliği sayılmaz. Normal
organizasyon yöneticisi yeni seti yönetmeyi formda açıkça seçer; canonical atama
servisi yalnız yeni set için kendisine yönetici sorumluluğu verir. Recovery hesabı
mevcut ayrıcalığıyla çalışır; eski setlere/grant'lara otomatik atama yok. Set,
explicit atama, kaynak adıyla özel RestSetupDraft ve audit tek transaction'da;
UUID niyeti tekrarlanan POST'ta ikinci set yaratmaz. Bağlantı izni yokken kullanıcı
kararına uygun biçimde bu kayıt üzerinden sonradan devam edilir. Aktör/org/intent
sunucudaki bir saatlik sınırlı state + imzalı token ile bağlı; mevcut set seçimleri
arama ve üst sınırla listelenir, final servis exact yetkiyi tekrar kontrol eder.
Yeni üretim bağımlılığı veya migration yok. Beş taslak sınırı/audit/atama hatası
bütün yeni set transaction'ını geri alır; grant veya source/job üretilmez.
Kanıt: form/CSRF/actor/org/revocation/stale-tab, metadata-only ret, idempotency/
concurrency/audit rollback, yeni set→izin bekleyen kayıt→mevcut resume akışı.

M6 set giriş uygulaması kodlandı; `.tmp/rest-scope-entry-sqlite.xml` **48 passed,
4 skipped** (30.68 s), yeni kapsam ve mevcut doküman/taslak regresyonları dahil.
Yeni set→yönetici açık seçimi→boş bağlantı listesi→aynı kaynak adıyla dört adımlı
kurulum tarayıcıda doğrulandı. Sentetik set public ID'si
`00e5b820-8ad1-48aa-99ff-af1e39ac99b2`; özel kurulum
`2b036627-4eeb-48c3-870e-b5ad76ef7adb`. Bağlantı izni veya Source yaratılmadı.
Ayrı PG ve kalan rol/arama/error/mobil doğrulamaları sürüyor.

M8 güncel geniş SQLite: `.tmp/simplification-through-stage-full-sqlite.xml`
**1682 passed, 158 skipped, 1 failed** (333.92 s). Tek hata eski auto-preparation
testindeki bare mock'un yeni Job dönüşünü taklit etmemesiydi; canonical create
servisini wraps ederek gerçek job/pin persistence da doğrulanacak şekilde düzeltildi.
Yukarıdaki 48 passed suite bu düzeltilen testi içeriyor. Assertion/kontrol kaldırılmadı.
PG tam suite bu set girişinden önceki runtime snapshot'ıyla devam ediyor; giriş
akışının sonradan eklenen kodu ayrı testlenecek. Tam mypy **562 dosyada temiz**
(set girişinden önceki sürüm); yeni altı dosya kontrolünde üç nullable actor kimliği
daraltması gerekiyordu, açık kimlik kontrolü eklendi ve tekrar doğrulanacak.

M6 set giriş son kanıtı: `.tmp/rest-scope-entry-final-pg.xml` **103 passed**
(101.23 s); yeni set/atama/taslak atomikliği, concurrent replay, non-owner FORCE RLS,
eski sekme/organizasyon değişimi, metadata-only ret ve ilişkili doküman/kaynak
regresyonları dahil. `.tmp/rest-scope-entry-final-sqlite.xml` **18 passed, 1 skipped**
(29.44 s), daha sonra eklenen RLS testi PG diliminde geçti. İlgili dört dosya sıkı
mypy temiz. Tarayıcıda yeni set üzerinde yalnız metadata rolü özel taslağı göremedi,
kurulum girişine doğrudan erişim 403 oldu; normal yöneticiye dönüldü. 390 px'de set
arama yalnız eşleşen seti gösterdi, yatay taşma yok; viewport sıfırlandı, son hata
log'u boş. Yeni kayıtlar sentetik fixture ile sınırlı kaldı.

Geniş PostgreSQL `.tmp/simplification-through-stage-full-pg.xml`: **1833 passed,
7 skipped, 1 failed** (964.48 s). Tek hata yukarıdaki aynı eski mock beklentisiydi;
düzeltilmiş test 103 passed diliminde gerçek iş/pin kaydıyla geçti. Geniş tarama set
girişinden önceki sürümdür; yeni giriş için ayrı kanıt kullanılır.

M5/M6 sonraki dilim: tamamlanmış REST/Confluence/MCP yenilemesini kaynak ayrıntısında
mevcut set hazırlama ayarlarını inceleyip açık kullanıcı eylemiyle aramaya hazırlama.
Planlanmış yenileme şartı yok; kaynak→build bağı aynı 0031 otoritesidir. Yeni profil,
schedule, durum tablosu veya otomatik aktivasyon yok. Actor/set/tenant yetkisi, canlı
kaynak izni ve değişmemiş config checksum'u org→source job→candidate→policy kilit
sırasında yeniden doğrulanır. İncelenen policy fingerprint'i POST'a bağlanır; stale
ayar ret olur. Yayın, canonical build/outbox, exact link ve fail-closed audit atomik.
Önceden bağlı veya aynı pin'lerle hazırlanmış iş tekrar kullanılır; başarısız/iptal
iş otomatik yeniden denenmez. Kullanıcı mevcut retry/iptal akışına yönelir. Tamamlanmamış,
boş/geçersiz, farklı kaynak/tenant veya artık kullanılamayan snapshot kabul edilmez.
Risk/kanıt: ücretli yinelenen iş, eski policy sekmesi, izin iptali ve tenant sızıntısı;
gerçek üç adapter snapshot'ı, concurrent replay, audit rollback, CSRF/doğrudan POST,
rol/affordance ve browser akışı testlenecek. Yeni schema/worker contract gerekmez.

İnceleme bulgusu: elle belge yükleme/yeniden taslak açma sorguları MCP adaylarını
henüz hariç tutmuyor; ayrıca kaynak yenilemesine ait draft üyeliği genel belge
servislerinden değiştirilebiliyor. Exact snapshot hazırlamadan önce üç connector
türünün adayları ortak bounded DB alt sorgularıyla yazar taslağından ayrılacak ve
üyelik ekleme/değiştirme/çıkarma reddedilecek. Connector kendi adayını run'a bağlamadan
önce oluşturduğu için normal snapshot yazımı korunur. Bu düzeltme, alınmış snapshot'ın
sonradan elle değiştirilip aynı işin kanıtı gibi hazırlanmasını önler.

M5/M6 elle hazırlama kodlandı. İlk SQLite taramasında 45 passed / 7 skipped,
6 failed / 10 fixture error görüldü: Confluence fixture imzası, metadata rol adı,
DocumentError code assertion'ı ve multipart CSRF sonrası body okuma düzeltildi.
Request boyutu/kapalı alan kontrolü artık tüketilmiş body'yi tekrar okumaz; hata
ve CSRF kontrolleri korunur. `.tmp/manual-preparation-final-sqlite.xml` **60 passed,
8 skipped** (34.35 s). Ardından rol/disabled/branch ve liste görünümü testleri eklendi.
`.tmp/manual-preparation-pg.xml` **194 passed, 3 failed** (244.90 s); üç hata aynı
concurrency fixture'ının tenant kapsamını transaction dışında açmasıydı. Testin
iki bağlantısı da gerçek transaction içinde scope açacak şekilde düzeltildi;
`.tmp/manual-preparation-final-pg.xml` son 39 test için sürüyor. Üretim tenant
kontrolü veya assertion gevşetilmedi. İlgili altı dosya sıkı mypy temiz; Ruff 568
dosya, format, system check, migration drift ve diff whitespace kontrolü temiz.

Tarayıcıda sentetik Source 6 üzerinde mevcut ayar özeti→Aramaya hazırla→exact iş
sırada doğrulandı; gerçek upstream/embedding/worker çalıştırılmadı. Metadata rolü
aynı kaynağın durumunu gördü, başlatma/iptal eylemlerini görmedi; başka setin Source
2 adresi 404 döndü. Yönetici oturumu geri açıldı. Son mobil/liste görünümü ve kayıt
kapanışı sürüyor. Bu dar kanıt bütün runtime/provider kabulünün yerine geçmez.

R2 sıradaki uygulama dilimi — MCP periyodik yenileme: mevcut ConnectorSyncSchedule,
ortak Job/Outbox ve exact source→preparation link kullanılır. ResourceSnapshot'a
nullable schedule + slot kanıtı eklenir; eski manuel kayıtlar null kalır. Aynı
source/schedule/slot yeniden teslimi yeni iş yaratmaz; plan gecikince catch-up yok,
aktif iş varken paralel tarama yok. DB tenant/source/type/slot eşleşmesini ve
snapshot schedule bağının değişmezliğini korur; dolu yeni lineage'ı rollback ile
silmek engellenir. Normal scheduler aynı org→schedule/source/job sırasını kullanır.
Yeniden başlatma/flag kapatma mevcut işleri kaybetmez; yeni MCP planı yalnız ortak
connector flag'i açıkken kabul edilir. Worker contract yeni davranış için artırılır;
canlı eski worker karışımı açılmaz, deployment hâlâ ayrı geçiş kabulündedir.

MCP planı taslakta tutma veya setin mevcut ayarlarıyla stage seçimini sunar; legacy
otomatik promotion seçimi açılmaz. Yeni MCP formu actor/set kapsamlıdır, mevcut
policy'nin güvenli özet/fingerprint'ini taşır; kayıt anında fingerprint, model/OCR
grant ve kaynak grant yeniden kontrol edilir. Schedule config servisi mevcut
yetki kararlarını org kilidi altında güncel nesnelerle tekrar doğrular. Atomik
audit/config ve completion→build korunur; yeni endpoint/profil/egress yetkisi yok.
MCP snapshot tamamlanınca ortak hazırlama completion outbox'u kullanılır; draft,
disabled, partial veya boş/no-change snapshot ücretli hazırlamayı tetiklemez.

Kabul: schedule admission ve slot tekilliği, gerçek sentetik MCP wire→snapshot→
exact hazırlama, broker kopması/duplicate/no-catch-up, flag/revoke/config-change,
eşzamanlılık, cross-tenant/direct SQL/RLS, ileri/korumalı geri migration, rol/CSRF/
stale policy ve browser list/detail davranışı. REST/Confluence ve manuel MCP
regresyonları ayrıca çalıştırılır. Son tam SQLite taraması mevcut R1 sürümünü
doğrularken bu dilimin tasarımı incelendi; yeni schema kanıtı ayrı tutulacak.

R1 son kanıt: `.tmp/manual-preparation-final-pg.xml` **39 passed** (90.29 s);
üç adapter'ın eşzamanlı POST'ları aynı build'e bağlandı. Son kaynak listesi değişikliği
manuel REST/MCP hazırlama durumunu schedule olmadan da gösteriyor; otomatik testte
üç adapter için doğrulandı. Tarayıcıda Source 6 için listede **Sırada** görüldü,
390 px'de sayfa genişliği 375 px; viewport sıfırlandı ve hata log'u boştu. Sunucu
son template'lerle yeniden açıldı; yalnız izole fixture 8109, schema 0031. Ana
8000 web/Redis/worker yok; PostgreSQL ve MinIO canlı sağlıklı, ana DB değişmedi.
Staff incelemesi: ortak hazırlama helper'ı ve aynı exact FK otoritesi, yeni schedule
veya model seçimi yok. Appsec incelemesi: mevcut rol/set/tenant, canlı source checksum/
grant, policy fingerprint, CSRF/kapalı alan ve actor attribution kontrolleri var.
SRE incelemesi: publication/link/outbox/audit atomik; broker commit sonrası, terminal
işi tekrar kullanma ücretli retry üretmiyor. Kaynak snapshot üyeliği korunurken
tombstone/iptal kontrolleri değişmedi. Tam ürün kabulü R2–R6 açık kaldığı için yok.

R1 geniş SQLite kanıtı (2026-09-11 tamamlandı):
`.tmp/simplification-through-manual-full-sqlite.xml` **1736 passed, 163 skipped,
1 failed**, 63212.12 s duvar süresi (uzun askıda kalma dahil). Tek başarısızlık,
liste artık kullanıcıya set adı gösterdiği halde eski logical_id bekleyen
`test_documents_list_is_tenant_scoped` idi. Test, izinli setin adı ve public URL'si
bulunmalı, diğer setin adı/URL'si bulunmamalı biçiminde güncellendi; mevcut erişim
retleri korundu. Düzeltmenin PostgreSQL kanıtı
`.tmp/document-list-name-regression-pg.xml` **8 passed** (42.75 s).
Bu tam suite R1 çalışma sürümünü kapsar; 0032/MCP schedule kanıtı değildir.

R2 MCP schedule uygulama/doğrulama (2026-09-11): eklemeli 0032, ortak scheduler,
admission/dedup/completion, stage-only policy seçimi, bağımsız MCP plan formu ve
kaynak liste/ayrıntı bağlantıları tamamlandı. Kaynak veya model grant iptalinden
sonra planı kapatma mümkün; yeni enabled admission tekrar reddedilir. Platform
catalog/grant otoritesi değişmedi. Worker contract **9**; ana DB/worker geçişi yok.

Kanıtlar: ilk SQLite `.tmp/mcp-schedule-first-sqlite.xml` **28 passed, 3 skipped,
1 failed** (28.73 s); ilk PG `.tmp/mcp-schedule-first-pg.xml` **116 passed,
3 failed** (150.92 s). Başarısızlıklar yeni test fixture'ındaki yanlış metadata
enum/eksik atayan, yanlış reverse-relation adı ve normal runtime rolünde zaten
bulunan schedule-target DELETE yetkisinin test rolünde eksik olmasıydı. Fixture'lar
gerçek model ve `provision-app-role.sql` ile eşleştirildi; assertion/kontrol kaldırılmadı.
Son `.tmp/mcp-schedule-final-sqlite.xml` **78 passed, 5 skipped** (37.97 s);
`.tmp/mcp-schedule-final-pg.xml` **75 passed** (66.89 s), aynı slot eşzamanlılık,
gerçek sentetik MCP wire→snapshot→exact build, no-change/disabled/draft-only,
broker tekrar gönderimi, grant/policy iptali, SQL/RLS ve dolu lineage rollback
koruması dahil. İlk geniş PG grubunun mevcut connector/manual hazırlama testleri de
geçti. Dokuz etkilenen dosyada container mypy temiz; ilk testteki nullable erişim
assertion ile doğrulandı. Ruff/format **553 dosya** temiz; system/drift temiz.

Tarayıcı: mevcut 8109 fixture'ı 0032'ye ilerletildi, ana DB değişmedi. Source 7
`Düzenli MCP Belgeleri` için yönetici saatlik/stage-only planı UI'dan kaydetti;
güncel model/parçalama/OCR özeti, sonraki yenileme ve hazırlama seçimi görüldü.
Sentetik kaynak grant'i canonical servisle iptal edildiğinde aynı UI planı kapattı;
grant sonra geri yüklendi, plan kapalı bırakıldı. Metadata viewer'da detay 200 ve
yönetim eylemleri yok, plan adresi 403; başka setin plan adresi 404. Yöneticiye
dönüldü. 390 px form genişliği 375 px, taşma yok; Tab odağı sıklıktan enable
alanına ilerledi. Viewport sıfırlandı, dev error log boş. Bulunan menü bölüm eşleme
kusuru düzeltildi; `.tmp/mcp-schedule-navigation-sqlite.xml` **33 passed** (26.24 s).
Fixture sunucusu son navigation koduyla yenilendi. Gerçek MCP provider/embedding,
broker/worker ve tam runtime kabulü hâlâ R6; sentetik browser kanıtı bu gate değildir.

Staff/Appsec/SRE incelemesi: yeni paralel iş/durum otoritesi yok; org kilidiyle
güncel kaynak/yetki/policy seçimi, immutable schedule/slot ve shared completion
lineage var. Başarılı audit/config ve snapshot→build atomik; bekleyen outbox broker
kesintisinde korunur. Metadata rolüne profil sırları/içerik verilmez. Kalan riskler
source config revision, legacy promotion/activation, büyük kuyruk/tenant taraması
ve gerçek provider rollout testleridir. MCP'de otomatik promotion açılmadı.

R2 sıradaki dilim — ilk hazırlama ayarları: set yöneticisi, henüz belge veya set
sürümü bulunmasa da arama modeli, OCR ve parçalama ayarını mevcut
DocumentSetPreparationProfile'a kaydedebilir. Yeni bir policy/status tablosu yok.
Mevcut alan/grant/model doğrulaması ve profile artifact yayın servisi kullanılır;
standart parçalama seçimi açıkça gösterilir ve immutable artifact olarak kaydedilir.
Kayıt tek başına belge alma/build/aktivasyon başlatmaz; otomatik hazırlama açık
seçimdir. Eski retrieval/summary referansları korunur, bu dar formda değiştirilmez.

Yeni ayar servisi actor/set/tenant yetkisini, aktif set/org ve model/OCR grant'ini
org kilidi altında tekrar kontrol eder; görülen policy fingerprint + auto_prepare
özeti stale-write kontrolüne girer. İlk create yarışında çift policy/artifact yok;
config/artifact/audit birlikte commit olur. REST üçüncü adımından ayarlara geçiş,
mevcut özel checkpoint'e değişkenler ve sıklık kaydedildikten sonra gerçekleşir.
Geri dönüş yalnız aynı actor/set'in kendi draft UUID'sine yapılır, harici return
URL kabul edilmez. Ayar sonrası hazırlama seçimi kullanıcıya yeniden sunulur.
Yeni migration veya üretim bağımlılığı gerekmez.

Kabul: boş set ilk policy, onaylı/izinsiz model ve OCR, metadata/cross-set/tenant,
stale policy/eşzamanlı ilk kayıt, audit rollback, sabit parçalama yeniden kullanımı,
iş oluşturmadan save, eski policy referanslarının korunması, REST checkpoint'in
kaybolmadan gidiş/dönüşü, CSRF/kapalı alanlar ve yeni set browser yolculuğu.

R2 ilk hazırlama ayarları uygulama/doğrulama (2026-09-11):
`preparation_settings.py`, console form/view/template ve REST checkpoint detour
uygulandı. Model seçimleri okunabilir adlarla, standard chunking açıklaması ve
kapalı başlangıç otomasyonu ile sunulur. Uzun sistem kimlikleri ana özette yok.

İlk SQLite denemesinde view'daki düz chunking şemasını iç içe okuma hatası üç
testi düşürdü; canonical flat defaults kullanılarak düzeltildi. Son kanıtlar:
`.tmp/initial-preparation-first-pg.xml` **72 passed** (73.78 s),
`.tmp/initial-preparation-final-sqlite.xml` **40 passed, 4 skipped** (34.45 s),
`.tmp/initial-preparation-final-pg.xml` **24 passed** (47.56 s).
PG seti OCR izni/iptali, mevcut policy referanslarını koruma, ilk kayıtta iki
thread yarışı, audit/artifact rollback ve non-owner FORCE RLS işlemini içerir.
Son okunabilir etiket değişikliği sonrası
`.tmp/initial-preparation-labels-sqlite.xml` **22 passed** (27.46 s).
Son dört dosyada container mypy temiz; Ruff/format **556 dosya** temiz,
Django system check ve migration drift temiz. Yeni migration yok.

İzole browser'da boş `İlk Hazırlama Denemesi` setinin REST üçüncü adımından
değişkenler/saatlik plan kaydedilerek ayarlara geçildi. İlk model/standart parçalama
kaydı sonrası aynı adımda girilen değer ve sıklık korundu; hazırlama yeniden
seçilip `Yeni Setin REST Belgeleri` kaynağı (Source 8) oluşturuldu. Kayıt hiçbir
sync/build veya set sürümü yaratmadı. Son kodla formda okunabilir etiketler ve
kapalı otomasyon görüldü. Metadata viewer için aynı setin ayarları 403, kapsam
dışı set 404; profil/veri ayrıntısı yok. HTTP POST/CSRF/kapalı alan/özel taslak
sınırları otomatik testlerde doğrulandı. 390 px görünümde scroll width 375 px,
yatay taşma yok; Tab arama modelinden OCR'a geçti, görünür odak var, JS error
log boş. Viewport sıfırlandı; yönetici oturumu ve Source 8 ekranı geri bırakıldı.

Staff/Appsec/SRE incelemesi: tek policy otoritesi ve canonical artifact servisi,
org kilidi altında güncel yetki/grant kontrolü, CAS ve atomik audit korunuyor.
Geri dönüş yalnız actor/set'e ait draft'a yapılır; GET iş üretmez. Yeni tablo,
bağımlılık veya egress yok. Son canlı kontrol: PG/MinIO sağlıklı; izole 8109 web
liveness 200; ana web/Redis/worker/beat çalışmıyor. Gerçek provider, broker ve
tüm uygulama kabulü R6'da açık; bu sentetik kanıt onların yerine geçmez.

R2 sıradaki dilim — REST kaynak ayarlarını sürümleyerek değiştirme:
mevcut immutable Source/profile/contract bağları yerinde değiştirilmez. Yeni
SourceConfigurationRevision, aynı setteki Source kayıtlarını bir kök altında
ilişkilendirir; numara/checksum/Source bağı değişmez, ailede tek current kayıt
vardır. İlk düzenlemede mevcut kaynak r1 olarak kayda alınır. Yeni ayar kaydı
ön doldurulmuş sihirbazdan, fark özeti ve CAS ile rN+1 oluşturur; UUID/numara
kullanıcıdan istenmez. Aynı özel checkpoint ve completion receipt yeniden kullanılır.
Yeni platform bağlantısı/grant otomatik yaratılmaz; seçilmiş exact aktif izin gerekir.

Aday kaynak elle alınabilir/hazırlanabilir; mevcut kaynağın planı geçişe kadar
korunur. Periyodik admission yalnız current kaynağa açıktır, ailede eşzamanlı
sync ret edilir. Her Source kendi cursor/document/job geçmişini korur; aday
snapshot aynı ailenin eski belge dilimini değiştirir. Başka kaynakların baseline
seçimi etkinleştirilmemiş ayarların belgelerini tüketmez. Genel index promotion/
rollback yolu da current olmayan kaynak belgelerini kabul etmez.

Geçiş actor/set operasyon yetkisi, canlı grant, aile/CAS ve tamamlanmış exact
snapshot→build bağını yeniden doğrular. Diğer kaynakların bu arada değişmesi
stale aday olarak reddedilir. Current seçimi, mevcut canonical index aktivasyonu,
schedule aktarımı ve audit tek transaction'dır; devam eden aile işleri varken
geçiş yok. Eski kayda dönüş aynı güvenlik ve lineage kontrollerinden geçer;
güncel izin iptali/tombstone geçmişten geri alınmaz. Eski plan/snapshot/job ve
veri silinmez; pending/retired/disabled terimleri mevcut Source status ile karışmaz.

Eklemeli şema + FORCE RLS + immutable config/lineage SQL koruması gerekir.
Reverse yalnız ayrı yetkilendirilmiş veri-koruyan geçişle mümkündür; dolu geçmişte
otomatik rollback şeması reddedilir. Worker contract arttırılır; eski worker'lar
drain edilmeden bu özelliğe geçilmez. Kabul: normal edit/diff/replay, eski writer'ın
korunması, aday veri sızıntısı olmaması, stale/CAS ve iki thread yarışı, grant/rol/
tenant/CSRF, audit rollback, SQL/RLS, schedule ve aynı aile job fencing, gerçek
sentetik snapshot→build→switch→restore, dar browser ve statik kontroller.

R2 REST source revision uygulama/doğrulama (2026-09-11): 0033 ve worker contract
10; immutable source family, özel checkpoint ile düzenleme/fark özeti, izole aday
snapshot ve exact hazırlanmış index ile atomik geçiş/geri dönüş uygulandı.
Kullanılan kaynak listede tek satırdır; diğer ayarlar geçmişten açılır. Aktif aile
sync/build işleri geçişi engeller. Geçişte o revision oluşturulurken kaydedilmiş
plan geri yüklenir; sonraki bağımsız plan düzenlemeleri revision'a yazılmaz. Bu
davranış ekranda ve ADR-0022'de açıklandı. Yeni belge bulunmayan sonraki yenileme,
önceki hazırlama sonucunu listede/ayrıntıda artık gizlemiyor.

Kanıtlar: `.tmp/source-revisions-ui-sqlite.xml` **53 passed, 7 skipped** (97.71 s),
`.tmp/source-revisions-second-pg.xml` **11 passed** (109.83 s),
`.tmp/source-revisions-boundaries-pg.xml` **90 passed** (205.56 s).
Son SQL seçilmiş-revision/build guard'ı ve iptal edilmiş grant testleri:
`.tmp/source-revisions-final-pg.xml` **48 passed** (174.09 s).
Son retained-baseline/no-change liste regresyonu ve tüm revision grubu:
`.tmp/source-revisions-review-pg.xml` **13 passed** (56.37 s).
PG kanıtı iki eşzamanlı editör, audit rollback, no-owner FORCE RLS, doğrudan SQL
immutable/no-current/unprepared-selection retleri, yanlış set/build, güncel izin
iptali, gerçek sentetik REST snapshot→pgvector build→switch→restore ve başka
kaynak verisini kaybetmeden yeniden hazırlama davranışını içerir. İlk denemelerde
test fixture'ındaki eksik hazırlama argümanları/yanlış enum, nullable erişim ve
bir exception'ın code alanı olmadığı varsayımı düzeltildi; hiçbir güvenlik
assertion'ı kaldırılmadı. 11 etkilenen dosyada container mypy, son düzenleme sonrası
5 dosyada tekrar mypy temiz. Ruff/format 559 dosya, system check ve migration
drift kontrol edildi; iki format farkı düzeltilip son kontrol ayrıca çalıştırıldı.

Browser: izole 8109 fixture'ı 0033'e ilerletildi. Source 8 düzenlemesi mevcut
alanlarla açıldı; ad/değişken/sıklık değişikliği özel checkpoint'e kaydedilip aynı
adımda devam etti. Fark özeti eski 60 dakika/yeni 15 dakika planını okunabilir
gösterdi. Source 9 deneme sürümü kaydedildi; Source 8 kullanılan r1 ve saatlik
planıyla listede kaldı. Kaydetmek sync/build başlatmadı. Geçmişte iki sürüm görüldü.
Metadata viewer detay 200 fakat düzenleme eylemi yok; düzenleme 403, başka set 404.
390 px görünümde scroll width 375 px; Tab kayıt düğmesinden önceki adıma ilerledi,
görünür odak var. Viewport ve yönetici oturumu geri bırakıldı. Bu sentetik web
kontrolü gerçek provider/worker geçişinin yerine geçmez; o kabul R6'dadır.

Staff incelemesi: Source/config tek otorite, token/family CAS, kendi cursor geçmişi,
diğer kaynak üyeliğinin korunması ve mevcut serving kilidiyle atomik seçim.
Appsec: mevcut manager/operations sınırı, canlı source/model izinleri, kapalı form,
CSRF/actor-private checkpoint, SQL immutable lineage ve RLS; içerik/sırlar audit'e
girmez. SRE: build tamamlanmadan current seçilemez; audit hatası pointer ve planları
birlikte geri alır; eski schedule/slot kimlikleri korunur. Migration yalnız test
PG ve browser fixture'da uygulandı; ana DB, gerçek provider, deployment değişmedi.
Etkin legacy promote-if-safe planının düzenlenmesi bu dilimde güvenli ret verir;
ortak promotion devamı ve Confluence/MCP config revision hâlâ açık. Reverse dolu
history'de veri silmek yerine durur. Üretim dependency/egress değişikliği yok.

R2 sıradaki dilim — model/embedding/OCR typed Connection eşlemesi: mevcut global
profillerin PK/revision/config/grant otoritesi korunacak. Ortak Connection'a exact
nullable PROTECT OneToOne bağları, kapalı tek-tür SQL kontrolü ve immutable config
koruması eklenir. Yeni platform kayıtları profile+identity+audit atomik oluşturur;
eski kayıtlar migration içinde sabit alan listesi ve bounded iterator ile eşlenir.
Normal uygulama rolünün global katalog SELECT sınırı korunur; yeni egress veya
tenant/set grant üretilmez. İzinli tüketici yine mevcut typed runtime kontrollerinden
geçer. Bu dilim tool-call bağlantılarını ve promotion/evaluation akışını değiştirmez;
ortak promotion devamı R3 yayın işlem sınırıyla birlikte ele alınacak.

Kabul: üç tür register/resolve/replay/disable, yeni revision ve eski checksum
koruması, platform dışı rol retleri, yanlış tür ve source'a model bağlama retleri,
audit rollback, concurrent materialization, non-owner read-only rol, idempotent
historical mapping/ileri migration/veri-koruyan geri ret, mevcut provider/console
regresyonları. Ana DB'ye geçiş yok. Eski geçersiz profil yapılandırmaları migration
tarafından düzeltilmez; kimlik eşlenir, runtime canonical validator hatası görünür kalır.

R2 model/embedding/OCR Connection uygulama/doğrulama (2026-09-11): 0034'te kapalı
üç yeni nullable OneToOne PROTECT ilişki; ortak resolver/materializer genişletildi.
Canonical üç platform register servisi profile/identity/audit'i tek transaction'da
yazar. Mevcut profile PK/revision/grant ve kaynaklar değişmedi; kimlik secret veya
transport kopyası taşımıyor. Legacy eşleme migration içinde sabit alanlarla,
200 kayıtlık iterator ile yapılır. Başka türe ait kimlik Source'a bağlanamaz.

`.tmp/model-connections-first-pg.xml` **56 passed** (51.43 s): üç türün normal,
rol/audit retleri, SQL immutability/lineage, readonly rol, eşzamanlılık ve mevcut
model/embedding/OCR sağlayıcı testleri. `.tmp/model-connections-final-pg.xml`
**73 passed, 2 failed** (79.29 s): MCP/ortak resolver regresyonları geçti; eski
deployment testi artık SQL ile değiştirilemeyen profili bozuyordu, migration
testi eski historical state'e orchestration uygulamasını dahil etmemişti.
Deployment testi aynı revision'a değişik model bildirimini environment üzerinden
veriyor; field mismatch/redaction ve eski profilin korunması assertion'ları var.
Migration fixture'ın historical hedef listesi düzeltildi. Son
`.tmp/model-connections-reviewed-pg.xml` **36 passed** (54.20 s), console platform
kayıt/rol yolları ve gerçek boş reverse→historical profile→forward→dolu reverse
ret işlemi dahil. SQLite ilk **48 passed, 13 skipped, 1 failed** (37.65 s), aynı
historical-state fixture düzeltmesi sonrası ilgili 5 test **passed** (30.06 s),
`.tmp/model-connections-reviewed-sqlite.xml`. Tüm `mypy --check-untyped-defs apps`
**560 dosya temiz**; Ruff/format 560 dosya, system check ve migration drift temiz.

Browser fixture yalnız 0034'e ilerletildi ve sunucu son kaynakla yenilendi.
Set yöneticisi platform model kaydına 403 aldı. Platform yöneticisi sentetik
`typed-model-browser` profilini formdan kaydetti; envanterde host/secret referansı
gösterilmedi. Aynı UI'dan disable başarılı; read-only kontrol exact tek Connection,
r1 ve disabled profilini doğruladı. JS error log boş, manager/Source 9'a dönüldü.
Bu dilim form düzenini değiştirmiyor; önceki mobil/klavye form kanıtı korunur.
Global katalogda tenant/cross-set semantiği yok; kayıt yetkisi platform-only,
Source binding reddi ve tenant grant'lerinin oluşmaması otomatik testle doğrulandı.
Gerçek provider/network çağrısı yapılmadı, ana DB migration/rollout yok.

Staff: config/grant tek otorite, kapalı profile-kind registry ve sabit historical
checksum; implicit Source/job taşıması yok. Appsec: canonical platform gate ve
SQL immutable provenance, normal rol SELECT-only; identity kullanım yetkisi değil.
SRE: başarısız audit profile/identity'i geri alır; eski kaydı değiştirmek yerine
yeni revision gerekir; dolu rollback koruması var. Bağımlılık/egress/log politikası
değişmedi. Tool-call Connection eşlemeleri ve ortak promotion/R3 yayın sınırı açık.

R3 uygulanan dilim — tek eylemli yayın işlem sınırı: mevcut EvalRun'ın aynı
exact suite ve tamamlanmış case/Run kayıtlarıyla devam etmesi sağlanır. Ayrı session
advisory namespace bir release evaluation sahibini korur; bağlantı kaybında yeni
sahipmiş gibi I/O veya kanıt kaydı yapılmaz. Tamamlanan case yeniden çağrılmaz;
tamamlanmış/başarısız eval otomatik olarak tekrar denenmez. Mevcut run_eval yeni
eval açan uyumlu giriş olarak kalır, resume yalnız exact kaydı yürütür.

Ardından yayın isteği için actor/scenario/intent ve görülen ayar token'ına bağlı,
exact candidate/evaluation ve önceki yayını PROTECT ile tutan kalıcı bir işlem
kaydı eklenir. Bu kayıt ikinci eval/job durum otoritesi kurmaz. Hazırlama ve eval
kaydı kısa org→scenario kilidi altında atomik; dış çalışma transaction dışında;
son seçimde güncel yetki, ayar/CAS, geçen eval ve alias/index readiness tekrar
kontrol edilir. Canonical release promote + scenario activate + receipt/audit
tek transaction olur. Hata/iptal/değişmiş ayar eski yayını korur. Aynı niyet aynı
aday/eval'i açar; yeni ücretli değerlendirme açık yeni işlem gerektirir. Legacy
ve snapshot sözleşmeleri birlikte desteklenir; mevcut senaryoların runtime
sözleşmesi sessizce değiştirilmez. Ortak connector promotion devamı bu sınırı
kullanacak; eski inline promotion ayrı bir yeni yol olarak genişletilmeyecek.

Kabul: exact resume/process-loss, iki eşzamanlı istek, yanlış org/suite, role/access
revocation, değişmiş draft/binding/active yayın, eval/provider/audit hatası,
alias/readiness başarısızlığında atomik geri alma, SQL/RLS/lineage, eski yayın
ve runtime uyumu, bir eylemli console + geçmiş/sonuç ekranı ve browser kanıtı.

R3 kanıtı — 2026-09-11: `ScenarioPublication` actor/scenario/UUID niyetini exact
candidate/eval ve önceki yayına bağlar; istek/görülen ayar ile hazırlama-sonrası ayar
ayrıdır. Workflow/node draft revizyonları, bağlı setler, legacy veri sürümleri,
ilgili katalog pinleri ve aktif yayın değişirse ilerleme durur. Tamamlanmış niyet
tekrar oynatılırken sonradan superseded olmuş eski sürüm tekrar etkinleşmez.
Yeni ücretli deneme yalnız yeni açık eylemle açılır. Yarım niyet aynı actor için
ekranda “Yayını sürdür” olur; son on işlem exact sonuçlarına bağlanır. Uzman aday
ve promotion kontrolleri Gelişmiş'te korunur. Varsayılan runtime sözleşmesi değişmedi.

PostgreSQL `releases.0006`: immutable receipt, release/eval pinleri ve tamamlanan
case kanıtı; org/scenario/project/draft/eval lineage, tamamlanma koşulu, FORCE RLS;
boş geçmişte reverse, veri varsa forward-compatible recovery gereği. Canonical
promotion/rollback org→scenario sırasıyla aynı canlı değişimi serileştirir;
non-key scenario kilidi FK insert ile gereksiz deadlock üretmez. Hazırlama, final
promote+activate+receipt ve audit kısa atomik birimler; uzak çalışma aralarında.

Otomatik kanıtlar:
- `.tmp/publication-regression-sqlite.xml`: 47 passed / 1 PG skip, 84.94 s.
- `.tmp/publication-reviewed-sqlite.xml`: 32 passed / 1 PG skip, 107.12 s.
- `.tmp/publication-final-pg.xml`: 66 passed / 1 failed, 104.57 s; tek hata
  deneme RLS rolünün mevcut tenant-scope fonksiyonuna EXECUTE izninin eksik olmasıydı.
  Ürün kontrolü gevşetilmeden fixture düzeltildi.
- `.tmp/publication-final-review-pg.xml`: 5 passed, 102.15 s; gerçek RLS,
  sahte lineage/tamamlanma reddi, dolu migration reverse reddi ve yeni console route.
- `.tmp/publication-access-review-pg.xml`: 7 passed, 96.91 s; hesap kapatma,
  eval sırasında set bağlama, birleşik yönetici ve adım/rol regresyonu.
- `.tmp/publication-lock-review-pg.xml`: 2 passed, 95.24 s; iki eşzamanlı
  yayın isteği tek niyet/eval, diğer geçerli yayın değişiminin final CAS ile korunması.
- Release evaluation resume/process-loss için ayrıca
  `.tmp/release-evaluation-resume-final-pg.xml` 7 passed; önceki dört fixture
  assertion adı düzeltmesi task içi test verisiydi. R3 PG geniş koşusu da resume,
  connection owner-loss, canonical compiler ve release lifecycle kontrollerini geçti.
- Sekiz etkilenen kaynak dosyasında mypy temiz (izole mevcut runtime image);
  host mypy DLL'si Windows Application Control tarafından engelleniyor. Ruff ve
  format 565 dosyada temiz; system check, migration drift ve diff whitespace temiz.

Dar browser kanıtı: mevcut guarded SQLite fixture'a yalnız releases 0006 eklendi;
`mcp-manager` ile “Tek İşlemle Yayın” senaryosu gerçek console düğmesiyle yayınlandı.
Canonical hazırlama servisiyle oluşturulan kesilmiş ikinci niyet ekranda görüldü;
“Yayını sürdür” aynı #2 aday/eval'i tamamladı; toplam 2 release/2 eval/2 receipt,
#1 superseded, #2 active. Görüntüleyici düğmesi disabled, geçmiş ve exact sonuçlar
okunabilir. Aynı fixture'da CSRF-enforced HTTP probe viewer POST 403; diğer özel
senaryo ve başka org GET/POST 404; yayın kayıt sayıları değişmedi. Tarayıcı JS
hata kaydı boş. 390 px kontrolde uzun adım metni daralmıştı; mobil butonlar metnin
altına alındı, güncel runtime screenshot ile okunabilir, scrollWidth 375/viewport
390, Tab odağı görünür. Viewport sıfırlandı, yönetici oturumu geri yüklendi.

Staff/security/SRE son incelemesi: ikinci job/eval durum otoritesi yok; exact
CASE/Run kanıtı korunur; güncel yetki ve CAS maliyet öncesi ve final seçimde tekrar
kontrol edilir; audit hatası canlı geçişi geri alır. Üretim bağımlılığı eklenmedi,
egress/authentication/ham veri saklama davranışı değiştirilmedi. Gerçek provider ve
tam worker/Redis topolojisi bu browser diliminde kullanılmadı; tam gate R6'dadır.
PostgreSQL/MinIO kullanıcı tarafından yeniden açıldı ve healthy doğrulandı; ana
DB'ye migration/cutover uygulanmadı. Diğer R2–R6 işleri bu dilimle tamamlanmış sayılmaz.

R2 sıradaki dilim — tenant kapsamlı tool-call Connection eşlemesi: altı global
profil türü korunur; `tool` türü yalnız exact `ToolDefinition` ve onun kurumu ile
eşlenir. Nullable organization + tool_definition bağı, global/tenant ayrı unique
constraint ve kapalı profil/tür/kapsam CHECK kullanılır. Connection üzerindeki
FORCE RLS global kimliklerin mevcut okunabilirliğini korur; tool satırı yalnız
mevcut transaction tenant scope'unda okunur/eklenir. App role yalnız INSERT ek
yetkisi alır; INSERT policy global profil kimliği yazmayı reddeder. UPDATE/DELETE
verilmez. Servis kendi tenant scope'unu genişletmez; çağıranın mevcut yetkilendirilmiş
scope'u kullanılır. Registry hâlâ platform incelemesi/artifact ve ToolBinding
otoritelerinden sonra çalışır; yeni grant, binding, insan onayı veya egress yok.

Canonical tool registration ile kimlik ve güvenli metadata audit'i tek transaction
içinde yazılır; audit hatası her ikisini geri alır. Version→revision, manifest
checksum, risk/protocol/side-effect aynaları ve kurum izin listesi doğrulanır;
kimlikte manifest veya credential kopyalanmaz. ToolDefinition'ın mevcut immutable
body sözleşmesi SQL katmanında da korunur; yalnız status/updated_at değişir.
Bu sayede tenant tool eşlemesi row-lock için yeni UPDATE yetkisi istemez;
exact unique constraint/get-or-create ve FK ile yarışlar korunur. Global profil
eşleme kilitleri korunur. 0035 tarihsel
eşleme sabit checksum sözleşmesiyle bounded batch kullanır; rollback ayrıcalıklı
rol, boş tool kimlik geçmişi ve yeni INSERT grant'inin önceden geri alınmasını
ister; dolu geçmişi silmez veya global yazmayı açmaz. Riskler: kurum verisinin
global katalogdan sızması, global yazma yetkisinin kazara açılması, stale config,
concurrent duplicate ve geçmiş kayıt uyumsuzluğu. Testler: HTTP/MCP canonical
registration, aynı ad/sürüm iki kurum, RLS foreign/empty scope, global read/insert
denial, immutable config/status, audit rollback, concurrency, migration roundtrip,
mevcut tool approval/proxy/compiler ve global connection regresyonları. Yeni UI
veya runtime cutover bu dilimin kapsamı değildir; bütünleşik gate R6'da kalır.
Operasyon incelemesinde nullable tenant sütununun mevcut readiness envanterinde
telemetry sayıldığı görüldü: Connection açık istisna ile korunan karma katalog
olarak denetlenir; tam iki SELECT/INSERT policy ve ifadeleri doğrulanır. App-role
provisioning yeni INSERT grant'inden önce bu migration/policy durumunu zorunlu
kılar. Eski şemada script çalıştırmak global yazma yetkisi açamaz.

R2 tool Connection kanıtı — 2026-09-11: tenant tool eşlemesi, 0035 frozen backfill/
SQL mühürleri/FORCE RLS, canonical registration/audit, read-only tool registry ile
eşleme, ayrı app INSERT politikası ve migration öncesi provisioning engeli uygulandı.
RLS readiness nullable Connection'ı telemetry saymaz; tam policy çifti ve ek policy
kontrol edilir. Org scope değişmez; otomatik tool binding/grant/onay yok.

- İlk SQLite mevcut registry/model regresyonu: 26 passed / 6 PG skip, 127.58 s
  (`.tmp/tool-connections-first-sqlite.xml`). Yeni tool SQLite: 7 passed / 4 PG skip,
  94.44 s (`.tmp/tool-connections-reviewed-sqlite.xml`).
- İlk PG: 49 passed / 3 failed, 131.30 s. Bir fixture audit SELECT izni eksikti;
  gerçek provision grant'ine uyarlandı. Rollback ACL kontrolü implicit yerleşik
  PostgreSQL yazma rolünü yeni app grant'i sayıyordu; gerçek tablo/sütun ACL'lerine
  daraltıldı. Sonraki geniş PG: 198 passed / 8 failed / 12 error, 156.65 s. İlk
  gerçek hata dolu backfill sonrası deferred FK event'leri nedeniyle Django'nun
  yeni index DDL'inin reddiydi; sonraki migration testlerine transaction hatası
  yayıldı. FK kontrollerini index DDL'den önce uygulayarak düzeltildi; hiçbir
  constraint/test gevşetilmedi.
- Düzeltilmiş registry/global kimlik/roundtrip/concurrency paketi: **43 passed**,
  55.27 s (`.tmp/tool-connections-final-pg.xml`). Aynı anda registration ve
  legacy mapping'in full_clean sırasında görünür olan kazananı reuse etmesi dahil.
- Son birleşik PG kabul paketi: **219 passed / 2 SQLite-only skip**, 67.37 s
  (`.tmp/tool-connections-acceptance-pg.xml`); tüm tools (HTTP/MCP adapter, proxy,
  approval, katalog), release compiler, console tool approval, global Connection
  ve deployment readiness birlikte temiz. Son mypy 4 dosya, Ruff/format 584 dosya,
  Django system/migration drift ve diff whitespace temiz.
- Ek provisioning/readiness paketi: **22 passed / 2 SQLite-only skip**, 37.80 s
  (`.tmp/tool-connections-deployment-pg.xml`). Eksik/gevşek/ek policy ve FORCE
  kaldırılınca readiness/provision reddi; empty/foreign scope; global INSERT
  reddi; tablo INSERT yetkisinin geri dönüş sınırı. Sütun ACL dalı son diff'te incelendi.
- Güncel fixture SQLite schema 0035'e ilerletildi, web 8109 yeniden başlatıldı.
  Tarayıcıda mcp-manager Source 9'u okuyup 1 tıkla düzenleme girişini açtı; yalnız
  izinli REST profili listede. mcp-scope-viewer ayrıntıyı okudu, değiştirme/çalıştırma
  eylemi görmedi; doğrudan edit URL 403, kapsam dışı Source 1 URL 404. Tarayıcı
  hata kaydı boş, masaüstü screenshot okunabilir. Manager oturumuna ve Source 9'a
  dönüldü. Kaydet/çalıştır seçilmedi; yeni source/job/provider isteği yok.
  Yeni tool registry eşlemesinin ayrı UI eylemi yok; tool approval/proxy rol
  kontrolleri PG suite'te doğrulandı. Bu dar browser kontrolü tam R6 gate değildir.

Staff/security/SRE incelemesi: null scope yalnız altı global tür için; tenant tool
kimliği FK ve CHECK ile scope'a bağlı. Kimlik okuma yeni runtime yetkisi değildir.
İmmutability SQL ve uygulama seviyelerinde; audit veriyle atomik. Geçiş geri dönüşü
history/INSERT ACL nedeniyle fail-closed, privilege script schema hazır olmadan
global yazmayı açmaz. Ana PostgreSQL verisine migration/provision/cutover
uygulanmadı. Tool runtime yetkileri ve public API aynı; yeni bağımlılık yok.

R4 sıradaki dilim — süresi dolan özel REST checkpoint içeriği: mevcut sabit 30 günlük
expires_at korunur. Yalnız süresi dolmuş ve tamamlanmamış kayıtların payload ve serbest
isim alanı boşaltılır; org/set/owner/UUID/expiry/revision/audit kimliği saklanır.
Nullable payload_purged_at ve SQL/ORM mühürleri kayıtların yeniden doldurulmasını,
erken temizlemeyi, tamamlanmış source receipt'ini değiştirmeyi engeller. Aktif
kurulum, tamamlanmış source, contract, grant ve işler etkilenmez.

Bakım komutu PostgreSQL tablo sahibinin yetkisiyle tek açık org için çalışır;
varsayılan preview, uygulama için açık --apply, 1–500 bounded batch. Normal app
rolü/istemci bu operasyona yetkili değildir. Org→draft kilit sırası save/complete
ile aynı, cutoff sunucu zamanı, preview yalnız sayaçlar, audit actor/UUID/revision
metadata'sı; batch ve audit atomik, retry temizlenmiş kaydı tekrar saymaz.
Ana veriye veya tarayıcı fixture'ına temizleme uygulanmayacak; yalnız disposable
PG test verileriyle doğrulanır. Operatör önce preview ve geri alınamaz içerik
boşaltımını değerlendirir; otomatik beat/scheduler eklenmez. Riskler: erken/scope
dışı temizlik, DB sahibi yetkisini actor string ile taklit, audit arızasında kayıp,
eşzamanlı kayıt, ters migration ile kanıt kaybı. Testler bunları ve mevcut
save/resume/complete/expiration regresyonunu kapsar. Reverse dolu purge kanıtını
silmek yerine reddeder. Büyük vektör retention/cutover R4'te ayrıca açık kalır.

R4 expired REST içerik bakımı kanıtı — 2026-09-11: 0036 marker/queue index/CHECK ve
SQL korumaları, PostgreSQL tablo sahibine özel tek-org preview/apply komutu,
bounded/audited temizlik ve operasyon kılavuzu uygulandı. Geçerli bir kurulumun
yeniden açılması için süre uzatılmadı; bakımı geçmiş kayıt yeniden doldurulamaz.
Komut payload/name okumaz; veri temizliği yalnız disposable PG test verisinde.

- `.tmp/rest-setup-retention-first-pg.xml`: **34 passed / 1 SQLite-only skip**,
  49.29 s. İlk koşuda temiz; eski kayıtları koruyan migration/empty reverse,
  purge history reverse reddi, erken/non-owner SQL reddi, refill reddi, foreign
  org/active/completed korunması, batch/preview/retry/concurrency, tüm batch audit
  rollback ve eski private save/resume/grant-wait/CSRF sınırları.
- `.tmp/rest-setup-retention-sqlite.xml`: **26 passed / 9 PG skip**, 29.44 s.
  PostgreSQL gerektiren bakımın SQLite'da yetki iddiası reddedilir; mevcut console
  kayıt/expiry/izin bekleme davranışı korunur. RLS/owner kanıtı PG koşusundadır.
- Son mypy 3 dosya temiz; Ruff/format 587 dosya, system check, migration drift ve
  diff whitespace temiz. Ek bağımlılık/secret scanner yok; tam security scan
  yapıldığı iddia edilmez.
- Browser fixture schema 0036'ya veri koruyarak ilerletildi, 8109 güncel kodla
  yeniden açıldı. Mevcut `2b036627-4eeb-48c3-870e-b5ad76ef7adb` izin-bekleme
  kaydı sahibiyle listede görünüyor, tek tıkla aynı isim ve Adım 1 ile açılıyor;
  hâlâ bağlantı izni yok, source/job oluşturulmadı. Görüntüleyici seti okuyor
  ancak özel taslağı veya eylemi görmüyor; exact kurulum GET 403. JS hata kaydı
  boş. Manager oturumu ve Source 9 ekranı geri yüklendi. Bakım komutunun ayrı UI
  yüzeyi yok; temizlenmiş kaydın resume POST reddi gerçek PG console testinde.
  Büyük/toplu veri ve tam provider/runtime gate R6 kapsamındadır.

Staff/security/SRE son incelemesi: SELECT yalnız kimlik/revision/expiry; actor string
DB yetkisi vermez. Scope ve expiry sunucuda belirlenir; batch/audit atomik ve aynı
org kilit sırası korunur. Marker ve audit kanıtı tutulur; ters migration bunu silmez.
Ana DB, kullanıcı/fixture taslağı veya kaynak içeriği temizlenmedi; otomatik schedule
yok. Bakım sıklığı/gerçek veriye --apply ayrı somut operasyon kabulüdür.

Summary: Birleşik geliştirme sürüyor; expired REST bakım komutu, tenant tool ve model bağlantı kimlikleri, tek eylemli senaryo yayını ve exact resume, REST ayar sürümleri, ilk hazırlama ayarları,
kuruluma kayıpsız dönüş ve MCP periyodik yenileme uygulanan son dilimlerdir. Tüm ürün kabul
maddeleri tamamlanmadı; kalan beş teslim R2–R6 matrisiyle izlenir.
Files changed: Son dilimler ingestion models/0030–0036, rest setup retention servis/komut/test/kılavuz, typed model/tool connections,
tools registration, tenancy RLS readiness ve app-role provisioning,
orchestration/embedding/OCR register servisleri, source revision, REST setup/draft/schedule/
scope, connector/manual preparation, MCP schedule ve preparation settings,
document snapshot üyelik koruması, console forms/views/templates,
ilgili testler, releases publication/models/0006/compiler/lifecycle, evaluation
resume/ownership, console publication route/history/mobile adımları, user guide,
ADR-0021/0022, master plan ve bu tek görev kaydı.
Önceki yerel değişiklikler korunuyor; commit/push yapılmadı.
Architecture impact: Yayın, exact build intent/link ve audit atomik; kaynak başarısı
ile hazırlama durumu ayrıdır. Kurulum tek mevcut set/policy/izin otoritesini kullanır.
Security impact: Kapalı şema, actor/set/tenant bağları, stale-write, CSRF, RLS ve
güncel grant kontrolleri var. Üretim bağımlılığı veya canlı ağ politikası değişmedi.
Authorization impact: Yeni setin yöneticiliği açık form seçimi ve mevcut atama
servisiyle yalnız o sete verilir. Bağlantı izni otomatik verilmez; diğer kullanıcının
özel taslağı metadata rolüyle açılamaz. İzin bekletme kullanıcı kararına göre uygulandı.
Data and privacy impact: Özel taslak config'i sınırlı ve 30 gün yeniden açılabilir;
tamamlanınca payload boşalır. Expired payload/name temizliği owner preview/apply
komutuyla ve audit'i korunarak uygulanabilir; henüz gerçek veride çalıştırılmadı. Gerçek veri taşınmadı
veya silinmedi; fixture kurulumları sentetik, provider isteği yapılmadı.
Logging, metrics, tracing and audit impact: Kritik kayıt/atama/yayın/link audit'i
veriyle atomik, hata rollback; actor/hedef/outcome metadata'sı, ham içerik log'u yok.
Database and migration impact: Eklemeli 0030 kalıcı REST taslağı, 0031 exact
hazırlama bağı, 0032 MCP schedule lineage, 0033 source revision, 0034 typed model, 0035 tenant tool, 0036 private expiry
Connection ve releases 0006 publication PG test DB'de doğrulandı. İlk hazırlama
ayarlarında yeni migration yok. Ana DB migration/reset/cutover yapılmadı.
Tests and verification results: 0029 baseline PG 1774/7 skipped ve SQLite 1629/152
skipped; sonraki 0030/0031 ve REST stage/set giriş kanıtları yukarıda ayrı kaydedildi.
Geniş suite tek eski mock hatası verdi; düzeltme son scope PG 103 passed içinde
doğrulandı. Son scope mypy temiz. Ruff/format/system/migration drift temiz.
Dar browser kanıtı tam deployment/provider gate yerine geçmez.
Unverified assumptions: Gerçek provider birlikte çalışabilirliği, tam runtime
topolojisi, büyük ANN/build-load/generic-plan kapasitesi ve rollout davranışı.
Remaining risks: M0/M2–M8 açık maddeler; ortak activation/legacy promotion birleşmesi,
retention/cutover ve tüm konsol kabulü.
Manual review required: Son ürün/rol/UX kabulü ve ayrı yetkilendirilecek canlı kesim.

R2 sıradaki dilim — MCP/Confluence kaynak ayarlarının sürümlenmesi (2026-09-11):
REST için doğrulanmış aynı SourceConfigurationRevision ailesi, snapshot izolasyonu,
exact hazırlama/index seçimi ve kayıtlı planı geri getirme bu iki adapter'a açılacak.
Aile içinde tür/set/tenant değişmez; mevcut writer ve plan, açık seçime kadar korunur.
Yeni sürüm yalnız mevcut aktif/onaylı profile bağlanabilir. Eski bağlantısız kaynak
GET sırasında eşlenmez; geçiş hazırlığı ayrıca gerekir. Grant/egress/secret yetkileri
değişmez. Form sunucu imzalı actor/source/token/intent bağını ve son incelemede
config/plan özetinin imzasını doğrular; aynı istek aynı revision'a döner, stale veya
değiştirilmiş istek reddedilir. Kayıt ve audit tek transaction'dır.
0037 yalnız revision scope ve exact typed snapshot SQL kanıtını genişletecek;
0036 özel taslak temizliği guard'ı korunacak. Geri migration, non-REST revision
geçmişi varsa reddedilecek. Confluence legacy run/schedule sınırı ve ortak aile
busy kontrolü de doğrulanacak. Testler: iki adapter create/replay/CAS/grant/rol,
scope/CSRF/kapalı form, SQL immutable/RLS/migration, gerçek PG snapshot/build/
select/restore ve audit rollback; mevcut REST regression. Dar browser UI kontrolü
sentetik 8109 fixture'da; gerçek provider, ana DB veya tam rollout bu dilimde yok.
Implemented: evet. Verified: aşağıdaki otomatik ve dar browser kanıtıyla; tam R6 kabulü değil.

R2 MCP/Confluence revision kanıtı — 2026-09-11:
Kaynaklar aynı SourceConfigurationRevision ailesinde tür/set/tenant korunarak kaydedilir.
Yeni form actor/source/intent/CAS ve exact inceleme checksum imzasını bağlar; 1 saat
geçerlidir. Aynı istek yeniden kaynak oluşturmaz. Ortak `_authorize`, snapshot,
prepare/select/restore ve schedule servisleri kullanılır; yeni grant/runtime otoritesi yok.
0037 typed REST/Confluence/MCP kanıtını ve legacy family writer kilidini genişletir,
0036 payload temizliği SQL korumasına dokunmaz. Eski worker'lar contract 11 öncesinde
drain edilmelidir. SQL reverse non-REST revision geçmişi varsa veriyi silmeden reddedilir.

İlk PG denemesi 25 geçti/12 hata: MCP alanı `mcp_profile` yerine gerçek
`mcp_resource_profile` olarak düzeltildi; type-check aynı kusuru yakaladı. İkinci
deneme 54 geçti/5 hata/2 skip: ek testlerde eksik import, yanlış yere taşınmış iki
assertion ve grant'te olmayan updated_at test alanı düzeltildi; assertion kaldırılmadı.
Son `.tmp/resource-revisions-acceptance-pg.xml`: **192 passed, 2 skipped, 135.07s**.
Skip'ler MCP için uygulanmayan legacy Confluence writer ve SQLite-only retention sınırı.
Gerçek PG snapshot→prepare→index→select→restore, güncel grant reddi, auditte rollback,
eşzamanlı aynı-intent, normal app role/RLS, immutable SQL/reverse, legacy family busy,
REST regression, MCP schedule/sync, elle hazırlama ve 0036 retention kapsandı.
SQLite `.tmp/resource-revisions-sqlite.xml`: **40 passed, 13 PG-only skipped, 35.38s**.
Son form metni/aday schedule linki düzeltmesinden sonra
`.tmp/resource-revisions-ui-review-pg.xml`: **2 passed, 32.26s**. Son disposable Linux
mypy 6 source dosyasında temiz; Ruff/format 572 dosyada, system check, migration drift
ve diff whitespace temiz. Ayrı secret/dependency scanner çalıştırılmadı.

Browser: yalnız `.tmp/agenthub_browser_gate_mcp_20260910.sqlite3`, şema 0037,
8109 sentetik fixture. MCP Source7→Source10, Confluence Source11→Source12 r2 kayıtları
gerçek browser edit→review→save (3 tıklama) ile oluşturuldu. Root7/11 seçili kaldı;
10/12 deneme ayarıdır, hiçbir fetch/build/provider işi başlatılmadı. Confluence root
fixture katalog/grant'ı canonical servislerden ve sadece fixture setup süresindeki
sentetik private policy ile oluşturuldu; çalışan uygulamanın ağ ayarı değişmedi.
Yeni Confluence planı 15 dakika draft-only, MCP planı manuel; gerçek plan ancak
hazırlanmış sürüm seçilirse uygulanır. Desktop okunabilir; 390px mobil inceleme
ekranında içerik375px, yatay taşma yok, Tab odağı solid. Viewer Source12 okuyabilir,
MCP/Confluence edit403; aynı org izin dışı Source1 edit404. Browser JS error/warn boş.
REST özel izin bekleyen taslak korunur; ana PG DB migration/reset/cutover yok.
Son küçük görünüm düzeltmesi aday MCP plan bağlantısını gizler ve Confluence
profilinin teknik model gösterimini okunabilir onaylı bağlantı etiketiyle değiştirir.
Bu dilim R2'nin kaynak revision maddesini kapatır; ortak promotion, varsayılan runtime,
retention/kapasite/cutover, bütün konsol ve bütünleşik R2–R6 kabulü devam eder.

Son diff incelemesi: Source family/grant/catalog/serving otoriteleri korunur; SQL
family writer kilidi mevcut org→source sırasını izler; type/profile/config değişikliği
yalnız yeni Source'ta olur. Audit ham config/URI/secret içermez, kayıt ve seçimde
başarısız audit tüm değişimi geri alır. Kalıcı veri silme/bağımlılık/public HTTP
sözleşmesi değişikliği yok. Eklemeli 0037 şema geçişi ana DB'ye uygulanmadı.
Değişen dosyalar: ingestion resource_revisions/source_revisions/connector_jobs/
confluence_sync/job_lifecycle, migration0037, resource revision testleri;
console resource_revision_views/source_revision_views ve iki kaynak template'i;
user guide, ADR0022, master plan ve bu tek görev dosyası.
Son fixture restart sonrası yönetici formunda Confluence bağlantı etiketi, aday
MCP'de plan düzenleme linkinin gizlenmesi browser'da doğrulandı. 8109 açık; bu
dar fixture kanıtı gerçek provider veya tam Compose işçi kapısı yerine geçmez.

R2 ortak promotion keşif notu: mevcut inline automation index'i değerlendirmeden
önce aktive ediyor; aktif release'in artifact pinlerini kullanıyor. Yeni tek eylemli
yayın ise editördeki taslağı derliyor. Bu ikisini doğrudan çağrıyla bağlamak yayınlanmamış
editör değişikliklerini otomatik yayımlama veya başarısız eval'de canlı veriyi değiştirme
riski yaratır. Dolayısıyla sonraki tasarım, onaylı aktif artifact pinlerini koruyan
exact aday veri değerlendirmesi ve yalnız başarıdan sonra atomik index/release seçimi
gerektirir. Active-generation run seçimi bugün sadece aktif index'i seçtiği için
izole aday değerlendirme kanıtı da incelenmelidir. Bu yeni dilimde henüz kod yazılmadı;
önce çağrı yolları ve mevcut eval/retrieval sözleşmesi doğrulanacak.

R2/R3 sıradaki uygulama dilimi — canlı veriyi değiştirmeden exact aday değerlendirme:
Mevcut EvalRun ve Run otoriteleri korunacak. EvalRun'a optional prepared SourceJob
bağı ve bounded generation sayısı; tenant kapsamlı immutable EvalDataGeneration
FK'ları; Run'a optional exact EvalRun bağı eklenecek. Bu bağ istemci JSON'undan,
request key metninden veya consumer adından yetki türetmez. Yetkili servis, güncel
senaryo test + set operasyon yetkisini, source grant/config, tamamlanmış exact build,
set/pipeline ve release veri kapsamını doğrulayarak aday index'i ve diğer hazır
index'leri tek kısa transaction'da sabitler; ham içerik/prompt saklanmaz.
Normal eval/run varsayılanları değişmez. Aday eval retrieval'ı yalnız kendi durable
Run→EvalRun→generation zincirinden, normal consumer+scenario+set grant kesişimiyle
ve non-tombstoned içerikle okur. Promotable index'e genel istemci erişimi açılmaz.
Scope/actor/grant/config/policy yeniden doğrulaması, retry'da aynı pinler, iptal/
başarısızlık ve eksik lineage'da fail-closed korunur. Child-workflow gibi exact aday
veri bağını devralmayan çalışma sınırları başlangıçta açık kodla reddedilir; canlı
veriye sessiz fallback yapılmaz. Aynı Run içindeki branch/agent retrieval kapsanır.
Hazırlanan veriyi kullanan passing eval, bu generation'lar aktif olmadan genel
release promotion kapısını açamaz. Son connector publish devamı bu temel üzerine
ayrı dilimde bağlanacak; mevcut legacy automation bu temel tamamlanırken çalıştırılmaz.
SQL/RLS/immutable FK ve deferred tamlık kontrolleri, dolu history'de güvenli reverse,
provision/readiness ve worker revision uyumu birlikte ele alınacak. Test: gerçek
PG aday retrieval ve eski live index'in değişmemesi, iki runtime sözleşmesi,
yanlış actor/tenant/consumer/run, revoked grant, stale build, raw SQL tamper, replay,
audit rollback ve normal eval/retrieval/publication regression. Ana DB'ye uygulanmaz.
Implemented: temel servis ve runtime bağı evet; ortak connector publish devamı henüz hayır.
Verified: ilk PostgreSQL 42 test geçti. Geniş regression 156 geçti / 4 fixture yetki
hatası / 2 SQLite-only skip; fixture yetkisi düzeltildikten sonra ilgili 4 test geçti.
Normal runtime SQLite kontrolleri 34 geçti. Yeni tarayıcı kabulü henüz yapılmadı.

Bu temel dilimin netleştirilen sınırları: prepared_actor gerçek kullanıcı FK'sıdır;
normal EvalRun/Run satırlarında yeni bağlar null, generation_count 0 kalır. Legacy
release'in belge sürümü pinleri değiştirilmez: aday version zaten release manifestinde
olmalıdır. Active-generation release için scope snapshot'tan alınır; diğer setler de
aynı kısa transaction'da hazır aktif generation'a sabitlenir. Yeni SourceJob→build→index
bağı hazırlamanın otoritesidir; DocumentSetVersion.built_index_version yalnız serving
seçiminde doldurulduğu için hazırlığın kanıtı olarak kullanılmaz. İlk test bu ayrımı
ortaya çıkardı. İkinci test legacy retrieve çağrısının Run'ı taşımadığı sınırı yakaladı;
workflow ve embedded-agent ortak retrieve çağrıları yalnız prepared FK varlığında bu
bağı da taşır. Sessiz live fallback testi böylece gerçek pgvector sonucuyla kapandı.

Eklemeli evaluations0006/workflows0021; tenant RLS, immutable pin/evidence/release/Run
bağları, deferred tamlık, index koruması ve boş-history/privileged reverse birlikte.
İç servis henüz yeni HTTP veya konsol eylemine açılmadı. Admission intent'in sahibi
gelecek connector publication receipt'idir; mevcut resume_eval aynı EvalRun'ı sürdürür.
Source grant, actor, consumer, set scope ve hazırlama politikası yeniden okunur;
admission ve her node/agent adımı ile retrieval sınırında iptal edilen yetki durdurur.
Audit başarısız admission'ı geri alır; deny ayrı ve içeriksiz kaydedilir. Worker
ingestion sözleşmesi 12'dir; rollout'ta schema/role provisioning ardından tüm ilgili
işçiler aynı uygulama revision'ında yeniden başlatılmalıdır. Normal runtime default'u
değişmedi; ana DB veya çalışan ana stack üzerinde şema geçişi yapılmadı.

R2/R3 sonraki dilim — ortak otomatik publication devamı:
Mevcut ScenarioPublication receipt'i editör taslağı veya SourceJob olmak üzere
tek, değişmez origin taşıyacak; yeni ikinci release/eval otoritesi açılmayacak.
SourceJob+scenario için kararlı intent, exact aktif baseline/artifact pinleri ve
aynı hazırlanmış index kullanılacak. Editördeki yayımlanmamış WorkflowDraft hiçbir
otomatik compile'a katılmaz; aktif execution/data sözleşmesi ile güncel senaryo
ayarları ayrışmışsa otomatik işlem durur. Mevcut schedule approval ve hedef listesi
senaryo test/yayın ve set operasyon yetkileriyle birlikte admission/final commit'te
yeniden doğrulanır. Tüm hedefler sınırlı ve aynı tenant'tır. Yeni index'in etkileyeceği
aktif-generation senaryolarından onaylı listede olmayan varsa yayın fail-closed durur.

Tüm hedeflerin exact aday evaluation'ları başarılı olmadan hiçbir canlı pointer
değişmez. Son kısa transaction org→scenario→set sırasıyla baseline/approval/policy
CAS yapar, index ve hedef release'leri aynı transaction'da seçer; audit/alias/readiness
başarısızlığında bütünü geri alınır. Mevcut completion outbox hazırlık/eval beklerken
pending kalır; aynı receipt ve evaluation sürdürülür, bitmiş başarısız değerlendirme
otomatik yeniden ücretli çalıştırılmaz. Legacy promotion mesajı ortak SourceJob varsa
buraya yönlendirilir; kanıtsız inline veriyi önce-aktive-et yolu genişletilmez.
Gerekli doğrudan kontroller: bir başarılı uçtan uca kaynak yayını, başarısız eval'de
eski yayının korunması, exact resume/idempotency, final yetki/baseline değişiminde
rollback ve schema origin koruması. Genel matrix tekrarları son kabulde birleştirilecek.
Implemented: ortak SourceJob publication receipt, hazırlık sonrası outbox devamı,
exact eval ve atomik index/release seçimi eklendi. MCP schedule arayüzü/SQL uyumu
tamamlandı; bütünleşik kabul ve rollout henüz bitmedi.
Verified: PostgreSQL doğrudan 6 kontrol geçti (iki runtime sözleşmesinde başarı,
başarısız eval, audit rollback/resume). Son incelemede hazırlık beklerken oluşturulan
iş bağının transaction rollback ile kaybolması düzeltildi; tüm eval setleri final
seçimden önce sıralı kilitleniyor. Bu düzeltmelerin doğrudan doğrulaması bekliyor.
Eklemeli MCP schedule guard geçişi, ortak promote_if_safe modunu tanıyacak;
reverse ayrıcalıklı rol ve boş promotion schedule/history gerektirecek.

R3 yeni oluşturma varsayılanı: runtime/restart/retry ve evaluation transaction
sınırları yukarıdaki kanıtlarla hazır. Yetkili konsol oluşturma servisi yeni senaryoyu
snapshot + active_generation ile oluşturacak. Mevcut Scenario/Release/Run kayıtları,
model/DB legacy varsayılanları ve düşük seviyeli uyumluluk fabrikası değişmez.
POST üzerinden contract seçimine izin verilmez; sunucu seçer ve oluşturma audit'inde
saklar. Üç konsol oluşturma şablonu ve eski fabrikanın uyumluluğu doğrudan kontrol
edilecek. Mevcut senaryonun açık geçiş önizlemesi ve seçimi ayrı kalan iş olarak
izlenir; bu değişiklik kendiliğinden mevcut yayınları dönüştürmez.

R2/R3 ortak publication son doğrudan kanıtı:
`.tmp/source-publication-complete-pg.xml` 17 geçti (99.76 s): REST/MCP ve iki
runtime sözleşmesinde başarı, aynı receipt ile resume, başarısız eval, audit rollback,
eval sonrası approval iptali; hazırlık bağının beklemede kalıcı olması dahil.
MCP SQL/form uyumu `.tmp/source-publication-final-pg.xml` içindeki ilk iki kontrolle
geçti; aynı dosyadaki legacy testin exception sınıfı yeni durable seam'e uyarlandı ve
17'lik son koşuda geçti. Ana DB ve çalışan browser fixture'a yeni migrations uygulanmadı.
Yeni konsol oluşturma varsayılanı `.tmp/scenario-runtime-defaults-sqlite.xml` 8 geçti;
üç şablon snapshot/active_generation, düşük seviyeli legacy fabrika korunuyor.

R3 mevcut senaryoyu açık geçiş: düzenleme/test/yayın yetkilisi mevcut yayın ve veri
bağlarını önizler; actor-bound süreli review token ve CAS ile yalnız gelecekteki
yayınların veri seçimi ayarı snapshot/active_generation olur. Eski release/Run ve
canlı pointer değişmez. Mevcut yayını değiştirmek için normal tek eylemli yayın ve
değerlendirme kapısı kullanılır. Token draft/binding/baseline değişiminde geçersiz,
audit başarısızlığında ayar değişimi atomik geri alınır. Ayrı migration/tablo veya
arka planda veri aktarımı yok; source-scoped index pinleri varsa geçiş reddedilir.

R3 geçiş kanıtı: `.tmp/runtime-transition-pg.xml` ilk uçtan uca kontrol geçti
(eski yayın korunarak ayar geçişi, replay ve normal yeniden yayın). Aynı koşuda
yetki iptali fixture'ı zorunlu revoked_at/revoked_by alanlarını atlamıştı;
düzeltildi. `.tmp/runtime-transition-final-pg.xml` kalan 4 kontrol geçti (40.11 s):
stale review, canlı yetki iptali, sahte token, audit rollback ve legacy/snapshot
yayın uyumu. 10 değişen servis/görünümde Linux mypy temiz; ilgili ruff, migration
drift, Django system check ve diff whitespace kontrolü temiz. Tarayıcı kabulü ve
güncel stack rollout'u bekliyor. R4 saklama süresi için kullanıcı tercihi soruldu;
hiçbir gerçek generation üzerinde temizlik veya şema geçişi çalıştırılmadı.

R5 dar metin düzeltmesi: geçiş ekranı browser incelemesinde senaryo ana sayfasında
İngilizce durum/izleyici etiketi ve teknik veri bağı açıklaması görüldü. Görünen
metinler sadeleştirildi; veri açıklamasındaki yinelenen aday-test düğmesi çıkarıldı,
ana yayın eylemi ve gelişmiş ayrı adımlar korunuyor. İzin/model değerleri değişmez. Ortak konsolun
geri kalanının tamamlandığı anlamına gelmez.

Dar browser kontrolü: mevcut 8109 fixture durdurulup dosya yedeği alındı,
evaluations0006/workflows0021/releases0007/ingestion0038 yalnız bu izole SQLite
veritabanına uygulandı ve fixture yeniden başlatıldı. Manager kullanıcıyla Senaryo
→ Gelişmiş → Veri yenileme ayarı önizlendi ve fixture senaryosu ayarı kaydedildi.
DB okuması scenario snapshot/active_generation olurken Release #2'nin hâlâ aktif
legacy, #1'in superseded legacy olduğunu doğruladı; yeni yayın/Run oluşturulmadı.
MCP Source #7 planında yeni otomatik yayın seçeneği ve maliyet/başarısızlık açıklaması
göründü; bağlı hedefi olmayan fixture'da liste boş, plan değiştirilmedi. Tam rol,
mobil ve worker kabulü açık. Ana PostgreSQL/MinIO healthy; ana web/Redis/workers
çalışmıyor. Bu bilgiler sonraki runtime işlemi öncesi yeniden sorgulanmalıdır.

R5 doküman listesi: mevcut tam liste ve set başına ayrı sürüm sayımı yerine aynı
yetki/aktif organizasyon süzgeci üzerinde ad/kimlik araması, durum süzgeci ve kararlı
25 kayıtlık sayfalama. Sürüm sayısı tek aggregate sorgusundan gelecek. Arama girdisi
200 karakterle sınırlı; önce yetki kapsamı uygulanır. Boş liste ile aramada sonuç
bulunmaması ayrılır; filtreler sayfa bağlantılarında korunur. Ayrı bir durum/izin
otoritesi veya yeni indeks/bağımlılık yok.

Doküman listesi `.tmp/document-list-filter-sqlite.xml` 2 geçti (28.93 s):
27 yetkili kayıt iki sayfada, başka tenant eşleşmesi gizli, doğru sürüm sayımı,
arama/durum ve bağlantılarda filtre koruma. Browser'da İzin araması doğru tek seti,
Etkin durumunu ve 3 sürümü gösterdi. Görsel incelemede oluşturma formu listeyi
itiyordu; aynı mevcut form kapalı details içine alındı, arama barı ortak senaryo
yerleşimiyle hizalandı. Son yerleşim görsel kontrolü bekliyor.

Kaynak hazırlama kartı artık otomatik publication sonucunu ayrı gösterir; yalnız
completion outbox'un bitmiş olması başarı sayılmaz, tamamlanmış ScenarioPublication
kanıtı gerekir. Değişen plan eski hazırlığı yanlışlıkla yayınlanmış gösteremez.
`.tmp/source-publication-presentation-pg.xml` 4 geçti (44.36 s), REST/MCP ve iki
runtime sözleşmesinde bu ayrım ve başarısız eval açıklaması. Console views ve
connector_presentation için Linux mypy temiz. R4 süre tercihinin cevabı bekleniyor.

R4 retention uygulama varsayımı (yanıt gelene kadar 90 gün): owner-only exact
organization/index komutu, varsayılan preview; apply bir çağrıda en fazla 1000 shared
chunk siler. Yayın/eval/Run generation, seçili set sürümü, türetilmiş generation,
source preparation ve çalışan build referansları korunur. Metadata/ID/job/doküman
kayıtları silinmez; legacy tablolarına dokunulmaz. Sealed→retired yalnız aynı owner
kontrolü, 90 günlük değişmezlik ve SQL referans kontrolüyle açılır; normal writer
koruması sürer. Fence ve bir batch+audit atomik; kalan retired batch'ler idempotent
sürdürülür. Eklemeli migration reverse retirement history varsa reddeder. Gerçek
veride apply çalıştırılmayacak; servis ve SQL yalnız disposable PG ile doğrulanacak.

R4 retention kanıtı: `.tmp/shared-retention-core-pg.xml` 4 geçti (31.11 s),
preview, bounded resume, metadata koruma, recent/active/derived referans ret,
audit rollback, ordinary role + sahte owner flag ret ve history reverse koruması.
`.tmp/shared-retention-evidence-pg.xml` 2 geçti (37.58 s): legacy/snapshot evaluation
hazırlık verisi 91 günlük olsa bile reclaim tarafından korunuyor. İki bakım dosyası
Linux mypy temiz. 0039 yalnız disposable PG'ye uygulandı; gerçek veri temizliği yok.
90 gün henüz kullanıcı cevabı değil, açıkça bildirilen konservatif uygulama varsayımı.
Önceden geçen 20k/mixed workload tekrarlanmadı; build-load/generic-plan ve bütünleşik
geçiş/kapsam kabulü açık kalıyor.

Son fixture güncellemesi: 0039 da yalnız SQLite deneme DB migration state'ine
uygulandı (PG guard'ları bu backend'de çalışmaz), mevcut 8109 server güncel kodla
yeniden açıldı. Son masaüstü screenshot'ta kapalı oluşturma paneli, hizalı arama
kontrolleri ve tablo aynı görünümde, kesilme yok. Aktif CUA tabı #2 doküman listesinde
İzin filtresinde bırakıldı. Ana DB/schema/üretim rollout/gerçek purge yapılmadı.

Bu devamın nihai dar incelemesi: source publication değişmez tek origin/eval zinciri;
geçiş yalnız gelecek yayınların ayarı; liste sorgusunda yetki süzgeci sayfalamadan
önce; retention exact owner/index ve referans/fence/batch/audit atomikliği incelendi.
Yeni üretim bağımlılığı, secret, public HTTP API, tenant kapsam genişlemesi yok.
Yayın/test/operasyon eylemlerinde mevcut güncel yetki kontrolleri korunuyor.
Loglara içerik/prompt/vector yazılmaz; audit yalnız güvenli kimlik/sayı/sonuç taşır.
Çalışılmayanlar: tam stack/provider/worker browser gate, genel regression son koşusu,
retention race/load ve generic/custom plan kapasitesi, legacy DDL privilege cutover.
Kalan risk: bu bütünleşik kabul ve rollout yapılmadan tüm görev Verified sayılamaz.
