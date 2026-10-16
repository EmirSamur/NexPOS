# Kafe Otomasyonu: Veri Modeli (v2)

Tek kafe · NexPOS (masaüstü kasa, garson ve yönetim paneli) · Flutter müşteri uygulaması · Firebase

> v2 değişiklikleri: NexPOS'a uyarlandı. `courier` rolü, `terminals`, `expenses` ve `waste` eklendi,
> personelin PIN ile girişi çevrimdışı çalışacak şekilde tanımlandı. Mimari ve çevrimdışı mod için `docs/MIMARI.md` dosyasına bakın.

## 0. Temel kurallar

Bu kurallar Genç Ofis'te işe yarayan yaklaşımın aynısı:

1. **Para her zaman kuruş cinsinden ve tam sayı tutulur.** `4500` = 45,00 ₺. Ondalıklı sayıyla para tutulmaz.
2. **Değerli veriyi istemci yazmaz.** Sipariş tutarı, ödeme, damga, ödül ve stok düşümü yalnızca
   Cloud Functions'ta, transaction içinde yapılır. İstemci ancak "şunu ekle" der; fiyatı sunucu hesaplar.
3. **Yetki custom claim ile verilir.** `request.auth.token.role` şu değerlerden birini alır:
   `owner | manager | cashier | waiter | courier | barista | kitchen`. Kasadaki bilgisayarlar ise `terminal` claim'i
   taşıyan ayrı bir cihaz hesabıyla bağlanır (bkz. `docs/MIMARI.md`). Müşterilerin `role` claim'i yoktur.

   NexPOS'taki rollerin karşılığı: Yönetici → `owner`, Müdür → `manager`, Kasa → `cashier`,
   Garson → `waiter`, Kurye → `courier`. `barista` ve `kitchen` rolleri bar ve mutfak ekranı için yeni eklendi.
4. **Siparişe anlık görüntü (snapshot) yazılır.** Siparişe ürünün o anki adı ve fiyatı kopyalanır.
   Menüde fiyat sonradan değişse de eski adisyonlar ve raporlar bozulmaz.
5. **Raporlar siparişleri taramaz.** Ödeme alındığında bir fonksiyon `dailyStats` dokümanını günceller,
   panel de raporları oradan okur. Bu hem hızlıdır hem de Firestore okuma maliyetini düşürür.
6. **Kritik her işlem `auditLogs`'a yazılır:** iptal, ikram, indirim, iade, kasa farkı ve fiyat değişikliği.
7. **Her dokümanda `updatedAt` (sunucu zamanı) alanı bulunur.** NexPOS'un çevrimdışı önbelleği değişiklikleri bu alana göre çeker.
8. **Hiçbir şey fiziksel olarak silinmez; `deleted: true` olarak işaretlenir.** Silinen kayıt terminal önbelleğinden de böylece düşer.
9. **Terminalde oluşan kayıtların kimliği UUID'dir** ve terminalde üretilir. Böylece internet yokken de sipariş açılabilir (bkz. `docs/MIMARI.md`).

---

## 1. Ayarlar

### `settings/general` (tek doküman)
```ts
{
  cafeName: string,
  logoUrl: string,
  currency: "TRY",
  defaultTaxRate: 10,                 // %; ürün bazında ezilebilir
  pricesIncludeTax: true,             // menü fiyatları KDV dahil mi
  openingHours: { mon: ["08:00","23:00"], ... },
  serviceStations: ["bar", "kitchen"],
  receiptFooter: string,
  updatedAt, updatedBy
}
```

### `settings/loyalty`
```ts
{
  stampsForReward: 10,                // 10 damga = 1 bedava içecek
  rewardMaxValue: 9000,               // bedava ürün en fazla 90 ₺ değerinde olabilir
  rewardValidDays: 60,
  birthdayReward: true,
  tiers: [                            // ömür boyu damgaya göre seviye
    { id: "bronze", name: "Bronz", minStamps: 0,   perks: [] },
    { id: "silver", name: "Gümüş", minStamps: 50,  perks: ["Ayda 1 ücretsiz boy büyütme"] },
    { id: "gold",   name: "Altın", minStamps: 150, perks: ["Her 8 damgada ödül"] }
  ],
  referralBonusStamps: 2
}
```

### `settings/quiz`: kahve önerisi testi (bkz. §8)

---

## 2. Personel

