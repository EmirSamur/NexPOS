// Emülatör testlerinin ortak yardımcıları.
const assert = require('node:assert/strict');
const path = require('path');
const { execFileSync } = require('child_process');

process.env.FIRESTORE_EMULATOR_HOST ||= '127.0.0.1:8080';
process.env.FIREBASE_AUTH_EMULATOR_HOST ||= '127.0.0.1:9099';
process.env.FIREBASE_STORAGE_EMULATOR_HOST ||= '127.0.0.1:9199';
process.env.GCLOUD_PROJECT ||= 'demo-nexpos';

const admin = require('firebase-admin/app');
const { getFirestore } = require('firebase-admin/firestore');
if (!admin.getApps().length) admin.initializeApp({ projectId: 'demo-nexpos' });
const adminDb = getFirestore();

const { initializeApp, deleteApp, getApps } = require('firebase/app');
const { getAuth, connectAuthEmulator, signInWithEmailAndPassword } = require('firebase/auth');
const { getFirestore: clientFirestore, connectFirestoreEmulator } = require('firebase/firestore');
const { getFunctions, connectFunctionsEmulator, httpsCallable } = require('firebase/functions');

// İlk yönetici, kurulumda kullanılan betiğin kendisiyle oluşturulur.
function createOwner({ email, password, name, pin }) {
  const out = execFileSync(
    'node',
    [path.join(__dirname, '../functions/scripts/createOwner.js'), email, password, name, pin],
    { env: process.env, encoding: 'utf8' },
  );
  return out.match(/staffId: ([A-Za-z0-9]+)/)[1];
}

let appCounter = 0;
function client() {
  const app = initializeApp({ projectId: 'demo-nexpos', apiKey: 'demo-key' }, `c${process.pid}-${appCounter++}`);
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
  await assert.rejects(promise, (e) => /permission|PERMISSION_DENIED|unauthorized/i.test(e.code || e.message));
}

async function expectCallError(promise, code) {
  await assert.rejects(promise, (e) => e.code === `functions/${code}`);
}

async function closeAll() {
  await Promise.all(getApps().map((a) => deleteApp(a)));
  await adminDb.terminate();
}

module.exports = { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll, deleteApp };
