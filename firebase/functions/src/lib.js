// Firebase'e bağımlı olmayan saf yardımcı fonksiyonlar (birim testleri test/lib.test.js içinde).
// NexPOS (Python) tarafındaki karşılıkları cloud/permissions.py ve cloud/pins.py içindedir;
// buradaki tablolar değişirse orayı da güncelleyin.

const crypto = require('crypto');

const ROLES = ['owner', 'manager', 'cashier', 'waiter', 'courier', 'barista', 'kitchen'];

// NexPOS yetki matrisindeki satırlar.
const PERMISSIONS = [
  'openTable', // Masa açma/kapatma
  'voidItem', // Sipariş/ürün iptali
  'comp', // İkram
  'refund', // İade
  'discount', // İskonto
  'cash', // Kasa işlemleri
  'expense', // Gider girişi
  'editMenu', // Ürün/fiyat tanımlama
  'settings', // Sistem ayarları
  'viewReports', // Raporlar
  'manageUsers', // Kullanıcı tanımlama
];

function allPermissions(value) {
  return Object.fromEntries(PERMISSIONS.map((p) => [p, value]));
}

const DEFAULT_PERMISSIONS = {
  owner: allPermissions(true),
  manager: {
    ...allPermissions(true),
    settings: false,
  },
  cashier: { ...allPermissions(false), openTable: true, discount: true, cash: true, expense: true },
  waiter: { ...allPermissions(false), openTable: true },
  courier: { ...allPermissions(false), openTable: true },
  barista: allPermissions(false),
  kitchen: allPermissions(false),
};

// İstemciden gelen matrisi temizler: bilinmeyen rol/yetki atılır, eksikler varsayılandan
// doldurulur, owner her zaman tam yetkilidir.
function normalizePermissions(input) {
  const roles = {};
  const source = input && typeof input === 'object' ? input : {};
  for (const role of ROLES) {
    const given = source[role] && typeof source[role] === 'object' ? source[role] : {};
    roles[role] = {};
    for (const p of PERMISSIONS) {
      roles[role][p] = typeof given[p] === 'boolean' ? given[p] : DEFAULT_PERMISSIONS[role][p];
    }
  }
  roles.owner = allPermissions(true);
  return roles;
}

// matrix: settings/permissions.roles, overrides: staff.permissions (kişiye özel)
function hasPermission(matrix, role, permission, overrides) {
  if (role === 'owner') return true;
  if (overrides && typeof overrides[permission] === 'boolean') return overrides[permission];
  const roles = matrix || DEFAULT_PERMISSIONS;
  return Boolean(roles[role] && roles[role][permission]);
}

// Yönetici herkesi; müdür yalnızca kendisinden alt rolleri yönetebilir.
function canManageRole(actorRole, targetRole) {
  if (actorRole === 'owner') return true;
  if (actorRole === 'manager') return !['owner', 'manager'].includes(targetRole);
  return false;
}

// Panel girişi (e-posta + şifre) yalnızca bu rollerde açılır.
function roleNeedsEmail(role) {
  return role === 'owner' || role === 'manager';
}

// 6 haneli, tahmin edilmesi kolay olmayan PIN.
function isValidPin(pin) {
  if (typeof pin !== 'string' || !/^\d{6}$/.test(pin)) return false;
  if (/^(\d)\1{5}$/.test(pin)) return false; // 000000, 111111
  if ('0123456789'.includes(pin) || '9876543210'.includes(pin)) return false; // 123456, 654321
  return true;
}

// PIN özeti: Python'daki hashlib.scrypt ile aynı parametreler.
const SCRYPT = { N: 16384, r: 8, p: 1, keylen: 32 };

function hashPin(pin, saltHex) {
  const salt = saltHex ? Buffer.from(saltHex, 'hex') : crypto.randomBytes(16);
  const hash = crypto.scryptSync(pin, salt, SCRYPT.keylen, {
    N: SCRYPT.N,
    r: SCRYPT.r,
    p: SCRYPT.p,
  });
  return {
    algo: 'scrypt',
    salt: salt.toString('hex'),
    hash: hash.toString('hex'),
    n: SCRYPT.N,
    r: SCRYPT.r,
    p: SCRYPT.p,
  };
}

function verifyPin(pin, record) {
  if (!record || record.algo !== 'scrypt' || typeof pin !== 'string') return false;
  const computed = Buffer.from(hashPin(pin, record.salt).hash, 'hex');
  const expected = Buffer.from(record.hash, 'hex');
  return computed.length === expected.length && crypto.timingSafeEqual(computed, expected);
}

// Terminale A, B, C… harfi verilir; adisyon numaraları bu harfle başlar (A47).
// Q harfi uygulamadan gelen siparişlere ayrılmıştır.
function nextTerminalLetter(usedLetters) {
  const used = new Set(usedLetters || []);
  for (const letter of 'ABCDEFGHJKLMNPRSTUVWXYZ') {
    if (letter !== 'Q' && !used.has(letter)) return letter;
  }
  return null;
}

// Telefonu sadece rakamlara indirger ve 5XXXXXXXXX biçimine getirir.
function normalizePhone(phone) {
  if (typeof phone !== 'string') return null;
  let digits = phone.replace(/\D/g, '');
  if (digits.startsWith('90') && digits.length === 12) digits = digits.slice(2);
  if (digits.startsWith('0') && digits.length === 11) digits = digits.slice(1);
  return /^5[0-9]{9}$/.test(digits) ? digits : null;
}

const MAX_OPS_PER_SYNC = 50;

// syncOps ile gelen paketin biçimini doğrular. Hatalı biçim tüm paketi reddeder;
// tek tek işlemlerin içeriği fonksiyonda ayrıca kontrol edilir.
function validateOpsBatch(ops) {
  if (!Array.isArray(ops) || ops.length === 0 || ops.length > MAX_OPS_PER_SYNC) return false;
  return ops.every(
    (o) =>
      o &&
      typeof o === 'object' &&
      typeof o.opId === 'string' &&
      /^[A-Za-z0-9-]{8,64}$/.test(o.opId) &&
      typeof o.op === 'string' &&
      /^[A-Za-z]{1,40}$/.test(o.op) &&
      o.payload &&
      typeof o.payload === 'object' &&
      !Array.isArray(o.payload) &&
      typeof o.staffId === 'string' &&
      o.staffId.length > 0 &&
      o.staffId.length <= 128 &&
      typeof o.createdAt === 'string',
  );
}

module.exports = {
  ROLES,
  PERMISSIONS,
  DEFAULT_PERMISSIONS,
  MAX_OPS_PER_SYNC,
  normalizePermissions,
  hasPermission,
  canManageRole,
  roleNeedsEmail,
  isValidPin,
  hashPin,
  verifyPin,
  nextTerminalLetter,
  normalizePhone,
  validateOpsBatch,
};
