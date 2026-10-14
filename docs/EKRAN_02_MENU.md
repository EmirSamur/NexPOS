# 2. Ekran: Menü Yönetimi (tarif, onay bekliyor)

Menü; kasanın, garson ekranının, mutfak/bar ekranının, müşteri uygulamasının ve kahve önerisinin
ortak kaynağı. Bu yüzden 1. ekrandan sonraki ilk iş bu.

## 0. Bugün NexPOS'ta ne var, ne değişiyor?

| Bugün | Bu ekrandan sonra |
|---|---|
| Kategori: ad + renk | + sıra, istasyon (bar/mutfak), uygulamada görünür mü, damga kazandırır mı |
| Ürün: ad, fiyat (`REAL`), kategori, birim | + açıklama, fotoğraf, KDV, alerjen, kalori, kafein, etiketler, tat profili, seçenek grupları |
| Fiyat ondalıklı sayı | **Kuruş cinsinden tam sayı** (`9500` = 95,00 ₺) |
| Seçenek yok | **Seçenek grupları:** boy, süt, şurup, ekstra shot (fiyat farkıyla) |
| Ürün silinince `aktif=0` | Aynı mantık bulutta: `deleted: true`, geçmiş adisyonlar bozulmaz |
| "Tükendi" yok | Barista/mutfak tek dokunuşla **"Tükendi"** işaretler (internetsiz de çalışır) |
| Zam = tek tek fiyat düzenleme | **Toplu fiyat güncelleme** (%X zam, yuvarlama, önizleme) |
| Menü yerel SQLite'ta | Menü bulutta; terminal önbelleğe alır |

## 1. Veri: kim yazar, nereden okunur?

- **Menü bulutta yaşar** (`categories`, `products`, `optionGroups`). Terminal 1. ekrandaki gibi
  delta senkronla önbelleğe alır. Garson ekranı ve kasa her zaman önbellekten okur, yani internetsiz de
  sipariş alınır.
- **Menü düzenleme internet ister** ve Cloud Functions üzerinden yapılır (`saveCategory`, `saveProduct`,
  `saveOptionGroup`, `reorderMenu`, `bulkUpdatePrices`). Fiyatı yalnızca yetkili kişi değiştirebilir
  (`editMenu`). Her fiyat değişikliği `auditLogs`'a eski ve yeni fiyatla yazılır.
- **Tek istisna "Tükendi":** Servis sırasında süt biterse internet olmasa da işaretlenebilmeli.
  Bu yüzden `setSoldOut` işlemi kuyruktan (outbox) gider. Yeni bir yetki eklenir:
  **`markSoldOut` (Tükendi işaretleyebilir)**. Varsayılan olarak Barista, Mutfak, Kasa, Müdür ve
  Yönetici'de açıktır.
- **Eski siparişler bozulmaz:** Bulut menüsü yerel `categories`/`products` tablolarına da yansıtılır
  (1. ekrandaki `staff` → `users` köprüsü gibi). Böylece mevcut garson ekranı 4. ekranda yeniden
  yazılana kadar çalışmaya devam eder.

## 2. Ekran düzeni (Yönetim paneli → Tanımlamalar → Menü / Ürünler)

```
┌─────────────┬──────────────────────────────────────────────────────────────────┐
│ KATEGORİLER │  🔍 Ürün ara…        [Tümü ▾] [Tükenenler] [Gizliler]  [+ Ürün]   │
│             │                                                                  │
│ ☰ Sıcak K. 8│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                             │
│ ☰ Soğuk K. 5│  │ 📷   │ │ 📷   │ │ 📷   │ │ 📷   │   Kart: fotoğraf, ad,       │
│ ☰ Çaylar   4│  │Latte │ │Mocha │ │Ameri.│ │Flat W│   fiyat, rozetler           │
│ ☰ Tatlılar 6│  │95,00₺│ │105 ₺ │ │80 ₺  │ │TÜKENDİ│  (Tükendi / Gizli / Yeni) │
│   …         │  └──────┘ └──────┘ └──────┘ └──────┘                             │
│ [+ Kategori]│                                                                  │
│             │  [⇅ Sırala]  [₺ Toplu Fiyat]  [⚙ Seçenek Grupları]               │
└─────────────┴──────────────────────────────────────────────────────────────────┘
```

- **Kategori listesi:** Sürükle-bırak ile sıralanır. Yanında ürün sayısı yazar. Sağ tık menüsünde
  Düzenle / Gizle / Sil seçenekleri bulunur. İçinde ürün olan kategori silinemez; önce ürünler
  taşınmalı ya da silinmelidir.
- **Ürün kartları:** Mevcut `ProductCard` korunur, üstüne fotoğraf ve rozet eklenir. Karta tıklayınca
  ürün düzenleme penceresi açılır. Kartın köşesindeki **⛔ Tükendi** düğmesi tek dokunuşla
  açılıp kapanır.
- **Filtreler:** Tümü / Tükenenler / Uygulamada gizli olanlar. Arama ürün adında ve etiketlerde yapılır.

## 3. Ürün düzenleme penceresi (sekmeli)

**Genel**
```
Ad*            [Latte                         ]
Kategori*      [Sıcak Kahveler ▾]
Fiyat*         [95,00] ₺    KDV [%10 ▾]   (fiyatlar KDV dahil girilir)
Açıklama       [Espresso ve buharla ısıtılmış süt…              ]
Fotoğraf       [📷 Seç…]  (otomatik 800 px'e küçültülür)
Etiketler      [yeni] [mevsimlik] [+]
☑ Satışta   ☑ Müşteri uygulamasında göster   ☑ Damga kazandırır (kategoriden gelir)
```

