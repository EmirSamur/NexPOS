# 3. Ekran: Salon ve Masa Planı (onaylandı, uygulandı)

Siparişin, adisyonun, mutfak fişinin ve müşterinin QR'dan vereceği siparişin hepsi bir masaya
bağlanır. Bu yüzden masa düzeni sipariş ekranından (4. ekran) önce gelir.

> Onaylanan kararlar: QR adresi Firebase Hosting (`https://<proje>.web.app/masa`, ayarlardan
> değiştirilebilir); etiketteki kafe adı Ayarlar'dan girilir; dekor öğeleri var; rezervasyon şimdilik
> garsonun boş masayı elle işaretlemesi.
>
> Uygulama sırasında yapılan değişiklik: plan kaydında silinecek masalar **açıkça** gönderilir
> (`removedTableIds`). Listede adı geçmeyen masaya dokunulmaz; böylece kasanın önbelleği eksikken
> kaydedilen bir plan, görülmeyen masaları yanlışlıkla silemez.

## 0. Bugün NexPOS'ta ne var, ne değişiyor?

| Bugün | Bu ekrandan sonra |
|---|---|
| Bölge: yalnızca ad | + sıra, plan boyutu, dekor öğeleri (bar tezgâhı, kapı, duvar, bitki) |
| Masa: ad + bölge, kartlar ızgarada | + kapasite, şekil (yuvarlak/kare/dikdörtgen), plandaki konum ve boyut |
| Masa ekleme tek tek, konum yok | **Sürükle-bırak plan editörü:** ızgaraya oturtma, çoğaltma, otomatik numara |
| Masalarda QR yok | **Her masaya QR kod**, A4 çıktı ve "QR yenile" |
| Garson masaları kart listesinde görür | **Plan görünümü:** salonun kuşbakışı hâli, durum renkleri (liste görünümü de kalır) |
| Masa/bölge yerel SQLite'ta | Bulutta; kasa önbelleğe alır |

## 1. Veri: kim yazar, nereden okunur?

- **Plan bulutta yaşar** (`areas`, `tables`). Kasa 1. ve 2. ekrandaki gibi delta senkronla önbelleğe
  alır. Garson ekranı her zaman önbellekten okur.
- **Planı düzenlemek internet ister.** Yetki mevcut `editMenu` ("Ürün / Fiyat / **Masa** Tanımlayabilir")
  yetkisidir. Bir bölgenin planı tek seferde kaydedilir (`saveFloorPlan`): masalar, konumları ve dekor
  öğeleri bir arada gider. Aynı planı iki kişi aynı anda düzenlerse sonra kaydeden uyarı alır
  (`layoutVersion`); kimsenin değişikliği sessizce ezilmez.
- **Masanın anlık durumu bu ekranın konusu değil.** Dolu/boş, hesap istendi, açık adisyon tutarı gibi
  bilgiler siparişle birlikte 4. ekranda buluta taşınacak. O zamana kadar bu bilgiler bugünkü gibi yerel
  tablodan okunur. Plan görünümü iki kaynağı birleştirerek gösterir.
- **Silme yine fiziksel değil:** Masa silinince `deleted: true` olur, eski adisyonlarda adıyla görünmeye
  devam eder. Açık adisyonu olan masa ve bölge silinemez.
- **İlk geçiş:** Bulutta plan yokken NexPOS'taki bölgeler ve masalar (Salon, Teras, Bahçe · 24 masa) bir
  kez buluta aktarılır. Masalar ızgara düzeninde yerleştirilir, sonra editörden düzenlenir.

## 2. Plan editörü (Yönetim paneli → Tanımlamalar → Masa / Bölgeler)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ [Salon] [Teras] [Bahçe] [+ Bölge]                         ✎ Bölge  ⇅ Sırala      │
├──────────┬───────────────────────────────────────────────────────┬───────────────┤
│ ARAÇLAR  │  · · · · · · · · · · · · · · · · · · · · · · · · · ·  │ SEÇİLİ: Masa 4│
│          │  ·  ╭───╮   ╭───╮   ┌─────┐            ▓▓▓▓▓▓▓▓▓▓▓▓ ·  │ Ad    [Masa 4]│
│ ◯ Yuvarlak│  ·  │ 1 │   │ 2 │   │  3  │            ▓ BAR TEZGÂHI▓ ·  │ Kişi  [4  ▾]  │
│ ▢ Kare    │  ·  ╰───╯   ╰───╯   └─────┘            ▓▓▓▓▓▓▓▓▓▓▓▓ ·  │ Şekil (•)◯ ▢ ▭│
│ ▭ Dikdörtg│  ·                                                  ·  │ Döndür [↻ 90°]│
│ ─ Duvar   │  ·  ╭───╮  ┏━━━━━━━┓                               ·  │               │
│ ▓ Bar     │  ·  │ 5 │  ┃   6   ┃ ← seçili, köşelerden boyutlanır ·  │ [⧉ Çoğalt]    │
│ ⌂ Kapı    │  ·  ╰───╯  ┗━━━━━━━┛                     🪴         ·  │ [🗑 Sil]       │
│ 🪴 Bitki  │  · · · · · · · · · · · · · · · · · · · · · · · · · ·  │               │
├──────────┴───────────────────────────────────────────────────────┴───────────────┤
│ 8 masa · 30 kişilik       ☑ Izgaraya oturt        [Vazgeç]  [💾 Planı Kaydet]       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- **Ekleme:** Soldaki araçtan plana sürükle ya da tıkla. Yeni masaya sıradaki numara otomatik verilir
  (Masa 9). Yeni masanın varsayılan kapasitesi şekline göre belirlenir: yuvarlak 2, kare 4,
  dikdörtgen 6.
