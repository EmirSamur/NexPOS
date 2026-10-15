// Kasa (6. ekran) ve modüller: bölme, iade, kasa oturumu, zorunlu kasa açılışı.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll, deleteApp } =
  require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc } = require('firebase/firestore');

const OWNER = { email: 'kasa-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Kasa Sahibi', pin: '482913' };
let owner;
let ownerId;
let term;
let terminalId;
let waiter;
let cashier;
let latte;
let catId;
let seq = 0;
const AT = '2026-10-15T12:00:00+03:00';

before(async () => {
  ownerId = createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  ({ staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson K', role: 'waiter', pin: '730591' }));
  ({ staffId: cashier } = await owner.call('manageStaff', { action: 'create', name: 'Kasiyer K', role: 'cashier', pin: '640218' }));
  ({ id: catId } = await owner.call('saveCategory', { name: 'Kasa Kahve' }));
  ({ id: latte } = await owner.call('saveProduct', { categoryId: catId, name: 'Kasa Latte', price: 10000 }));
  const reg = await owner.call('registerTerminal', { name: 'Kasa Test' });
  terminalId = reg.terminalId;
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(async () => {
  // Menü testleri boş menü bekler; bu dosyanın açtığı menü ve modül ayarı silinir.
  await Promise.all([adminDb.doc('settings/modules').delete(), adminDb.doc(`categories/${catId}`).delete(),
    adminDb.doc(`products/${latte}`).delete()]);
  await closeAll();
});

const op = (name, payload, staffId = cashier) => ({ opId: `cash-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId, createdAt: AT });
const sync = async (...ops) => (await term.call('syncOps', { ops })).results;
const order = async (id) => (await adminDb.doc(`orders/${id}`).get()).data();
const item = (lineId, unitPrice, qty = 1) => ({ lineId, productId: latte, name: 'Kasa Latte', unitPrice, qty, station: 'bar' });

// Masasız (paket) adisyon aç, ekle, gönder
async function takeaway(id, items) {
  const r = await sync(
    op('openOrder', { orderId: id, no: `K${seq}`, businessDay: '2026-10-15', type: 'takeaway' }, waiter),
    op('addItems', { orderId: id, items }, waiter),
    op('sendItems', { orderId: id, lineIds: items.map((i) => i.lineId), ticketIds: { bar: `TK-${id}` } }, waiter),
  );
  assert.deepEqual(r.map((x) => x.status), ['ok', 'ok', 'ok']);
}

test('modüller: yalnızca yönetici kaydeder, doğrulanır, personel ve terminal okur', async () => {
  const saved = await owner.call('saveModules', { kds: { enabled: true, warnMinutes: 8, lateMinutes: 15 },
    cashSession: { required: true } });
  assert.deepEqual([saved.kds.enabled, saved.kds.warnMinutes, saved.cashSession.required, saved.paymentMethods.cash],
    [true, 8, true, true]);
  await expectCallError(owner.call('saveModules', { kds: { warnMinutes: 20, lateMinutes: 10 } }), 'invalid-argument');
  await expectCallError(owner.call('saveModules', { paymentMethods: { cash: false, card: false, meal: false } }),
    'invalid-argument');

  await owner.call('manageStaff', { action: 'create', name: 'Kasa Müdür', role: 'manager',
    email: 'kasa-mudur@kafe.test', password: 'mudur-sifre-1', pin: '583920' });
  const manager = await signedInAs('kasa-mudur@kafe.test', 'mudur-sifre-1');
  await expectCallError(manager.call('saveModules', {}), 'permission-denied');
  assert.equal((await getDoc(doc(manager.db, 'settings/modules'))).data().kds.lateMinutes, 15);
  await deleteApp(manager.app);
  assert.equal((await getDoc(doc(term.db, 'settings/modules'))).data().cashSession.required, true);
  const log = await adminDb.collection('auditLogs').where('action', '==', 'modules_change').get();
  assert.ok(log.size >= 1);
});

test('zorunlu kasa: oturum yokken nakit alınamaz, kart alınır', async () => {
  await owner.call('saveModules', { cashSession: { required: true } });
  await takeaway('KZ1', [item('l1', 10000)]);
  const [cash] = await sync(op('takePayment', { orderId: 'KZ1', paymentId: 'KZ1-P1', method: 'cash', amount: 5000 }));
  assert.equal(cash.status, 'rejected');
  assert.match(cash.error, /Kasa açılmadan/);
  const [card] = await sync(op('takePayment', { orderId: 'KZ1', paymentId: 'KZ1-P2', method: 'card', amount: 10000 }));
  assert.equal(card.status, 'ok');
});

test('kasa oturumu: aç, hareket, ödeme, iade, kapat → beklenen nakit sunucuda hesaplanır', async () => {
  await owner.call('saveModules', { cashSession: { required: true, diffReasonThreshold: 1000 } });
  const S = 'CS-1';
  // Garsonun kasa yetkisi yok
  const [denied] = await sync(op('openCashSession', { cashSessionId: S, businessDay: '2026-10-15', openingCash: 50000 }, waiter));
  assert.equal(denied.status, 'rejected');
  const [opened] = await sync(op('openCashSession', { cashSessionId: S, businessDay: '2026-10-15', openingCash: 50000 }));
  assert.equal(opened.status, 'ok');
  const [second] = await sync(op('openCashSession', { cashSessionId: 'CS-2', businessDay: '2026-10-15', openingCash: 0 }));
  assert.match(second.error, /açık bir kasa oturumu/);

  // Ürün seçerek bölme: 3 latteden 1'i ayrılır, önce o ödenir (nakit), kalanı kartla
  await takeaway('KS1', [item('a', 10000, 3), item('b', 5000)]);
  const r = await sync(
    op('splitLine', { orderId: 'KS1', lineId: 'a', qty: 1, newLineId: 'a2' }),
    op('takePayment', { orderId: 'KS1', paymentId: 'KS1-P1', method: 'cash', amount: 10000, received: 20000,
      lineIds: ['a2'], cashSessionId: S }),
    op('takePayment', { orderId: 'KS1', paymentId: 'KS1-P2', method: 'card', amount: 25000, tip: 2000,
      lineIds: ['a', 'b'], cashSessionId: S }),
  );
  assert.deepEqual(r.map((x) => x.status), ['ok', 'ok', 'ok']);
  const o = await order('KS1');
  assert.deepEqual([o.status, o.items.map((l) => l.paidBy)], ['paid', ['KS1-P2', 'KS1-P1', 'KS1-P2']]);
  const p1 = (await adminDb.doc('payments/KS1-P1').get()).data();
  assert.deepEqual([p1.cashSessionId, p1.lineIds, p1.change], [S, ['a2'], 10000]);

  // İade: kasiyerin refund yetkisi yok → müdür onayıyla
  const [noPerm] = await sync(op('refundPayment', { orderId: 'KS1', refundId: 'KS1-R1', method: 'cash', amount: 3000,
    reason: 'Soğuk geldi', cashSessionId: S }));
  assert.match(noPerm.error, /refund/);
  const [refunded] = await sync(op('refundPayment', { orderId: 'KS1', refundId: 'KS1-R1', method: 'cash', amount: 3000,
    reason: 'Soğuk geldi', approvedBy: ownerId, cashSessionId: S }));
  assert.equal(refunded.status, 'ok');
  assert.deepEqual([(await order('KS1')).refunded, (await order('KS1')).status], [3000, 'paid']);
  const rdoc = (await adminDb.doc('refunds/KS1-R1').get()).data();
  assert.deepEqual([rdoc.amount, rdoc.approvedBy, rdoc.orderNo], [3000, ownerId, o.no]);
  const [over] = await sync(op('refundPayment', { orderId: 'KS1', refundId: 'KS1-R2', method: 'card', amount: 33000,
    reason: 'x', approvedBy: ownerId }));
  assert.match(over.error, /aşamaz/);

  // Kasa hareketleri
  const mv = await sync(
    op('cashMovement', { cashSessionId: S, movementId: 'M1', type: 'in', amount: 2000, reason: 'Bozuk para' }),
    op('cashMovement', { cashSessionId: S, movementId: 'M2', type: 'out', amount: 4000, reason: 'Süt', expense: true }),
    op('cashMovement', { cashSessionId: S, movementId: 'M3', type: 'out', amount: 100, reason: '' }),
  );
  assert.deepEqual(mv.map((x) => x.status), ['ok', 'ok', 'rejected']);

  // Beklenen: 50000 + 10000 − 3000 + 2000 − 4000 = 55000
  const [noReason] = await sync(op('closeCashSession', { cashSessionId: S, countedCash: 53000, expectedCash: 55000 }));
  assert.match(noReason.error, /gerekçe/);
  const [closed] = await sync(op('closeCashSession', { cashSessionId: S, countedCash: 53000, expectedCash: 55000,
    reason: 'Bozuk para eksik', report: { sales: 35000 } }));
  assert.equal(closed.status, 'ok');
  const cs = (await adminDb.doc(`cashSessions/${S}`).get()).data();
  assert.deepEqual([cs.status, cs.expectedCash, cs.difference, cs.differenceReason, cs.terminalId, cs.report.sales],
    ['closed', 55000, -2000, 'Bozuk para eksik', terminalId, 35000]);
  assert.equal(cs.movements.find((m) => m.movementId === 'M2').expense, true);

  // Kapalı oturuma ödeme yazılamaz
  await takeaway('KS2', [item('l1', 10000)]);
  const [late] = await sync(op('takePayment', { orderId: 'KS2', paymentId: 'KS2-P1', method: 'cash', amount: 10000,
    cashSessionId: S }));
  assert.match(late.error, /Kasa oturumu açık değil/);
});

test('kasa oturumları ve iadeler: terminal ve yönetici okur, giriş yapmayan okuyamaz, kimse yazamaz', async () => {
  assert.ok((await getDoc(doc(term.db, 'cashSessions/CS-1'))).exists());
  assert.ok((await getDoc(doc(owner.db, 'refunds/KS1-R1'))).exists());
  const anon = client();
  await expectDenied(getDoc(doc(anon.db, 'cashSessions/CS-1')));
  await deleteApp(anon.app);
});
