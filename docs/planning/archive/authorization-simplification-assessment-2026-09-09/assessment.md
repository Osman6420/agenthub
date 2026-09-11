# Yetkilendirme sadeleştirme değerlendirmesi — 9 Eylül 2026

## Sonuç

Organizasyon, proje ve senaryo sınırları gerekli. Mevcut modelin her günlük iş
sorumluluğunu ayrı atamaya dönüştürmesi ise varsayılan ürün deneyimi için fazla
parçalı. Öneri: az sayıda anlaşılır rol, sunucuda ayrıntılı işlem denetimi ve yalnız
gerçek ihtiyaç olduğunda açılan görev ayrılığı. İzin kontrolü sayısını azaltmakla
kullanıcının yönetmek zorunda olduğu izin sayısını azaltmak aynı şey değildir.

Bu bir değerlendirmedir; uygulanmış veya onaylanmış yeni yetki modeli değildir.
9 Eylül çalışma ağacı, mevcut yerel değişiklikler dahil incelendi. Canlı kullanıcı
atamaları, müşteri sözleşmeleri ve üretim kullanımı araştırılmadı. Önceki
[ADR-0015](../../../adr/0015-responsibility-based-operator-authorization.md)
görev ayrılığını bilinçli olarak seçmiş; bu rapor onu değiştirmez.

## Mevcut insan rolleri: tek tek değerlendirme

Kaynak: [rol tanımları](../../../../apps/identity/models.py),
[merkezi karar servisi](../../../../apps/identity/authorization.py),
[atama servisi](../../../../apps/identity/assignment_services.py).
Beş kapsamda 13 adlandırılmış sorumluluk ve 24 işlem capability'si var.
Üyelik ve kurtarma süper kullanıcısı bu 13 role dahil değil.

| Kapsam / mevcut rol | Gerçekte sağladığı yetki | Öneri |
| --- | --- | --- |
| Platform / Global administrator | Platform ve idari kapsamları yönetir; normal kullanımda içerik okuma, senaryo düzenleme veya onay verme getirmez | Kalsın; günlük platform işletimi |
| Organizasyon / Administrator | Organizasyon, üyeler ve sorumluluk atamaları; geniş metadata/audit/runtime görünürlüğü | Kalsın; erişim idaresi açıkça isimlendirilsin |
| Organizasyon / Auditor | Organizasyon, proje, senaryo metadata'sı, audit ve runtime görünürlüğü | İsteğe bağlı denetçi; normal ekibin zorunlu rolü olmasın |
| Proje / Viewer | Projeyi ve içindeki senaryoları görür | Kalsın; senaryoya görünürlük aktarımı zaten var |
| Proje / Administrator | Projeyi yönetir, senaryo oluşturur; senaryo viewer/editor atayabilir; kendiliğinden düzenleyemez | Proje yöneticisi deneyimi sadeleştirilsin; yeni kapsam aktarımı ayrıca kararlaştırılsın |
| Senaryo / Viewer | Senaryo görüntüleme | Kalsın |
| Senaryo / Editor | Görüntüleme, düzenleme ve test; aday hazırlama/derleme ve publish-and-verify yolu da bu aktöre açık | Kalsın; düzenle ve test et tek rol |
| Senaryo / Release manager | Yayına alma, geri alma ve çağrılabilirlik geçişleri | Varsayılanda senaryo yöneticisine dahil; bağımsız yayıncı ancak görev ayrılığı gerekiyorsa |
| Senaryo / Runtime operator | Runtime görüntüleme, iptal, durdurma ve sürdürme | Varsayılanda senaryo yöneticisine dahil; ayrı operasyon ekibi varsa uzman rol |
| Senaryo / Approver | Senaryoya ait araç onaylarını görür ve karara bağlar | Yalnız onay gerektiren araçların kullanıldığı senaryolarda ayrı sorumluluk |
| Doküman seti / Metadata viewer | Set metadata'sı | Basit katalog görünürlüğünden türetilebilir; özel metadata gizliliği ihtiyacı varsa tutulur |
| Doküman seti / Content reader | Metadata ve kaynak içeriği | Kalsın; senaryo çalıştırma yetkisiyle eşitlenmesin |
| Doküman seti / Manager | İçerik, hazırlama/operasyon ve senaryoya retrieval izni verme | Kalsın; tek veri yöneticisi rolü |

