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
  MenuError,
  validateCategory,
  validateProduct,
  validateOptionGroup,
  validatePriceRule,
  applyPriceRule,
  validateArea,
  validateFloorPlan,
  newQrToken,
  gridLayout,
  validateGeneralSettings,
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
  // Ürünü ya da tek bir seçeneği "tükendi" işaretler (2. ekran). Servis sırasında
  // internet olmasa da terminalde yapılabilsin diye kuyruktan gelir.
  // payload: { productId, soldOut } ya da { optionGroupId, optionId, soldOut }
  async setSoldOut(tx, { op, terminalId, staff, matrix }) {
    if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
    if (!hasPermission(matrix, staff.role, 'markSoldOut', staff.permissions)) {
      return { status: 'rejected', error: 'Tükendi işaretleme yetkisi yok.' };
    }
    const p = op.payload;
    if (typeof p.soldOut !== 'boolean') return { status: 'rejected', error: 'soldOut true/false olmalıdır.' };
    const stamp = { updatedAt: FieldValue.serverTimestamp() };
    if (typeof p.productId === 'string' && p.productId) {
      const ref = db.doc(`products/${p.productId}`);
      const snap = await tx.get(ref);
      if (!snap.exists) return { status: 'rejected', error: 'Ürün bulunamadı.' };
      tx.update(ref, { soldOut: p.soldOut, ...stamp });
      audit(tx, { action: 'sold_out', actor: op.staffId, target: `products/${p.productId}`,
        after: { soldOut: p.soldOut }, terminalId, clientAt: parseClientTime(op.createdAt) });
      return { status: 'ok' };
    }
    if (typeof p.optionGroupId === 'string' && typeof p.optionId === 'string') {
      const ref = db.doc(`optionGroups/${p.optionGroupId}`);
      const snap = await tx.get(ref);
      if (!snap.exists) return { status: 'rejected', error: 'Seçenek grubu bulunamadı.' };
      const options = snap.data().options || [];
      if (!options.some((o) => o.id === p.optionId)) return { status: 'rejected', error: 'Seçenek bulunamadı.' };
      tx.update(ref, {
        options: options.map((o) => (o.id === p.optionId ? { ...o, soldOut: p.soldOut } : o)),
        ...stamp,
      });
      audit(tx, { action: 'sold_out', actor: op.staffId, target: `optionGroups/${p.optionGroupId}/${p.optionId}`,
        after: { soldOut: p.soldOut }, terminalId, clientAt: parseClientTime(op.createdAt) });
      return { status: 'ok' };
    }
    return { status: 'rejected', error: 'Ürün ya da seçenek belirtilmedi.' };
  },

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

  const matrix = await loadPermissionMatrix();
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
      const outcome = await handler(tx, { op, terminalId, staff, staffRef, matrix });
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

// ---------------------------------------------------------------------------
// Menü (2. ekran)
//
// Menü düzenleme internet ister ve yalnızca editMenu yetkisiyle yapılır. Silme
// fiziksel değildir (deleted: true); terminaller delta senkronla silineni de görür ve
// eski adisyonlar bozulmaz. Yeni kayıtların sırası (order) oluşturulma zamanıdır; böylece
// listenin sonuna düşer, reorderMenu ile 0..n olarak yeniden numaralanır.
// ---------------------------------------------------------------------------

function validated(fn, input) {
  try {
    return fn(input);
  } catch (e) {
    if (e instanceof MenuError) throw new HttpsError('invalid-argument', e.message);
    throw e;
  }
}

async function requireLive(ref, label) {
  const snap = await ref.get();
  if (!snap.exists || snap.data().deleted === true) {
    throw new HttpsError('not-found', `${label} bulunamadı.`);
  }
  return snap;
}

async function liveProductsWhere(field, op, value) {
  const snap = await db.collection('products').where(field, op, value).get();
  return snap.docs.filter((d) => d.data().deleted !== true);
}

exports.saveCategory = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const data = validated(validateCategory, request.data);
  const id = request.data?.id;
  const ref = id ? db.doc(`categories/${requireString(id, 'Kategori', { max: 128 })}`) : db.collection('categories').doc();
  const before = id ? (await requireLive(ref, 'Kategori')).data() : null;
  await db.runTransaction(async (tx) => {
    if (before) {
      tx.update(ref, { ...data, updatedAt: FieldValue.serverTimestamp() });
    } else {
      tx.set(ref, {
        ...data,
        order: Date.now(),
        deleted: false,
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
    }
    audit(tx, { action: before ? 'category_update' : 'category_create', actor: actor.uid,
      target: `categories/${ref.id}`, before: before ? { name: before.name } : null, after: { name: data.name } });
  });
  return { id: ref.id };
});

