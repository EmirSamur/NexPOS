// Müşteri ve sadakat (10. ekran): kasada üyelik, damga, ödül, iade, doğum günü, düzeltme, QR, KVKK.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Timestamp } = require('firebase-admin/firestore');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc } = require('firebase/firestore');

const OWNER = { email: 'sadakat-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Sadakat Sahibi', pin: '482916' };
const MANAGER = { email: 'sadakat-mudur@kafe.test', password: 'mudur-sifre-1' };
let owner;
let manager;
let managerId;
let waiter;
let term;
let seq = 0;
const AT = '2026-10-16T12:00:00+03:00';
const DAY = '2026-10-16';

before(async () => {
  createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  ({ staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson S', role: 'waiter', pin: '730593' }));
  ({ staffId: managerId } = await owner.call('manageStaff', { action: 'create', name: 'Müdür S', role: 'manager', pin: '583921',
    email: MANAGER.email, password: MANAGER.password }));
  manager = await signedInAs(MANAGER.email, MANAGER.password);
  const reg = await owner.call('registerTerminal', { name: 'Sadakat Kasa' });
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(closeAll);

const op = (name, payload, staffId = waiter) => ({ opId: `loy-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId, createdAt: AT });
const sync = async (...ops) => (await term.call('syncOps', { ops })).results;
const data = async (path) => (await adminDb.doc(path).get()).data();
const latte = (lineId, qty = 1) => ({ lineId, productId: null, name: 'Latte', unitPrice: 9500, qty, station: 'bar', stampEligible: true });
const cake = (lineId) => ({ lineId, productId: null, name: 'Kek', unitPrice: 6000, qty: 1, station: 'kitchen', stampEligible: false });

// Masasız adisyon: ürünler gönderilir, müşteri eklenir; ödeme ayrıca alınır
async function openWith(orderId, customerId, items, extra = []) {
  const r = await sync(
    op('openOrder', { orderId, no: orderId, businessDay: DAY, type: 'takeaway' }),
    op('addItems', { orderId, items }),
    op('sendItems', { orderId, lineIds: items.map((i) => i.lineId), ticketIds: { bar: `${orderId}-b`, kitchen: `${orderId}-k` } }),
    op('setCustomer', { orderId, customer: { id: customerId, name: 'Ayşe K.', tier: null } }),
    ...extra,
  );
  assert.ok(r.every((x) => x.status === 'ok'), JSON.stringify(r));
}
const pay = async (orderId, amount) => (await sync(op('takePayment', { orderId, paymentId: `P-${orderId}-${amount}`, method: 'card', amount })))[0];

test('kasada üyelik: internetsiz kayıt, telefon tekil (aynı numara asıl kayda yönlenir), panelden düzenleme', async () => {
  let r = await sync(op('customerCreate', { customerId: 'C1', name: 'Ayşe K.', phone: '0532 111 22 33', marketingConsent: true, birthDate: '10-18' }));
  assert.equal(r[0].status, 'ok');
  const c = await data('customers/C1');
  assert.deepEqual([c.phone, c.stamps, c.tier, c.source, c.marketingConsent, c.consentAt], ['5321112233', 0, 'bronze', 'pos', true, AT]);
  assert.equal((await data('customerPhones/5321112233')).customerId, 'C1');
  r = await sync(op('customerCreate', { customerId: 'C1dup', name: 'Ayşe', phone: '+90 532 111 2233', marketingConsent: false }));
  assert.equal(r[0].status, 'ok');
  assert.equal((await data('customers/C1dup')).aliasOf, 'C1');
  r = await sync(op('customerCreate', { customerId: 'C2', name: 'X', phone: '123', marketingConsent: false }));
  assert.match(r[0].error, /Telefon/);
  r = await sync(op('customerCreate', { customerId: 'C3', name: 'Mehmet T.', phone: '05051234512', marketingConsent: false }));
  assert.equal(r[0].status, 'ok');
  // Panel: düzenleme, başkasının numarası verilemez; garson oturumu müşterileri okuyamaz
  await manager.call('saveCustomer', { id: 'C3', name: 'Mehmet Tan', phone: '0505 123 45 99', marketingConsent: true });
  assert.equal((await data('customers/C3')).phone, '5051234599');
  assert.equal(await data('customerPhones/5051234512'), undefined);
  await expectCallError(manager.call('saveCustomer', { id: 'C3', name: 'M', phone: '05321112233', marketingConsent: false }), 'already-exists');
  const { id } = await manager.call('saveCustomer', { name: 'Zeynep', phone: '0544 000 00 01', marketingConsent: false });
  assert.equal((await data(`customers/${id}`)).source, 'panel');
  assert.ok((await getDoc(doc(term.db, 'customers/C1'))).exists());
  assert.ok((await getDoc(doc(manager.db, 'customers/C1'))).exists());
  await expectDenied(getDoc(doc(client().db, 'customers/C1')));
});

test('ödemede damga, kart dolunca ödül; ödül sonraki adisyonda kullanılır ve damga vermez', async () => {
  await adminDb.doc('customers/C1').update({ stamps: 8, lifetimeStamps: 48 });
  await openWith('LO1', 'C1', [latte('l1', 2), cake('l2')]);
  assert.equal((await pay('LO1', 25000)).status, 'ok');
  let c = await data('customers/C1');
  assert.deepEqual([c.stamps, c.lifetimeStamps, c.tier, c.visitCount, c.totalSpent, c.lastVisitAt], [0, 50, 'silver', 1, 25000, AT]);
  const reward = await data('rewards/LO1-r1');
  assert.deepEqual([reward.customerId, reward.status, reward.type, reward.expiresAt], ['C1', 'active', 'free_drink', '2026-12-15']);
  const ev = await data('loyaltyEvents/LO1-stamp');
  assert.deepEqual([ev.amount, ev.rewards, ev.customerId], [2, 2, 'C1']);   // + doğum günü haftası ödülü (10-18)
  assert.equal((await data('rewards/LO1-bday')).type, 'birthday');
  assert.equal(c.lastBirthdayYear, '2026');
  // Ödülü kullan: 2 latteden biri bedava (en fazla 90 ₺), yalnızca 1 damga
  await openWith('LO2', 'C1', [latte('l1', 2)], [op('useReward', { orderId: 'LO2', rewardId: 'LO1-r1', lineId: 'l1', amount: 9000 })]);
  assert.equal((await data('orders/LO2')).total, 10000);
  await pay('LO2', 10000);
  assert.equal((await data('rewards/LO1-r1')).status, 'used');
  assert.equal((await data('rewards/LO1-r1')).usedOrderId, 'LO2');
  c = await data('customers/C1');
  assert.deepEqual([c.stamps, c.visitCount], [1, 2]);
  assert.equal((await data('orders/LO2')).stamps, 1);
  // Doğum günü ödülü aynı yıl ikinci kez verilmez
  assert.equal(await data('rewards/LO2-bday'), undefined);
  // Kullanılmış ödül yeniden: para alınır, kayda düşer
  await openWith('LO3', 'C1', [latte('l1')], [op('useReward', { orderId: 'LO3', rewardId: 'LO1-r1', lineId: 'l1', amount: 9000 })]);
  assert.equal((await pay('LO3', 500)).status, 'ok');
  const logs = await adminDb.collection('auditLogs').where('action', '==', 'reward_conflict').get();
  assert.ok(logs.docs.some((d) => d.data().target === 'rewards/LO1-r1'));
});

test('iade damgayı oranında geri alır; çift kayıt (aynı telefon) asıl kayda işlenir; günlük özet', async () => {
  await adminDb.doc('customers/C1').update({ stamps: 0 });
  await openWith('LO4', 'C1dup', [latte('l1', 4)]);
  await pay('LO4', 38000);
  let c = await data('customers/C1');
  assert.equal(c.stamps, 4);
  const [r] = await sync(op('refundPayment', { orderId: 'LO4', refundId: 'RF-LO4', method: 'card', amount: 19000, reason: 'Soğuktu',
    approvedBy: managerId }));
  assert.equal(r.status, 'ok');
  c = await data('customers/C1');
  assert.equal(c.stamps, 2);
  assert.equal((await data('orders/LO4')).stampsRevoked, 2);
  assert.equal((await data('loyaltyEvents/RF-LO4-revoke')).amount, -2);
  const stats = await data(`dailyStats/${DAY}`);
  assert.ok(stats.members.orders >= 4);
  assert.ok(stats.rewards.count >= 2 && stats.rewards.amount >= 18000);
});

test('elle düzeltme: loyalty yetkisi ve gerekçe; ödül verilebilir', async () => {
  let [r] = await sync(op('loyaltyAdjust', { adjustId: 'ADJ1', customerId: 'C1', stamps: 3, reason: 'Kart kayboldu' }));
  assert.match(r.error, /loyalty/);
  [r] = await sync(op('loyaltyAdjust', { adjustId: 'ADJ1', customerId: 'C1', stamps: 3, reason: ' ', approvedBy: managerId }));
  assert.equal(r.status, 'rejected');
  const before = (await data('customers/C1')).stamps;
  [r] = await sync(op('loyaltyAdjust', { adjustId: 'ADJ2', customerId: 'C1', stamps: 3, grantReward: true, reason: 'Kart kayboldu',
    approvedBy: managerId }));
  assert.equal(r.status, 'ok');
  assert.equal((await data('customers/C1')).stamps, before + 3);
  assert.equal((await data('rewards/ADJ2-r1')).type, 'manual');
  assert.equal((await data('loyaltyEvents/ADJ2')).approvedBy, managerId);
});

test('uygulama QR: tek kullanım, süreli; ayarlar yalnızca yönetici; dışa aktarma; KVKK silme', async () => {
  const future = Timestamp.fromMillis(Date.now() + 60_000);
  await adminDb.doc('loyaltyTokens/tok1').set({ uid: 'C1', expiresAt: future });
  await adminDb.doc('loyaltyTokens/tok2').set({ uid: 'C1', expiresAt: Timestamp.fromMillis(Date.now() - 1000) });
  const res = await term.call('resolveLoyaltyToken', { token: 'tok1' });
  assert.deepEqual([res.customerId, res.phone], ['C1', '0532 *** ** 33']);
  await expectCallError(term.call('resolveLoyaltyToken', { token: 'tok1' }), 'not-found');
  await expectCallError(term.call('resolveLoyaltyToken', { token: 'tok2' }), 'not-found');
  await expectCallError(manager.call('resolveLoyaltyToken', { token: 'tok1' }), 'permission-denied');

  await expectCallError(manager.call('saveLoyaltySettings', { stampsForReward: 8 }), 'permission-denied');
  await expectCallError(owner.call('saveLoyaltySettings', { stampsForReward: 1 }), 'invalid-argument');
  const s = await owner.call('saveLoyaltySettings', { stampsForReward: 8, rewardMaxValue: 10000 });
  assert.deepEqual([s.stampsForReward, s.rewardValidDays, s.tiers[2].minStamps], [8, 60, 150]);
  assert.equal((await data('settings/loyalty')).stampsForReward, 8);

  const ex = await manager.call('exportCustomer', { id: 'C1' });
  assert.equal(ex.customer.phone, '5321112233');
  assert.ok(ex.orders.length >= 3 && ex.orders.every((o) => o.total >= 0));
  assert.ok(ex.events.some((e) => e.type === 'adjust') && ex.rewards.length >= 3);

  await expectCallError(manager.call('deleteCustomer', { id: 'C1' }), 'permission-denied');
  await owner.call('deleteCustomer', { id: 'C1' });
  const c = await data('customers/C1');
  assert.deepEqual([c.name, c.phone, c.birthDate, c.deleted], ['Silinmiş müşteri', null, null, true]);
  assert.equal(await data('customerPhones/5321112233'), undefined);
  assert.equal((await data('rewards/ADJ2-r1')).status, 'cancelled');
  // Silinmiş müşteriye damga işlenmez; numara yeniden kullanılabilir
  await openWith('LO5', 'C1', [latte('l1')]);
  assert.equal((await pay('LO5', 9500)).status, 'ok');
  assert.equal((await data('customers/C1')).stamps, 0);
  const [r] = await sync(op('customerCreate', { customerId: 'C9', name: 'Yeni', phone: '05321112233', marketingConsent: false }));
  assert.equal(r.status, 'ok');
  assert.equal((await data('customers/C9')).aliasOf, undefined);
});
