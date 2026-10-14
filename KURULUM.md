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
firebase deploy --only firestore,functions,storage
```

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

## Geliştirme: emülatörle çalışma

Canlı veriye dokunmadan denemek için:

```bash
cd firebase && firebase emulators:start --project demo-nexpos --only auth,firestore,functions,storage
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
```
