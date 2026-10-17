// Uygulama siparişleri (11b): masadan QR sipariş ve gel-al isteği → kasa onayı → adisyon → fişler → hazır → kapanış;
// red, süre dolması, sınırlar, kasa çevrimdışı, gelmedi, garson çağır / hesap iste, kurallar.
// (menü ve salon testlerinden sonra çalışsın diye adı orders_app: onlar boş menü/plan bekler)
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { getAuth } = require('firebase-admin/auth');
const { Timestamp } = require('firebase-admin/firestore');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc, getDocs, collection, query, where } = require('firebase/firestore');

const OWNER = { email: 'appsiparis-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Uygulama Sipariş', pin: '482917' };
let owner;
let ownerId;
let term;
let termId;
let tablet;
let table;
let latte;
let cookie;
let size;
let seq = 0;
const AT = '2026-11-03T12:00:00+03:00'; // diğer testlerin günlük özetine karışmasın

before(async () => {
  ownerId = createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  const { id: areaId } = await owner.call('saveArea', { name: 'Uygulama Salonu' });
  const plan = await owner.call('saveFloorPlan', { areaId, expectedVersion: 0, fixtures: [], tables: [{ tempId: 'u4', name: '4',
    shape: 'square', capacity: 4, x: 60, y: 60, w: 120, h: 120, rotation: 0 }] });
  const t = (await adminDb.doc(`tables/${plan.created.u4}`).get()).data();
  table = { id: plan.created.u4, t: t.qrToken };
  const { id: catId } = await owner.call('saveCategory', { name: 'Uygulama Kahve', stampEligible: true });
  ({ id: size } = await owner.call('saveOptionGroup', { name: 'Boy', selection: 'single', required: true,
    options: [{ id: 's', name: 'Küçük', priceDelta: 0 }, { id: 'l', name: 'Büyük', priceDelta: 1500 }] }));
  ({ id: latte } = await owner.call('saveProduct', { categoryId: catId, name: 'Latte', price: 9500, optionGroupIds: [size] }));
  ({ id: cookie } = await owner.call('saveProduct', { categoryId: catId, name: 'Kurabiye', price: 4000 }));
  await adminDb.doc('settings/modules').set({ app: { enabled: true, tableOrders: true, pickup: true } }, { merge: true });
  await owner.call('saveAppSettings', { cafeName: 'Velvet Kafe', pickupPrepMinutes: 10, acceptMinutes: 2 });
  const reg = await owner.call('registerTerminal', { name: 'Uygulama Kasası' });
  termId = reg.terminalId;
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
  const { code } = await owner.call('createKdsPairingCode', { name: 'Bar Tableti' });
  tablet = client();
  await signInWithCustomToken(tablet.auth, (await tablet.call('pairKds', { code, station: 'all' })).customToken);
});
after(closeAll);

