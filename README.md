<div align="center">

# NexPOS — Kafe & Restoran Yönetim Sistemi

**Python · PySide6 · SQLite · Firebase · OOP**

Kafe ve restoran işletmelerinin masa takibi, sipariş yönetimi, finansal raporlama ve personel yetkilendirme süreçlerini tek bir merkezden yöneten masaüstü otomasyon yazılımı.

</div>

---

## İçindekiler

- [Özellikler](#özellikler)
- [Teknolojiler](#teknolojiler)
- [Dosya Yapısı](#dosya-yapısı)
- [Kurulum](#kurulum)
- [Kullanım](#kullanım)
- [İlk Kurulum ve Giriş](#i̇lk-kurulum-ve-giriş)
- [Proje Ekibi](#proje-ekibi)

---

## Özellikler

### Garson Paneli
- Salon, Teras, Bahçe gibi bölgelere ayrılmış masa görünümü — dolu/boş durumu renk kodlu kartlarla anlık takip
- Ürün arama ve kategori filtreleme ile hızlı sipariş oluşturma
- Sipariş notu ekleme ("az şekerli", "allerji var" vb.)
- İskonto uygulama (yüzde bazlı, anlık net tutar önizlemesi)
- Masa transfer — aktif siparişi başka bir masaya taşıma
- Sipariş panosu: Mutfakta / Hazır aşamalarını gerçek zamanlı takip
- Vardiyam — mesaiye başla/bitir, mola, haftalık plan ve çalışılan saat, günün satışı
- Nakit / Kredi Kartı / Yemek Kartı ödeme; hesabı eşit bölme ya da ürün seçerek bölme
- Kasa: açılış, para giriş/çıkışı, X ve Z raporu (KDV dökümü, personel, kasa farkı), iade
- Bilgi fişi (adisyon), mutfak/bar fişi ve rapor yazdırma; yazıcı yoksa PDF
- Mutfak / bar ekranı: tablette çalışan web sayfası, fişler canlı düşer, hazır olunca kasada 🔔

### Yönetici Paneli
- Ana sayfa: bugünün cirosu geçen haftanın aynı saatine göre, saatlik satış, en çok satanlar, uyarılar
- Masa ve bölge yönetimi — yeni bölge/masa ekleme, mevcut masaları düzenleme
- Menü yönetimi — kategori ve ürün ekleme/düzenleme/silme (soft-delete, geçmiş siparişler korunur)
- Kullanıcı yönetimi — personel ekleme, rol atama, aktif/pasif durumu
- Yetkilendirme matrisi — Garson, Kurye, Kasa, Müdür, Yönetici rolleri için işlem bazlı izin yönetimi
- Vardiya planı (şablon, izin, 45 saat uyarısı, yayınla, PDF/WhatsApp) ve mesai raporu (geç, gelmedi, fazla mesai, işçilik maliyeti)
- Gider / Masraf takibi — tarih filtreli listeleme ve özet
- Zayi yönetimi — bozulan veya hatalı üretilen ürünlerin stoktan düşülmesi
- Raporlar — satış özeti ve KDV dökümü, ürün/seçenek, saat ısı haritası, personel, kayıp ve denetim, gelir-gider, mutfak; CSV ve PDF
- CSV dışa aktarma
- Ctrl+B ile tek tıkla veritabanı yedekleme

### Bulut ve Güvenlik (v4)
- Veriler Firebase'de; kafedeki bilgisayar bir **terminal** olarak bağlanır ([KURULUM.md](KURULUM.md))
- **İnternetsiz çalışma:** işlemler yerel kuyruğa yazılır, internet gelince otomatik gönderilir
- **PIN ile giriş:** personel kartına dokun + 6 haneli PIN; 5 hatalı denemede kart kilitlenir
- **Yetkili onayı:** yetkisiz işlemde (iskonto, iptal) müdür PIN'i istenir, kayıt altına alınır
- **Gerçek yetki matrisi:** buluta kaydedilir, hem ekranlarda hem sunucuda uygulanır
- Hareketsizlikte otomatik ekran kilidi, panelden terminal iptali

### Teknik
- Rol tabanlı erişim kontrolü (RBAC) — her kullanıcı yalnızca kendi panelini görür
- PIN'ler sunucuda scrypt ile özetlenir; şifreler Firebase Authentication'da tutulur
- QTimer ile 30 saniyelik otomatik masa doluluk güncelleme
- Global crash handler — beklenmedik hatalar `crash_log.txt`'e yazılır
- Tüm veritabanı işlemleri Foreign Key kısıtlı, cascade-safe

---

## Teknolojiler

| Bileşen | Teknoloji |
|---|---|
| Programlama Dili | Python 3.10+ |
| GUI Framework | PySide6 (Qt for Python) |
| Bulut | Firebase (Firestore, Authentication, Cloud Functions) |
| Yerel veritabanı | SQLite 3 (önbellek + çevrimdışı işlem kuyruğu) |
| Mimari | Nesne Yönelimli Programlama (OOP) |
| Stil | QSS (Qt Style Sheets) |

---

## Dosya Yapısı

```
nexpos/
├── main.py            # Uygulama giriş noktası — eşleme → giriş → panel, senkron, otomatik kilit
├── database.py        # Yerel veritabanı: CRUD, PIN girişi, bulut önbelleği, işlem kuyruğu
├── login_screen.py    # Personel kartları + PIN ile giriş, yönetici e-posta girişi
├── pairing_screen.py  # İlk kurulum: bilgisayarı kafeye (Firebase) bağlama
├── auth_widgets.py    # PIN tuş takımı, personel kartı, senkron durum etiketi
├── access.py          # Yetkili onayı ve panel işlemleri için yönetici oturumu
├── admin_access_pages.py  # Kullanıcılar, Yetki Matrisi, Terminaller sayfaları
├── cloud/             # Firebase REST istemcisi, senkron motoru, terminal eşleme
├── firebase/          # Firestore kuralları, Cloud Functions ve emülatör testleri
├── docs/              # Mimari ve veri modeli
├── tests/             # pytest testleri
├── admin_panel.py     # Yönetici paneli (dashboard, ürün, masa, kullanıcı, raporlar)
├── user_panel.py      # Garson paneli (masa seçimi, sipariş, pano, ödeme)
├── widgets.py         # Özel UI bileşenleri (TableCard, OrderCard, StatCard, ToastNotification)
├── styles.py          # Merkezi renk paleti, font ve QSS stil tanımları
├── requirements.txt   # Bağımlılık listesi
├── nexpos.db          # SQLite veritabanı — demo verilerle birlikte
└── Brew_Flow_NexPOS_Uygulama_Kullanim_Kilavuzu.docx   # Kullanım kılavuzu
```

> `nexpos.db` repoda demo verilerle hazır gelir. Silinirse, uygulama ilk çalıştırmada veritabanını ve demo verileri otomatik olarak yeniden oluşturur.

---

## Kurulum

Uygulamayı iki şekilde çalıştırabilirsiniz.

### Seçenek 1 — Hazır uygulama (Windows .exe)

Python kurulumu **gerektirmez**. Derlenmiş `.exe` dosyası boyutu nedeniyle GitHub'a yüklenememiştir; aşağıdaki bağlantıdan indirebilirsiniz:

**İndirme bağlantısı:** [NexPOS.exe (OneDrive)](https://ogrencibartinedu-my.sharepoint.com/:f:/g/personal/23010708021_ogrenci_bartin_edu_tr/IgAKcNJudmblRr6V15mGF9mPAeqAXTiwDJrx3Gekjient5U?e=XZ0yuz)

İndirdikten sonra dosyaya çift tıklayarak çalıştırın. Uygulama, içindeki `nexpos.db` veritabanıyla birlikte gelir; bu nedenle mevcut veriler korunur. Veritabanı dosyası silinse veya bulunamasa bile, uygulama ilk açılışta veritabanını ve demo verileri otomatik olarak oluşturur.

### Seçenek 2 — Kaynaktan çalıştırma (Python)

**Gereksinimler:** Python **3.10** veya üzeri ([indir](https://www.python.org/downloads/)) ve pip

**1. Repoyu klonlayın**

```bash
git clone https://github.com/aligungorr/nexpos.git
cd nexpos
```

**2. Bağımlılıkları yükleyin**

```bash
pip install -r requirements.txt
```

Yalnızca `PySide6` kurulması yeterlidir. Diğer modüller (`sqlite3`, `hashlib`, `json`, `datetime` vb.) Python standart kütüphanesinde yer almaktadır.

**3. Uygulamayı başlatın**

```bash
python main.py
```

Bu yöntemde de `nexpos.db` veritabanı mevcutsa kullanılır; silinmişse veya hiç yoksa ilk çalıştırmada otomatik olarak oluşturulur. Herhangi bir ek yapılandırmaya gerek yoktur.

---

## Kullanım

Uygulama başlatıldığında personel kartları görünür. Kişi kartına dokunup 6 haneli PIN'ini girer; rolüne göre yönlendirilir:

- **Yönetici / Müdür** → Admin Paneli (oradan "Sipariş (Garson Ekranı)" ile garson paneline geçebilir)
- **Kasa / Garson / Kurye / Barista / Mutfak** → Garson Paneli

### Temel İş Akışı (Garson)

```
Kartına dokun + PIN → Bölgeler → Masa Seç → Sipariş Oluştur → Mutfağa Gönder → Ödeme Al → Masa Kapandı
```

### Temel İş Akışı (Yönetici)

```
Giriş → Dashboard → Tanımlamalar (Masa / Menü) → Raporlar → Kullanıcı Yönetimi
```

---

## İlk Kurulum ve Giriş

Demo e-posta/şifre hesapları kaldırıldı. Kurulum adımları [KURULUM.md](KURULUM.md) dosyasındadır:

1. Firebase projesi açılır, kurallar ve fonksiyonlar yayınlanır.
2. `createOwner.js` ile ilk yönetici oluşturulur.
3. NexPOS ilk açılışta yönetici hesabıyla kafeye bağlanır.
4. Personel panelden eklenir; herkes kendi kartı ve PIN'i ile giriş yapar.

---

## Proje Ekibi

| İsim | Öğrenci No |
|---|---|
| Ali Güngör | 23010708021 |
| Emirhan Yusuf Arslan | 22640708002 |

---

<div align="center">

Bu proje **Görsel Programlama II** dersi kapsamında akademik amaçla geliştirilmiştir.

**Bartın Üniversitesi · 2025–2026**

</div>