exports.deleteCategory = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const ref = db.doc(`categories/${requireString(request.data?.id, 'Kategori', { max: 128 })}`);
  const snap = await requireLive(ref, 'Kategori');
  const products = await liveProductsWhere('categoryId', '==', ref.id);
  if (products.length) {
    throw new HttpsError('failed-precondition',
      `Bu kategoride ${products.length} ürün var. Önce ürünleri başka kategoriye taşıyın ya da silin.`);
  }
  await db.runTransaction(async (tx) => {
    tx.update(ref, { deleted: true, updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'category_delete', actor: actor.uid, target: `categories/${ref.id}`,
      before: { name: snap.data().name } });
  });
  return { id: ref.id };
});

exports.saveProduct = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const data = validated(validateProduct, request.data);
  await requireLive(db.doc(`categories/${data.categoryId}`), 'Kategori');
  if (data.optionGroupIds.length) {
    const groups = await db.getAll(...data.optionGroupIds.map((g) => db.doc(`optionGroups/${g}`)));
    if (groups.some((g) => !g.exists || g.data().deleted === true)) {
      throw new HttpsError('not-found', 'Seçilen seçenek gruplarından biri bulunamadı.');
    }
  }
  const id = request.data?.id;
  const ref = id ? db.doc(`products/${requireString(id, 'Ürün', { max: 128 })}`) : db.collection('products').doc();
  const before = id ? (await requireLive(ref, 'Ürün')).data() : null;
  await db.runTransaction(async (tx) => {
    if (before) {
      tx.update(ref, { ...data, updatedAt: FieldValue.serverTimestamp() });
    } else {
      tx.set(ref, {
        ...data,
        soldOut: false,
        deleted: false,
        order: Date.now(),
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
    }
    if (before && before.price !== data.price) {
      audit(tx, { action: 'price_change', actor: actor.uid, target: `products/${ref.id}`,
        before: { name: before.name, price: before.price }, after: { name: data.name, price: data.price } });
    } else {
      audit(tx, { action: before ? 'product_update' : 'product_create', actor: actor.uid,
        target: `products/${ref.id}`, after: { name: data.name, price: data.price } });
    }
  });
  return { id: ref.id };
});

exports.deleteProduct = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const ref = db.doc(`products/${requireString(request.data?.id, 'Ürün', { max: 128 })}`);
  const snap = await requireLive(ref, 'Ürün');
  await db.runTransaction(async (tx) => {
    tx.update(ref, { deleted: true, active: false, updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'product_delete', actor: actor.uid, target: `products/${ref.id}`,
      before: { name: snap.data().name, price: snap.data().price } });
  });
  return { id: ref.id };
});

exports.saveOptionGroup = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const data = validated(validateOptionGroup, request.data);
  const id = request.data?.id;
  const ref = id ? db.doc(`optionGroups/${requireString(id, 'Seçenek grubu', { max: 128 })}`) : db.collection('optionGroups').doc();
  const before = id ? (await requireLive(ref, 'Seçenek grubu')).data() : null;
  await db.runTransaction(async (tx) => {
    if (before) {
      tx.update(ref, { ...data, updatedAt: FieldValue.serverTimestamp() });
    } else {
      tx.set(ref, {
        ...data,
        order: Date.now(),
        deleted: false,
        createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp(),
      });
    }
    audit(tx, { action: before ? 'option_group_update' : 'option_group_create', actor: actor.uid,
      target: `optionGroups/${ref.id}`, after: { name: data.name, options: data.options.length } });
  });
  return { id: ref.id };
});

