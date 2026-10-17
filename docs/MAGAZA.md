# Müşteri uygulamasını yayınlama (Google Play ve web)

Uygulama her kafe için ayrı derlenir (ad, logo, renkler, Firebase projesi). Bu belge bir kafe kabul ettiğinde
yapılacakları sırayla anlatır. iOS (App Store) için bir Mac ve Apple Developer hesabı (yıllık 99 $) gerekir;
adımlar aynıdır, yalnızca derleme ve mağaza formu farklıdır.

## 1. Hesaplar

| Ne | Kim açar | Ücret |
|---|---|---|
| Firebase projesi (Blaze planı: Functions ve SMS için) | Kafe sahibi ya da sen (kafe adına) | Kullandıkça; küçük kafede aylık düşük |
| Google Play geliştirici hesabı | Tercihen kafe (uygulama onun adına yayınlanır) | Tek seferlik 25 $ |
| Alan adı (isteğe bağlı) | Kafe | `<proje>.web.app` ücretsizdir |

## 2. Firebase ayarları

1. Authentication → **Telefon** girişini aç; Ayarlar → yetkili alan adlarına `<proje>.web.app` (ve varsa kendi alan adı).
2. Proje ayarları → **Web uygulaması** ekle → yapılandırmayı `mobile/assets/brand.json` → `firebase`'e yaz.
3. **Android uygulaması** ekle: paket adı `brand.json` → `androidPackage` (ör. `com.velvetkafe.app`);
   çıkan uygulama kimliğini `firebase.androidAppId`'ye yaz.
4. Cloud Messaging → Web anahtar çifti (VAPID) oluştur → `brand.json` → `webPushKey`.
5. `brand.json` → `emulator.enabled: false`, `webHost: <proje>.web.app`.

## 3. Derleme

```bash
cd mobile
python3 tool/apply_brand.py          # ad, paket adı, simgeler, bağlantılar, bildirim servis çalışanı
tool/build_web.sh                    # web sürümü (masadaki QR bunu açar) → firebase/hosting
flutter build appbundle --release    # Google Play için .aab (imzalama: aşağıda)
cd ../firebase && firebase deploy    # kurallar, fonksiyonlar, web
```

Android SDK'sı olmayan bilgisayarda: GitHub'da **Actions → Mobil uygulama → Run workflow**; derlenen APK
"Artifacts" altından indirilir (`.github/workflows/mobile.yml`).

**İmzalama:** `keytool -genkey -v -keystore kafe.jks -keyalg RSA -keysize 2048 -validity 10000 -alias kafe`
ile anahtar üret; `android/key.properties` ile tanımla (Flutter belgesi: "Build and release an Android app").
Anahtarı kaybetme — güncellemeler aynı anahtarla imzalanır. Play App Signing açık olsun.

**Masa QR'ının uygulamayı açması (App Links):** Play Console → Uygulama bütünlüğü → uygulama imzalama anahtarının
SHA-256 parmak izini `brand.json` → `androidSha256`'ya yaz, `apply_brand.py` ve `build_web.sh`'ı tekrar çalıştır
(`/.well-known/assetlinks.json` üretilir). Bu yapılmazsa QR yine çalışır, tarayıcıda açılır.

## 4. Play Console formu

- **Uygulama adı:** kafenin adı (30 karakter). **Kısa açıklama (80):**
  "<Kafe> menüsü, dijital damga kartı, masadan sipariş ve gel-al."
- **Tam açıklama (taslak):**
  > <Kafe>'nin resmi uygulaması. Her kahvede damga kazan, kart dolunca içeceğin bizden. Menüye göz at,
  > masadaki QR'ı okutup garson beklemeden sipariş ver ya da yoldayken gel-al siparişi bırak; hazır olunca
  > haber verelim. Kararsız mısın? "Bana öner" birkaç soruyla sana uygun kahveyi bulur. Kampanyaları ve
  > doğum günü sürprizlerini kaçırma.
- **Grafikler:** simge 512×512 (`mobile/store/icon_512.png`, `apply_brand.py` üretir), öne çıkan görsel 1024×500,
  en az 2 telefon ekran görüntüsü (ana sayfa, menü, QR, sepet, sipariş durumu, Bana öner).
- **Kategori:** Yeme ve İçme. **İletişim:** kafenin e-postası.
- **Gizlilik politikası URL'si:** `https://<webHost>/gizlilik` (panelde Pazarlama → Mobil Uygulama'daki metin).
- **Hesap silme URL'si:** `https://<webHost>/hesap-sil` (uygulama içinde: Profil → Hesabımı sil).
- **Hedef kitle:** 13+ (çocuklara yönelik değil). **Reklam:** yok.

### Veri güvenliği formu (cevaplar)

| Veri | Toplanıyor | Amaç | Paylaşılıyor |
|---|---|---|---|
| Telefon numarası | Evet (zorunlu) | Hesap, sadakat kartı | Hayır |
| Ad | Evet (zorunlu) | Hesap | Hayır |
| Doğum günü (gün/ay) | İsteğe bağlı | Doğum günü hediyesi | Hayır |
| Satın alma geçmişi | Evet | Sadakat, "her zamankinden", öneri | Hayır |
| Cihaz kimliği (bildirim anahtarı) | Evet | Sipariş ve kampanya bildirimi | Hayır |

Veriler aktarım sırasında şifrelenir (HTTPS); kullanıcı hesabını ve verilerini silebilir. Konum, kişiler,
fotoğraf, ödeme bilgisi toplanmaz.

## 5. Yayından sonra

- Kampanya bildirimleri Pazarlama → Bildirimler'den gider (izinli üyelere, günde en fazla 1).
- Raporlar → **Uygulama**: uygulama siparişleri, onay süresi, reddedilenler ve kahve önerisinin tutma oranı.
- Yeni sürüm: `pubspec.yaml` → `version` artır (ör. `1.0.1+2`), derle, Play Console'a yükle.
