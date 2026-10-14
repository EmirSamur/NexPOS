// NexPOS Cloud Functions.
//
// Personel, yetki ve terminal işlemleri ile terminalden gelen işlem kuyruğu (syncOps)
// yalnızca burada yazılır. Firestore kuralları bu koleksiyonlara istemciden yazmayı
// engeller; Admin SDK kuralları atladığı için fonksiyonlar tek yetkili yazıcıdır.
//
// Kimlikler:
//   - Yönetici / müdür: Firebase Auth kullanıcısı, uid = staff doküman kimliği,
//     custom claim { role }.
//   - Diğer personel: Auth hesabı yoktur; terminalde PIN ile giriş yapar.
//   - Terminal (kafedeki NexPOS): uid = "terminal-<id>", custom claim
//     { terminal: true, terminalId }.

const { initializeApp } = require('firebase-admin/app');
const { getAuth } = require('firebase-admin/auth');
const { getFirestore, FieldValue, Timestamp } = require('firebase-admin/firestore');
const { setGlobalOptions } = require('firebase-functions/v2');
const { onCall, HttpsError } = require('firebase-functions/v2/https');

const {
  ROLES,
  PERMISSIONS,
  normalizePermissions,
  hasPermission,
  canManageRole,
  roleNeedsEmail,
  isValidPin,
  hashPin,
  nextTerminalLetter,
  normalizePhone,
  validateOpsBatch,
} = require('./src/lib');

initializeApp();
const db = getFirestore();

setGlobalOptions({ region: 'europe-west1', maxInstances: 10 });

const TERMINAL_UID_PREFIX = 'terminal-';

// ---------------------------------------------------------------------------
// Yardımcılar
// ---------------------------------------------------------------------------

function requireAuth(request) {
  if (!request.auth) {
    throw new HttpsError('unauthenticated', 'Bu işlem için giriş yapmalısınız.');
  }
  return request.auth.uid;
}

async function loadPermissionMatrix() {
  const snap = await db.doc('settings/permissions').get();
  return snap.exists ? normalizePermissions(snap.data().roles) : normalizePermissions(null);
}

// Panelden (e-posta ile) giriş yapmış ve aktif olan personeli döndürür.
async function requireStaff(request, permission) {
  const uid = requireAuth(request);
  const role = request.auth.token.role;
  if (!ROLES.includes(role)) {
    throw new HttpsError('permission-denied', 'Bu işlem için personel hesabı gerekir.');
  }
  const staffSnap = await db.doc(`staff/${uid}`).get();
  if (!staffSnap.exists || staffSnap.data().active !== true) {
    throw new HttpsError('permission-denied', 'Personel kaydınız pasif durumda.');
  }
  if (permission) {
    const matrix = await loadPermissionMatrix();
    if (!hasPermission(matrix, role, permission, staffSnap.data().permissions)) {
      throw new HttpsError('permission-denied', 'Bu işlem için yetkiniz yok.');
    }
  }
  return { uid, role, staff: staffSnap.data() };
}

async function requireTerminal(request) {
  requireAuth(request);
  const { terminal, terminalId } = request.auth.token;
  if (terminal !== true || typeof terminalId !== 'string') {
    throw new HttpsError('permission-denied', 'Bu işlem yalnızca kayıtlı terminallerden yapılabilir.');
  }
  const ref = db.doc(`terminals/${terminalId}`);
  const snap = await ref.get();
  if (!snap.exists || snap.data().revoked === true) {
    throw new HttpsError('permission-denied', 'Bu terminal iptal edilmiş.');
  }
  return { terminalId, ref, terminal: snap.data() };
}

function requireString(value, field, { min = 1, max = 200 } = {}) {
  if (typeof value !== 'string') {
    throw new HttpsError('invalid-argument', `${field} alanı geçersiz.`);
  }
  const trimmed = value.trim();
  if (trimmed.length < min || trimmed.length > max) {
    throw new HttpsError('invalid-argument', `${field} alanı ${min}-${max} karakter olmalıdır.`);
  }
  return trimmed;
}

