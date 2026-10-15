// Mutfak / bar ekranı (5. ekran): eşleme, cihaz hesabının sınırları, fiş durumu, iptal ve taşıma.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll, deleteApp } =
  require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc, getDocs, collection, query, where } = require('firebase/firestore');

const OWNER = { email: 'kds-sahip@kafe.test', password: 'sahip-sifre-1', name: 'KDS Sahibi', pin: '482913' };
let owner;
let pos;
let waiter;
let manager;
let tables;
let areaId;
let seq = 0;
const AT = '2026-10-15T12:00:00+03:00';

before(async () => {
  createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  ({ staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson KDS', role: 'waiter', pin: '730591' }));
  ({ staffId: manager } = await owner.call('manageStaff', { action: 'create', name: 'Müdür KDS', role: 'manager',
    email: 'kds-mudur@kafe.test', password: 'mudur-sifre-1', pin: '583920' }));
  ({ id: areaId } = await owner.call('saveArea', { name: 'KDS Salonu' }));
  const plan = await owner.call('saveFloorPlan', { areaId, expectedVersion: 0, fixtures: [], tables: [1, 2].map((n) => (
    { tempId: `k${n}`, name: `K${n}`, shape: 'square', capacity: 4, x: 60 + n * 140, y: 60, w: 120, h: 120, rotation: 0 })) });
  tables = plan.created;
  const reg = await owner.call('registerTerminal', { name: 'KDS Kasa' });
  pos = client();
  await signInWithCustomToken(pos.auth, reg.customToken);
});
after(async () => {
  await adminDb.doc(`areas/${areaId}`).delete();
  await Promise.all(Object.values(tables).map((id) => adminDb.doc(`tables/${id}`).delete()));
  await closeAll();
});

const op = (name, payload, staffId = waiter) => ({ opId: `kds-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId, createdAt: AT });
const sync = async (...ops) => (await pos.call('syncOps', { ops })).results;
const ticket = async (id) => (await adminDb.doc(`kitchenTickets/${id}`).get()).data();
const line = (lineId, name, station, qty = 1) => ({ lineId, productId: null, name, unitPrice: 5000, qty, station });

async function pairTablet(station, name) {
  const { code } = await owner.call('createKdsPairingCode', { name });
  assert.match(code, /^\d{6}$/);
  const tablet = client();
  const res = await tablet.call('pairKds', { code, station });
  await signInWithCustomToken(tablet.auth, res.customToken);
  return { tablet, terminalId: res.terminalId, code };
}

test('eşleme: kod tek kullanımlık, garson kod üretemez, hatalı kod reddedilir', async () => {
  const { tablet, terminalId, code } = await pairTablet('kitchen', 'Mutfak tableti');
  const term = (await adminDb.doc(`terminals/${terminalId}`).get()).data();
  assert.deepEqual([term.kind, term.station, term.letter, term.revoked], ['kds', 'kitchen', null, false]);
  const again = client();
  await expectCallError(again.call('pairKds', { code, station: 'bar' }), 'not-found');
  await expectCallError(again.call('pairKds', { code: '12a456', station: 'bar' }), 'invalid-argument');
  await expectCallError(again.call('pairKds', { code: '000000', station: 'grill' }), 'invalid-argument');
  // Süresi dolan kod
  const { code: old } = await owner.call('createKdsPairingCode', {});
  await adminDb.doc(`kdsPairings/${old}`).update({ expiresAt: new Date(Date.now() - 1000) });
  await expectCallError(again.call('pairKds', { code: old, station: 'bar' }), 'not-found');
  await deleteApp(again.app);
  const manager = await signedInAs('kds-mudur@kafe.test', 'mudur-sifre-1');
  // Kod üretmek settings yetkisi ister (müdürde varsayılan olarak yok)
  await expectCallError(manager.call('createKdsPairingCode', {}), 'permission-denied');
  await deleteApp(manager.app);
  await deleteApp(tablet.app);
});

test('mutfak ekranı yalnızca fişleri ve modül ayarını okur; kasa fonksiyonlarını çağıramaz', async () => {
  const { tablet, terminalId } = await pairTablet('kitchen', 'Okuma testi');
  await getDocs(collection(tablet.db, 'kitchenTickets'));
  await getDoc(doc(tablet.db, 'settings/modules'));
  await getDoc(doc(tablet.db, `terminals/${terminalId}`));
  await expectDenied(getDocs(collection(tablet.db, 'staffPins')));
  await expectDenied(getDocs(collection(tablet.db, 'staff')));
  await expectDenied(getDocs(collection(tablet.db, 'orders')));
  await expectDenied(getDoc(doc(tablet.db, 'settings/permissions')));
  await expectCallError(tablet.call('syncOps', { ops: [op('staffLogin', {})] }), 'permission-denied');
  // Kasa terminali de mutfak fonksiyonunu çağıramaz
  await expectCallError(pos.call('updateKitchenTicket', { ticketId: 'x', status: 'ready' }), 'permission-denied');
  await tablet.call('terminalHeartbeat', { pending: 0, appVersion: 'kds-1' });
  await deleteApp(tablet.app);
});

test('fiş: Başla → Hazır → Geri al, satır işaretleme, istasyon sınırı', async () => {
  const r = await sync(
    op('openOrder', { orderId: 'KO1', no: 'K1', businessDay: '2026-10-15', type: 'dine_in', tableId: tables.k1, tableName: 'K1' }),
    op('addItems', { orderId: 'KO1', items: [line('t1', 'Tost', 'kitchen', 2), line('m1', 'Menemen', 'kitchen'),
      line('l1', 'Latte', 'bar')] }),
    op('sendItems', { orderId: 'KO1', lineIds: ['t1', 'm1', 'l1'], ticketIds: { kitchen: 'KT-KO1-k', bar: 'KT-KO1-b' } }),
  );
  assert.deepEqual(r.map((x) => x.status), ['ok', 'ok', 'ok']);
  const { tablet } = await pairTablet('kitchen', 'Akış');
  const live = await getDocs(query(collection(tablet.db, 'kitchenTickets'), where('status', 'in', ['new', 'preparing']),
    where('station', '==', 'kitchen')));
  assert.ok(live.docs.some((d) => d.id === 'KT-KO1-k'));
  assert.ok(!live.docs.some((d) => d.id === 'KT-KO1-b'));

  await tablet.call('updateKitchenTicket', { ticketId: 'KT-KO1-k', status: 'preparing' });
  await tablet.call('updateKitchenTicket', { ticketId: 'KT-KO1-k', doneLineIds: ['t1', 'yok'] });
  let t = await ticket('KT-KO1-k');
  assert.deepEqual([t.status, t.doneLineIds, typeof t.preparingAt], ['preparing', ['t1'], 'string']);
  await tablet.call('updateKitchenTicket', { ticketId: 'KT-KO1-k', status: 'ready' });
  assert.equal((await ticket('KT-KO1-k')).status, 'ready');
  await tablet.call('updateKitchenTicket', { ticketId: 'KT-KO1-k', status: 'preparing' }); // geri al
  assert.equal((await ticket('KT-KO1-k')).status, 'preparing');
  await expectCallError(tablet.call('updateKitchenTicket', { ticketId: 'KT-KO1-b', status: 'ready' }), 'permission-denied');
  await expectCallError(tablet.call('updateKitchenTicket', { ticketId: 'KT-KO1-k', status: 'served' }), 'invalid-argument');

  // Kasa teslim edince mutfak artık değiştiremez
  await sync(op('updateTicket', { ticketId: 'KT-KO1-k', status: 'served' }));
  await expectCallError(tablet.call('updateKitchenTicket', { ticketId: 'KT-KO1-k', status: 'ready' }), 'failed-precondition');
  await deleteApp(tablet.app);
});

test('iptal edilen ürün ve adisyon fişe yansır; taşınan masanın adı güncellenir', async () => {
  await sync(
    op('openOrder', { orderId: 'KO2', no: 'K2', businessDay: '2026-10-15', type: 'dine_in', tableId: tables.k2, tableName: 'K2' }),
    op('addItems', { orderId: 'KO2', items: [line('a', 'Tost', 'kitchen'), line('b', 'Omlet', 'kitchen')] }),
    op('sendItems', { orderId: 'KO2', lineIds: ['a', 'b'], ticketIds: { kitchen: 'KT-KO2' } }),
  );
  const [voided] = await sync(op('voidItem', { orderId: 'KO2', lineId: 'b', reason: 'Vazgeçti', approvedBy: manager }));
  assert.equal(voided.status, 'ok');
  let t = await ticket('KT-KO2');
  assert.deepEqual(t.lines.map((l) => !!l.voided), [false, true]);

  // K1'i boşaltıp KO2'yi oraya taşı
  await sync(op('cancelOrder', { orderId: 'KO1', reason: 'Test', approvedBy: manager }));
  const [moved] = await sync(op('moveOrder', { orderId: 'KO2', toTableId: tables.k1, toTableName: 'K1' }));
  assert.equal(moved.status, 'ok');
  assert.equal((await ticket('KT-KO2')).tableName, 'K1');
  assert.equal((await ticket('KT-KO1-b')).cancelled, true); // KO1 iptali bar fişine de düştü

  await sync(op('cancelOrder', { orderId: 'KO2', reason: 'Müşteri gitti', approvedBy: manager }));
  t = await ticket('KT-KO2');
  assert.equal(t.cancelled, true);
  assert.ok(t.lines.every((l) => l.voided));
});

test('iptal edilen mutfak ekranı okuyamaz ve fiş güncelleyemez', async () => {
  const { tablet, terminalId } = await pairTablet('all', 'İptal testi');
  await owner.call('revokeTerminal', { terminalId });
  await expectDenied(getDocs(collection(tablet.db, 'kitchenTickets')));
  await expectCallError(tablet.call('updateKitchenTicket', { ticketId: 'KT-KO2', status: 'ready' }), 'permission-denied');
  assert.equal((await getDoc(doc(tablet.db, `terminals/${terminalId}`))).data().revoked, true);
  await deleteApp(tablet.app);
});
