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

const { randomInt } = require('crypto');
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
  validateModules,
  normalizeModules,
  validateIngredient,
  validateRecipe,
  validateRecipeEffect,
  validateStockMove,
  STOCK_MOVE_TYPES,
  UNITS,
  validateSupplier,
  validatePurchaseOrder,
  validateReceipt,
  validateSupplierPayment,
  weightedUnitCost,
  expectedCash,
  validateShiftCell,
  validateCustomer,
} = require('./src/lib');
const shiftCalc = require('./src/shifts');
const { OrderError, applyOrderOp, mergeOrders, tableStatusFor, stampCount, computeTotals } = require('./src/orders');
const loyaltyCalc = require('./src/loyalty');
const campaignCalc = require('./src/campaigns');
const { businessDayOf, contribution, refundContribution, merge } = require('./src/stats');

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

// Kasa terminali (NexPOS). Mutfak ekranı (kds) bu fonksiyonları çağıramaz; allowKds ile
// yalnızca ortak olanlara (canlılık sinyali) izin verilir.
async function requireTerminal(request, { allowKds = false } = {}) {
  requireAuth(request);
  const { terminal, terminalId, kds } = request.auth.token;
  if (terminal !== true || typeof terminalId !== 'string' || (kds === true && !allowKds)) {
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
  const { ref } = await requireTerminal(request, { allowKds: true });
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

// ---------------------------------------------------------------------------
// Sipariş işlemleri (4. ekran)
//
// Terminal her işlemi önce kendinde uygular, sonra kuyruktan buraya gönderir. Sunucu aynı
// mantığı (src/orders.js) bulut kaydı üzerinde tekrar çalıştırır: toplamları kendisi hesaplar,
// yetkiyi denetler, masa durumunu, mutfak/bar fişlerini ve ödeme kayıtlarını yazar.
// ---------------------------------------------------------------------------

// İşlem → gereken yetki. Onaylayan (payload.approvedBy) varsa yetki onun üzerinden aranır.
function requiredPermission(op, payload, order) {
  if (op === 'voidItem') return 'voidItem';
  if (op === 'compItem') return 'comp';
  if (op === 'refundPayment') return 'refund';
  if (op === 'setDiscount') return payload.discount === null ? 'openTable' : 'discount';
  if (op === 'cancelOrder') {
    const sent = (order?.items || []).some((l) => l.status === 'active' && l.state === 'sent');
    return sent ? 'voidItem' : 'openTable';
  }
  // Kampanyalar kendiliğinden uygulanır; adisyondan kampanya kaldırmak iskonto yetkisi ister
  if (op === 'applyCampaigns') {
    const before = new Set(order?.campaignsExcluded || []);
    return (Array.isArray(payload.excluded) ? payload.excluded : []).some((x) => !before.has(x)) ? 'discount' : 'openTable';
  }
  return 'openTable';
}

// Müşteri kaydı; telefonla çift kayıt birleştirildiyse (aliasOf) asıl kayıt döner. Silinmişse null.
async function readCustomer(tx, id) {
  if (typeof id !== 'string' || !id) return null;
  let snap = await tx.get(db.doc(`customers/${id}`));
  if (snap.exists && snap.data().aliasOf) snap = await tx.get(db.doc(`customers/${snap.data().aliasOf}`));
  if (!snap.exists || snap.data().deleted === true) return null;
  return { ref: snap.ref, data: snap.data() };
}

const TABLE_STATUS_FIELDS = (order, status) => (status === 'empty'
  ? { status: 'empty', currentOrderId: null, openedAt: null, waiterId: null }
  : { status, currentOrderId: order.id, openedAt: order.openedAt, waiterId: order.waiterId });

// Adisyon kapanınca damga, kart dolunca ödül, doğum günü ödülü, kullanılan ödüller; iadede damga geri alınır.
function applyLoyalty(tx, { op, p, order, next, loyalty, at, terminalId, staffId, now }) {
  const { ref, data: c, settings: S } = loyalty;
  const L = loyaltyCalc;
  if (op === 'takePayment' && next.status === 'paid') {
    const day = next.businessDay;
    const earned = stampCount(next);
    const st = L.applyStamps(c, earned, S);
    const update = { stamps: st.stamps, lifetimeStamps: st.lifetimeStamps, tier: st.tier,
      totalSpent: (c.totalSpent || 0) + next.total, visitCount: (c.visitCount || 0) + 1, lastVisitAt: at, updatedAt: now };
    const rewards = [];
    for (let i = 1; i <= st.newRewards; i += 1) rewards.push([`${next.id}-r${i}`, 'free_drink']);
    const year = day.slice(0, 4);
    if (S.birthdayReward && L.isBirthdayWeek(c.birthDate, day) && c.lastBirthdayYear !== year) {
      rewards.push([`${next.id}-bday`, 'birthday']);
      update.lastBirthdayYear = year;
    }
    tx.update(ref, update);
    for (const [id, type] of rewards) {
      tx.set(db.doc(`rewards/${id}`), { customerId: ref.id, type, status: 'active', sourceOrderId: next.id,
        createdAt: at, expiresAt: L.addDays(day, S.rewardValidDays), updatedAt: now });
    }
    tx.set(db.doc(`loyaltyEvents/${next.id}-stamp`), { customerId: ref.id, type: 'stamp', amount: earned,
      rewards: rewards.length, orderId: next.id, orderNo: next.no, total: next.total, at, terminalId, by: staffId, createdAt: now });
    (next.rewards || []).forEach((r, i) => {
      const snap = loyalty.rewardSnaps[i];
      if (snap && snap.exists && L.rewardUsable(snap.data(), ref.id, day)) {
        tx.update(snap.ref, { status: 'used', usedOrderId: next.id, usedAt: at, updatedAt: now });
      } else {
        // Para alınmış; ödül geçersizse adisyon değişmez, kayda düşer
        audit(tx, { action: 'reward_conflict', actor: staffId, target: `rewards/${r.rewardId}`, detail: next.id, terminalId,
          clientAt: parseClientTime(at) });
      }
    });
  }
  if (op === 'refundPayment') {
    const t = computeTotals(next);
    const n = L.refundRevoke(order.stamps || 0, t.paid, t.refunded, order.stampsRevoked || 0);
    const refundAmount = p.amount || 0;
    const update = { totalSpent: Math.max((c.totalSpent || 0) - refundAmount, 0), updatedAt: now };
    if (n) {
      const st = L.revokeStamps(c, n, S);
      Object.assign(update, { stamps: st.stamps, lifetimeStamps: st.lifetimeStamps, tier: st.tier });
      next.stampsRevoked = (order.stampsRevoked || 0) + n;
      tx.set(db.doc(`loyaltyEvents/${p.refundId}-revoke`), { customerId: ref.id, type: 'revoke', amount: -n,
        orderId: next.id, orderNo: next.no, at, terminalId, by: staffId, createdAt: now });
    }
    tx.update(ref, update);
  }
}

function orderHandler(op) {
  return async (tx, { op: envelope, terminalId, staff, matrix }) => {
    if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
    const p = envelope.payload;
    if (typeof p.orderId !== 'string' || !p.orderId) return { status: 'rejected', error: 'Adisyon belirtilmedi.' };
    const at = envelope.createdAt;
    const ctx = { staffId: envelope.staffId, at };

    // ---- Okumalar (transaction kuralı: tüm okumalar yazmalardan önce)
    const orderRef = db.doc(`orders/${p.orderId}`);
    const orderSnap = await tx.get(orderRef);
    const order = orderSnap.exists ? orderSnap.data() : null;
    let source = null;
    let sourceRef = null;
    if (op === 'mergeOrders') {
      sourceRef = db.doc(`orders/${p.sourceOrderId}`);
      const s = await tx.get(sourceRef);
      source = s.exists ? s.data() : null;
    }
    const approverId = typeof p.approvedBy === 'string' && p.approvedBy ? p.approvedBy : envelope.staffId;
    let approver = staff;
    if (approverId !== envelope.staffId) {
      const a = await tx.get(db.doc(`staff/${approverId}`));
      approver = a.exists && a.data().active === true ? a.data() : null;
    }
    const tableIds = new Set();
    if (op === 'openOrder' && p.tableId) tableIds.add(p.tableId);
    if (order?.tableId) tableIds.add(order.tableId);
    if (op === 'moveOrder' && p.toTableId) tableIds.add(p.toTableId);
    if (source?.tableId) tableIds.add(source.tableId);
    const tableSnaps = new Map();
    for (const id of tableIds) tableSnaps.set(id, await tx.get(db.doc(`tables/${id}`)));
    // Kasa oturumu: nakit tahsilat/iade hangi oturuma yazıldı, zorunlu modül açık mı?
    let modules = null;
    let session = null;
    if (op === 'takePayment' || op === 'refundPayment') {
      modules = normalizeModules((await tx.get(db.doc('settings/modules'))).data());
      if (typeof p.cashSessionId === 'string' && p.cashSessionId) {
        const cs = await tx.get(db.doc(`cashSessions/${p.cashSessionId}`));
        session = cs.exists ? cs.data() : null;
        if (!session || session.terminalId !== terminalId || session.status !== 'open') {
          return { status: 'rejected', error: 'Kasa oturumu açık değil.' };
        }
      } else if (p.method === 'cash' && modules.cashSession.required) {
        return { status: 'rejected', error: 'Kasa açılmadan nakit işlem yapılamaz.' };
      }
    }
    // Mutfak/bar fişleri: iptal edilen ürün fişte "İPTAL" görünsün, taşınan masanın adı güncellensin
    const ticketRefs = new Map();
    if (order && ['voidItem', 'cancelOrder'].includes(op)) {
      const lines = order.items.filter((l) => l.status === 'active' && l.state === 'sent'
        && (op === 'cancelOrder' || l.lineId === p.lineId) && l.ticketId);
      for (const id of new Set(lines.map((l) => l.ticketId))) ticketRefs.set(id, await tx.get(db.doc(`kitchenTickets/${id}`)));
    }
    if (order && ['moveOrder', 'mergeOrders'].includes(op)) {
      const ids = [order.id, ...(source ? [source.id] : [])];
      const q = await tx.get(db.collection('kitchenTickets').where('orderId', 'in', ids));
      for (const d of q.docs) if (d.data().status !== 'served') ticketRefs.set(d.id, d);
    }
    // Günlük özet (dailyStats): kapanan/iptal edilen adisyonun ve iadenin günü
    let statsRef = null;
    let statsSnap = null;
    if (['takePayment', 'cancelOrder'].includes(op) && order) statsRef = db.doc(`dailyStats/${order.businessDay}`);
    if (op === 'refundPayment' && typeof at === 'string') statsRef = db.doc(`dailyStats/${businessDayOf(at)}`);
    if (statsRef) statsSnap = await tx.get(statsRef);
    let products = [];
    if (op === 'addItems' && Array.isArray(p.items)) {
      const ids = [...new Set(p.items.map((i) => i?.productId).filter((x) => typeof x === 'string' && x))];
      products = ids.length ? await tx.getAll(...ids.map((x) => db.doc(`products/${x}`))) : [];
    }

    // Sadakat (10. ekran): kapanışta damga ve ödül, iadede damga geri alma
    let loyalty = null;
    if (order?.customer && ((op === 'takePayment' && order.status === 'open') || op === 'refundPayment')) {
      loyalty = await readCustomer(tx, order.customer.id);
      if (loyalty) {
        loyalty.settings = loyaltyCalc.normalizeLoyalty((await tx.get(db.doc('settings/loyalty'))).data());
        loyalty.rewardSnaps = [];
        if (op === 'takePayment') {
          for (const r of order.rewards || []) loyalty.rewardSnaps.push(await tx.get(db.doc(`rewards/${r.rewardId}`)));
        }
      }
    }

    // ---- Yetki
    const permission = requiredPermission(op, p, order);
    if (!approver || !hasPermission(matrix, approver.role, permission, approver.permissions)) {
      return { status: 'rejected', error: `Bu işlem için yetki yok (${permission}).` };
    }
    // Masa kuralları
    if (op === 'openOrder' && p.tableId) {
      const t = tableSnaps.get(p.tableId);
      if (!t.exists || t.data().deleted === true) return { status: 'rejected', error: 'Masa bulunamadı.' };
      const busy = t.data().currentOrderId;
      if (busy && busy !== p.orderId && ['occupied', 'bill_requested'].includes(t.data().status)) {
        return { status: 'rejected', error: 'Masada açık bir adisyon var.' };
      }
    }
    if (op === 'moveOrder') {
      const t = tableSnaps.get(p.toTableId);
      if (!t || !t.exists || t.data().deleted === true) return { status: 'rejected', error: 'Hedef masa bulunamadı.' };
      if (['occupied', 'bill_requested'].includes(t.data().status)) {
        return { status: 'rejected', error: 'Hedef masa dolu; birleştirmeyi kullanın.' };
      }
    }

    // ---- Uygula
    let next;
    let nextSource = null;
    try {
      if (op === 'mergeOrders') [next, nextSource] = mergeOrders(order, source, ctx);
      else next = applyOrderOp(order, op, p, ctx);
    } catch (e) {
      if (e instanceof OrderError) return { status: 'rejected', error: e.message };
      throw e;
    }

    // ---- Yazmalar
    const now = FieldValue.serverTimestamp();
    if (loyalty) applyLoyalty(tx, { op, p, order, next, loyalty, at, terminalId, staffId: envelope.staffId, now });
    const stamp = { terminalId, updatedAt: now };
    const finalize = (o) => ({ ...o, ...stamp, stamps: o.status === 'paid' ? stampCount(o) : null });
    tx.set(orderRef, finalize(next));
    if (nextSource) tx.set(sourceRef, finalize(nextSource));

    // Masa durumları
    const statusByTable = new Map();
    if (order?.tableId && order.tableId !== next.tableId) statusByTable.set(order.tableId, ['empty', next]);
    if (next.tableId) statusByTable.set(next.tableId, [tableStatusFor(next), next]);
    if (nextSource?.tableId) statusByTable.set(nextSource.tableId, ['empty', nextSource]);
    if (op === 'refundPayment') statusByTable.clear(); // iade masayı etkilemez
    for (const [tableId, [st, o]] of statusByTable) {
      const snap = tableSnaps.get(tableId);
      if (!snap || !snap.exists) continue;
      // Başka bir adisyonun masasını boşaltma
      if (st === 'empty' && snap.data().currentOrderId && snap.data().currentOrderId !== o.id) continue;
      tx.update(snap.ref, { ...TABLE_STATUS_FIELDS(o, st), updatedAt: now });
    }

    // Mutfak / bar fişleri
    if (op === 'sendItems') {
      const byTicket = new Map();
      for (const line of next.items.filter((l) => p.lineIds.includes(l.lineId))) {
        if (!byTicket.has(line.ticketId)) byTicket.set(line.ticketId, { station: line.station, lines: [] });
        byTicket.get(line.ticketId).lines.push({
          lineId: line.lineId, name: line.name, qty: line.qty, note: line.note || '',
          options: (line.options || []).map((x) => x.name),
        });
      }
      for (const [ticketId, t] of byTicket) {
        tx.set(db.doc(`kitchenTickets/${ticketId}`), {
          orderId: next.id, orderNo: next.no, tableName: next.tableName || '', type: next.type,
          station: t.station, lines: t.lines, doneLineIds: [], status: 'new', createdAt: at, terminalId, updatedAt: now,
        });
      }
    }

    for (const [, snap] of ticketRefs) {
      if (!snap.exists) continue;
      if (op === 'voidItem' || op === 'cancelOrder') {
        const voided = new Set(next.items.filter((l) => l.status === 'void' || op === 'cancelOrder').map((l) => l.lineId));
        tx.update(snap.ref, { lines: snap.data().lines.map((l) => (voided.has(l.lineId) ? { ...l, voided: true } : l)),
          ...(op === 'cancelOrder' ? { cancelled: true } : {}), updatedAt: now });
      } else {
        tx.update(snap.ref, { tableName: next.tableName || '', updatedAt: now });
      }
    }

    // Ödeme kaydı (kasa ve raporlar için ayrı koleksiyon)
    if (op === 'takePayment') {
      const pay = next.payments[next.payments.length - 1];
      tx.set(db.doc(`payments/${pay.paymentId}`), {
        ...pay, orderId: next.id, orderNo: next.no, businessDay: next.businessDay, terminalId, createdAt: now,
      });
    }

    let delta = null;
    if (op === 'takePayment' && next.status === 'paid') delta = contribution(next);
    if (op === 'cancelOrder') delta = contribution(next);
    if (op === 'refundPayment') delta = refundContribution(next.refunds[next.refunds.length - 1]);
    if (delta && statsRef) {
      const current = statsSnap.exists ? statsSnap.data() : {};
      delete current.updatedAt;
      tx.set(statsRef, { ...merge(current, delta), day: statsRef.id, updatedAt: now });
    }

    if (op === 'refundPayment') {
      const r = next.refunds[next.refunds.length - 1];
      tx.set(db.doc(`refunds/${r.refundId}`), {
        ...r, orderId: next.id, orderNo: next.no, businessDay: next.businessDay, terminalId, createdAt: now,
      });
    }

    // Fiyat farkı: terminal fiyatı geçerli kalır, kayda düşer
    if (op === 'addItems') {
      const current = new Map(products.filter((x) => x.exists).map((x) => [x.id, x.data().price]));
      const mismatches = p.items
        .filter((i) => i?.productId && current.has(i.productId) && current.get(i.productId) !== i.unitPrice)
        .map((i) => ({ productId: i.productId, name: i.name, terminal: i.unitPrice, menu: current.get(i.productId) }));
      if (mismatches.length) {
        audit(tx, { action: 'price_mismatch', actor: envelope.staffId, target: `orders/${next.id}`, after: mismatches,
          terminalId, clientAt: parseClientTime(at) });
      }
    }

    const auditable = { voidItem: 'order_void', compItem: 'order_comp', setDiscount: 'order_discount',
      cancelOrder: 'order_cancel', mergeOrders: 'order_merge', moveOrder: 'order_move', refundPayment: 'order_refund' };
    if (auditable[op]) {
      audit(tx, { action: auditable[op], actor: envelope.staffId, approvedBy: approverId, target: `orders/${next.id}`,
        detail: p.lineId || p.toTableId || p.sourceOrderId || (op === 'refundPayment' ? `${p.amount} ${p.method}` : null), reason: p.reason || null,
        after: op === 'setDiscount' ? next.discount : null, terminalId, clientAt: parseClientTime(at) });
    }
    return { status: 'ok' };
  };
}

const ORDER_OPS = ['openOrder', 'addItems', 'updateItem', 'removeItem', 'sendItems', 'voidItem', 'compItem',
  'setDiscount', 'requestBill', 'moveOrder', 'takePayment', 'cancelOrder', 'mergeOrders', 'splitLine',
  'refundPayment', 'setCustomer', 'useReward', 'removeReward', 'applyCampaigns'];
for (const name of ORDER_OPS) OP_HANDLERS[name] = orderHandler(name);

// Mutfak/bar fişinin durumu: new → preparing → ready → served
OP_HANDLERS.updateTicket = async (tx, { op, staff }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  const p = op.payload;
  if (!['new', 'preparing', 'ready', 'served'].includes(p.status)) return { status: 'rejected', error: 'Fiş durumu geçersiz.' };
  const ref = db.doc(`kitchenTickets/${p.ticketId}`);
  const snap = await tx.get(ref);
  if (!snap.exists) return { status: 'rejected', error: 'Fiş bulunamadı.' };
  tx.update(ref, { status: p.status, [`${p.status}At`]: op.createdAt, updatedAt: FieldValue.serverTimestamp() });
  return { status: 'ok' };
};

// Stok hareketi (8. ekran): satışta reçeteden düşme, iptalde iade, sayım, düzeltme, zayi.
// Terminal reçeteyi kendisi hesaplar (internetsiz çalışır); sunucu yetkiyi denetler, malzemelerin
// stoğunu artırır/azaltır ve hareketi kaydeder. Aynı hareket iki kez gelirse processedOps korur.
OP_HANDLERS.stockMove = async (tx, { op, terminalId, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  let m;
  try {
    m = validateStockMove(op.payload);
  } catch (e) {
    if (e instanceof MenuError) return { status: 'rejected', error: e.message };
    throw e;
  }
  const approverId = typeof op.payload.approvedBy === 'string' && op.payload.approvedBy ? op.payload.approvedBy : op.staffId;
  let approver = staff;
  if (approverId !== op.staffId) {
    const a = await tx.get(db.doc(`staff/${approverId}`));
    approver = a.exists && a.data().active === true ? a.data() : null;
  }
  const refs = m.lines.map((l) => db.doc(`ingredients/${l.ingredientId}`));
  const snaps = refs.length ? await tx.getAll(...refs) : [];
  const permission = STOCK_MOVE_TYPES[m.type];
  if (!approver || !hasPermission(matrix, approver.role, permission, approver.permissions)) {
    return { status: 'rejected', error: `Bu işlem için yetki yok (${permission}).` };
  }
  const now = FieldValue.serverTimestamp();
  // Silinmiş ya da bilinmeyen malzeme satırı atlanır (reçete eski olabilir); hareket yine kaydedilir.
  const applied = [];
  snaps.forEach((snap, i) => {
    if (!snap.exists) return;
    tx.update(snap.ref, { stock: FieldValue.increment(m.lines[i].qty), updatedAt: now });
    applied.push(m.lines[i]);
  });
  tx.set(db.doc(`stockMovements/${m.movementId}`), {
    ...m, applied, by: op.staffId, approvedBy: approverId, terminalId, at: op.createdAt, createdAt: now,
  });
  return { status: 'ok' };
};

// Teslim alma (8b): stok artar, birim maliyet ağırlıklı ortalamayla güncellenir, sipariş satırlarına
// teslim edilen miktar yazılır, ödenmediyse tedarikçinin borç bakiyesi artar. İnternetsiz yapılabilir.
OP_HANDLERS.receivePurchase = async (tx, { op, terminalId, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  let r;
  try {
    r = validateReceipt(op.payload);
  } catch (e) {
    if (e instanceof MenuError) return { status: 'rejected', error: e.message };
    throw e;
  }
  const approverId = typeof op.payload.approvedBy === 'string' && op.payload.approvedBy ? op.payload.approvedBy : op.staffId;
  let approver = staff;
  if (approverId !== op.staffId) {
    const a = await tx.get(db.doc(`staff/${approverId}`));
    approver = a.exists && a.data().active === true ? a.data() : null;
  }
  const supplierRef = db.doc(`suppliers/${r.supplierId}`);
  const poRef = r.purchaseOrderId ? db.doc(`purchaseOrders/${r.purchaseOrderId}`) : null;
  const [supplier, po, ...ings] = await Promise.all([tx.get(supplierRef), poRef ? tx.get(poRef) : null,
    ...r.lines.map((l) => tx.get(db.doc(`ingredients/${l.ingredientId}`)))]);
  if (!approver || !hasPermission(matrix, approver.role, 'stock', approver.permissions)) {
    return { status: 'rejected', error: 'Bu işlem için yetki yok (stock).' };
  }
  if (!supplier.exists) return { status: 'rejected', error: 'Tedarikçi bulunamadı.' };
  if (po && (!po.exists || po.data().status === 'cancelled')) return { status: 'rejected', error: 'Sipariş bulunamadı ya da iptal.' };
  const now = FieldValue.serverTimestamp();
  // Aynı malzeme iki satırda olabilir: sırayla uygulanır
  const state = new Map();
  ings.forEach((snap) => { if (snap.exists) state.set(snap.id, { ...snap.data(), ref: snap.ref }); });
  const applied = [];
  for (const l of r.lines) {
    const ing = state.get(l.ingredientId);
    if (!ing) continue;
    const factor = (UNITS[ing.unit] || UNITS.adet).factor;
    ing.unitCost = weightedUnitCost(ing.stock || 0, ing.unitCost || 0, l.qty, l.amount, factor);
    ing.stock = (ing.stock || 0) + l.qty;
    applied.push({ ingredientId: l.ingredientId, qty: l.qty });
  }
  for (const [, ing] of state) tx.update(ing.ref, { stock: ing.stock, unitCost: ing.unitCost, updatedAt: now });
  if (po) {
    const lines = po.data().lines.map((pl) => {
      const got = r.lines.filter((l) => l.ingredientId === pl.ingredientId).reduce((s, l) => s + l.qty, 0);
      return { ...pl, received: (pl.received || 0) + got };
    });
    const done = lines.every((pl) => pl.received >= pl.qty);
    tx.update(poRef, { lines, status: done ? 'received' : 'partial', receivedAt: op.createdAt, updatedAt: now });
  }
  if (r.payment.status === 'unpaid') tx.update(supplierRef, { balance: FieldValue.increment(r.total), updatedAt: now });
  tx.set(db.doc(`purchaseReceipts/${r.receiptId}`), { ...r, by: op.staffId, approvedBy: approverId, terminalId,
    at: op.createdAt, createdAt: now });
  tx.set(db.doc(`stockMovements/${r.receiptId}`), { movementId: r.receiptId, type: 'purchase', lines: applied, applied,
    purchaseOrderId: r.purchaseOrderId, reason: '', by: op.staffId, approvedBy: approverId, terminalId,
    at: op.createdAt, createdAt: now });
  return { status: 'ok' };
};

// Tedarikçiye ödeme (borç bakiyesinden düşer)
OP_HANDLERS.supplierPayment = async (tx, { op, terminalId, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  let p;
  try {
    p = validateSupplierPayment(op.payload);
  } catch (e) {
    if (e instanceof MenuError) return { status: 'rejected', error: e.message };
    throw e;
  }
  const approverId = typeof op.payload.approvedBy === 'string' && op.payload.approvedBy ? op.payload.approvedBy : op.staffId;
  let approver = staff;
  if (approverId !== op.staffId) {
    const a = await tx.get(db.doc(`staff/${approverId}`));
    approver = a.exists && a.data().active === true ? a.data() : null;
  }
  const ref = db.doc(`suppliers/${p.supplierId}`);
  const snap = await tx.get(ref);
  if (!approver || !hasPermission(matrix, approver.role, 'stock', approver.permissions)) {
    return { status: 'rejected', error: 'Bu işlem için yetki yok (stock).' };
  }
  if (!snap.exists) return { status: 'rejected', error: 'Tedarikçi bulunamadı.' };
  tx.update(ref, { balance: FieldValue.increment(-p.amount), updatedAt: FieldValue.serverTimestamp() });
  tx.set(db.doc(`supplierPayments/${p.paymentId}`), { ...p, by: op.staffId, approvedBy: approverId, terminalId,
    at: op.createdAt, createdAt: FieldValue.serverTimestamp() });
  return { status: 'ok' };
};

// ---------------------------------------------------------------------------
// Mesai (9. ekran): kişi kendi PIN'iyle başlar/biter/molaya çıkar (internetsiz, kuyruktan).
// payload: { entryId, action: 'in'|'out'|'breakStart'|'breakEnd', at, auto? }
// Geç kalma sunucuda plan ve toleransla hesaplanır (src/shifts.js; kasadaki shifts_logic.py ile aynı).
// ---------------------------------------------------------------------------

const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

OP_HANDLERS.timeClock = async (tx, { op, terminalId, staff }) => {
  if (!staff || staff.active !== true) return { status: 'rejected', error: 'Personel bulunamadı.' };
  const p = op.payload;
  if (!['in', 'out', 'breakStart', 'breakEnd'].includes(p.action)) return { status: 'rejected', error: 'Mesai işlemi geçersiz.' };
  if (typeof p.entryId !== 'string' || !/^[\w-]{1,64}$/.test(p.entryId)) return { status: 'rejected', error: 'Kayıt kimliği geçersiz.' };
  if (typeof p.at !== 'string' || !ISO_RE.test(p.at)) return { status: 'rejected', error: 'Saat geçersiz.' };
  const ref = db.doc(`timeEntries/${p.entryId}`);
  const snap = await tx.get(ref);
  const now = FieldValue.serverTimestamp();
  if (p.action === 'in') {
    if (snap.exists) return { status: 'rejected', error: 'Bu mesai zaten başlamış.' };
    const day = shiftCalc.businessDayOf(p.at);
    const [plan, mods] = await Promise.all([tx.get(db.doc(`shiftPlans/${op.staffId}_${day}`)), tx.get(db.doc('settings/modules'))]);
    const tolerance = normalizeModules(mods.data()).staff.lateToleranceMinutes;
    tx.set(ref, { staffId: op.staffId, businessDay: day, clockIn: p.at, clockOut: null, breaks: [],
      late: shiftCalc.lateMinutes(plan.exists && !plan.data().deleted ? plan.data() : null, p.at, tolerance), flags: [],
      terminalId, createdAt: now, updatedAt: now });
    return { status: 'ok' };
  }
  if (!snap.exists) return { status: 'rejected', error: 'Mesai kaydı bulunamadı.' };
  const e = snap.data();
  if (e.staffId !== op.staffId) return { status: 'rejected', error: 'Başkasının mesaisi değiştirilemez.' };
  if (e.clockOut) return { status: 'rejected', error: 'Mesai bitmiş.' };
  const breaks = [...(e.breaks || [])];
  const open = breaks.length > 0 && !breaks[breaks.length - 1].end;
  if (p.action === 'breakStart') {
    if (open) return { status: 'rejected', error: 'Zaten molada.' };
    breaks.push({ start: p.at, end: null });
    tx.update(ref, { breaks, updatedAt: now });
  } else if (p.action === 'breakEnd') {
    if (!open) return { status: 'rejected', error: 'Molada değil.' };
    breaks[breaks.length - 1] = { ...breaks[breaks.length - 1], end: p.at };
    tx.update(ref, { breaks, updatedAt: now });
  } else {
    if (open) breaks[breaks.length - 1] = { ...breaks[breaks.length - 1], end: p.at };
    const flags = p.auto === true ? [...(e.flags || []), 'forgotClockOut'] : e.flags || [];
    tx.update(ref, { clockOut: p.at, breaks, flags, updatedAt: now });
  }
  return { status: 'ok' };
};

// Mesai düzeltme (shifts yetkisi; gerekçe zorunlu). Eksik kaydı (gelmiş ama başlatmamış) da açabilir.
// payload: { entryId, staffId, clockIn, clockOut, breaks, reason, approvedBy? }
OP_HANDLERS.timeEdit = async (tx, { op, terminalId, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  const p = op.payload;
  const approverId = typeof p.approvedBy === 'string' && p.approvedBy ? p.approvedBy : op.staffId;
  let approver = staff;
  if (approverId !== op.staffId) {
    const a = await tx.get(db.doc(`staff/${approverId}`));
    approver = a.exists && a.data().active === true ? a.data() : null;
  }
  const ref = typeof p.entryId === 'string' && /^[\w-]{1,64}$/.test(p.entryId) ? db.doc(`timeEntries/${p.entryId}`) : null;
  const snap = ref ? await tx.get(ref) : null;
  if (!approver || !hasPermission(matrix, approver.role, 'shifts', approver.permissions)) {
    return { status: 'rejected', error: 'Bu işlem için yetki yok (shifts).' };
  }
  if (!ref || typeof p.staffId !== 'string') return { status: 'rejected', error: 'Kayıt geçersiz.' };
  const reason = typeof p.reason === 'string' ? p.reason.trim().slice(0, 120) : '';
  if (!reason) return { status: 'rejected', error: 'Gerekçe zorunludur.' };
  if (!ISO_RE.test(p.clockIn || '') || (p.clockOut && !ISO_RE.test(p.clockOut))) return { status: 'rejected', error: 'Saat geçersiz.' };
  if (p.clockOut && Date.parse(`${p.clockOut.slice(0, 19)}Z`) <= Date.parse(`${p.clockIn.slice(0, 19)}Z`)) {
    return { status: 'rejected', error: 'Çıkış girişten sonra olmalıdır.' };
  }
  const breaks = (Array.isArray(p.breaks) ? p.breaks : []).filter((b) => ISO_RE.test(b?.start || '')).slice(0, 10)
    .map((b) => ({ start: b.start, end: ISO_RE.test(b.end || '') ? b.end : null }));
  const before = snap.exists ? snap.data() : null;
  if (before && before.staffId !== p.staffId) return { status: 'rejected', error: 'Kayıt başka personelin.' };
  const day = shiftCalc.businessDayOf(p.clockIn);
  const [plan, mods] = await Promise.all([tx.get(db.doc(`shiftPlans/${p.staffId}_${day}`)), tx.get(db.doc('settings/modules'))]);
  const tolerance = normalizeModules(mods.data()).staff.lateToleranceMinutes;
  const flags = [...new Set([...(before?.flags || []), 'edited'])];
  tx.set(ref, { staffId: p.staffId, businessDay: day, clockIn: p.clockIn, clockOut: p.clockOut || null, breaks,
    late: shiftCalc.lateMinutes(plan.exists && !plan.data().deleted ? plan.data() : null, p.clockIn, tolerance),
    flags, resolved: true, editedBy: approverId, reason, terminalId,
    createdAt: before?.createdAt || FieldValue.serverTimestamp(), updatedAt: FieldValue.serverTimestamp() });
  audit(tx, { action: 'time_edit', actor: op.staffId, approvedBy: approverId, target: ref.path, reason,
    before: before ? { clockIn: before.clockIn, clockOut: before.clockOut } : null,
    after: { clockIn: p.clockIn, clockOut: p.clockOut || null }, terminalId, clientAt: parseClientTime(op.createdAt) });
  return { status: 'ok' };
};

// Kasada yeni üye (10. ekran, internetsiz). Telefon başka üyedeyse bu kayıt ona yönlendirilir (aliasOf);
// adisyondaki müşteri kimliği bozulmaz, damgalar asıl kayda işlenir.
// payload: { customerId, name, phone, birthDate?, marketingConsent }
OP_HANDLERS.customerCreate = async (tx, { op, terminalId, staff }) => {
  if (!staff || staff.active !== true) return { status: 'rejected', error: 'Personel bulunamadı.' };
  const p = op.payload;
  if (typeof p.customerId !== 'string' || !/^[\w-]{1,64}$/.test(p.customerId)) return { status: 'rejected', error: 'Müşteri kimliği geçersiz.' };
  let data;
  try {
    data = validateCustomer(p);
  } catch (e) {
    if (e instanceof MenuError) return { status: 'rejected', error: e.message };
    throw e;
  }
  const ref = db.doc(`customers/${p.customerId}`);
  const phoneRef = db.doc(`customerPhones/${data.phone}`);
  const [snap, phone] = [await tx.get(ref), await tx.get(phoneRef)];
  if (snap.exists) return { status: 'rejected', error: 'Bu müşteri zaten kayıtlı.' };
  const now = FieldValue.serverTimestamp();
  if (phone.exists && phone.data().customerId !== p.customerId) {
    tx.set(ref, { aliasOf: phone.data().customerId, deleted: true, createdAt: now, updatedAt: now });
    return { status: 'ok' };
  }
  tx.set(ref, { ...data, consentAt: data.marketingConsent ? op.createdAt : null, stamps: 0, lifetimeStamps: 0,
    tier: 'bronze', totalSpent: 0, visitCount: 0, lastVisitAt: null, source: 'pos', createdBy: op.staffId, terminalId,
    deleted: false, createdAt: now, updatedAt: now });
  tx.set(phoneRef, { customerId: p.customerId });
  return { status: 'ok' };
};

// Elle damga düzeltme / ödül verme (loyalty yetkisi, gerekçe zorunlu).
// payload: { adjustId, customerId, stamps (−100..100), grantReward?, reason, approvedBy? }
OP_HANDLERS.loyaltyAdjust = async (tx, { op, terminalId, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  const p = op.payload;
  const approverId = typeof p.approvedBy === 'string' && p.approvedBy ? p.approvedBy : op.staffId;
  let approver = staff;
  if (approverId !== op.staffId) {
    const a = await tx.get(db.doc(`staff/${approverId}`));
    approver = a.exists && a.data().active === true ? a.data() : null;
  }
  const customer = await readCustomer(tx, p.customerId);
  const settings = loyaltyCalc.normalizeLoyalty((await tx.get(db.doc('settings/loyalty'))).data());
  if (!approver || !hasPermission(matrix, approver.role, 'loyalty', approver.permissions)) {
    return { status: 'rejected', error: 'Bu işlem için yetki yok (loyalty).' };
  }
  if (!customer) return { status: 'rejected', error: 'Müşteri bulunamadı.' };
  if (typeof p.adjustId !== 'string' || !/^[\w-]{1,64}$/.test(p.adjustId)) return { status: 'rejected', error: 'Kayıt kimliği geçersiz.' };
  const stamps = p.stamps ?? 0;
  if (!Number.isInteger(stamps) || stamps < -100 || stamps > 100) return { status: 'rejected', error: 'Damga −100 ile 100 arası olmalıdır.' };
  if (!stamps && p.grantReward !== true) return { status: 'rejected', error: 'Değişiklik yok.' };
  const reason = typeof p.reason === 'string' ? p.reason.trim().slice(0, 120) : '';
  if (!reason) return { status: 'rejected', error: 'Gerekçe zorunludur.' };
  const c = customer.data;
  const st = stamps >= 0 ? loyaltyCalc.applyStamps(c, stamps, settings) : loyaltyCalc.revokeStamps(c, -stamps, settings);
  const now = FieldValue.serverTimestamp();
  const day = businessDayOf(op.createdAt);
  const n = st.newRewards + (p.grantReward === true ? 1 : 0);
  tx.update(customer.ref, { stamps: st.stamps, lifetimeStamps: st.lifetimeStamps, tier: st.tier, updatedAt: now });
  for (let i = 1; i <= n; i += 1) {
    tx.set(db.doc(`rewards/${p.adjustId}-r${i}`), { customerId: customer.ref.id, type: 'manual', status: 'active',
      createdAt: op.createdAt, expiresAt: loyaltyCalc.addDays(day, settings.rewardValidDays), updatedAt: now });
  }
  tx.set(db.doc(`loyaltyEvents/${p.adjustId}`), { customerId: customer.ref.id, type: 'adjust', amount: stamps,
    rewards: n, reason, by: op.staffId, approvedBy: approverId, at: op.createdAt, terminalId, createdAt: now });
  audit(tx, { action: 'loyalty_adjust', actor: op.staffId, approvedBy: approverId, target: customer.ref.path, reason,
    after: { stamps, grantReward: p.grantReward === true }, terminalId, clientAt: parseClientTime(op.createdAt) });
  return { status: 'ok' };
};

// Boş masayı elle rezerve işaretleme
OP_HANDLERS.setTableReserved = async (tx, { op, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  if (!hasPermission(matrix, staff.role, 'openTable', staff.permissions)) return { status: 'rejected', error: 'Yetki yok.' };
  const p = op.payload;
  const ref = db.doc(`tables/${p.tableId}`);
  const snap = await tx.get(ref);
  if (!snap.exists || snap.data().deleted === true) return { status: 'rejected', error: 'Masa bulunamadı.' };
  const current = snap.data().status || 'empty';
  if (!['empty', 'reserved'].includes(current)) return { status: 'rejected', error: 'Dolu masa rezerve edilemez.' };
  tx.update(ref, { status: p.reserved === true ? 'reserved' : 'empty', updatedAt: FieldValue.serverTimestamp() });
  return { status: 'ok' };
};

// ---------------------------------------------------------------------------
// Kasa oturumu (6. ekran): açılış, hareket, kapanış (Z). Terminal internetsiz de açıp kapatır;
// işlemler kuyruktan sırayla gelir. Beklenen nakdi sunucu kendi kayıtlarından tekrar hesaplar.
// ---------------------------------------------------------------------------

const MAX_MONEY = 10_000_000;
const isMoney = (v, min = 0) => Number.isInteger(v) && v >= min && v <= MAX_MONEY;
const shortText = (v, max = 120) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : '');

// İşlemi yapan ya da onaylayan personelin 'cash' yetkisi
async function cashApprover(tx, envelope, staff, matrix) {
  const id = typeof envelope.payload.approvedBy === 'string' && envelope.payload.approvedBy
    ? envelope.payload.approvedBy : envelope.staffId;
  let approver = staff;
  if (id !== envelope.staffId) {
    const a = await tx.get(db.doc(`staff/${id}`));
    approver = a.exists && a.data().active === true ? a.data() : null;
  }
  return approver && hasPermission(matrix, approver.role, 'cash', approver.permissions) ? id : null;
}

async function openSession(tx, p, terminalId) {
  if (typeof p.cashSessionId !== 'string' || !p.cashSessionId) return [null, null];
  const ref = db.doc(`cashSessions/${p.cashSessionId}`);
  const snap = await tx.get(ref);
  const s = snap.exists ? snap.data() : null;
  return [ref, s && s.terminalId === terminalId && s.status === 'open' ? s : null];
}

// payload: { cashSessionId, businessDay, openingCash, approvedBy? }
OP_HANDLERS.openCashSession = async (tx, { op, terminalId, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  const p = op.payload;
  const approvedBy = await cashApprover(tx, op, staff, matrix);
  if (typeof p.cashSessionId !== 'string' || !/^[\w-]{1,64}$/.test(p.cashSessionId)) {
    return { status: 'rejected', error: 'Kasa oturumu kimliği geçersiz.' };
  }
  const ref = db.doc(`cashSessions/${p.cashSessionId}`);
  const [snap, open] = await Promise.all([
    tx.get(ref),
    tx.get(db.collection('cashSessions').where('terminalId', '==', terminalId).where('status', '==', 'open')),
  ]);
  if (!approvedBy) return { status: 'rejected', error: 'Bu işlem için yetki yok (cash).' };
  if (snap.exists) return { status: 'rejected', error: 'Bu kasa oturumu zaten açılmış.' };
  if (!open.empty) return { status: 'rejected', error: 'Bu terminalde açık bir kasa oturumu var.' };
  if (!isMoney(p.openingCash)) return { status: 'rejected', error: 'Açılış nakdi geçersiz.' };
  tx.set(ref, {
    terminalId, status: 'open', businessDay: shortText(p.businessDay, 10), openingCash: p.openingCash,
    openedBy: op.staffId, approvedBy, openedAt: op.createdAt, movements: [],
    closedBy: null, closedAt: null, countedCash: null, expectedCash: null, difference: null, report: null,
    updatedAt: FieldValue.serverTimestamp(),
  });
  audit(tx, { action: 'cash_open', actor: op.staffId, approvedBy, target: `cashSessions/${p.cashSessionId}`,
    after: { openingCash: p.openingCash }, terminalId, clientAt: parseClientTime(op.createdAt) });
  return { status: 'ok' };
};

// payload: { cashSessionId, movementId, type: in|out, amount, reason, expense?, approvedBy? }
OP_HANDLERS.cashMovement = async (tx, { op, terminalId, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  const p = op.payload;
  const approvedBy = await cashApprover(tx, op, staff, matrix);
  const [ref, session] = await openSession(tx, p, terminalId);
  if (!approvedBy) return { status: 'rejected', error: 'Bu işlem için yetki yok (cash).' };
  if (!session) return { status: 'rejected', error: 'Kasa oturumu açık değil.' };
  if (!['in', 'out'].includes(p.type)) return { status: 'rejected', error: 'Hareket türü geçersiz.' };
  if (!isMoney(p.amount, 1)) return { status: 'rejected', error: 'Tutar geçersiz.' };
  const reason = shortText(p.reason);
  if (!reason) return { status: 'rejected', error: 'Gerekçe zorunludur.' };
  if (typeof p.movementId !== 'string' || !p.movementId) return { status: 'rejected', error: 'Hareket kimliği eksik.' };
  if (session.movements.some((m) => m.movementId === p.movementId)) return { status: 'rejected', error: 'Bu hareket zaten kaydedilmiş.' };
  if (session.movements.length >= 500) return { status: 'rejected', error: 'Kasa hareketi sınırı aşıldı.' };
  const movement = { movementId: p.movementId, type: p.type, amount: p.amount, reason,
    expense: p.type === 'out' && p.expense === true, by: op.staffId, approvedBy, at: op.createdAt };
  tx.update(ref, { movements: [...session.movements, movement], updatedAt: FieldValue.serverTimestamp() });
  audit(tx, { action: 'cash_movement', actor: op.staffId, approvedBy, target: `cashSessions/${p.cashSessionId}`,
    after: movement, reason, terminalId, clientAt: parseClientTime(op.createdAt) });
  return { status: 'ok' };
};

// payload: { cashSessionId, countedCash, expectedCash, reason?, report?, approvedBy? }
OP_HANDLERS.closeCashSession = async (tx, { op, terminalId, staff, matrix }) => {
  if (!staff) return { status: 'rejected', error: 'Personel bulunamadı.' };
  const p = op.payload;
  const approvedBy = await cashApprover(tx, op, staff, matrix);
  const [ref, session] = await openSession(tx, p, terminalId);
  const [pays, refs, modSnap] = session ? await Promise.all([
    tx.get(db.collection('payments').where('cashSessionId', '==', p.cashSessionId)),
    tx.get(db.collection('refunds').where('cashSessionId', '==', p.cashSessionId)),
    tx.get(db.doc('settings/modules')),
  ]) : [];
  if (!approvedBy) return { status: 'rejected', error: 'Bu işlem için yetki yok (cash).' };
  if (!session) return { status: 'rejected', error: 'Kasa oturumu açık değil.' };
  if (!isMoney(p.countedCash) || !isMoney(p.expectedCash)) return { status: 'rejected', error: 'Sayılan nakit geçersiz.' };
  const modules = normalizeModules(modSnap.data());
  const reason = shortText(p.reason, 200);
  // Gerekçe kuralı terminalin gördüğü farka göre uygulanır (terminal bunu zaten zorunlu tutar).
  if (Math.abs(p.countedCash - p.expectedCash) > modules.cashSession.diffReasonThreshold && !reason) {
    return { status: 'rejected', error: 'Kasa farkı için gerekçe zorunludur.' };
  }
  const expected = expectedCash(session, pays.docs.map((d) => d.data()), refs.docs.map((d) => d.data()));
  let report = null;
  if (p.report && typeof p.report === 'object' && JSON.stringify(p.report).length <= 20_000) report = p.report;
  tx.update(ref, {
    status: 'closed', closedBy: op.staffId, approvedBy, closedAt: op.createdAt,
    countedCash: p.countedCash, expectedCash: expected, terminalExpectedCash: p.expectedCash,
    difference: p.countedCash - expected, differenceReason: reason || null, report,
    updatedAt: FieldValue.serverTimestamp(),
  });
  audit(tx, { action: 'cash_close', actor: op.staffId, approvedBy, target: `cashSessions/${p.cashSessionId}`,
    after: { countedCash: p.countedCash, expectedCash: expected, difference: p.countedCash - expected },
    reason: reason || null, terminalId, clientAt: parseClientTime(op.createdAt) });
  if (expected !== p.expectedCash) {
    audit(tx, { action: 'cash_expected_mismatch', actor: op.staffId, target: `cashSessions/${p.cashSessionId}`,
      after: { server: expected, terminal: p.expectedCash }, terminalId, clientAt: parseClientTime(op.createdAt) });
  }
  return { status: 'ok' };
};

// ---------------------------------------------------------------------------
// Mutfak / bar ekranı (5. ekran, KDS)
//
// Tablet, panelde üretilen 6 haneli kodla eşlenir ve ayrı bir cihaz hesabı alır
// (claims: terminal, terminalId, kds, station). Bu hesap yalnızca fişleri ve modül/genel
// ayarları okuyabilir; personel, PIN ve sipariş verisine erişemez. Fiş durumunu
// updateKitchenTicket ile değiştirir. Terminaller sayfasından iptal edilebilir.
// ---------------------------------------------------------------------------

const KDS_STATIONS = ['bar', 'kitchen', 'all'];
const PAIRING_MINUTES = 10;
const PAIRING_MAX_FAILURES = 30; // 10 dakikada; kod tahminine karşı

exports.createKdsPairingCode = onCall(async (request) => {
  const actor = await requireStaff(request, 'settings');
  const name = request.data?.name ? requireString(request.data.name, 'Ekran adı', { max: 40 }) : 'Mutfak ekranı';
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const code = String(randomInt(0, 1_000_000)).padStart(6, '0');
    const ref = db.doc(`kdsPairings/${code}`);
    const created = await db.runTransaction(async (tx) => {
      const snap = await tx.get(ref);
      if (snap.exists && snap.data().used !== true && snap.data().expiresAt.toMillis() > Date.now()) return false;
      tx.set(ref, { name, used: false, createdBy: actor.uid, createdAt: FieldValue.serverTimestamp(),
        expiresAt: Timestamp.fromMillis(Date.now() + PAIRING_MINUTES * 60_000) });
      return true;
    });
    if (created) return { code, expiresInMinutes: PAIRING_MINUTES };
  }
  throw new HttpsError('unavailable', 'Kod üretilemedi, tekrar deneyin.');
});

// Tabletten giriş yapmadan çağrılır: { code, station, name? } → customToken
exports.pairKds = onCall(async (request) => {
  const code = request.data?.code;
  const station = request.data?.station;
  if (typeof code !== 'string' || !/^\d{6}$/.test(code)) throw new HttpsError('invalid-argument', 'Kod 6 haneli olmalıdır.');
  if (!KDS_STATIONS.includes(station)) throw new HttpsError('invalid-argument', 'İstasyon geçersiz.');
  const guardRef = db.doc('pairingGuard/kds');
  const pairingRef = db.doc(`kdsPairings/${code}`);
  const ref = db.collection('terminals').doc();
  const outcome = await db.runTransaction(async (tx) => {
    const [guard, pairing] = await Promise.all([tx.get(guardRef), tx.get(pairingRef)]);
    const now = Date.now();
    const g = guard.exists && now - guard.data().windowStart < PAIRING_MINUTES * 60_000
      ? guard.data() : { windowStart: now, failures: 0 };
    if (g.failures >= PAIRING_MAX_FAILURES) return { error: 'resource-exhausted' };
    const p = pairing.exists ? pairing.data() : null;
    if (!p || p.used === true || p.expiresAt.toMillis() <= now) {
      tx.set(guardRef, { windowStart: g.windowStart, failures: g.failures + 1 });
      return { error: 'not-found' };
    }
    const name = typeof request.data?.name === 'string' && request.data.name.trim()
      ? request.data.name.trim().slice(0, 40) : p.name;
    tx.update(pairingRef, { used: true, usedAt: FieldValue.serverTimestamp(), terminalId: ref.id });
    tx.set(ref, { name, kind: 'kds', station, letter: null, deviceUid: TERMINAL_UID_PREFIX + ref.id, revoked: false,
      pendingOps: 0, appVersion: null, lastSeenAt: FieldValue.serverTimestamp(), createdBy: p.createdBy,
      createdAt: FieldValue.serverTimestamp(), updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'kds_pair', actor: p.createdBy, target: ref.id, after: { name, station } });
    return { name };
  });
  if (outcome.error === 'resource-exhausted') {
    throw new HttpsError('resource-exhausted', 'Çok fazla hatalı deneme. Birkaç dakika sonra tekrar deneyin.');
  }
  if (outcome.error) throw new HttpsError('not-found', 'Kod geçersiz ya da süresi dolmuş. Panelden yeni kod alın.');
  const uid = TERMINAL_UID_PREFIX + ref.id;
  const claims = { terminal: true, terminalId: ref.id, kds: true, station };
  await getAuth().createUser({ uid, displayName: `Mutfak ekranı · ${outcome.name}` });
  await getAuth().setCustomUserClaims(uid, claims);
  const customToken = await getAuth().createCustomToken(uid, claims);
  return { terminalId: ref.id, name: outcome.name, station, customToken };
});

// Mutfak ekranı fiş durumu: Başla (preparing), Hazır (ready), Geri al (ready → preparing),
// hazırlanan satırların işaretlenmesi (doneLineIds). Teslim (served) kasadan yapılır.
exports.updateKitchenTicket = onCall(async (request) => {
  requireAuth(request);
  const { kds, terminalId, station } = request.auth.token;
  if (kds !== true || typeof terminalId !== 'string') {
    throw new HttpsError('permission-denied', 'Bu işlem yalnızca mutfak ekranından yapılabilir.');
  }
  const term = await db.doc(`terminals/${terminalId}`).get();
  if (!term.exists || term.data().revoked === true) throw new HttpsError('permission-denied', 'Bu ekran iptal edilmiş.');
  const ticketId = requireString(request.data?.ticketId, 'Fiş', { max: 64 });
  const status = request.data?.status;
  const done = request.data?.doneLineIds;
  if (status !== undefined && !['new', 'preparing', 'ready'].includes(status)) {
    throw new HttpsError('invalid-argument', 'Fiş durumu geçersiz.');
  }
  if (done !== undefined && (!Array.isArray(done) || done.length > 50 || done.some((x) => typeof x !== 'string'))) {
    throw new HttpsError('invalid-argument', 'Satır listesi geçersiz.');
  }
  const ref = db.doc(`kitchenTickets/${ticketId}`);
  return db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (!snap.exists) throw new HttpsError('not-found', 'Fiş bulunamadı.');
    const t = snap.data();
    if (station !== 'all' && t.station !== station) throw new HttpsError('permission-denied', 'Bu fiş başka istasyonun.');
    if (t.status === 'served') throw new HttpsError('failed-precondition', 'Fiş teslim edilmiş.');
    const update = { updatedAt: FieldValue.serverTimestamp(), updatedByKds: terminalId };
    if (status !== undefined && status !== t.status) {
      update.status = status;
      update[`${status}At`] = new Date().toISOString();
    }
    if (done !== undefined) {
      const ids = new Set(t.lines.map((l) => l.lineId));
      update.doneLineIds = [...new Set(done)].filter((x) => ids.has(x));
    }
    tx.update(ref, update);
    return { status: update.status || t.status };
  });
});

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

// ---------------------------------------------------------------------------
// Stok: malzemeler (8. ekran). Stok miktarı burada değiştirilmez; yalnızca hareketlerle değişir.
// ---------------------------------------------------------------------------

exports.saveIngredient = onCall(async (request) => {
  const actor = await requireStaff(request, 'stock');
  const data = validated(validateIngredient, request.data);
  const id = request.data?.id;
  const ref = id ? db.doc(`ingredients/${requireString(id, 'Malzeme', { max: 128 })}`) : db.collection('ingredients').doc();
  const before = id ? (await requireLive(ref, 'Malzeme')).data() : null;
  await db.runTransaction(async (tx) => {
    if (before) tx.update(ref, { ...data, updatedAt: FieldValue.serverTimestamp() });
    else {
      tx.set(ref, { ...data, stock: 0, deleted: false, createdAt: FieldValue.serverTimestamp(),
        updatedAt: FieldValue.serverTimestamp() });
    }
    audit(tx, { action: before ? 'ingredient_update' : 'ingredient_create', actor: actor.uid,
      target: `ingredients/${ref.id}`, before: before ? { unitCost: before.unitCost } : null,
      after: { name: data.name, unitCost: data.unitCost } });
  });
  return { id: ref.id };
});

exports.deleteIngredient = onCall(async (request) => {
  const actor = await requireStaff(request, 'stock');
  const id = requireString(request.data?.id, 'Malzeme', { max: 128 });
  const ref = db.doc(`ingredients/${id}`);
  await requireLive(ref, 'Malzeme');
  const products = await db.collection('products').where('deleted', '==', false).get();
  const using = products.docs.filter((d) => (d.data().recipe || []).some((r) => r.ingredientId === id))
    .map((d) => d.data().name);
  if (using.length) {
    throw new HttpsError('failed-precondition', `Bu malzeme şu ürünlerin reçetesinde: ${using.slice(0, 5).join(', ')}.`);
  }
  await db.runTransaction(async (tx) => {
    tx.update(ref, { deleted: true, updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'ingredient_delete', actor: actor.uid, target: `ingredients/${id}` });
  });
  return { deleted: true };
});

// Vardiya planı (9. ekran): hücreler toplu kaydedilir; belge kimliği personel_tarih.
exports.saveShiftPlans = onCall(async (request) => {
  const actor = await requireStaff(request, 'shifts');
  const cells = request.data?.cells;
  if (!Array.isArray(cells) || cells.length < 1 || cells.length > 300) throw new HttpsError('invalid-argument', 'Hücre yok.');
  const clean = cells.map((c) => validated(validateShiftCell, c));
  const batch = db.batch();
  for (const c of clean) {
    const ref = db.doc(`shiftPlans/${c.staffId}_${c.date}`);
    if (c.clear) batch.set(ref, { staffId: c.staffId, date: c.date, deleted: true, updatedAt: FieldValue.serverTimestamp() });
    else batch.set(ref, { ...c, deleted: false, published: false, updatedBy: actor.uid, updatedAt: FieldValue.serverTimestamp() });
  }
  batch.set(db.collection('auditLogs').doc(), { action: 'shift_plan_save', actor: actor.uid, target: 'shiftPlans',
    after: { cells: clean.length }, at: FieldValue.serverTimestamp() });
  await batch.commit();
  return { saved: clean.length };
});

// Haftayı yayınla: haftanın bütün hücreleri personele görünür olur
exports.publishShiftWeek = onCall(async (request) => {
  const actor = await requireStaff(request, 'shifts');
  const start = request.data?.weekStart;
  if (typeof start !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(start)) throw new HttpsError('invalid-argument', 'Hafta geçersiz.');
  const end = new Date(Date.parse(`${start}T00:00:00Z`) + 6 * 86400_000).toISOString().slice(0, 10);
  const snap = await db.collection('shiftPlans').where('date', '>=', start).where('date', '<=', end).get();
  const batch = db.batch();
  snap.docs.forEach((d) => batch.update(d.ref, { published: true, updatedAt: FieldValue.serverTimestamp() }));
  batch.set(db.collection('auditLogs').doc(), { action: 'shift_publish', actor: actor.uid, target: `shiftPlans/${start}`,
    at: FieldValue.serverTimestamp() });
  await batch.commit();
  return { published: snap.size };
});

// Saatlik ücret: yalnızca Yönetici yazar ve okur (terminal önbelleğine inmez).
exports.saveWages = onCall(async (request) => {
  const actor = await requireStaff(request);
  if (actor.role !== 'owner') throw new HttpsError('permission-denied', 'Ücretleri yalnızca yönetici değiştirebilir.');
  const wages = request.data?.wages;
  if (!wages || typeof wages !== 'object' || Object.keys(wages).length > 200) {
    throw new HttpsError('invalid-argument', 'Ücret listesi geçersiz.');
  }
  const batch = db.batch();
  for (const [staffId, rate] of Object.entries(wages)) {
    if (rate !== null && (!Number.isInteger(rate) || rate < 0 || rate > 10_000_000)) {
      throw new HttpsError('invalid-argument', 'Saatlik ücret kuruş cinsinden olmalıdır.');
    }
    batch.set(db.doc(`staffWages/${staffId}`), { hourlyRate: rate, updatedBy: actor.uid, updatedAt: FieldValue.serverTimestamp() });
  }
  batch.set(db.collection('auditLogs').doc(), { action: 'wages_change', actor: actor.uid, target: 'staffWages',
    after: { count: Object.keys(wages).length }, at: FieldValue.serverTimestamp() });
  await batch.commit();
  return { saved: Object.keys(wages).length };
});

// ---------------------------------------------------------------------------
// Müşteri ve sadakat (10. ekran)
// ---------------------------------------------------------------------------

// Firestore zaman damgalarını ISO metne çevirir (callable yanıtları için)
function plain(value) {
  if (value instanceof Timestamp) return value.toDate().toISOString();
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v)]));
  return value;
}

// Sadakat ayarları: yalnızca Yönetici
exports.saveLoyaltySettings = onCall(async (request) => {
  const actor = await requireStaff(request);
  if (actor.role !== 'owner') throw new HttpsError('permission-denied', 'Sadakat ayarlarını yalnızca yönetici değiştirebilir.');
  let data;
  try {
    data = loyaltyCalc.validateLoyaltySettings(request.data);
  } catch (e) {
    if (e instanceof loyaltyCalc.LoyaltyError) throw new HttpsError('invalid-argument', e.message);
    throw e;
  }
  await db.runTransaction(async (tx) => {
    tx.set(db.doc('settings/loyalty'), { ...data, updatedAt: FieldValue.serverTimestamp(), updatedBy: actor.uid });
    audit(tx, { action: 'loyalty_settings', actor: actor.uid, target: 'settings/loyalty', after: data });
  });
  return data;
});

// Müşteri ekle / düzenle (panel, internet). Telefon tekil tutulur.
exports.saveCustomer = onCall(async (request) => {
  const actor = await requireStaff(request, 'loyalty');
  const data = validated(validateCustomer, request.data);
  const id = request.data?.id;
  const ref = id ? db.doc(`customers/${requireString(id, 'Müşteri', { max: 64 })}`) : db.collection('customers').doc();
  await db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    const phoneSnap = await tx.get(db.doc(`customerPhones/${data.phone}`));
    if (id && (!snap.exists || snap.data().deleted === true)) throw new HttpsError('not-found', 'Müşteri bulunamadı.');
    if (phoneSnap.exists && phoneSnap.data().customerId !== ref.id) {
      throw new HttpsError('already-exists', 'Bu telefon numarası başka bir üyede kayıtlı.');
    }
    const before = snap.exists ? snap.data() : null;
    const now = FieldValue.serverTimestamp();
    if (before && before.phone !== data.phone) tx.delete(db.doc(`customerPhones/${before.phone}`));
    const consentAt = data.marketingConsent ? (before?.marketingConsent ? before.consentAt : new Date().toISOString()) : null;
    if (before) tx.update(ref, { ...data, consentAt, updatedAt: now });
    else {
      tx.set(ref, { ...data, consentAt, stamps: 0, lifetimeStamps: 0, tier: 'bronze', totalSpent: 0, visitCount: 0,
        lastVisitAt: null, source: 'panel', createdBy: actor.uid, deleted: false, createdAt: now, updatedAt: now });
    }
    tx.set(db.doc(`customerPhones/${data.phone}`), { customerId: ref.id });
    audit(tx, { action: before ? 'customer_update' : 'customer_create', actor: actor.uid, target: ref.path,
      before: before ? { name: before.name, phone: before.phone } : null, after: { name: data.name, phone: data.phone } });
  });
  return { id: ref.id };
});

