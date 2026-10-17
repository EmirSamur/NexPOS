// 11c: kahve önerisi soruları ve kaydı, telefon bildirimleri (emülatörde pushLog), uygulama raporu.
// (menü testlerinden sonra çalışsın diye adı p ile başlar: onlar boş menü bekler)
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { getAuth } = require('firebase-admin/auth');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc } = require('firebase/firestore');

const OWNER = { email: 'oneri-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Öneri Sahibi', pin: '482916' };
let owner;
let term;
let latte;
let mocha;
let seq = 0;

before(async () => {
  createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  const { id: cat } = await owner.call('saveCategory', { name: 'Öneri Kahve', station: 'bar', stampEligible: true });
  const flavor = (strength, sweetness, notes) => ({ strength, sweetness, acidity: 2, body: 3, milk: true, temperature: 'hot', notes });
  ({ id: latte } = await owner.call('saveProduct', { categoryId: cat, name: 'Öneri Latte', price: 9500, flavor: flavor(2, 2, []) }));
  ({ id: mocha } = await owner.call('saveProduct', { categoryId: cat, name: 'Öneri Mocha', price: 11000, flavor: flavor(2, 4, ['çikolata']) }));
  await adminDb.doc('settings/modules').set({ app: { enabled: true, tableOrders: true, pickup: true } }, { merge: true });
  const reg = await owner.call('registerTerminal', { name: 'Öneri Kasası' });
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(closeAll);

async function customer(phone, name, consent = true) {
  const uid = `pq-${++seq}-${Date.now()}`;
  await getAuth().createUser({ uid, phoneNumber: phone });
  const c = client();
  await signInWithCustomToken(c.auth, await getAuth().createCustomToken(uid));
  const r = await c.call('linkCustomer', { name, marketingConsent: consent, kvkkAccepted: true });
  await c.auth.currentUser.getIdToken(true);
  c.customerId = r.customer.id;
  return c;
}
const data = async (path) => (await adminDb.doc(path).get()).data();
// Tetikleyiciler (Firestore → fonksiyon) birkaç saniye içinde çalışır
async function pushes(customerId, n, timeout = 15000) {
  const end = Date.now() + timeout;
  for (;;) {
    const q = await adminDb.collection('pushLog').where('customerId', '==', customerId).get();
    const list = q.docs.map((d) => d.data()).sort((a, b) => a.at.toMillis() - b.at.toMillis());
    if (list.length >= n || Date.now() > end) return list;
    await new Promise((r) => setTimeout(r, 300));
  }
}
const today = () => new Date(Date.now() + 3 * 3600_000).toISOString().slice(0, 10);

test('öneri soruları: panelden düzenlenir, herkes okur; geçersiz reddedilir; hazıra dönülür', async () => {
  const quiz = { questions: [{ id: 'mood', text: 'Nasılsın?', answers: [
    { id: 'tired', text: 'Yorgun', weights: { strength: 2 } }, { id: 'fine', text: 'İyi' }] }] };
  const saved = await owner.call('saveQuiz', quiz);
  assert.equal(saved.questions[0].answers[0].weights.strength, 2);
  assert.equal((await getDoc(doc(client().db, 'settings/quiz'))).data().questions[0].text, 'Nasılsın?');
  await expectCallError(owner.call('saveQuiz', { questions: [{ id: 'x', text: 'Tek?', answers: [{ id: 'a', text: 'A' }] }] }),
    'invalid-argument');
  const ayse = await customer('+905321250001', 'Ayşe');
  await expectCallError(ayse.call('saveQuiz', quiz), 'permission-denied');
  const reset = await owner.call('saveQuiz', { reset: true });
  assert.equal(reset.questions.length, 4);
});

test('öneri kaydı: gösterilen sayılır, önerilen ürün sipariş edilince tuttu; müşteri kendi geçmişini okur', async () => {
  const can = await customer('+905321250002', 'Can');
  const { id } = await can.call('logRecommendation', { productIds: [mocha, latte], answers: { mood: 'happy', taste: 'choc' } });
  const rec = (await getDoc(doc(can.db, `customers/${can.customerId}/recommendations/${id}`))).data();
  assert.deepEqual([rec.productIds, rec.chosenProductId, rec.answers.taste], [[mocha, latte], null, 'choc']);
  const ece = await customer('+905321250003', 'Ece');
  await expectDenied(getDoc(doc(ece.db, `customers/${can.customerId}/recommendations/${id}`)));
  await expectCallError(can.call('logRecommendation', { productIds: [] }), 'invalid-argument');

  const r = await can.call('createAppOrder', { kind: 'pickup', pickup: { asap: true }, recommendationId: id,
    items: [{ productId: mocha, qty: 1 }] });
  const after1 = await data(`customers/${can.customerId}/recommendations/${id}`);
  assert.deepEqual([after1.chosenProductId, after1.appOrderId], [mocha, r.id]);
  const stats = await data(`dailyStats/${today()}`);
  assert.ok(stats.recs.shown >= 1 && stats.recs.ordered >= 1);
  assert.ok(stats.app.requests >= 1 && stats.app.pickup >= 1);
  await term.call('rejectAppOrder', { id: r.id, reason: 'Deneme' });
});

test('bildirim: cihaz kaydı; sipariş onay/hazır/red her zaman gider, cihazı olmayana gitmez', async () => {
  const mert = await customer('+905321250004', 'Mert', false);
  await mert.call('registerDevice', { token: 'tok-mert-1', platform: 'android' });
  await mert.call('registerDevice', { token: 'tok-mert-1', platform: 'android' }); // aynı cihaz tek kayıt
  assert.equal((await adminDb.collection(`customers/${mert.customerId}/devices`).get()).size, 1);
  await expectCallError(client().call('registerDevice', { token: 'x' }), 'unauthenticated');

  const r = await mert.call('createAppOrder', { kind: 'pickup', pickup: { asap: true }, items: [{ productId: latte, qty: 1 }] });
  await term.call('acceptAppOrder', { id: r.id, orderId: 'PQ1', orderNo: 'A55', ticketIds: [] });
  await adminDb.doc(`appOrders/${r.id}`).update({ status: 'ready' }); // fiş "Hazır" (bkz. orders_app testleri)
  const log = await pushes(mert.customerId, 2);
  assert.deepEqual(log.map((x) => [x.title, x.kind]), [['Siparişin onaylandı ☕', 'order'], ['Siparişin hazır 🔔', 'order']]);
  assert.equal(log[1].body, 'A55 · Gelip alabilirsin.');
  assert.equal(log[1].data.status, 'ready');

  const zey = await customer('+905321250005', 'Zeynep');
  const r2 = await zey.call('createAppOrder', { kind: 'pickup', pickup: { asap: true }, items: [{ productId: latte, qty: 1 }] });
  await term.call('rejectAppOrder', { id: r2.id, reason: 'Kapanıyoruz' });
  await new Promise((res) => setTimeout(res, 2000));
  assert.equal((await pushes(zey.customerId, 1, 1000)).length, 0); // cihazı yok
});

test('kampanya bildirimi: izinli ve cihazlı üyeye gider, günde en fazla 1; ödül bildirimi izinle', async () => {
  const deniz = await customer('+905321250006', 'Deniz', true);
  const bora = await customer('+905321250007', 'Bora', false);
  await deniz.call('registerDevice', { token: 'tok-deniz', platform: 'web' });
  await bora.call('registerDevice', { token: 'tok-bora', platform: 'web' });
  const n1 = await owner.call('saveNotification', { title: 'Yeni: Pumpkin Latte', body: 'Bu hafta %10 indirim', segment: 'all' });
  await owner.call('saveNotification', { title: 'İkinci', body: 'Aynı gün ikinci bildirim', segment: 'all' });
  const end = Date.now() + 15000;
  while ((await data(`notifications/${n1.id}`)).status !== 'sent' && Date.now() < end) await new Promise((r) => setTimeout(r, 300));
  const n = await data(`notifications/${n1.id}`);
  assert.equal(n.status, 'sent');
  assert.ok(n.sentCount >= 1);
  await new Promise((r) => setTimeout(r, 2000));
  const dl = await pushes(deniz.customerId, 1);
  assert.deepEqual(dl.map((x) => [x.title, x.kind]), [['Yeni: Pumpkin Latte', 'marketing']]); // ikincisi günlük sınıra takıldı
  assert.equal((await pushes(bora.customerId, 1, 500)).length, 0); // izin yok
  assert.equal((await data(`customers/${deniz.customerId}`)).lastMarketingPushDay, today());

  await adminDb.doc(`rewards/PQ-r1`).set({ customerId: deniz.customerId, type: 'free_drink', status: 'active', expiresAt: '2026-12-16' });
  await adminDb.doc(`rewards/PQ-r2`).set({ customerId: bora.customerId, type: 'free_drink', status: 'active', expiresAt: '2026-12-16' });
  const after2 = await pushes(deniz.customerId, 2);
  assert.equal(after2[1].title, 'Kartın doldu 🎁'); // ödül bildirimi günlük kampanya sınırına takılmaz
  await new Promise((r) => setTimeout(r, 1500));
  assert.equal((await pushes(bora.customerId, 1, 500)).length, 0);
});

test('uygulama raporu: sayaçlar, onay süresi, öneri tutma; yetki ister', async () => {
  const day = today();
  const rep = await owner.call('appReport', { from: day, to: day });
  const a = rep.totals.app;
  assert.ok(a.requests >= 3 && a.accepted >= 1 && a.rejected >= 2);
  assert.ok(a.acceptSeconds >= 0 && a.acceptedAmount >= 9500);
  assert.ok(rep.totals.recs.shown >= 1 && rep.totals.recs.ordered >= 1);
  assert.ok(rep.products[mocha].shown >= 1 && rep.products[mocha].ordered >= 1);
  await expectCallError(owner.call('appReport', { from: '2026-13-01', to: day }), 'invalid-argument');
  const kim = await customer('+905321250008', 'Kim');
  await expectCallError(kim.call('appReport', { from: day, to: day }), 'permission-denied');
});
