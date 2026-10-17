# 11. Ekran: Müşteri Uygulaması (Flutter) (tamam: 11a, 11b, 11c)

## Amaç

Müşterinin cebindeki kafe:

- **Sadakat kartı** telefonda olsun: damgalar, ödüller, seviye; kasada okutulan QR.
- **Menü** her yerden görülsün: fotoğraf, açıklama, alerjen, kalori, kafein, tükendi bilgisi.
- **Masadan QR ile sipariş**: masadaki QR okutulur, sipariş garson beklemeden bara/mutfağa düşer.
- **Gel-al**: yoldayken sipariş, "hazır" bildirimi, gelip al.
- **Kahve önerisi**: birkaç soruyla "bugün sana ne iyi gelir".
- 10. ekrandaki **kampanyalar ve bildirimler** müşteriye ulaşsın.

Sistemin geri kalanıyla ilişkisi: uygulama **Firebase**'e bağlanır (aynı proje). Sipariş doğrudan NexPOS'a
yazılmaz; buluta bir **istek** olarak düşer, NexPOS onu alıp normal adisyona çevirir. Böylece kasanın internetsiz
çalışma düzeni ve tek doğru kaynak (adisyon kasada açılır) bozulmaz.

Bu da bir **modül**dür (Ayarlar → Modüller → "Mobil uygulama"): masadan sipariş ve gel-al ayrı ayrı açılıp kapanır.

---

## 11.1 Giriş ve kayıt

```
┌────────────────────────┐
│      ☕ Velvet Kafe      │
│                        │
│  Telefon numaran        │
│  [ 0532 ___ __ __ ]     │
│  [   Kod gönder   ]     │
│                        │
│  Giriş yapmadan menüye  │
│  bak →                  │
└────────────────────────┘
```

- Telefon + **SMS kodu** (Firebase). Kasada telefonla üye olan müşteri, aynı numarayla girince kartı aynen gelir.
- İlk girişte: ad, isteğe bağlı doğum günü (gün/ay), **KVKK aydınlatma metni** ve kampanya bildirimi izni (ayrı onay).
- Giriş yapmadan menüye bakılabilir; sipariş ve kart için giriş gerekir.
- **Hesabı sil** (Profil): 10. ekrandaki KVKK silmeyle aynı; uygulama mağazaları da bunu zorunlu tutar.

## 11.2 Ana sayfa ve sadakat kartı

```
┌────────────────────────────┐
│ Merhaba Ayşe 👋   Gümüş ⭐   │
│ ┌────────────────────────┐ │
│ │ ●●●●●●●○○○  7 / 10      │ │
│ │ 3 kahve sonra bir bedava│ │
│ │ 🎁 1 ödülün var (60 gün) │ │
│ │      [ QR'ı göster ]     │ │
│ └────────────────────────┘ │
│ 🏷 Happy Hour %20 · 14–17   │
│ 🏷 2. kahveye %50           │
│ [☕ Sipariş ver] [✨ Bana öner]│
└────────────────────────────┘
```

- **QR'ı göster**: 60 saniyede bir yenilenen, tek kullanımlık QR (10. ekrandaki `resolveLoyaltyToken`); ekran
  parlaklığı açılır. Ekran görüntüsü başkasına verilse işe yaramaz.
- Kampanyalar: panelde "uygulamada göster" işaretli olanlar, açıklamasıyla.
- Doğum günü haftasında 🎂 kartı.

## 11.3 Menü

- Kategoriler, ürün kartı (fotoğraf, fiyat), ürün detayı: açıklama, seçenekler (boy, süt…), alerjen, kalori, kafein.
- Tükenen ürün "tükendi" görünür (kasadaki **Tükendi** işareti anında yansır).
- **Favoriler** ve **"Her zamankinden"** (son siparişi tek dokunuşla tekrarla).
- Kampanya fiyatı ürün kartında görünür ("Happy Hour'da 76 ₺").

## 11.4 Masadan QR ile sipariş

```
Masadaki QR → telefonun kamerası → (uygulama varsa uygulama, yoksa tarayıcıda) "Masa 4 · Velvet Kafe"
→ menü → sepet → [Siparişi gönder] → "Siparişin alındı, hazırlanıyor"
```

- Masadaki QR 3. ekranda basılan QR'dır (masa + gizli anahtar); başka masanın QR'ı tahmin edilemez.
- Sipariş NexPOS'ta **onaylanınca** o masanın adisyonuna eklenir ve bara/mutfağa düşer (KDS ve fiş aynen çalışır).
- Masada açık adisyon varsa ona eklenir; yoksa açılır.
- Müşteri masadan **"Garson çağır"** ve **"Hesap iste"** diyebilir (garson ekranında masa 🔔 olur).
- Ödeme masada garsona / kasaya (bkz. Sorular 3). Üye girişliyse damga kendiliğinden kartına işlenir.
- Kötüye kullanıma karşı: aynı masadan bekleyen en fazla 2 istek, sepet tutarı sınırı, fiyatlar sunucuda menüden
  hesaplanır (uygulamanın gönderdiği fiyata güvenilmez).

