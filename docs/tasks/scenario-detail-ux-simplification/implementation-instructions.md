> Superseded: [tek aktif geliştirme görevi](../Agent_Hub_MD/plan.md). Bu belge tarihsel kaynaktır; bağımsız uygulanmaz.

# Senaryo Detay Ekranını Sadeleştirme — Coding Agent Uygulama Talimatı

## Rolün ve çalışma biçimin

Bu repository üzerinde çalışan kıdemli ürün odaklı full-stack geliştirici, uygulama güvenliği
mühendisi ve SRE olarak hareket et. Repository kökündeki `AGENTS.md` ve `docs/ai/` kurallarını
eksiksiz uygula.

Çalışmaya başlamadan önce:

1. Aktif handoff'u canlı kod, test ve runtime durumuyla doğrula.
2. `git status` ile kullanıcıya ait mevcut değişiklikleri belirle; hiçbirini ezme, geri alma veya
   kapsam dışı biçimde yeniden düzenleme.
3. [`plan.md`](plan.md) ve [`threat-model.md`](threat-model.md) dosyalarını canlı gerçekliğe göre
   güncelle.
4. `docs/manual-testing-guide.md` bölüm 0, canonical Compose dosyası, canlı Compose rolleri ve health
   endpoint'ini doğrulamadan uygulamayı başlatma, durdurma veya teşhis etme.
5. Codebase Memory mevcut ve sağlıklıysa mimari keşif için; Serena mevcutsa exact sembol ve referans
   doğrulaması için kullan. Son doğruluk kaynağı canlı kod, testler, runtime yapılandırması ve gerçek
   tarayıcıdır.

Bu talimat UI'da görsel makyaj istemez. Bilgi mimarisini ve durum modelini kullanıcı hedeflerine göre
sadeleştirirken mevcut backend güvenlik ve yaşam döngüsü sınırlarını koruyan eksiksiz bir ürün
değişikliği ister.

## Problem

Senaryo detay sayfası şu anda birbirinden farklı işleri tek, uzun yüzeyde birleştiriyor:

- ilk kurulum,
- tekrarlanan taslak/test/yayın döngüsü,
- doküman ve istemci ilişkileri,
- input/output sözleşmeleri,
- tek seferlik test,
- API/MCP entegrasyon örnekleri,
- release ve artifact teşhisi,
- lifecycle/runtime acil kontrolleri,
- Studio revision bilgisi,
- LLM workflow DSL geliştirici rehberi.

Mevcut altı adım bir defalık kurulum checklist'i gibi görünür fakat son üç adım her değişiklikte
tekrarlanır. Bir aktif senaryo aynı anda “Temel bilgiler bekliyor”, “Akış bekliyor” ve “Yayına al
tamamlandı” gösterebilir. Bu, kullanıcının “Şu anda ne canlı?” ve “Sıradaki doğru işlem ne?”
sorularını cevaplamaz.

Canlı inceleme başlangıç kanıtı:

- 1280x720 görünümde genişletilmiş Gelişmiş alanı yaklaşık 3.616 px,
- tam sayfa yaklaşık 5.539 px,
- 390x844 görünümde Gelişmiş alanı yaklaşık 5.420 px,
- mobil tam sayfa yaklaşık 8.737 px,
- tek Gelişmiş disclosure içinde sekiz başlık ve on beş bağlantı/buton.

Bu ölçümleri nihai çözüm için hedef olarak kopyalama; güncel build üzerinde yeniden ölç ve önce/sonra
kanıtını `verification.md` içine kaydet.

## Ürün hedefi

Senaryo sayfası ilk bakışta yalnız şu soruları cevaplamalıdır:

1. Bu senaryo şu anda çağrılabilir mi?
2. Hangi release canlı?
3. Yayınlanmamış bir değişiklik veya bekleyen aday var mı?
4. Test ve bilgi kaynağı durumu nedir?
5. Benim yetkimle yapabileceğim sıradaki doğru işlem nedir?

Hedef zihinsel model:

```text
İlk kurulum: Tasarla → Bilgi kaynağını hazırla (gerekiyorsa) → Kontrol et → Yayına al

Günlük kullanım: Mevcut durum → Tek sıradaki eylem → Ayrıntıya gerektiğinde git
```

