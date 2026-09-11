# Arayüz sadeleştirme risk sınırları

Belge teslimi kod veya runtime değiştirmez. Uygulamadaki başlıca riskler:

- Menü/sekme sadeleşirken yetkisiz nesne, sayaç veya içerik ifşası.
- Profil seçimi, test veya aktivasyonun tek eylem altında yetki/önkoşul atlaması.
- Aktif indeks ile hazırlanan indeksin, taslak ile yayımlanmış sürümün karıştırılması.
- Geçersiz geri dönüş URL'si, kaybolan proje/set kapsamı veya form hatasının gizli panelde kalması.
- Yeni görünümde önemli operasyonel engelin, audit'in veya hata/kurtarma yolunun kaybolması.
- Çakışan aktif işlerde eski backend/rol varsayımlarının yeniden uygulanması.

Önlemler: mevcut sunucu izinleri ve domain servisleri; adlandırılmış iç rotalar; doğrulanmış
filtreler; kapsamlı negatif testler; gerçek durumdan üretilen etiketler; ayrı aktivasyon kararı;
gizli panellere yetkisiz veri göndermeme; canlı kod ve plan uzlaştırması. Proje ve senaryo
yetkileri, doküman içerik okuma ve araç onay sınırları korunur. Testler izole sentetik veriyle
yapılır; gerçek kullanıcı verisinde izin/yayın/sıfırlama yapılmaz.

Üretim dependency/API/authorization/network değişikliği veya destructive işlem ihtiyacı
çıkarsa repository onay sınırını somut etki ve geri dönüş planıyla değerlendir.
