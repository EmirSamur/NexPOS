// Firestore kuralları + Cloud Functions emülatör testleri.
// Çalıştırma: cd firebase/tests && npm install && npm test

const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');

process.env.FIRESTORE_EMULATOR_HOST ||= '127.0.0.1:8080';
process.env.FIREBASE_AUTH_EMULATOR_HOST ||= '127.0.0.1:9099';
process.env.GCLOUD_PROJECT ||= 'demo-nexpos';

const admin = require('firebase-admin/app');
const { getFirestore } = require('firebase-admin/firestore');
admin.initializeApp({ projectId: 'demo-nexpos' });
const adminDb = getFirestore();

const { initializeApp, deleteApp, getApps } = require('firebase/app');
const {
  getAuth,
  connectAuthEmulator,
  signInWithEmailAndPassword,
  signInWithCustomToken,
} = require('firebase/auth');
const {
  getFirestore: clientFirestore,
  connectFirestoreEmulator,
  doc,
  getDoc,
  getDocs,
  setDoc,
  collection,
} = require('firebase/firestore');
const { getFunctions, connectFunctionsEmulator, httpsCallable } = require('firebase/functions');

const path = require('path');
const { execFileSync } = require('child_process');

// İlk yönetici, kurulumda kullanılan betiğin kendisiyle oluşturulur.
function createOwner({ email, password, name, pin }) {
  const out = execFileSync(
    'node',
    [path.join(__dirname, '../functions/scripts/createOwner.js'), email, password, name, pin],
    { env: process.env, encoding: 'utf8' },
  );
  return out.match(/staffId: ([A-Za-z0-9]+)/)[1];
}

const OWNER = { email: 'sahip@kafe.test', password: 'sahip-sifre-1', name: 'Deniz Yılmaz', pin: '482913' };

let appCounter = 0;
function client() {
  const app = initializeApp({ projectId: 'demo-nexpos', apiKey: 'demo-key' }, `c${appCounter++}`);
  const auth = getAuth(app);
  connectAuthEmulator(auth, 'http://127.0.0.1:9099', { disableWarnings: true });
  const db = clientFirestore(app);
  connectFirestoreEmulator(db, '127.0.0.1', 8080);
  const fns = getFunctions(app, 'europe-west1');
  connectFunctionsEmulator(fns, '127.0.0.1', 5001);
  const call = (name, data) => httpsCallable(fns, name)(data).then((r) => r.data);
  return { app, auth, db, call };
}

async function signedInAs(email, password) {
  const c = client();
  await signInWithEmailAndPassword(c.auth, email, password);
  return c;
}

async function expectDenied(promise) {
  await assert.rejects(promise, (e) => /permission|PERMISSION_DENIED/i.test(e.code || e.message));
}

async function expectCallError(promise, code) {
  await assert.rejects(promise, (e) => e.code === `functions/${code}`);
}

let owner;
let ownerId;

before(async () => {
  ownerId = createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
});

// Açık kalan bağlantılar test sürecinin kapanmasını engellemesin.
after(async () => {
  await Promise.all(getApps().map((a) => deleteApp(a)));
  await adminDb.terminate();
});

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
  assert.equal(reg.letter, 'A');
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

  // İkinci terminal B harfini alır.
  const reg2 = await owner.call('registerTerminal', { name: 'Kasa 2' });
  assert.equal(reg2.letter, 'B');

  // İptal: mevcut token ile bile veri okunamaz, fonksiyon çağrılamaz; kendi kaydı okunabilir.
  await owner.call('revokeTerminal', { terminalId: reg.terminalId });
  await expectDenied(getDocs(collection(term.db, 'staffPins')));
  await expectCallError(term.call('syncOps', { ops: ops.slice(0, 1) }), 'permission-denied');
  const own = await getDoc(doc(term.db, `terminals/${reg.terminalId}`));
  assert.equal(own.data().revoked, true);
  await deleteApp(term.app);
});