### `staff/{uid}`: uid, Firebase Auth kullanıcısıyla aynıdır
```ts
{
  name: string,
  phone: string,
  role: "owner"|"manager"|"cashier"|"waiter"|"courier"|"barista"|"kitchen",  // claim ile senkron
  email?: string,           // yalnızca yönetim paneline girenler (owner/manager) için
  active: boolean,
  hourlyWage?: number,      // kuruş
  permissions?: Partial<Permissions>,   // rolün varsayılanını kişi bazında ezer (bkz. settings/permissions)
  pinVersion: number,       // PIN değişince artar; terminaller önbelleği yeniler
  lastLoginAt?: Timestamp,
  createdAt
}
```

### `staffPins/{uid}`: yalnızca fonksiyonlar ve terminaller okur
```ts
{ pinHash: string, salt: string, algo: "scrypt", pinVersion: number }
```
> PIN ayrı dokümanda tutulur. Personel listesini gören yönetici bile PIN özetlerini okuyamaz.
> Terminal bu dokümanı önbelleğe alır, böylece internet yokken de PIN doğrulanabilir.

### `settings/permissions`: NexPOS'taki yetki matrisi
```ts
{
  roles: {
    waiter:  { openTable: true,  voidItem: false, editMenu: false, settings: false,
               viewReports: false, discount: false, cash: false, manageUsers: false, comp: false, refund: false },
    cashier: { ..., discount: true, cash: true },
    manager: { ..., voidItem: true, viewReports: true, comp: true, refund: true },
    owner:   { /* hepsi true, değiştirilemez */ }
  }
}
```
> NexPOS'taki matris şu an kaydedilmiyor ve hiçbir yerde uygulanmıyor. Artık hem NexPOS ekranları
> (butonu gizler) hem de Cloud Functions (isteği reddeder) bu dokümanı okur.

### `terminals/{id}`: kafedeki NexPOS kurulumları
```ts
{
  name: "Kasa 1", deviceUid: string,      // terminal cihaz hesabının uid'i
  lastSeenAt: Timestamp,                   // her senkronda güncellenir
  online: boolean,                         // son 2 dakikada görüldüyse true
  pendingOps: number,                      // kuyrukta bekleyen işlem sayısı
  appVersion: string
}
```

### `shiftPlans/{staffId}_{tarih}`: vardiya planı (9. ekran; panelden, `saveShiftPlans`)
```ts
{
  staffId, date: "2026-10-13",          // iş günü; 16:00–01:00 gibi gece yarısını geçen vardiya bu güne aittir
  start: "09:00" | null, end: "17:00" | null, breakMinutes: 30,
  leave: null | "annual" | "sick" | "unpaid" | "holiday",
  note, published: boolean,             // publishShiftWeek ile true; kaydedilen hücre taslağa döner
  deleted: boolean, updatedBy, updatedAt
}
```
> Okuma: personel ve terminal. Yazma: yalnızca fonksiyon (`shifts` yetkisi).

### `timeEntries/{entryId}`: mesai kaydı (kuyruktaki `timeClock` / `timeEdit`)
```ts
{
  staffId, businessDay, clockIn: "2026-10-13T09:07:00+03:00", clockOut: string | null,
  breaks: [ { start, end | null } ],
  late: 7,                              // dakika; plan + tolerans (settings/modules.staff) ile sunucuda hesaplanır
  flags: ["forgotClockOut", "edited"], resolved?, editedBy?, reason?, terminalId
}
```
> `timeClock` payload `{ entryId, action: "in"|"out"|"breakStart"|"breakEnd", at, auto? }`: kişi kendi kaydını
> değiştirir. `auto: true` gün sonunda unutulan çıkışın planlanan bitişle kapatıldığını gösterir.
> `timeEdit` payload `{ entryId, staffId, clockIn, clockOut, breaks, reason, approvedBy }`: `shifts` yetkisi ve
> gerekçe zorunlu; eski/yeni değer `auditLogs` (time_edit) kaydına geçer. Okuma: manager+ ve terminal.
> Hesaplar (çalışılan, mola, geç, fazla mesai) `functions/src/shifts.js` ve `shifts_logic.py`'de, ortak senaryolarla.

### `staffWages/{staffId}`: saatlik ücret (yalnızca owner okur/yazar; terminale inmez)
`{ hourlyRate: 15000 | null }` — kuruş / saat, `saveWages` ile.

