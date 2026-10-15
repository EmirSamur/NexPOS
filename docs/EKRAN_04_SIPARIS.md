# 4. Ekran: Garson Ekranı ve Sipariş (tarif, onay bekliyor)

Kafenin her gün en çok kullanılan ekranı. İlk üç ekranda hazırlanan her şey burada buluşur: PIN ile
giren garson (1), menü ve seçenekler (2), masa planı (3).

## 0. Bugün NexPOS'ta ne var, ne değişiyor?

| Bugün | Bu ekrandan sonra |
|---|---|
| Küçük bir pencerede açılır kutudan ürün seçilir | **Tam ekran sipariş ekranı:** kategori → büyük ürün kartları → adisyon |
| Seçenek yok | Ürüne dokununca **seçenek penceresi** açılır (boy, süt, ekstra); fiyat farkı eklenir |
| Ürün eklenince hemen "mutfakta" sayılır | Ürünler önce adisyonda **bekler**, garson **"Gönder"** deyince tek seferde gider; bar ve mutfak fişleri ayrılır |
| Fiyatlar ondalıklı sayı (`REAL`) | **Kuruş cinsinden tam sayı**; satıra ürünün o anki adı, fiyatı ve seçenekleri kopyalanır |
| İskonto yeni ürün eklenince **tekrar uygulanıyor** (hata) | İskonto bir kez, ara toplama uygulanır; yüzde ya da tutar; yetkili onaylı |
| İptal yalnızca siparişin tamamı için | **Satır bazında iptal ve ikram**, gerekçeli ve yetkili onaylı |
| Ödeme yöntemi seçiliyor ama **kaydedilmiyor** (hata) | Ödeme, yöntemiyle (nakit/kart/yemek kartı) kaydedilir; nakitte para üstü hesaplanır |
| Masayı zorla boşaltma veritabanına doğrudan yazıyor | Gerekçeli ve yetkili onaylı bir işlem olur, kayda geçer |
| Sipariş ve masa durumu yalnızca bu bilgisayarda | **Buluta gider** (internetsiz de çalışır); masa durumu planda ve ileride mobil uygulamada görünür |
| Paket servis yok | **Masasız sipariş** (gel-al / paket), numarayla takip |

## 1. Veri: sipariş nasıl yaşar?

- **Önce yerel, sonra bulut (1. ekrandaki tasarım).** Her işlem (ürün ekle, gönder, iptal, iskonto, ödeme)
  önce bu bilgisayarda uygulanır, sonra kuyruğa (outbox) yazılır. İnternet yokken de sipariş alınır,
  hesap kapatılır. İnternet gelince işlemler sırayla gider.
- **Bulutta tek doğru kayıt `orders/{id}`.** Sunucu kuyruktan gelen işlemleri sırayla uygular ve
  toplamları kendisi yeniden hesaplar. Terminalin hesabıyla fark çıkarsa (ör. fiyat o arada değiştiyse)
  terminalin fiyatı geçerli kalır, `auditLogs`'a `price_mismatch` yazılır.
- **Masa durumu bulutta da tutulur** (`tables/{id}.status`: boş / dolu / hesap istendi / rezerve,
  açık adisyonun kimliği, açılış saati, garson). Plan görünümü artık buradan okur.
- **Adisyon numarası:** Terminal harfi + günlük sıra numarası (`A47`). Gün, ayarlanabilir bir
  **gün dönümü saatinde** başlar (varsayılan 05:00). Gece 01:00'de kapanan hesap bir önceki günün
  cirosuna yazılır.
- **Fişler:** "Gönder" denince bekleyen satırlar istasyona göre (bar / mutfak) `kitchenTickets`
  dokümanlarına bölünür. Mevcut **Sipariş Panosu** bu fişleri gösterir. Ayrı mutfak/bar ekranı 5. ekranda
  gelecek.