// KVKK: kişisel bilgiler silinir (ad, telefon, doğum günü); geçmiş satışlar anonim kalır. Yalnızca Yönetici.
exports.deleteCustomer = onCall(async (request) => {
  const actor = await requireStaff(request);
  if (actor.role !== 'owner') throw new HttpsError('permission-denied', 'Müşteri kaydını yalnızca yönetici silebilir.');
  const ref = db.doc(`customers/${requireString(request.data?.id, 'Müşteri', { max: 64 })}`);
  const active = await db.collection('rewards').where('customerId', '==', ref.id).where('status', '==', 'active').get();
  await db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (!snap.exists || snap.data().deleted === true) throw new HttpsError('not-found', 'Müşteri bulunamadı.');
    const now = FieldValue.serverTimestamp();
    if (snap.data().phone) tx.delete(db.doc(`customerPhones/${snap.data().phone}`));
    tx.set(ref, { name: 'Silinmiş müşteri', phone: null, birthDate: null, marketingConsent: false, consentAt: null,
      stamps: 0, lifetimeStamps: snap.data().lifetimeStamps || 0, tier: snap.data().tier || 'bronze',
      totalSpent: snap.data().totalSpent || 0, visitCount: snap.data().visitCount || 0,
      deleted: true, deletedAt: now, createdAt: snap.data().createdAt || now, updatedAt: now });
    for (const r of active.docs) tx.update(r.ref, { status: 'cancelled', updatedAt: now });
    audit(tx, { action: 'customer_delete', actor: actor.uid, target: ref.path });
  });
  return { deleted: true };
});