Candidate, manifest, exact artifact pin, revision ve DSL gibi iç kavramlar ana kullanıcı akışında
birer hedef değildir. Backend'de korunmalı; kullanıcıya yalnız karar vermesi veya teşhis yapması
gerektiğinde gösterilmelidir.

## Bağlayıcı mimari ve güvenlik sınırları

Aşağıdakileri değiştirme veya dolanma:

- Mutable `WorkflowDraft` ile immutable artifact/release ayrımı.
- Server-side manifest türetme ve compiler doğrulaması.
- Deterministik eval ve hazır exact indeks gerektiren fail-closed promotion kapısı.
- Scenario Editor ile Scenario Release Manager yetkilerinin ayrılığı.
- Runtime Operator, document-set manager/content reader ve consumer-access yetkilerinin ayrı olması.
- Exact scenario/organization tenant scope, cross-tenant fail-closed davranışı.
- CSRF, POST-only state changes, audit olayları ve idempotency kuralları.
- Promotion, activation, rollback, canary ve runtime servislerinin mevcut domain sahipliği.
- Immutable geçmiş ve geri dönüş yeteneği.

UI hangi butonu gösterirse göstersin istemci hiçbir zaman authorization veya readiness kaynağı
değildir. View/template içinde doğrudan model mutasyonu ekleme. Birleştirilmiş kullanıcı eylemi
mevcut domain servislerini doğru sırada çağırabilir; her servis kendi yetki, önkoşul, transaction ve
audit kontrolünü korumalıdır.

Authentication, authorization, tenant izolasyonu, public API, migration veya üretim dependency
değişikliği gerektiğini düşünürsen repository kuralındaki açık kullanıcı onayını almadan ilerleme.

## Hedef bilgi mimarisi

### 1. Senaryo başlığı ve birincil eylem

Başlık alanında göster:

- senaryo adı,
- anlaşılır durum: Kullanımda / Taslak / Kullanıma kapalı / Operasyonel olarak durduruldu,
- API alias,
- aktif release özeti,
- tek birincil eylem.

Birincil eylemi authoritative server state ve kullanıcının exact yetkisi belirlemelidir. Örnek karar
sırası; canlı kodun gerçek durumlarıyla doğrula:

| Durum | Birincil eylem |
| --- | --- |
| İlk akış hazırlanmamış | Akışı hazırla |
| Yayınlanmamış taslak değişikliği var | Değişiklikleri test et |
| Candidate değerlendirmesi çalışıyor | Test sonucunu görüntüle |
| Candidate testi başarısız | Hataları incele |
| Candidate testi geçti ve kullanıcı release manager | Yayına al |
| Candidate testi geçti fakat kullanıcı editor | Release manager bekleniyor / adayı görüntüle |
| Aktif, bekleyen değişiklik yok | Senaryoyu test et veya Akışı düzenle; ürün kararıyla yalnız biri primary olsun |
| Runtime durdurulmuş | Durdurma nedenini göster; yetkiliyse devam ettir |
| Senaryo kullanıma kapalı | Yetkiliyse kullanıma aç; tüm önkoşulları sunucuda yeniden doğrula |

Aynı anda iki büyük primary CTA gösterme. Kullanılamayan işlemleri kalıcı pasif buton olarak bırakma;
durumu ve engeli metin olarak göster, gerekiyorsa yetkili hedefe bağlantı ver.

### 2. İlk kurulum rehberi

Henüz hiç aktif release'i olmayan yeni senaryoda en fazla dört kullanıcı-hedefli aşama göster:

1. **Tasarla** — temel kimlik, sözleşme varsayılanları ve workflow.
2. **Bilgi kaynağını hazırla** — yalnız compiled workflow retrieval gerektiriyorsa zorunlu; retrieval
   kullanmayan akışta gizli veya açıkça isteğe bağlı.
3. **Kontrol et** — yayınlanmış akıştan candidate üretme ve uygulanabilir test sonucu.
4. **Yayına al** — yalnız release-manager kararı ve mevcut tüm fail-closed kapılar geçince.

Adımların durumunu artifact veya draft'ın salt varlığından tahmin etme. Workflow requirement analizi,
exact candidate/eval ve aktif release gibi mevcut authoritative kaynakları yeniden kullan. Template'e
dağılmış paralel readiness mantığı yazma.