- **Eski veri:** Kapanmış eski siparişler raporlar için olduğu gibi kalır. Açık eski siparişler ilk
  açılışta bir kez yeni yapıya taşınır. Raporlar 7. ekranda yeni yapıya geçene kadar eski tablolar da
  beslenmeye devam eder; dashboard ve istatistikler bozulmaz.

## 2. Sipariş ekranı

Garson planda ya da listede masaya dokunur. Boş masada yeni adisyon, dolu masada mevcut adisyon açılır.

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ ← Masalar   MASA 5 · Salon · 4 kişi · A47 · Cem · 38 dk                  🟢 Çevrimiçi       │
├────────────┬──────────────────────────────────────────┬───────────────────────────────────┤
│ 🔍 Ara      │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐│ ADİSYON                           │
│            │  │ Latte  │ │Americano│ │Cappucc.│ │Mocha ││  2× Latte             190,00 ₺   │
│ Sıcak Kah. │  │ 95 ₺   │ │ 80 ₺   │ │ 85 ₺   │ │TÜKENDİ││     Orta, Yulaf sütü   +50,00   │
│ Soğuk Kah. │  └────────┘ └────────┘ └────────┘ └──────┘│     ✓ gönderildi 14:02            │
│ Çaylar     │  ┌────────┐ ┌────────┐ ┌────────┐         │  1× San Sebastian     130,00 ₺   │
│ Tatlılar   │  │Flat Wh.│ │Türk K. │ │Cortado │         │     ⏳ bekliyor  "az tatlı"        │
│ Kahvaltı   │  │ 100 ₺  │ │ 60 ₺   │ │ 90 ₺   │         │  1× Su              İKRAM  0,00   │
│ …          │  └────────┘ └────────┘ └────────┘         │ ───────────────────────────────── │
│            │                                          │ Ara toplam              370,00 ₺   │
│ ★ Sık      │                                          │ İskonto %10             −37,00 ₺   │
│   satanlar │                                          │ TOPLAM                  333,00 ₺   │
│            │                                          │ [📨 Gönder (1)] [% İskonto] [🧾 Hesap]│
│            │                                          │ [⇄ Taşı] [⧉ Birleştir]  [💳 Öde]   │
└────────────┴──────────────────────────────────────────┴───────────────────────────────────┘
```

- **Ürün kartları** büyük ve dokunmatik ekrana uygun. Tükenen ürün gri görünür, eklenemez.
  "Sık satanlar" sekmesi o günün en çok satılanlarını öne çıkarır.
- **Seçenek penceresi:** Seçenek grubu olan ürüne dokununca açılır. Zorunlu grup seçilmeden eklenmez,
  tükenen seçenek seçilemez. Fiyat farkı anında görünür. Seçeneksiz ürün tek dokunuşla eklenir; aynı
  ürün tekrar eklenince adedi artar.
- **Adisyon satırı:** Satıra dokunulunca adet (+/−), **not** ("az şekerli", "alerji var"), **ikram** ve
  **iptal** seçenekleri çıkar.
  - **Henüz gönderilmemiş satır** serbestçe silinir; mutfağa hiç gitmemiştir.
  - **Gönderilmiş satırın iptali** `voidItem` yetkisi ve gerekçe ister. Yetki yoksa 1. ekrandaki yetkili
    onayı penceresi açılır. Satır silinmez, üstü çizili kalır ve kayda geçer.
  - **İkram** `comp` yetkisi ister. Satır 0 ₺ olur ve ikram olarak raporlanır.
- **Gönder:** Bekleyen satırları bar ve mutfağa ayrı fişler olarak yollar. Düğmenin üstünde bekleyen
  satır sayısı yazar. Gönderilmemiş ürünle masadan çıkılırsa uyarı verilir.
- **İskonto:** Yüzde ya da tutar olarak, adisyonun tamamına bir kez uygulanır. Yeni ürün eklenince yeniden
  hesaplanır ama **üst üste binmez**. `discount` yetkisi yoksa yetkili onayı istenir.
- **Hesap iste:** Masayı turuncu "hesap istendi" durumuna geçirir. İstenirse adisyon yazdırılır
  (yazıcı ayarlıysa).
- **Taşı / Birleştir:** Adisyon boş bir masaya taşınır ya da başka bir masanın adisyonuyla birleştirilir
  (ör. 4 ve 5 numaralı masalar tek hesap). İkisi de kayda geçer.

## 3. Ödeme (temel)

```
┌──────────────── Ödeme · Masa 5 · A47 ────────────────┐
│ Toplam                               333,00 ₺        │
│ Yöntem:  [ Nakit ] [ Kredi Kartı ] [ Yemek Kartı ]   │
│ Alınan:  [ 400,00 ]   Hızlı: [333] [350] [400] [500] │
│ Para üstü:                            67,00 ₺        │
│ Bahşiş (kart):  [ 0,00 ]                              │
│                         [Vazgeç]  [✓ Tahsil Et]      │
└──────────────────────────────────────────────────────┘
```

- Ödeme tutarı ve yöntemiyle `payments` kaydına yazılır. Tamamı ödenince adisyon kapanır, masa boşalır.
  Bu işlem internetsiz de çalışır.
- **Bu ekranda tek seferde tek yöntemle ödeme alınır.** Bölünmüş hesap (kişi başı ya da ürün bazında),
  karma ödeme, kasa açılış-kapanışı, Z raporu ve iade **6. ekranda (Kasa)** gelecek. Veri yapısı şimdiden
  bunlara uygun kuruluyor.
- **Sadakat damgası:** Müşteri QR'ı okutma ve damga basma 10. ekranda gelecek. Ödeme kaydı şimdiden
  hangi ürünlerin damga kazandırdığını tutuyor; böylece o ekran geldiğinde ek iş çıkmayacak.

## 4. Masasız sipariş (gel-al / paket)

Plan ekranının üstünde **"+ Masasız sipariş"** düğmesi olur. Masa yerine numarayla (`A48`) açılır,
akışı aynıdır. Açık masasız siparişler planın yanında küçük kartlar olarak görünür. Ödeme alınınca kapanır.

## 5. "Bitti" sayılma ölçütü

- [ ] Masaya dokununca sipariş ekranı açılıyor; seçenekli ürün seçenek penceresiyle, seçeneksiz ürün tek
      dokunuşla ekleniyor; zorunlu seçenek ve tükenen ürün/seçenek kuralları çalışıyor
- [ ] Fiyatlar ve toplamlar kuruş olarak tutuluyor; satır fiyatı sonradan menüde değişse de adisyon değişmiyor
- [ ] "Gönder" bekleyen satırları bar ve mutfak fişlerine bölüyor; pano fişleri gösteriyor
- [ ] Gönderilmiş satır iptali ve ikram yetki/gerekçe istiyor, kayda geçiyor; iptal edilen satır toplamdan düşüyor
- [ ] İskonto bir kez uygulanıyor; ürün eklendikçe üst üste binmiyor (eski hata için test)
- [ ] Ödeme yöntemiyle kaydediliyor, para üstü doğru; adisyon kapanıyor, masa boşalıyor
- [ ] Taşıma, birleştirme, hesap isteme ve masasız sipariş çalışıyor
- [ ] İnternet yokken baştan sona (aç → ekle → gönder → öde) çalışıyor; internet gelince bulutta sipariş,
      masa durumu, fişler ve ödeme doğru oluşuyor; aynı işlem iki kez gönderilse de bir kez işleniyor
- [ ] Sunucu toplamları yeniden hesaplıyor; fark varsa `price_mismatch` kaydı düşüyor
- [ ] Açık eski siparişler yeni yapıya bir kez taşınıyor; dashboard ve raporlar bozulmuyor
- [ ] Emülatör testleri: her işlem türü, sıra, idempotentlik, yetki, toplamlar, masa durumu