// Müşterinin bütün kaydı (detay ekranı ve KVKK "verimi istiyorum" talebi)
exports.exportCustomer = onCall(async (request) => {
  await requireStaff(request, 'loyalty');
  const id = requireString(request.data?.id, 'Müşteri', { max: 64 });
  const snap = await db.doc(`customers/${id}`).get();
  if (!snap.exists) throw new HttpsError('not-found', 'Müşteri bulunamadı.');
  const [events, rewards, orders] = await Promise.all([
    db.collection('loyaltyEvents').where('customerId', '==', id).get(),
    db.collection('rewards').where('customerId', '==', id).get(),
    db.collection('orders').where('customer.id', '==', id).get(),
  ]);
  const byAt = (a, b) => String(b.at || b.createdAt || '').localeCompare(String(a.at || a.createdAt || ''));
  return plain({
    customer: { id, ...snap.data() },
    events: events.docs.map((d) => ({ id: d.id, ...d.data() })).sort(byAt),
    rewards: rewards.docs.map((d) => ({ id: d.id, ...d.data() })).sort(byAt),
    orders: orders.docs.map((d) => d.data()).filter((o) => o.status === 'paid')
      .map((o) => ({ id: o.id, no: o.no, businessDay: o.businessDay, closedAt: o.closedAt, total: o.total,
        items: o.items.filter((l) => l.status === 'active').map((l) => ({ name: l.name, qty: l.qty })) }))
      .sort((a, b) => String(b.closedAt).localeCompare(String(a.closedAt))),
  });
});

