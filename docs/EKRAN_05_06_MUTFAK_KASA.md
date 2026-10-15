# 5. ve 6. Ekran: Mutfak/Bar Ekranı ve Kasa

> Durum: **uygulandı** (modül altyapısı, 6. ekran Kasa, 5. ekran Mutfak/Bar Ekranı).
>
> Uygulamada netleşenler:
> - Kasa işlemleri ve iade yetkisi hem ekranda hem kasa servisinde (cash.py, pos.py) hem sunucuda denetlenir;
>   kuyruğa giren işlem sonradan reddedilmez.
> - Ödenmiş (ürün seçerek bölmede) satır iptal edilemez; iade yapılır. Ürün seçerek ödeme alındıktan sonra
>   iskonto değiştirilemez.
> - Z raporu kapsamı: oturum açıkken alınan ödemeler/iadeler; adisyon sayısı, iskonto, ikram, KDV ve personel
>   dökümü son ödemesi bu oturumda alınan (kapanan) adisyonlardan hesaplanır.
> - Fark gerekçe eşiği modül ayarıdır (varsayılan 20 ₺).
> - PDF fişler veritabanının yanındaki `fisler/` klasörüne kaydedilir.
> - Mutfak ekranı Firebase web SDK'sını CDN'den değil, kendi Hosting adresinden yükler (`hosting/mutfak/vendor`).
> - Tablet hesabı yalnızca fişleri ve modül/genel ayarları okur; kasa terminali fonksiyonlarını çağıramaz.
> - Kod tahminine karşı: 10 dakikada 30 hatalı denemeden sonra eşleme geçici olarak kapanır.
> - Adisyon iptal edilince fişi "İPTAL EDİLDİ" görünür ve tabletten "Kaldır" ile kaldırılır (kasada bildirim çıkmaz).
> - Masa adı yalnızca rakamsa "Masa" eklenir ("Masa 5"); "Bahçe 3" gibi adlar olduğu gibi gösterilir.

İki ekran da **modül** olarak gelir: Yönetici ayarlardan açar ya da kapatır. Kapalı modül hiçbir ekranda
görünmez ve iş akışını etkilemez. Böylece küçük bir kafe yalnızca kasayla, büyük bir kafe mutfak ekranı
ve zorunlu kasa açılışıyla çalışabilir.

## 0. Modüller (Ayarlar → Modüller)

```
┌ Modüller ─────────────────────────────────────────────────────────────────┐
│ ☑ Mutfak / Bar Ekranı (KDS)    Fişler tablet ekranına düşer.               │
│      Eşikler: [10] dk sarı, [20] dk kırmızı   ☑ Yeni fişte ses              │
│ ☐ Zorunlu kasa açılışı          Nakit almak için önce kasa açılmalı.       │
│ ☑ Bilgi fişi yazdırma           Yazıcı: [EPSON TM-T20 ▾] Kâğıt: [80 mm ▾]  │
│ Ödeme yöntemleri:  ☑ Nakit  ☑ Kredi Kartı  ☑ Yemek Kartı   ☑ Bahşiş        │
└───────────────────────────────────────────────────────────────────────────┘
```

- Ayarlar bulutta (`settings/modules`) tutulur. Kasa önbelleğe alır; değişiklik birkaç saniyede bütün
  cihazlara iner.
- Yalnızca Yönetici (owner) değiştirebilir. Her değişiklik kayda geçer.
- **Bir modül kapatıldığında veri silinmez.** Geçmiş kasa oturumları ve fişler raporlarda görünmeye
  devam eder.

---

## 5. Ekran: Mutfak / Bar Ekranı (KDS)

### 5.1 Nerede çalışır?

**Tarayıcıda çalışan bir web sayfası.** Mutfaktaki ya da bardaki herhangi bir tablet (Android, iPad) veya
eski bir bilgisayar yeterli; kurulum gerekmez. Sayfa Firebase Hosting'de, QR adresiyle aynı alan adında
yayınlanır (`https://<proje>.web.app/mutfak`).

- **Eşleme:** Panelde **Terminaller → "+ Mutfak ekranı ekle"** düğmesi 6 haneli, 10 dakika geçerli bir
  kod üretir. Tablette sayfa açılır, kod girilir, istasyon seçilir (Bar / Mutfak / İkisi). Tablet,
  kasa terminali gibi ayrı bir cihaz hesabı alır ve panelden iptal edilebilir.
- **Anlık:** Fişler buluttan canlı dinlenir; yeni fiş saniyeler içinde ekrana düşer.

### 5.2 Ekran