İlk release başarıyla aktif olduktan sonra bu rehber ana yüzeyi işgal etmemeli. Ürün kararıyla:

- tamamen güncel durum paneline dönüşsün veya
- “İlk kurulum tamamlandı” adıyla kapalı, ikincil yardım alanı olsun.

### 3. Yayın sonrası güncel durum paneli

Kompakt bir panelde yalnız güncel karar verdiren bilgileri göster:

- **Canlı sürüm:** release numarası, yayın zamanı ve durum,
- **Düzenleme:** canlıyla aynı / yayınlanmamış değişiklik / mutable draft yok,
- **Test:** son ilgili candidate/active release için çalışıyor / başarılı / başarısız / çalıştırılmadı,
- **Bilgi kaynağı:** gerekli değil veya bağlı set ve hazır release-pinned indeks özeti,
- **Erişim:** aktif istemci sayısı ve kritik eksik bağ/izin.

Her satır ayrıntının authoritative sayfasına gidebilir. Ham UUID, logical ID, checksum, manifest veya
doküman içeriği ana panelde gösterme.

### 4. Gerçek bölümler

Mevcut “Adımlar / Dokümanlar / Erişim / Gelişmiş” kontrolleri sekme gibi görünür fakat aynı uzun
sayfadaki anchor'lardır. İki güvenli yaklaşımdan birini, mevcut `console-navigation` işiyle
çakışmayacak şekilde seç:

1. ayrı server-rendered alt görünümler, veya
2. erişilebilir gerçek tab/panel davranışı.

Yalnız hash'i değiştirip bütün içeriği DOM'da alt alta tutan sahte sekmeleri nihai çözüm olarak
bırakma. Eğer aynı-sayfa bölüm bağlantısı korunacaksa `role="tab"` kullanma ve bunu “Bölümler” olarak
sun. `Gelişmiş` bağlantısı kapalı bir disclosure'a gidiyorsa disclosure otomatik/açık ve odak doğru
olmalı; iki ayrı keşif tıklaması gerektirmemeli.

Önerilen destinasyonlar:

- **Genel:** güncel durum ve tek primary eylem,
- **Bilgi kaynakları:** doküman seti bağları ve readiness,
- **Test:** tek seferlik soru, soru setleri ve sonuçlar,
- **Entegrasyon:** istemci bağları, capability özeti, API/MCP çağrı örnekleri ve sözleşmeler,
- **Sürümler:** aktif/bekleyen özet ve release geçmişine erişim,
- **Ayarlar ve operasyon:** lifecycle/runtime kontrolleri.

Bu liste yeni route zorunluluğu değildir; hedef görev ayrımıdır.

## Mevcut Gelişmiş içeriğinin yerleşimi

### Aktif release artifact'leri

Senaryo detayındaki tam exact artifact listesini kaldır. Aynı bilgi release ayrıntısındaki **Exact
artifact pinleri** bölümünde authoritative olarak zaten bulunur.

Senaryo sayfasında en fazla şunu göster:

```text
Canlı sürüm #42 · 6 bileşen · Bütünlük doğrulandı
[Sürüm ayrıntısını aç]
```

Checksum mismatch veya çözümlenemeyen artifact varsa ayrıntıyı gizleme; ana durumda kritik uyarı ve
release ayrıntısına bağlantı göster. Normal durumda checksum değerini veya her artifact satırını
tekrarlama.

### Release'ler

Ana senaryo yüzeyinde geçmiş tablosunu kaldır. Yalnız:

- aktif release,
- varsa en yeni geçerli pending candidate,
- gerekiyorsa son başarısız test/rollback uyarısı

göster. Tam geçmişi ayrı **Sürümler** destinasyonunda veya mevcut yetkili release görünümünde sun.
Eski release'e rollback, yine exact release ayrıntısındaki mevcut **Bu sürüme geri dön** kontrolü ve
release-manager yetkisiyle çalışmalıdır.

### Akışın authoring durumu

Ayrı kartı kaldır. Revision/son publish bilgisi, Genel görünümdeki **Düzenleme** satırına ve Studio
içindeki kendi durum göstergesine aittir.

Şu durumları dürüstçe ayır:

