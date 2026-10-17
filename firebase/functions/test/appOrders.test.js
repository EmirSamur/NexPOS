// Uygulama siparişi kuralları: sepet fiyatı, gel-al saati, fişlerden durum, kasa çevrimiçi mi.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const A = require('../src/appOrders');

const menu = () => ({
  categories: new Map([['c1', { name: 'Kahve' }], ['c2', { name: 'Gizli', visibleInApp: false }]]),
  products: new Map([
    ['latte', { name: 'Latte', categoryId: 'c1', price: 9500, optionGroupIds: ['size', 'milk', 'extra'] }],
    ['brownie', { name: 'Brownie', categoryId: 'c1', price: 12000, optionGroupIds: [] }],
    ['gone', { name: 'Tükenen', categoryId: 'c1', price: 100, soldOut: true }],
    ['hidden', { name: 'Gizli', categoryId: 'c2', price: 100 }],
    ['off', { name: 'Kapalı', categoryId: 'c1', price: 100, visibleInApp: false }],
  ]),
  groups: new Map([
    ['size', { name: 'Boy', selection: 'single', required: true, min: 1, max: 1,
      options: [{ id: 's', name: 'Küçük', priceDelta: 0 }, { id: 'l', name: 'Büyük', priceDelta: 1500 }] }],
    ['milk', { name: 'Süt', selection: 'single', required: false, min: 0, max: 1,
      options: [{ id: 'oat', name: 'Yulaf', priceDelta: 2000 }, { id: 'soy', name: 'Soya', priceDelta: 2000, soldOut: true }] }],
    ['extra', { name: 'Ekstra', selection: 'multi', required: false, min: 0, max: 2,
      options: [{ id: 'shot', name: 'Shot', priceDelta: 1000 }, { id: 'syr', name: 'Şurup', priceDelta: 500 },
        { id: 'cr', name: 'Krema', priceDelta: 500 }] }],
  ]),
});

test('sepet: fiyat menüden, seçenek farkları eklenir', () => {
  const r = A.priceCart([
    { productId: 'latte', qty: 2, options: [{ groupId: 'size', optionId: 'l' }, { groupId: 'milk', optionId: 'oat' }], note: ' az sıcak ' },
    { productId: 'brownie', qty: 1, unitPrice: 1 },
  ], menu());
  assert.equal(r.total, 2 * (9500 + 1500 + 2000) + 12000);
  assert.deepEqual(r.items[0].options.map((o) => o.name), ['Büyük', 'Yulaf']);
  assert.equal(r.items[0].note, 'az sıcak');
  assert.equal(r.items[1].unitPrice, 12000); // uygulamanın gönderdiği fiyat yok sayılır
});

test('sepet: zorunlu seçenek, en fazla seçim, başka ürünün seçeneği', () => {
  const m = menu();
  assert.throws(() => A.priceCart([{ productId: 'latte', qty: 1 }], m), /Boy seçilmelidir/);
  assert.throws(() => A.priceCart([{ productId: 'latte', qty: 1, options: [{ groupId: 'size', optionId: 's' },
    { groupId: 'extra', optionId: 'shot' }, { groupId: 'extra', optionId: 'syr' }, { groupId: 'extra', optionId: 'cr' }] }], m),
  /en fazla 2/);
  assert.throws(() => A.priceCart([{ productId: 'brownie', qty: 1, options: [{ groupId: 'size', optionId: 's' }] }], m),
    /bu ürüne ait değil/);
  assert.throws(() => A.priceCart([{ productId: 'latte', qty: 1, options: [{ groupId: 'size', optionId: 'xx' }] }], m),
    /menüde yok/);
  assert.throws(() => A.priceCart([{ productId: 'latte', qty: 1, options: [{ groupId: 'size', optionId: 's' },
    { groupId: 'size', optionId: 's' }] }], m), /iki kez/);
});

test('sepet: tükenen, gizli ürün ve seçenek; sınırlar', () => {
  const m = menu();
  assert.throws(() => A.priceCart([{ productId: 'gone', qty: 1 }], m), /tükendi/);
  assert.throws(() => A.priceCart([{ productId: 'hidden', qty: 1 }], m), /menüde yok/);
  assert.throws(() => A.priceCart([{ productId: 'off', qty: 1 }], m), /menüde yok/);
  assert.throws(() => A.priceCart([{ productId: 'nope', qty: 1 }], m), /menüde yok/);
  assert.throws(() => A.priceCart([{ productId: 'latte', qty: 1, options: [{ groupId: 'size', optionId: 's' },
    { groupId: 'milk', optionId: 'soy' }] }], m), /Soya tükendi/);
  assert.throws(() => A.priceCart([], m), /Sepet boş/);
  assert.throws(() => A.priceCart([{ productId: 'brownie', qty: 21 }], m), /Adet/);
  assert.throws(() => A.priceCart([{ productId: 'brownie', qty: 0 }], m), /Adet/);
  assert.throws(() => A.priceCart(Array.from({ length: 3 }, () => ({ productId: 'brownie', qty: 20 })), m), /en fazla 50 ürün/);
  m.products.get('brownie').price = 200_000;
  assert.throws(() => A.priceCart([{ productId: 'brownie', qty: 2 }], m), /tutarı sınırı/);
  assert.throws(() => A.priceCart([{ productId: 'brownie', qty: 1, note: 'x'.repeat(121) }], m), /Not/);
});

test('gel-al saati: hemen, dakika sonra, saat; sınırlar', () => {
  const now = Date.parse('2026-10-17T12:00:00Z');
  assert.equal(A.pickupAt({ asap: true }, now, 10), now + 10 * 60_000);
  assert.equal(A.pickupAt({ inMinutes: 30 }, now, 10), now + 30 * 60_000);
  assert.equal(A.pickupAt({ inMinutes: 5 }, now, 10), now + 10 * 60_000); // hazırlanma süresinden önce olamaz
  assert.equal(A.pickupAt({ at: '2026-10-17T13:00:00Z' }, now, 10), Date.parse('2026-10-17T13:00:00Z'));
  assert.throws(() => A.pickupAt({ at: '2026-10-17T12:05:00Z' }, now, 10), /En erken 10/);
  assert.throws(() => A.pickupAt({ at: '2026-10-17T15:30:00Z' }, now, 10), /3 saat/);
  assert.throws(() => A.pickupAt({}, now, 10), /seçilmelidir/);
});

test('fişlerden durum', () => {
  assert.equal(A.progressFrom(['new', 'new']), 'accepted');
  assert.equal(A.progressFrom(['preparing', 'new']), 'preparing');
  assert.equal(A.progressFrom(['ready', 'new']), 'preparing');
  assert.equal(A.progressFrom(['ready', 'served']), 'ready');
  assert.equal(A.progressFrom([]), 'accepted');
});

test('kasa çevrimiçi: mutfak ekranı ve iptal edilen sayılmaz', () => {
  const now = 1_000_000;
  assert.equal(A.kasaOnline([{ lastSeenMs: now - 60_000 }], now), true);
  assert.equal(A.kasaOnline([{ lastSeenMs: now - 130_000 }], now), false);
  assert.equal(A.kasaOnline([{ kind: 'kds', lastSeenMs: now }], now), false);
  assert.equal(A.kasaOnline([{ revoked: true, lastSeenMs: now }], now), false);
});
