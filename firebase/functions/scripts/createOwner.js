// İlk yöneticiyi (owner) oluşturur. Sonraki tüm personeli bu kişi NexPOS panelinden ekler.
//
// Kullanım:
//   GOOGLE_APPLICATION_CREDENTIALS=servis-hesabi.json \
//     node scripts/createOwner.js <e-posta> <şifre> "<Ad Soyad>" <6 haneli PIN>
//
// Emülatörde denemek için FIRESTORE_EMULATOR_HOST ve FIREBASE_AUTH_EMULATOR_HOST
// ortam değişkenlerini ayarlayın.

const { initializeApp } = require('firebase-admin/app');
const { getAuth } = require('firebase-admin/auth');
const { getFirestore, FieldValue } = require('firebase-admin/firestore');
const { isValidPin, hashPin } = require('../src/lib');

async function createOwner({ email, password, name, pin }) {
  if (!email || !password || !name || !pin) {
    throw new Error('Kullanım: node scripts/createOwner.js <e-posta> <şifre> "<Ad Soyad>" <PIN>');
  }
  if (password.length < 8) throw new Error('Şifre en az 8 karakter olmalıdır.');
  if (!isValidPin(pin)) throw new Error('PIN 6 haneli olmalı ve kolay tahmin edilmemelidir.');

  const db = getFirestore();
  const auth = getAuth();
  const ref = db.collection('staff').doc();
  await auth.createUser({ uid: ref.id, email: email.toLowerCase(), password, displayName: name });
  await auth.setCustomUserClaims(ref.id, { role: 'owner' });

  const batch = db.batch();
  batch.set(ref, {
    name,
    phone: null,
    role: 'owner',
    email: email.toLowerCase(),
    active: true,
    deleted: false,
    pinVersion: 1,
    createdAt: FieldValue.serverTimestamp(),
    updatedAt: FieldValue.serverTimestamp(),
  });
  batch.set(db.doc(`staffPins/${ref.id}`), {
    ...hashPin(pin),
    pinVersion: 1,
    updatedAt: FieldValue.serverTimestamp(),
  });
  batch.set(db.collection('auditLogs').doc(), {
    action: 'staff_create',
    actor: 'createOwner-script',
    target: ref.id,
    after: { name, role: 'owner' },
    at: FieldValue.serverTimestamp(),
  });
  await batch.commit();
  return ref.id;
}

if (require.main === module) {
  initializeApp();
  const [email, password, name, pin] = process.argv.slice(2);
  createOwner({ email, password, name, pin })
    .then((id) => {
      console.log(`Yönetici oluşturuldu: ${name} <${email}> (staffId: ${id})`);
      process.exit(0);
    })
    .catch((e) => {
      console.error(e.message || e);
      process.exit(1);
    });
}

module.exports = { createOwner };
