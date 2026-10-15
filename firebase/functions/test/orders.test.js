// Sipariş mantığı: test/order_vectors.json senaryoları (aynı dosya Python tarafında da çalışır).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { applyOrderOp, mergeOrders, tableStatusFor, stampCount, OrderError } = require('../src/orders');

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'order_vectors.json'), 'utf8'));

function run(steps) {
  const orders = {};
  for (const s of steps) {
    const ctx = { staffId: s.staffId, at: s.at };
    if (s.op === 'mergeOrders') {
      const [t, src] = mergeOrders(orders[s.payload.orderId], orders[s.payload.sourceOrderId], ctx);
      orders[t.id] = t;
      orders[src.id] = src;
    } else {
      const id = s.payload.orderId;
      orders[id] = applyOrderOp(orders[id] || null, s.op, s.payload, ctx);
    }
  }
  return orders;
}

for (const c of cases) {
  test(c.name, () => {
    if (c.expectError) {
      assert.throws(() => run(c.steps), (e) => e instanceof OrderError && e.message.includes(c.expectError));
      return;
    }
    const orders = run(c.steps);
    for (const [id, fields] of Object.entries(c.expect || {})) {
      for (const [k, v] of Object.entries(fields)) assert.deepEqual(orders[id][k], v, `${id}.${k}`);
    }
    for (const [id, lines] of Object.entries(c.expectLines || {})) {
      assert.equal(orders[id].items.length, lines.length);
      lines.forEach((exp, i) => {
        for (const [k, v] of Object.entries(exp)) assert.deepEqual(orders[id].items[i][k], v, `${id}.items[${i}].${k}`);
      });
    }
    for (const [id, pays] of Object.entries(c.expectPayments || {})) {
      pays.forEach((exp, i) => {
        for (const [k, v] of Object.entries(exp)) assert.deepEqual(orders[id].payments[i][k], v);
      });
    }
    for (const [id, st] of Object.entries(c.expectTableStatus || {})) assert.equal(tableStatusFor(orders[id]), st);
  });
}

test('damga sayısı: yalnızca aktif ve damga kazandıran satırlar', () => {
  const ctx = { staffId: 's1', at: 'x' };
  let o = applyOrderOp(null, 'openOrder', { orderId: 'o', no: 'A1', businessDay: 'd', type: 'takeaway' }, ctx);
  o = applyOrderOp(o, 'addItems', { orderId: 'o', items: [
    { lineId: 'a', name: 'Latte', unitPrice: 1, qty: 2, station: 'bar', stampEligible: true },
    { lineId: 'b', name: 'Kek', unitPrice: 1, qty: 1, station: 'kitchen', stampEligible: false },
    { lineId: 'c', name: 'Mocha', unitPrice: 1, qty: 1, station: 'bar', stampEligible: true },
  ] }, ctx);
  o = applyOrderOp(o, 'sendItems', { orderId: 'o', lineIds: ['a', 'b', 'c'], ticketIds: { bar: 't1', kitchen: 't2' } }, ctx);
  o = applyOrderOp(o, 'voidItem', { orderId: 'o', lineId: 'c', reason: 'x' }, ctx);
  assert.equal(stampCount(o), 2);
});
