// Müşteri uygulaması (11a): telefonla giriş → üyelik bağlama/açma, profil, dinamik QR, geçmiş, hesabı silme, kurallar.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { getAuth } = require('firebase-admin/auth');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc, getDocs, collection, query, where } = require('firebase/firestore');

const OWNER = { email: 'uygulama-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Uygulama Sahibi', pin: '482918' };
let owner;
let term;
let seq = 0;

before(async () => {
  createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  const reg = await owner.call('registerTerminal', { name: 'Uygulama Kasa' });
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(closeAll);

// Telefonla doğrulanmış müşteri oturumu (SMS adımı emülatörde kullanıcı kaydıyla taklit edilir)
async function phoneUser(phone) {
  const uid = `app-${++seq}-${Date.now()}`;
  await getAuth().createUser({ uid, phoneNumber: phone });
  const c = client();
  await signInWithCustomToken(c.auth, await getAuth().createCustomToken(uid));
  return c;
}
const refresh = (c) => c.auth.currentUser.getIdToken(true);
const data = async (path) => (await adminDb.doc(path).get()).data();
const op = (name, payload) => ({ opId: `app-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId: 'x', createdAt: '2026-10-17T10:00:00+03:00' });

test('kasada açılmış üyelik aynı telefonla uygulamaya bağlanır; kart ve ödüller yalnızca sahibine görünür', async () => {
  await adminDb.doc('customers/APP1').set({ name: 'Ayşe K.', phone: '5321230001', stamps: 7, lifetimeStamps: 57, tier: 'silver',
    marketingConsent: false, deleted: false });
  await adminDb.doc('customerPhones/5321230001').set({ customerId: 'APP1' });
  await adminDb.doc('rewards/APP1-r1').set({ customerId: 'APP1', status: 'active', type: 'free_drink', expiresAt: '2099-01-01' });
  await adminDb.doc('rewards/OTHER-r1').set({ customerId: 'APP9', status: 'active', type: 'free_drink', expiresAt: '2099-01-01' });
  const ayse = await phoneUser('+905321230001');
  const r = await ayse.call('linkCustomer', { marketingConsent: true });
  assert.deepEqual([r.status, r.customer.id, r.customer.stamps, r.customer.tier, r.customer.phone], ['linked', 'APP1', 7, 'silver', '0532 *** ** 01']);
  await refresh(ayse);
  const c = await data('customers/APP1');
  assert.deepEqual([c.authUid, c.marketingConsent, typeof c.consentAt], [ayse.auth.currentUser.uid, true, 'string']);
  assert.ok((await getDoc(doc(ayse.db, 'customers/APP1'))).exists());
  await expectDenied(getDoc(doc(ayse.db, 'customers/APP9')));
  const mine = await getDocs(query(collection(ayse.db, 'rewards'), where('customerId', '==', 'APP1')));
  assert.equal(mine.size, 1);
  await expectDenied(getDocs(query(collection(ayse.db, 'rewards'), where('customerId', '==', 'APP9'))));
  // Kafe bilgisi ve kart kuralları herkese açık; personel ayarları değil
  await owner.call('saveAppSettings', { cafeName: 'Velvet Kafe', hours: 'Her gün 08–24', kvkkText: 'Aydınlatma metni…' });
  assert.equal((await getDoc(doc(client().db, 'settings/app'))).data().cafeName, 'Velvet Kafe');
  await expectDenied(getDoc(doc(client().db, 'settings/permissions')));
  await expectCallError(ayse.call('saveAppSettings', { cafeName: 'X' }), 'permission-denied');
});

test('yeni müşteri: önce profil ister, KVKK onayıyla üyelik açar; profil güncelleme', async () => {
  const can = await phoneUser('+905441230002');
  assert.deepEqual(await can.call('linkCustomer', {}), { status: 'needsProfile' });
  await expectCallError(can.call('linkCustomer', { name: 'Can', marketingConsent: false }), 'invalid-argument');
  const r = await can.call('linkCustomer', { name: 'Can B.', birthDate: '03-08', marketingConsent: false, kvkkAccepted: true });
  assert.equal(r.status, 'created');
  const c = await data(`customers/${r.customer.id}`);
  assert.deepEqual([c.phone, c.source, c.birthDate, c.stamps], ['5441230002', 'app', '03-08', 0]);
  assert.equal((await data('customerPhones/5441230002')).customerId, r.customer.id);
  await refresh(can);
  const u = await can.call('updateMyProfile', { name: 'Can Bulut', marketingConsent: true });
  assert.deepEqual([u.customer.name, u.customer.marketingConsent], ['Can Bulut', true]);
  await expectCallError(can.call('updateMyProfile', { birthDate: '13-40' }), 'invalid-argument');
  // Personel hesabı müşteri olamaz
  await expectCallError(owner.call('linkCustomer', {}), 'permission-denied');
});

test('dinamik QR kasada bir kez okunur; geçmiş siparişler; hesabı silme', async () => {
  const ayse = await phoneUser('+905321230003');
  const r = await ayse.call('linkCustomer', { name: 'Zeynep', marketingConsent: false, kvkkAccepted: true });
  await refresh(ayse);
  const id = r.customer.id;
  const { qr } = await ayse.call('getLoyaltyQr', {});
  assert.match(qr, /^KAFE:LOYALTY:[0-9a-f]{32}$/);
  const res = await term.call('resolveLoyaltyToken', { token: qr });
  assert.equal(res.customerId, id);
  await expectCallError(term.call('resolveLoyaltyToken', { token: qr }), 'not-found');
  await adminDb.doc('orders/APPO1').set({ id: 'APPO1', no: 'A9', businessDay: '2026-10-16', status: 'paid', total: 19000,
    closedAt: '2026-10-16T12:00:00+03:00', customer: { id, name: 'Zeynep' }, stamps: 2,
    items: [{ productId: 'latte', name: 'Latte', qty: 2, status: 'active', options: [] }, { productId: 'k', name: 'Kek', qty: 1, status: 'void' }] });
  const orders = await ayse.call('myOrders', {});
  assert.deepEqual([orders.length, orders[0].items.length, orders[0].items[0].qty], [1, 1, 2]);
  // Üyeliği olmayan oturum QR alamaz
  const nobody = await phoneUser('+905551230004');
  await expectCallError(nobody.call('getLoyaltyQr', {}), 'failed-precondition');
  await ayse.call('deleteMyAccount', {});
  const c = await data(`customers/${id}`);
  assert.deepEqual([c.deleted, c.phone, c.authUid], [true, null, null]);
  assert.equal(await data('customerPhones/5321230003'), undefined);
  await assert.rejects(getAuth().getUser(ayse.auth.currentUser.uid));
});
