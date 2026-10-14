# Kafe Otomasyonu: Mimari (B yolu) ve 1. Ekran

NexPOS kafedeki kasa, garson ve yönetim paneli olarak kalıyor. Merkezde Firebase var.
Flutter müşteri uygulaması da aynı Firebase'e bağlanıyor.

```
 ┌──────────────── Kafe ────────────────┐        ┌──────────── Bulut (Firebase) ────────────┐
 │ NexPOS (Windows, PySide6)            │        │ Auth: personel, terminal, müşteri        │
 │  ├─ Ekranlar (mevcut UI)             │        │ Firestore: tek doğru kaynak              │
 │  ├─ database.py  ← aynı fonksiyonlar │  HTTPS │ Cloud Functions: fiyat, ödeme, damga,    │
 │  ├─ Yerel önbellek (SQLite)          │◄──────►│   stok, syncOps, registerTerminal…       │
 │  ├─ Giden kuyruk (outbox)            │        │ FCM: bildirimler                         │
 │  └─ Senkron işçisi (arka plan)       │        └──────────────────▲───────────────────────┘
 └──────────────────────────────────────┘                           │
                                                 Flutter müşteri uygulaması (sadakat, menü,
                                                 kahve önerisi, masadan QR sipariş)
```

---

## 1. B yolunun eksisi: internet kesilirse ne olacak?

**Çözüm: NexPOS "önce yerel" (local-first) çalışacak.** Ekranlar her zaman yerel SQLite'tan okuyup
yerel SQLite'a yazar. Bulutla konuşma işini arkada çalışan bir senkron işçisi yapar. Garson internetin
gidip geldiğini fark etmez. Yalnızca üst barda bir durum etiketi değişir:
"🟢 Çevrimiçi" → "🟠 Çevrimdışı · 12 işlem bekliyor".

Bu A yolundaki (köprü) "iki veritabanı" sorununa geri dönmek değil. Fark şurada:
A'da iki eşit veritabanı vardı ve birbirine yetişmeye çalışıyordu. Burada **bulut tek patrondur.**
Yerel SQLite yalnızca bir önbellek ve gönderilmeyi bekleyen işlemlerin kuyruğudur.
Hangi verinin sahibi kim, aşağıdaki tablo kesin olarak belirliyor.

### Verinin sahibi kim?

| Veri | Sahibi | Çevrimdışıyken |
|---|---|---|
| Menü, fiyat, masa yerleşimi, personel, yetkiler, ayarlar | **Bulut** | Önbellekten okunur. Düzenleme kapalıdır (panelde uyarı çıkar) |
| Sipariş açma, ürün ekleme, mutfağa gönderme, durum değişikliği | **Terminal üretir**, bulut onaylar | ✅ Tam çalışır, kuyruğa yazılır |
| Ödeme alma, masa kapatma, gider, zayi | **Terminal üretir**, bulut onaylar | ✅ Tam çalışır, kuyruğa yazılır |
| Sadakat damgası basma | Bulut | ✅ QR çevrimdışı doğrulanır, damga internet gelince basılır (§1.3) |
| Ödül kullanma (bedava kahve) | Bulut | ❌ Kapalıdır. Aynı ödül iki kez harcanmasın diye internet gerekir |
| Müşterinin QR'dan / uygulamadan verdiği sipariş | Bulut | ❌ Uygulamada "Masadan sipariş şu an kapalı, garsona söyleyin" yazar (§1.4) |
| Raporlar | Bulut (`dailyStats`) | Son senkrondaki hâli gösterilir, üstünde "en son 14:32" yazar |

### 1.1 Kuyruk (outbox) nasıl çalışıyor?

NexPOS'un yerel SQLite dosyasına iki tablo eklenir:

```sql
CREATE TABLE outbox (
  op_id      TEXT PRIMARY KEY,   -- UUID; aynı işlem iki kez gönderilse de bir kez işlenir
  op         TEXT NOT NULL,      -- 'openTable', 'addItems', 'takePayment', ...
  payload    TEXT NOT NULL,      -- JSON
  staff_id   TEXT NOT NULL,      -- işlemi yapan personel (PIN ile giren)
  created_at TEXT NOT NULL,      -- terminal saati
  attempts   INTEGER DEFAULT 0,
  last_error TEXT
);
CREATE TABLE sync_state (collection TEXT PRIMARY KEY, last_pulled_at TEXT);
```

- **Yazma:** `database.create_order(...)` yerel tabloları günceller ve aynı SQLite transaction'ı içinde
  `outbox`'a bir satır ekler. Ya ikisi birden olur ya hiçbiri.
