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