- taslak canlı/published akışla aynı,
- yayınlanmamış değişiklik var,
- workflow artifact var fakat mutable Studio draft yok (legacy/GitOps/imported),
- hiç yayınlanmış workflow yok.

Aktif immutable release varken mutable draft yok diye senaryoyu “Akış bekliyor” gösterme.

### LLM için workflow DSL kurallarını al

Senaryo operasyon sayfasından kaldır. `Scenario Studio` içinde kapalı **Yardım / Geliştirici
araçları** alanına taşı. Bu alan:

- yalnız workflow düzenleme bağlamında görünmeli,
- normal kullanıcı akışına karışmamalı,
- rehber kopyalamanın artifact oluşturmadığını açıkça söylemeli,
- backend compiler doğrulamasının yerini almamalı,
- built-in AI authoring bulunuyorsa onunla yinelenen yönlendirme üretmemeli.

### Senaryoya sor

Gelişmiş ayar değildir. **Test** destinasyonuna taşı ve aktif/bekleyen hangi exact release üzerinde
çalıştığını açıkça belirt. Tek seferlik smoke test ile kalıcı soru seti/evaluation farkını koru.
Doküman parçaları ve cevap kanıtları mevcut ayrı content-read yetkisinden geçmeye devam etmelidir.

### Senaryoyu çağırma

**Entegrasyon** destinasyonuna taşı. Ana sayfada yalnız bağlı aktif istemci sayısı, desteklenen
protokoller ve kritik eksik yetki özeti kalsın. Uzun idempotency açıklaması, curl örnekleri ve MCP
ayrıntıları orada açılır olsun. Token, secret veya gerçek credential hiçbir zaman HTML'e basılmasın.

### Sözleşmeler

Input/output contract özetini **Entegrasyon** altında göster. Varsayılan sözleşme normal durumda
teknik görev gibi görünmemeli. Override yeni immutable sürüm üretmeye ve ancak yeni candidate/release
ile etkili olmaya devam etmelidir.

Aktif release exact contract pinine sahipken yeni scenario-namespace varsayılan kaydı bulunmadığı için
“Temel bilgiler bekliyor” deme. Legacy/imported durumu açıkça adlandır ve onarım/override işlemini
gerektiğinde öner.

### Lifecycle ve çalışma zamanı

İki farklı domain kararını birleştirme fakat kullanıcı dilinde aynı operasyon alanında açıkça ayır:

- **Kullanıma kapat / yeniden aç:** planlı scenario callability kararı,
- **Acil durdur / devam ettir:** incident, dependency outage, maintenance, capacity veya policy
  durumunda runtime kontrolü.

Broader-scope runtime suspension exact scenario resume'dan üstün kalmalıdır. Aktif suspension veya
callability problemi Gelişmiş kapalıyken de sayfanın üstünde görünmelidir. Neden kodu ve güvenli
açıklama audit için korunmalı; form yalnız exact yetkili kullanıcıya gösterilmelidir.

## Dil ve görsel hiyerarşi

Ana kullanıcı yüzeyinde mümkün olduğunca şu dili kullan:

- `artifact` → **bileşen**,
- `authoring durumu` → **düzenleme durumu**,
- `immutable version` → **değiştirilemez sürüm**,
- `exact scenario control` → **yalnız bu senaryo**,
- `runtime suspension` → **acil durdurma** veya bağlama uygun açık karşılık.

`release` ürünün yerleşik terimiyse korunabilir; kullanıcı araştırması/onaylı sözlük yoksa tek görevde
bütün ürünü mekanik olarak yeniden adlandırma. Teknik model adları ve İngilizce kodlar ayrıntı/teşhis
seviyesinde kalabilir.

Görsel kurallar:

- İç içe büyük gölgeli kartları azalt.
- Bir ekranda bir primary CTA kullan.
- Durumları renk yanında metin ve simgeyle belirt.
- Normal/başarılı ayrıntıları sıkıştır; blocker ve failure'ı öne çıkar.
- Mobilde yalnız yatay taşmayı değil, toplam görev uzunluğunu ve tıklama sayısını da ölç.
- Pasif butonları kalıcı durum etiketi yerine kullanma.
- Empty state, kullanıcıya neden ve uygulanabilir sonraki eylemi söylesin.

