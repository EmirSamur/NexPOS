// Menü (2. ekran): fonksiyonlar, kurallar, toplu fiyat, aktarım ve "tükendi" kuyruğu.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc, getDocs, setDoc, collection } = require('firebase/firestore');
const { getStorage, connectStorageEmulator, ref: storageRef, uploadBytes } = require('firebase/storage');

const OWNER = { email: 'menu-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Menü Sahibi', pin: '482913' };
let owner;
let ownerId;

before(async () => {
  ownerId = createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
});
after(closeAll);

test('aktarım: boş menüye bir kez yapılır, fiyatlar kuruş olarak yazılır', async () => {
  const res = await owner.call('importMenu', {
    categories: [
      { localId: 1, name: 'Sıcak Kahveler', color: '#8D6E63', station: 'bar', stampEligible: true },
      { localId: 6, name: 'Kahvaltılar', color: '#FFA726', station: 'kitchen', stampEligible: false },
    ],
    products: [
      { localId: 2, localCategoryId: 1, name: 'Latte', price: 8500 },
      { localId: 3, localCategoryId: 1, name: 'Americano', price: 7500 },
      { localId: 20, localCategoryId: 6, name: 'Menemen', price: 11000 },
    ],
  });
  assert.equal(Object.keys(res.categories).length, 2);
  const latte = (await adminDb.doc(`products/${res.products['2']}`).get()).data();
  assert.equal(latte.price, 8500);
  assert.equal(latte.categoryId, res.categories['1']);
  assert.equal(latte.soldOut, false);
  await expectCallError(owner.call('importMenu', { categories: [{ localId: 1, name: 'X' }], products: [] }),
    'failed-precondition');
});

test('menü herkese açık okunur ama istemciden yazılamaz', async () => {
  const anon = client();
  const products = await getDocs(collection(anon.db, 'products'));
  assert.ok(products.size >= 3);
  await expectDenied(setDoc(doc(anon.db, 'products/x'), { name: 'Hack', price: 1 }));
  await expectDenied(setDoc(doc(owner.db, 'products/x'), { name: 'Hack', price: 1 }));
});

test('kategori, seçenek grubu ve ürün: oluşturma, fiyat değişikliği kaydı, silme kuralları', async () => {
  const { id: catId } = await owner.call('saveCategory', { name: 'Soğuk Kahveler', stampEligible: true });
  const { id: milkId } = await owner.call('saveOptionGroup', {
    name: 'Süt Seçimi', required: true,
    options: [{ id: 'normal', name: 'Normal süt', priceDelta: 0 }, { id: 'oat', name: 'Yulaf sütü', priceDelta: 1500 }],
  });
  const { id: pid } = await owner.call('saveProduct', {
    categoryId: catId, name: 'Ice Latte', price: 9000, optionGroupIds: [milkId], allergens: ['milk'],
    flavor: { strength: 3, sweetness: 2, acidity: 1, body: 3, milk: true, temperature: 'iced', notes: [] },
  });
  await owner.call('saveProduct', { id: pid, categoryId: catId, name: 'Ice Latte', price: 9500, optionGroupIds: [milkId] });
  const logs = await adminDb.collection('auditLogs').where('action', '==', 'price_change').get();
  const log = logs.docs.map((d) => d.data()).find((l) => l.target === `products/${pid}`);
  assert.deepEqual([log.before.price, log.after.price], [9000, 9500]);

  // Geçersiz fiyat (ondalık) ve olmayan kategori reddedilir.
  await expectCallError(owner.call('saveProduct', { categoryId: catId, name: 'X', price: 90.5 }), 'invalid-argument');
  await expectCallError(owner.call('saveProduct', { categoryId: 'yok', name: 'X', price: 100 }), 'not-found');

  // Kullanımdaki grup ve içi dolu kategori silinemez.
  await expectCallError(owner.call('deleteOptionGroup', { id: milkId }), 'failed-precondition');
  await expectCallError(owner.call('deleteCategory', { id: catId }), 'failed-precondition');
  await owner.call('deleteProduct', { id: pid });
  const deleted = (await adminDb.doc(`products/${pid}`).get()).data();
  assert.equal(deleted.deleted, true);
  assert.equal(deleted.name, 'Ice Latte'); // eski adisyonlar için kayıt durur
  await owner.call('deleteOptionGroup', { id: milkId });
  await owner.call('deleteCategory', { id: catId });
});

test('sıralama', async () => {
  const cats = (await adminDb.collection('categories').where('deleted', '==', false).get()).docs.map((d) => d.id);
  const reversed = [...cats].reverse();
  await owner.call('reorderMenu', { kind: 'categories', ids: reversed });
  const orders = await Promise.all(reversed.map((id) => adminDb.doc(`categories/${id}`).get()));
  assert.deepEqual(orders.map((s) => s.data().order), reversed.map((_, i) => i));
  await expectCallError(owner.call('reorderMenu', { kind: 'staff', ids: ['x'] }), 'invalid-argument');
});