// Kasada uygulama QR'ı: tek kullanımlık, 60 sn geçerli token → müşteri. İnternet ister.
exports.resolveLoyaltyToken = onCall(async (request) => {
  await requireTerminal(request);
  const token = requireString(request.data?.token, 'QR', { max: 128 });
  const ref = db.doc(`loyaltyTokens/${token.replace(/[^\w-]/g, '')}`);
  return db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    const t = snap.exists ? snap.data() : null;
    const expires = t?.expiresAt instanceof Timestamp ? t.expiresAt.toMillis() : 0;
    if (!t || t.used === true || expires < Date.now()) throw new HttpsError('not-found', 'QR geçersiz ya da süresi dolmuş.');
    const customer = await readCustomer(tx, t.uid);
    if (!customer) throw new HttpsError('not-found', 'Müşteri bulunamadı.');
    tx.update(ref, { used: true, usedAt: FieldValue.serverTimestamp() });
    const c = customer.data;
    return { customerId: customer.ref.id, name: c.name, stamps: c.stamps || 0, tier: c.tier || 'bronze',
      phone: loyaltyCalc.maskPhone(c.phone) };
  });
});

// Kampanyalar (10. ekran): panelden (internet); kasa önbelleğe alır ve internetsiz uygular.
exports.saveCampaign = onCall(async (request) => {
  const actor = await requireStaff(request, 'campaigns');
  let data;
  try {
    data = campaignCalc.validateCampaign(request.data);
  } catch (e) {
    if (e instanceof campaignCalc.CampaignError) throw new HttpsError('invalid-argument', e.message);
    throw e;
  }
  const id = request.data?.id;
  const ref = id ? db.doc(`campaigns/${requireString(id, 'Kampanya', { max: 128 })}`) : db.collection('campaigns').doc();
  await db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (id && (!snap.exists || snap.data().deleted === true)) throw new HttpsError('not-found', 'Kampanya bulunamadı.');
    const now = FieldValue.serverTimestamp();
    tx.set(ref, { ...data, deleted: false, updatedBy: actor.uid, updatedAt: now,
      createdAt: snap.exists ? snap.data().createdAt : now });
    audit(tx, { action: id ? 'campaign_update' : 'campaign_create', actor: actor.uid, target: ref.path, after: data });
  });
  return { id: ref.id };
});

