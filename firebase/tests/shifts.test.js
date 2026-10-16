// Vardiya ve mesai (9. ekran): plan kaydet/yayınla, mesai (kuyruktan), düzeltme, ücretler ve kurallar.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc } = require('firebase/firestore');

const OWNER = { email: 'vardiya-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Vardiya Sahibi', pin: '482915' };
const MANAGER = { email: 'vardiya-mudur@kafe.test', password: 'mudur-sifre-1' };
let owner;
let ownerId;
let manager;
let managerId;
let waiter;
let waiter2;
let term;
let seq = 0;
const AT = '2026-10-16T10:00:00+03:00';

before(async () => {
  ownerId = createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  ({ staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson V', role: 'waiter', pin: '640219' }));
  ({ staffId: waiter2 } = await owner.call('manageStaff', { action: 'create', name: 'Garson W', role: 'waiter', pin: '640231' }));
  ({ staffId: managerId } = await owner.call('manageStaff', { action: 'create', name: 'Müdür V', role: 'manager', pin: '640227',
    email: MANAGER.email, password: MANAGER.password }));
  manager = await signedInAs(MANAGER.email, MANAGER.password);
  const reg = await owner.call('registerTerminal', { name: 'Vardiya Kasa' });
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(closeAll);

const op = (name, payload, staffId) => ({ opId: `shf-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId, createdAt: AT });
const sync = async (...ops) => (await term.call('syncOps', { ops })).results;
const data = async (path) => (await adminDb.doc(path).get()).data();

test('plan: kaydet (taslak), boşalt, yayınla; yetki ve doğrulama', async () => {
  const cells = [
    { staffId: waiter, date: '2026-10-12', start: '09:00', end: '17:00', breakMinutes: 30, note: 'Açılış' },
    { staffId: waiter, date: '2026-10-13', start: '16:00', end: '01:00', breakMinutes: 0 },
    { staffId: waiter, date: '2026-10-14', leave: 'sick' },
    { staffId: waiter2, date: '2026-10-12', start: '08:00', end: '16:00' },
  ];
  assert.deepEqual(await manager.call('saveShiftPlans', { cells }), { saved: 4 });
  let p = await data(`shiftPlans/${waiter}_2026-10-12`);
  assert.deepEqual([p.start, p.end, p.breakMinutes, p.note, p.published, p.deleted], ['09:00', '17:00', 30, 'Açılış', false, false]);
  p = await data(`shiftPlans/${waiter}_2026-10-14`);
  assert.deepEqual([p.leave, p.start], ['sick', null]);
  await manager.call('saveShiftPlans', { cells: [{ staffId: waiter2, date: '2026-10-12', clear: true }] });
  assert.equal((await data(`shiftPlans/${waiter2}_2026-10-12`)).deleted, true);
  assert.deepEqual(await manager.call('publishShiftWeek', { weekStart: '2026-10-12' }), { published: 4 });
  assert.equal((await data(`shiftPlans/${waiter}_2026-10-13`)).published, true);
  await expectCallError(manager.call('saveShiftPlans', { cells: [{ staffId: waiter, date: '2026-10-15', start: '9', end: '17:00' }] }),
    'invalid-argument');
  await expectCallError(manager.call('saveShiftPlans', { cells: [{ staffId: waiter, date: '2026-10-15', leave: 'tatil' }] }),
    'invalid-argument');
  await expectCallError(manager.call('saveShiftPlans', { cells: [] }), 'invalid-argument');
  // Terminal ve personel planı okur; oturumsuz okuyamaz
  assert.ok((await getDoc(doc(term.db, `shiftPlans/${waiter}_2026-10-12`))).exists());
  await expectDenied(getDoc(doc(client().db, `shiftPlans/${waiter}_2026-10-12`)));
});

test('mesai: giriş (geç), mola, çıkış kuyruktan; tekrar ve başkasının kaydı', async () => {
  const id = 'TEv1';
  const r = await sync(
    op('timeClock', { entryId: id, action: 'in', at: '2026-10-12T09:12:00+03:00' }, waiter),
    op('timeClock', { entryId: id, action: 'breakStart', at: '2026-10-12T12:00:00+03:00' }, waiter),
    op('timeClock', { entryId: id, action: 'breakEnd', at: '2026-10-12T12:25:00+03:00' }, waiter),
  );
  assert.deepEqual(r.map((x) => x.status), ['ok', 'ok', 'ok']);
  let e = await data(`timeEntries/${id}`);
  assert.deepEqual([e.businessDay, e.late, e.breaks.length, e.clockOut], ['2026-10-12', 12, 1, null]);
  // Başkası bu kaydı kapatamaz; molada değilken moladan dönülemez
  let [x] = await sync(op('timeClock', { entryId: id, action: 'out', at: '2026-10-12T17:00:00+03:00' }, waiter2));
  assert.equal(x.status, 'rejected');
  [x] = await sync(op('timeClock', { entryId: id, action: 'breakEnd', at: '2026-10-12T13:00:00+03:00' }, waiter));
  assert.equal(x.status, 'rejected');
  // Gece yarısını geçen vardiya, tolerans içinde: geç değil; unutulan çıkış otomatik kapanır
  const out = op('timeClock', { entryId: id, action: 'out', at: '2026-10-12T17:05:00+03:00' }, waiter);
  [x] = await sync(out);
  assert.equal(x.status, 'ok');
  [x] = await sync(out);
  assert.equal(x.status, 'duplicate');
  [x] = await sync(op('timeClock', { entryId: id, action: 'breakStart', at: '2026-10-12T18:00:00+03:00' }, waiter));
  assert.equal(x.status, 'rejected');
  e = await data(`timeEntries/${id}`);
  assert.deepEqual([e.clockOut, e.flags], ['2026-10-12T17:05:00+03:00', []]);
  const r2 = await sync(
    op('timeClock', { entryId: 'TEv2', action: 'in', at: '2026-10-13T16:04:00+03:00' }, waiter),
    op('timeClock', { entryId: 'TEv2', action: 'out', at: '2026-10-14T01:00:00+03:00', auto: true }, waiter),
  );
  assert.deepEqual(r2.map((y) => y.status), ['ok', 'ok']);
  e = await data('timeEntries/TEv2');
  assert.deepEqual([e.late, e.businessDay, e.flags], [0, '2026-10-13', ['forgotClockOut']]);
  [x] = await sync(op('timeClock', { entryId: 'bad id!', action: 'in', at: AT }, waiter));
  assert.equal(x.status, 'rejected');
});

test('düzeltme: shifts yetkisi ve gerekçe; eski/yeni değer denetim kaydında', async () => {
  const fix = (approvedBy, reason, staffId = waiter) => op('timeEdit', { entryId: 'TEv2', staffId,
    clockIn: '2026-10-13T16:04:00+03:00', clockOut: '2026-10-14T00:30:00+03:00', breaks: [], reason, approvedBy }, waiter);
  let [x] = await sync(fix(undefined, 'Kapanış'));
  assert.match(x.error, /shifts/);
  [x] = await sync(fix(managerId, '  '));
  assert.equal(x.status, 'rejected');
  [x] = await sync(fix(managerId, 'Kapanışta erken çıktı', waiter2));
  assert.equal(x.status, 'rejected');
  [x] = await sync(fix(managerId, 'Kapanışta erken çıktı'));
  assert.equal(x.status, 'ok');
  const e = await data('timeEntries/TEv2');
  assert.deepEqual([e.clockOut, e.resolved, e.editedBy, e.flags.sort()], ['2026-10-14T00:30:00+03:00', true, managerId,
    ['edited', 'forgotClockOut']]);
  const logs = await adminDb.collection('auditLogs').where('action', '==', 'time_edit').get();
  const log = logs.docs.map((d) => d.data()).find((l) => l.target === 'timeEntries/TEv2');
  assert.deepEqual([log.before.clockOut, log.after.clockOut, log.reason], ['2026-10-14T01:00:00+03:00',
    '2026-10-14T00:30:00+03:00', 'Kapanışta erken çıktı']);
  // Eksik kayıt (gelmiş ama başlatmamış) yetkiliyle açılır
  [x] = await sync(op('timeEdit', { entryId: 'TEv3', staffId: waiter2, clockIn: '2026-10-15T08:00:00+03:00',
    clockOut: '2026-10-15T16:00:00+03:00', reason: 'Giriş unutuldu' }, managerId));
  assert.equal(x.status, 'ok');
  // Mesai kayıtlarını terminal ve müdür okur, garson (oturumla) okuyamaz
  assert.ok((await getDoc(doc(manager.db, 'timeEntries/TEv3'))).exists());
  assert.ok((await getDoc(doc(term.db, 'timeEntries/TEv3'))).exists());
});

test('saatlik ücret: yalnızca yönetici yazar ve okur', async () => {
  await expectCallError(manager.call('saveWages', { wages: { [waiter]: 15000 } }), 'permission-denied');
  await expectCallError(owner.call('saveWages', { wages: { [waiter]: 150.5 } }), 'invalid-argument');
  await owner.call('saveWages', { wages: { [waiter]: 15000, [waiter2]: null } });
  assert.equal((await data(`staffWages/${waiter}`)).hourlyRate, 15000);
  assert.equal((await getDoc(doc(owner.db, `staffWages/${waiter}`))).data().hourlyRate, 15000);
  await expectDenied(getDoc(doc(manager.db, `staffWages/${waiter}`)));
  await expectDenied(getDoc(doc(term.db, `staffWages/${waiter}`)));
  assert.ok(ownerId);
});