exports.deleteOptionGroup = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const ref = db.doc(`optionGroups/${requireString(request.data?.id, 'Seçenek grubu', { max: 128 })}`);
  const snap = await requireLive(ref, 'Seçenek grubu');
  const products = await liveProductsWhere('optionGroupIds', 'array-contains', ref.id);
  if (products.length) {
    throw new HttpsError('failed-precondition',
      `Bu grup ${products.length} üründe kullanılıyor (${products.slice(0, 3).map((p) => p.data().name).join(', ')}…). ` +
      'Önce ürünlerden kaldırın.');
  }
  await db.runTransaction(async (tx) => {
    tx.update(ref, { deleted: true, updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'option_group_delete', actor: actor.uid, target: `optionGroups/${ref.id}`,
      before: { name: snap.data().name } });
  });
  return { id: ref.id };
});

const ORDERABLE = ['categories', 'products', 'optionGroups', 'areas'];

exports.reorderMenu = onCall(async (request) => {
  await requireStaff(request, 'editMenu');
  const { kind, ids } = request.data || {};
  if (!ORDERABLE.includes(kind)) throw new HttpsError('invalid-argument', 'Geçersiz liste türü.');
  if (!Array.isArray(ids) || ids.length === 0 || ids.length > 400 || ids.some((x) => typeof x !== 'string' || !x)) {
    throw new HttpsError('invalid-argument', 'Sıralama listesi geçersiz.');
  }
  const refs = ids.map((x) => db.doc(`${kind}/${x}`));
  const snaps = await db.getAll(...refs);
  const batch = db.batch();
  snaps.forEach((snap, i) => {
    if (snap.exists) batch.update(snap.ref, { order: i, updatedAt: FieldValue.serverTimestamp() });
  });
  await batch.commit();
  return { count: snaps.filter((s) => s.exists).length };
});

// Toplu fiyat güncelleme. dryRun: true ise yalnızca önizleme döner, hiçbir şey yazılmaz.
// Seçenek fiyat farkları yalnızca yüzde kuralında ve pozitif farklarda güncellenir.
exports.bulkUpdatePrices = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const d = request.data || {};
  const rule = validated(validatePriceRule, d.rule);
  if (!Array.isArray(d.categoryIds) || d.categoryIds.length < 1 || d.categoryIds.length > 30 ||
      d.categoryIds.some((x) => typeof x !== 'string' || !x)) {
    throw new HttpsError('invalid-argument', 'En az bir kategori seçin (en fazla 30).');
  }
  const products = await liveProductsWhere('categoryId', 'in', d.categoryIds);
  const productChanges = products
    .map((p) => ({ id: p.id, name: p.data().name, before: p.data().price, after: applyPriceRule(p.data().price, rule) }))
    .filter((c) => c.after !== c.before)
    .sort((a, b) => a.name.localeCompare(b.name, 'tr'));

  const optionChanges = [];
  const groupUpdates = new Map();
  if (d.includeOptions === true && rule.mode === 'percent') {
    const groupIds = [...new Set(products.flatMap((p) => p.data().optionGroupIds || []))];
    const groups = groupIds.length ? await db.getAll(...groupIds.map((g) => db.doc(`optionGroups/${g}`))) : [];
    for (const g of groups) {
      if (!g.exists || g.data().deleted === true) continue;
      let changed = false;
      const options = (g.data().options || []).map((o) => {
        if (!(o.priceDelta > 0)) return o;
        const after = applyPriceRule(o.priceDelta, rule);
        if (after === o.priceDelta) return o;
        changed = true;
        optionChanges.push({ groupId: g.id, optionId: o.id, name: `${g.data().name} · ${o.name}`, before: o.priceDelta, after });
        return { ...o, priceDelta: after };
      });
      if (changed) groupUpdates.set(g.id, options);
    }
  }

  const result = { products: productChanges, options: optionChanges, rule };
  if (d.dryRun === true) return result;
  if (productChanges.length + groupUpdates.size === 0) return result;
  if (productChanges.length + groupUpdates.size > 450) {
    throw new HttpsError('resource-exhausted', 'Tek seferde en fazla 450 kayıt güncellenebilir; kategorileri bölün.');
  }

  const batch = db.batch();
  for (const c of productChanges) {
    batch.update(db.doc(`products/${c.id}`), { price: c.after, updatedAt: FieldValue.serverTimestamp() });
  }
  for (const [groupId, options] of groupUpdates) {
    batch.update(db.doc(`optionGroups/${groupId}`), { options, updatedAt: FieldValue.serverTimestamp() });
  }
  batch.set(db.collection('auditLogs').doc(), {
    action: 'bulk_price_update',
    actor: actor.uid,
    target: 'products',
    rule,
    categoryIds: d.categoryIds,
    count: productChanges.length,
    changes: productChanges.slice(0, 200),
    optionChanges: optionChanges.slice(0, 100),
    at: FieldValue.serverTimestamp(),
  });
  await batch.commit();
  return result;
});