test('toplu fiyat: önizleme yazmaz, uygulama tek audit kaydıyla yazar', async () => {
  const { id: catId } = await owner.call('saveCategory', { name: 'Zam Test' });
  const { id: syrup } = await owner.call('saveOptionGroup', {
    name: 'Şurup', selection: 'multi', options: [{ id: 'vanilla', name: 'Vanilya', priceDelta: 1000 }],
  });
  const { id: a } = await owner.call('saveProduct', { categoryId: catId, name: 'Mocha', price: 9500, optionGroupIds: [syrup] });
  const { id: b } = await owner.call('saveProduct', { categoryId: catId, name: 'Flat White', price: 10000 });
  const rule = { mode: 'percent', value: 12, rounding: 500 };

  const preview = await owner.call('bulkUpdatePrices', { categoryIds: [catId], rule, includeOptions: true, dryRun: true });
  assert.deepEqual(preview.products.map((c) => [c.name, c.before, c.after]), [['Flat White', 10000, 11500], ['Mocha', 9500, 11000]]);
  assert.deepEqual(preview.options.map((c) => [c.before, c.after]), [[1000, 1500]]);
  assert.equal((await adminDb.doc(`products/${a}`).get()).data().price, 9500);

  await owner.call('bulkUpdatePrices', { categoryIds: [catId], rule, includeOptions: true });
  assert.equal((await adminDb.doc(`products/${a}`).get()).data().price, 11000);
  assert.equal((await adminDb.doc(`products/${b}`).get()).data().price, 11500);
  assert.equal((await adminDb.doc(`optionGroups/${syrup}`).get()).data().options[0].priceDelta, 1500);
  const logs = await adminDb.collection('auditLogs').where('action', '==', 'bulk_price_update').get();
  assert.equal(logs.size, 1);
  assert.equal(logs.docs[0].data().count, 2);
});

test('yetki: editMenu kapalı müdür menüyü değiştiremez', async () => {
  await owner.call('manageStaff', {
    action: 'create', name: 'Menü Müdür', role: 'manager', email: 'menu-mudur@kafe.test',
    password: 'mudur-sifre-1', pin: '583920',
  });
  const manager = await signedInAs('menu-mudur@kafe.test', 'mudur-sifre-1');
  await manager.call('saveCategory', { name: 'Müdür Kategorisi' });
  await owner.call('savePermissions', { roles: { manager: { editMenu: false } } });
  await expectCallError(manager.call('saveCategory', { name: 'Yasak' }), 'permission-denied');
  await expectCallError(manager.call('bulkUpdatePrices', { categoryIds: ['x'], rule: { mode: 'percent', value: 1 } }),
    'permission-denied');
  await owner.call('savePermissions', { roles: {} });
});

test('tükendi: terminal kuyruğundan, yetkiye göre', async () => {
  const { id: catId } = await owner.call('saveCategory', { name: 'Tükendi Test' });
  const { id: milk } = await owner.call('saveOptionGroup', {
    name: 'Süt', options: [{ id: 'normal', name: 'Normal', priceDelta: 0 }, { id: 'oat', name: 'Yulaf', priceDelta: 1500 }],
  });
  const { id: pid } = await owner.call('saveProduct', { categoryId: catId, name: 'Cortado', price: 8000 });
  const { staffId: barista } = await owner.call('manageStaff', { action: 'create', name: 'Barista', role: 'barista', pin: '573920' });
  const { staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson', role: 'waiter', pin: '640218' });

  const reg = await owner.call('registerTerminal', { name: 'Menü Kasa' });
  const term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
  const at = new Date().toISOString();
  const { results } = await term.call('syncOps', { ops: [
    { opId: 'sold-0000001', op: 'setSoldOut', payload: { productId: pid, soldOut: true }, staffId: barista, createdAt: at },
    { opId: 'sold-0000002', op: 'setSoldOut', payload: { optionGroupId: milk, optionId: 'oat', soldOut: true }, staffId: barista, createdAt: at },
    { opId: 'sold-0000003', op: 'setSoldOut', payload: { productId: pid, soldOut: false }, staffId: waiter, createdAt: at },
    { opId: 'sold-0000004', op: 'setSoldOut', payload: { productId: 'yok', soldOut: true }, staffId: barista, createdAt: at },
  ] });
  assert.deepEqual(results.map((r) => r.status), ['ok', 'ok', 'rejected', 'rejected']);
  assert.match(results[2].error, /yetki/i);
  assert.equal((await adminDb.doc(`products/${pid}`).get()).data().soldOut, true);
  const oat = (await adminDb.doc(`optionGroups/${milk}`).get()).data().options.find((o) => o.id === 'oat');
  assert.equal(oat.soldOut, true);
});

test('fotoğraf: yönetici yükler, anonim yükleyemez', async () => {
  const png = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
  const ownerStorage = getStorage(owner.app, 'demo-nexpos.appspot.com');
  connectStorageEmulator(ownerStorage, '127.0.0.1', 9199);
  await uploadBytes(storageRef(ownerStorage, 'products/p1/a.png'), png, { contentType: 'image/png' });

  const anon = client();
  const anonStorage = getStorage(anon.app, 'demo-nexpos.appspot.com');
  connectStorageEmulator(anonStorage, '127.0.0.1', 9199);
  await expectDenied(uploadBytes(storageRef(anonStorage, 'products/p1/b.png'), png, { contentType: 'image/png' }));
  await expectDenied(uploadBytes(storageRef(ownerStorage, 'products/p1/c.txt'), png, { contentType: 'text/plain' }));
});
