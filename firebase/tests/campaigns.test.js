// Kampanya ve bildirim (10b): panelden kampanya, kasadan uygulama/kaldırma, günlük özet, bildirim kitlesi.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc } = require('firebase/firestore');

const OWNER = { email: 'kampanya-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Kampanya Sahibi', pin: '482917' };
const MANAGER = { email: 'kampanya-mudur@kafe.test', password: 'mudur-sifre-1' };
let owner;
let manager;
let managerId;
let waiter;
let term;
let hh;
let seq = 0;
const AT = '2026-10-16T15:00:00+03:00';
const DAY = '2026-10-17';   // başka testlerin günlük özetinden ayrı

before(async () => {
  createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  ({ staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson K', role: 'waiter', pin: '730594' }));
  ({ staffId: managerId } = await owner.call('manageStaff', { action: 'create', name: 'Müdür K', role: 'manager', pin: '583922',
    email: MANAGER.email, password: MANAGER.password }));
  manager = await signedInAs(MANAGER.email, MANAGER.password);
  const reg = await owner.call('registerTerminal', { name: 'Kampanya Kasa' });
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(closeAll);

const op = (name, payload, staffId = waiter) => ({ opId: `kmp-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId, createdAt: AT });
const sync = async (...ops) => (await term.call('syncOps', { ops })).results;
const data = async (path) => (await adminDb.doc(path).get()).data();

test('kampanya: kaydet, doğrulama, yetki, herkese açık okuma, silme', async () => {
  ({ id: hh } = await manager.call('saveCampaign', { name: 'Happy Hour', type: 'percent', value: 20,
    appliesTo: { categoryIds: ['kahve'] }, schedule: { days: [1, 2, 3, 4, 5], from: '14:00', to: '17:00' } }));
  const c = await data(`campaigns/${hh}`);
  assert.deepEqual([c.type, c.value, c.active, c.deleted, c.schedule.from, c.audience], ['percent', 20, true, false, '14:00', 'all']);
  await expectCallError(manager.call('saveCampaign', { name: 'X', type: 'nth', value: 50, nthQty: 1 }), 'invalid-argument');
  await manager.call('saveCampaign', { id: hh, name: 'Happy Hour', type: 'percent', value: 25, appliesTo: { categoryIds: ['kahve'] },
    schedule: { days: [1, 2, 3, 4, 5], from: '14:00', to: '17:00' } });
  assert.equal((await data(`campaigns/${hh}`)).value, 25);
  // Müşteri uygulaması giriş yapmadan kampanyaları görür
  assert.ok((await getDoc(doc(client().db, `campaigns/${hh}`))).exists());
  const { id: tmp } = await owner.call('saveCampaign', { name: 'Geçici', type: 'double_stamps' });
  await owner.call('deleteCampaign', { id: tmp });
  assert.deepEqual([(await data(`campaigns/${tmp}`)).deleted, (await data(`campaigns/${tmp}`)).active], [true, false]);
  await expectCallError(owner.call('saveCampaign', { id: tmp, name: 'Geçici', type: 'double_stamps' }), 'not-found');
});

test('kasada kampanya: uygulanır, ürün değişince silinir, kaldırma iskonto yetkisi ister; günlük özette ayrı', async () => {
  const line = { lineId: 'l1', productId: null, name: 'Latte', unitPrice: 9500, qty: 2, station: 'bar', stampEligible: true };
  const camp = { campaignId: hh, name: 'Happy Hour', type: 'percent', lines: { l1: 4750 } };
  let r = await sync(
    op('openOrder', { orderId: 'K1', no: 'K1', businessDay: DAY, type: 'takeaway' }),
    op('addItems', { orderId: 'K1', items: [line] }),
    op('sendItems', { orderId: 'K1', lineIds: ['l1'], ticketIds: { bar: 'K1-b' } }),
    op('applyCampaigns', { orderId: 'K1', campaigns: [camp], excluded: [] }),
  );
  assert.ok(r.every((x) => x.status === 'ok'), JSON.stringify(r));
  let o = await data('orders/K1');
  assert.deepEqual([o.campaignAmount, o.total], [4750, 14250]);
  // Garson kampanyayı kaldıramaz; müdür onayıyla kaldırılır
  [r] = await sync(op('applyCampaigns', { orderId: 'K1', campaigns: [], excluded: [hh] }));
  assert.match(r.error, /discount/);
  [r] = await sync(op('applyCampaigns', { orderId: 'K1', campaigns: [], excluded: [hh], approvedBy: managerId }));
  assert.equal(r.status, 'ok');
  o = await data('orders/K1');
  assert.deepEqual([o.campaignAmount, o.campaignsExcluded], [0, [hh]]);
  // Kaldırılan listesi değişmeden yeniden uygulama yetki istemez
  [r] = await sync(op('applyCampaigns', { orderId: 'K1', campaigns: [{ ...camp, campaignId: 'k2', name: 'Diğer' }], excluded: [hh] }));
  assert.equal(r.status, 'ok');
  [r] = await sync(op('addItems', { orderId: 'K1', items: [{ ...line, lineId: 'l2', qty: 1 }] }));
  assert.equal((await data('orders/K1')).campaigns.length, 0);
  // Fiyatı aşan kampanya reddedilir
  [r] = await sync(op('applyCampaigns', { orderId: 'K1', campaigns: [{ ...camp, campaignId: 'k2', lines: { l2: 9600 } }], excluded: [hh] }));
  assert.equal(r.status, 'rejected');
  await sync(op('sendItems', { orderId: 'K1', lineIds: ['l2'], ticketIds: { bar: 'K1-b2' } }),
    op('applyCampaigns', { orderId: 'K1', campaigns: [{ ...camp, campaignId: 'k2', name: 'Diğer', lines: { l2: 1000 } }], excluded: [hh] }));
  [r] = await sync(op('takePayment', { orderId: 'K1', paymentId: 'P-K1', method: 'card', amount: 27500 }));
  assert.equal(r.status, 'ok');
  const stats = await data(`dailyStats/${DAY}`);
  assert.deepEqual([stats.campaign, stats.byCampaign.k2.amount, stats.byCampaign.k2.count, stats.revenue], [1000, 1000, 1, 27500]);
  assert.equal(stats.gross - stats.campaign - stats.discount, stats.revenue);
});

test('bildirim: kitle ve erişim izinli üyelerden, yetki, okuma kuralı', async () => {
  const now = '2026-10-16';
  await adminDb.doc('customers/KN1').set({ name: 'A', phone: '5300000001', marketingConsent: true, tier: 'gold',
    lastVisitAt: '2026-10-15T10:00:00+03:00', birthDate: '10-17', deleted: false });
  await adminDb.doc('customers/KN2').set({ name: 'B', phone: '5300000002', marketingConsent: true, tier: 'bronze',
    lastVisitAt: '2026-08-01T10:00:00+03:00', deleted: false });
  await adminDb.doc('customers/KN3').set({ name: 'C', phone: '5300000003', marketingConsent: false, tier: 'gold', deleted: false });
  const all = await manager.call('saveNotification', { title: 'Sıcak çikolata', body: 'Bugün %20', segment: 'all', day: now });
  const gold = await manager.call('saveNotification', { title: 'Altın', body: 'Size özel', segment: 'gold', day: now });
  const away = await manager.call('saveNotification', { title: 'Özledik', body: 'Kahve bizden', segment: 'inactive30', day: now });
  const bday = await manager.call('saveNotification', { title: 'İyi ki doğdun', body: 'Hediye', segment: 'birthday', day: now });
  assert.ok(all.reach >= 2);
  assert.deepEqual([gold.reach >= 1, away.reach >= 1, bday.reach >= 1], [true, true, true]);
  const n = await data(`notifications/${all.id}`);
  assert.deepEqual([n.status, n.segment, n.title], ['waiting_app', 'all', 'Sıcak çikolata']);
  await expectCallError(manager.call('saveNotification', { title: 'X', body: 'Y', segment: 'herkes' }), 'invalid-argument');
  await expectCallError(manager.call('saveNotification', { title: '', body: 'Y', segment: 'all' }), 'invalid-argument');
  assert.ok((await getDoc(doc(term.db, `notifications/${all.id}`))).exists());
  await expectDenied(getDoc(doc(client().db, `notifications/${all.id}`)));
});
