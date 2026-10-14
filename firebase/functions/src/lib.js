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
  'markSoldOut', // Ürünü "tükendi" işaretleme (internetsiz de çalışır)
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
  cashier: {
    ...allPermissions(false),
    openTable: true,
    discount: true,
    cash: true,
    expense: true,
    markSoldOut: true,
  },
  waiter: { ...allPermissions(false), openTable: true },
  courier: { ...allPermissions(false), openTable: true },
  barista: { ...allPermissions(false), markSoldOut: true },
  kitchen: { ...allPermissions(false), markSoldOut: true },
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

// ---------------------------------------------------------------------------
// Menü doğrulama (2. ekran)
// Para her zaman kuruş cinsinden tam sayıdır: 9500 = 95,00 ₺.
// Doğrulama hatası MenuError fırlatır; fonksiyonlar bunu invalid-argument'a çevirir.
// ---------------------------------------------------------------------------

class MenuError extends Error {}

const MAX_PRICE = 10_000_000; // 100.000 ₺
const TAX_RATES = [0, 1, 10, 20];
const STATIONS = ['bar', 'kitchen'];
const ALLERGENS = ['milk', 'gluten', 'nuts', 'soy', 'egg'];
const ROUNDING_STEPS = [0, 100, 500, 1000]; // yok, 1 ₺, 5 ₺, 10 ₺

function text(value, field, { min = 1, max = 80, optional = false } = {}) {
  if ((value === undefined || value === null || value === '') && optional) return '';
  if (typeof value !== 'string') throw new MenuError(`${field} geçersiz.`);
  const t = value.trim();
  if (t.length < min || t.length > max) throw new MenuError(`${field} ${min}-${max} karakter olmalıdır.`);
  return t;
}

function kurus(value, field, { min = 0, max = MAX_PRICE } = {}) {
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new MenuError(`${field} kuruş cinsinden ${min}-${max} arası tam sayı olmalıdır.`);
  }
  return value;
}

function bool(value, fallback) {
  return typeof value === 'boolean' ? value : fallback;
}

function optionalInt(value, field, max) {
  if (value === undefined || value === null || value === '') return null;
  if (!Number.isInteger(value) || value < 0 || value > max) throw new MenuError(`${field} geçersiz.`);
  return value;
}

function stringList(value, field, { maxItems = 10, maxLen = 24 } = {}) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value) || value.length > maxItems) throw new MenuError(`${field} en fazla ${maxItems} öğe olabilir.`);
  const out = [];
  for (const v of value) {
    const t = text(v, field, { max: maxLen });
    if (!out.includes(t)) out.push(t);
  }
  return out;
}

