# 8. Ekran: Stok, Reçete ve Tedarik

> Durum: **uygulandı** (8a ve 8b). Sorulara verilen cevaplar (hepsi öneri yönünde): stok Gönder'de düşer;
> iptalde "Hazırlandı mı?" sorulur (Modüller'den kapatılabilir); maliyet ağırlıklı ortalama (alışlar 8b'de);
> malzeme bitince ürün tükendi yapılmaz, yalnızca uyarı; tedarikçi borç bakiyesi 8b'de; hazır şablon var.
>
> Uygulamada netleşenler:
> - Miktarlar temel birimde tam sayı (g, ml, adet); birim maliyet kg / L / adet başına kuruş.
> - Seçenek etkileri sırası: yerine koy → çarp → ekle. Çarpan adetli malzemelere (bardak) uygulanmaz.
> - Stok modülü kapalıyken gönderilmiş ürün sonradan iptal edilirse stoğa iade yazılmaz (düşülmemişti).
> - Silinmiş malzemeye ait hareket satırı sunucuda atlanır, hareket yine kaydedilir.
> - Reçetede kullanılan malzeme silinemez.
> - Maliyet ve kâr güncel birim maliyetlerle hesaplanır; ürün penceresinde ve raporlarda yalnızca
>   `viewReports` yetkisi olan görür.
> - 8b: tedarikçi ve sipariş taslağı bulutta düzenlenir (internet ister); teslim alma, tedarikçi ödemesi,
>   sayım ve zayi internetsiz yapılır ve kuyrukla gider. Teslimde birim maliyet kasada hemen, sunucuda aynı
>   formülle güncellenir. Kasa açıkken nakit ödeme kasadan çıkış olarak düşer ve `cash` yetkisi ister.
> - İlk sayım (hiç sayım yokken yapılan) kayıp sayılmaz; sonraki sayımların farkı tüketim raporunda görünür.
> - Gönderilmiş ürün bölünüp ana parçası hazırlanmadan iptal edilirse güncel adedi kadar stoğa döner.

## Amaç

Satılan her ürün, reçetesindeki malzemeleri stoktan **kendiliğinden** düşsün. Böylece:

- Ne kadar süt, çekirdek, şurup kaldığı her an bilinir; azalan malzeme için uyarı çıkar.
- Her ürünün **maliyeti ve kârı** hesaplanır; Raporlar'daki boş maliyet/kâr sütunları dolar.
- Sayımda "olması gereken" ile "olan" karşılaştırılır; fire, israf ve kaçak görünür hâle gelir.
- Tedarikçiye sipariş, teslim alma ve alış fiyatları tek yerden yönetilir.

Bugün NexPOS'ta yalnızca **Zayi** sayfası var: ürün adı, adet ve elle yazılan maliyet. Stok yok.

Stok da bir **modül**dür (Ayarlar → Modüller → "Stok ve reçete"). Kullanmak istemeyen kafe kapatır;
kapalıyken hiçbir şey stoktan düşmez ve Stok menüsü görünmez.

---

## 8.1 Malzemeler (Stok → Malzemeler)

```
┌ Malzemeler ─────────────────────────────────────── [+ Malzeme] [Excel'den aktar] ┐
│ Ara: [          ]  Filtre: (•) Hepsi  ( ) Kritik  ( ) Biten                        │
│ Malzeme              Stok        Kritik    Birim maliyet   Stok değeri  Tedarikçi  │
│ ⚠ Süt (tam yağlı)     3,2 L      10 L      32,00 ₺/L        102,40 ₺    Ak Süt     │
│ Espresso çekirdeği    4,8 kg     2 kg      780,00 ₺/kg    3.744,00 ₺    Kahveci    │
│ Yulaf sütü            6 L        4 L       95,00 ₺/L        570,00 ₺    Kahveci    │
│ Karton bardak 12oz    840 adet   200 adet  1,80 ₺/adet    1.512,00 ₺    Ambalajcı  │
│ ...                                                        Toplam: 48.210,00 ₺     │
└───────────────────────────────────────────────────────────────────────────────────┘
```

