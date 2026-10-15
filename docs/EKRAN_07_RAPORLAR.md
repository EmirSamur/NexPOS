# 7. Ekran: Ana Sayfa (Gösterge Paneli) ve Raporlar

> Durum: **uygulandı.** Sorulara verilen cevaplar (hepsi öneri yönünde): günlük özet buluta yazılıyor
> (telefonda görme sayfası sonra), eski NexPOS satışları "eski kayıt" olarak görünüyor, dışa aktarma CSV + PDF,
> garson "Vardiyam"da kendi cirosunu ve bahşişini görüyor.
>
> Uygulamada netleşenler:
> - Hesaplar `reports.py`'de; kasa Z raporu KDV ve iskonto dağıtımında aynı fonksiyonları kullanıyor.
> - Sunucudaki `src/stats.js` aynı "katkı" hesabını yapıyor; ortak adisyon senaryolarındaki her adisyon için iki
>   dilin sonucu testte birebir karşılaştırılıyor, emülatörde de bulut özeti yerel raporla aynı çıkıyor.
> - İptal/ikram/iskonto satırlarına işlem saati (`actionAt`, `discount.at`) eklendi; denetim listesi bunu gösterir.
> - Tablolar sütun başlığına tıklanarak sıralanır; varsayılan: ürün ve personel ciroya göre, denetim en yeni üstte.
> - Kayıp ve Denetim sekmesini yalnızca Yönetici ve Müdür görür.

## Bugünkü durum ve sorun

- **Ana Sayfa** ve **İstatistikler** sayfası eski NexPOS tablolarından (`orders`, `order_items`) okuyor.
  Bu tablolarda iskonto, ikram, iptal, ödeme yöntemi, bahşiş, KDV ve iade **yok**. Bu yüzden rakamlar
  eksik ve kasa Z raporuyla tutmuyor.
- Sabit "son 30 gün" var; tarih seçilemiyor, dönem karşılaştırması yapılamıyor.
- Garsonun "Vardiyam" penceresi eski tabloya bakıyor.

7. ekranda bütün raporlar yeni adisyon kaydından (`pos_orders`: satırlar, iskonto, ödemeler, iadeler)
hesaplanır. Kasa Z raporuyla **aynı hesap fonksiyonları** kullanılır; böylece iki ekran aynı günü
asla farklı göstermez.

---

## 7.1 Ana Sayfa (Bugün)

Panel açılınca ilk görülen sayfa. Her 30 saniyede bir ve her senkronda tazelenir.

```
┌ Bugün · Çarşamba 15 Ekim (gün 05:00'te döner) ────────────────────────────────────────────┐
│ ┌ Ciro ─────────┐ ┌ Adisyon ──────┐ ┌ Ortalama ─────┐ ┌ Açık masa ────┐ ┌ Kasa ─────────┐  │
│ │ 12.480 ₺      │ │ 96            │ │ 130 ₺         │ │ 7 / 24        │ │ 🟢 Açık        │  │
│ │ ▲ %8 geçen    │ │ ▲ %5          │ │ ▲ %3          │ │ 1.840 ₺ açık  │ │ Beklenen      │  │
│ │ Çarşamba'ya   │ │               │ │               │ │ hesapta       │ │ 3.240 ₺       │  │
│ └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘  │
│ Saatlik satış (bugün ▇ / geçen hafta aynı gün ┈)        En çok satanlar (bugün)            │
│  ▁▂▅▇▆▃▂▃▅▇█▆▃                                         1. Latte          42 adet           │
│ 08 10 12 14 16 18 20 22                                 2. Türk Kahvesi   31 adet           │
│                                                         3. Cheesecake     18 adet ...       │
│ Dikkat edilecekler                                      Mutfak (KDS açıksa)                 │
│  ⚠ 3 iptal (360 ₺) · 6 ikram (410 ₺) · iskonto 340 ₺     Ortalama hazırlama: bar 4 dk,      │
│  ⚠ Kasa farkı dün: −40 ₺ (gerekçe: bozuk para)          mutfak 11 dk · geciken fiş: 2      │
│  ⚠ 2 işlem buluta gönderilemedi → Terminaller           │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

- Karşılaştırma **geçen haftanın aynı günü, aynı saatine kadar** yapılır (pazartesiyi pazarla
  karşılaştırmak yanıltır; saat 14:00'te bütün günle karşılaştırmak da yanıltır).
- "Dikkat edilecekler" kartları tıklanınca ilgili rapora (Kayıp/Denetim, Kasa, Terminaller) gider.
- Kapalı modülün kartı görünmez (kasa oturumu, mutfak).

## 7.2 Raporlar

Üstte dönem seçici: **Bugün · Dün · Bu hafta · Geçen hafta · Bu ay · Geçen ay · Özel aralık**.
"Önceki dönemle karşılaştır" açıkken her rakamın yanında % değişim görünür. Her sekme **CSV**
(Excel açar) ve **PDF** olarak dışa aktarılır.

### Sekme 1: Satış Özeti
```
Brüt satış (KDV dahil)     58.400 ₺
 − İskonto                 −1.620 ₺   (54 adisyon)
 − İade                      −310 ₺   (4 iade)
 = Net satış               56.470 ₺   ▲ %6