function validateCategory(input) {
  const d = input || {};
  const station = d.station ?? 'bar';
  if (!STATIONS.includes(station)) throw new MenuError('İstasyon bar ya da mutfak olmalıdır.');
  const color = d.color ?? '#6C5CE7';
  if (typeof color !== 'string' || !/^#[0-9A-Fa-f]{6}$/.test(color)) throw new MenuError('Renk #RRGGBB biçiminde olmalıdır.');
  return {
    name: text(d.name, 'Kategori adı', { max: 40 }),
    station,
    color,
    visibleInApp: bool(d.visibleInApp, true),
    stampEligible: bool(d.stampEligible, false),
  };
}

function validateFlavor(f) {
  if (f === undefined || f === null) return null;
  if (typeof f !== 'object' || Array.isArray(f)) throw new MenuError('Tat profili geçersiz.');
  const scale = (v, field) => {
    if (!Number.isInteger(v) || v < 1 || v > 5) throw new MenuError(`${field} 1-5 arası olmalıdır.`);
    return v;
  };
  if (!['hot', 'iced'].includes(f.temperature)) throw new MenuError('Sıcaklık sıcak ya da soğuk olmalıdır.');
  return {
    strength: scale(f.strength, 'Sertlik'),
    sweetness: scale(f.sweetness, 'Tatlılık'),
    acidity: scale(f.acidity, 'Asidite'),
    body: scale(f.body, 'Gövde'),
    milk: bool(f.milk, false),
    temperature: f.temperature,
    notes: stringList(f.notes, 'Tat notaları', { maxItems: 8 }),
  };
}

function validateProduct(input) {
  const d = input || {};
  const taxRate = d.taxRate ?? 10;
  if (!TAX_RATES.includes(taxRate)) throw new MenuError(`KDV oranı ${TAX_RATES.join(', ')} olabilir.`);
  const allergens = d.allergens ?? [];
  if (!Array.isArray(allergens) || allergens.some((a) => !ALLERGENS.includes(a))) {
    throw new MenuError('Alerjen listesi geçersiz.');
  }
  const optionGroupIds = d.optionGroupIds ?? [];
  if (!Array.isArray(optionGroupIds) || optionGroupIds.length > 10 || optionGroupIds.some((x) => typeof x !== 'string' || !x)) {
    throw new MenuError('Seçenek grupları geçersiz.');
  }
  const imageUrl = d.imageUrl ?? null;
  if (imageUrl !== null && (typeof imageUrl !== 'string' || !/^https?:\/\//.test(imageUrl) || imageUrl.length > 1000)) {
    throw new MenuError('Fotoğraf adresi geçersiz.');
  }
  return {
    categoryId: text(d.categoryId, 'Kategori', { max: 128 }),
    name: text(d.name, 'Ürün adı', { max: 60 }),
    description: text(d.description, 'Açıklama', { max: 300, optional: true }),
    price: kurus(d.price, 'Fiyat'),
    taxRate,
    imageUrl,
    tags: stringList(d.tags, 'Etiketler'),
    active: bool(d.active, true),
    visibleInApp: bool(d.visibleInApp, true),
    // null: kategoriden gelir
    stampEligible: typeof d.stampEligible === 'boolean' ? d.stampEligible : null,
    optionGroupIds: [...new Set(optionGroupIds)],
    allergens: [...new Set(allergens)],
    calories: optionalInt(d.calories, 'Kalori', 5000),
    caffeineMg: optionalInt(d.caffeineMg, 'Kafein', 1000),
    flavor: validateFlavor(d.flavor),
  };
}

function validateOptionGroup(input) {
  const d = input || {};
  const selection = d.selection ?? 'single';
  if (!['single', 'multi'].includes(selection)) throw new MenuError('Seçim türü tek ya da çoklu olmalıdır.');
  if (!Array.isArray(d.options) || d.options.length < 1 || d.options.length > 30) {
    throw new MenuError('Grupta 1-30 seçenek olmalıdır.');
  }
  const ids = new Set();
  const options = d.options.map((o) => {
    const id = text(o?.id, 'Seçenek kimliği', { max: 40 });
    if (!/^[A-Za-z0-9_-]+$/.test(id) || ids.has(id)) throw new MenuError('Seçenek kimlikleri benzersiz olmalıdır.');
    ids.add(id);
    if (!Number.isInteger(o.priceDelta) || Math.abs(o.priceDelta) > MAX_PRICE) {
      throw new MenuError('Seçenek fiyat farkı kuruş cinsinden tam sayı olmalıdır.');
    }
    return {
      id,
      name: text(o.name, 'Seçenek adı', { max: 40 }),
      priceDelta: o.priceDelta,
      active: bool(o.active, true),
      soldOut: bool(o.soldOut, false),
    };
  });
  const required = bool(d.required, false);
  let min = Number.isInteger(d.min) ? d.min : required ? 1 : 0;
  let max = Number.isInteger(d.max) ? d.max : selection === 'single' ? 1 : options.length;
  if (selection === 'single') max = 1;
  if (required && min < 1) min = 1;
  if (min < 0 || max < 1 || min > max || max > options.length) throw new MenuError('En az / en çok değerleri tutarsız.');
  return { name: text(d.name, 'Grup adı', { max: 40 }), selection, required, min, max, options };
}

// Toplu fiyat kuralı: { mode: 'percent' | 'amount', value, rounding }
// percent: value yüzde (12 = %12, -10 = %10 indirim); amount: kuruş (+500 = +5 ₺).
// rounding: kuruş adımı; sonuç bu adıma YUKARI yuvarlanır (0 = yuvarlama yok).
function validatePriceRule(rule) {
  const r = rule || {};
  if (!['percent', 'amount'].includes(r.mode)) throw new MenuError('Değişim türü yüzde ya da tutar olmalıdır.');
  if (typeof r.value !== 'number' || !Number.isFinite(r.value)) throw new MenuError('Değişim değeri geçersiz.');
  if (r.mode === 'percent' && (r.value < -90 || r.value > 500)) throw new MenuError('Yüzde -90 ile 500 arasında olmalıdır.');
  if (r.mode === 'amount' && (!Number.isInteger(r.value) || Math.abs(r.value) > MAX_PRICE)) {
    throw new MenuError('Tutar kuruş cinsinden tam sayı olmalıdır.');
  }
  const rounding = r.rounding ?? 0;
  if (!ROUNDING_STEPS.includes(rounding)) throw new MenuError('Yuvarlama adımı geçersiz.');
  return { mode: r.mode, value: r.value, rounding };
}

function applyPriceRule(price, rule) {
  let next = rule.mode === 'percent' ? Math.round(price * (1 + rule.value / 100)) : price + rule.value;
  if (rule.rounding) next = Math.ceil(next / rule.rounding) * rule.rounding;
  return Math.min(Math.max(next, 0), MAX_PRICE);
}

// ---------------------------------------------------------------------------
// Salon ve masa planı (3. ekran)
// Plan, ekrandan bağımsız 1200 × 800 birimlik sanal bir tuvalde tutulur.
// ---------------------------------------------------------------------------

const CANVAS = { width: 1200, height: 800 };
const TABLE_SHAPES = ['round', 'square', 'rect'];
const FIXTURE_KINDS = ['wall', 'bar', 'door', 'plant'];
const MAX_PLAN_ITEMS = 100;

function validateArea(input) {
  return { name: text((input || {}).name, 'Bölge adı', { max: 40 }) };
}

function geometry(o, label, { minSize = 20, maxSize = CANVAS.width } = {}) {
  const int = (v, f, min, max) => {
    if (!Number.isInteger(v) || v < min || v > max) throw new MenuError(`${label}: ${f} geçersiz.`);
    return v;
  };
  const w = int(o.w, 'genişlik', minSize, maxSize);
  const h = int(o.h, 'yükseklik', minSize, maxSize);
  const rotation = o.rotation ?? 0;
  if (![0, 90].includes(rotation)) throw new MenuError(`${label}: döndürme 0 ya da 90 olmalıdır.`);
  return {
    x: int(o.x, 'konum', 0, CANVAS.width - Math.min(w, h)),
    y: int(o.y, 'konum', 0, CANVAS.height - Math.min(w, h)),
    w,
    h,
    rotation,
  };
}

// Bir bölgenin planı: eklenen/güncellenen masalar ve bölgenin bütün dekor öğeleri.
// (Silinecek masalar saveFloorPlan'a ayrıca removedTableIds olarak gelir.)
function validateFloorPlan(input) {
  const d = input || {};
  if (!Array.isArray(d.tables) || d.tables.length > MAX_PLAN_ITEMS) {
    throw new MenuError(`Bir bölgede en fazla ${MAX_PLAN_ITEMS} masa olabilir.`);
  }
  if (!Array.isArray(d.fixtures) || d.fixtures.length > MAX_PLAN_ITEMS) {
    throw new MenuError(`Bir bölgede en fazla ${MAX_PLAN_ITEMS} dekor öğesi olabilir.`);
  }
  const names = new Set();
  const ids = new Set();
  const tables = d.tables.map((t) => {
    const name = text(t?.name, 'Masa adı', { max: 20 });
    const key = name.toLocaleLowerCase('tr');
    if (names.has(key)) throw new MenuError(`"${name}" adı bu bölgede birden fazla masada kullanılmış.`);
    names.add(key);
    const id = t.id ?? null;
    if (id !== null) {
      if (typeof id !== 'string' || !id || ids.has(id)) throw new MenuError('Masa kimlikleri geçersiz.');
      ids.add(id);
    }
    const tempId = id === null ? text(t.tempId, 'Geçici masa kimliği', { max: 40 }) : null;
    if (!TABLE_SHAPES.includes(t.shape)) throw new MenuError(`${name}: şekil geçersiz.`);
    if (!Number.isInteger(t.capacity) || t.capacity < 1 || t.capacity > 30) {
      throw new MenuError(`${name}: kişi sayısı 1-30 arası olmalıdır.`);
    }
    return { id, tempId, name, shape: t.shape, capacity: t.capacity,
      ...geometry(t, name, { minSize: 40, maxSize: 400 }) };
  });
  const fixtureIds = new Set();
  const fixtures = d.fixtures.map((f) => {
    if (!FIXTURE_KINDS.includes(f?.kind)) throw new MenuError('Dekor türü geçersiz.');
    const id = text(f.id, 'Dekor kimliği', { max: 40 });
    if (fixtureIds.has(id)) throw new MenuError('Dekor kimlikleri benzersiz olmalıdır.');
    fixtureIds.add(id);
    return { id, kind: f.kind, label: text(f.label, 'Dekor etiketi', { max: 30, optional: true }),
      ...geometry(f, 'Dekor', { minSize: 10 }) };
  });
  return { tables, fixtures };
}

function newQrToken() {
  return crypto.randomBytes(12).toString('base64url'); // 16 karakter, tahmin edilemez
}

// Eski NexPOS düzenini ızgaraya yerleştirir: 6 sütun, 120'lik kare masalar.
function gridLayout(index) {
  const col = index % 6;
  const row = Math.floor(index / 6);
  return { x: 60 + col * 180, y: 60 + row * 180, w: 120, h: 120, rotation: 0 };
}

function validateGeneralSettings(input) {
  const d = input || {};
  const qrBaseUrl = text(d.qrBaseUrl, 'QR adresi', { max: 200 });
  if (!/^https:\/\/[^\s?#]+$/.test(qrBaseUrl) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/[^\s?#]*$/.test(qrBaseUrl)) {
    throw new MenuError('QR adresi https:// ile başlamalı ve ? ya da # içermemelidir.');
  }
  const idle = d.idleLockMinutes ?? 3;
  if (!Number.isInteger(idle) || idle < 1 || idle > 60) throw new MenuError('Otomatik kilit 1-60 dakika olmalıdır.');
  return {
    cafeName: text(d.cafeName, 'Kafe adı', { max: 60 }),
    qrBaseUrl: qrBaseUrl.replace(/\/+$/, ''),
    idleLockMinutes: idle,
  };
}

module.exports = {
  CANVAS,
  validateArea,
  validateFloorPlan,
  newQrToken,
  gridLayout,
  validateGeneralSettings,
  MenuError,
  ALLERGENS,
  ROUNDING_STEPS,
  validateCategory,
  validateProduct,
  validateOptionGroup,
  validatePriceRule,
  applyPriceRule,
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