- **Birim:** g, ml ya da adet (stok bu birimde tutulur). Ekranda okunaklı gösterilir: 3200 ml → "3,2 L".
- **Alış birimi:** Tedarikçiden nasıl geliyor? "1 koli = 12 L", "1 paket = 1 kg". Alışta koli girilir,
  stok ml olarak artar.
- **Kritik seviye:** Altına düşünce Ana Sayfa'da ve listede ⚠ uyarı. **Hedef seviye** (isteğe bağlı):
  sipariş önerisinde "hedefe tamamla" miktarı.
- **Birim maliyet:** Alışlarla kendiliğinden güncellenir (bkz. 8.5); ilk kurulumda elle girilir.

## 8.2 Reçete (Menü → Ürün düzenle → "Reçete" sekmesi)

```
┌ Latte · Reçete ───────────────────────────────────────────────────────────┐
│ Malzeme              Miktar                                Maliyet        │
│ Espresso çekirdeği   18 g                                   14,04 ₺       │
│ Süt (tam yağlı)      200 ml                                  6,40 ₺       │
│ Karton bardak 12oz   1 adet   (yalnızca paket siparişte)     1,80 ₺       │
│ [+ Malzeme]                                                                │
│ Seçeneklere göre:                                                          │
│   Süt → Yulaf sütü:  Süt −200 ml, Yulaf sütü +200 ml       +12,60 ₺       │
│   Boy → Büyük:       bütün reçete ×1,5                                     │
│   Ekstra shot:       Espresso çekirdeği +9 g                 +7,02 ₺       │
│ ───────────────────────────────────────────────────────────────────────── │
│ Maliyet 20,44 ₺ · Satış 95,00 ₺ (KDV hariç 86,36 ₺) · Kâr 65,92 ₺ · %76   │
└───────────────────────────────────────────────────────────────────────────┘
```

- Reçetesi olmayan ürün stoktan bir şey düşürmez (ör. hazır alınan şişe su için malzeme = ürünün kendisi:
  "Su 0,5 L × 1 adet").
- Bir malzeme **yalnızca paket siparişte** düşebilir (bardak, kapak, poşet).
- Seçenekler reçeteyi değiştirir: **yerine koy** (süt → yulaf), **ekle** (ekstra shot), **çarp** (büyük boy ×1,5).
- Maliyet ve kâr **KDV hariç** satış fiyatı üzerinden hesaplanır.

## 8.3 Stoktan düşme (otomatik)

- Ürün **Gönder** ile bar/mutfağa gittiğinde reçetesi stoktan düşer (hazırlanmaya başladığı an).
- **İkram** da stoktan düşer (ürün yine yapıldı); maliyeti raporda ikram maliyeti olarak görünür.
- **Gönderildikten sonra iptal:** NexPOS sorar: *"Ürün hazırlandı mı?"*
  - Hazırlandıysa → zayi olarak yazılır (stok dönmez, maliyet fire raporuna düşer).
  - Hazırlanmadıysa → stoğa geri döner.
- Her şey **internetsiz** çalışır: stok hareketleri bu bilgisayarda hemen işlenir, kuyrukla buluta gider.
- Stok **eksiye düşebilir** (satış durdurulmaz). Eksi stok, sayım ya da alış girilmediğinin işaretidir;
  listede kırmızı görünür.

## 8.4 Sayım (Stok → Sayım)

```
┌ Sayım · 15 Ekim · Haftalık sayım ─────────────────────────────────────────────┐
│ Malzeme              Sistemde    Sayılan     Fark          Fark tutarı        │
│ Süt (tam yağlı)      3,2 L       [ 2,4 L ]   −0,8 L  ⚠     −25,60 ₺           │
│ Espresso çekirdeği   4,8 kg      [ 4,75 kg]  −0,05 kg       −39,00 ₺           │
│ Karton bardak 12oz   840 adet    [ 840   ]   0               0,00 ₺           │
│ (Boş bırakılan malzeme sayılmamış sayılır, stok değişmez)                     │
│                         Toplam fark: −64,60 ₺   [Taslak kaydet] [Sayımı onayla]│
└───────────────────────────────────────────────────────────────────────────────┘
```