- **Düzenleme:** Sürükle-bırak taşıma, köşelerden boyutlandırma, 90° döndürme. Ok tuşlarıyla ince
  ayar yapılır, Ctrl+D çoğaltır, Delete siler. "Izgaraya oturt" açıkken her şey 20 birimlik ızgaraya
  hizalanır.
- **Sağ panel:** Seçili masanın adı, kişi sayısı ve şekli; dekor öğesinde yalnızca etiket.
- **Kaydetme:** Değişiklikler "Planı Kaydet" ile tek seferde gider. Kaydedilmemiş değişiklik varken
  sayfadan çıkılırsa uyarı verilir.
- **Ölçek:** Plan, ekran boyutundan bağımsız sanal bir tuvalde (1200 × 800 birim) tutulur ve ekrana
  sığacak şekilde ölçeklenir. Kasadaki büyük ekranda da dizüstünde de aynı görünür.
- **Bölge işlemleri:** Ekleme, ad değiştirme, sıralama ve silme. İçinde açık adisyon olan bölge
  silinemez.

## 3. Masa QR kodları

Her masanın kendine ait bir QR kodu olur. Müşteri okuttuğunda menü o masa için açılır. QR'dan
sipariş verme işi 11. ekranda (mobil) yapılacak; QR'ın kendisi şimdi hazırlanıp masalara yapıştırılabilir.

- **İçerik:** `https://<kafe-adresi>/masa/<masaId>?t=<anahtar>`. Anahtar (`qrToken`) sunucuda üretilen
  rastgele bir değerdir. Masa kimliğini tahmin eden biri başka bir masa adına sipariş veremez.
- **QR yenile:** Masa etiketinin fotoğrafı internete düşerse ya da kötüye kullanılırsa tek tıkla yeni
  anahtar üretilir. Eski QR o anda geçersiz olur, yeni etiket basılır.
- **Çıktı:** Seçili masalar ya da bütün bölge için **A4 PDF** üretilir. Sayfa başına 6 etiket basılır;
  her etikette kafe adı, büyük masa adı ve "Menü ve sipariş için okutun" yazısı bulunur. Yazıcıdan çıkarıp
  kesip masaya yapıştırmak yeterli.

```
┌──────────────────────┐
│     VELVET KAFE      │
│   ▛▀▀▜ ▞▖▛▀▜ ▛▀▀▜    │
│   ▌██▐ ▚▞▌█▐ ▌██▐    │
│   ▙▄▄▟ ▗▚▙▄▟ ▙▄▄▟    │
│       MASA 4         │
│ Menü ve sipariş için │
│      okutun 📱       │
└──────────────────────┘
```

## 4. Garson ekranına etkisi: plan görünümü

```
 [Salon (3/8)] [Teras (1/8)] [Bahçe (0/8)]                         [▦ Plan | ☰ Liste]
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │   ╭─────╮     ╭─────╮     ┌────────┐                  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓            │
 │   │  1  │     │  2  │     │   3    │                  ▓ BAR TEZGÂHI ▓            │
 │   │ boş │     │ 1s05│     │ 235 ₺  │                  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓            │
 │   ╰─────╯     ╰─────╯     └────────┘                                            │
 │                 🟥 dolu     🟧 hesap istendi     ⬜ boş     🟦 rezerve            │
 └──────────────────────────────────────────────────────────────────────────────────┘
```

- **Masalar plandaki yerlerinde görünür.** Renk durumu, üstündeki yazı ise süreyi ve açık tutarı
  gösterir. Masaya dokununca bugünkü sipariş penceresi açılır; sipariş akışı 4. ekrana kadar
  değişmez.
- **Liste görünümü korunur.** Mevcut kart düzeni küçük ekranlar ve alışkanlık için bir düğmeyle
  açılabilir. Seçim bilgisayarda hatırlanır.
- **Masa transferi** (mevcut özellik) plan görünümünde de çalışır.

## 5. "Bitti" sayılma ölçütü

- [x] Bölge eklenip adı değiştirilebiliyor, sıralanabiliyor, silinebiliyor (açık adisyon yoksa)
- [x] Plan editöründe masa ve dekor eklenip taşınabiliyor, boyutlandırılıp döndürülebiliyor, çoğaltılıp
      silinebiliyor; ızgaraya hizalama çalışıyor
- [x] Plan tek seferde kaydediliyor; aynı anda başkası kaydettiyse çakışma uyarısı çıkıyor
- [x] İnternet yokken plan görüntüleniyor, düzenleme kapalı
- [x] Mevcut 3 bölge / 24 masa buluta bir kez, çift kayıt olmadan aktarılıyor; eski siparişler
      masalarına bağlı kalıyor
- [x] Her masanın QR'ı var; "QR yenile" eski anahtarı geçersiz kılıyor; A4 PDF 6'lı etiket basıyor
- [x] Garson ekranında plan görünümü durum renkleriyle çalışıyor; liste görünümüne geçilebiliyor
- [x] Yetkisi olmayan (`editMenu` yok) kişi planı değiştiremiyor; hem ekranda hem fonksiyonda reddediliyor
- [x] Emülatör testleri: kurallar, `saveFloorPlan` (çakışma dahil), QR yenileme, aktarım, delta senkron
