// Kahve önerisi: test/quiz_vectors.json (aynı dosya Dart tarafında da çalışır) ve soru doğrulama.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const Q = require('../src/quiz');

const V = JSON.parse(fs.readFileSync(path.join(__dirname, 'quiz_vectors.json'), 'utf8'));

for (const c of V.cases) {
  test(c.name, () => {
    const pool = V.products.filter((p) => !c.without.includes(p.id));
    assert.deepEqual(Q.profileFrom(V.quiz, c.answers), c.profile);
    assert.deepEqual(Q.recommend(pool, V.quiz, c.answers, c.ctx), c.expect);
  });
}

test('hazır sorular geçerli; doğrulama kimlik, ağırlık ve süzgeci denetler', () => {
  assert.deepEqual(Q.validateQuiz(Q.DEFAULT_QUIZ), Q.DEFAULT_QUIZ);
  const q = (answers, extra = {}) => ({ questions: [{ id: 'q1', text: 'Soru?', answers, ...extra }] });
  const ok = [{ id: 'a', text: 'A' }, { id: 'b', text: 'B' }];
  assert.throws(() => Q.validateQuiz({ questions: [] }), /1-6 soru/);
  assert.throws(() => Q.validateQuiz(q([{ id: 'a', text: 'A' }])), /2-5 cevap/);
  assert.throws(() => Q.validateQuiz(q([{ id: 'a', text: 'A' }, { id: 'a', text: 'B' }])), /benzersiz/);
  assert.throws(() => Q.validateQuiz(q([{ id: 'a', text: 'A', weights: { bitterness: 1 } }, ok[1]])), /Bilinmeyen tat/);
  assert.throws(() => Q.validateQuiz(q([{ id: 'a', text: 'A', weights: { strength: 4 } }, ok[1]])), /-3 ile \+3/);
  assert.throws(() => Q.validateQuiz(q([{ id: 'a', text: 'A', filter: { temperature: 'warm' } }, ok[1]])), /Sıcaklık/);
  assert.throws(() => Q.validateQuiz(q(ok, { id: 'Büyük Harf' })), /kimliği/);
  const v = Q.validateQuiz(q([{ id: 'a', text: ' Çikolata ', weights: { sweetness: 1, body: 0 }, notes: ['Çikolata', 'çikolata'] }, ok[1]]));
  assert.deepEqual(v.questions[0].answers[0], { id: 'a', text: 'Çikolata', weights: { sweetness: 1 }, notes: ['çikolata'] });
  assert.equal(Q.normalizeQuiz({ questions: 'bozuk' }), Q.DEFAULT_QUIZ);
});
