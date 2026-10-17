// Kahve önerisi (11c): "Bana öner" soruları ve kural tabanlı eşleştirme (yapay zekâ yok).
//
// Müşteri uygulaması aynı hesabı Dart'ta (mobile/lib/quiz.dart) internetsiz yapar; ikisi de
// test/quiz_vectors.json'daki ortak senaryolarla test edilir.
//
// Cevaplar bir hedef tat profili kurar (sertlik, tatlılık, asidite, gövde: 1–5; başlangıç 3), nota ekler
// ve süzgeç koyar (sütlü mü, sıcak mı soğuk mu). Tat profili girilmiş, tükenmemiş ürünler profile yakınlığına
// göre puanlanır; bağlam artıları: akşam (17:00 sonrası) kafeinsiz, sıcak günde soğuk, hiç denenmemiş ürün.

class QuizError extends Error {}

const DIMS = ['strength', 'sweetness', 'acidity', 'body'];

const DEFAULT_QUIZ = {
  questions: [
    { id: 'mood', text: 'Bugün nasıl hissediyorsun?', answers: [
      { id: 'sleepy', text: 'Uykuluyum 😴', weights: { strength: 2, body: 1 } },
      { id: 'happy', text: 'Keyifliyim 🙂', weights: { sweetness: 1 } },
      { id: 'calm', text: 'Sakin bir şey', weights: { strength: -2 } },
    ] },
    { id: 'milk', text: 'Sütlü mü?', answers: [
      { id: 'yes', text: 'Evet', filter: { milk: true } },
      { id: 'no', text: 'Hayır', filter: { milk: false } },
      { id: 'any', text: 'Fark etmez' },
    ] },
    { id: 'temp', text: 'Sıcak mı soğuk mu?', answers: [
      { id: 'hot', text: 'Sıcak ☕', filter: { temperature: 'hot' } },
      { id: 'iced', text: 'Buz gibi 🧊', filter: { temperature: 'iced' } },
    ] },
    { id: 'taste', text: 'Hangisi sana yakın?', answers: [
      { id: 'choc', text: 'Çikolata 🍫', weights: { sweetness: 1, body: 1 }, notes: ['çikolata'] },
      { id: 'fruit', text: 'Meyvemsi 🍓', weights: { acidity: 2 }, notes: ['meyvemsi'] },
      { id: 'nut', text: 'Fındık 🌰', weights: { body: 1 }, notes: ['fındık', 'karamel'] },
      { id: 'plain', text: 'Sade', weights: { sweetness: -1 } },
    ] },
  ],
};

const fail = (m) => {
  throw new QuizError(m);
};
const text = (v, field, max) => {
  if (typeof v !== 'string' || !v.trim() || v.length > max) fail(`${field} 1-${max} karakter olmalıdır.`);
  return v.trim();
};
const slug = (v, field) => {
  if (typeof v !== 'string' || !/^[a-z0-9_-]{1,24}$/.test(v)) fail(`${field} kimliği geçersiz.`);
  return v;
};

function validateAnswer(a) {
  const out = { id: slug(a?.id, 'Cevap'), text: text(a.text, 'Cevap', 40) };
  if (a.weights !== undefined && a.weights !== null) {
    if (typeof a.weights !== 'object' || Array.isArray(a.weights)) fail('Ağırlıklar geçersiz.');
    const w = {};
    for (const [k, v] of Object.entries(a.weights)) {
      if (!DIMS.includes(k)) fail(`Bilinmeyen tat: ${k}`);
      if (!Number.isInteger(v) || v < -3 || v > 3) fail('Ağırlık -3 ile +3 arası olmalıdır.');
      if (v) w[k] = v;
    }
    if (Object.keys(w).length) out.weights = w;
  }
  if (a.notes !== undefined && a.notes !== null) {
    if (!Array.isArray(a.notes) || a.notes.length > 4) fail('Notalar en fazla 4 olabilir.');
    const notes = a.notes.map((n) => text(n, 'Nota', 24).toLocaleLowerCase('tr'));
    if (notes.length) out.notes = [...new Set(notes)];
  }
  if (a.filter !== undefined && a.filter !== null) {
    const f = {};
    if (a.filter.milk !== undefined) {
      if (typeof a.filter.milk !== 'boolean') fail('Süt süzgeci evet/hayır olmalıdır.');
      f.milk = a.filter.milk;
    }
    if (a.filter.temperature !== undefined) {
      if (!['hot', 'iced'].includes(a.filter.temperature)) fail('Sıcaklık süzgeci sıcak ya da soğuk olmalıdır.');
      f.temperature = a.filter.temperature;
    }
    if (Object.keys(f).length) out.filter = f;
  }
  return out;
}

