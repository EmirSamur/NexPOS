// Firestore kuralları + Cloud Functions emülatör testleri.
// Çalıştırma: cd firebase/tests && npm install && npm test

const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');

const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll, deleteApp } =
  require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc, getDocs, setDoc, collection } = require('firebase/firestore');

const OWNER = { email: 'sahip@kafe.test', password: 'sahip-sifre-1', name: 'Deniz Yılmaz', pin: '482913' };

let owner;
let ownerId;

before(async () => {
  ownerId = createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
});

// Açık kalan bağlantılar test sürecinin kapanmasını engellemesin.
after(closeAll);

test('giriş yapmamış kullanıcı hiçbir şey okuyamaz', async () => {
  const anon = client();
  await expectDenied(getDocs(collection(anon.db, 'staff')));
  await expectDenied(getDoc(doc(anon.db, 'settings/permissions')));
  await deleteApp(anon.app);
});

test('yönetici personeli okuyabilir ama PIN özetlerini okuyamaz, doğrudan yazamaz', async () => {
  const snap = await getDoc(doc(owner.db, `staff/${ownerId}`));
  assert.equal(snap.data().role, 'owner');
  await expectDenied(getDoc(doc(owner.db, `staffPins/${ownerId}`)));
  await expectDenied(setDoc(doc(owner.db, `staff/${ownerId}`), { role: 'owner', name: 'x' }));
});

test('personel ekleme: PIN ve rol kuralları', async () => {
  const { staffId } = await owner.call('manageStaff', {
    action: 'create',
    name: 'Cem Akar',
    role: 'waiter',
    phone: '0535 987 65 43',
    pin: '730591',
  });
  const s = (await adminDb.doc(`staff/${staffId}`).get()).data();
  assert.equal(s.role, 'waiter');
  assert.equal(s.phone, '5359876543');
  assert.equal(s.email, null);
  const pin = (await adminDb.doc(`staffPins/${staffId}`).get()).data();
  assert.equal(pin.algo, 'scrypt');
  assert.equal(pin.pinVersion, 1);

  await expectCallError(
    owner.call('manageStaff', { action: 'create', name: 'Kolay', role: 'waiter', pin: '123456' }),
    'invalid-argument',
  );
  // Müdür için e-posta ve şifre zorunlu.
  await expectCallError(
    owner.call('manageStaff', { action: 'create', name: 'Müdür', role: 'manager', pin: '730592' }),
    'invalid-argument',
  );
});

test('müdür: garson ekler, müdür ekleyemez, yetki matrisini değiştiremez', async () => {
  await owner.call('manageStaff', {
    action: 'create',
    name: 'Mert Kaya',
    role: 'manager',
    email: 'mudur@kafe.test',
    password: 'mudur-sifre-1',
    pin: '583920',
  });
  const manager = await signedInAs('mudur@kafe.test', 'mudur-sifre-1');
  await manager.call('manageStaff', { action: 'create', name: 'Elif Demir', role: 'waiter', pin: '640218' });
  await expectCallError(
    manager.call('manageStaff', {
      action: 'create',
      name: 'Başka Müdür',
      role: 'manager',
      email: 'mudur2@kafe.test',
      password: 'mudur-sifre-2',
      pin: '583921',
    }),
    'permission-denied',
  );
  await expectCallError(manager.call('savePermissions', { roles: {} }), 'permission-denied');
  await expectCallError(manager.call('registerTerminal', { name: 'Kasa 9' }), 'permission-denied');
  await deleteApp(manager.app);
});

test('yetki matrisi: yönetici kaydeder, normalize edilir', async () => {
  const { roles } = await owner.call('savePermissions', {
    roles: { waiter: { discount: true }, owner: { settings: false } },
  });
  assert.equal(roles.waiter.discount, true);
  assert.equal(roles.owner.settings, true);
  const saved = (await getDoc(doc(owner.db, 'settings/permissions'))).data();
  assert.equal(saved.roles.waiter.discount, true);
});

test('rol değişikliği: garson müdür olunca panel hesabı açılır, geri alınca kapanır', async () => {
  const { staffId } = await owner.call('manageStaff', {
    action: 'create',
    name: 'Ayşe Tan',
    role: 'waiter',
    pin: '902817',
  });
  await expectCallError(owner.call('manageStaff', { action: 'update', staffId, role: 'manager' }), 'invalid-argument');
  await owner.call('manageStaff', {
    action: 'update',
    staffId,
    role: 'manager',
    email: 'ayse@kafe.test',
    password: 'ayse-sifre-1',
  });
  const promoted = await signedInAs('ayse@kafe.test', 'ayse-sifre-1');
  const token = await promoted.auth.currentUser.getIdTokenResult(true);
  assert.equal(token.claims.role, 'manager');
  await deleteApp(promoted.app);

  await owner.call('manageStaff', { action: 'update', staffId, role: 'cashier' });
  const s = (await adminDb.doc(`staff/${staffId}`).get()).data();
  assert.equal(s.role, 'cashier');
  assert.equal(s.email, null);
  await assert.rejects(signedInAs('ayse@kafe.test', 'ayse-sifre-1'));
});