---

## 3. Menü

### `categories/{id}`
```ts
{
  name: "Sıcak Kahveler",
  order: number,
  station: "bar"|"kitchen",       // bu kategorideki ürünler hangi ekrana düşer
  imageUrl?: string,
  visibleInApp: boolean,
  stampEligible: boolean           // bu kategoriden alınan ürün damga kazandırır mı
}
```

### `products/{id}`
```ts
{
  categoryId: string,
  name: "Latte",
  description: string,
  price: 9500,                     // kuruş, KDV dahil (settings'e göre)
  taxRate?: number,                // yoksa defaultTaxRate kullanılır
  imageUrl: string,
  order: number,

  active: boolean,                 // yönetici elle kapatır
  outOfStock: boolean,             // stok fonksiyonu yazar (reçetedeki malzeme bittiyse)

  optionGroupIds: string[],        // ["size", "milk", "extra-shot"]
  recipe: [ { ingredientId, qty } ],   // qty, malzemenin biriminde (g/ml/adet)
  cost: number,                    // fonksiyon reçeteden hesaplar (kâr marjı raporu için)

  // müşteri uygulaması için
  allergens: ("milk"|"gluten"|"nuts"|"soy"|"egg")[],
  calories?: number,
  caffeineMg?: number,
  tags: string[],                  // "yeni", "vegan", "mevsimlik"

  // kahve önerisi için tat profili (bkz. §8)
  flavor?: {
    strength: 1-5, sweetness: 1-5, acidity: 1-5, body: 1-5,
    milk: boolean, temperature: "hot"|"iced",
    notes: string[]                // "çikolata", "fındık", "meyvemsi"
  },

  stampEligible?: boolean,         // kategoriden farklıysa ezilir
  createdAt, updatedAt
}
```

### `optionGroups/{id}`: boy, süt, şurup gibi seçenekler
```ts
{
  name: "Süt Seçimi",
  selection: "single"|"multi",
  required: boolean,
  min: 0, max: 1,
  options: [
    {
      id: "oat", name: "Yulaf sütü", priceDelta: 1500, active: true,
      recipeDelta: [ { ingredientId: "milk", qty: -200 }, { ingredientId: "oat-milk", qty: 200 } ]
    }
  ]
}
```
> Seçenek grubu ayrı koleksiyonda tutulur. "Süt seçimi" 20 üründe ortaktır; tek yerden değiştirilir.

---

## 4. Stok ve tedarik

### `ingredients/{id}`
```ts
{
  name: "Espresso çekirdeği",
  unit: "g"|"ml"|"adet",               // miktarlar bu birimde tam sayı
  group: "bar"|"kitchen"|"packaging"|"other",
  purchaseUnit: { name: "koli", size: 12000 } | null,
  stock: number,                       // yalnızca stockMove hareketleriyle değişir
  critical: number, target: number | null,
  unitCost: number,                    // kuruş / kg, L ya da adet
  supplierName: string, deleted: boolean
}
```
Ürün reçetesi `products.recipe: [{ ingredientId, qty, takeawayOnly }]`; seçeneğin etkisi
`optionGroups.options[].recipeEffect: { replace?: [{from, to}], scale?: 1.5, add?: [{ingredientId, qty}] }`.

### `stockMovements/{movementId}`: yalnızca fonksiyonlar yazar (kuyruktaki `stockMove` işlemi)
```ts
{
  type: "sale"|"void_return"|"count"|"adjust"|"waste",
  lines: [ { ingredientId, qty } ],    // + giriş, − çıkış; applied: uygulanan satırlar
  orderId?, lineId?, reason?, by, approvedBy, terminalId, at
}
```
> Yetki: sale/void_return `openTable`, count/adjust `stock`, waste `waste`.

### `suppliers/{id}`
`{ name, contactName, phone, email, note, balance (kuruş, borç), deleted }` — bakiye yalnızca fonksiyonlarla değişir.

### `purchaseOrders/{id}`
```ts
{
  no: 12,                              // counters/purchaseOrders ile sırayla
  supplierId, status: "draft"|"sent"|"partial"|"received"|"cancelled",
  lines: [ { ingredientId, qty, amount, received? } ],   // qty temel birim, amount kuruş (satır toplamı)
  total, note, createdBy, createdAt, receivedAt?
}
```