- Tüm malzemeler ya da bir grup (bar, mutfak, ambalaj) sayılabilir. Taslak kaydedilip sonra bitirilebilir.
- Onaylanınca stok sayılan değere eşitlenir; fark "sayım farkı" hareketi olarak kaydedilir.
- **Tutarsızlık raporu:** dönemdeki satışa göre *teorik tüketim* ile sayıma göre *gerçek tüketim*
  karşılaştırılır. ("Bu hafta 18 L süt kullanılmalıydı, 24 L kullanılmış: +6 L / 192 ₺ açık.")
- Kurulumda **ilk sayım** başlangıç stoğunu girer.

## 8.5 Tedarikçiler ve alış (Stok → Alışlar)

```
Sipariş #12 · Kahveci · Taslak
  Espresso çekirdeği   5 paket (1 kg)    780,00 ₺   3.900,00 ₺
  Yulaf sütü           2 koli (12 L)    1.140,00 ₺   2.280,00 ₺
  [Kritik malzemeleri ekle]   Toplam 6.180,00 ₺
  [PDF / yazdır]  [WhatsApp metnini kopyala]  [Gönderildi]  [Teslim al]
```

- **Sipariş önerisi:** "Kritik malzemeleri ekle" kritik altındakileri hedef seviyeye tamamlayacak miktarla,
  her malzemenin kendi tedarikçisinin siparişine ekler.
- **Teslim al:** gelen miktar ve fiyat girilir (eksik ya da farklı gelebilir; kısmi teslim olabilir). Stok artar,
  birim maliyet **ağırlıklı ortalama** ile güncellenir:
  `(eski stok × eski maliyet + gelen × alış fiyatı) / (eski stok + gelen)`.
- Teslim alırken ödeme: **Ödendi** (nakit / kart / havale) ya da **Ödenecek**. Ödenen tutar **Masraflar**'a yazılır
  (nakit ödeme açık kasadan çıkış olarak da düşer). "Ödenecek" tutarlar tedarikçinin **borç bakiyesi**nde
  birikir; sonradan "Ödeme yap" ile kapatılır.
- Siparişsiz alış da girilebilir (pazardan alınan limon gibi): doğrudan "Alış gir".

## 8.6 Zayi (mevcut sayfanın yerine)

- **Ürün zayisi:** "2 Cheesecake düştü" → reçetesi stoktan düşer, maliyet kendiliğinden hesaplanır.
- **Malzeme zayisi:** "1 L süt bozuldu" → doğrudan malzemeden düşer.
- Gerekçe zorunlu (bozuldu, düştü, son kullanma, yanlış hazırlandı, diğer). Barista ve mutfak da girebilir.
- Eski zayi kayıtları silinmez; raporlarda "eski kayıt" olarak kalır.

## 8.7 Raporlara etkisi

- **Ürünler** sekmesine **maliyet, kâr ve kâr marjı** sütunları eklenir.
- **Menü analizi:** ürünler satış adedi ve kâr marjına göre dört gruba ayrılır
  (★ yıldız: çok satan + kârlı · 🐴 iş atı: çok satan + az kârlı · 🧩 bulmaca: az satan + kârlı ·
  🐶 köpek: az satan + az kârlı) — fiyat ve menü kararları için.
- **Gelir – Gider:** "ürün maliyeti (satılan malın maliyeti)" satırı eklenir → gerçek brüt kâr.
- Yeni rapor sekmesi **Stok:** stok değeri, tüketim (malzeme bazında), zayi, sayım farkları, alışlar.
- Ana Sayfa: "⚠ 3 malzeme kritik seviyede" uyarısı.

## 8.8 Yetkiler

Yetki matrisine iki yeni satır:

| Yetki | Varsayılan |
|---|---|
| `stock` — malzeme, reçete, sayım, alış, tedarikçi | Yönetici, Müdür |
| `waste` — zayi girme | Yönetici, Müdür, Barista, Mutfak, Kasiyer |

Birim maliyet ve kâr bilgisini yalnızca `viewReports` yetkisi olan görür.

## 8.9 Veri

- Bulut: `ingredients`, `recipes` (ürün dokümanında `recipe` alanı), `stockMovements`, `suppliers`,
  `purchaseOrders`, `stockCounts`. Stok miktarı ve birim maliyeti **yalnızca fonksiyonlar** değiştirir.