```
┌ 🍳 MUTFAK · 14:32 ────────────────────────────────── 🟢 Bağlı · Bekleyen: 3× Tost, 2× Menemen ┐
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                         │
│ │ MASA 5 · A47 │ │ MASA 2 · A45 │ │ PAKET · A48  │ │ MASA 11 · A44│                         │
│ │ 03:12   YENİ │ │ 08:40  HAZIR.│ │ 01:05   YENİ │ │ 21:30 ⚠ GECİK│ ← kırmızı kenar          │
│ │ ☐ 2× Tost    │ │ ☑ 1× Menemen │ │ ☐ 1× Sandviç │ │ ☐ 1× Köfte   │                         │
│ │   bol kaşarlı│ │ ☐ 1× Omlet   │ │              │ │              │                         │
│ │ ☐ 1× Kek     │ │              │ │              │ │              │                         │
│ │ [ Başla ]    │ │ [ Hazır ✓ ]  │ │ [ Başla ]    │ │ [ Başla ]    │                         │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘                         │
│                                        [↶ Son kapatılanı geri al]   [Hepsi | Yeni | Hazırlanan]│
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Fiş kartı:** Masa ya da paket, adisyon numarası, geçen süre, satırlar, seçenekler ve notlar
  büyük yazıyla gösterilir.
- **Gecikme renkleri:** Süre sarı eşiği geçince kart sarı, kırmızı eşiği geçince kırmızı olur
  (varsayılan 10 / 20 dk).
- **Satır işaretleme:** Satıra dokunulunca üstü çizilir; hazırlanan ürün işaretlenir.
- **Durum:** Başla → Hazır. Hazır olan fiş ekrandan kalkar; yanlışlıkla kalkan fiş "Geri al" ile döner.
- **Toplu bekleyen:** Üst satır, bekleyen ürünlerin toplamını gösterir ("3× Tost"). Aşçı aynı ürünleri
  tek seferde hazırlayabilir.
- **İptal edilen ürün** fişte üstü çizili ve kırmızı "İPTAL" etiketiyle görünür. Ürün boşuna hazırlanmaz.
- **Ses:** Yeni fiş gelince kısa bir ses çalar (ayarlardan kapatılabilir).

### 5.3 Kasaya etkisi

- Fiş **Hazır** olunca kasada ve garson ekranında bildirim çıkar ("Masa 5 · A47 hazır"). Plandaki masada
  küçük bir 🔔 işareti görünür. Garson teslim edince işaret kalkar.
- Kasadaki **Fiş Panosu** modül açıkken de çalışır (yedek). Modül kapalıyken tek fiş ekranı odur.
- **İnternet kesilirse:** Mutfak ekranı yeni fiş alamaz; bu, web sayfasının doğası. Kasa bunu fark
  eder ve uyarı gösterir: "Mutfak ekranına ulaşılamıyor, fişleri Fiş Panosu'ndan takip edin".
  Bilgi fişi yazıcısı açıksa fiş ayrıca kâğıda basılır. İnternet gelince bekleyen fişler ekrana düşer.

---

## 6. Ekran: Kasa

### 6.1 Hesap bölme

Ödeme penceresine iki seçenek eklenir:

- **Eşit böl:** Kişi sayısı seçilir (2–20). Her ödeme kalan tutarın payı kadar önerilir. Kuruş farkı
  son ödemeye eklenir; toplam her zaman tutar.
- **Ürün seçerek böl:** Ödenecek satırlar işaretlenir. Birden fazla adetli satır adetle bölünebilir
  (3 latteden 1'i). Ödenen satırlar adisyonda "ödendi" olarak işaretlenir, iki kez ödenemez.
- **Karma ödeme** zaten var: kalan tutarın bir kısmı nakit, kalanı kart.

### 6.2 Kasa oturumu (açılış / kapanış)

```
Kasa Aç                          Kasa Kapat (Z)
  Açılış nakdi: [ 500,00 ]         Beklenen nakit:      3.240,00 ₺  (açılış + nakit satış − çıkış)
  [Kasayı Aç]                      Sayılan nakit: [ 3.200,00 ]
                                   Fark:              −40,00 ₺ ⚠  Gerekçe: [ ...... ]
                                   [Z Raporunu Al ve Kasayı Kapat]