- **Gönderme (push):** İşçi her 3 saniyede bir kuyruğu kontrol eder. İşlemleri 50'şerlik paketler
  hâlinde `syncOps` fonksiyonuna sırayla gönderir. Fonksiyon her `op_id`'yi `processedOps/{opId}`
  dokümanına yazar; aynı işlem tekrar gelirse atlanır (idempotent). Başarılı işlemler kuyruktan silinir.
- **Çekme (pull):** İşçi her 5 saniyede bir, `updatedAt > son çekme zamanı` olan dokümanları
  Firestore REST ile çeker: menü, masalar, açık siparişler, mutfak fişleri. Böylece uygulamadan gelen
  siparişler ve diğer kasanın yaptıkları da görünür.
- **Hata:** Fonksiyon bir işlemi reddederse (örneğin yetkisi yoksa) işlem kuyrukta "hatalı" olarak
  işaretlenir, panelde kırmızı uyarı çıkar. Sessizce kaybolmaz.

Bunun için veri modeline iki kural eklendi:
1. **Her dokümanda `updatedAt` (sunucu zamanı) alanı olur.** Delta çekme bu alana bakar.
2. **Hiçbir şey fiziksel olarak silinmez; `deleted: true` işaretlenir.** Aksi hâlde silinen bir ürünü
   çekme işlemi göremez ve ürün terminalde kalır. (NexPOS ürünlerde bunu zaten yapıyor.)

### 1.2 Çevrimdışıyken kimlikler ve numaralar

- **Belge kimlikleri terminalde üretilir (UUID).** Bulutun "id ver" demesini beklemeye gerek kalmaz.
  NexPOS'taki `INTEGER AUTOINCREMENT` kimlikleri bu yüzden metin UUID'ye geçecek.
- **Adisyon numarası:** Her terminalin kendi harfi vardır (Kasa 1 = `A`). Numaralar `A47`, `A48` diye
  ilerler; uygulamadan gelen siparişler `Q12` olur. Böylece iki kaynak aynı numarayı vermez.
- **Fiyat:** Çevrimdışıyken terminal fiyatı önbellekteki menüden hesaplar. Bulut sonradan aynı hesabı
  tekrar yapar. Fark çıkarsa (örneğin fiyat o arada değişmişse) terminalin fiyatı geçerli kalır ama
  `auditLogs`'a `price_mismatch` kaydı düşer. Personel güvenilir bir kullanıcıdır; müşteri siparişlerinde
  fiyatı ise **her zaman** sunucu belirler.

### 1.3 Sadakat QR'ı internetsiz nasıl doğrulanır?

Müşterinin QR kodu sunucunun **özel anahtarıyla imzalanmış** kısa bir veridir:
`KAFE1.<uid>.<sonGeçerlilik>.<nonce>.<imza>` (Ed25519).

- Terminal imzayı yanında tuttuğu **açık anahtarla** doğrular. Bunun için internet gerekmez.
- Damga işlemi kuyruğa yazılır. Sunucu aynı `nonce`'u ikinci kez kabul etmez; ekran görüntüsüyle
  tekrar kullanılamaz.
- Müşteri uygulaması QR'ı her 60 saniyede yeniler. İmzalı QR'ları önceden 10 tane alıp sakladığı için
  müşterinin telefonunda internet yoksa bile QR gösterilebilir.

### 1.4 Uygulama, kafenin internetinin gittiğini nereden bilir?

Her terminal her senkronda `terminals/{id}.lastSeenAt` alanını günceller. Son 2 dakikada hiçbir terminal
görünmediyse müşteri uygulaması masadan siparişi ve gel-al siparişini kapatır, menü yine görünür.
Böylece müşteri "siparişim mutfağa gitti" sanıp boşuna beklemez.

### 1.5 Elektrik kesilir ya da bilgisayar bozulursa

- Kuyruk yerel SQLite'ta durduğu için bilgisayar kapanıp açılsa da kaybolmaz.
- İnternet geldikten sonra veri buluttadır. Bilgisayar tamamen bozulsa bile yeni bilgisayar eşlenip
  (§3.1) her şey geri iner. NexPOS'taki "Ctrl+B yedek" özelliğine gerek kalmaz; sadece henüz
  gönderilmemiş işlemler riskte kalır. Panelde "bekleyen işlem" sayısı bu yüzden hep görünür.

---

## 2. `database.py` dönüşümü

Ekranlar `database.xxx()` çağırmaya devam eder. Fonksiyonların içi değişir.