exports.deleteCampaign = onCall(async (request) => {
  const actor = await requireStaff(request, 'campaigns');
  const ref = db.doc(`campaigns/${requireString(request.data?.id, 'Kampanya', { max: 128 })}`);
  await db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (!snap.exists) throw new HttpsError('not-found', 'Kampanya bulunamadı.');
    tx.update(ref, { deleted: true, active: false, updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'campaign_delete', actor: actor.uid, target: ref.path });
  });
  return { deleted: true };
});

// Bildirim (10. ekran): yalnızca izin veren üyeler. Kitle ve erişim burada hesaplanır; gerçek gönderim
// müşteri uygulaması (11. ekran) yayınlanınca açılır (durum: waiting_app). Kişi başı günde en fazla 1 bildirim.
const SEGMENTS = ['all', 'inactive30', 'silver', 'gold', 'birthday'];
function inSegment(c, segment, day) {
  if (!c.marketingConsent || c.deleted === true || c.aliasOf) return false;
  if (segment === 'inactive30') return String(c.lastVisitAt || c.createdAt || '').slice(0, 10) < loyaltyCalc.addDays(day, -30);
  if (segment === 'silver') return ['silver', 'gold'].includes(c.tier);
  if (segment === 'gold') return c.tier === 'gold';
  if (segment === 'birthday') return loyaltyCalc.isBirthdayWeek(c.birthDate, day);
  return true;
}