İkram (satışa dahil değil)  2.140 ₺   (31 ürün)
İptal (satışa dahil değil)  1.380 ₺   (17 ürün)
Bahşiş                        980 ₺
Ödeme: Nakit 14.200 · Kart 38.900 · Yemek Kartı 3.370
KDV:   %10 matrah 51.200 → 4.654,55 · %20 matrah 5.270 → 878,33 · %1 …
Adisyon 442 · ortalama 127,76 ₺ · masa 361 / paket 81
```
- **KDV dökümü** muhasebeciye gidecek tablodur (oran başına KDV dahil tutar, matrah, KDV).
  ⚠️ Bilgi amaçlıdır; resmi kayıt ÖKC/e-Arşiv'dir.

### Sekme 2: Ürünler ve Kategoriler
- Ürün başına adet, ciro, ciro payı, ikram ve iptal adedi; sıralanabilir tablo.
- Kategori toplamları (çubuk grafik).
- **Seçenekler:** hangi seçenek kaç kez seçildi ve ne kadar ek gelir getirdi
  (ör. "Yulaf sütü: 120 kez, +1.800 ₺").
- **Hiç satılmayan ürünler** (dönem içinde): menüden çıkarma adayı.
- Maliyet ve kâr sütunları 8. ekranda (reçete) gelir; şimdilik boş durur.

### Sekme 3: Saatler ve Günler
- Gün × saat ısı haritası (ciro ya da adisyon sayısı): yoğun saatler ve personel planı için.
- Haftanın günlerine göre ortalama ciro.

### Sekme 4: Personel
```
Personel     Adisyon  Ciro      Ortalama  İskonto  İkram  İptal  Bahşiş
Cem Akar     121      15.840 ₺  130 ₺     4        6      2      310 ₺
Elif Demir   ...
```
- Ciro, adisyonu açan garsona yazılır. İskonto/ikram/iptal hem **yapan** hem **onaylayan** olarak
  sayılır (kim kimin işlemini onaylıyor görülür).
- Garsonun **"Vardiyam"** penceresi aynı hesabın yalnızca kendi satırını gösterir.

### Sekme 5: Kayıp ve Denetim
Dönemdeki her iptal, ikram, iskonto, iade, adisyon iptali, kasa farkı ve fiyat uyuşmazlığı satır
satır listelenir: **saat · adisyon · ürün/tutar · yapan · onaylayan · gerekçe**. Filtrelenir
(türe ve personele göre). Hırsızlık ve kötüye kullanımı fark etmenin asıl aracı budur.

### Sekme 6: Gelir – Gider
```
Net satış                 56.470 ₺
 − Giderler (Masraflar)   −9.820 ₺   (nakit 4.100 · diğer 5.720)
 − Zayi                     −640 ₺
 = Kalan                  46.010 ₺   (ürün maliyeti 8. ekranla düşülecek)
