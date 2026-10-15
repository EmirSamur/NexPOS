// Sipariş işlemleri (4. ekran): terminal kuyruğundan gelen adisyon işlemleri.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc, getDocs, collection } = require('firebase/firestore');

const OWNER = { email: 'siparis-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Sipariş Sahibi', pin: '482913' };
let owner;
let term;
let ownerId;
let waiter;
let manager;
let cashier;
let tables;
let latte;
let cake;
let seq = 0;
const AT = '2026-10-15T12:00:00+03:00';

before(async () => {
  ownerId = createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  ({ staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson', role: 'waiter', pin: '730591' }));
  ({ staffId: cashier } = await owner.call('manageStaff', { action: 'create', name: 'Kasa', role: 'cashier', pin: '640218' }));
  ({ staffId: manager } = await owner.call('manageStaff', { action: 'create', name: 'Müdür', role: 'manager',
    email: 'siparis-mudur@kafe.test', password: 'mudur-sifre-1', pin: '583920' }));
  const { id: areaId } = await owner.call('saveArea', { name: 'Sipariş Salonu' });
  const plan = await owner.call('saveFloorPlan', { areaId, expectedVersion: 0, fixtures: [], tables: [1, 2, 3, 4].map((n) => (
    { tempId: `m${n}`, name: `S${n}`, shape: 'square', capacity: 4, x: 60 + n * 140, y: 60, w: 120, h: 120, rotation: 0 })) });
  tables = plan.created;
  const { id: catId } = await owner.call('saveCategory', { name: 'Sipariş Kahve', stampEligible: true });
  ({ id: latte } = await owner.call('saveProduct', { categoryId: catId, name: 'Latte', price: 9500 }));
  ({ id: cake } = await owner.call('saveProduct', { categoryId: catId, name: 'Kek', price: 7000 }));
  const reg = await owner.call('registerTerminal', { name: 'Sipariş Kasa' });
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(closeAll);

const op = (name, payload, staffId = waiter) => ({ opId: `ord-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId, createdAt: AT });
const sync = async (...ops) => (await term.call('syncOps', { ops })).results;
const order = async (id) => (await adminDb.doc(`orders/${id}`).get()).data();
const table = async (id) => (await adminDb.doc(`tables/${id}`).get()).data();
const item = (lineId, productId, unitPrice, qty = 1, station = 'bar', extra = {}) =>
  ({ lineId, productId, name: 'Ürün', unitPrice, qty, station, stampEligible: true, ...extra });

test('masa aç → ekle → gönder → hesap iste → nakit öde', async () => {
  const r = await sync(
    op('openOrder', { orderId: 'O1', no: 'A1', businessDay: '2026-10-15', type: 'dine_in', tableId: tables.m1, tableName: 'S1' }),
    op('addItems', { orderId: 'O1', items: [item('l1', latte, 9500, 2), item('l2', cake, 6000, 1, 'kitchen', { stampEligible: false })] }),
    op('sendItems', { orderId: 'O1', lineIds: ['l1', 'l2'], ticketIds: { bar: 'TK-O1-bar', kitchen: 'TK-O1-kit' } }),
  );
  assert.deepEqual(r.map((x) => x.status), ['ok', 'ok', 'ok']);
  assert.equal((await order('O1')).total, 25000);
  assert.deepEqual([(await table(tables.m1)).status, (await table(tables.m1)).currentOrderId], ['occupied', 'O1']);
  const bar = (await adminDb.doc('kitchenTickets/TK-O1-bar').get()).data();
  assert.deepEqual([bar.station, bar.lines[0].qty, bar.status, bar.orderNo], ['bar', 2, 'new', 'A1']);
  assert.ok((await adminDb.doc('kitchenTickets/TK-O1-kit').get()).exists);

  // Kek menüde 70 ₺, terminal 60 ₺ ile sattı → terminal fiyatı geçerli, kayda düşer
  const mism = await adminDb.collection('auditLogs').where('action', '==', 'price_mismatch').get();
  const m = mism.docs.map((d) => d.data()).find((x) => x.target === 'orders/O1');
  assert.deepEqual([m.after[0].terminal, m.after[0].menu], [6000, 7000]);

  await sync(op('requestBill', { orderId: 'O1', value: true }));
  assert.equal((await table(tables.m1)).status, 'bill_requested');
  await sync(op('takePayment', { orderId: 'O1', paymentId: 'PAY-O1', method: 'cash', amount: 25000, received: 30000 }));
  const o = await order('O1');
  assert.deepEqual([o.status, o.paid, o.stamps], ['paid', 25000, 2]);
  assert.equal((await table(tables.m1)).status, 'empty');
  const pay = (await adminDb.doc('payments/PAY-O1').get()).data();
  assert.deepEqual([pay.method, pay.change, pay.businessDay], ['cash', 5000, '2026-10-15']);
});

test('aynı işlem iki kez gelirse bir kez uygulanır', async () => {
  const open = op('openOrder', { orderId: 'O2', no: 'A2', businessDay: '2026-10-15', type: 'dine_in', tableId: tables.m2, tableName: 'S2' });
  const add = op('addItems', { orderId: 'O2', items: [item('l1', latte, 9500)] });
  await sync(open, add);
  const again = await sync(open, add);
  assert.deepEqual(again.map((x) => x.status), ['duplicate', 'duplicate']);
  assert.equal((await order('O2')).items.length, 1);
});

test('yetki: garson iptal/iskonto yapamaz, onaylayanla yapar; toplamı sunucu hesaplar', async () => {
  await sync(op('sendItems', { orderId: 'O2', lineIds: ['l1'], ticketIds: { bar: 'TK-O2', kitchen: 'TK-O2k' } }));
  let [r] = await sync(op('voidItem', { orderId: 'O2', lineId: 'l1', reason: 'Vazgeçti' }));
  assert.equal(r.status, 'rejected');
  assert.match(r.error, /voidItem/);
  [r] = await sync(op('setDiscount', { orderId: 'O2', discount: { type: 'percent', value: 10 } }));
  assert.equal(r.status, 'rejected');
  [r] = await sync(op('setDiscount', { orderId: 'O2', discount: { type: 'percent', value: 10 }, approvedBy: cashier, reason: 'Sürekli müşteri' }));
  assert.equal(r.status, 'ok');
  await sync(op('addItems', { orderId: 'O2', items: [item('l2', latte, 9500)] }));
  assert.deepEqual([(await order('O2')).discountAmount, (await order('O2')).total], [1900, 17100]); // üst üste binmez
  [r] = await sync(op('voidItem', { orderId: 'O2', lineId: 'l1', reason: 'Vazgeçti', approvedBy: manager }));
  assert.equal(r.status, 'ok');
  const voided = (await order('O2')).items.find((l) => l.lineId === 'l1');
  assert.deepEqual([voided.status, voided.approvedBy], ['void', manager]);
  const logs = await adminDb.collection('auditLogs').where('action', '==', 'order_void').get();
  assert.ok(logs.docs.some((d) => d.data().approvedBy === manager));
});

test('taşıma, dolu masaya açma, birleştirme, iptal', async () => {
  // Dolu masaya yeni adisyon açılamaz
  let [r] = await sync(op('openOrder', { orderId: 'O3', no: 'A3', businessDay: '2026-10-15', type: 'dine_in', tableId: tables.m2, tableName: 'S2' }));
  assert.match(r.error, /açık bir adisyon/);
  // O2: S2 → S3
  [r] = await sync(op('moveOrder', { orderId: 'O2', toTableId: tables.m3, toTableName: 'S3' }));
  assert.equal(r.status, 'ok');
  assert.equal((await table(tables.m2)).status, 'empty');
  assert.equal((await table(tables.m3)).currentOrderId, 'O2');
  // O4 S4'te açılır, O2 ile birleşir
  await sync(
    op('openOrder', { orderId: 'O4', no: 'A4', businessDay: '2026-10-15', type: 'dine_in', tableId: tables.m4, tableName: 'S4' }),
    op('addItems', { orderId: 'O4', items: [item('k1', cake, 7000)] }),
  );
  [r] = await sync(op('moveOrder', { orderId: 'O4', toTableId: tables.m3, toTableName: 'S3' }));
  assert.match(r.error, /dolu/);
  [r] = await sync(op('mergeOrders', { orderId: 'O2', sourceOrderId: 'O4' }));
  assert.equal(r.status, 'ok');
  assert.equal((await order('O4')).status, 'merged');
  assert.equal((await table(tables.m4)).status, 'empty');
  assert.ok((await order('O2')).items.some((l) => l.lineId === 'k1'));
  // Gönderilmiş ürünü olan adisyonu garson tek başına iptal edemez
  await sync(op('sendItems', { orderId: 'O2', lineIds: ['l2', 'k1'], ticketIds: { bar: 'TK-O2b', kitchen: 'TK-O2c' } }));
  [r] = await sync(op('cancelOrder', { orderId: 'O2', reason: 'Müşteri gitti' }));
  assert.equal(r.status, 'rejected');
  [r] = await sync(op('cancelOrder', { orderId: 'O2', reason: 'Müşteri gitti', approvedBy: manager }));
  assert.equal(r.status, 'ok');
  assert.equal((await table(tables.m3)).status, 'empty');
});

test('masasız sipariş, fiş durumu, rezerve, kurallara aykırı işlem', async () => {
  let r = await sync(
    op('openOrder', { orderId: 'O5', no: 'A5', businessDay: '2026-10-15', type: 'takeaway' }),
    op('addItems', { orderId: 'O5', items: [item('t1', latte, 9500)] }),
    op('sendItems', { orderId: 'O5', lineIds: ['t1'], ticketIds: { bar: 'TK-O5', kitchen: 'TK-O5k' } }),
    op('updateTicket', { ticketId: 'TK-O5', status: 'ready' }),
    op('takePayment', { orderId: 'O5', paymentId: 'PAY-O5', method: 'card', amount: 9500, tip: 1000 }),
    op('setTableReserved', { tableId: tables.m1, reserved: true }),
    op('addItems', { orderId: 'O5', items: [item('t2', latte, 9500)] }),
  );
  assert.deepEqual(r.map((x) => x.status), ['ok', 'ok', 'ok', 'ok', 'ok', 'ok', 'rejected']);
  assert.match(r[6].error, /kapanmış/);
  assert.equal((await adminDb.doc('kitchenTickets/TK-O5').get()).data().status, 'ready');
  assert.equal((await adminDb.doc('payments/PAY-O5').get()).data().tip, 1000);
  assert.equal((await table(tables.m1)).status, 'reserved');
});

test('kurallar: siparişler herkese açık değil', async () => {
  const anon = client();
  await expectDenied(getDoc(doc(anon.db, 'orders/O1')));
  await expectDenied(getDocs(collection(anon.db, 'payments')));
  assert.equal((await getDoc(doc(owner.db, 'orders/O1'))).data().status, 'paid');
  assert.equal((await getDoc(doc(term.db, 'kitchenTickets/TK-O1-bar'))).data().station, 'bar');
});