exports.saveNotification = onCall(async (request) => {
  const actor = await requireStaff(request, 'campaigns');
  const d = request.data || {};
  const title = requireString(d.title, 'Başlık', { max: 60 });
  const body = requireString(d.body, 'Metin', { max: 200 });
  if (!SEGMENTS.includes(d.segment)) throw new HttpsError('invalid-argument', 'Kitle geçersiz.');
  const campaignId = typeof d.campaignId === 'string' && d.campaignId ? d.campaignId.slice(0, 128) : null;
  const day = typeof d.day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d.day) ? d.day : new Date().toISOString().slice(0, 10);
  const customers = await db.collection('customers').where('marketingConsent', '==', true).get();
  const reach = customers.docs.filter((x) => inSegment(x.data(), d.segment, day)).length;
  const ref = db.collection('notifications').doc();
  await db.runTransaction(async (tx) => {
    const now = FieldValue.serverTimestamp();
    tx.set(ref, { title, body, segment: d.segment, campaignId, reach, status: 'waiting_app', createdBy: actor.uid,
      createdAt: now, updatedAt: now });
    audit(tx, { action: 'notification_create', actor: actor.uid, target: ref.path, after: { segment: d.segment, reach } });
  });
  return { id: ref.id, reach };
});

// Tedarikçiler ve sipariş (8b). Teslim alma ve ödeme kuyruktan gelir (internetsiz).
exports.saveSupplier = onCall(async (request) => {
  const actor = await requireStaff(request, 'stock');
  const data = validated(validateSupplier, request.data);
  const id = request.data?.id;
  const ref = id ? db.doc(`suppliers/${requireString(id, 'Tedarikçi', { max: 128 })}`) : db.collection('suppliers').doc();
  if (id) await requireLive(ref, 'Tedarikçi');
  await db.runTransaction(async (tx) => {
    if (id) tx.update(ref, { ...data, updatedAt: FieldValue.serverTimestamp() });
    else tx.set(ref, { ...data, balance: 0, deleted: false, createdAt: FieldValue.serverTimestamp(), updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: id ? 'supplier_update' : 'supplier_create', actor: actor.uid, target: `suppliers/${ref.id}`,
      after: { name: data.name } });
  });
  return { id: ref.id };
});

