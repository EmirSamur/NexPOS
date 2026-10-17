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
  'stock', // Malzeme, reçete, sayım, alış (8. ekran)
  'waste', // Zayi girme
  'shifts', // Vardiya planı, mesai düzeltme ve raporu (9. ekran)
  'loyalty', // Müşteri listesi, elle damga/ödül düzeltme (10. ekran)
  'campaigns', // Kampanya ve bildirim (10. ekran)
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
    waste: true,
  },
  waiter: { ...allPermissions(false), openTable: true },
  courier: { ...allPermissions(false), openTable: true },
  barista: { ...allPermissions(false), markSoldOut: true, waste: true },
  kitchen: { ...allPermissions(false), markSoldOut: true, waste: true },
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
    // Reçete (8. ekran). Gönderilmezse undefined döner ve kayıtlı reçete korunur.
    ...(d.recipe !== undefined ? { recipe: validateRecipe(d.recipe) } : {}),
  };
}

// ---------------------------------------------------------------------------
// Stok ve reçete (8. ekran)
//
// Miktarlar malzemenin temel biriminde tam sayıdır (g, ml, adet). Birim maliyet kuruş cinsinden
// gösterim birimi başınadır: kg, L ya da adet (UNITS.factor temel birimdir).
// ---------------------------------------------------------------------------

const UNITS = { g: { display: 'kg', factor: 1000 }, ml: { display: 'L', factor: 1000 }, adet: { display: 'adet', factor: 1 } };
const INGREDIENT_GROUPS = ['bar', 'kitchen', 'packaging', 'other'];
const MAX_QTY = 10_000_000;

function qtyInt(v, field, { min = 1, max = MAX_QTY } = {}) {
  if (!Number.isInteger(v) || v < min || v > max) throw new MenuError(`${field} geçersiz.`);
  return v;
}

function validateIngredient(input) {
  const d = input || {};
  if (!UNITS[d.unit]) throw new MenuError('Birim g, ml ya da adet olmalıdır.');
  let purchaseUnit = null;
  if (d.purchaseUnit) {
    purchaseUnit = { name: text(d.purchaseUnit.name, 'Alış birimi', { max: 20 }),
      size: qtyInt(d.purchaseUnit.size, 'Alış birimi miktarı') };
  }
  const group = d.group ?? 'other';
  if (!INGREDIENT_GROUPS.includes(group)) throw new MenuError('Malzeme grubu geçersiz.');
  return {
    name: text(d.name, 'Malzeme adı', { max: 60 }),
    unit: d.unit,
    group,
    purchaseUnit,
    critical: qtyInt(d.critical ?? 0, 'Kritik seviye', { min: 0 }),
    target: d.target == null ? null : qtyInt(d.target, 'Hedef seviye', { min: 0 }),
    unitCost: kurus(d.unitCost ?? 0, 'Birim maliyet'),
    supplierName: text(d.supplierName, 'Tedarikçi', { max: 60, optional: true }),
    supplierId: d.supplierId ? text(d.supplierId, 'Tedarikçi', { max: 128 }) : null,
  };
}

// ---------------------------------------------------------------------------
// Tedarik (8b)
// ---------------------------------------------------------------------------

const PURCHASE_PAYMENT_METHODS = ['cash', 'card', 'transfer'];

function validateSupplier(input) {
  const d = input || {};
  return {
    name: text(d.name, 'Tedarikçi adı', { max: 60 }),
    contactName: text(d.contactName, 'Yetkili', { max: 60, optional: true }),
    phone: text(d.phone, 'Telefon', { max: 20, optional: true }),
    email: text(d.email, 'E-posta', { max: 80, optional: true }),
    note: text(d.note, 'Not', { max: 200, optional: true }),
  };
}

// Sipariş / teslim satırı: miktar temel birimde, tutar kuruş (satır toplamı)
function purchaseLines(list, { allowZero = false } = {}) {
  if (!Array.isArray(list) || list.length < 1 || list.length > 60) throw new MenuError('Satır yok ya da çok fazla.');
  return list.map((l) => ({
    ingredientId: text(l?.ingredientId, 'Malzeme', { max: 128 }),
    qty: qtyInt(l.qty, 'Miktar', { min: allowZero ? 0 : 1 }),
    amount: kurus(l.amount ?? 0, 'Tutar', { max: 100_000_000 }),
  }));
}

function validatePurchaseOrder(input) {
  const d = input || {};
  if (!['draft', 'sent'].includes(d.status ?? 'draft')) throw new MenuError('Sipariş durumu geçersiz.');
  return {
    supplierId: text(d.supplierId, 'Tedarikçi', { max: 128 }),
    status: d.status ?? 'draft',
    lines: purchaseLines(d.lines),
    note: text(d.note, 'Not', { max: 200, optional: true }),
  };
}