**Seçenekler**
- Ürüne bağlanacak seçenek grupları işaretlenir: ☑ Boy ☑ Süt seçimi ☐ Şurup ☑ Ekstra shot.
- Grupların kendisi ortak bir **Seçenek Grupları** penceresinden yönetilir. "Yulaf sütü +15 ₺" bir kez
  tanımlanır, 20 üründe birden kullanılır.

**Müşteri bilgisi** (müşteri uygulamasında görünür)
- Alerjenler: ☐ Süt ☐ Gluten ☐ Kuruyemiş ☐ Soya ☐ Yumurta
- Kalori (kcal), kafein (mg)

**Tat profili** (kahve önerisi için; yalnızca içecek kategorilerinde görünür)
```
Sertlik    ●●●○○     Tatlılık  ●●○○○
Asidite    ●○○○○     Gövde     ●●●●○
Sütlü mü   ☑         Sıcaklık  (•) Sıcak  ( ) Soğuk
Notalar    [çikolata] [fındık] [+]
```

## 4. Seçenek Grupları penceresi

```
┌ Süt Seçimi ─────────────────────────────────────────┐
│ Seçim: (•) Tek  ( ) Çoklu    ☑ Zorunlu   En az 1  En çok 1 │
│  Normal süt          +0,00 ₺   ☑ satışta   [⇅] [🗑]  │
│  Yulaf sütü         +15,00 ₺   ☑ satışta   [⇅] [🗑]  │
│  Laktozsuz          +10,00 ₺   ☐ satışta   [⇅] [🗑]  │
│  [+ Seçenek ekle]                                    │
└──────────────────────────────────────────────────────┘
```
Tek bir seçenek de "tükendi" yapılabilir (yulaf sütü bitti gibi). Malzeme reçetesi (`recipeDelta`)
stok ekranında (8. ekran) eklenecek.

## 5. Toplu fiyat güncelleme

```
Kapsam:      [☑ Sıcak Kahveler] [☑ Soğuk Kahveler] [☐ Tatlılar] …
Değişim:     (•) %  [ 12 ]     ( ) Sabit tutar [ +5,00 ₺ ]
Yuvarlama:   [En yakın 5 ₺'ye yukarı ▾]   (yok / 1 ₺ / 5 ₺ / 10 ₺)
Seçenekler:  ☐ Seçenek fiyat farklarını da güncelle

Önizleme                      Eski      Yeni     Fark
Latte                        95,00 ₺  110,00 ₺  +15,00
Americano                    80,00 ₺   90,00 ₺  +10,00
…                                       [Vazgeç] [18 ürünü güncelle]
```
Tek bir işlemde (transaction) uygulanır ve tek bir audit kaydına yazılır: kim, ne zaman, hangi
kural, hangi ürünler. Böylece zam geri alınması gerekirse kayıttan bulunur.

## 6. İlk geçiş: mevcut menünün buluta aktarılması

Bulutta menü boşken panel bir kez **"Bu bilgisayardaki menüyü buluta aktar (30 ürün, 10 kategori)"**
seçeneği sunar. Fiyatlar kuruşa çevrilir (85 → `8500`), kategori renkleri korunur. İçecek kategorileri
varsayılan olarak "bar" istasyonuna ve "damga kazandırır" ayarına düşer, yemekler "mutfak" istasyonuna.
Aktarım sonrası her şey yukarıdaki ekrandan düzenlenir.

## 7. Garson ekranına etkisi (bu ekranda yapılacak kadarı)

- Ürün listesi bulut önbelleğinden gelir. **Tükenen ürün** gri görünür ve sepete eklenemez.
- Fiyat gösterimi kuruştan biçimlenir. Garson ekranındaki fiyatı metinden ayıklayan kırılgan kod
  (`user_panel.py:812`) kaldırılır.
- Seçenek seçme penceresi (boy/süt seçimi) ve siparişe seçeneklerin yazılması **4. ekranda** (sipariş)
  yapılır. Bu ekranda yalnızca veri hazırlanır.

## 8. Bu ekranın "bitti" sayılma ölçütü

- [ ] Kategori ve ürün eklenip düzenlenebiliyor, sıralanabiliyor; değişiklik terminale ve 5 sn içinde
      diğer ekranlara iniyor
- [ ] Fiyatlar kuruş olarak tutuluyor; ekranda `95,00 ₺` biçiminde görünüyor
- [ ] Seçenek grupları tanımlanıp ürünlere bağlanabiliyor
- [ ] İnternet yokken menü düzenleme düğmeleri kapalı, "Tükendi" düğmesi çalışıyor; internet gelince
      tükendi bilgisi buluta gidiyor
- [ ] Toplu fiyat güncelleme önizleme gösteriyor, tek transaction'da uygulanıyor, audit kaydı oluşuyor
- [ ] Yetkisi olmayan (`editMenu` yok) kişi menüyü değiştiremiyor; hem ekranda hem fonksiyonda reddediliyor
- [ ] Mevcut yerel menü buluta bir kez aktarılabiliyor
- [ ] Silinen ürün eski adisyonlarda adıyla ve fiyatıyla görünmeye devam ediyor
- [ ] Emülatör testleri: kurallar, fonksiyonlar, delta senkron, tükendi kuyruğu