- NexPOS'ta yerel kopya ve hareket defteri; satıştaki düşüm internetsiz yapılır, işlemler kuyrukla gider,
  sunucu her hareketi bir kez uygular (aynı hareket iki kez gelirse tekrar düşmez).
- Malzeme ve reçete tanımlama (menü düzenleme gibi) internet ister; satış, zayi, sayım ve teslim alma istemez.

## Uygulama sırası

Ekran büyük olduğu için iki adımda yapılır, her adım kendi başına işe yarar:

- **8a:** Modül, malzemeler, reçete ve seçenek etkileri, satışta otomatik düşme, iptal sorusu, ürün maliyeti ve
  kâr raporu, menü analizi, kritik stok uyarısı, ilk sayım.
- **8b:** Sayım ve tutarsızlık raporu, yeni zayi, tedarikçiler, alış siparişi, teslim alma ve ağırlıklı maliyet,
  tedarikçi borç bakiyesi, Stok rapor sekmesi.

## Sorular

1. **Stoktan düşme zamanı:** Ürün "Gönder" denince mi düşsün, ödeme alınınca mı?
   *Önerim: Gönder'de* (malzeme o an harcanır; ödenmeden kalkan masa da stoğu doğru düşürür).
2. **Gönderildikten sonra iptal:** "Hazırlandı mı?" sorusu sorulsun mu?
   *Önerim: evet* (hazırlandıysa zayi, değilse stoğa döner). Her iptalde sorulması garsonu yorarsa
   "her zaman zayi say" ayarı da eklenebilir.
3. **Maliyet yöntemi:** Ağırlıklı ortalama mı, son alış fiyatı mı? *Önerim: ağırlıklı ortalama*
   (fiyat dalgalandığında kâr raporu zıplamaz).
4. **Malzeme bitince** ürün kendiliğinden "tükendi" olsun mu? *Önerim: hayır, yalnızca uyarı*
   (stok sayımı hatalıysa satış gereksiz yere durur). İsteyen için ayar olarak eklenebilir.
5. **Tedarikçi borç takibi** (veresiye alış, sonradan ödeme) olsun mu? *Önerim: evet, basit bakiye* —
   ayrıntılı muhasebe yok.
6. **Başlangıç verisi:** Malzeme listesini ve reçeteleri siz mi gireceksiniz, yoksa yaygın kafe ürünleri için
   hazır bir şablon (espresso bazlı içecekler, çaylar, tatlılar) önerelim mi? *Önerim: şablon* — üzerinden
   düzenlenir.
7. **Sıra:** 8a ve 8b olarak iki adımda yapmak uygun mu? *Önerim: evet.*

## "Bitti" sayılma ölçütü

**8a**
- [x] Stok modülü açılıp kapanıyor; kapalıyken hiçbir şey stoktan düşmüyor
- [x] Malzeme ekleme/düzenleme, birim ve alış birimi dönüşümü, kritik ve hedef seviye
- [x] Reçete; seçeneklerin yerine koy / ekle / çarp etkisi; yalnızca pakette düşen malzeme
- [x] Gönder'de stoktan düşme, ikramda düşme, iptalde "hazırlandı mı?"; internetsiz çalışıyor, buluta bir kez gidiyor
- [x] Ürün maliyeti ve kâr; Raporlar'da maliyet/kâr sütunları, menü analizi, Gelir–Gider'de ürün maliyeti
- [x] Kritik stok uyarısı (liste ve Ana Sayfa); ilk sayım; hazır şablon (seçilirse)
- [x] Testler: reçete hesabı (seçenekli), düşme/iade senaryoları (yerel + sunucu aynı sonuç), emülatör

**8b**
- [x] Sayım (taslak, kısmi, onay), sayım farkı ve teorik/gerçek tüketim raporu
- [x] Yeni zayi (ürün ve malzeme), eski kayıtlarla birlikte raporlanıyor
- [x] Tedarikçi, sipariş önerisi, sipariş PDF/metni, kısmi teslim alma, ağırlıklı ortalama maliyet
- [x] Ödendi / ödenecek, Masraflar'a ve kasaya yansıma, tedarikçi bakiyesi
- [x] Raporlar → Stok sekmesi