// Terminaldeki eski (yerel) menünün buluta tek seferlik aktarımı. Bulutta menü varsa reddedilir.
// payload: { categories: [{ localId, name, color, station, stampEligible }],
//            products:   [{ localId, localCategoryId, name, price }] }
exports.importMenu = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const d = request.data || {};
  if (!Array.isArray(d.categories) || !Array.isArray(d.products) || d.categories.length < 1 ||
      d.categories.length > 50 || d.products.length > 400) {
    throw new HttpsError('invalid-argument', 'Aktarılacak menü geçersiz.');
  }
  const existing = await db.collection('categories').where('deleted', '==', false).limit(1).get();
  if (!existing.empty) {
    throw new HttpsError('failed-precondition', 'Bulutta zaten bir menü var; aktarım yalnızca boş menüye yapılabilir.');
  }
  const batch = db.batch();
  const categoryIds = {};
  const productIds = {};
  const now = Date.now();
  d.categories.forEach((c, i) => {
    const data = validated(validateCategory, c);
    const ref = db.collection('categories').doc();
    categoryIds[String(c.localId)] = ref.id;
    batch.set(ref, { ...data, order: i, deleted: false, createdAt: FieldValue.serverTimestamp(),
      updatedAt: FieldValue.serverTimestamp() });
  });
  d.products.forEach((p, i) => {
    const categoryId = categoryIds[String(p.localCategoryId)];
    if (!categoryId) throw new HttpsError('invalid-argument', `"${p.name}" ürününün kategorisi listede yok.`);
    const data = validated(validateProduct, { categoryId, name: p.name, price: p.price });
    const ref = db.collection('products').doc();
    productIds[String(p.localId)] = ref.id;
    batch.set(ref, { ...data, soldOut: false, deleted: false, order: now + i,
      createdAt: FieldValue.serverTimestamp(), updatedAt: FieldValue.serverTimestamp() });
  });
  batch.set(db.collection('auditLogs').doc(), {
    action: 'menu_import', actor: actor.uid, target: 'menu',
    after: { categories: d.categories.length, products: d.products.length },
    at: FieldValue.serverTimestamp(),
  });
  await batch.commit();
  return { categories: categoryIds, products: productIds };
});

// ---------------------------------------------------------------------------
// Salon ve masa planı (3. ekran)
//
// Bir bölgenin planı (masalar + dekor) tek seferde kaydedilir. layoutVersion ile
// eşzamanlı düzenleme yakalanır: istemci okuduğu sürümü gönderir, arada başkası
// kaydetmişse istek reddedilir. Masaların anlık durumu (dolu/boş) burada tutulmaz;
// siparişle birlikte 4. ekranda gelir. Her masanın tahmin edilemeyen bir qrToken'ı vardır.
// ---------------------------------------------------------------------------

exports.saveArea = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const data = validated(validateArea, request.data);
  const id = request.data?.id;
  const ref = id ? db.doc(`areas/${requireString(id, 'Bölge', { max: 128 })}`) : db.collection('areas').doc();
  const before = id ? (await requireLive(ref, 'Bölge')).data() : null;
  await db.runTransaction(async (tx) => {
    if (before) {
      tx.update(ref, { ...data, updatedAt: FieldValue.serverTimestamp() });
    } else {
      tx.set(ref, { ...data, fixtures: [], layoutVersion: 0, order: Date.now(), deleted: false,
        createdAt: FieldValue.serverTimestamp(), updatedAt: FieldValue.serverTimestamp() });
    }
    audit(tx, { action: before ? 'area_update' : 'area_create', actor: actor.uid, target: `areas/${ref.id}`,
      before: before ? { name: before.name } : null, after: data });
  });
  return { id: ref.id };
});