### `purchaseReceipts/{receiptId}` (kuyruktaki `receivePurchase`)
`{ supplierId, purchaseOrderId?, lines, total, payment: { status: "paid"|"unpaid", method? }, note, by, at }`
> Stok artar; birim maliyet = (eski stok × eski maliyet + gelen tutar) / (eski stok + gelen) — eksi stok 0 sayılır.
> Ödenmediyse `suppliers.balance` artar. Ayrıca `stockMovements/{receiptId}` (type: purchase) yazılır.

### `supplierPayments/{paymentId}` (kuyruktaki `supplierPayment`)
`{ supplierId, amount, method: "cash"|"card"|"transfer", note, by, at }` — borç bakiyesi düşer.

---

## 5. Salon ve masalar

### `areas/{id}`
`{ name: "Bahçe", order }`

### `tables/{id}`
```ts
{
  areaId, name: "B4", capacity: 4,
  layout: { x, y, w, h, shape: "round"|"square"|"rect", rotation },  // masa planı editörü
  status: "empty"|"occupied"|"bill_requested"|"reserved",
  currentOrderId: string|null,
  openedAt?: Timestamp,
  waiterId?: string,
  qrToken: string                  // masadaki QR: KAFE:TABLE:<tableId>:<qrToken>
}
```
> `status` ve `currentOrderId` alanlarını sipariş fonksiyonları yönetir. Masa planı bu alanlar için tek doğru kaynaktır.

---

## 6. Sipariş, mutfak ve kasa

### `orders/{id}`
```ts
{
  no: 47,                          // günlük sıra numarası (counters/orders-2026-10-13)
  businessDay: "2026-10-13",       // gece 01:00'de kapanan gün yine bir önceki güne yazılır
  type: "dine_in"|"takeaway"|"pickup",
  source: "pos"|"table_qr"|"app",
  tableId?: string, tableName?: string,
  customerId?: string,             // sadakat QR'ı okutulduysa
  waiterId?: string,
  status: "open"|"paid"|"cancelled",

  items: [
    {
      lineId: string,
      productId, name, unitPrice,          // snapshot
      qty: number,
      options: [ { groupId, optionId, name, priceDelta } ],
      note?: string,                        // "az şekerli"
      station: "bar"|"kitchen",
      kitchenStatus: "pending"|"sent"|"preparing"|"ready"|"served",
      ticketId?: string,
      lineTotal: number,
      status: "active"|"void"|"comp",       // iptal / ikram
      voidReason?: string, voidBy?: string,
      addedBy: uid, addedAt
    }
  ],

  subtotal: number,
  discounts: [ { type: "percent"|"amount"|"campaign"|"reward", value, amount, refId?, by } ],
  taxTotal: number,
  total: number,
  paidAmount: number,

  pickup?: { requestedAt: Timestamp, readyAt?: Timestamp },   // uygulamadan gel-al
  createdAt, closedAt?, closedBy?
}
```

Siparişi değiştiren her işlem bir **callable function** üzerinden yapılır:

| Fonksiyon | Kim çağırır | Ne yapar |
|---|---|---|
| `openTable` | garson | sipariş açar, masayı `occupied` yapar |
| `addItems` | garson / müşteri (QR) | fiyatı sunucuda hesaplar, satırları ekler |
| `sendToKitchen` | garson | `pending` satırları istasyona göre gruplayıp `kitchenTickets` oluşturur |
| `voidItem` / `compItem` | yetkili | iptal veya ikram işler, stok iadesi ve audit kaydı yazar |
| `applyDiscount` | yetkili | indirim uygular |
| `moveTable` / `mergeTables` | garson | masa taşır veya birleştirir |
| `takePayment` | kasiyer | ödeme alır; tamamı ödendiyse siparişi kapatır, stok düşer, damga basar, istatistik günceller |

### `kitchenTickets/{id}`: mutfak ve bar ekranı (KDS)
```ts
{
  orderId, orderNo, tableName, type: "dine_in"|"takeaway", station: "bar"|"kitchen",
  lines: [ { lineId, name, qty, options: string[], note, voided?: true } ],
  doneLineIds: string[],             // tablette işaretlenen (hazırlanan) satırlar
  status: "new"|"preparing"|"ready"|"served",
  cancelled?: true,                  // adisyon iptal edildi
  createdAt, preparingAt?, readyAt?, servedAt?, terminalId, updatedAt
}
```
> Tablet `status in [new, preparing]` (ve istasyonu) olan fişleri canlı dinler; durumu `updateKitchenTicket`
> ile değiştirir (served hariç; teslimi kasa yapar). İptal edilen satır `voided`, taşınan masada `tableName`
> güncellenir. Hazırlama süresi raporu `readyAt − createdAt` farkından çıkar.

