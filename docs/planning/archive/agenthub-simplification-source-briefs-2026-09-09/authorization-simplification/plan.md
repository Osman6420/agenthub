# Yetkilendirme sadeleştirme

## Durum

**Planned — uygulama başlamadı.** 2026-09-09 tarihinde kullanıcı, önceki
değerlendirmeyi uygulayacak kodlama ajanı için Markdown talimatı istedi.
Bu bir belge teslimidir; uygulama değişikliği veya canlı geçiş yapılmamıştır.

## Amaç ve kapsam

[Uygulama talimatı](implementation-prompt.md) bu işin ayrıntılı hedefidir.
Organizasyon/proje/senaryo sınırları korunarak üç temel proje/senaryo rolü,
açık devralma, basit istemci erişim paketleri ve sunucudan üretilen ortak UI
eylem kararları uygulanacaktır. Doküman içeriği, araç onayı ve tenant izolasyonu
ayrı korunacaktır. Eski atamalar sessizce daha geniş rollere dönüştürülmeyecektir.

## Kaynaklar

- [Değerlendirme](../../authorization-simplification-assessment-2026-09-09/assessment.md)
- [Mevcut ADR-0015](../../../../adr/0015-responsibility-based-operator-authorization.md)
- [Riskler](threat-model.md)
- [Belge doğrulaması ve sonraki uygulama kanıtları](verification.md)

## Kabul ölçütleri ve kilometre taşları

| Kilometre taşı | Implemented | Verified |
| --- | --- | --- |
| Rol/işlem matrisi ve devralma servisi | Hayır | Hayır |
| Eski erişimleri koruyan geçiş ve fark önizlemesi | Hayır | Hayır |
| Proje/senaryo erişim ekranları ve ortak eylem çıktısı | Hayır | Hayır |
| API istemcisi paketleri ve doküman erişim modları | Hayır | Hayır |
| MCP ingestion durum kapsamının sınırlandırılması | Hayır | Hayır |
| Negatif testler, PostgreSQL ve tarayıcı doğrulaması | Hayır | Hayır |

Her ölçütün ayrıntısı uygulama talimatının test ve tamamlanma bölümlerindedir.

## Etkiler ve sınırlar

Gelecekteki uygulama yetkilendirme ve eklemeli şema değişikliği içerebilir.
Yeni üretim bağımlılığı, kimlik doğrulama değişikliği, dış API kaldırma, veri
silme/reset, canlı üretim erişimi veya deploy bu belge tesliminin kapsamında değildir.
Uygulama sırasında mevcut çalışma ağacı yeniden incelenecek; ilgisiz değişiklikler
korunacak. Yeni politika canlı trafiğe geçirilmeden eski/yeni yetki farkları
ve geri dönüş yöntemi doğrulanacak.
