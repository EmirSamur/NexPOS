// Stok ve reçete (8a): malzemeler, reçete, seçenek etkisi, kuyruktan stok hareketi, şablon aktarma.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll, deleteApp } =
  require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc, getDocs, collection } = require('firebase/firestore');

const OWNER = { email: 'stok-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Stok Sahibi', pin: '482913' };
let owner;
let term;
let waiter;
let barista;
let catId;
let latte;
let group;
let seq = 0;
const created = [];
const AT = '2026-10-15T12:00:00+03:00';

before(async () => {
  createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  ({ staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson S', role: 'waiter', pin: '730591' }));
  ({ staffId: barista } = await owner.call('manageStaff', { action: 'create', name: 'Barista S', role: 'barista', pin: '640218' }));
  ({ id: catId } = await owner.call('saveCategory', { name: 'Stok Kahve' }));
  ({ id: latte } = await owner.call('saveProduct', { categoryId: catId, name: 'Stok Latte', price: 9500 }));
  const reg = await owner.call('registerTerminal', { name: 'Stok Kasa' });
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(async () => {
  // Menü testleri boş menü bekler
  await Promise.all([adminDb.doc(`categories/${catId}`).delete(), adminDb.doc(`products/${latte}`).delete(),
    ...(group ? [adminDb.doc(`optionGroups/${group}`).delete()] : [])]);
  await closeAll();
});

const op = (name, payload, staffId = waiter) => ({ opId: `stk-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId, createdAt: AT });
const sync = async (...ops) => (await term.call('syncOps', { ops })).results;
const stockOf = async (id) => (await adminDb.doc(`ingredients/${id}`).get()).data().stock;

test('malzeme: yetki, doğrulama, birim maliyet', async () => {
  const { id } = await owner.call('saveIngredient', { name: 'Süt', unit: 'ml', critical: 5000, unitCost: 3500,
    purchaseUnit: { name: 'koli', size: 12000 }, group: 'bar' });
  created.push(id);
  const d = (await adminDb.doc(`ingredients/${id}`).get()).data();
  assert.deepEqual([d.stock, d.unit, d.purchaseUnit.size, d.deleted], [0, 'ml', 12000, false]);
  await expectCallError(owner.call('saveIngredient', { name: 'X', unit: 'litre' }), 'invalid-argument');
  // Stok bu fonksiyonla değiştirilemez
  await owner.call('saveIngredient', { id, name: 'Süt (tam yağlı)', unit: 'ml', stock: 999999, unitCost: 3600 });
  assert.equal(await stockOf(id), 0);
  // Müdür (stock yetkisi var) kaydedebilir; terminal okuyabilir, yazamaz
  await owner.call('manageStaff', { action: 'create', name: 'Stok Müdür', role: 'manager',
    email: 'stok-mudur@kafe.test', password: 'mudur-sifre-1', pin: '583920' });
  const manager = await signedInAs('stok-mudur@kafe.test', 'mudur-sifre-1');
  const { id: esp } = await manager.call('saveIngredient', { name: 'Espresso', unit: 'g', unitCost: 80000 });
  created.push(esp);
  await deleteApp(manager.app);
  assert.ok((await getDocs(collection(term.db, 'ingredients'))).size >= 2);
  await expectDenied(getDocs(collection(client().db, 'ingredients')));
});

test('reçete ve seçenek etkisi kaydedilir; reçetesiz kayıt eski reçeteyi silmez', async () => {
  const [sut, esp] = created;
  ({ id: group } = await owner.call('saveOptionGroup', { name: 'Stok Süt', options: [
    { id: 'n', name: 'Normal', priceDelta: 0 },
    { id: 'big', name: 'Büyük', priceDelta: 1000, recipeEffect: { scale: 1.5, add: [{ ingredientId: esp, qty: 9 }] } }] }));
  await owner.call('saveProduct', { id: latte, categoryId: catId, name: 'Stok Latte', price: 9500, optionGroupIds: [group],
    recipe: [{ ingredientId: esp, qty: 18 }, { ingredientId: sut, qty: 200 }] });
  let p = (await adminDb.doc(`products/${latte}`).get()).data();
  assert.deepEqual(p.recipe.map((r) => [r.qty, r.takeawayOnly]), [[18, false], [200, false]]);
  await owner.call('saveProduct', { id: latte, categoryId: catId, name: 'Stok Latte', price: 9900, optionGroupIds: [group] });
  p = (await adminDb.doc(`products/${latte}`).get()).data();
  assert.equal(p.recipe.length, 2);
  const g = (await adminDb.doc(`optionGroups/${group}`).get()).data();
  assert.deepEqual(g.options[1].recipeEffect, { scale: 1.5, add: [{ ingredientId: esp, qty: 9 }] });
  assert.equal(g.options[0].recipeEffect, null);
  await expectCallError(owner.call('saveProduct', { id: latte, categoryId: catId, name: 'Stok Latte', price: 9900,
    recipe: [{ ingredientId: esp, qty: 0 }] }), 'invalid-argument');
  // Reçetede olan malzeme silinemez
  await expectCallError(owner.call('deleteIngredient', { id: esp }), 'failed-precondition');
});

test('stok hareketi: satış düşer, iade ekler, tekrar gelen işlem bir kez uygulanır, yetkiler', async () => {
  const [sut, esp] = created;
  const sale = op('stockMove', { movementId: 'MV1', type: 'sale', orderId: 'X1', lineId: 'L1',
    lines: [{ ingredientId: esp, qty: -18 }, { ingredientId: sut, qty: -200 }, { ingredientId: 'silinmis', qty: -1 }] });
  let r = await sync(sale);
  assert.equal(r[0].status, 'ok');
  assert.deepEqual([await stockOf(esp), await stockOf(sut)], [-18, -200]);
  r = await sync(sale);
  assert.equal(r[0].status, 'duplicate');
  assert.equal(await stockOf(esp), -18);
  const mv = (await adminDb.doc('stockMovements/MV1').get()).data();
  assert.deepEqual([mv.type, mv.orderId, mv.applied.length, mv.terminalId !== undefined], ['sale', 'X1', 2, true]);

  r = await sync(op('stockMove', { movementId: 'MV2', type: 'void_return', orderId: 'X1', lineId: 'L1',
    lines: [{ ingredientId: esp, qty: 18 }] }));
  assert.equal(r[0].status, 'ok');
  assert.equal(await stockOf(esp), 0);
  // Sayım stock yetkisi ister: garson reddedilir, yönetici onayıyla geçer
  const owners = await adminDb.collection('staff').where('email', '==', OWNER.email).get();
  const count = (approvedBy) => op('stockMove', { movementId: `C-${approvedBy || 'x'}`, type: 'count',
    lines: [{ ingredientId: sut, qty: 12200 }], reason: 'İlk sayım', ...(approvedBy ? { approvedBy } : {}) });
  r = await sync(count(null));
  assert.match(r[0].error, /stock/);
  r = await sync(count(owners.docs[0].id));
  assert.equal(r[0].status, 'ok');
  assert.equal(await stockOf(sut), 12000);
  // Zayi: barista girebilir
  r = await sync(op('stockMove', { movementId: 'W1', type: 'waste', reason: 'Bozuldu',
    lines: [{ ingredientId: sut, qty: -1000 }] }, barista));
  assert.equal(r[0].status, 'ok');
  assert.equal(await stockOf(sut), 11000);
  // Geçersiz hareketler
  r = await sync(op('stockMove', { movementId: 'B1', type: 'gift', lines: [{ ingredientId: sut, qty: -1 }] }),
    op('stockMove', { movementId: 'B2', type: 'sale', lines: [{ ingredientId: sut, qty: 1.5 }] }));
  assert.deepEqual(r.map((x) => x.status), ['rejected', 'rejected']);
  // Hareketleri yönetici okur, terminal okur; giriş yapmayan okuyamaz
  assert.ok((await getDoc(doc(owner.db, 'stockMovements/MV1'))).exists());
  assert.ok((await getDoc(doc(term.db, 'stockMovements/MV1'))).exists());
});

test('hazır şablon: malzemeler, reçeteler ve seçenek etkileri tek seferde', async () => {
  const [sut] = created;
  const res = await owner.call('importStock', {
    ingredients: [{ key: 'yulaf', name: 'Yulaf sütü', unit: 'ml', unitCost: 9500 },
      { key: 'bardak', name: 'Bardak', unit: 'adet', unitCost: 180 }],
    recipes: [{ productId: latte, recipe: [{ ingredient: sut, qty: 200 }, { ingredient: 'bardak', qty: 1, takeawayOnly: true }] }],
    optionEffects: [{ groupId: group, optionId: 'n', effect: { replace: [{ from: sut, to: 'yulaf' }] } }],
  });
  const yulaf = res.ingredients.yulaf;
  created.push(yulaf, res.ingredients.bardak);
  const p = (await adminDb.doc(`products/${latte}`).get()).data();
  assert.deepEqual(p.recipe.map((r) => r.ingredientId), [sut, res.ingredients.bardak]);
  const g = (await adminDb.doc(`optionGroups/${group}`).get()).data();
  assert.deepEqual(g.options[0].recipeEffect, { replace: [{ from: sut, to: yulaf }] });
  assert.ok(g.options[1].recipeEffect.scale === 1.5); // dokunulmayan seçenek korunur
  const log = await adminDb.collection('auditLogs').where('action', '==', 'stock_import').get();
  assert.ok(log.size >= 1);
});

test('temizlik: bu dosyanın malzemeleri silinir', async () => {
  await Promise.all(created.map((id) => adminDb.doc(`ingredients/${id}`).delete()));
});