## Durum modeli ve edge case'ler

En az aşağıdaki matris için beklenen başlık, durum özeti, blocker ve primary eylemi açıkça tanımla ve
test et:

1. Yeni Empty Workflow; draft var, publish yok.
2. Yeni Document Answer; doküman seti/index yok.
3. Retrieval workflow; set bağlı fakat release-pinned indeks hazır değil.
4. Published workflow; candidate yok.
5. Candidate eval queued/running.
6. Candidate eval failed/error.
7. Candidate eval passed; editor kullanıcı.
8. Candidate eval passed; release manager kullanıcı.
9. Active release; temiz draft.
10. Active release; yayınlanmamış draft değişikliği.
11. Active release ve daha yeni pending candidate.
12. Active legacy/GitOps release; Studio draft yok.
13. Scenario disabled fakat active release mevcut.
14. Exact veya broader-scope runtime suspension.
15. Artifact checksum mismatch/çözümlenemeyen pin.
16. Organization disabled.
17. Superseded ve rolled-back release geçmişi.

“En yeni release” ile “promote edilebilir pending release” kavramlarını karıştırma; mevcut güvenli
`_pending_release`/domain mantığını doğrula ve yeniden kullan.

## Yetkiye göre görünürlük

Her rol için salt okunur bilgi ile eylemi ayır:

- Viewer mevcut durumu görebilir; state-changing CTA görmez.
- Editor akışı ve testleri yönetebilir; promotion/rollback/canary/runtime yetkisi kazanmaz.
- Release Manager candidate/promotion/rollback/canary/callability kararlarını yönetebilir; doküman
  içeriği veya Studio edit yetkisi kazanmaz.
- Runtime Operator yalnız izin verilen pause/resume kontrollerini kullanabilir.
- Document-set yetkileri senaryo editörlüğünden türemez.
- Organizasyon yöneticisi olmak exact release/runtime/content yetkisini örtük vermiyorsa UI da
  vermemelidir; canlı authorization kaynağını doğrula.

Yetkisiz eylemi yalnız CSS/hidden ile saklama; doğrudan route negatif testleri zorunludur.

## Uygulama yaklaşımı

1. Mevcut `_scenario_setup_steps` benzeri template-oriented sözlükleri incele. Gerekirse tek, typed ve
   test edilebilir scenario page state/read model oluştur; domain kurallarını kopyalama.
2. Durum modelini view içinde dağınık sorgularla değil, bounded sorgu sayısı ve açık helper/service
   sınırıyla üret.
3. N+1 ve unbounded history sorgusu ekleme. Release geçmişi sayfalı/bounded kalmalı.
4. Mevcut GET/POST route'larını ve domain servislerini yeniden kullan. Salt UI sadeleştirmesi için
   yeni paralel lifecycle endpoint'i yazma.
5. Mevcut working tree'de aynı şablon/navigation dosyaları değişmişse önce sahipliği ve intended
   davranışı uzlaştır; kullanıcı değişikliğini sessizce ezme.
6. İlk küçük diff'ten sonra state-matrix testlerini yaz; yalnız snapshot/metin varlığı testlerine
   güvenme.
7. Son diff'i gerçek rollerle canlı tarayıcıda kullan; yalnız HTML response testini UI kanıtı sayma.

## Test ve doğrulama gereksinimleri

### State/read-model testleri

- Her edge case için current state, blocker ve tek primary action.
- Retrieval gereksiniminin workflow analizinden gelmesi.
- Aktif legacy release + draft yok durumunun yanlış incomplete görünmemesi.
- Dirty draft ile active release'in açıkça ayrılması.
- Pending candidate'ın eski active release tarafından maskelenmemesi.
- Test sonucunun doğru exact release'e bağlanması.

### Authorization ve izolasyon

- Anonymous/session boundary.
- Viewer, Editor, Release Manager, Runtime Operator ve Document-set Manager allow/deny matrisi.
- Aynı tenant içinde yetkisiz başka senaryo/release/doküman seti.
- Cross-tenant UUID/ID denemeleri.
- Editor direct POST ile promote/rollback/runtime yapamaz.
- Release Manager document content veya Studio edit yetkisi kazanmaz.
- GET state değiştirmez; POST-only ve CSRF korunur.

