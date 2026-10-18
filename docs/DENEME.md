# Kendi bilgisayarında deneme (canlıya almadan)

Her şey bilgisayarında çalışır: Firebase'in yerine **emülatör** (bulutun bilgisayardaki kopyası), kasada **NexPOS**,
tarayıcıda **müşteri uygulaması** ve **mutfak ekranı**. Gerçek bir Firebase projesi, kart, SMS ücreti gerekmez;
hiçbir şey internete yayınlanmaz. Deneme verisi gerçek kasa verisine (`nexpos.db`) karışmaz.

```
┌───────────── Bilgisayarın ─────────────────────────────────────────────┐
│  [1] Emülatör penceresi  ←→  [3] NexPOS (kasa / garson / panel)          │
│          ↑                                                              │
│  Tarayıcı: http://127.0.0.1:5005        → müşteri uygulaması            │
│            http://127.0.0.1:5005/masa/… → masadaki QR'ı okutmuş gibi     │
│            http://127.0.0.1:5005/mutfak → mutfak / bar ekranı            │
└────────────────────────────────────────────────────────────────────────┘
```

## A. Bir kez kurulacaklar (Windows)

| Program | Nereden | Not |
|---|---|---|
| Python 3.11+ | python.org | Kurarken **"Add python.exe to PATH"** işaretli olsun |
| Node.js 22 LTS | nodejs.org | |
| Java 21 | adoptium.net (Temurin 21) | Firestore emülatörü için |
| Firebase CLI | Komut İstemi'nde: `npm install -g firebase-tools` | Giriş yapmak gerekmez |
| Google Chrome | | Uygulamayı görmek için |
| (İsteğe bağlı) Flutter | flutter.dev → Windows | Yalnızca uygulamayı kendin derleyeceksen |

Kontrol: Komut İstemi'nde `python --version`, `node --version`, `java -version`, `firebase --version`.

**Kodu indir:** GitHub'da depo → dal (branch) olarak **`claude/zen-keller-0w8hhb`** seç → **Code → Download ZIP**,
bir klasöre aç (ör. `C:\NexPOS`). (Bu dal henüz ana dala birleşmedi; ana daldaki kod eski.)

## B. Müşteri uygulamasının web sürümü (bir kez)

- **Flutter kurmadan:** sana gönderilen `kafe-web-deneme.zip`'i aç, içindekileri `firebase\hosting` klasörüne kopyala
  (`mutfak` klasörü yerinde kalsın; `index.html` doğrudan `firebase\hosting` içinde olmalı).
- **Flutter varsa:** `demo\4-uygulama-derle.bat` (uygulamada bir şey değiştirince de bunu çalıştır).

## C. Her denemede

1. **`demo\1-bulut.bat`** — emülatörler açılır. İlk seferde paketleri kurar (birkaç dakika).
   *"All emulators ready!"* yazınca hazır. **Bu pencere açık kalsın.** Kapatırken pencerede **Ctrl+C**:
   veriler `firebase\demo-veri`'ye kaydedilir, bir sonraki açılışta aynen gelir.
2. **`demo\2-ornek-veri.bat`** — örnek kafe kurulur: 14 ürün (tat profilleriyle), personel, kampanyalar,
   7 damgalı bir üye. Sonda giriş bilgilerini yazar. (İkinci kez çalıştırmak bir şeyi bozmaz.)
3. **`demo\3-nexpos.bat`** — NexPOS açılır (ilk seferde Python paketlerini kurar).
   - "Bu bilgisayarı kafeye bağla": **sahip@demo.kafe** / **demo-sifre-1**, terminal adı: Kasa 1.
   - Giriş: Yönetici PIN **482913** · Müdür **583920** · Kasa **640218** · Garson **730591**.
   - **Masaları buluta aktar (bir kez):** Yönetim → Tanımlamalar → Masa / Bölgeler → **Buluta Aktar**.
     Sonra `demo\2-ornek-veri.bat`'ı tekrar çalıştır: masaların QR adresleri listelenir.
4. Tarayıcıda **http://127.0.0.1:5005** — müşteri uygulaması. Telefon görünümü için Chrome'da **F12 →
   cihaz simgesi (Ctrl+Shift+M)** → iPhone/Pixel seç.
   - Giriş: **0532 777 00 11** → "Kod gönder" → **SMS kodu 1. pencerede yazar**:
     *"To verify the phone number +905327770011, use the code 123456"*. Kasada açılmış üye olduğu için kart dolu gelir.
   - Başka numarayla girersen yeni üye açılır (ad + aydınlatma metni onayı).

## D. Denenecek senaryolar