// Teslim alma (kuyruktan): { receiptId, supplierId, purchaseOrderId?, lines, payment: { status, method? }, note }
function validateReceipt(input) {
  const d = input || {};
  const pay = d.payment || {};
  if (!['paid', 'unpaid'].includes(pay.status)) throw new MenuError('Ödeme durumu ödendi ya da ödenecek olmalıdır.');
  if (pay.status === 'paid' && !PURCHASE_PAYMENT_METHODS.includes(pay.method)) throw new MenuError('Ödeme yöntemi geçersiz.');
  const lines = purchaseLines(d.lines, { allowZero: true }).filter((l) => l.qty > 0);
  if (!lines.length) throw new MenuError('Teslim alınan malzeme yok.');
  return {
    receiptId: text(d.receiptId, 'Teslim', { max: 64 }),
    supplierId: text(d.supplierId, 'Tedarikçi', { max: 128 }),
    purchaseOrderId: d.purchaseOrderId ? text(d.purchaseOrderId, 'Sipariş', { max: 128 }) : null,
    lines,
    total: lines.reduce((s, l) => s + l.amount, 0),
    payment: { status: pay.status, method: pay.status === 'paid' ? pay.method : null },
    note: text(d.note, 'Not', { max: 200, optional: true }),
  };
}

function validateSupplierPayment(input) {
  const d = input || {};
  if (!PURCHASE_PAYMENT_METHODS.includes(d.method)) throw new MenuError('Ödeme yöntemi geçersiz.');
  return {
    paymentId: text(d.paymentId, 'Ödeme', { max: 64 }),
    supplierId: text(d.supplierId, 'Tedarikçi', { max: 128 }),
    amount: kurus(d.amount, 'Tutar', { min: 1, max: 100_000_000 }),
    method: d.method,
    note: text(d.note, 'Not', { max: 200, optional: true }),
  };
}

// Ağırlıklı ortalama birim maliyet. stock: temel birim (eksi stok 0 sayılır), unitCost: kuruş / kg-L-adet,
// gelen: qty (temel birim) ve amount (kuruş, satır toplamı). factor: 1000 (g, ml) ya da 1 (adet).
function weightedUnitCost(stock, unitCost, qty, amount, factor) {
  const s = Math.max(stock, 0);
  if (qty <= 0) return unitCost;
  // s × (unitCost / factor) + amount  →  toplam değer (kuruş); bölü (s + qty) × factor
  return Math.round(((s * unitCost) / factor + amount) * factor / (s + qty));
}

function validateRecipe(list) {
  if (!Array.isArray(list) || list.length > 30) throw new MenuError('Reçete en çok 30 malzeme olabilir.');
  const seen = new Set();
  return list.map((r) => {
    const ingredientId = text(r?.ingredientId, 'Malzeme', { max: 128 });
    const takeawayOnly = r.takeawayOnly === true;
    const key = `${ingredientId}:${takeawayOnly}`;
    if (seen.has(key)) throw new MenuError('Bir malzeme reçetede bir kez yer alabilir.');
    seen.add(key);
    return { ingredientId, qty: qtyInt(r.qty, 'Reçete miktarı', { max: 100_000 }), takeawayOnly };
  });
}

// Seçeneğin reçeteye etkisi: { replace: [{from, to}], add: [{ingredientId, qty}], scale: 1.5 } ya da null.
function validateRecipeEffect(e) {
  if (e === undefined || e === null) return null;
  if (typeof e !== 'object') throw new MenuError('Reçete etkisi geçersiz.');
  const out = {};
  if (e.replace?.length) {
    if (!Array.isArray(e.replace) || e.replace.length > 5) throw new MenuError('Değiştirme listesi geçersiz.');
    out.replace = e.replace.map((r) => ({ from: text(r?.from, 'Malzeme', { max: 128 }), to: text(r?.to, 'Malzeme', { max: 128 }) }));
  }
  if (e.add?.length) {
    if (!Array.isArray(e.add) || e.add.length > 5) throw new MenuError('Ekleme listesi geçersiz.');
    out.add = e.add.map((r) => ({ ingredientId: text(r?.ingredientId, 'Malzeme', { max: 128 }),
      qty: qtyInt(r.qty, 'Ek miktar', { max: 100_000 }) }));
  }
  if (e.scale !== undefined && e.scale !== null && e.scale !== 1) {
    if (typeof e.scale !== 'number' || e.scale < 0.25 || e.scale > 5) throw new MenuError('Çarpan 0,25 ile 5 arasında olmalıdır.');
    out.scale = Math.round(e.scale * 100) / 100;
  }
  return Object.keys(out).length ? out : null;
}