function requireRole(value) {
  if (!ROLES.includes(value)) {
    throw new HttpsError('invalid-argument', 'Geçersiz rol.');
  }
  return value;
}

function requirePin(value) {
  if (!isValidPin(value)) {
    throw new HttpsError(
      'invalid-argument',
      'PIN 6 haneli olmalı; 123456, 111111 gibi kolay tahmin edilen PIN kullanılamaz.',
    );
  }
  return value;
}

function optionalPhone(value) {
  if (value === undefined || value === null || value === '') return null;
  const phone = normalizePhone(value);
  if (!phone) throw new HttpsError('invalid-argument', 'Telefon 5XXXXXXXXX biçiminde olmalıdır.');
  return phone;
}

function audit(tx, entry) {
  tx.set(db.collection('auditLogs').doc(), {
    ...entry,
    at: FieldValue.serverTimestamp(),
  });
}

async function countActiveOwners() {
  const snap = await db
    .collection('staff')
    .where('role', '==', 'owner')
    .where('active', '==', true)
    .get();
  return snap.size;
}

async function authUserExists(uid) {
  try {
    await getAuth().getUser(uid);
    return true;
  } catch (e) {
    if (e.code === 'auth/user-not-found') return false;
    throw e;
  }
}

// Firebase Auth hata kodlarını kullanıcıya anlaşılır mesajlara çevirir.
function authError(e) {
  if (e.code === 'auth/email-already-exists') {
    return new HttpsError('already-exists', 'Bu e-posta adresi başka bir hesapta kayıtlı.');
  }
  if (e.code === 'auth/invalid-password') {
    return new HttpsError('invalid-argument', 'Şifre en az 8 karakter olmalıdır.');
  }
  if (e.code === 'auth/invalid-email') {
    return new HttpsError('invalid-argument', 'E-posta adresi geçersiz.');
  }
  return e;
}

