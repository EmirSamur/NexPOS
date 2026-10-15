// Mutfak ekranının saf hesapları (hosting/mutfak/kds-logic.js, tarayıcı modülü).
const { test, before } = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { pathToFileURL } = require('url');

let k;
before(async () => {
  k = await import(pathToFileURL(path.join(__dirname, '../../hosting/mutfak/kds-logic.js')).href);
});

const T0 = Date.parse('2026-10-15T12:00:00+03:00');
const ticket = (id, createdMin, lines, extra = {}) => ({
  id, createdAt: new Date(T0 + createdMin * 60000).toISOString(), status: 'new', type: 'dine_in', tableName: '5',
  orderNo: 'A1', lines, doneLineIds: [], ...extra,
});

test('gecikme rengi: 10 dk sarı, 20 dk kırmızı', () => {
  const t = ticket('a', 0, []);
  assert.equal(k.ageClass(t.createdAt, T0 + 9.9 * 60000, 10, 20), 'ok');
  assert.equal(k.ageClass(t.createdAt, T0 + 10 * 60000, 10, 20), 'warn');
  assert.equal(k.ageClass(t.createdAt, T0 + 20 * 60000, 10, 20), 'late');
});

test('geçen süre biçimi', () => {
  assert.equal(k.formatElapsed(125000), '02:05');
  assert.equal(k.formatElapsed(3725000), '1:02:05');
  assert.equal(k.formatElapsed(-5), '00:00');
});

test('toplu bekleyen: işaretlenen, iptal edilen satır ve iptal edilen fiş sayılmaz', () => {
  const tickets = [
    ticket('a', 0, [{ lineId: '1', name: 'Tost', qty: 2 }, { lineId: '2', name: 'Menemen', qty: 1 }], { doneLineIds: ['2'] }),
    ticket('b', 1, [{ lineId: '3', name: 'Tost', qty: 1 }, { lineId: '4', name: 'Kek', qty: 1, voided: true }]),
    ticket('c', 2, [{ lineId: '5', name: 'Omlet', qty: 4 }], { cancelled: true }),
  ];
  assert.deepEqual(k.allDay(tickets), [{ name: 'Tost', qty: 3 }]);
});

test('filtre ve sıralama: en eski üstte', () => {
  const list = [ticket('b', 5, [], { status: 'preparing' }), ticket('a', 1, []), ticket('c', 3, [])];
  assert.deepEqual(k.visibleTickets(list, 'all').map((t) => t.id), ['a', 'c', 'b']);
  assert.deepEqual(k.visibleTickets(list, 'preparing').map((t) => t.id), ['b']);
});

test('satır işaretleme açılıp kapanır; iptal edilen satır işaretlenmez', () => {
  const t = ticket('a', 0, [{ lineId: '1', name: 'Tost', qty: 1 }, { lineId: '2', name: 'Kek', qty: 1, voided: true }]);
  assert.deepEqual(k.toggleDone(t, '1'), ['1']);
  assert.deepEqual(k.toggleDone({ ...t, doneLineIds: ['1'] }, '1'), []);
  assert.equal(k.toggleDone(t, '2'), null);
  assert.equal(k.whereLabel({ type: 'takeaway' }), 'PAKET');
  assert.equal(k.whereLabel(t), 'MASA 5');
  assert.equal(k.whereLabel({ ...t, tableName: 'Bahçe 3' }), 'BAHÇE 3');
  assert.equal(k.whereLabel({ ...t, tableName: 'iç salon 1' }), 'İÇ SALON 1');
});
