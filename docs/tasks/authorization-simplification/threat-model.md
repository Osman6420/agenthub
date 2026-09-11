> Superseded: [tek aktif geliştirme görevi](../Agent_Hub_MD/plan.md). Bu belge tarihsel kaynaktır; bağımsız uygulanmaz.

# Risk modeli

Belge hazırlama aşaması: yalnız yerel dokümantasyon değişir. Aşağıdakiler
gelecekteki uygulamanın tasarım ve doğrulama yükümlülükleridir.

- Varlıklar: tenant/proje/senaryo sınırları, doküman içeriği, servis kimlikleri,
  ücretli model kullanımı, araç yan etkileri, onaylar ve audit kayıtları.
- Aktörler: platform/organizasyon idarecisi, proje/senaryo rolleri, veri yöneticisi,
  insan onaylayan, REST/MCP tüketicisi ve worker. Bu kimlik sınıfları birleştirilmez.
- Devralma riski: eski proje yöneticisine bütün senaryolarda yayın yetkisi doğması.
  Eski davranış korunur; genişleme açık atama/değişiklik ve audit gerektirir.
- Veri riski: senaryo-ortak veri modunun bütün mevcut/gelecek izinli istemcilere
  aynı veriyi açması. Veri sahibinin bu kapsamı bilerek yetkilendirmesi gerekir.
- Tarayıcı riski: değiştirilen `allowed_actions`, rol veya workspace değeriyle
  sunucuyu kandırma. Her eylem güvenilir nesneler üzerinden yeniden denetlenir.
- Yetki yükseltme riski: senaryo yöneticisinin kendisini onaylayan veya doküman
  okuyucusu yapması. Bu yetkiler senaryo yöneticiliğinden türetilmez.
- Geçiş riski: eski worker/politika/cache ile yeni web sürümünün birlikte
  çalışması. Sürüm uyumu ve iptal edilmiş yetkinin etkisi test edilir.
- Operasyon riski: özel erişime geçerken son yöneticinin kaybedilmesi; audit
  yazılamadığı halde rol veya paylaşım modunun kaydedilmesi. Atomik servis,
  kilitler, son yönetici kuralları ve hata testleri gereklidir.

Zorunlu negatif testler ve kalan belirsizliklerin yönetimi
[uygulama talimatında](implementation-prompt.md) tanımlıdır.