## 11.5 Gel-al

```
Sepet → "Ne zaman geleceksin?"  [Şimdi (~10 dk)] [15 dk] [30 dk] [Saat seç]
→ [Siparişi gönder] → Alındı ✓ → Hazırlanıyor ☕ → Hazır 🔔 ("Siparişin hazır, A-47")
```

- Kafe açık saatlerinde ve kasa çevrimiçiyken açıktır (kasa 2 dakikadır internetsizse "şu an çevrimiçi sipariş
  alınmıyor" yazar).
- NexPOS'ta onaylanınca **masasız (paket) adisyon** olarak açılır, fiş bara düşer; barista **Hazır** deyince
  müşteriye bildirim gider.
- Ödeme gelince kasada (bkz. Sorular 3). Gelmeyen sipariş kasada iptal edilir; aynı müşteri 2 kez gelmezse gel-al
  ona kapanır (panelden açılır).

## 11.6 Kahve önerisi ("Bana öner")

```
1/4 Bugün nasıl hissediyorsun?   [Uykuluyum 😴] [Keyifliyim 🙂] [Sakin bir şey]
2/4 Sütlü mü?                    [Evet] [Hayır] [Fark etmez]
3/4 Sıcak mı soğuk mu?           [Sıcak] [Buz gibi]
4/4 Hangisi sana yakın?          [Çikolata] [Meyvemsi] [Fındık] [Sade]
→ "Sana önerimiz: Mocha ☕ (%92 uyum)"  [Sepete ekle]   + 2 alternatif
```

- **Kural tabanlıdır** (yapay zekâ yok; hızlı, ücretsiz). Cevaplar bir tat profili oluşturur; menüdeki ürünlerin
  tat profiliyle karşılaştırılır; tükenen ürün önerilmez. Akşam 17:00'den sonra kafeinsiz ürüne, sıcak günde
  soğuk içeceğe, müşterinin hiç denemediği ürüne küçük artı puan.
- Ürünlerin tat profili (sertlik, tatlılık, asidite, gövde, sütlü/sütsüz, sıcak/soğuk, notalar) panelde
  **Menü → ürün → Tat profili** sekmesinden girilir; yaygın kahveler için **hazır şablon** (8. ekrandaki reçete
  şablonu gibi) doldurur. Sorular panelden düzenlenir.
- Önerinin sipariş edilip edilmediği kaydedilir (Raporlar'da "öneri tutma oranı").

## 11.7 Bildirimler

- 10. ekranda hazırlanan bildirimler gönderilir (yalnızca izin verenlere, kişi başı günde en fazla 1).
- Sipariş durumu bildirimleri (alındı, hazır) her zaman gider (izin gerektirmez; işlem bildirimi).
- Ödül kazanıldı, doğum günü, "ödülünün süresi 7 gün sonra doluyor" bildirimleri (izinliyse).

## 11.8 Profil

Bilgilerim (ad, doğum günü), geçmiş siparişler ve damgalar, ödüllerim, bildirim izinleri, KVKK metni, hesabı sil,
çıkış.

## 11.9 NexPOS ve panel tarafı

```
┌ Gelen siparişler (2) ──────────────────────────────────────────┐
│ 🔔 Masa 4 · Ayşe K. · 2× Latte, 1× Brownie · 310 ₺   [Onayla] [Reddet] │
│ 🛍 Gel-al · Mehmet T. · 15:40'ta gelecek · 1× Cold Brew  [Onayla] [Reddet]│
└──────────────────────────────────────────────────────────────────┘
```

- Kasada ve garson ekranında **Gelen siparişler** kutusu, sesli uyarı. Onayla → normal adisyon (masa ya da paket),
  fişler bara/mutfağa. Reddet → gerekçe (ör. "ürün bitti"), müşteriye bildirim.
- 2 dakika içinde onaylanmayan istek müşteriye "kafe şu an yoğun" olarak döner (ayarlanabilir).
- Panel: Ayarlar → **Mobil uygulama**: masadan sipariş açık/kapalı, gel-al açık/kapalı ve saatleri, hazırlanma
  süresi, onay süresi; KVKK metni; uygulamada görünecek kafe bilgisi (adres, saatler, telefon, Instagram).
- Panel: Menü'de ürün **fotoğrafı, uygulamada görünür, alerjen, kalori, kafein, tat profili** alanları.
- Raporlar: uygulama siparişleri (masadan / gel-al), onay süresi, reddedilenler, öneri tutma oranı.

## 11.10 Teknik

- **Flutter** (tek kod: Android, iOS, web). Masadan QR sipariş için uygulamayı indirmeyen müşteriye aynı kodun
  **web sürümü** açılır (`https://<proje>.web.app/m/...`).
- Firebase Auth (telefon), Firestore (menü, kampanya, kendi kartı ve siparişleri), Cloud Functions (sipariş
  isteği, QR, bildirim), Cloud Messaging (bildirim), App Check (sahte istemciye karşı).
- Yeni veri: `appOrders/{id}` (istek: kaynak, masa, müşteri, ürünler, durum, gel-al saati, bağlandığı adisyon),
  `settings/app`, `settings/quiz`, `customers/{id}/devices`, `recommendations/{id}`. Müşteri yalnızca kendi
  kartını, ödüllerini ve isteklerini okuyabilir.
- Testler: Flutter birim ve ekran testleri, emülatörde uçtan uca (istek → NexPOS onayı → adisyon → hazır bildirimi).
- Bu geliştirme ortamında Android APK derlenip sana gönderilir; iOS derlemesi bir Mac gerektirir (yayın hazırlığında).

## Sorular

1. **Masadan QR sipariş uygulama indirmeden (tarayıcıda) çalışsın mı?** *Önerim: evet* — masadaki müşterinin çoğu
   uygulama indirmez; aynı Flutter kodunun web sürümü açılır. Sadakat için orada da telefonla giriş yapılabilir.
2. **Uygulamadan gelen sipariş kasada onaylansın mı, yoksa kendiliğinden mutfağa mı düşsün?** *Önerim: onaylansın*
   (tek dokunuş, sesli uyarı) — şaka siparişleri ve biten ürünler mutfağı bozmasın. İsterseniz sonra
   "üye siparişlerini otomatik onayla" açılır.
3. **Uygulama içinden ödeme (kartla) olsun mu?** *Önerim: şimdilik hayır* — gel-al kasada, masadan siparişte masada
   ödenir. Online ödeme için sanal POS sözleşmesi (iyzico, PayTR vb.) ve ek işlem gerekir; ayrı bir iş olarak sonra.
4. **Giriş SMS koduyla olsun mu?** *Önerim: evet* — kasadaki üyelik telefona bağlı. SMS'ler Firebase faturasına
   yansır (gönderim başına küçük bir ücret; kafenin ölçeğinde aylık düşük tutar).
5. **Önce Android mi?** *Önerim: Android + web önce*, iOS yayın hazırlığında (Mac ve Apple Developer hesabı,
   yıllık 99 $, gerekir). Android için Google Play hesabı (tek seferlik 25 $) gerekir.
6. **Kasa internetsizken** uygulama siparişleri kapansın mı? *Önerim: evet* — kasa 2 dakikadır görünmüyorsa masadan
   sipariş ve gel-al "şu an alınmıyor" der; menü, kart ve öneri çalışmaya devam eder.
7. **Masadan "Garson çağır" ve "Hesap iste"** olsun mu? *Önerim: evet.*
8. **Uygulamanın adı, logosu ve renkleri** ne olsun? Kafenin adını ve logosunu (varsa) gönderirsen ona göre
   hazırlarım; yoksa "Velvet Kafe" ve sade bir kahve teması ile başlarım, sonra değiştiririz.

## Aşamalar

Bu ekran büyük olduğu için üç parçada gelir; her biri ayrı test edilip gönderilir:

- **11a** — Uygulama iskeleti, giriş/kayıt (SMS, KVKK), ana sayfa, sadakat kartı ve QR, menü, profil;
  panelde ürün fotoğrafı/alerjen/kalori/kafein alanları ve Mobil uygulama ayarları.
- **11b** — Masadan QR sipariş (uygulama + web), gel-al, NexPOS'ta Gelen siparişler, garson çağır / hesap iste,
  sipariş bildirimleri.
- **11c** — Kahve önerisi (tat profilleri, hazır şablon, soru düzenleyici), kampanya/ödül/doğum günü
  bildirimleri, raporlar, mağaza yayın hazırlığı (simgeler, ekran görüntüleri, gizlilik metni).

## "Bitti" sayılma ölçütü

- [x] SMS ile giriş; kasada açılmış üyelik aynı numarayla uygulamaya geliyor; KVKK onayı ve hesabı silme
- [x] Sadakat kartı canlı (damga, ödül, seviye); dönen QR kasada okunuyor
- [x] Menü: fotoğraf, seçenek, alerjen, tükendi anında; favori ve "her zamankinden"
- [x] Masadan QR sipariş (uygulama ve tarayıcı): istek → NexPOS onayı → masanın adisyonu → KDS; garson çağır / hesap iste
- [x] Gel-al: saat seçimi, onay, hazırlanıyor, hazır bildirimi; kasa çevrimdışıyken kapanıyor
- [x] Fiyatlar sunucuda menüden hesaplanıyor; başka masanın QR'ı ve sahte istek reddediliyor
- [x] Kahve önerisi: sorular, tat profili, tükenen ürün elenir, öneri sepete eklenir; tutma oranı raporu
- [x] Bildirimler: kampanya (izinli, günde 1), sipariş durumu, ödül ve doğum günü
- [x] Testler: Flutter birim/ekran, emülatörde uçtan uca; Android APK derleniyor (GitHub Actions — bu geliştirme ortamında Android SDK indirilemiyor)

## Durum

- **11a tamam.** `mobile/` (Flutter, Android + web): giriş (SMS, KVKK onayı, kasadaki üyeliğe bağlanma), ana sayfa
  (kart, ödüller, kampanyalar, "her zamankinden", kafe bilgisi), 60 sn'de dönen QR, menü (arama, kategori,
  tükendi, alerjen/kafein, favori), profil (düzenleme, izin, geçmiş, hesabı silme). Panelde
  **Pazarlama → Mobil Uygulama** (kafe bilgisi, KVKK metni) ve **Modüller → Mobil uygulama**.
- Testler: Flutter birim/ekran (ortak vektörlerle), emülatörde `customer_app.test.js`, tarayıcıda
  `app.browser.js` (Flutter web + Playwright).

- **11b tamam.** Masadaki QR (`/masa/<masa>?t=<anahtar>`) uygulamanın web sürümünü açar: giriş ekranı atlanır,
  menü masanın adıyla gelir; ürün seçenekleri, adet, not → sepet → (giriş) → **Siparişi gönder**. Gel-al: ana
  sayfadan, saat seçimi (hemen / 15 / 30 dk / saat seç). Sipariş durumu canlı (Onay bekliyor → Onaylandı →
  Hazırlanıyor → Hazır); "hazır" bildirimi uygulamanın her ekranında görünür (telefon bildirimi 11c'de).
  **Garson çağır / Hesap iste** girişsiz çalışır. Kasa 2 dakikadır görünmüyorsa sipariş alınmaz.
- NexPOS: üst çubukta **📲 Gelen siparişler**: Onayla (masanın adisyonuna eklenir ya da açılır; gel-al masasız
  adisyon; fişler bara/mutfağa; üye adisyona bağlanır), Reddet (gerekçe müşteriye gider), masa çağrıları (Tamam),
  gel-al listesi (Adisyonu aç / Gelmedi). Yeni istekte ses ve bildirim; masada 🙋 / 🧾 işareti. Onay sunucuya
  ulaşmazsa (müşteri iptal etti, süre doldu, internet yok) kasada hiçbir şey kaydedilmez.
- Kötüye kullanıma karşı: fiyat sunucuda menüden; masadan bekleyen en fazla 2, müşteri başına en fazla 3 açık
  istek; tek istekte en fazla 50 ürün / 3.000 ₺; başka masanın QR'ı geçmez; üst üste 2 kez gelmeyene gel-al
  kapanır (Pazarlama → Müşteriler'den açılır).

- **11c tamam.** **Bana öner**: panelden düzenlenen sorular (Pazarlama → Kahve Önerisi; "Dene" önizlemesi), ürünlerin
  tat profili (Menü → ürün → Tat Profili, 19 hazır şablon); eşleştirme telefonda internetsiz yapılır (JS, Python ve
  Dart aynı sonucu verir: `quiz_vectors.json`). Üyenin gördüğü öneri kaydedilir; önerilen ürün uygulamadan sipariş
  edilirse "tuttu" sayılır. **Telefon bildirimleri** (Firebase Cloud Messaging): sipariş onaylandı / hazır /
  alınamadı (her zaman), ödül ve doğum günü, ödülün süresi 7 gün sonra doluyor (izinle), panelden kampanya
  bildirimi (izin + günde en fazla 1). **Raporlar → Uygulama**: sipariş sayıları, onay oranı ve süresi,
  reddedilen / süresi dolan / gelinmeyen, öneri tutma oranı ve ürün bazında. **Mağaza**: `tool/apply_brand.py`
  (ad, paket adı, simgeler, App Links, bildirim servis çalışanı), `/gizlilik` ve `/hesap-sil` sayfaları,
  GitHub Actions ile APK; adımlar `docs/MAGAZA.md`.

### Kafeye özel (white-label)

Ad, logo ve renkler henüz belli değil; uygulama kafeye göre derlenir. Kod ortaktır, kafeye özel olanlar:
`mobile/assets/brand.json` (ad, slogan, renkler, Firebase ayarları), `mobile/assets/logo.png`, Android paket
adı ve kafenin kendi Firebase projesi. Adres, saatler ve KVKK metni panelden (`settings/app`) canlı gelir.
Adımlar KURULUM.md → "Yeni kafe için müşteri uygulaması".
