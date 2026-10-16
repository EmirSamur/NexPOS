# 10. Ekran: Müşteri, Sadakat, Kampanya ve Bildirim (tarif, onay bekliyor)

## Amaç

- Gelen müşteri **tanınsın**: kasada uygulamadaki QR okutulur ya da telefon numarası yazılır.
- Her içecekte **damga** toplansın; 10 damgada bir içecek bedava olsun (sayı ayarlanır). Doğum gününde hediye.
- **Kampanyalar** (Happy Hour, 2. kahve %50, hafta içi tatlı indirimi, çift damga günü) kasada kendiliğinden
  uygulansın; elle iskonto aramaya gerek kalmasın.
- Panelden **müşteri listesi**, kampanya yönetimi ve **bildirim** (uygulamaya) hazırlansın.
- Sonuç ölçülsün: kaç üye var, ne sıklıkla geliyor, ödüllerin ve kampanyaların maliyeti ne, kampanya işe yaradı mı.

Bu ekran **panel ve kasa tarafıdır**. Müşterinin elindeki uygulama (kayıt, sadakat kartı, QR, menü) 11. ekrandır;
burada kurulan veri ve kurallar oraya hazır olur. Uygulama yokken de çalışır: kasada telefonla üyelik açılır.

Sadakat ve Kampanyalar iki ayrı **modül**dür (Ayarlar → Modüller); kapalıyken kasada hiçbir şey sorulmaz.

---

## 10.1 Kasada müşteri (ödeme ekranı ve adisyon)

```
┌ Masa 4 · Adisyon 47 ──────────────────────────────────────────────┐
│ [👤 Müşteri ekle]                                                   │
│   ↳ QR okut  |  Telefon: [0532 ___ __ __]  [Ara]  [+ Yeni üye]       │
│                                                                     │
│ 👤 Ayşe K. · ●●●●●●●○○○ 7/10 · Gümüş · 🎁 1 ödül hazır               │
│                                                                     │
│ 2× Latte                          190,00 ₺   (+2 damga)              │
│ 1× Cheesecake                     140,00 ₺                           │
│ 🏷 Happy Hour %20 (kahveler)      −38,00 ₺   kendiliğinden           │
│ 🎁 Ödül: bedava içecek (Latte)    −95,00 ₺   [Kullan] [Sonraya sakla] │
│                                                    Toplam 197,00 ₺   │
└─────────────────────────────────────────────────────────────────────┘
```

- **Tanıma:** uygulamadaki QR (60 sn geçerli, ekran görüntüsüyle çalışmaz) ya da telefon numarası.
  Telefonla aramada ad ve numaranın son 4 hanesi görünür (`0532 *** ** 67`).
- **Yeni üye (kasada):** ad + telefon + "kampanya bildirimi istiyor mu" (KVKK onayı, müşteriye sorulur).
  Müşteri sonra uygulamaya aynı numarayla girince kartı aynen gelir.
- **Damga:** ödeme tamamlanınca, "damga kazandıran" kategorilerdeki (varsayılan: içecekler) her ürün için 1 damga.
  İkram edilen, iptal edilen ve ödülle bedava alınan ürün damga kazandırmaz. İade edilen ürünün damgası geri alınır.
- **Ödül:** damga dolunca ödül hazır olur. Kasiyer "Kullan" der; adisyondaki en pahalı uygun içecek
  (en fazla ayarlanan tutar, ör. 90 ₺) bedava olur. Kullanılmayan ödül 60 gün geçerlidir.