const STOCK_MOVE_TYPES = { sale: 'openTable', void_return: 'openTable', count: 'stock', adjust: 'stock', waste: 'waste' };
// Not: alış (purchase) hareketi stockMove ile değil, receivePurchase işlemiyle gelir (maliyeti de günceller).

// Stok hareketi (kuyruktan): { movementId, type, orderId?, lineId?, reason?, lines: [{ ingredientId, qty (+/−) }] }
function validateStockMove(p) {
  const d = p || {};
  if (!STOCK_MOVE_TYPES[d.type]) throw new MenuError('Stok hareketi türü geçersiz.');
  if (!Array.isArray(d.lines) || d.lines.length < 1 || d.lines.length > 60) throw new MenuError('Hareket satırı yok.');
  const totals = new Map();
  for (const l of d.lines) {
    const id = text(l?.ingredientId, 'Malzeme', { max: 128 });
    if (!Number.isInteger(l.qty) || l.qty === 0 || Math.abs(l.qty) > MAX_QTY) throw new MenuError('Miktar geçersiz.');
    totals.set(id, (totals.get(id) || 0) + l.qty);
  }
  return {
    movementId: text(d.movementId, 'Hareket', { max: 64 }),
    type: d.type,
    orderId: d.orderId ? text(d.orderId, 'Adisyon', { max: 64 }) : null,
    lineId: d.lineId ? text(d.lineId, 'Satır', { max: 64 }) : null,
    reason: text(d.reason, 'Gerekçe', { max: 120, optional: true }),
    lines: [...totals].filter(([, q]) => q !== 0).map(([ingredientId, qty]) => ({ ingredientId, qty })),
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
      recipeEffect: validateRecipeEffect(o.recipeEffect),
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

// ---------------------------------------------------------------------------
// Modüller (5. ve 6. ekran): settings/modules. Kapalı modül hiçbir ekranda görünmez;
// kapatmak veriyi silmez.
// ---------------------------------------------------------------------------

const DEFAULT_MODULES = {
  kds: { enabled: false, warnMinutes: 10, lateMinutes: 20, sound: true },
  cashSession: { required: false, diffReasonThreshold: 2000 },
  printing: { enabled: false, kitchenTickets: false },
  paymentMethods: { cash: true, card: true, meal: true },
  tips: true,
  stock: { enabled: false, askOnVoid: true },
  staff: { enabled: false, lateToleranceMinutes: 5 },
  loyalty: { enabled: false },
  campaigns: { enabled: false },
  app: { enabled: false, tableOrders: false, pickup: false },
};

function strictBool(v, fallback) {
  if (v === undefined || v === null) return fallback;
  if (typeof v !== 'boolean') throw new MenuError('Açık/kapalı değeri geçersiz.');
  return v;
}

function intIn(v, fallback, min, max, message) {
  const x = v ?? fallback;
  if (!Number.isInteger(x) || x < min || x > max) throw new MenuError(message);
  return x;
}

function validateModules(input) {
  const d = input || {};
  const D = DEFAULT_MODULES;
  const kds = d.kds || {};
  const warnMinutes = intIn(kds.warnMinutes, D.kds.warnMinutes, 1, 120, 'Sarı eşik 1-120 dakika olmalıdır.');
  const lateMinutes = intIn(kds.lateMinutes, D.kds.lateMinutes, 2, 240, 'Kırmızı eşik 2-240 dakika olmalıdır.');
  if (lateMinutes <= warnMinutes) throw new MenuError('Kırmızı eşik sarı eşikten büyük olmalıdır.');
  const cs = d.cashSession || {};
  const pr = d.printing || {};
  const pm = d.paymentMethods || {};
  const st = d.stock || {};
  const sf = d.staff || {};
  const methods = {
    cash: strictBool(pm.cash, true),
    card: strictBool(pm.card, true),
    meal: strictBool(pm.meal, true),
  };
  if (!Object.values(methods).some(Boolean)) throw new MenuError('En az bir ödeme yöntemi açık olmalıdır.');
  return {
    kds: { enabled: strictBool(kds.enabled, D.kds.enabled), warnMinutes, lateMinutes, sound: strictBool(kds.sound, D.kds.sound) },
    cashSession: {
      required: strictBool(cs.required, D.cashSession.required),
      diffReasonThreshold: intIn(cs.diffReasonThreshold, D.cashSession.diffReasonThreshold, 0, 10_000_000,
        'Fark eşiği geçersiz.'),
    },
    printing: { enabled: strictBool(pr.enabled, D.printing.enabled), kitchenTickets: strictBool(pr.kitchenTickets, false) },
    paymentMethods: methods,
    tips: strictBool(d.tips, D.tips),
    stock: { enabled: strictBool(st.enabled, D.stock.enabled), askOnVoid: strictBool(st.askOnVoid, D.stock.askOnVoid) },
    staff: { enabled: strictBool(sf.enabled, D.staff.enabled),
      lateToleranceMinutes: intIn(sf.lateToleranceMinutes, D.staff.lateToleranceMinutes, 0, 60,
        'Geç kalma toleransı 0-60 dakika olmalıdır.') },
    loyalty: { enabled: strictBool((d.loyalty || {}).enabled, D.loyalty.enabled) },
    campaigns: { enabled: strictBool((d.campaigns || {}).enabled, D.campaigns.enabled) },
    app: { enabled: strictBool((d.app || {}).enabled, false), tableOrders: strictBool((d.app || {}).tableOrders, false),
      pickup: strictBool((d.app || {}).pickup, false) },
  };
}

function normalizeModules(stored) {
  try {
    return validateModules(stored);
  } catch (e) {
    return JSON.parse(JSON.stringify(DEFAULT_MODULES));
  }
}

// Kasa oturumunda beklenen nakit: açılış + nakit tahsilat − nakit iade + giriş − çıkış.
// Para üstü tahsilata dahil değildir (alınan − para üstü = tutar).
function expectedCash(session, payments, refunds) {
  const cashIn = payments.filter((p) => p.method === 'cash').reduce((s, p) => s + p.amount, 0);
  const cashOut = refunds.filter((r) => r.method === 'cash').reduce((s, r) => s + r.amount, 0);
  const moves = (session.movements || []).reduce((s, m) => s + (m.type === 'in' ? m.amount : -m.amount), 0);
  return session.openingCash + cashIn - cashOut + moves;
}

// ---------------------------------------------------------------------------
// Vardiya planı ve mesai (9. ekran)
// ---------------------------------------------------------------------------

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
const PLAN_LEAVES = ['annual', 'sick', 'unpaid', 'holiday'];

// Plan hücresi: { staffId, date, start, end, breakMinutes, leave, note } ya da { staffId, date, clear: true }
function validateShiftCell(c) {
  const d = c || {};
  const staffId = text(d.staffId, 'Personel', { max: 128 });
  if (typeof d.date !== 'string' || !DATE_RE.test(d.date)) throw new MenuError('Tarih geçersiz.');
  if (d.clear === true) return { staffId, date: d.date, clear: true };
  const note = text(d.note, 'Not', { max: 80, optional: true });
  if (d.leave) {
    if (!PLAN_LEAVES.includes(d.leave)) throw new MenuError('İzin türü geçersiz.');
    return { staffId, date: d.date, leave: d.leave, start: null, end: null, breakMinutes: 0, note };
  }
  if (!TIME_RE.test(d.start || '') || !TIME_RE.test(d.end || '')) throw new MenuError('Saat SS:DD biçiminde olmalıdır.');
  if (d.start === d.end) throw new MenuError('Başlangıç ve bitiş aynı olamaz.');
  return { staffId, date: d.date, leave: null, start: d.start, end: d.end,
    breakMinutes: intIn(d.breakMinutes, 0, 0, 240, 'Mola 0-240 dakika olmalıdır.'), note };
}

// Müşteri (10. ekran): { name, phone, birthDate?: 'MM-DD', marketingConsent }
const BIRTH_RE = /^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
function validateCustomer(input) {
  const { normalizePhone } = require('./loyalty');
  const d = input || {};
  const name = text(d.name, 'Ad', { max: 60 });
  const phone = normalizePhone(d.phone);
  if (!phone) throw new MenuError('Telefon numarası geçersiz.');
  let birthDate = null;
  if (d.birthDate !== undefined && d.birthDate !== null && d.birthDate !== '') {
    if (typeof d.birthDate !== 'string' || !BIRTH_RE.test(d.birthDate)) throw new MenuError('Doğum günü AA-GG biçiminde olmalıdır.');
    birthDate = d.birthDate;
  }
  if (typeof d.marketingConsent !== 'boolean') throw new MenuError('Bildirim izni belirtilmelidir.');
  return { name, phone, birthDate, marketingConsent: d.marketingConsent };
}

module.exports = {
  validateCustomer,
  validateShiftCell,
  PURCHASE_PAYMENT_METHODS,
  validateSupplier,
  validatePurchaseOrder,
  validateReceipt,
  validateSupplierPayment,
  weightedUnitCost,
  UNITS,
  STOCK_MOVE_TYPES,
  validateIngredient,
  validateRecipe,
  validateRecipeEffect,
  validateStockMove,
  DEFAULT_MODULES,
  validateModules,
  normalizeModules,
  expectedCash,
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