| Mevcut fonksiyon | Yeni hâli |
|---|---|
| `authenticate_user(email, şifre)` | `login_with_pin(staff_id, pin)` (yerel) + `login_manager(email, şifre)` (Firebase Auth) |
| `get_all_users`, `add_user`, `update_user`, `delete_user`, `update_user_password` | Önbellekten okur / `manageStaff` fonksiyonu (çevrimiçi) |
| `get_all_regions`, `get_tables_by_region`, `add_table`, `delete_table`, `add_region`… | Önbellekten okur / yönetici işlemleri çevrimiçi |
| `get_all_categories`, `get_products_by_category`, `add_product`, `update_product`… | Önbellekten okur / yönetici işlemleri çevrimiçi |
| `create_order(masa, garson, items, iskonto)` | Yerel yazar + kuyruk: `openTable`, `addItems`, `applyDiscount` |
| `update_order_status` | Yerel + kuyruk: `updateTicketStatus` / `closeOrder` |
| `transfer_table` | Yerel + kuyruk: `moveTable` |
| *(yok)* | `take_payment(order, yöntem, tutar)` → kuyruk: `takePayment` |
| `get_expenses`, `add_expense`, `get_waste`, `add_waste`… | Önbellek + kuyruk |
| `get_dashboard_stats`, `get_popular_products`, `get_toplam_iskonto`, `get_shift_summary` | `dailyStats` dokümanları (önbellekli) |

Bu sırada NexPOS'ta düzeltilecek hatalar:

- **Ödeme yöntemi kaydedilmiyor.** Ödeme ekranındaki "Nakit / Kredi Kartı" seçimi hiçbir yere yazılmıyor,
  sipariş sadece `tamamlandi` yapılıyor. Kasa sayımı bu yüzden yapılamıyor.
- **İskonto üst üste biniyor.** Açık bir siparişe yeni ürün eklenirken, zaten iskontolu olan toplamın
  üstüne iskonto tekrar uygulanıyor (`database.py:429`).
- **Yetki matrisi sahte.** "Yetkileri Kaydet" butonu sadece mesaj gösteriyor; matris kaydedilmiyor ve
  hiçbir yerde kontrol edilmiyor.
- **İki ekran veritabanına doğrudan dokunuyor:** masayı zorla kapatma (`user_panel.py:490`) ve
  masa adı değiştirme (`admin_panel.py:584`). Bunlar da `database.py` üzerinden geçecek.
- **Para `REAL` tutuluyor.** Kuruş cinsinden tam sayıya geçilecek.