// Bölgeyi ve içindeki masaları siler (geri alınabilir: deleted bayrağı). Açık adisyon
// kontrolü terminal tarafında yapılır; adisyonlar 4. ekrana kadar yereldedir.
exports.deleteArea = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const ref = db.doc(`areas/${requireString(request.data?.id, 'Bölge', { max: 128 })}`);
  const snap = await requireLive(ref, 'Bölge');
  const tables = await db.collection('tables').where('areaId', '==', ref.id).get();
  const batch = db.batch();
  batch.update(ref, { deleted: true, updatedAt: FieldValue.serverTimestamp() });
  tables.docs.filter((t) => t.data().deleted !== true).forEach((t) =>
    batch.update(t.ref, { deleted: true, updatedAt: FieldValue.serverTimestamp() }));
  batch.set(db.collection('auditLogs').doc(), { action: 'area_delete', actor: actor.uid, target: `areas/${ref.id}`,
    before: { name: snap.data().name, tables: tables.size }, at: FieldValue.serverTimestamp() });
  await batch.commit();
  return { id: ref.id };
});

// tables: gönderilen masalar eklenir/güncellenir; removedTableIds açıkça silinir.
// Listede adı geçmeyen masalara dokunulmaz: terminalin önbelleği eksik olsa bile
// görmediği bir masa yanlışlıkla silinmez.
exports.saveFloorPlan = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const d = request.data || {};
  const plan = validated(validateFloorPlan, d);
  const areaRef = db.doc(`areas/${requireString(d.areaId, 'Bölge', { max: 128 })}`);
  if (!Number.isInteger(d.expectedVersion)) throw new HttpsError('invalid-argument', 'Plan sürümü eksik.');
  const removedIds = d.removedTableIds ?? [];
  if (!Array.isArray(removedIds) || removedIds.length > 100 || removedIds.some((x) => typeof x !== 'string' || !x)) {
    throw new HttpsError('invalid-argument', 'Silinecek masa listesi geçersiz.');
  }

  return db.runTransaction(async (tx) => {
    const area = await tx.get(areaRef);
    if (!area.exists || area.data().deleted === true) throw new HttpsError('not-found', 'Bölge bulunamadı.');
    const version = area.data().layoutVersion || 0;
    if (version !== d.expectedVersion) {
      throw new HttpsError('aborted', 'Bu bölgenin planı siz düzenlerken başka biri tarafından kaydedildi. ' +
        'Değişikliklerinizi kaydetmeden önce planı yenileyin.');
    }
    const existing = await tx.get(db.collection('tables').where('areaId', '==', areaRef.id));
    const live = new Map(existing.docs.filter((t) => t.data().deleted !== true).map((t) => [t.id, t]));
    const updatedIds = new Set(plan.tables.filter((t) => t.id).map((t) => t.id));
    for (const id of [...updatedIds, ...removedIds]) {
      if (!live.has(id)) throw new HttpsError('not-found', 'Planda bu bölgeye ait olmayan bir masa var.');
    }
    if (removedIds.some((id) => updatedIds.has(id))) {
      throw new HttpsError('invalid-argument', 'Bir masa aynı anda hem güncellenip hem silinemez.');
    }
    // Ad benzersizliği: dokunulmayan masalar + gönderilenler birlikte
    const names = new Map();
    const untouched = [...live.values()].filter((t) => !updatedIds.has(t.id) && !removedIds.includes(t.id));
    for (const name of [...untouched.map((t) => t.data().name), ...plan.tables.map((t) => t.name)]) {
      const key = String(name).toLocaleLowerCase('tr');
      if (names.has(key)) throw new HttpsError('invalid-argument', `"${name}" adı bu bölgede birden fazla masada kullanılmış.`);
      names.set(key, true);
    }

    const now = FieldValue.serverTimestamp();
    const created = {};
    for (const t of plan.tables) {
      const { id, tempId, ...fields } = t;
      if (id) {
        tx.update(db.doc(`tables/${id}`), { ...fields, updatedAt: now });
      } else {
        const ref = db.collection('tables').doc();
        created[tempId] = ref.id;
        tx.set(ref, { ...fields, areaId: areaRef.id, qrToken: newQrToken(), deleted: false,
          createdAt: now, updatedAt: now });
      }
    }
    for (const id of removedIds) tx.update(db.doc(`tables/${id}`), { deleted: true, updatedAt: now });
    tx.update(areaRef, { fixtures: plan.fixtures, layoutVersion: version + 1, updatedAt: now });
    audit(tx, { action: 'floor_plan_save', actor: actor.uid, target: `areas/${areaRef.id}`,
      after: { tables: plan.tables.length, created: Object.keys(created).length, removed: removedIds.length,
        fixtures: plan.fixtures.length, layoutVersion: version + 1 } });
    return { layoutVersion: version + 1, created, removed: removedIds };
  });
});