| Ne | Nasıl |
|---|---|
| **Kasada satış** | NexPOS → masa seç → ürün ekle → Gönder → Öde. Ana Sayfa ve Raporlar dolar. |
| **Mutfak ekranı** | NexPOS → Yönetim → Terminaller → **Mutfak Ekranı Ekle** → 6 haneli kod; tarayıcıda yeni sekme **http://127.0.0.1:5005/mutfak** → kodu gir. Kasadan gönderilen ürün düşer; **Başla → Hazır** → kasada 🔔. |
| **Sadakat** | Kasada adisyonda 👤 Müşteri ekle → telefon 0532 777 00 11; ödeyince damga işler, uygulamadaki kart anında güncellenir. (Uygulamadaki **QR'ım** kasada barkod okuyucuyla okutulur; okuyucu yoksa telefonla aramak aynı işi görür.) |
| **Masadan sipariş** | `2-ornek-veri`'nin yazdığı masa adresini aç → menü → sepet → gönder (giriş ister). NexPOS'ta **📲 Gelen siparişler** turuncu olur → **Onayla**: adisyon açılır, fiş mutfağa düşer; mutfakta **Hazır** → uygulamada "Siparişin hazır 🔔". |
| **Garson çağır / Hesap iste** | Masa adresinde üstteki düğmeler → NexPOS'ta masada 🙋 / 🧾, Gelen siparişler'de "Tamam". |
| **Gel-al** | Uygulama ana sayfa → **Gel-al sipariş** → sepet → saat → gönder → NexPOS'ta onayla. |
| **Onay süresi** | Gelen siparişi 2 dakika bekletirsen uygulamada "Kafe şu an yoğun" yazar. |
| **Kasa kapalıyken uygulama** | NexPOS'u kapat, 2 dakika bekle: uygulamada sepet "Şu an çevrimiçi sipariş alınmıyor" der. NexPOS'u açınca düzelir. |
| **İnternet kesilince kasa** | 1. pencereyi Ctrl+C ile kapat: NexPOS satışa devam eder (üstte "çevrimdışı"). `1-bulut`'u tekrar açınca bekleyen işlemler kendiliğinden gider. |
| **Bana öner** | Uygulama → **✨ Bana öner** → 4 soru. Soruları NexPOS → Pazarlama → **Kahve Önerisi**'nden değiştir ("Dene" ile önizle). |
| **Kampanya** | Happy Hour hafta içi 14–17 arası kendiliğinden uygulanır; Pazarlama → Kampanyalar'dan saatini değiştirip dene. |
| **Raporlar** | Yönetim → Raporlar (sekmeler); **Uygulama** sekmesi → "Buluttan yükle" (yönetici şifresi sorar). |
| **Stok, vardiya** | Ayarlar → Modüller'den Stok'u aç → Stok sayfası; Vardiyam / Personel. |

**Telefon bildirimi** emülatörde gerçekten telefona gitmez (Google'ın sunucusu gerekir); uygulama açıkken
sipariş durumu ekranda bildirim olarak görünür. Gerçek bildirim canlıya almada denenir.

## E. Sorun olursa

| Belirti | Çözüm |
|---|---|
| `firebase` / `node` / `java` tanınmıyor | Programı kurduktan sonra Komut İstemi'ni kapatıp aç |
| 1. pencerede "port taken" | Önceki emülatör açık kalmış: o pencereyi kapat ya da bilgisayarı yeniden başlat |
| "HTTP 404" ya da 1. pencerede "Failed to load function definition … Timeout" | Fonksiyonlar zamanında yüklenemedi: 1. pencereyi Ctrl+C ile kapatıp `1-bulut.bat`'ı tekrar açın (yeni sürümde bekleme süresi 120 sn). Açılışta "Loaded functions definitions" satırını görün |
| NexPOS "bağlanamadı" | 1. pencere açık mı, "All emulators ready!" yazdı mı? |
| Uygulama boş beyaz sayfa | B adımı yapılmamış: `firebase\hosting\index.html` var mı? |
| Baştan başlamak | Emülatörü kapat, `firebase\demo-veri` klasörünü ve `nexpos_demo.db` dosyasını sil |

## F. Mac / Linux

Aynı adımlar, `.bat` yerine `demo/1-bulut.sh`, `demo/2-ornek-veri.sh`, `demo/3-nexpos.sh`,
`demo/4-uygulama-derle.sh` (Terminal'de çalıştır). Java için `brew install --cask temurin@21`.

## G. (İsteğe bağlı) Gerçek telefondan bakmak

Bilgisayar ve telefon aynı Wi-Fi'da olmalı. Bilgisayarın yerel IP'sini öğren (`ipconfig` → IPv4, ör. 192.168.1.20):

1. `firebase/firebase.json` → `emulators` altındaki tüm `"host": "127.0.0.1"` değerlerini `"0.0.0.0"` yap.
2. `mobile/assets/brand.json` → `"emulator": { "enabled": true, "host": "192.168.1.20" }`, sonra uygulamayı
   yeniden derle (`4-uygulama-derle`; Flutter gerekir).
3. NexPOS → Yönetim → Ayarlar → **Genel Ayarlar** → QR adresi: `http://192.168.1.20:5005/masa` (basılan QR'lar telefondan açılır).
4. Windows güvenlik duvarı sorarsa "Özel ağlarda izin ver". Telefonda `http://192.168.1.20:5005`.
   (Mutfak ekranını bu modda yalnızca bilgisayarın kendisinde aç: `http://127.0.0.1:5005/mutfak`.)

Denemeden sonra bu değişiklikleri geri al (`git checkout firebase/firebase.json mobile/assets/brand.json`).