function validateQuiz(input) {
  const qs = input?.questions;
  if (!Array.isArray(qs) || qs.length < 1 || qs.length > 6) fail('1-6 soru olmalıdır.');
  const ids = new Set();
  return {
    questions: qs.map((q) => {
      const id = slug(q?.id, 'Soru');
      if (ids.has(id)) fail('Soru kimlikleri benzersiz olmalıdır.');
      ids.add(id);
      if (!Array.isArray(q.answers) || q.answers.length < 2 || q.answers.length > 5) fail('Her soruda 2-5 cevap olmalıdır.');
      const aids = new Set();
      const answers = q.answers.map((a) => {
        const v = validateAnswer(a);
        if (aids.has(v.id)) fail('Cevap kimlikleri benzersiz olmalıdır.');
        aids.add(v.id);
        return v;
      });
      return { id, text: text(q.text, 'Soru', 80), answers };
    }),
  };
}

function normalizeQuiz(stored) {
  try {
    return stored && stored.questions ? validateQuiz(stored) : DEFAULT_QUIZ;
  } catch {
    return DEFAULT_QUIZ;
  }
}

// answers: { soruId: cevapId } → { target: {strength..}, notes: [], filter: {} }
function profileFrom(quiz, answers) {
  const target = { strength: 3, sweetness: 3, acidity: 3, body: 3 };
  const notes = [];
  const filter = {};
  for (const q of quiz.questions) {
    const a = q.answers.find((x) => x.id === (answers || {})[q.id]);
    if (!a) continue;
    for (const [k, v] of Object.entries(a.weights || {})) target[k] = Math.min(5, Math.max(1, target[k] + v));
    for (const n of a.notes || []) if (!notes.includes(n)) notes.push(n);
    Object.assign(filter, a.filter || {});
  }
  return { target, notes, filter };
}

// products: [{ id, name, flavor, soldOut, caffeineMg }]; ctx: { hour, hotDay, triedIds }
// → [{ productId, score (0–100), reasons: [] }] en fazla 3
function recommend(products, quiz, answers, ctx = {}) {
  const { target, notes, filter } = profileFrom(quiz, answers);
  const usable = products.filter((p) => p.flavor && p.soldOut !== true);
  const passes = (p) => (filter.milk === undefined || p.flavor.milk === filter.milk)
    && (filter.temperature === undefined || p.flavor.temperature === filter.temperature);
  let pool = usable.filter(passes);
  // Süzgece uyan yoksa önce sıcaklık, sonra süt gevşetilir (boş sonuç yerine en yakın öneri)
  if (!pool.length && filter.temperature !== undefined) {
    pool = usable.filter((p) => filter.milk === undefined || p.flavor.milk === filter.milk);
  }
  if (!pool.length) pool = usable;
  const tried = new Set(ctx.triedIds || []);
  const scored = pool.map((p) => {
    const f = p.flavor;
    const distance = DIMS.reduce((s, k) => s + Math.abs(target[k] - f[k]), 0);
    let score = 1 - distance / 16;
    const reasons = [];
    const pnotes = (f.notes || []).map((n) => n.toLocaleLowerCase('tr'));
    if (notes.some((n) => pnotes.includes(n))) {
      score += 0.15;
      reasons.push('notes');
    }
    if ((ctx.hour ?? 12) >= 17 && p.caffeineMg === 0) {
      score += 0.1;
      reasons.push('decaf');
    }
    if (ctx.hotDay && f.temperature === 'iced') {
      score += 0.1;
      reasons.push('iced');
    }
    if (ctx.triedIds && !tried.has(p.id)) {
      score += 0.05;
      reasons.push('new');
    }
    return { productId: p.id, score: Math.round(Math.min(1, Math.max(0, score)) * 100), reasons };
  });
  // Eşit puanda kimlik sırası (Dart ile aynı sonuç için dil kuralı kullanılmaz)
  scored.sort((a, b) => b.score - a.score || (a.productId < b.productId ? -1 : a.productId > b.productId ? 1 : 0));
  return scored.slice(0, 3).map(({ productId, score, reasons }) => ({ productId, score, reasons }));
}

module.exports = { QuizError, DEFAULT_QUIZ, DIMS, validateQuiz, normalizeQuiz, profileFrom, recommend };
