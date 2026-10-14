// Salon planı (3. ekran): bölgeler, plan kaydetme (çakışma dahil), QR, aktarım, ayarlar.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc, getDocs, setDoc, collection } = require('firebase/firestore');

const OWNER = { email: 'salon-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Salon Sahibi', pin: '482913' };
let owner;

before(async () => {
  createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
});
after(closeAll);

const table = (o) => ({ shape: 'square', capacity: 4, x: 60, y: 60, w: 120, h: 120, ...o });

test('aktarım: boş plana bir kez, ızgara düzeninde, QR anahtarlı', async () => {
  const res = await owner.call('importFloor', { areas: [
    { localId: 1, name: 'Salon', tables: [{ localId: 1, name: 'Masa 1' }, { localId: 2, name: 'Masa 2' }] },
    { localId: 2, name: 'Teras', tables: [{ localId: 9, name: 'Masa 9' }] },
  ] });
  assert.equal(Object.keys(res.tables).length, 3);
  const m2 = (await adminDb.doc(`tables/${res.tables['2']}`).get()).data();
  assert.equal(m2.areaId, res.areas['1']);
  assert.deepEqual([m2.x, m2.y], [240, 60]);
  assert.match(m2.qrToken, /^[A-Za-z0-9_-]{16}$/);
  await expectCallError(owner.call('importFloor', { areas: [{ localId: 3, name: 'X', tables: [] }] }), 'failed-precondition');
});

test('plan: masalar ve qrToken herkese açık değil; personel ve terminal okur', async () => {
  const anon = client();
  await expectDenied(getDocs(collection(anon.db, 'tables')));
  await expectDenied(getDocs(collection(anon.db, 'areas')));
  const t = await getDocs(collection(owner.db, 'tables'));
  assert.ok(t.size >= 3);
  await expectDenied(setDoc(doc(owner.db, 'tables/x'), { name: 'Hack' }));
});

test('saveFloorPlan: ekle, güncelle, sil, dekor; sürüm çakışması', async () => {
  const { id: areaId } = await owner.call('saveArea', { name: 'Bahçe' });
  const r1 = await owner.call('saveFloorPlan', {
    areaId, expectedVersion: 0,
    tables: [table({ tempId: 'a', name: 'B1' }), table({ tempId: 'b', name: 'B2', x: 300, shape: 'round', capacity: 2 })],
    fixtures: [{ id: 'f1', kind: 'plant', x: 1000, y: 600, w: 60, h: 60 }],
  });
  assert.equal(r1.layoutVersion, 1);
  const b1 = r1.created.a;
  const b2 = r1.created.b;

  // B1 taşınır, B2 açıkça silinir, B3 eklenir
  const r2 = await owner.call('saveFloorPlan', {
    areaId, expectedVersion: 1, removedTableIds: [b2],
    tables: [table({ id: b1, name: 'B1', x: 500, rotation: 90, shape: 'rect', w: 200, capacity: 6 }), table({ tempId: 'c', name: 'B3' })],
    fixtures: [],
  });
  assert.deepEqual(r2.removed, [b2]);
  const moved = (await adminDb.doc(`tables/${b1}`).get()).data();
  assert.deepEqual([moved.x, moved.rotation, moved.shape, moved.capacity], [500, 90, 'rect', 6]);
  assert.equal((await adminDb.doc(`tables/${b2}`).get()).data().deleted, true);
  assert.equal((await adminDb.doc(`areas/${areaId}`).get()).data().fixtures.length, 0);

  // Listede adı geçmeyen masaya dokunulmaz (eksik önbellekle kaydetmek masa silmez)
  await owner.call('saveFloorPlan', { areaId, expectedVersion: 2, tables: [], fixtures: [] });
  assert.equal((await adminDb.doc(`tables/${b1}`).get()).data().deleted, false);
  // Dokunulmayan masayla aynı adı taşıyan yeni masa reddedilir
  await expectCallError(owner.call('saveFloorPlan', {
    areaId, expectedVersion: 3, tables: [table({ tempId: 'd', name: 'b1' })], fixtures: [] }), 'invalid-argument');

  // Eski sürümle kaydetmeye çalışan ikinci kişi reddedilir
  await expectCallError(owner.call('saveFloorPlan', { areaId, expectedVersion: 1, tables: [], fixtures: [] }), 'aborted');
  // Başka bölgenin masası bu bölgeye yazılamaz
  const other = (await adminDb.collection('tables').where('name', '==', 'Masa 1').get()).docs[0].id;
  await expectCallError(owner.call('saveFloorPlan', {
    areaId, expectedVersion: 3, tables: [table({ id: other, name: 'Masa 1' })], fixtures: [] }), 'not-found');
  await expectCallError(owner.call('saveFloorPlan', {
    areaId, expectedVersion: 3, tables: [], removedTableIds: [other], fixtures: [] }), 'not-found');
  await expectCallError(owner.call('saveFloorPlan', {
    areaId, expectedVersion: 3, tables: [table({ tempId: 'x', name: 'Y', x: 5000 })], fixtures: [] }), 'invalid-argument');
});

test('QR yenileme eski anahtarı değiştirir', async () => {
  const t = (await adminDb.collection('tables').where('name', '==', 'Masa 1').get()).docs[0];
  const old = t.data().qrToken;
  await owner.call('rotateTableQr', { tableIds: [t.id] });
  const now = (await t.ref.get()).data().qrToken;
  assert.notEqual(now, old);
  const logs = await adminDb.collection('auditLogs').where('action', '==', 'table_qr_rotate').get();
  assert.ok(logs.size >= 1);
});

test('bölge silme masaları da siler; bölgeler sıralanır', async () => {
  const { id: areaId } = await owner.call('saveArea', { name: 'Geçici' });
  const r = await owner.call('saveFloorPlan', { areaId, expectedVersion: 0, tables: [table({ tempId: 'z', name: 'G1' })], fixtures: [] });
  await owner.call('deleteArea', { id: areaId });
  assert.equal((await adminDb.doc(`tables/${r.created.z}`).get()).data().deleted, true);
  const areas = (await adminDb.collection('areas').where('deleted', '==', false).get()).docs.map((d) => d.id);
  await owner.call('reorderMenu', { kind: 'areas', ids: [...areas].reverse() });
  assert.equal((await adminDb.doc(`areas/${areas[0]}`).get()).data().order, areas.length - 1);
});

test('genel ayarlar: yalnızca settings yetkisi; terminal okur', async () => {
  const saved = await owner.call('saveGeneralSettings', { cafeName: 'Velvet Kafe', qrBaseUrl: 'https://velvet.web.app/masa' });
  assert.equal(saved.cafeName, 'Velvet Kafe');
  await owner.call('manageStaff', { action: 'create', name: 'Salon Müdür', role: 'manager', email: 'salon-mudur@kafe.test',
    password: 'mudur-sifre-1', pin: '583920' });
  const manager = await signedInAs('salon-mudur@kafe.test', 'mudur-sifre-1');
  await expectCallError(manager.call('saveGeneralSettings', { cafeName: 'X', qrBaseUrl: 'https://x.web.app' }), 'permission-denied');
  // Müdür planı düzenleyebilir (editMenu), terminal plan ve ayarları okur
  await manager.call('saveArea', { name: 'Müdür Bölgesi' });
  const reg = await owner.call('registerTerminal', { name: 'Salon Kasa' });
  const term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
  assert.ok((await getDocs(collection(term.db, 'tables'))).size >= 1);
  assert.equal((await getDoc(doc(term.db, 'settings/general'))).data().cafeName, 'Velvet Kafe');
});
