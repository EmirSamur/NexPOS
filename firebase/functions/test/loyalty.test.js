// Sadakat kuralları: test/loyalty_vectors.json (aynı dosya Python tarafında da çalışır).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const L = require('../src/loyalty');

const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'loyalty_vectors.json'), 'utf8'));

for (const c of cases) {
  test(c.name, () => {
    if (c.error) {
      assert.throws(() => L[c.fn](...c.args), (e) => e instanceof L.LoyaltyError && e.message.includes(c.error));
      return;
    }
    assert.deepEqual(L[c.fn](...c.args), c.expect);
  });
}
