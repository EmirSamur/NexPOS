# 9. Ekran: Personel Vardiya ve Mesai

> Durum: **uygulandı**. Sorulara verilen cevaplar (hepsi öneri yönünde): mesaiye başlamadan sipariş alınır
> (yalnızca hatırlatma çıkar); unutulan çıkış gün sonunda planlanan bitişle kapanıp düzeltme listesine düşer;
> mola düğmeyle, basılmadıysa plandaki mola düşülür; saatlik ücret isteğe bağlı ve yalnızca Yönetici görür;
> izin yalnızca işaretlenir (bakiye yok); geç kalma toleransı 5 dk (Modüller'den değişir); plan personele
> Vardiyam + PDF + WhatsApp metniyle ulaşır.
>
> Uygulama notları: Plan ve mesai, panelde **Kullanıcılar → Vardiya ve Mesai** sayfasındadır (iki sekme).
> Vardiyam, garson ekranında "Vardiyam" düğmesinden ve üst bardaki isimden açılır. Dünden açık kalan mesai,
> ertesi gün giriş ekranı açılınca ya da kişi mesaiye başlarken kendiliğinden kapanır.

## Amaç

- Kimin hangi gün hangi saatlerde çalışacağı **planlansın** (haftalık vardiya planı) ve personele ulaşsın.
- Kimin **gerçekte** ne zaman gelip gittiği, mola verdiği kaydedilsin (puantaj).
- Ay sonunda kişi başı çalışılan saat, fazla mesai, geç kalma ve devamsızlık tek raporda çıksın;
  isteyen için **işçilik maliyeti** ve cironun yüzde kaçı olduğu görünsün.

Bugün NexPOS'ta yalnızca PIN girişinin saati var. Ama **PIN girişi mesai değildir**: garson gün içinde
defalarca kilit ekranına düşer, tekrar girer. Bu yüzden mesai ayrı bir "Mesaiye başla / bitir" işlemidir.

Bu da bir **modül**dür (Ayarlar → Modüller → "Personel ve mesai"); kapalıyken hiçbir şey sorulmaz.

---

## 9.1 Giriş / çıkış (puantaj) — giriş ekranında

```
┌ Giriş ─────────────────────────────────────────────────────────────┐
│  [Cem Akar]        [Elif Demir]       [Selin Er]      [Mert Kaya]   │
│  🟢 Mesaide 08:58   ⚪ Bugün 16:00     ☕ Molada 12:40   ⚪ İzinli     │
└────────────────────────────────────────────────────────────────────┘
PIN girildikten sonra (mesaide değilse):
┌───────────────────────────────────────────────┐
│ Günaydın Cem! Bugünkü vardiyan 09:00 – 17:00   │
│ [ Mesaiye başla ]   [ Sadece giriş yap ]       │
└───────────────────────────────────────────────┘
```

- **Mesaiye başla / Mesaiyi bitir / Molaya çık / Moladan dön** — kişi kendi PIN'iyle yapar.
  Üst bardaki kullanıcı menüsünden de erişilir.
- Saat **bu bilgisayarın saatidir** ve internetsiz kaydedilir; kuyrukla buluta gider.
- **Geç kalma:** planlanan başlangıçtan sonra (tolerans varsayılan 5 dk) başlayan mesai "geç" işaretlenir.
- **Çıkışı unutmak:** iş günü bittiğinde (05:00) açık kalan mesai **planlanan bitiş saatiyle** kapatılır ve
  "çıkış unutuldu" olarak müdürün düzeltme listesine düşer. Plan yoksa son işlem saati kullanılır.
- **Düzeltme:** Yönetici/müdür kayıtları düzeltebilir (giriş/çıkış saati, mola); gerekçe zorunlu, eski ve yeni
  değer kayda geçer. Personel kendi kaydını değiştiremez.

## 9.2 Vardiya planı (Personel → Vardiya Planı)

```
┌ Vardiya Planı · 13 – 19 Ekim ───────────── [◀ Önceki] [Bu hafta] [Sonraki ▶] [Geçen haftayı kopyala] ┐
│              Pzt 13      Sal 14      Çar 15      Per 16      Cum 17      Cmt 18      Paz 19   Toplam│
│ Cem Akar     09–17       09–17       İZİN        09–17       12–22       12–22       —        40 sa │
│ Elif Demir   16–24       16–24       16–24       —           16–24       10–18       10–18    48 sa⚠│
│ Selin Er     08–16       08–16       08–16       08–16       08–16       —           —        40 sa │
│ Günlük kişi  3           3           2           2           3           3           1              │
│ Şablonlar: [Sabah 08–16] [Akşam 16–24] [Ara 12–22] [İzin ▾]          [Yayınla]  [PDF]  [WhatsApp metni]│
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- Hücreye tıklanır: başlangıç, bitiş, mola süresi, not; ya da **izin** (yıllık izin, rapor, ücretsiz izin,
  resmi tatil). Şablona tıklayıp hücrelere "boyamak" mümkündür.
- Gece yarısını geçen vardiya (16–01) aynı güne aittir.
- Haftalık toplam **45 saati** aşan kişi ⚠ ile işaretlenir (iş kanunu sınırı; bilgi amaçlı).
- **Günlük kişi sayısı** satırı, Raporlar'daki saatlik yoğunlukla karşılaştırma için.
- **Yayınla:** personel kendi planını NexPOS'taki **Vardiyam** penceresinde görür. Plan PDF olarak
  basılabilir ya da WhatsApp grubuna yapıştırılacak metin olarak kopyalanır.
- Plan düzenlemek internet ister (menü gibi bulutta tutulur); giriş/çıkış istemez.

## 9.3 Mesai raporu (Raporlar → Personel → Mesai)

```
Personel     Plan    Çalışılan  Mola   Fazla mesai  Geç (kez/dk)  Gelmedi  Unutulan çıkış  Ciro/saat
Cem Akar     160 sa  163,5 sa   12 sa  3,5 sa       2 / 14 dk     0        1               412 ₺
Elif Demir   176 sa  170,0 sa   13 sa  0            5 / 47 dk     1        0               388 ₺
```

- Dönem seçilir (bu hafta, bu ay, geçen ay…). Kişiye tıklayınca gün gün giriş/çıkış dökümü açılır.
- **Fazla mesai:** haftalık 45 saati aşan çalışma (bilgi amaçlı; bordro hesabı değildir).
- **Ciro/saat:** kişinin açtığı adisyonların cirosu ÷ çalıştığı saat (7. ekrandaki personel raporuyla aynı ciro).
- CSV/PDF olarak muhasebeye gönderilir.
- **İşçilik maliyeti (isteğe bağlı):** kişiye saatlik ücret girilirse dönemin işçilik maliyeti ve cironun yüzdesi
  görünür ("İşçilik: 48.200 ₺ · cironun %21'i"). Ücretler **yalnızca Yönetici** görür ve terminal önbelleğine
  inmez; bu bölüm internet ister.

## 9.4 Vardiyam (garson / barista / kasiyer)

Mevcut "Vardiyam" penceresine eklenir: bu hafta ve gelecek haftanın planı, bu hafta çalışılan saat,
bugünkü giriş saati ve mola. Mesaiye başla / bitir / mola düğmeleri de buradadır.

## 9.5 Yetkiler

| Yetki | Varsayılan |
|---|---|
| `shifts` — vardiya planı, mesai düzeltme, mesai raporu | Yönetici, Müdür |
| Kendi mesaisini başlat/bitir, mola | herkes |
| Saatlik ücret ve işçilik maliyeti | yalnızca Yönetici |

## 9.6 Veri

- `shiftPlans/{personel_tarih}`: `{ staffId, date, start: "09:00", end: "17:00", breakMinutes, leave?: "annual"|"sick"|"unpaid"|"holiday", note, published }` — panelden (internet).
- `timeEntries/{id}`: `{ staffId, businessDay, clockIn, clockOut?, breaks: [{start, end}], late, flags: ["forgotClockOut", "edited"], editedBy?, reason? }` — kuyruktan (internetsiz), düzeltme yetkiyle.
- `staffWages/{staffId}`: `{ hourlyRate }` — yalnızca Yönetici okur/yazar.

## Sorular

1. **Mesaiye başlamadan sipariş alınabilsin mi?** *Önerim: evet, yalnızca hatırlatma çıksın* — servisi
   kilitlemek yoğun anda sorun olur.
2. **Çıkışı unutan:** gün sonunda planlanan bitiş saatiyle kapatılıp müdüre "düzeltilecek" diye düşsün mü?
   *Önerim: evet.*
3. **Mola:** düğmeyle mi (gerçek süre), yoksa plandaki sabit mola süresi mi düşülsün?
   *Önerim: düğmeyle; düğmeye basılmamışsa plandaki mola süresi düşülsün.*
4. **Saatlik ücret ve işçilik maliyeti** olsun mu? *Önerim: evet, isteğe bağlı ve yalnızca Yönetici görsün.*
5. **İzin:** yalnızca plana işaretlemek yeterli mi, yoksa yıllık izin bakiyesi (kalan gün) de takip edilsin mi?
   *Önerim: şimdilik işaretleme; bakiye sonra.*
6. **Geç kalma toleransı:** 5 dakika uygun mu? (Modüller'den değiştirilebilir.)
7. **Plan personele nasıl ulaşsın:** NexPOS'taki Vardiyam + PDF + WhatsApp metni yeterli mi?
   *Önerim: evet* (11. ekrandaki mobil uygulama müşteriler içindir; personel uygulaması ayrı bir iş olur).

## "Bitti" sayılma ölçütü

- [x] Modül açılıp kapanıyor; kapalıyken mesai sorulmuyor
- [x] Mesaiye başla / bitir / mola internetsiz çalışıyor, buluta bir kez gidiyor; giriş kartında durum görünüyor
- [x] Geç kalma işaretleniyor; unutulan çıkış gün sonunda kapanıp düzeltme listesine düşüyor
- [x] Yetkili düzeltme gerekçeyle kayda geçiyor
- [x] Haftalık plan: hücre düzenleme, şablon, izin, geçen haftayı kopyalama, 45 saat uyarısı, günlük kişi sayısı,
      yayınla, PDF ve WhatsApp metni
- [x] Mesai raporu: plan/çalışılan/mola/fazla mesai/geç/gelmedi/unutulan çıkış/ciro-saat; gün gün döküm; CSV/PDF
- [x] İşçilik maliyeti yalnızca Yönetici'ye görünüyor, terminale inmiyor
- [x] Vardiyam penceresi planı ve haftalık saati gösteriyor
- [x] Testler: saat hesapları (gece yarısını geçen vardiya, mola, geç kalma, 45 saat), yerel ve emülatör