async function customer(phone, name) {
  const uid = `ao-${++seq}-${Date.now()}`;
  await getAuth().createUser({ uid, phoneNumber: phone });
  const c = client();
  await signInWithCustomToken(c.auth, await getAuth().createCustomToken(uid));
  const r = await c.call('linkCustomer', { name, marketingConsent: false, kvkkAccepted: true });
  await c.auth.currentUser.getIdToken(true);
  c.customerId = r.customer.id;
  return c;
}
const op = (name, payload) => ({ opId: `ao-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId: ownerId, createdAt: AT });
const sync = async (...ops) => (await term.call('syncOps', { ops })).results;
const data = async (path) => (await adminDb.doc(path).get()).data();
const latteL = (qty = 1) => ({ productId: latte, qty, options: [{ groupId: size, optionId: 'l' }] });
// Diğer test dosyalarının terminalleri de çevrimiçi sayılır; çevrimdışı denemesinde hepsi eskitilir
async function allTerminalsSeen(ms) {
  const snap = await adminDb.collection('terminals').get();
  await Promise.all(snap.docs.map((d) => d.ref.update({ lastSeenAt: Timestamp.fromMillis(ms) })));
}

test('masadan sipariş: QR doğrulanır, fiyat menüden; kasa onaylar → adisyon ve fişler → hazırlanıyor → hazır → tamamlandı', async () => {
  const ayse = await customer('+905321240001', 'Ayşe K.');
  await expectCallError(client().call('appOrderingInfo', { tableId: table.id, t: 'yanlis' }), 'not-found');
  const info = await client().call('appOrderingInfo', { tableId: table.id, t: table.t });
  assert.deepEqual([info.online, info.tableOrders, info.pickup, info.table.label, info.cafeName], [true, true, true, 'Masa 4', 'Velvet Kafe']);

  // Giriş gerekir; başka masanın anahtarı ve fiyat oyunu geçmez
  await expectCallError(client().call('createAppOrder', { kind: 'table', tableId: table.id, t: table.t, items: [latteL()] }), 'unauthenticated');
  await expectCallError(ayse.call('createAppOrder', { kind: 'table', tableId: table.id, t: 'x', items: [latteL()] }), 'not-found');
  await expectCallError(ayse.call('createAppOrder', { kind: 'table', tableId: table.id, t: table.t,
    items: [{ productId: latte, qty: 1 }] }), 'invalid-argument'); // boy seçilmemiş
  await expectCallError(ayse.call('createAppOrder', { kind: 'table', tableId: table.id, t: table.t,
    items: [latteL(2)], expectedTotal: 100 }), 'aborted');
  const r = await ayse.call('createAppOrder', { kind: 'table', tableId: table.id, t: table.t, note: 'pencere kenarı',
    items: [latteL(2), { productId: cookie, qty: 1, unitPrice: 1 }], expectedTotal: 2 * 11000 + 4000 });
  assert.equal(r.total, 26000);
  const a = await data(`appOrders/${r.id}`);
  assert.deepEqual([a.status, a.kind, a.tableName, a.customerName, a.items[0].options[0].name, a.items[1].unitPrice],
    ['pending', 'table', '4', 'Ayşe K.', 'Büyük', 4000]);

  // Müşteri yalnızca kendi isteklerini okur; kasa hepsini
  assert.equal((await getDocs(query(collection(ayse.db, 'appOrders'), where('customerId', '==', ayse.customerId)))).size, 1);
  const can = await customer('+905321240002', 'Can');
  await expectDenied(getDoc(doc(can.db, `appOrders/${r.id}`)));
  assert.ok((await getDoc(doc(term.db, `appOrders/${r.id}`))).exists());
  await expectCallError(ayse.call('acceptAppOrder', { id: r.id, orderId: 'X', orderNo: 'A1' }), 'permission-denied');

  // Kasa: adisyonu kendisi açar (kuyruk), onayı bildirir
  const res = await sync(
    op('openOrder', { orderId: 'AO1', no: 'A71', businessDay: '2026-11-03', type: 'dine_in', tableId: table.id, tableName: '4' }),
    op('addItems', { orderId: 'AO1', items: a.items.map((x, i) => ({ lineId: `aol${i}`, productId: x.productId, name: x.name,
      unitPrice: x.unitPrice, qty: x.qty, options: x.options, station: 'bar', stampEligible: true })) }),
    op('sendItems', { orderId: 'AO1', lineIds: ['aol0', 'aol1'], ticketIds: { bar: 'TK-AO1-bar' } }),
  );
  assert.deepEqual(res.map((x) => x.status), ['ok', 'ok', 'ok']);
  assert.deepEqual(await term.call('acceptAppOrder', { id: r.id, orderId: 'AO1', orderNo: 'A71', ticketIds: ['TK-AO1-bar'], staffId: ownerId }),
    { status: 'accepted' });
  assert.deepEqual(await term.call('acceptAppOrder', { id: r.id, orderId: 'AO1', orderNo: 'A71', ticketIds: ['TK-AO1-bar'] }),
    { status: 'accepted' }); // tekrar deneme zarar vermez
  await expectCallError(ayse.call('cancelMyAppOrder', { id: r.id }), 'failed-precondition');

  // Mutfak ekranı: Başla → hazırlanıyor, Hazır → hazır
  await tablet.call('updateKitchenTicket', { ticketId: 'TK-AO1-bar', status: 'preparing' });
  assert.equal((await data(`appOrders/${r.id}`)).status, 'preparing');
  await sync(op('updateTicket', { ticketId: 'TK-AO1-bar', status: 'ready' })); // kasadan da işaretlenebilir
  const ready = await data(`appOrders/${r.id}`);
  assert.deepEqual([ready.status, typeof ready.readyAt, ready.orderNo], ['ready', 'string', 'A71']);
  await sync(op('takePayment', { orderId: 'AO1', paymentId: 'PAY-AO1', method: 'card', amount: 26000 }));
  assert.equal((await data(`appOrders/${r.id}`)).status, 'completed');
});

test('red, müşteri iptali, süre dolması ve masa/müşteri sınırları', async () => {
  const ece = await customer('+905321240003', 'Ece');
  const send = (c) => c.call('createAppOrder', { kind: 'table', tableId: table.id, t: table.t, items: [{ productId: cookie, qty: 1 }] });
  const r1 = await send(ece);
  const r2 = await send(ece);
  await expectCallError(send(ece), 'resource-exhausted'); // masadan bekleyen en fazla 2
  await expectCallError(term.call('rejectAppOrder', { id: r1.id }), 'invalid-argument'); // gerekçe zorunlu
  await term.call('rejectAppOrder', { id: r1.id, reason: 'Kurabiye bitti' });
  assert.deepEqual([(await data(`appOrders/${r1.id}`)).status, (await data(`appOrders/${r1.id}`)).reason], ['rejected', 'Kurabiye bitti']);
  await expectCallError(term.call('acceptAppOrder', { id: r1.id, orderId: 'X', orderNo: 'A1' }), 'failed-precondition');
  await ece.call('cancelMyAppOrder', { id: r2.id });
  await expectCallError(term.call('acceptAppOrder', { id: r2.id, orderId: 'X', orderNo: 'A1' }), 'failed-precondition');

  // Onay süresi dolan istek: kasa onaylayamaz, müşteriye "kafe şu an yoğun"
  const r3 = await send(ece);
  await adminDb.doc(`appOrders/${r3.id}`).update({ expiresAt: Timestamp.fromMillis(Date.now() - 1000) });
  await expectCallError(term.call('acceptAppOrder', { id: r3.id, orderId: 'X', orderNo: 'A1' }), 'failed-precondition');
  assert.deepEqual([(await data(`appOrders/${r3.id}`)).status, (await data(`appOrders/${r3.id}`)).reason], ['expired', 'Kafe şu an yoğun.']);
  // Süresi dolan istek masa sınırına sayılmaz
  const r4 = await send(ece);
  const r5 = await send(ece);
  const pickup = () => ece.call('createAppOrder', { kind: 'pickup', pickup: { asap: true }, items: [{ productId: cookie, qty: 1 }] });
  const r6 = await pickup();
  await expectCallError(pickup(), 'resource-exhausted'); // müşteri başına en fazla 3 açık istek
  for (const r of [r4, r5, r6]) await term.call('rejectAppOrder', { id: r.id, reason: 'Deneme' });
});

test('gel-al: saat, kasa çevrimdışıyken kapalı, gelmedi iki kez → gel-al kapanır; modül kapalıysa alınmaz', async () => {
  const mert = await customer('+905321240004', 'Mert T.');
  const pick = (extra = {}) => mert.call('createAppOrder', { kind: 'pickup', items: [{ productId: cookie, qty: 2 }],
    pickup: { inMinutes: 15 }, ...extra });
  await expectCallError(pick({ pickup: { at: new Date(Date.now() + 4 * 3600_000).toISOString() } }), 'invalid-argument');
  await expectCallError(pick({ pickup: undefined }), 'invalid-argument');

  await allTerminalsSeen(Date.now() - 10 * 60_000);
  assert.equal((await client().call('appOrderingInfo', {})).online, false);
  await expectCallError(pick(), 'failed-precondition');
  await term.call('terminalHeartbeat', { pending: 0 }); // kasa geri geldi

  for (let i = 1; i <= 2; i += 1) {
    const r = await pick();
    const a = await data(`appOrders/${r.id}`);
    const minutes = Math.round((Date.parse(a.pickupAt) - Date.parse(a.createdAt)) / 60_000);
    assert.equal(minutes, 15);
    await term.call('acceptAppOrder', { id: r.id, orderId: `AOP${i}`, orderNo: `A8${i}`, ticketIds: [] });
    const ns = await term.call('appOrderNoShow', { id: r.id, staffId: ownerId });
    assert.equal(ns.pickupBlocked, i === 2);
  }
  const c = await data(`customers/${mert.customerId}`);
  assert.deepEqual([c.noShows, c.pickupBlocked], [2, true]);
  const info = await mert.call('appOrderingInfo', {});
  assert.deepEqual([info.pickup, info.pickupBlocked], [false, true]);
  await expectCallError(pick(), 'failed-precondition');
  // Masadan sipariş etkilenmez; modül kapanınca o da kapanır
  await mert.call('createAppOrder', { kind: 'table', tableId: table.id, t: table.t, items: [{ productId: cookie, qty: 1 }] })
    .then((r) => term.call('rejectAppOrder', { id: r.id, reason: 'Deneme' }));
  await adminDb.doc('settings/modules').set({ app: { enabled: true, tableOrders: false, pickup: true } }, { merge: true });
  await expectCallError(mert.call('createAppOrder', { kind: 'table', tableId: table.id, t: table.t,
    items: [{ productId: cookie, qty: 1 }] }), 'failed-precondition');
  await adminDb.doc('settings/modules').set({ app: { enabled: true, tableOrders: true, pickup: true } }, { merge: true });
});

test('kasada iptal edilen adisyonun isteği iptal olur', async () => {
  const deniz = await customer('+905321240005', 'Deniz');
  const r = await deniz.call('createAppOrder', { kind: 'pickup', pickup: { asap: true }, items: [{ productId: cookie, qty: 1 }] });
  await sync(op('openOrder', { orderId: 'AOC1', no: 'A90', businessDay: '2026-11-03', type: 'takeaway' }));
  await term.call('acceptAppOrder', { id: r.id, orderId: 'AOC1', orderNo: 'A90', ticketIds: [] });
  await sync(op('cancelOrder', { orderId: 'AOC1', reason: 'Müşteri vazgeçti' }));
  assert.deepEqual([(await data(`appOrders/${r.id}`)).status, (await data(`appOrders/${r.id}`)).reason], ['cancelled', 'Kasada iptal edildi.']);
});

test('garson çağır / hesap iste: masa QR\'ı ile, tekrar basınca çoğalmaz; garson görür ve kapatır', async () => {
  await expectCallError(client().call('callTable', { tableId: table.id, t: 'x', kind: 'waiter' }), 'not-found');
  await expectCallError(client().call('callTable', { tableId: table.id, t: table.t, kind: 'dans' }), 'invalid-argument');
  assert.deepEqual(await client().call('callTable', { tableId: table.id, t: table.t, kind: 'waiter' }), { status: 'open', already: false });
  assert.deepEqual(await client().call('callTable', { tableId: table.id, t: table.t, kind: 'waiter' }), { status: 'open', already: true });
  await client().call('callTable', { tableId: table.id, t: table.t, kind: 'bill' });
  const call = (await getDoc(doc(term.db, `tableCalls/${table.id}_waiter`))).data();
  assert.deepEqual([call.kind, call.tableName, call.status], ['waiter', '4', 'open']);
  await expectDenied(getDoc(doc(client().db, `tableCalls/${table.id}_waiter`)));
  const res = await sync(op('ackTableCall', { callId: `${table.id}_waiter`, at: call.at }));
  assert.equal(res[0].status, 'ok');
  assert.equal((await data(`tableCalls/${table.id}_waiter`)).status, 'done');
  assert.equal((await data(`tableCalls/${table.id}_bill`)).status, 'open');
  // Kapatıldıktan sonra tekrar çağrılabilir
  assert.equal((await client().call('callTable', { tableId: table.id, t: table.t, kind: 'waiter' })).already, false);
  await sync(op('ackTableCall', { callId: `${table.id}_waiter`, at: '2000-01-01T00:00:00Z' })); // eski onay yenisini kapatmaz
  assert.equal((await data(`tableCalls/${table.id}_waiter`)).status, 'open');
});