### `kdsPairings/{code}`: mutfak ekranı eşleme kodu (yalnızca fonksiyonlar)
`{ name, used, createdBy, createdAt, expiresAt (10 dk), usedAt?, terminalId? }` — mutfak tableti
`terminals/{id}` altında `kind: "kds", station` ile kaydolur ve oradan iptal edilir.

### `payments/{id}`
```ts
{
  orderId, orderNo, businessDay, paymentId,
  method: "cash"|"card"|"meal",
  amount, tip, received?, change,   // received/change yalnızca nakitte
  lineIds: string[] | null,         // "ürün seçerek böl" ile ödenen satırlar
  cashSessionId: string | null,     // açık kasa oturumu varsa
  by: uid, at, terminalId
}
```
> Eşit bölme ayrı bir alan tutmaz: her kişi ayrı bir ödemedir, kuruş farkı son ödemede kapanır.

### `refunds/{id}`: ödenmiş adisyonda iade (6. ekran)
```ts
{ orderId, orderNo, businessDay, refundId, method, amount, reason,
  by: uid, approvedBy: uid, at, cashSessionId: string | null, terminalId }
```
> Adisyon `paid` kalır; `orders.refunds[]` ve `orders.refunded` toplamı da güncellenir. `refund` yetkisi gerekir.

### `cashSessions/{id}`: kasa açılış ve kapanışı (Z raporu)
```ts
{
  terminalId, businessDay, status: "open"|"closed",
  openedBy, approvedBy, openedAt, openingCash,
  movements: [ { movementId, type: "in"|"out", amount, reason, expense, by, approvedBy, at } ],
  closedBy?, closedAt?,
  countedCash?, expectedCash?,      // expectedCash sunucuda yeniden hesaplanır
  terminalExpectedCash?, difference?, differenceReason?,
  report?: { sales, refunds, tips, discount, comps, voids, vat, orders, staff, cash }
}
```
> Beklenen nakit = açılış + nakit tahsilat − nakit iade + giriş − çıkış. Terminalle sunucu farklı
> hesaplarsa `cash_expected_mismatch` kaydı düşer. Terminal başına bir açık oturum olabilir.

### `settings/modules`: açılıp kapanan modüller (5. ve 6. ekran, yalnızca owner yazar)
```ts
{
  kds: { enabled, warnMinutes: 10, lateMinutes: 20, sound },
  cashSession: { required, diffReasonThreshold: 2000 },   // kuruş
  printing: { enabled, kitchenTickets },
  paymentMethods: { cash, card, meal },
  tips: boolean,
  stock: { enabled, askOnVoid },
  staff: { enabled, lateToleranceMinutes: 5 }            // 9. ekran
}
```
> Yazıcı seçimi bulutta değil, her bilgisayarda yereldir.

### `counters/orders-{businessDay}`
`{ last: 47 }`: günlük sipariş numarası (transaction ile artar)

---

## 7. Müşteri ve sadakat

### `customers/{uid}`: müşteri uygulamasından kayıt
```ts
{
  name, phone, email?,
  birthDate?: "MM-DD",             // yıl tutulmaz (KVKK: gereken kadar veri)
  marketingConsent: boolean, consentAt?,

  // yalnızca fonksiyonlar yazar
  stamps: number,                  // mevcut karttaki damga (0–9)
  lifetimeStamps: number,
  tier: "bronze"|"silver"|"gold",
  totalSpent: number, visitCount: number, lastVisitAt,

  favoriteOrder?: { items: [...] },   // "her zamankinden"
  referralCode: string, referredBy?: uid,
  createdAt
}
```

- `customers/{uid}/loyaltyEvents/{id}` **(yalnızca fonksiyonlar yazar)**  
  `{ type: "stamp"|"reward_earned"|"reward_used"|"bonus"|"expire", amount, orderId?, at }`