Üyelik yalnız organizasyona bağlılığı ve organizasyon kabuğunu açıyor. Normal
organizasyon yöneticisi senaryo editörü değil; proje yöneticisi de oluşturduğu
kapsamda otomatik editör değil. Proje yöneticisi viewer/editor atayabiliyor fakat
release/runtime/approver atamalarını organizasyon yöneticisi yapıyor. Bu durum
"yöneticiyim ama işimi yapamıyorum" deneyiminin doğrudan kaynağı.
İlgili davranışlar [kimlik testlerinde](../../../../apps/identity/tests/test_responsibility_authorization.py)
ve [Studio testlerinde](../../../../apps/builder/tests/test_responsibility_authorization.py)
açıkça doğrulanıyor.

Model tamamen hiyerarşisiz değil: proje rolü senaryo görünürlüğü sağlar. Fakat
eylem yetkileri aynı şekilde aktarılmaz. Yalnız tek senaryoya atanan kişi aynı
projedeki diğer senaryolara otomatik erişmemelidir.

## 24 insan işlemi için önerilen karşılık

Bu tablo kullanıcıya 24 kutu sunma önerisi değildir. Sunucuda bu ayrımların çoğu
korunabilir; roller bunları anlamlı paketler halinde verir.

| Mevcut capability | Önerilen ürün karşılığı |
| --- | --- |
| `platform.manage` | Platform yönetimi |
| `organization.view` | Aktif organizasyon üyeliği |
| `organization.manage` | Organizasyon yöneticisi |
| `membership.manage` | Organizasyon yöneticisi |
| `responsibility.manage` | Organizasyon erişim yönetimi; proje/senaryo delegasyonu açık kapsamlı |
| `audit.view` | Yönetici / isteğe bağlı denetçi |
| `project.view` | Proje görüntüleyen ve üzeri |
| `project.manage` | Proje yöneticisi |
| `scenario.create` | Proje düzenleyen veya yöneticisi — yeni düzenleyen rolü bir öneri |
| `scenario.view` | Senaryo görüntüleyen ve üzeri |
| `scenario.edit` | Senaryo düzenleyen / yöneticisi |
| `scenario.test` | Düzenleyen / yönetici; ücretli test limitleri ayrıca uygulanır |
| `scenario.release` | Senaryo yöneticisi; isteğe bağlı bağımsız yayıncı |
| `scenario.approval.view` | İsteğe bağlı onaylayan |
| `scenario.approval.decide` | İsteğe bağlı onaylayan; ilgili araç işleminin onayı |
| `document_set.metadata.read` | İzinli katalog görünürlüğü; otomatik içerik erişimi değildir |
| `document_set.retrieve.grant` | Veri yöneticisinin senaryoya kullanım izni |
| `document_set.content.read` | Veri okuyucusu / yöneticisi |
| `document_set.content.manage` | Veri yöneticisi |
| `document_set.operations.manage` | Veri yöneticisi |
| `runtime.view` | Senaryo yöneticisi; düzenleyene kendi test sonuçları; korumalı çıktı ayrıca filtrelenir |
| `runtime.cancel` | Yönetici; kendi testini iptal etme için sahiplik denetimi gereken ayrı ürün davranışı |
| `runtime.pause` | Senaryo yöneticisi |
| `runtime.resume` | Senaryo yöneticisi |

## Önerilen basit rol modeli

| Kapsam | Varsayılan roller | Sınır |
| --- | --- | --- |
| Organizasyon | Üye, Yönetici | Üye olmak bütün projeleri açmaz; yönetici üyelik/erişim idaresini yapar |
| Proje | Görüntüleyen, Düzenleyen, Yönetici | Projeye katılım ve senaryolara uygulanacak standart erişim |
| Senaryo | Görüntüleyen, Düzenleyen, Yönetici | Yönetici düzenleme + yayın + çalışma kontrolü + sınırlandırılmış erişim yönetimi |
| Doküman seti | Okuyucu, Yönetici | Kaynak içeriği ve veri kullanım izni ayrı korunur |
| API istemcisi | İzinli senaryoları çalıştırma | Araçlarla veri değiştirme ve operasyonel erişim gelişmiş seçenekler |

Senaryo ekranında "Projeden devral" ve "Bu senaryoya özel erişim" yeterli olabilir.
Devralma açık bir politika olmalı: standart senaryolar proje rolünün karşılığını
alır; özel erişimde doğrudan atamalar değerlendirilir. Proje yöneticisinin özel
senaryolar üzerindeki erişim-idare yetkisi ayrıca açıkça gösterilmeli; gizlilik
vaadi ile kendine yetki verebilen yönetici modeli karıştırılmamalı.

