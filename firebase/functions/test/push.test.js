// Bildirim kuralları: sipariş durumu metinleri, izin ve günlük sınır, günlük doğum günü / süre doluyor.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const P = require('../src/push');
const { addDays } = require('../src/loyalty');

test('sipariş durumu: yalnızca değişince ve bilinen durumlarda', () => {
  assert.equal(P.orderMessage({ status: 'pending' }, { status: 'pending' }), null);
  assert.equal(P.orderMessage({ status: 'ready' }, { status: 'completed' }), null);
  const m = P.orderMessage({ status: 'preparing' }, { id: 'a1', status: 'ready', kind: 'pickup', orderNo: 'A7' });
  assert.deepEqual(m, { title: 'Siparişin hazır 🔔', body: 'A7 · Gelip alabilirsin.', data: { type: 'appOrder', id: 'a1', status: 'ready' } });
  assert.equal(P.orderMessage({ status: 'pending' }, { status: 'rejected', reason: 'Ürün bitti' }).body, 'Ürün bitti');
  assert.equal(P.orderMessage({ status: 'pending' }, { status: 'ready', kind: 'table' }).body, 'Birazdan masanda.');
});

test('izin: sipariş her zaman, ödül izinle, kampanya izin + günde 1', () => {
  const c = { marketingConsent: true };
  assert.equal(P.allowed({ marketingConsent: false }, 'order', '2026-10-17'), true);
  assert.equal(P.allowed({ marketingConsent: false }, 'loyalty', '2026-10-17'), false);
  assert.equal(P.allowed(c, 'marketing', '2026-10-17'), true);
  assert.equal(P.allowed({ ...c, lastMarketingPushDay: '2026-10-17' }, 'marketing', '2026-10-17'), false);
  assert.equal(P.allowed({ ...c, lastMarketingPushDay: '2026-10-17' }, 'loyalty', '2026-10-17'), true);
  assert.equal(P.allowed({ ...c, deleted: true }, 'order', '2026-10-17'), false);
});

test('ödül ve günlük bildirimler', () => {
  assert.equal(P.rewardMessage({ type: 'free_drink', status: 'active', expiresAt: '2026-12-16' }).body,
    'Bir içecek bizden. Son kullanma: 16.12.2026');
  assert.equal(P.rewardMessage({ type: 'campaign', status: 'active', expiresAt: '2026-12-16' }), null);
  const out = P.dailyMessages([{ id: 'c1', birthDate: '10-17' }, { id: 'c2', birthDate: '10-18' }],
    [{ id: 'r1', customerId: 'c3', status: 'active', expiresAt: '2026-10-24' },
      { id: 'r2', customerId: 'c4', status: 'used', expiresAt: '2026-10-24' }], '2026-10-17', addDays);
  assert.deepEqual(out.map((m) => [m.customerId, m.title]), [['c1', 'Doğum günün kutlu olsun 🎂'], ['c3', 'Ödülünü unutma 🎁']]);
});