exports.rotateTableQr = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const ids = request.data?.tableIds;
  if (!Array.isArray(ids) || ids.length < 1 || ids.length > 100 || ids.some((x) => typeof x !== 'string' || !x)) {
    throw new HttpsError('invalid-argument', 'Masa listesi geçersiz.');
  }
  const snaps = await db.getAll(...ids.map((x) => db.doc(`tables/${x}`)));
  if (snaps.some((s) => !s.exists || s.data().deleted === true)) throw new HttpsError('not-found', 'Masa bulunamadı.');
  const batch = db.batch();
  snaps.forEach((s) => batch.update(s.ref, { qrToken: newQrToken(), updatedAt: FieldValue.serverTimestamp() }));
  batch.set(db.collection('auditLogs').doc(), { action: 'table_qr_rotate', actor: actor.uid, target: 'tables',
    after: { tableIds: ids }, at: FieldValue.serverTimestamp() });
  await batch.commit();
  return { count: ids.length };
});

// Eski NexPOS bölge/masa düzeninin buluta tek seferlik aktarımı (bulutta plan yokken).
// payload: { areas: [{ localId, name, tables: [{ localId, name }] }] }
exports.importFloor = onCall(async (request) => {
  const actor = await requireStaff(request, 'editMenu');
  const areas = request.data?.areas;
  if (!Array.isArray(areas) || areas.length < 1 || areas.length > 20) {
    throw new HttpsError('invalid-argument', 'Aktarılacak bölgeler geçersiz.');
  }
  const existing = await db.collection('areas').where('deleted', '==', false).limit(1).get();
  if (!existing.empty) {
    throw new HttpsError('failed-precondition', 'Bulutta zaten bir salon planı var; aktarım yalnızca boş plana yapılabilir.');
  }
  const batch = db.batch();
  const areaIds = {};
  const tableIds = {};
  const now = FieldValue.serverTimestamp();
  let count = 0;
  areas.forEach((a, i) => {
    const { name } = validated(validateArea, a);
    const tables = Array.isArray(a.tables) ? a.tables.slice(0, 60) : [];
    const plan = validated(validateFloorPlan, {
      tables: tables.map((t, j) => ({ tempId: String(t.localId), name: t.name, shape: 'square', capacity: 4,
        ...gridLayout(j) })),
      fixtures: [],
    });
    const areaRef = db.collection('areas').doc();
    areaIds[String(a.localId)] = areaRef.id;
    batch.set(areaRef, { name, fixtures: [], layoutVersion: 0, order: i, deleted: false, createdAt: now, updatedAt: now });
    for (const t of plan.tables) {
      const { id, tempId, ...fields } = t;
      const ref = db.collection('tables').doc();
      tableIds[tempId] = ref.id;
      batch.set(ref, { ...fields, areaId: areaRef.id, qrToken: newQrToken(), deleted: false, createdAt: now, updatedAt: now });
      count += 1;
    }
  });
  if (count + areas.length > 450) throw new HttpsError('resource-exhausted', 'Aktarılacak masa sayısı çok fazla.');
  batch.set(db.collection('auditLogs').doc(), { action: 'floor_import', actor: actor.uid, target: 'areas',
    after: { areas: areas.length, tables: count }, at: FieldValue.serverTimestamp() });
  await batch.commit();
  return { areas: areaIds, tables: tableIds };
});

// Genel ayarlar: kafe adı (QR etiketi, ekranlar), QR adresi, otomatik kilit süresi.
exports.saveGeneralSettings = onCall(async (request) => {
  const actor = await requireStaff(request, 'settings');
  const data = validated(validateGeneralSettings, request.data);
  const ref = db.doc('settings/general');
  await db.runTransaction(async (tx) => {
    const before = await tx.get(ref);
    tx.set(ref, { ...data, updatedBy: actor.uid, updatedAt: FieldValue.serverTimestamp() }, { merge: true });
    audit(tx, { action: 'settings_change', actor: actor.uid, target: 'settings/general',
      before: before.exists ? before.data() : null, after: data });
  });
  return data;
});