Python tarafında eklenecek kütüphaneler: `requests` (Firebase REST), `keyring` (terminal anahtarını
Windows Kimlik Bilgisi Yöneticisi'nde saklamak için), `cryptography` (QR imzası doğrulama).
PIN özetleri için standart kütüphanedeki `hashlib.scrypt` yeterli.

---

## 3. 1. Ekran: Giriş ve roller

Onayına sunulan ekran tarifi.

### 3.1 Terminal eşleme (sadece ilk kurulumda, bir kez)

NexPOS ilk kez açıldığında karşısına bu ekran çıkar:

```
┌──────────────────────────────────────────────┐
│  ☕  Bu bilgisayarı kafeye bağla              │
│                                              │
│  Yönetici e-posta   [_____________________]  │
│  Şifre              [_____________________]  │
│  Terminal adı       [Kasa 1_______________]  │
│                                              │
│               [ Bağla ve verileri indir ]    │
│  ▓▓▓▓▓▓▓▓░░░░  Menü indiriliyor… (2/5)       │
└──────────────────────────────────────────────┘
```

- Yönetici Firebase Auth ile giriş yapar, `registerTerminal` fonksiyonu bu bilgisayar için ayrı bir
  **cihaz hesabı** (`terminal: true` claim'i olan) açar ve terminale bir harf verir (A, B…).
- Cihazın anahtarı Windows Kimlik Bilgisi Yöneticisi'ne kaydedilir. Bir daha şifre sorulmaz.
- Menü, masalar, personel listesi ve PIN özetleri indirilir. Bundan sonra terminal internetsiz açılabilir.
- Yönetici panelden terminali her an iptal edebilir (bilgisayar çalınırsa diye).

### 3.2 Günlük giriş ekranı (mevcut e-posta/şifre ekranının yerine)

```
┌───────────────────────────────────────────────────────────┐
│  NexPOS · Kasa 1                         🟢 Çevrimiçi      │
│                                                           │
│   Kim çalışıyor?                                          │
│   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                    │
│   │  CA  │ │  ED  │ │  MK  │ │  DY  │                    │
│   │ Cem  │ │ Elif │ │ Mert │ │ Deniz│                    │
│   │Garson│ │Garson│ │ Kasa │ │Müdür │                    │
│   └──────┘ └──────┘ └──────┘ └──────┘                    │
│                                                           │
│                       Yönetici girişi (e-posta) →         │
└───────────────────────────────────────────────────────────┘
          ↓ karta tıklayınca
     ┌─────────────────┐
     │ Elif · PIN      │
     │   ● ● ● ○ ○ ○   │
     │  1   2   3      │
     │  4   5   6      │
     │  7   8   9      │
     │  ⌫   0   ✓      │
     └─────────────────┘
```

- **PIN 6 hanelidir** ve dokunmatik ekranda da kullanılabilen bir tuş takımıyla girilir. İnternet yoksa
  da çalışır, çünkü önbellekteki PIN özetiyle karşılaştırılır.
- **Rolüne göre yönlendirir:** Garson ve Kurye garson paneline, Kasa garson paneline (+ kasa işlemleri),
  Müdür ve Yönetici yönetim paneline gider. Yönetim panelinden garson ekranına geçmek için bir buton da olur.
- **5 hatalı denemede** o kişinin kartı 5 dakika kilitlenir.
- **"Yönetici girişi (e-posta)"** bağlantısı internet gerektirir. Menü, fiyat, personel ve yetki
  düzenlemek isteyen kişi bununla girer, çünkü bu işlemler doğrudan buluta yazılır.

### 3.3 Hızlı kullanıcı değiştirme ve otomatik kilit

- Her ekranın üst barında **"👤 Elif ▾ → Kullanıcı değiştir"** düğmesi bulunur. Uygulamayı kapatmadan
  giriş ekranına dönülür; açık siparişler olduğu yerde kalır.
- Ayarlardan belirlenen süre (varsayılan 3 dk) boyunca işlem yapılmazsa ekran giriş ekranına döner.
  Birinin açık bıraktığı oturumdan başkası işlem yapamaz.
- Her işlem, PIN ile giren kişinin adıyla kaydedilir (`staff_id` alanı kuyruğa da yazılır).

### 3.4 Yetkili onayı

Garson kendi yetkisinin dışında bir şey yapmak isterse (iskonto, ürün iptali, ikram) işlem reddedilmez,
bu pencere açılır:

```
┌────────────────────────────────────┐
│ 🔒 Bu işlem için yetkili onayı gerekir │
│ İşlem: Latte ×1 iptal (₺95,00)     │
│ Neden: [Müşteri vazgeçti      ▾]   │
│ Yetkili: [Deniz (Müdür) ▾] PIN ●●●●●● │
│                 [Vazgeç] [Onayla]  │
└────────────────────────────────────┘
```

İşlem, garsonun ve onaylayan müdürün adıyla `auditLogs`'a yazılır.

### 3.5 Yönetim paneli değişiklikleri

- **Kullanıcılar sayfası:** Personel eklenirken şifre yerine **PIN** belirlenir. Yalnızca Müdür ve
  Yönetici için isteğe bağlı olarak e-posta (panel girişi) istenir. "PIN sıfırla" butonu eklenir.
- **Yetki matrisi:** Mevcut tablo görünümü korunur ama artık gerçekten `settings/permissions`'a kaydedilir.
  Hem NexPOS ekranları (yetkisi olmayan butonları gizler) hem Cloud Functions (isteği reddeder) bu ayarı uygular.
  Matrise `İkram`, `İade` ve `Gider girişi` satırları eklenir.
- **Yeni "Terminaller" sayfası:** Ad, harf, son görülme zamanı, 🟢/🟠 durumu, bekleyen işlem sayısı ve
  "İptal et" butonu.

### 3.6 İlk yönetici (Owner)

En baştaki tek yönetici, Genç Ofis'teki `setAdmin.js` betiği gibi bir komutla tanımlanır:
`node scripts/createOwner.js email@ornek.com`. Bundan sonraki herkesi panelden o ekler.

### 3.7 Bu ekranın "bitti" sayılma ölçütü

- [ ] Yeni bir bilgisayar eşlenebiliyor; internet kesikken NexPOS açılıp PIN ile giriş yapılabiliyor
- [ ] Yanlış PIN 5 kez girilince kart kilitleniyor
- [ ] Garson iskonto butonuna bastığında yetkili onayı istenmeden işlem yapılamıyor
- [ ] Yetki matrisi kaydediliyor; NexPOS yeniden açılınca ve fonksiyon tarafında da geçerli oluyor
- [ ] Panelden iptal edilen terminal bir sonraki senkronda giriş ekranına kilitleniyor
- [ ] Firestore kuralları ve fonksiyonlar emülatör testleriyle doğrulanıyor (Genç Ofis'teki `firebase-tests` gibi)