- `customers/{uid}/rewards/{id}` **(yalnızca fonksiyonlar yazar)**  
  `{ type: "free_drink"|"birthday"|"referral"|"campaign", status: "active"|"used"|"expired", expiresAt, usedOrderId? }`
- `customers/{uid}/devices/{token}`  
  `{ platform, updatedAt }` (FCM bildirim token'ları)

### `loyaltyTokens/{token}`: kasada okutulan QR
```ts
{ uid, expiresAt }                 // 60 saniye geçerli; uygulama sürekli yeniler
```
> QR sabit olmaz. Ekran görüntüsü alıp arkadaşına damga topla(t)mak mümkün olmaz.
> Akış şöyle: müşteri `getLoyaltyQr` çağırır → kasiyer okutur → `attachCustomer(orderId, token)` çalışır →
> ödeme alınınca `takePayment` uygun ürün sayısı kadar damga basar.

### `campaigns/{id}`
```ts
{
  name: "Happy Hour",
  type: "percent"|"amount"|"buy_x_get_y"|"double_stamps",
  value: number,
  appliesTo: { categoryIds?: [], productIds?: [] },
  schedule: { days: [1,2,3,4,5], from: "14:00", to: "17:00", startDate, endDate },
  audience: "all"|"tier:gold"|"app_users",
  active: boolean,
  showInApp: boolean, bannerUrl?
}
```

### `notifications/{id}`: panelden gönderilen toplu bildirimler
`{ title, body, segment: "all"|"tier:gold"|"inactive_30d"|"birthday_today", sentAt, sentBy, reach }`

---

## 8. Kahve önerisi

İlk sürüm **yapay zekâ kullanmaz**, kural tabanlıdır. Hızlı, ücretsiz ve çevrimdışı da çalışır.

### `settings/quiz`
```ts
{
  questions: [
    {
      id: "mood", text: "Bugün nasıl hissediyorsun?",
      answers: [
        { text: "Uykuluyum 😴", weights: { strength: +2 } },
        { text: "Keyifliyim 🙂", weights: { sweetness: +1 } },
        { text: "Sakin bir şey istiyorum", weights: { strength: -2 } }
      ]
    },
    { id: "milk",  text: "Sütlü mü?",         answers: [ { text: "Evet", filter: { milk: true } }, ... ] },
    { id: "temp",  text: "Sıcak mı soğuk mu?", answers: [ { text: "Buz gibi", filter: { temperature: "iced" } }, ... ] },
    { id: "taste", text: "Hangisi sana yakın?", answers: [ { text: "Çikolata", weights: { notes: "çikolata" } }, ... ] }
  ]
}
```

**Puanlama mantığı:**
- Cevaplar bir hedef profil oluşturur (örneğin güç 4, tatlılık 2, sütlü, sıcak).
- `filter` alanı uymayan ürünleri eler.
- Kalan ürünlerin `flavor` alanı hedef profille karşılaştırılır; en yakın üç ürün önerilir.
- Bağlam bonusu eklenir: saat 17:00'den sonra kafeinsiz ürüne +, hava 25 derecenin üstündeyse `iced` ürünlere +, müşterinin hiç denemediği ürüne +.

### `customers/{uid}/recommendations/{id}`
`{ productIds: [], answers: {}, chosenProductId?, at }`
> Müşterinin öneriyi sipariş edip etmediği buraya kaydedilir. Hangi önerinin tuttuğu bu veriyle ölçülür;
> ileride yapay zekâ barista bu geçmişi ve menüyü bağlam olarak kullanır.

---

## 9. Gider ve zayi (NexPOS'tan gelen)

### `expenses/{id}`
```ts
{ type: "Kira"|"Fatura"|..., amount, paymentMethod: "cash"|"card"|"transfer",
  detail, date: "2026-10-13", cashSessionId?, by, createdAt }
```
> Nakit ödenen gider kasadan çıkış olarak `cashSessions.cashOut`'a da yazılır. Böylece kasa sayımı tutar.

### `waste/{id}`
```ts
{ productId?, ingredientId?, name, qty, reason, cost, date, by, createdAt }
```
> Ürün bazlı zayi kaydı (NexPOS'taki gibi) korunur. Ürünün reçetesi varsa fonksiyon ayrıca
> malzeme stoğundan `waste` hareketi düşer.

---

## 10. Raporlama ve kayıt

### `dailyStats/{businessDay}`: günlük özet (yalnızca fonksiyonlar yazar; yönetici/müdür okur)
Adisyon ödenip kapanınca ya da iptal edilince katkısı açıldığı iş gününe, iade yapıldığı iş gününe eklenir
(`src/stats.js`; NexPOS'taki `reports.py` ile aynı hesap).
```ts
{
  day, orders, dineIn, takeaway,
  gross, discount, discountCount, revenue,        // revenue = gross − discount
  tips, byPayment: { cash, card, meal },
  byHour: { "14": { revenue, orders } },           // kapanış saati (terminal yerel saati)
  byStaff: { [staffId]: { revenue, orders } },     // adisyonu açan garson
  byProduct: { [productId | "n:<ad>"]: { name, qty, revenue, comps?, voids? } },
  comps: { count, amount }, voids: { count, amount },   // liste fiyatıyla, satışa dahil değil
  vat: { "10": kdvDahilTutar, ... },
  cancelled, refunds: { count, amount, cash?, card?, meal? },
  updatedAt
}
```
> Ürün maliyeti, misafir sayısı, hazırlama süresi ve sadakat alanları ilgili ekranlarda eklenecek.

### `auditLogs/{id}`
`{ action: "void"|"comp"|"discount"|"refund"|"price_change"|"cash_diff"|"role_change", actor, target, before?, after?, reason?, at }`

---

## 11. Erişim özeti (güvenlik kurallarının taslağı)

| Koleksiyon | Okuma | Yazma |
|---|---|---|
| `categories`, `products`, `optionGroups`, `campaigns` | herkes (app için) | manager+ |
| `settings/*` | herkes (`loyalty`, `quiz`) / personel (`general`) | owner |
| `staff` | personel (kendi), terminal, manager+ (tümü) | manager+ (yalnızca fonksiyon üzerinden; claim senkronu için) |
| `shiftPlans` | personel, terminal | yalnızca fonksiyon (`shifts` yetkisi) |
| `timeEntries` | manager+, terminal | yalnızca fonksiyon (kuyruktan) |
| `staffWages` | owner | yalnızca fonksiyon (owner) |
| `staffPins` | terminal | yalnızca fonksiyon |
| `terminals` | manager+ | yalnızca fonksiyon |
| `expenses`, `waste` | manager+ | manager+ / terminal (kuyruktan) |
| `ingredients`, `suppliers`, `purchaseOrders` | personel | manager+ (stok **alanı** yalnızca fonksiyon) |
| `stockMovements` | manager+ | yalnızca fonksiyon |
| `areas`, `tables` | personel | manager+ (yerleşim); durum alanları yalnızca fonksiyon |
| `orders` | personel; müşteri kendi siparişini | yalnızca fonksiyon |
| `kitchenTickets` | personel | barista/kitchen yalnızca `status` alanı |
| `payments`, `refunds`, `cashSessions` | manager+ ve terminal | yalnızca fonksiyon |
| `customers/{uid}` | sahibi, cashier+ | sahibi yalnızca `name`, `birthDate`, `marketingConsent` |
| `customers/*/loyaltyEvents`, `rewards` | sahibi, cashier+ | yalnızca fonksiyon |
| `dailyStats`, `auditLogs` | manager+ | yalnızca fonksiyon |

"manager+" = manager ve owner. "cashier+" = cashier, manager ve owner.

---

## 12. Ekran sırası (önerilen)

Her ekran bir öncekinin verisine dayanır:

1. **Giriş ve roller:** terminal eşleme, PIN ile personel girişi, yönetici girişi, yetki matrisi
2. **Menü yönetimi:** kategoriler, ürünler, seçenek grupları *(her şey buna bağlı)*
3. **Salon ve masa planı editörü:** alanlar, masalar, sürükle-bırak yerleşim, QR çıktısı
4. **Garson ekranı (POS):** masa seç → ürün ekle → mutfağa gönder
5. **Mutfak ve bar ekranı (KDS)**
6. **Kasa:** ödeme, bölünmüş hesap, kasa açılış/kapanış, Z raporu
7. **Dashboard ve raporlar**
8. **Stok, reçete ve tedarik**
9. **Personel ve vardiya**
10. **Müşteri, sadakat, kampanya ve bildirim** (panel tarafı)
11. **Mobil:** kayıt → sadakat kartı → menü → kahve önerisi → masadan QR sipariş → gel-al
