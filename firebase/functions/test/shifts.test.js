// Vardiya/mesai hesapları: test/shift_vectors.json (aynı dosya Python tarafında da çalışır).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const s = require('../src/shifts');
const { cases, overtime } = require('./shift_vectors.json');

for (const c of cases) {
  test(c.name, () => {
    const e = c.expect;
    if ('planned' in e) assert.equal(s.plannedMinutes(c.plan), e.planned);
    if ('late' in e) assert.equal(s.lateMinutes(c.plan, c.entry?.clockIn, c.tolerance), e.late);
    if ('break' in e) assert.equal(s.breakMinutes(c.entry, c.plan), e.break);
    if ('worked' in e) assert.equal(s.workedMinutes(c.entry, c.plan), e.worked);
    if ('businessDay' in e) assert.equal(s.businessDayOf(c.entry.clockIn), e.businessDay);
  });
}

test('haftalık fazla mesai (45 saat)', () => {
  for (const [worked, expected] of overtime) assert.equal(s.overtimeMinutes(worked), expected);
});