exports.deleteSupplier = onCall(async (request) => {
  const actor = await requireStaff(request, 'stock');
  const ref = db.doc(`suppliers/${requireString(request.data?.id, 'Tedarikçi', { max: 128 })}`);
  const s = (await requireLive(ref, 'Tedarikçi')).data();
  if (s.balance) throw new HttpsError('failed-precondition', 'Borç bakiyesi olan tedarikçi silinemez.');
  await db.runTransaction(async (tx) => {
    tx.update(ref, { deleted: true, updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'supplier_delete', actor: actor.uid, target: ref.path });
  });
  return { deleted: true };
});

// Sipariş: taslak ya da gönderildi durumunda düzenlenir; numara sırayla verilir.
exports.savePurchaseOrder = onCall(async (request) => {
  const actor = await requireStaff(request, 'stock');
  const data = validated(validatePurchaseOrder, request.data);
  await requireLive(db.doc(`suppliers/${data.supplierId}`), 'Tedarikçi');
  const id = request.data?.id;
  const ref = id ? db.doc(`purchaseOrders/${requireString(id, 'Sipariş', { max: 128 })}`) : db.collection('purchaseOrders').doc();
  const counter = db.doc('counters/purchaseOrders');
  const no = await db.runTransaction(async (tx) => {
    const [before, c] = await Promise.all([tx.get(ref), tx.get(counter)]);
    const total = data.lines.reduce((s, l) => s + l.amount, 0);
    if (id) {
      if (!before.exists) throw new HttpsError('not-found', 'Sipariş bulunamadı.');
      if (!['draft', 'sent'].includes(before.data().status)) {
        throw new HttpsError('failed-precondition', 'Teslim alınmış ya da iptal edilmiş sipariş değiştirilemez.');
      }
      tx.update(ref, { ...data, total, updatedAt: FieldValue.serverTimestamp() });
      return before.data().no;
    }
    const next = (c.exists ? c.data().last : 0) + 1;
    tx.set(counter, { last: next });
    tx.set(ref, { ...data, total, no: next, createdBy: actor.uid, createdAt: FieldValue.serverTimestamp(),
      updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'purchase_order_create', actor: actor.uid, target: ref.path, after: { no: next, total } });
    return next;
  });
  return { id: ref.id, no };
});

