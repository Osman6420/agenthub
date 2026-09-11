> Superseded: [tek aktif geliştirme görevi](../Agent_Hub_MD/plan.md). Bu belge tarihsel kaynaktır; bağımsız uygulanmaz.

# Konsol arayüzünü sadeleştirme

Durum: **Planned — kapsamlı arayüz uygulaması başlamadı.**

2026-09-09 kullanıcı isteği, konuşulan arayüz hedeflerini kodlama ajanına verilecek bir
Markdown dosyasında toplamaktır. Bu belge teslimi uygulama başlatma veya canlı geçiş değildir.
Ana teslim [uygulama talimatıdır](implementation-instructions.md).

## Kapsam ve mevcut işlerle ilişki

Ortak görsel dil ve gezinme; doküman çalışma alanı/hazırlama pilotu; mevcut senaryo alt işi;
diğer konsol ekranları ve geçişleri. Gezinme işinin uygulanmış sonuçları korunur. Senaryo
ayrıntıları mevcut alt planda kalır. Ayrı RAG, vektör ve yetki planları bu işle başlatılmaz.

| Kilometre taşı | Implemented | Verified |
| --- | --- | --- |
| Ortak tasarım ve tüm sayfa/durum envanteri | Hayır | Hayır |
| Doküman çalışma alanı ve hazırlama | Hayır | Hayır |
| Senaryo sadeleştirme alt işinin entegrasyonu | Hayır | Hayır |
| Diğer sayfa aileleri ve geçişleri | Hayır | Hayır |
| Güncel tüm testler ve tarayıcı kabulü | Hayır | Hayır |

Önceki gezinme iyileştirmelerinin durumu [kendi kaydında](../console-navigation-2026-09-08/plan.md)
tutulur; bu tablodaki Hayır bunların geri alındığı anlamına gelmez.

## Risk, test ve kapanış

[Tehdit modeli](threat-model.md) ve [doğrulama kaydı](verification.md) geçerlidir.
Uygulama sırasında acceptance ölçütlerini ana talimata göre kanıta eşleştir; canlı durumu
yeniden doğrula; mevcut yerel değişiklikleri koru. Kod, dependency, API, yetki veya schema
değişikliği bu belge tesliminde yapılmaz. Çalışan tasarım doğrulandığında kullanıcı belgelerini
ve master planı güncelle; gerekli kabul tamamlanınca arşivle.