test('son aktif yönetici pasife alınamaz ve müdüre düşürülemez', async () => {
  // Diğer test dosyalarının açtığı yöneticiler bu testi etkilemesin.
  const owners = await adminDb.collection('staff').where('role', '==', 'owner').get();
  await Promise.all(owners.docs.filter((d) => d.id !== ownerId).map((d) => d.ref.update({ active: false })));
  await expectCallError(
    owner.call('manageStaff', { action: 'setActive', staffId: ownerId, active: false }),
    'failed-precondition',
  );
  await expectCallError(
    owner.call('manageStaff', {
      action: 'update',
      staffId: ownerId,
      role: 'manager',
    }),
    'failed-precondition',
  );
});

test('terminal: eşleme, okuma yetkileri, işlem kuyruğu ve iptal', async () => {
  const reg = await owner.call('registerTerminal', { name: 'Kasa 1', appVersion: '4.0.0' });
  assert.match(reg.letter, /^[A-Z]$/);
  assert.ok(reg.customToken);

  const term = client();
  await signInWithCustomToken(term.auth, reg.customToken);

  // Terminal personeli, PIN özetlerini ve ayarları okuyabilir; yazamaz.
  const staff = await getDocs(collection(term.db, 'staff'));
  assert.ok(staff.size >= 2);
  const pins = await getDocs(collection(term.db, 'staffPins'));
  assert.equal(pins.size, staff.size);
  await getDoc(doc(term.db, 'settings/permissions'));
  await expectDenied(setDoc(doc(term.db, `staff/${ownerId}`), { role: 'waiter' }));
  await expectDenied(getDocs(collection(term.db, 'auditLogs')));

  // Personel paneli fonksiyonlarını terminal çağıramaz.
  await expectCallError(term.call('manageStaff', { action: 'create' }), 'permission-denied');

  const ops = [
    { opId: 'op-00000001', op: 'staffLogin', payload: { method: 'pin' }, staffId: ownerId, createdAt: new Date().toISOString() },
    {
      opId: 'op-00000002',
      op: 'audit',
      payload: { action: 'approval_discount', detail: 'Masa 4 · %10', approvedBy: ownerId, reason: 'Müdür onayı' },
      staffId: ownerId,
      createdAt: new Date().toISOString(),
    },
    { opId: 'op-00000003', op: 'addItems', payload: {}, staffId: ownerId, createdAt: new Date().toISOString() },
    { opId: 'op-00000004', op: 'staffLogin', payload: {}, staffId: 'yok-boyle-biri', createdAt: new Date().toISOString() },
  ];
  const first = await term.call('syncOps', { ops });
  assert.deepEqual(
    first.results.map((r) => r.status),
    ['ok', 'ok', 'unsupported', 'rejected'],
  );
  const again = await term.call('syncOps', { ops: ops.slice(0, 2) });
  assert.deepEqual(again.results.map((r) => r.status), ['duplicate', 'duplicate']);

  const logs = await adminDb.collection('auditLogs').where('action', '==', 'approval_discount').get();
  assert.equal(logs.size, 1);
  assert.equal(logs.docs[0].data().terminalId, reg.terminalId);
  assert.ok((await adminDb.doc(`staff/${ownerId}`).get()).data().lastLoginAt);

  await term.call('terminalHeartbeat', { pending: 3, appVersion: '4.0.0' });
  assert.equal((await adminDb.doc(`terminals/${reg.terminalId}`).get()).data().pendingOps, 3);

  // İkinci terminal farklı bir harf alır.
  const reg2 = await owner.call('registerTerminal', { name: 'Kasa 2' });
  assert.match(reg2.letter, /^[A-Z]$/);
  assert.notEqual(reg2.letter, reg.letter);

  // İptal: mevcut token ile bile veri okunamaz, fonksiyon çağrılamaz; kendi kaydı okunabilir.
  await owner.call('revokeTerminal', { terminalId: reg.terminalId });
  await expectDenied(getDocs(collection(term.db, 'staffPins')));
  await expectCallError(term.call('syncOps', { ops: ops.slice(0, 1) }), 'permission-denied');
  const own = await getDoc(doc(term.db, `terminals/${reg.terminalId}`));
  assert.equal(own.data().revoked, true);
  await deleteApp(term.app);
});