exports.cancelPurchaseOrder = onCall(async (request) => {
  const actor = await requireStaff(request, 'stock');
  const ref = db.doc(`purchaseOrders/${requireString(request.data?.id, 'Sipariş', { max: 128 })}`);
  await db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (!snap.exists) throw new HttpsError('not-found', 'Sipariş bulunamadı.');
    if (!['draft', 'sent'].includes(snap.data().status)) throw new HttpsError('failed-precondition', 'Bu sipariş iptal edilemez.');
    tx.update(ref, { status: 'cancelled', updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'purchase_order_cancel', actor: actor.uid, target: ref.path });
  });
  return { cancelled: true };
});

// Hazır şablon / toplu kurulum: malzemeler oluşturulur, ürün reçeteleri ve seçenek etkileri yazılır.
// { ingredients: [{ key, ...malzeme }], recipes: [{ productId, recipe: [{ ingredient: key|id, qty, takeawayOnly }] }],
//   optionEffects: [{ groupId, optionId, effect }] }  (effect içinde malzemeler key ya da id ile)
exports.importStock = onCall(async (request) => {
  const actor = await requireStaff(request, 'stock');
  const matrix = await loadPermissionMatrix();
  if (!hasPermission(matrix, actor.role, 'editMenu', actor.staff.permissions)) {
    throw new HttpsError('permission-denied', 'Reçete yazmak için menü düzenleme yetkisi de gerekir.');
  }
  const d = request.data || {};
  if (!Array.isArray(d.ingredients) || d.ingredients.length > 200) throw new HttpsError('invalid-argument', 'Malzeme listesi geçersiz.');
  const keys = new Map();
  const batch = db.batch();
  for (const ing of d.ingredients) {
    const key = requireString(ing?.key, 'Anahtar', { max: 60 });
    const ref = db.collection('ingredients').doc();
    keys.set(key, ref.id);
    batch.set(ref, { ...validated(validateIngredient, ing), stock: 0, deleted: false,
      createdAt: FieldValue.serverTimestamp(), updatedAt: FieldValue.serverTimestamp() });
  }
  const resolve = (k) => keys.get(k) || k;
  for (const r of d.recipes || []) {
    const recipe = validated(validateRecipe, (r.recipe || []).map((x) => ({ ...x, ingredientId: resolve(x.ingredient || x.ingredientId) })));
    const ref = db.doc(`products/${requireString(r.productId, 'Ürün', { max: 128 })}`);
    await requireLive(ref, 'Ürün');
    batch.update(ref, { recipe, updatedAt: FieldValue.serverTimestamp() });
  }
  const groups = new Map();
  for (const o of d.optionEffects || []) {
    const gid = requireString(o.groupId, 'Seçenek grubu', { max: 128 });
    if (!groups.has(gid)) groups.set(gid, (await requireLive(db.doc(`optionGroups/${gid}`), 'Seçenek grubu')).data());
    const e = o.effect || {};
    const effect = validated(validateRecipeEffect, {
      ...(e.replace ? { replace: e.replace.map((x) => ({ from: resolve(x.from), to: resolve(x.to) })) } : {}),
      ...(e.add ? { add: e.add.map((x) => ({ ingredientId: resolve(x.ingredient || x.ingredientId), qty: x.qty })) } : {}),
      ...(e.scale ? { scale: e.scale } : {}),
    });
    const g = groups.get(gid);
    g.options = g.options.map((opt) => (opt.id === o.optionId ? { ...opt, recipeEffect: effect } : opt));
  }
  for (const [gid, g] of groups) batch.update(db.doc(`optionGroups/${gid}`), { options: g.options, updatedAt: FieldValue.serverTimestamp() });
  batch.set(db.collection('auditLogs').doc(), { action: 'stock_import', actor: actor.uid, target: 'ingredients',
    after: { ingredients: keys.size, recipes: (d.recipes || []).length }, at: FieldValue.serverTimestamp() });
  await batch.commit();
  return { ingredients: Object.fromEntries(keys) };
});

// Modüller (5. ve 6. ekran): yalnızca Yönetici (owner) değiştirir.
exports.saveModules = onCall(async (request) => {
  const actor = await requireStaff(request);
  if (actor.role !== 'owner') throw new HttpsError('permission-denied', 'Modülleri yalnızca yönetici değiştirebilir.');
  const data = validated(validateModules, request.data);
  const ref = db.doc('settings/modules');
  await db.runTransaction(async (tx) => {
    const before = await tx.get(ref);
    tx.set(ref, { ...data, updatedBy: actor.uid, updatedAt: FieldValue.serverTimestamp() });
    audit(tx, { action: 'modules_change', actor: actor.uid, target: 'settings/modules',
      before: before.exists ? before.data() : null, after: data });
  });
  return data;
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