```

- **Açılış:** Gün başında açılış nakdi girilerek açılır.
  - "Zorunlu kasa açılışı" modülü açıksa kasa açılmadan nakit ödeme alınamaz.
  - Modül kapalıysa kasa yine açılabilir; sadece zorunlu olmaz.
- **Kasa hareketi:** Giriş (bozuk para eklendi) ya da çıkış (tedarikçiye ödeme, gider). Nakit gider
  bugünkü Gider sayfasına da yazılır.
- **Kapanış:**
  - Sayılan nakit girilir ve beklenen nakitle karşılaştırılır.
  - Fark belli bir tutarı aşarsa gerekçe zorunludur; fark kayda geçer.
  - Kapanışta açık adisyon varsa liste gösterilir ve onay istenir.
- **Yetki:** Açma, kapama ve kasa hareketi mevcut `cash` yetkisi ("Kasa İşlemleri Yapabilir") ister.
  Yetkisi olmayana yetkili onayı penceresi açılır.

### 6.3 Z raporu (gün sonu)

Kapanışta otomatik oluşur; istendiği an "X raporu" (ara rapor) da alınabilir.

```
VELVET KAFE · Z RAPORU · Kasa 1 (A) · 15.10.2026
Açılış 08:02 (Cem)  ·  Kapanış 23:41 (Deniz)
────────────────────────────────────────────
Satış (KDV dahil)             12.480,00 ₺
  Nakit                        3.120,00 ₺
  Kredi Kartı                  8.140,00 ₺
  Yemek Kartı                  1.220,00 ₺
İade                            −95,00 ₺
İskonto                        −340,00 ₺   (12 adisyon)
İkram                           (6 ürün · 410,00 ₺)
İptal                           (4 ürün · 360,00 ₺)
Bahşiş (kart)                    620,00 ₺
KDV %10 / %20                  1.124,36 / 18,50 ₺
Adisyon sayısı / ortalama        96 / 130,00 ₺
────────────────────────────────────────────
Kasa: açılış 500,00 + nakit 3.120,00 − çıkış 380,00 = beklenen 3.240,00
Sayılan 3.200,00  ·  Fark −40,00 (gerekçe: bozuk para eksik)
Personel: Cem 5.210,00 · Elif 4.880,00 · Selin 2.390,00
```

PDF olarak kaydedilir ve yazıcı varsa basılır. Geçmiş Z raporları **Raporlar → Kasa Oturumları**
sayfasından açılır.

### 6.4 İade

Kapanmış bir adisyon "Bugünün adisyonları" listesinden açılır. Tamamı ya da bir kısmı, seçilen yöntemle
iade edilir. İade `refund` yetkisi ve gerekçe ister; Z raporunda ayrı satırda görünür.

### 6.5 Bilgi fişi (yazdırma)

- **Adisyon (ön fiş):** Garson "Hesap İste" dediğinde ya da ödemede istenirse basılır. Üzerinde kafe adı,
  masa, adisyon no, satırlar, iskonto, toplam ve **"Bilgi fişidir, mali değeri yoktur"** yazar.
- **Mutfak/bar fişi:** Modül açıksa "Gönder" dendiğinde istasyonun yazıcısından basılır (KDS'nin
  kâğıt yedeği).
- Windows'a sürücüsü kurulu her yazıcı çalışır (80 mm / 58 mm termal ya da A4). Yazıcı yoksa PDF
  kaydedilir.
- ⚠️ **Mali fiş (ÖKC / yazar kasa / e-Arşiv) bu ekranın kapsamında değildir.** Türkiye'de satışın mali
  belgesi ÖKC'den ya da e-Arşiv'den kesilir. Bu entegrasyon cihaz markasına ve mali müşavire bağlı ayrı
  bir iştir (bkz. soru 3).

---

## Sıra

1. **Modül altyapısı + 6. ekran (Kasa):** İlave cihaz gerektirmez, her kafede hemen işe yarar.
2. **5. ekran (KDS):** Web sayfası, eşleme ve canlı dinleme.

## "Bitti" sayılma ölçütü

- [x] Modüller ayarlardan açılıp kapanıyor, değişiklik kasaya iniyor; kapalı modül hiçbir ekranda görünmüyor
- [x] Eşit bölme kuruş farkını son ödemede kapatıyor; ürün bazında bölmede aynı satır iki kez ödenemiyor
- [x] Kasa açılış, hareket ve kapanış çalışıyor; beklenen nakit doğru; fark gerekçesi zorunlu oluyor;
      zorunlu modülde kasa kapalıyken nakit alınamıyor
- [x] Z raporundaki bütün kalemler adisyonlarla tutuyor (otomatik test); PDF ve yazıcı çıktısı alınıyor
- [x] İade yetki ve gerekçe istiyor; Z raporuna düşüyor
- [x] Bilgi fişi ve mutfak fişi yazdırılabiliyor; yazıcı yoksa PDF kaydediliyor
- [x] KDS tablette eşleniyor, panelden iptal edilebiliyor; fişler canlı düşüyor; gecikme renkleri,
      satır işaretleme, Hazır, Geri al ve toplu bekleyen çalışıyor
- [x] Hazır olan fiş kasada bildirim olarak çıkıyor; internet kesilince kasa uyarı gösteriyor
- [x] İnternetsiz: kasa oturumu, ödeme, bölme ve iade çalışıyor; internet gelince buluta gidiyor
- [x] Emülatör testleri: modül ayarları, kasa işlemleri, Z hesaplaması, KDS eşleme ve yetkileri
