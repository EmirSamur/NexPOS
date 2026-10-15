const { test } = require('node:test');
const assert = require('node:assert/strict');
const lib = require('../src/lib');

test('normalizePermissions: eksikleri varsayılandan doldurur, owner her zaman tam yetkili', () => {
  const roles = lib.normalizePermissions({
    waiter: { discount: true, bogus: true },
    owner: { settings: false },
    hacker: { settings: true },
  });
  assert.equal(roles.waiter.discount, true);
  assert.equal(roles.waiter.openTable, true);
  assert.equal(roles.waiter.bogus, undefined);
  assert.equal(roles.owner.settings, true);
  assert.equal(roles.hacker, undefined);
  assert.deepEqual(Object.keys(roles).sort(), [...lib.ROLES].sort());
});

test('normalizePermissions: boolean olmayan değerleri yok sayar', () => {
  const roles = lib.normalizePermissions({ waiter: { discount: 'true' } });
  assert.equal(roles.waiter.discount, false);
});

test('hasPermission: kişiye özel ayar rolü ezer, owner her zaman yetkili', () => {
  const m = lib.normalizePermissions(null);
  assert.equal(lib.hasPermission(m, 'waiter', 'discount'), false);
  assert.equal(lib.hasPermission(m, 'waiter', 'discount', { discount: true }), true);
  assert.equal(lib.hasPermission(m, 'cashier', 'discount', { discount: false }), false);
  assert.equal(lib.hasPermission(m, 'owner', 'settings', { settings: false }), true);
  assert.equal(lib.hasPermission(m, 'nobody', 'openTable'), false);
});

test('canManageRole: müdür yönetici ve müdür ekleyemez', () => {
  assert.equal(lib.canManageRole('owner', 'owner'), true);
  assert.equal(lib.canManageRole('manager', 'waiter'), true);
  assert.equal(lib.canManageRole('manager', 'manager'), false);
  assert.equal(lib.canManageRole('manager', 'owner'), false);
  assert.equal(lib.canManageRole('cashier', 'waiter'), false);
});

test('isValidPin', () => {
  assert.equal(lib.isValidPin('482913'), true);
  for (const bad of ['12345', '1234567', 'abcdef', '111111', '123456', '654321', '012345', 482913]) {
    assert.equal(lib.isValidPin(bad), false, String(bad));
  }
});

test('hashPin / verifyPin', () => {
  const rec = lib.hashPin('482913');
  assert.equal(rec.algo, 'scrypt');
  assert.equal(rec.salt.length, 32);
  assert.equal(lib.verifyPin('482913', rec), true);
  assert.equal(lib.verifyPin('482914', rec), false);
  assert.equal(lib.verifyPin('482913', null), false);
  // Aynı tuz aynı özeti verir (Python tarafı bu özelliğe dayanır).
  assert.equal(lib.hashPin('482913', rec.salt).hash, rec.hash);
});

test('hashPin: Python hashlib.scrypt ile aynı sonucu verir (sabit vektör)', () => {
  // python3 -c "import hashlib;print(hashlib.scrypt(b'482913',salt=bytes.fromhex('00112233445566778899aabbccddeeff'),n=16384,r=8,p=1,dklen=32).hex())"
  const rec = lib.hashPin('482913', '00112233445566778899aabbccddeeff');
  assert.equal(rec.hash, '7a1c930a8cc57f037ca762cbfd3f09a10469299fafcca9ff5e0a25a46b23414d');
});