### Güvenlik ve gizlilik

- Özetlerde secret/token/header/endpoint/raw manifest/prompt/answer/document text bulunmaz.
- Artifact checksum mismatch normal “hazır” durumuna indirgenmez.
- Broader runtime suspension gizlenmez veya exact resume ile aşılmaz.
- Evaluation/index gate UI tarafından atlanamaz.
- Mevcut audit olaylarının successful ve denied yolları korunur.

### UI/UX ve erişilebilirlik

- 1280x720 ve en az bir mobil viewport.
- Klavyeyle tüm bölümlere ve primary action'a erişim; görünür focus.
- Disclosure/section navigation doğru `aria-expanded`, `aria-current`, heading ve landmark semantiği.
- Eğer gerçek tab uygulanırsa tablist/tab/tabpanel klavye sözleşmesi; uygulanmıyorsa sahte tab rolleri
  bulunmaması.
- Hash/deep-link doğru bölümü açar ve odağı kaybettirmez.
- Uzun Türkçe adlar, boş durumlar, hata/banner ve pasif organizasyon.
- Önce/sonra sayfa yüksekliği, primary action sayısı ve temel görev tıklama sayısı kaydı.
- Yetkili/yetkisiz rollerle gerçek browser affordance kontrolü ve doğrudan-route negatif kanıtı.

### Repository kontrolleri

Uygulanabilir olanların tamamını çalıştır ve exact komut/sonucu `verification.md` içine yaz:

- formatter ve linter,
- mypy/type-check,
- migration drift,
- odaklı ve tam Python testleri,
- frontend type-check, Vitest ve build (Studio değişirse zorunlu),
- secret/static/security kontrolleri,
- canlı Compose/health ve ingestion preflight,
- mandatory post-development browser gate.

Çalışmayan veya çalıştırılmayan hiçbir kontrolü geçmiş sayma; nedenini ve kalan riski açıkça yaz.

## Kabul senaryosu

İlk defa Document Answer oluşturan yetkili bir kullanıcı:

1. akışı hazırlar,
2. gerekli bilgi kaynağının eksik olduğunu açıkça görür,
3. kaynağı bağlayıp hazırlar,
4. tek bağlamsal eylemle değişikliği test eder,
5. yetkisi varsa yayına alır; yoksa release manager beklendiğini görür,
6. yayın sonrasında kurulum checklist'i yerine canlı release ve güncel değişiklik durumunu görür,
7. eski sürüme dönmek istediğinde Sürümler → exact release ayrıntısı → mevcut güvenli rollback yolunu
   kolayca bulur,
8. artifact pinleri veya DSL rehberiyle karşılaşmadan normal işini tamamlar.

Bu akış mevcut compiler, eval, index, authorization ve audit kapılarının hiçbirini atlamamalıdır.

## Teslimatlar

- Uygulanmış senaryo detay bilgi mimarisi ve gerekli Studio/release yerleşim değişiklikleri.
- Typed/test edilmiş current-state ve primary-action üretimi.
- Güncellenmiş unit/integration/authorization/browser testleri.
- Güncellenmiş `docs/user-guide.md` ve `docs/manual-testing-guide.md`.
- Güncel `plan.md`, `threat-model.md` ve ayrıntılı `verification.md`.
- Gerekirse kalıcı ürün kararı için ADR; yalnız gerçekten durable mimari karar oluşursa.
- Final diff için staff engineer, application-security engineer ve SRE inceleme raporu.

## Tamamlanma ölçütü

Görev yalnız ekran daha kısa göründüğünde tamamlanmış sayılmaz. Şunların hepsi kanıtlanmalıdır:

- kullanıcı mevcut canlı durumu yanlış yorumlamıyor,
- bir sonraki doğru eylem açık ve tekil,
- ilk kurulum ile günlük release döngüsü ayrılmış,
- legacy ve edge case durumları dürüst,
- teknik ayrıntılar authoritative yüzeylerde erişilebilir,
- authorization/audit/tenant/release güvenlik sınırları değişmemiş,
- gerçek tarayıcıda masaüstü, mobil, klavye ve rol bazlı kullanım doğrulanmış,
- repository Definition of Done eksiksiz karşılanmış.
