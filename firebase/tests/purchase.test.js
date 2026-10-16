// Tedarik (8b): tedarikçi, sipariş, teslim alma (ağırlıklı maliyet), borç ve ödeme.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { adminDb, createOwner, client, signedInAs, expectDenied, expectCallError, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');
const { doc, getDoc } = require('firebase/firestore');

const OWNER = { email: 'tedarik-sahip@kafe.test', password: 'sahip-sifre-1', name: 'Tedarik Sahibi', pin: '482913' };
let owner;
let ownerId;
let term;
let cashier;
let esp;
let sut;
let supplier;
let poId;
let seq = 0;
const AT = '2026-10-16T10:00:00+03:00';

before(async () => {
  ownerId = createOwner(OWNER);
  owner = await signedInAs(OWNER.email, OWNER.password);
  ({ staffId: cashier } = await owner.call('manageStaff', { action: 'create', name: 'Kasiyer T', role: 'cashier', pin: '640218' }));
  ({ id: esp } = await owner.call('saveIngredient', { name: 'Tedarik Espresso', unit: 'g', unitCost: 80000 }));
  ({ id: sut } = await owner.call('saveIngredient', { name: 'Tedarik Süt', unit: 'ml', unitCost: 3500 }));
  await adminDb.doc(`ingredients/${esp}`).update({ stock: 1000 });
  const reg = await owner.call('registerTerminal', { name: 'Tedarik Kasa' });
  term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
});
after(async () => {
  await Promise.all([adminDb.doc(`ingredients/${esp}`).delete(), adminDb.doc(`ingredients/${sut}`).delete()]);
  await closeAll();
});

const op = (name, payload, staffId = ownerId) => ({ opId: `pur-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId, createdAt: AT });
const sync = async (...ops) => (await term.call('syncOps', { ops })).results;
const data = async (path) => (await adminDb.doc(path).get()).data();

test('tedarikçi ve sipariş: numara sırayla, düzenleme, iptal', async () => {
  ({ id: supplier } = await owner.call('saveSupplier', { name: 'Kahveci', phone: '0532 000 00 00' }));
  assert.equal((await data(`suppliers/${supplier}`)).balance, 0);
  const a = await owner.call('savePurchaseOrder', { supplierId: supplier, lines: [{ ingredientId: esp, qty: 2000, amount: 160000 }] });
  const b = await owner.call('savePurchaseOrder', { supplierId: supplier, lines: [{ ingredientId: sut, qty: 12000, amount: 42000 }] });
  assert.equal(b.no, a.no + 1);
  await owner.call('savePurchaseOrder', { id: a.id, supplierId: supplier, status: 'sent',
    lines: [{ ingredientId: esp, qty: 3000, amount: 240000 }, { ingredientId: sut, qty: 6000, amount: 21000 }] });
  const po = await data(`purchaseOrders/${a.id}`);
  assert.deepEqual([po.status, po.total, po.no], ['sent', 261000, a.no]);
  await owner.call('cancelPurchaseOrder', { id: b.id });
  await expectCallError(owner.call('savePurchaseOrder', { id: b.id, supplierId: supplier,
    lines: [{ ingredientId: sut, qty: 1, amount: 1 }] }), 'failed-precondition');
  await expectCallError(owner.call('savePurchaseOrder', { supplierId: supplier, lines: [] }), 'invalid-argument');
  poId = a.id;
});

test('teslim alma: kısmi teslim, ağırlıklı maliyet, borç, yetki ve tekrar koruması', async () => {
  // Kasiyerin stok yetkisi yok
  const [denied] = await sync(op('receivePurchase', { receiptId: 'R0', supplierId: supplier,
    lines: [{ ingredientId: esp, qty: 1, amount: 1 }], payment: { status: 'unpaid' } }, cashier));
  assert.match(denied.error, /stock/);
  // Kısmi: 2 kg espresso (1.900 ₺), süt gelmedi; ödenecek
  const first = op('receivePurchase', { receiptId: 'R1', supplierId: supplier, purchaseOrderId: poId,
    lines: [{ ingredientId: esp, qty: 2000, amount: 190000 }, { ingredientId: sut, qty: 0, amount: 0 }],
    payment: { status: 'unpaid' }, note: 'İrsaliye 5' });
  let r = await sync(first);
  assert.equal(r[0].status, 'ok');
  let e = await data(`ingredients/${esp}`);
  assert.deepEqual([e.stock, e.unitCost], [3000, 90000]);   // (1 kg × 800 + 1.900) / 3 kg
  let po = await data(`purchaseOrders/${poId}`);
  assert.deepEqual([po.status, po.lines[0].received, po.lines[1].received], ['partial', 2000, 0]);
  assert.equal((await data(`suppliers/${supplier}`)).balance, 190000);
  r = await sync(first);
  assert.equal(r[0].status, 'duplicate');
  assert.equal((await data(`ingredients/${esp}`)).stock, 3000);
  // Kalanı: 1 kg espresso + 6 L süt; ödendi (kart) → borç değişmez, sipariş tamamlanır
  r = await sync(op('receivePurchase', { receiptId: 'R2', supplierId: supplier, purchaseOrderId: poId,
    lines: [{ ingredientId: esp, qty: 1000, amount: 90000 }, { ingredientId: sut, qty: 6000, amount: 21000 }],
    payment: { status: 'paid', method: 'card' } }));
  assert.equal(r[0].status, 'ok');
  po = await data(`purchaseOrders/${poId}`);
  assert.equal(po.status, 'received');
  e = await data(`ingredients/${sut}`);
  assert.deepEqual([e.stock, e.unitCost], [6000, 3500]);
  assert.equal((await data(`suppliers/${supplier}`)).balance, 190000);
  const mv = await data('stockMovements/R2');
  assert.deepEqual([mv.type, mv.applied.length], ['purchase', 2]);
  const receipt = await data('purchaseReceipts/R1');
  assert.deepEqual([receipt.total, receipt.lines.length, receipt.note], [190000, 1, 'İrsaliye 5']);
  // Geçersiz: ödendi ama yöntem yok
  r = await sync(op('receivePurchase', { receiptId: 'R3', supplierId: supplier,
    lines: [{ ingredientId: esp, qty: 1, amount: 1 }], payment: { status: 'paid' } }));
  assert.equal(r[0].status, 'rejected');
});

test('tedarikçi ödemesi borcu düşürür; borçlu tedarikçi silinemez; kurallar', async () => {
  let [r] = await sync(op('supplierPayment', { paymentId: 'SP1', supplierId: supplier, amount: 100000, method: 'transfer' }));
  assert.equal(r.status, 'ok');
  assert.equal((await data(`suppliers/${supplier}`)).balance, 90000);
  [r] = await sync(op('supplierPayment', { paymentId: 'SP2', supplierId: supplier, amount: 0, method: 'cash' }));
  assert.equal(r.status, 'rejected');
  await expectCallError(owner.call('deleteSupplier', { id: supplier }), 'failed-precondition');
  assert.ok((await getDoc(doc(term.db, `suppliers/${supplier}`))).exists());
  assert.ok((await getDoc(doc(owner.db, 'purchaseReceipts/R1'))).exists());
  await expectDenied(getDoc(doc(client().db, `suppliers/${supplier}`)));
  await sync(op('supplierPayment', { paymentId: 'SP3', supplierId: supplier, amount: 90000, method: 'cash' }));
  await owner.call('deleteSupplier', { id: supplier });
  assert.equal((await data(`suppliers/${supplier}`)).deleted, true);
});