test('nextTerminalLetter: Q ve kullanılmış harfleri atlar', () => {
  assert.equal(lib.nextTerminalLetter([]), 'A');
  assert.equal(lib.nextTerminalLetter(['A', 'B']), 'C');
  assert.equal(lib.nextTerminalLetter(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P']), 'R');
});

test('validateOpsBatch', () => {
  const ok = { opId: 'abcd1234-ef', op: 'audit', payload: {}, staffId: 's1', createdAt: '2026-10-14T10:00:00Z' };
  assert.equal(lib.validateOpsBatch([ok]), true);
  assert.equal(lib.validateOpsBatch([]), false);
  assert.equal(lib.validateOpsBatch(Array(51).fill(ok)), false);
  assert.equal(lib.validateOpsBatch([{ ...ok, opId: 'kısa' }]), false);
  assert.equal(lib.validateOpsBatch([{ ...ok, payload: [] }]), false);
  assert.equal(lib.validateOpsBatch([{ ...ok, op: 'a b' }]), false);
  assert.equal(lib.validateOpsBatch([{ ...ok, staffId: '' }]), false);
});

// ---------------------------------------------------------------------------
// Menü (2. ekran)
// ---------------------------------------------------------------------------

test('markSoldOut varsayılanları', () => {
  const m = lib.normalizePermissions(null);
  assert.equal(m.barista.markSoldOut, true);
  assert.equal(m.kitchen.markSoldOut, true);
  assert.equal(m.cashier.markSoldOut, true);
  assert.equal(m.waiter.markSoldOut, false);
});

test('validateCategory', () => {
  const c = lib.validateCategory({ name: ' Sıcak Kahveler ', stampEligible: true });
  assert.deepEqual(c, { name: 'Sıcak Kahveler', station: 'bar', color: '#6C5CE7', visibleInApp: true, stampEligible: true });
  assert.throws(() => lib.validateCategory({ name: '' }), lib.MenuError);
  assert.throws(() => lib.validateCategory({ name: 'x', station: 'salon' }), lib.MenuError);
  assert.throws(() => lib.validateCategory({ name: 'x', color: 'red' }), lib.MenuError);
});

test('validateProduct: kuruş, KDV, alerjen, tat profili', () => {
  const p = lib.validateProduct({
    categoryId: 'c1', name: 'Latte', price: 9500, tags: ['yeni', 'yeni'], allergens: ['milk'],
    optionGroupIds: ['size', 'size', 'milk'],
    flavor: { strength: 3, sweetness: 2, acidity: 1, body: 4, milk: true, temperature: 'hot', notes: ['çikolata'] },
  });
  assert.equal(p.price, 9500);
  assert.equal(p.taxRate, 10);
  assert.deepEqual(p.tags, ['yeni']);
  assert.deepEqual(p.optionGroupIds, ['size', 'milk']);
  assert.equal(p.stampEligible, null);
  assert.equal(p.flavor.milk, true);
  for (const bad of [
    { price: 95.5 }, { price: -1 }, { taxRate: 18 }, { allergens: ['fıstık'] },
    { flavor: { strength: 6, sweetness: 1, acidity: 1, body: 1, temperature: 'hot' } },
    { imageUrl: 'javascript:alert(1)' },
  ]) {
    assert.throws(() => lib.validateProduct({ categoryId: 'c1', name: 'X', price: 100, ...bad }), lib.MenuError, JSON.stringify(bad));
  }
});

test('validateOptionGroup', () => {
  const g = lib.validateOptionGroup({
    name: 'Süt', required: true,
    options: [{ id: 'normal', name: 'Normal', priceDelta: 0 }, { id: 'oat', name: 'Yulaf', priceDelta: 1500 }],
  });
  assert.equal(g.selection, 'single');
  assert.equal(g.min, 1);
  assert.equal(g.max, 1);
  assert.equal(g.options[1].soldOut, false);
  assert.throws(() => lib.validateOptionGroup({ name: 'X', options: [] }), lib.MenuError);
  assert.throws(() => lib.validateOptionGroup({
    name: 'X', options: [{ id: 'a', name: 'A', priceDelta: 0 }, { id: 'a', name: 'B', priceDelta: 0 }],
  }), lib.MenuError);
  assert.throws(() => lib.validateOptionGroup({
    name: 'X', selection: 'multi', min: 3, max: 2, options: [{ id: 'a', name: 'A', priceDelta: 0 }],
  }), lib.MenuError);
});

test('applyPriceRule: yüzde, tutar, yukarı yuvarlama', () => {
  const r = (mode, value, rounding) => lib.validatePriceRule({ mode, value, rounding });
  assert.equal(lib.applyPriceRule(9500, r('percent', 12, 500)), 11000); // 106,40 → 110
  assert.equal(lib.applyPriceRule(8000, r('percent', 12, 0)), 8960);
  assert.equal(lib.applyPriceRule(8000, r('percent', 12, 100)), 9000);
  assert.equal(lib.applyPriceRule(8000, r('amount', 500, 0)), 8500);
  assert.equal(lib.applyPriceRule(300, r('amount', -500, 0)), 0);
  assert.equal(lib.applyPriceRule(10000, r('percent', 0, 500)), 10000); // zaten 5'in katı
  assert.throws(() => r('percent', 12, 250), lib.MenuError);
  assert.throws(() => r('amount', 5.5, 0), lib.MenuError);
  assert.throws(() => r('percent', 900, 0), lib.MenuError);
});

// ---------------------------------------------------------------------------
// Salon planı (3. ekran)
// ---------------------------------------------------------------------------

const T = (o = {}) => ({ tempId: 't1', name: 'Masa 1', shape: 'round', capacity: 2, x: 60, y: 60, w: 100, h: 100, ...o });

test('validateFloorPlan: geçerli plan', () => {
  const plan = lib.validateFloorPlan({
    tables: [T(), T({ tempId: 't2', name: 'Masa 2', shape: 'rect', capacity: 6, w: 200, rotation: 90 })],
    fixtures: [{ id: 'f1', kind: 'bar', label: 'Bar', x: 800, y: 40, w: 300, h: 60 }],
  });
  assert.equal(plan.tables.length, 2);
  assert.equal(plan.tables[1].rotation, 90);
  assert.equal(plan.fixtures[0].label, 'Bar');
});

test('validateFloorPlan: hatalar', () => {
  const bad = [
    { tables: [T(), T({ tempId: 't2', name: 'masa 1' })], fixtures: [] }, // aynı ad (büyük/küçük harf)
    { tables: [T({ shape: 'triangle' })], fixtures: [] },
    { tables: [T({ capacity: 0 })], fixtures: [] },
    { tables: [T({ x: 1190 })], fixtures: [] }, // tuval dışı
    { tables: [T({ w: 20 })], fixtures: [] }, // çok küçük
    { tables: [T({ rotation: 45 })], fixtures: [] },
    { tables: [T({ x: 1.5 })], fixtures: [] },
    { tables: [], fixtures: [{ id: 'f', kind: 'tv', x: 0, y: 0, w: 50, h: 50 }] },
    { tables: Array.from({ length: 101 }, (_, i) => T({ tempId: `t${i}`, name: `M${i}` })), fixtures: [] },
  ];
  for (const p of bad) assert.throws(() => lib.validateFloorPlan(p), lib.MenuError, JSON.stringify(p).slice(0, 80));
});

test('newQrToken: 16 karakter, tekrarsız', () => {
  const set = new Set(Array.from({ length: 200 }, () => lib.newQrToken()));
  assert.equal(set.size, 200);
  for (const t of set) assert.match(t, /^[A-Za-z0-9_-]{16}$/);
});

test('validateGeneralSettings', () => {
  assert.deepEqual(lib.validateGeneralSettings({ cafeName: 'Velvet', qrBaseUrl: 'https://kafe.web.app/masa/' }),
    { cafeName: 'Velvet', qrBaseUrl: 'https://kafe.web.app/masa', idleLockMinutes: 3 });
  for (const url of ['http://kafe.com/masa', 'https://kafe.com/masa?x=1', 'javascript:alert(1)']) {
    assert.throws(() => lib.validateGeneralSettings({ cafeName: 'V', qrBaseUrl: url }), lib.MenuError, url);
  }
  assert.throws(() => lib.validateGeneralSettings({ cafeName: 'V', qrBaseUrl: 'https://a.b', idleLockMinutes: 0 }), lib.MenuError);
});

test('modüller: varsayılanlar, eşik sırası ve en az bir ödeme yöntemi', () => {
  const { validateModules, normalizeModules, DEFAULT_MODULES, MenuError } = require('../src/lib');
  assert.deepEqual(validateModules({}), DEFAULT_MODULES);
  assert.equal(validateModules({ kds: { enabled: true } }).kds.enabled, true);
  assert.throws(() => validateModules({ kds: { warnMinutes: 15, lateMinutes: 15 } }), MenuError);
  assert.throws(() => validateModules({ paymentMethods: { cash: false, card: false, meal: false } }), MenuError);
  assert.throws(() => validateModules({ tips: 'evet' }), MenuError);
  assert.deepEqual(normalizeModules({ kds: { warnMinutes: 'x' } }), DEFAULT_MODULES);
});

test('beklenen nakit: açılış + nakit tahsilat − nakit iade ± hareketler', () => {
  const { expectedCash } = require('../src/lib');
  const session = { openingCash: 50000, movements: [{ type: 'in', amount: 2000 }, { type: 'out', amount: 4000 }] };
  const pays = [{ method: 'cash', amount: 10000 }, { method: 'card', amount: 25000 }];
  const refunds = [{ method: 'cash', amount: 3000 }, { method: 'card', amount: 500 }];
  assert.equal(expectedCash(session, pays, refunds), 55000);
});
