# NexPOS Bulut Kurulumu

NexPOS artık verisini Firebase'de tutar. Kafedeki bilgisayar bir **terminal** olarak buluta
bağlanır ve internet kesilse de çalışmaya devam eder. Mimari ve çevrimdışı çalışma için
[`docs/MIMARI.md`](docs/MIMARI.md), veri modeli için [`docs/VERI_MODELI.md`](docs/VERI_MODELI.md)
dosyalarına bakın.

| Klasör / Dosya | Görevi |
|---|---|
| `firebase/firestore.rules` | Kim neyi okuyup yazabilir |
| `firebase/functions/` | Cloud Functions: personel, yetki, terminal eşleme ve işlem kuyruğu (`syncOps`) |
| `firebase/functions/scripts/createOwner.js` | İlk yöneticiyi oluşturur |
| `firebase/tests/` | Kurallar + fonksiyonlar için emülatör testleri |
| `cloud/` | NexPOS'un bulut katmanı: Firebase REST istemcisi, senkron motoru, terminal eşleme |
| `tests/` | NexPOS testleri (yerel + emülatörle uçtan uca) |

## 1. Firebase projesi (bir kez)

1. [Firebase konsolunda](https://console.firebase.google.com) yeni proje açın, **Blaze** planına geçin
   (Cloud Functions için gerekir; küçük bir kafe ücretsiz kotanın içinde kalır).
2. **Firestore** veritabanı oluşturun. Konum olarak `eur3 (europe-west)` seçin.
3. **Authentication → Sign-in method** altında **E-posta/Şifre** yöntemini açın.
4. **Storage**'ı başlatın (ürün fotoğrafları için). Kova adını (`proje.firebasestorage.app`) not edin.
5. **Proje ayarları → Genel → Uygulamalarınız** altından bir **Web uygulaması** ekleyin ve `apiKey`
   değerini not edin.
6. Terminal eşleme özel token ürettiği için fonksiyonların servis hesabına imza yetkisi gerekir:
   Google Cloud konsolu → **IAM** → `PROJE_NO-compute@developer.gserviceaccount.com` hesabına
   **Service Account Token Creator** rolünü verin ve **IAM Service Account Credentials API**'yi
   etkinleştirin.

## 2. Kuralları ve fonksiyonları yayınlama

```bash
npm install -g firebase-tools
firebase login
cd firebase
firebase use --add            # projenizi seçin
cd functions && npm install && cd ..
firebase deploy --only firestore,functions,storage,hosting
```

`hosting` mutfak/bar ekranını (`https://<proje>.web.app/mutfak`) yayınlar. Sayfanın kullandığı Firebase
web SDK dosyaları `hosting/mutfak/vendor/` klasöründedir (tablet her şeyi kafenin kendi adresinden
yükler); SDK sürümünü yükseltmek için `cd firebase/tests && npm install && cd .. && node scripts/vendor-firebase-sdk.js`.

## 3. İlk yönetici

Firebase konsolu → Proje ayarları → **Hizmet hesapları** → "Yeni özel anahtar oluştur" ile bir JSON
indirin (bu dosyayı **kimseyle paylaşmayın ve repoya koymayın**), sonra:

```bash
cd firebase/functions
GOOGLE_APPLICATION_CREDENTIALS=/yol/servis-hesabi.json \
  node scripts/createOwner.js sahip@kafe.com "güçlü-bir-şifre" "Ad Soyad" 482913
```

Son parametre yöneticinin 6 haneli PIN'idir. Bundan sonraki tüm personeli yönetici NexPOS
panelinden ekler.

## 4. Kafedeki bilgisayar

1. `nexpos_config.example.json` dosyasını `nexpos_config.json` adıyla kopyalayın ve `apiKey`,
   `projectId` ve `storageBucket` değerlerini doldurun (exe kullanılıyorsa exe'nin yanına koyun).
2. `pip install -r requirements.txt` ve `python main.py`.
3. İlk açılışta **"Bu bilgisayarı kafeye bağla"** ekranı gelir. Yönetici e-postası ve şifresiyle
   giriş yapıp terminale bir ad verin. Personel ve yetkiler iner; bundan sonra NexPOS internetsiz
   de açılır.

Terminal anahtarı Windows Kimlik Bilgisi Yöneticisi'nde (`NexPOS / terminal`) saklanır. Bilgisayar
çalınırsa panelden **Terminaller → Terminali İptal Et** yapın.

## Giriş ve roller

| Rol | Giriş | Varsayılan ekran |
|---|---|---|
| Yönetici (owner) | PIN veya e-posta | Yönetim paneli |
| Müdür (manager) | PIN veya e-posta | Yönetim paneli |
| Kasa, Garson, Kurye, Barista, Mutfak | PIN | Garson paneli |

- PIN ile giriş internetsiz çalışır. 5 hatalı denemede kart 5 dakika kilitlenir.
- 3 dakika işlem yapılmazsa ekran kilitlenir (`settings/general.idleLockMinutes` ile değiştirilebilir).
- Personel, PIN ve yetki matrisi değişiklikleri buluta yazılır; PIN ile giren yöneticiye bir kez
  şifresi sorulur.
- Yetkisi olmayan işlemde (iskonto, sipariş iptali) **yetkili onayı** penceresi açılır; onay
  `auditLogs` koleksiyonuna iki kişinin adıyla yazılır.

## Menü

Menü bulutta tutulur (`categories`, `products`, `optionGroups`); NexPOS önbelleğe alır, satış
internetsiz de devam eder. Yönetim paneli → Tanımlamalar → **Menü / Ürünler**:

- Bulutta menü yoksa ilk açılışta **"Buluta Aktar"** ile NexPOS'taki mevcut menü bir kez aktarılır.
- Fiyatlar kuruş cinsinden tutulur ve KDV dahil girilir (varsayılan %10).
- Menü düzenleme internet ister ve `editMenu` yetkisi gerektirir; fiyat değişiklikleri `auditLogs`'a yazılır.
- **Tükendi** işaretleme internetsiz çalışır (`markSoldOut` yetkisi: barista, mutfak, kasa, müdür, yönetici).
  Garson ekranında **⛔ Tükendi** düğmesinden de yapılır.
- **Toplu Fiyat** ile seçili kategorilere yüzde/tutar zam uygulanır; önce önizleme gösterilir.

## Salon ve masa planı

Yönetim paneli → Tanımlamalar → **Masa / Bölgeler**:

- Bulutta plan yoksa **"Buluta Aktar"** ile NexPOS'taki bölgeler ve masalar bir kez aktarılır.
- Masalar sürükle-bırakla yerleştirilir, köşeden boyutlandırılır, 90° döndürülür; dekor öğeleri
  (bar tezgâhı, duvar, kapı, bitki) eklenebilir. Plan **"Planı Kaydet"** ile tek seferde buluta gider;
  aynı anda başkası kaydettiyse uyarı verilir.
- Her masanın QR kodu vardır: **Bölgenin tümü** ya da **Seçilileri yazdır** A4'e 6'lı etiket PDF'i üretir.
  **QR yenile** eski etiketi geçersiz kılar.
- QR adresi ve etiketteki kafe adı **Ayarlar → Genel Ayarlar**'dan değiştirilir (varsayılan
  `https://<proje>.web.app/masa`).
- Garson ekranında **Plan / Liste** görünümü arasında geçilir; plan görünümünde boş masaya sağ tıklayıp
  **Rezerve et** seçilebilir.

## Sipariş ve ödeme

- Garson masaya dokununca tam ekran sipariş ekranı açılır. Seçenekli ürünlerde (boy, süt, ekstra)
  seçenek penceresi çıkar; tükenen ürün ve seçenek eklenemez.
- Ürünler önce adisyonda **bekler**; **Gönder** ile bar ve mutfak fişlerine bölünüp gider.
  Fişler **Fiş Panosu**'nda (Yeni → Hazırlanıyor → Hazır) görünür.
- Gönderilmiş ürünün iptali (`voidItem`), ikram (`comp`) ve iskonto (`discount`) yetki ister;
  yetkisi olmayan garson için yetkili PIN onayı açılır. Hepsi `auditLogs`'a yazılır.
- Ödeme yöntemleri: Nakit (para üstü hesaplanır), Kredi Kartı ve Yemek Kartı (isteğe bağlı bahşiş).
  Kısmi ödeme alınabilir; kalan tutar adisyonda açık kalır.
- Masa taşıma, masaları birleştirme, hesap isteme ve **masasız sipariş** (gel-al / paket) vardır.
- Adisyon numaraları terminal harfi + günlük sıra numarasıdır (`A47`); gün 05:00'te döner.
- Her şey internetsiz çalışır; işlemler internet gelince buluta gider ve sunucu toplamları yeniden
  hesaplar. Terminalin fiyatı menüden farklıysa `price_mismatch` kaydı düşer.
- NexPOS'un eski sürümünde açık kalmış adisyonlar ilk açılışta bir kez yeni yapıya taşınır.

## Modüller (Ayarlar → Modüller)

Yalnızca Yönetici açıp kapatır; ayar bulutta tutulur ve bütün cihazlara iner. Modül kapatmak veri silmez.

- **Mutfak / Bar Ekranı (KDS):** sarı/kırmızı gecikme eşikleri (varsayılan 10/20 dk) ve ses.
- **Zorunlu kasa açılışı:** kasa açılmadan nakit alınmaz; kapanışta bu tutarı aşan fark gerekçe ister.
- **Bilgi fişi yazdırma:** "Hesap İste"de adisyon basılır; istenirse mutfak/bar fişi de. Yazıcı her
  bilgisayarda **Ayarlar → Yazıcı Ayarları**'ndan seçilir; yazıcı yoksa PDF `fisler/` klasörüne kaydedilir.
  Bu fişlerin mali değeri yoktur (ÖKC / e-Arşiv bu kapsamda değildir).
- **Ödeme yöntemleri ve bahşiş.**

## Kasa

- **Kasa** sayfası (yönetim panelinde İşlemler → Kasa; kasiyerde üstteki **Kasa** sekmesi): açılış
  nakdi, para girişi/çıkışı (nakit gider Masraflar'a da yazılır), **X raporu** (ara) ve **kapanış (Z)**.
  Kapanışta sayılan nakit girilir; beklenen nakitle farkı rapora ve buluta yazılır. Sunucu beklenen nakdi
  kendi kayıtlarından yeniden hesaplar.
- Ödeme penceresinde **Tamamı / Eşit böl / Ürün seç**. Ürün seçerken birden fazla adetli satırın bir
  kısmı seçilebilir (3 latteden 1'i); ödenen satır ikinci kez ödenemez.
- **İade:** Kasa → Bugünün Adisyonları → İade Et (`refund` yetkisi ve gerekçe).
- Kasa işlemleri `cash` yetkisi ister; yetkisi olmayana yetkili onayı penceresi açılır. Hepsi internetsiz çalışır.

## Ana Sayfa ve Raporlar

- **Ana Sayfa:** bugünün cirosu, adisyon sayısı ve ortalaması (geçen haftanın aynı günü, aynı saatine göre),
  açık masalar, kasa, saatlik satış grafiği, en çok satanlar ve uyarılar (iptal/ikram/iskonto, kasa farkı,
  gönderilemeyen işlem). Uyarıya tıklayınca ilgili rapora gidilir.
- **Raporlar → Satış ve Diğer Raporlar:** dönem seçilir (bugün … geçen ay, özel aralık), önceki dönemle
  karşılaştırılır. Sekmeler: Satış Özeti (KDV dökümü dahil), Ürünler (kategori, seçenek, satılmayanlar),
  Saatler ve Günler (ısı haritası), Personel, Kayıp ve Denetim, Gelir – Gider, Mutfak. Her sekme CSV
  (Excel'de açılır) ve PDF olarak kaydedilir.
- Raporlar bu bilgisayardaki kayıtlardan hesaplanır, internetsiz çalışır ve kasa Z raporuyla aynı hesabı kullanır.
  Günlük özet ayrıca buluta (`dailyStats`) yazılır; ileride telefondan rapor bakmak için.
- Garson **Vardiyam** düğmesiyle bugünkü kendi cirosunu, bahşişini ve işlemlerini görür.

## Stok ve reçete

1. **Ayarlar → Modüller → Stok ve reçete**'yi açın.
2. **İşlemler → Stok / Malzemeler → Hazır şablon**: menüdeki ürün adlarına göre yaygın malzemeler, reçeteler ve
   seçenek etkileri (yulaf sütü, büyük boy, ekstra shot) eklenir. Miktar ve fiyatları kafeye göre düzeltin.
3. **Stok gir / ilk sayım** ile eldeki miktarları girin (koli, kg ya da L olarak da girilebilir).
4. Bundan sonra her ürün **Gönder** denince reçetesi stoktan düşer. Gönderilmiş ürün iptal edilirken
   "Hazırlandı mı?" sorulur; hazırlanmadıysa stoğa döner.
5. Reçeteler ürün penceresindeki **Reçete** sekmesinden, seçenek etkileri **Seçenek Grupları**'ndan düzenlenir;
   pencerede maliyet, kâr ve marj anında görünür.
6. Raporlarda ürün maliyeti/kâr sütunları, **Menü Analizi** sekmesi ve Gelir–Gider'de ürün maliyeti çıkar.
   Kritik seviyenin altındaki malzemeler Ana Sayfa'da uyarı olarak görünür.

## Mutfak / bar ekranı (tablet)

1. **Ayarlar → Modüller**'de "Mutfak / Bar Ekranı"nı açın.
2. **Terminaller → Mutfak Ekranı Ekle**: 6 haneli, 10 dakika geçerli bir kod çıkar.
3. Tablette `https://<proje>.web.app/mutfak` adresini açın (ana ekrana ekleyebilirsiniz), kodu girin,
   istasyonu seçin (Mutfak / Bar / İkisi). Eşleme tablette kalır; yeniden açınca kod sorulmaz.
4. Fişler canlı düşer: **Başla → Hazır**, satıra dokununca işaretlenir, iptal edilen ürün "İPTAL" görünür,
   **Geri al** son kapatılanı döndürür. Hazır olan fiş kasada 🔔 bildirimi olarak çıkar; garson Fiş
   Panosu'nda **Teslim edildi** deyince kalkar.
5. Tablet kaybolursa **Terminaller**'den iptal edin; ekran hemen kilitlenir. Tablet yalnızca fişleri
   okuyabilir; personel, PIN ve satış verisine erişemez.
6. İnternet kesilirse tablet yeni fiş alamaz; kasa uyarı verir ve fişler **Fiş Panosu**'nda izlenir.

## Geliştirme: emülatörle çalışma

Canlı veriye dokunmadan denemek için:

```bash
cd firebase && firebase emulators:start --project demo-nexpos --only auth,firestore,functions,storage,hosting
# mutfak ekranı: http://127.0.0.1:5005/mutfak
# başka bir terminalde:
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 GCLOUD_PROJECT=demo-nexpos \
  node firebase/functions/scripts/createOwner.js sahip@kafe.test sahip-sifre-1 "Deniz Yılmaz" 482913
NEXPOS_EMULATOR=1 python main.py
```

## Testler

```bash
# Fonksiyon birim testleri
cd firebase/functions && npm test
# Kurallar + fonksiyonlar (emülatör)
cd firebase/tests && npm install && npm test
# NexPOS yerel testleri
pip install -r requirements-dev.txt && python -m pytest tests
# NexPOS ↔ Firebase uçtan uca (emülatör)
cd firebase && firebase emulators:exec --project demo-nexpos --only auth,firestore,functions,storage \
  "cd .. && NEXPOS_EMULATOR=1 python -m pytest tests"
# Mutfak ekranı tarayıcıda (Playwright + Chromium)
cd firebase && firebase emulators:exec --project demo-nexpos --only auth,firestore,functions,hosting \
  "node tests/kds.browser.js"
```