```

### Sekme 7: Mutfak (KDS modülü açıksa)
- İstasyon ve ürün başına ortalama hazırlama süresi (gönderme → hazır), geciken fiş oranı (kırmızı eşiği aşan).

> Kasa oturumları ve Z raporları zaten **Kasa → Geçmiş Oturumlar**'da; raporlar sayfasından oraya bağlantı verilir.

---

## 7.3 Veri: nereden okunur?

- **Bu bilgisayar (NexPOS):** raporlar yerel adisyonlardan hesaplanır → **internetsiz çalışır**, anında açılır.
  Hesaplar tek bir modülde (`reports.py`) toplanır; kasa Z raporu da bu modülü kullanacak şekilde
  düzenlenir.
- **Bulut (`dailyStats/{iş günü}`):** sunucu, ödeme/iade/iptal geldikçe günlük özeti günceller
  (ciro, yöntemler, KDV, saatler, ürünler, personel, iskonto/ikram/iptal). Bu, ileride **telefondan
  rapor bakmak** ve birden fazla kasa için hazırlıktır. NexPOS'un yerel rakamı ile buluttaki rakam
  otomatik testlerde karşılaştırılır.
- **Eski NexPOS kayıtları** (yeni sisteme geçmeden önceki satışlar): yalnızca toplam ciro ve ürün adedi
  vardır. Raporlarda "eski kayıt" olarak ayrı satırda gösterilir, ayrıntı sütunları boş kalır.
- Gün dönümü 05:00 (gece yarısından sonraki satış önceki iş gününe yazılır), kasa ile aynı.

## 7.4 Yetkiler

- Ana Sayfa ve Raporlar: `viewReports` (varsayılan: Yönetici, Müdür).
- "Vardiyam": herkes, yalnızca kendi satırı.
- Kayıp ve Denetim sekmesi: Yönetici ve Müdür (`viewReports` + panel rolü).

## Sorular

1. **Telefondan rapor:** Siz kafede değilken günün cirosunu telefondan görmek ister misiniz? İsterseniz
   bulut özeti (`dailyStats`) şimdi yazılır, görüntüleme sayfası 11. ekranda (ya da ayrı küçük bir web
   sayfasıyla) gelir. *Önerim: özet şimdi buluta yazılsın, sayfası sonra.*
2. **Eski NexPOS satışları** raporlarda "eski kayıt" olarak görünsün mü, yoksa raporlar yeni sisteme
   geçiş gününden mi başlasın? *Önerim: görünsün.*
3. **Dışa aktarma:** CSV + PDF yeterli mi, yoksa gerçek Excel dosyası (.xlsx) da ister misiniz?
   *Önerim: CSV + PDF (CSV Excel'de açılır).*
4. **Vardiyam:** Garson kendi cirosunu ve bahşişini görsün mü? *Önerim: evet.*

## "Bitti" sayılma ölçütü

- [x] Ana Sayfa bugünün rakamlarını, geçen haftanın aynı saatine göre karşılaştırmasını, saatlik grafiği,
      en çok satanları ve uyarıları gösteriyor; internetsiz çalışıyor
- [x] Dönem seçici ve önceki dönem karşılaştırması bütün sekmelerde çalışıyor
- [x] Satış özeti ve KDV dökümü, aynı dönemin kasa Z raporlarının toplamıyla kuruşu kuruşuna tutuyor (otomatik test)
- [x] Ürün, seçenek, saat ısı haritası, personel, kayıp/denetim, gelir-gider ve mutfak sekmeleri doğru
- [x] CSV ve PDF dışa aktarma
- [x] Bulut günlük özeti (`dailyStats`) yerel hesapla aynı (emülatör testi)
- [x] "Vardiyam" yeni hesapla, yalnızca kendi satırı
- [x] Eski NexPOS kayıtları seçilen şekilde görünüyor