Bu devralma mevcut davranış değildir ve geçmiş atamalara topluca uygulanamaz.
İlk güvenli adım, mevcut yetkileri değiştirmeyen toplu rol paketleri ve daha iyi
isimlendirmedir. Gerçek rol birleştirme ikinci adım olur. Sadece release yetkisi
olan birini otomatik yeni Yönetici yapmak ona düzenleme ve operasyon yetkisi de
verir; bu nedenle eski rollerin her biri yeni role körlemesine eşlenmemeli.

Onaylayan günlük üçüncü/dördüncü adım rolü değil, riskli araç işlemlerine yönelik
isteğe bağlı sorumluluk olsun. Ayrı yayın yöneticisi ve runtime operatörü yalnız
gerçek ayrı ekip/sorumluluk ihtiyacı varsa gelişmiş görev ayrılığında tutulsun.
Yeni atama ekranında bu uzman rolleri her kullanıcıya zorunlu olarak sunmayın.

## API/MCP istemcisindeki 10 izin

Kaynaklar: [capability listesi](../../../../apps/identity/capabilities.py),
[istemci formu](../../../../apps/console/forms.py),
[gateway](../../../../apps/gateway/views.py),
[MCP işlemleri](../../../../apps/mcp/service.py),
[araç proxy'si](../../../../apps/tools/proxy.py).

| İzin | Mevcut kullanım | Öneri |
| --- | --- | --- |
| `workflow_run` | REST/MCP admission ve alt çalışma kabulünde etkin | İzinli senaryo bağının standart çalıştırma izni; ayrı teknik kutu gerekmeyebilir |
| `tool_call` | Okuma yapan araç çalıştırılırken etkin | Araç kullanan senaryo için anlaşılır erişim paketi; sunucu kontrolü kalsın |
| `tool_call_side_effect` | Veri değiştiren araç çağrısında etkin | Açık, gelişmiş izin kalsın; yeni release bu yetkiyi kendiliğinden artırmasın |
| `tool_approve` | Üretim kaynak aramasında bu capability ile karar veren yol bulunmadı; gerçek onay insanın `scenario.approval.decide` yetkisiyle | Yeni istemci formundan kaldırma adayı; insan onayıyla karıştırılmasın |
| `memory_read` | Bu capability'yi denetleyen üretim yolu bulunmadı | Özellik uygulanana kadar yeni formdan kaldırma adayı |
| `memory_write` | Bu capability'yi denetleyen üretim yolu bulunmadı | Aynı |
| `retrieve_debug` | MCP/protokol ve senaryo bağı denetleniyor; yanıt şu an boş `chunks` ve `redacted: true` | Mevcut kullanıcı değeri sınırlı; normal istemciden gizle, gerçek tanılama gerekirse iç operatör yüzeyi |
| `ingestion_read` | MCP ingestion status | Genel senaryo istemcisinden ayır; kapsam doğruluğunu düzeltmeden yaygınlaştırma |
| `ingestion_trigger` | Form preset'i ve sözlükte var; bunu denetleyen gerçek trigger yolu bulunmadı | Yeni formdan kaldırma adayı |
| `release_promote` | Sözlükte var; console yayını insan release yetkisiyle yürür | Normal istemci formundan kaldırma adayı |

"Bulunmadı" sonucu üretim kaynaklarında enum adı ve literal metin araması ile
ilgili çağrı yollarının incelenmesine dayanır; dışarıdaki bir entegrasyonun bu
değerleri kaydetmediği anlamına gelmez. Saklanmış izinleri veya kabul edilen API
değerlerini silmek için uyumluluk incelemesi gerekir.

Mevcut preset yalnız checkbox dolduruyor; kullanıcıdan hem preset hem exact liste
bekleniyor ve uyumsuzsa form reddediliyor. Basit ekranda istemci adı, token,
izinli senaryolar ve kota yeterli. İleri seçeneklerde veri değiştiren araçlara
izin ve iç operasyon erişimi bulunabilir. Tool allowlist, insan onayı, ağ sınırları
ve alt çalışmanın üst çalışmadan fazla yetki alamaması sunucuda korunmalı.

## Doküman erişiminin neden üç katmanı var?

[Retrieval kodu](../../../../apps/retrieval/providers.py) normal tüketimde şu
kesişimi alıyor: tenant + release'in sabitlediği set sürümleri + canlı
ScenarioDocumentSetGrant + tüketici DocumentSetGrant + aktif indeks + silinmemiş
dokümanlar. İnsan kaynak metni için ayrıca
[content-read denetimi](../../../../apps/documents/content_access.py) var.

- Senaryo hangi veriyi kullanabilir? Kalsın; editörün rastgele gizli set bağlaması engellenir.
- İnsan orijinal dokümanı/parçayı görebilir mi? Kalsın; çalıştırma ile aynı izin değildir.
- Aynı senaryoyu çağıran iki istemci farklı dokümanlara erişmeli mi? Ancak gerekiyorsa
  ek consumer/set matrisi kullanıcı tarafından yönetilsin.

Aynı veri erişimine sahip bütün istemciler için senaryo veri izninden türeyen,
açıkça seçilmiş standart erişim modu düşünülebilir. Mevcut eksik tüketici grant'i
otomatik "izin var" sayılmamalı. İstemciye göre veri ayrımı veya gerçek son
kullanıcıya göre ACL gerekiyorsa bu kontrol korunur. Ortak uygulama token'ı
arkasındaki kullanıcıları ayıramaz; gerçek kullanıcı bağlamı ayrıca doğrulanmalıdır.

Çalışma ağacında `grant_scenario_document_set_access_if_authorized` ve
`_ensure_evaluation_consumer_grant` gibi kolaylaştırıcı yollar zaten eklenmiş.
Bu, tekrar eden kurulum maliyetinin kaynakta da görülebildiğini gösterir; güncel
değişiklikler değerlendirmeye dahil edildi, değiştirilmedi.

## Tarayıcı tarafı

Bağımsız bir React rol/politika motoru bulmadım. `useBuilder` salt okunurluğu
sunucunun `draft.can_write` değerinden alıyor; API yazma taleplerinde tekrar
gerçek senaryo yetkisini denetliyor. Bu yaklaşım doğru. Butonun görünmemesi
güvenlik sınırı değildir; kullanıcıya yapamayacağı işi sunmamak için vardır.

Asıl sadeleştirme adayları:

1. `org.can_write` mevcut console bootstrap'ında daima false; React hâlâ onu
   `can_author_scenario` ile birleştiriyor. Eski/geniş kapsam temsilini kaldırma adayı.
2. `can_compile_release` adı yanıltıcı: bayrak `SCENARIO_RELEASE` üzerinden
   üretiliyor, oysa `_candidate_scenario` editörün de aday derlemesine izin veriyor.
   Aday hazırlama ve canlıya alma eylemleri için doğru isimli sunucu kararları üretin.
3. `can_write`, `can_evaluate`, `can_compile_release`, pause/resume ve menü
   bayrakları farklı noktalarda oluşturuluyor. Nesneye ait tek `allowed_actions`
   çıktısı ve ortak görünüm yardımcıları tutarsızlık ihtimalini azaltabilir.
4. Senaryo prompt'u, retrieval ayarı, workflow düğümü ve test soruları için yeni
   bağımsız roller eklemeyin: mevcut çoğu düzenleme aynı senaryo editörüne bağlı.
   Düğüm panelindeki tekrar eden `disabled` kontrolleri ayrı yetki atamaları değildir.
5. Kodda geçen bazı `role` sözcükleri artifact bağlama rolü, `capability_missing`
   ise AI yazarının eksik düğüm yeteneğidir; kullanıcı yetkilendirmesi sayılmamalıdır.

Kaynak: [React uygulaması](../../../../frontend/src/App.tsx),
[builder controller](../../../../frontend/src/useBuilder.ts),
[API](../../../../apps/builder/api.py),
[console görünümü](../../../../apps/console/views.py),
[scope filtreleri](../../../../apps/console/scoping.py).

Sunucu her istekte yetkiyi doğrulamalı; tarayıcı yalnız sonucu göstermeli.
Bu ayrım [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
ile de uyumludur. Önerilen rol sayısı OWASP zorunluluğu değil, bu ürün için tasarım değerlendirmesidir.

## Diğer korumalar ve inceleme bulguları

- LDAP/session insan kimliği ile bearer tüketici kimliği ayrı kalmalı; token iptali,
  döndürme, tenant durumu ve REST/MCP protokol kontrolü anlamlıdır.
- Üyelik iptali, atama süresi, son yöneticiyi koruma ve audit kayıtları rol
  ekranının karmaşıklığından bağımsızdır. Kurtarma süper kullanıcısı günlük rol olmasın.
- Tenant RLS/membership nesne seviyesinde yetkilendirmenin yerini tutmaz. Assignment
  RLS migration'ları kaynakta mevcut; canlı non-owner PostgreSQL etkinliği bu task'ta doğrulanmadı.
- Embedding/OCR tenant grant'leri ve Confluence/REST profilinin tam doküman setine
  grant'i ücretli hizmet ve dış sisteme erişim sınırıdır; senaryo alt rolü gibi kaldırılmamalı.
- Tool input/output allowlist, approval, outbound güvenliği, çalışma limitleri ve
  child capability kesişimi rol değildir; yürütme güvenlik politikasıdır.
- `apps/identity/roles.py` eski sekiz rolü taşıyor; incelenen üretim uygulama ve
  config kaynaklarında import/referans bulunmadı. Canlı rol envanterine eklenmedi;
  sonraki temizlikte dış kullanım kontrolünden sonra kaldırılabilir.
- **Kapsam tutarsızlığı:** MCP `_ingestion_status`, kaynakları organizasyona göre
  seçiyor ve istemcinin herhangi bir aktif binding'inde `ingestion_read` bulunmasını
  yeterli sayıyor. Kaynağa/projeye/sete ilişkin grant ile eşleştirme yapmıyor;
  yorumdaki proje kapsamı kodda sağlanmıyor. Aynı organizasyonda istenmeyen source
  ID/status metadata görünürlüğü riski var. Bu kaynak inceleme bulgusudur, canlı
  istismar doğrulaması değildir. Ayrı düzeltme/negatif test gerekir.
- Araç self-approval karşılaştırması gerçek `initiated_by_user_id` varsa etkin.
  Mevcut çağrılarda bu alanın doldurulmadığı çalışma ağacında belgelenmiş;
  paylaşılan makine kimliği üzerinden uçtan uca insan görev ayrılığı var sayılmamalı.

## Uygulama sırası ve karar sınırları

Önce görünür olmayan/işlevsiz izinleri yeni formlardan ayırın, preset'i tek seçim
yapın, eylem adlarını düzeltin ve mevcut yetkileri koruyan toplu atamalar sunun.
Sonra gerçek ihtiyaç doğrulanırsa üç rol ve açık senaryo devralma politikasına geçin.
Doküman tüketici matrisini ancak istemcilerin aynı veri erişimine sahip olduğu
senaryolarda, açık erişim modu ve önce/sonra erişim karşılaştırmasıyla sadeleştirin.

Geçiş planı her eski atama için önce/sonra izin farkını, özel senaryoları,
revocation/expiry davranışını, cache/worker durumunu ve API uyumluluğunu kapsamalı.
Karışık eski/yeni politika sürümleri ile çalışmayın; otomatik yetki genişlemesi
yaratan dönüşümlere izin vermeyin. Yeni testlerde aynı tenant farklı proje/senaryo,
başka tüketici run'ı, gizli kaynak içerik, doğrudan API isteği, iptal edilmiş yetki,
side effect ve gerekli onaylar özellikle sınanmalı.

## Son rapor

- Summary: İnceleme tamamlandı; üç temel rol ve isteğe bağlı görev ayrılığı önerildi.
- Files changed: Yalnız bu değerlendirme belgeleri, arşiv dizini ve master-plan bağlantısı.
- Architecture impact: Mevcut mimari değişmedi; yeni model öneri olarak kaldı.
- Security impact: Kontrol kaldırılmadı; MCP scope riski kaydedildi.
- Authorization impact: Mevcut izin/rol/devralma davranışı değiştirilmedi.
- Data and privacy impact: Canlı veri okunmadı veya değiştirilmedi; içerik ayrımı korundu.
- Logging, metrics, tracing and audit impact: Değişiklik yok.
- Database and migration impact: Şema/migration/canlı veritabanı değişikliği yok.
- Tests and verification results: [Doğrulama kaydı](verification.md).
- Unverified assumptions: Gerçek rol kullanımı, görev ayrılığı yükümlülükleri ve istemci veri farklılıkları.
- Remaining risks: Yetki genişletmeden rol dönüşümü tasarlanmalı; canlı RLS/browser kapsamı doğrulanmadı.
- Manual review required: Uygulamaya geçmeden devralma, yayın yetkisi ve tüketici veri ayrımı ürün kararı.