- **Doğum günü:** doğum günü haftasında gelen üyeye bir ödül (ayarlanır).
- **İnternetsiz:** bu bilgisayar üyelerin kart bilgisini (ad, maskeli telefon, damga, ödüller) önbellekte tutar;
  telefonla tanıma, damga ve ödül kullanımı internetsiz çalışır, kuyrukla gider. **QR ile tanıma internet ister**
  (QR'ın gerçekliği sunucuda doğrulanır). Tek kasa olduğu için ödülün iki kez kullanılması riski yoktur;
  yine de sunucu bunu ayrıca denetler.

## 10.2 Kampanyalar (Pazarlama → Kampanyalar)

```
┌ Kampanyalar ───────────────────────────────────────────────── [+ Kampanya] ┐
│ ● Happy Hour        %20 · Kahveler       Hft içi 14:00–17:00   Aktif   38 kez │
│ ● 2. Kahveye %50    2. ürün %50 · Kahve  Her gün               Aktif   12 kez │
│ ○ Çift Damga Salı   2× damga             Salı                  Pasif          │
│ ● Öğrenci Menüsü    Latte+Kurabiye 120 ₺ Hft içi               Aktif    4 kez │
└────────────────────────────────────────────────────────────────────────────┘
```

Kampanya türleri:

| Tür | Örnek |
|---|---|
| Yüzde indirim | Kahvelerde %20 |
| Tutar indirim | Tatlılarda 20 ₺ |
| X al Y öde / 2. ürün indirimli | 2. kahveye %50, 3 al 2 öde |
| Sabit fiyatlı ikili (menü) | Latte + Kurabiye 120 ₺ |
| Çift damga | Salı günü damgalar 2 kat |

- **Koşullar:** ürün/kategori, gün ve saat aralığı, başlangıç–bitiş tarihi, kime (herkes / yalnızca üyeler /
  belirli seviye), en az adisyon tutarı.
- **Kasada:** koşulu tutan kampanya **kendiliğinden** uygulanır ve adisyonda 🏷 satırı olarak görünür;
  kasiyer tek dokunuşla kaldırabilir. Bir ürüne en fazla **bir** kampanya uygulanır (müşteri için en
  avantajlısı). Elle iskonto yapılan adisyonda kampanya uygulanmaz (ikisi üst üste binmez).
- Kampanya fişte, Z raporunda ve raporlarda **ayrı** satırdır (elle iskontodan ayrı).
- Kampanyalar menü gibi bulutta düzenlenir (internet), kasada internetsiz uygulanır.

## 10.3 Müşteriler (Pazarlama → Müşteriler)

```
Ad          Telefon          Seviye  Damga  Ziyaret  Harcama    Son ziyaret  Bildirim
Ayşe K.     0532 *** ** 67   Gümüş   7/10   41       6.240 ₺    bugün        ✓
Mehmet T.   0505 *** ** 12   Bronz   2/10   5        610 ₺      34 gün önce  ✗
```

- Arama, sıralama, filtre (seviye, 30 gündür gelmeyen, bu hafta doğum günü olan, bildirim izni olan).
- Müşteri detayı: ziyaret ve harcama geçmişi, damga/ödül hareketleri, en çok aldığı ürünler.
- **Elle damga/ödül düzeltme:** yetki (`loyalty`) ve gerekçe ister, kayda geçer.
- **KVKK:** müşteri isterse kaydı silinir (kişisel bilgiler silinir, geçmiş satışlar anonim kalır);
  verisi istenirse dışa aktarılır. Tam telefon numarasını yalnızca Yönetici/Müdür görür.
- Seviyeler (Bronz / Gümüş / Altın) ömür boyu damgaya göre; ayrıcalıkları Ayarlar → Sadakat'ta yazılır.

## 10.4 Bildirimler (Pazarlama → Bildirimler)

```
Başlık: [Yağmurlu günlere sıcak çikolata ☕]   Metin: [Bugün sıcak çikolata %20 indirimli]
Kime:  (•) Bildirim izni olan herkes   ( ) 30 gündür gelmeyenler   ( ) Altın üyeler   ( ) Bugün doğum günü olanlar
Kampanyaya bağla: [Happy Hour ▾]                                 Tahmini erişim: 214 kişi   [Gönder]
```

- Yalnızca **bildirim izni veren** üyelere gider; kişi başı günde en fazla 1 bildirim.
- Bildirimler uygulamaya (11. ekran) gider. Bu ekranda yazma, kitle seçme, erişim tahmini ve geçmiş hazır olur;
  gerçek gönderim uygulama yayınlanınca açılır.
- SMS/WhatsApp toplu gönderim bu kapsamda **yok** (ücretli servis ve ayrıca ticari ileti izni gerekir).

## 10.5 Rapor (Raporlar → Sadakat sekmesi)

- Üye sayısı (yeni / aktif), üyelerin cirodaki payı, ortalama ziyaret sıklığı, geri gelme oranı.
- Verilen damga, kazanılan ve kullanılan ödül, ödüllerin maliyeti (ürün maliyeti; stok modülü açıksa).
- Kampanya başına: kaç kez uygulandı, indirim tutarı, kampanya saatlerindeki ciro ve adisyon sayısı
  (önceki 4 haftanın aynı saatleriyle karşılaştırma).

## 10.6 Yetkiler

| Yetki | Varsayılan |
|---|---|
| Müşteri ekle / tanı, damga (ödemeyle kendiliğinden), ödül kullan | Kasa, Garson, Müdür, Yönetici |
| Kampanyayı adisyondan kaldırma | Kasa, Müdür, Yönetici |
| `loyalty` — elle damga/ödül düzeltme, müşteri listesi | Müdür, Yönetici |
| `campaigns` — kampanya ve bildirim | Müdür, Yönetici |
| Sadakat ayarları, müşteri kaydı silme, tam telefon | Yönetici (silme), Müdür+ (telefon) |

## 10.7 Veri

- `settings/loyalty`: `{ stampsForReward: 10, stampCategoryIds, rewardMaxValue, rewardValidDays, birthdayReward, tiers }`
- `customers/{id}`: `{ name, phone, birthDate?, marketingConsent, stamps, lifetimeStamps, tier, totalSpent,
  visitCount, lastVisitAt, deleted }` — damga ve harcama alanlarını **yalnızca fonksiyonlar** yazar.
- `customers/{id}/loyaltyEvents`, `customers/{id}/rewards` — kuyruktan (`loyaltyStamp`, `rewardUse`, `customerCreate`).
- `orders.customerId`, `orders.items[].campaignId`, `orders.campaigns: [{ id, name, amount }]`.
- `campaigns/{id}`: tür, değer, koşullar, takvim, kitle, aktif.
- `loyaltyTokens/{token}`: QR (60 sn, tek kullanım).
- `notifications/{id}`: başlık, metin, kitle, erişim, gönderen, zaman.

## Sorular

1. **Kasada telefonla üyelik** açılsın mı (uygulamayı indirmeyen müşteri için)? *Önerim: evet* — uygulama
   gelene kadar sadakat bununla başlar; sonra aynı numarayla uygulamaya geçilir.
2. **Damga kuralı:** her uygun ürün = 1 damga mı, yoksa her ziyaret (adisyon) = 1 damga mı?
   *Önerim: içecek başına 1 damga* (2 kahve alan 2 damga alır; kafelerde alışılmış olan bu).
3. **Ödül:** "10 damga = 1 bedava içecek (en fazla 90 ₺)" uygun mu? Bedava ürün en pahalı içecek mi olsun,
   kasiyer mi seçsin? *Önerim: kendiliğinden en pahalı uygun içecek, kasiyer değiştirebilir.*
4. **Seviyeler** (Bronz/Gümüş/Altın) ilk sürümde olsun mu? *Önerim: evet ama yalnızca rozet + yazılı ayrıcalık*;
   seviyeye özel otomatik indirim kampanyalarla (kitle: Altın) yapılır.
5. **Kampanya ve elle iskonto** üst üste binebilsin mi? *Önerim: hayır* — elle iskonto yapılırsa kampanya kalkar.
6. **Kampanyalar kasada kendiliğinden mi uygulansın**, yoksa kasiyer mi seçsin?
   *Önerim: kendiliğinden, kasiyer tek dokunuşla kaldırabilir.*
7. **Bildirim:** gerçek gönderim uygulama (11. ekran) yayınlanınca açılsın; burada yalnızca hazırlık ve kitle
   seçimi olsun mu? *Önerim: evet.* SMS kapsam dışı.

## "Bitti" sayılma ölçütü

- [ ] Sadakat ve Kampanyalar modülleri açılıp kapanıyor
- [ ] Kasada müşteri: telefonla arama, yeni üye (onaylı), QR ile tanıma (internetle); kart özeti adisyonda
- [ ] Ödemede damga; ikram/iptal/ödül damga vermez; iadede geri alınır; damga dolunca ödül; doğum günü ödülü
- [ ] Ödül kullanma (en pahalı uygun içecek, üst sınır), süre sonu; internetsiz çalışıyor, buluta bir kez gidiyor
- [ ] Kampanyalar: 5 tür, koşullar ve takvim, kasada kendiliğinden, ürüne tek kampanya, elle iskontoyla çakışmıyor,
      fişte/Z raporunda/raporlarda ayrı satır
- [ ] Müşteri listesi, detay, elle düzeltme (gerekçeli), KVKK silme ve dışa aktarma
- [ ] Bildirim taslağı, kitle seçimi, erişim tahmini, izin ve günlük sınır kuralları
- [ ] Sadakat raporu ve kampanya etkisi
- [ ] Testler: kampanya hesabı ve damga kuralları (yerel + sunucu aynı sonuç, ortak senaryolar), emülatör, uçtan uca