// Rolün e-posta ile panel girişi gerektirip gerektirmediğine göre Auth hesabını
// oluşturur, günceller ya da kaldırır. Transaction dışında çağrılır.
async function syncAuthAccount(staffId, { role, name, email, password, active }) {
  const exists = await authUserExists(staffId);
  if (roleNeedsEmail(role)) {
    if (!exists) {
      if (!email || !password) {
        throw new HttpsError(
          'invalid-argument',
          'Yönetici ve müdür için panel girişi e-postası ve şifresi gerekir.',
        );
      }
      try {
        await getAuth().createUser({ uid: staffId, email, password, displayName: name });
      } catch (e) {
        throw authError(e);
      }
    } else {
      const update = { displayName: name, disabled: !active };
      if (email) update.email = email;
      if (password) update.password = password;
      try {
        await getAuth().updateUser(staffId, update);
      } catch (e) {
        throw authError(e);
      }
    }
    await getAuth().setCustomUserClaims(staffId, { role });
    if (!active) await getAuth().revokeRefreshTokens(staffId);
    return email || (await getAuth().getUser(staffId)).email;
  }
  if (exists) {
    // Panel yetkisi olmayan role düşürüldü: e-posta hesabı kaldırılır.
    await getAuth().deleteUser(staffId);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Terminal eşleme
// ---------------------------------------------------------------------------

// Kafedeki bir bilgisayarı terminal olarak kaydeder. Yönetici e-postasıyla giriş
// yapılmış NexPOS'tan çağrılır; dönen customToken ile terminal kendi hesabına geçer.
exports.registerTerminal = onCall(async (request) => {
  const actor = await requireStaff(request, 'settings');
  const name = requireString(request.data?.name, 'Terminal adı', { max: 40 });
  const appVersion = typeof request.data?.appVersion === 'string' ? request.data.appVersion.slice(0, 20) : null;

  const ref = db.collection('terminals').doc();
  const letter = await db.runTransaction(async (tx) => {
    const active = await tx.get(db.collection('terminals').where('revoked', '==', false));
    const next = nextTerminalLetter(active.docs.map((d) => d.data().letter));
    if (!next) throw new HttpsError('resource-exhausted', 'Terminal sınırına ulaşıldı.');
    tx.set(ref, {
      name,
      letter: next,
      deviceUid: TERMINAL_UID_PREFIX + ref.id,
      revoked: false,
      pendingOps: 0,
      appVersion,
      lastSeenAt: FieldValue.serverTimestamp(),
      createdBy: actor.uid,
      createdAt: FieldValue.serverTimestamp(),
      updatedAt: FieldValue.serverTimestamp(),
    });
    audit(tx, { action: 'terminal_register', actor: actor.uid, target: ref.id, after: { name, letter: next } });
    return next;
  });

  const uid = TERMINAL_UID_PREFIX + ref.id;
  const claims = { terminal: true, terminalId: ref.id };
  await getAuth().createUser({ uid, displayName: `Terminal ${letter} · ${name}` });
  await getAuth().setCustomUserClaims(uid, claims);
  const customToken = await getAuth().createCustomToken(uid, claims);

  return { terminalId: ref.id, letter, name, customToken };
});

exports.revokeTerminal = onCall(async (request) => {
  const actor = await requireStaff(request, 'settings');
  const terminalId = requireString(request.data?.terminalId, 'Terminal', { max: 64 });
  const ref = db.doc(`terminals/${terminalId}`);
  const snap = await ref.get();
  if (!snap.exists) throw new HttpsError('not-found', 'Terminal bulunamadı.');
  if (snap.data().revoked === true) return { revoked: true };

  await db.runTransaction(async (tx) => {
    tx.update(ref, {
      revoked: true,
      revokedAt: FieldValue.serverTimestamp(),
      revokedBy: actor.uid,
      updatedAt: FieldValue.serverTimestamp(),
    });
    audit(tx, { action: 'terminal_revoke', actor: actor.uid, target: terminalId });
  });
  const uid = TERMINAL_UID_PREFIX + terminalId;
  if (await authUserExists(uid)) {
    await getAuth().updateUser(uid, { disabled: true });
    await getAuth().revokeRefreshTokens(uid);
  }
  return { revoked: true };
});

// Terminal her senkronda çağırır: canlı olduğunu ve kuyruktaki işlem sayısını bildirir.
exports.terminalHeartbeat = onCall(async (request) => {
  const { ref } = await requireTerminal(request);
  const pending = Number.isInteger(request.data?.pending) && request.data.pending >= 0 ? request.data.pending : 0;
  const appVersion = typeof request.data?.appVersion === 'string' ? request.data.appVersion.slice(0, 20) : null;
  await ref.update({
    lastSeenAt: FieldValue.serverTimestamp(),
    pendingOps: pending,
    appVersion,
    updatedAt: FieldValue.serverTimestamp(),
  });
  return { serverTime: Date.now() };
});

// ---------------------------------------------------------------------------
// Personel
// ---------------------------------------------------------------------------

exports.manageStaff = onCall(async (request) => {
  const actor = await requireStaff(request, 'manageUsers');
  const data = request.data || {};
  const action = data.action;

  if (action === 'create') {
    const name = requireString(data.name, 'Ad soyad', { min: 2, max: 80 });
    const role = requireRole(data.role);
    if (!canManageRole(actor.role, role)) {
      throw new HttpsError('permission-denied', 'Bu rolde personel ekleme yetkiniz yok.');
    }
    const phone = optionalPhone(data.phone);
    const pin = requirePin(data.pin);
    const ref = db.collection('staff').doc();
    const email = await syncAuthAccount(ref.id, {
      role,
      name,
      email: typeof data.email === 'string' ? data.email.trim().toLowerCase() : null,
      password: data.password,
      active: true,
    });
    await db.runTransaction(async (tx) => {
      tx.set(ref, {
        name,
        phone,
        role,
        email,
        active: true,
        deleted: false,
        pinVersion: 1,
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
      tx.set(db.doc(`staffPins/${ref.id}`), {
        ...hashPin(pin),
        pinVersion: 1,
        updatedAt: FieldValue.serverTimestamp(),
      });
      audit(tx, { action: 'staff_create', actor: actor.uid, target: ref.id, after: { name, role } });
    });
    return { staffId: ref.id };
  }

  const staffId = requireString(data.staffId, 'Personel', { max: 128 });
  const ref = db.doc(`staff/${staffId}`);
  const snap = await ref.get();
  if (!snap.exists || snap.data().deleted === true) {
    throw new HttpsError('not-found', 'Personel bulunamadı.');
  }
  const current = snap.data();
  if (!canManageRole(actor.role, current.role)) {
    throw new HttpsError('permission-denied', 'Bu personeli düzenleme yetkiniz yok.');
  }

  if (action === 'update') {
    const name = requireString(data.name ?? current.name, 'Ad soyad', { min: 2, max: 80 });
    const role = requireRole(data.role ?? current.role);
    if (!canManageRole(actor.role, role)) {
      throw new HttpsError('permission-denied', 'Bu rolü atama yetkiniz yok.');
    }
    if (current.role === 'owner' && role !== 'owner' && (await countActiveOwners()) <= 1) {
      throw new HttpsError('failed-precondition', 'Sistemde en az bir aktif yönetici kalmalıdır.');
    }
    const phone = data.phone === undefined ? current.phone ?? null : optionalPhone(data.phone);
    const email = await syncAuthAccount(staffId, {
      role,
      name,
      email: typeof data.email === 'string' && data.email.trim() ? data.email.trim().toLowerCase() : null,
      password: data.password || null,
      active: current.active,
    });
    await db.runTransaction(async (tx) => {
      tx.update(ref, { name, role, phone, email, updatedAt: FieldValue.serverTimestamp() });
      audit(tx, {
        action: role !== current.role ? 'role_change' : 'staff_update',
        actor: actor.uid,
        target: staffId,
        before: { name: current.name, role: current.role },
        after: { name, role },
      });
    });
    return { staffId };
  }

  if (action === 'setPin') {
    const pin = requirePin(data.pin);
    const pinVersion = (Number(current.pinVersion) || 0) + 1;
    await db.runTransaction(async (tx) => {
      tx.update(ref, { pinVersion, updatedAt: FieldValue.serverTimestamp() });
      tx.set(db.doc(`staffPins/${staffId}`), {
        ...hashPin(pin),
        pinVersion,
        updatedAt: FieldValue.serverTimestamp(),
      });
      audit(tx, { action: 'pin_reset', actor: actor.uid, target: staffId });
    });
    return { staffId, pinVersion };
  }

  if (action === 'setActive') {
    if (typeof data.active !== 'boolean') {
      throw new HttpsError('invalid-argument', 'active alanı true/false olmalıdır.');
    }
    if (staffId === actor.uid && data.active === false) {
      throw new HttpsError('failed-precondition', 'Kendi hesabınızı pasife alamazsınız.');
    }
    if (current.role === 'owner' && data.active === false && (await countActiveOwners()) <= 1) {
      throw new HttpsError('failed-precondition', 'Sistemde en az bir aktif yönetici kalmalıdır.');
    }
    if (await authUserExists(staffId)) {
      await getAuth().updateUser(staffId, { disabled: !data.active });
      if (!data.active) await getAuth().revokeRefreshTokens(staffId);
    }
    await db.runTransaction(async (tx) => {
      tx.update(ref, { active: data.active, updatedAt: FieldValue.serverTimestamp() });
      audit(tx, {
        action: data.active ? 'staff_activate' : 'staff_deactivate',
        actor: actor.uid,
        target: staffId,
      });
    });
    return { staffId, active: data.active };
  }

  throw new HttpsError('invalid-argument', 'Bilinmeyen işlem.');
});

// ---------------------------------------------------------------------------
// Yetki matrisi
// ---------------------------------------------------------------------------

// Matrisi yalnızca yönetici (owner) değiştirebilir; aksi hâlde bir müdür kendi
// rolüne istediği yetkiyi verebilirdi.
exports.savePermissions = onCall(async (request) => {
  const actor = await requireStaff(request);
  if (actor.role !== 'owner') {
    throw new HttpsError('permission-denied', 'Yetki matrisini yalnızca yönetici değiştirebilir.');
  }
  const roles = normalizePermissions(request.data?.roles);
  const ref = db.doc('settings/permissions');
  await db.runTransaction(async (tx) => {
    const before = await tx.get(ref);
    tx.set(ref, {
      roles,
      permissions: PERMISSIONS,
      updatedBy: actor.uid,
      updatedAt: FieldValue.serverTimestamp(),
    });
    audit(tx, {
      action: 'permissions_change',
      actor: actor.uid,
      target: 'settings/permissions',
      before: before.exists ? before.data().roles : null,
      after: roles,
    });
  });
  return { roles };
});

// ---------------------------------------------------------------------------
// Terminal işlem kuyruğu
// ---------------------------------------------------------------------------

// Terminalde çevrimdışıyken biriken işlemler buraya sırayla gönderilir. Her işlem
// kendi transaction'ında, processedOps/{opId} kaydıyla birlikte işlenir; aynı işlem
// ikinci kez gelirse "duplicate" döner ve tekrar uygulanmaz.
//
// Desteklenmeyen işlemler "unsupported" döner ve terminalde kuyrukta kalır; böylece
// sunucu güncellendiğinde kaybolmadan işlenir.
const OP_HANDLERS = {
  // Personelin PIN ile girişi. payload: { method: 'pin' }
  async staffLogin(tx, { op, staff, staffRef }) {
    if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
    tx.update(staffRef, {
      lastLoginAt: parseClientTime(op.createdAt),
      updatedAt: FieldValue.serverTimestamp(),
    });
    return { status: 'ok' };
  },

  // Yetkili onayı ve terminalde yapılan kritik işlemlerin kaydı.
  // payload: { action, detail?, reason?, approvedBy? }
  async audit(tx, { op, terminalId, staff }) {
    if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
    const p = op.payload;
    if (typeof p.action !== 'string' || !/^[a-z_]{1,40}$/.test(p.action)) {
      return { status: 'rejected', error: 'Geçersiz kayıt türü.' };
    }
    audit(tx, {
      action: p.action,
      actor: op.staffId,
      approvedBy: typeof p.approvedBy === 'string' ? p.approvedBy.slice(0, 128) : null,
      detail: typeof p.detail === 'string' ? p.detail.slice(0, 500) : null,
      reason: typeof p.reason === 'string' ? p.reason.slice(0, 200) : null,
      terminalId,
      clientAt: parseClientTime(op.createdAt),
    });
    return { status: 'ok' };
  },
};

function parseClientTime(value) {
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? Timestamp.fromMillis(ms) : FieldValue.serverTimestamp();
}

exports.syncOps = onCall(async (request) => {
  const { terminalId, ref: terminalRef } = await requireTerminal(request);
  const ops = request.data?.ops;
  if (!validateOpsBatch(ops)) {
    throw new HttpsError('invalid-argument', 'İşlem paketi geçersiz.');
  }

  const results = [];
  for (const op of ops) {
    const handler = OP_HANDLERS[op.op];
    if (!handler) {
      results.push({ opId: op.opId, status: 'unsupported' });
      continue;
    }
    const processedRef = db.doc(`processedOps/${op.opId}`);
    const staffRef = db.doc(`staff/${op.staffId}`);
    const result = await db.runTransaction(async (tx) => {
      const [processed, staffSnap] = await Promise.all([tx.get(processedRef), tx.get(staffRef)]);
      if (processed.exists) return { status: 'duplicate' };
      const staff = staffSnap.exists ? staffSnap.data() : null;
      const outcome = await handler(tx, { op, terminalId, staff, staffRef });
      tx.set(processedRef, {
        op: op.op,
        terminalId,
        status: outcome.status,
        error: outcome.error || null,
        at: FieldValue.serverTimestamp(),
      });
      return outcome;
    });
    results.push({ opId: op.opId, ...result });
  }

  await terminalRef.update({
    lastSeenAt: FieldValue.serverTimestamp(),
    updatedAt: FieldValue.serverTimestamp(),
  });
  return { results };
});
