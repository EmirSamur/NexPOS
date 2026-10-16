// Kampanyalar (10. ekran): doğrulama, ne zaman geçerli olduğu ve adisyona uygulanacak indirimler.
//
// NexPOS'taki karşılığı campaigns_logic.py'dir; ikisi de test/campaign_vectors.json'daki ortak senaryolarla
// test edilir. Kasa hesabı yapıp sonucu `applyCampaigns` ile gönderir; sunucu tutarları satır sınırlarıyla
// denetler. Para kuruştur. Bir ürüne en fazla bir kampanya uygulanır (müşteri için en avantajlısı).

const TYPES = ['percent', 'amount', 'nth', 'bundle', 'double_stamps'];
const AUDIENCES = ['all', 'members', 'silver', 'gold'];
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

class CampaignError extends Error {}

function fail(message) {
  throw new CampaignError(message);
}

function isInt(v, min, max) {
  return Number.isInteger(v) && v >= min && v <= max;
}

function ids(v, field, max) {
  if (v === undefined || v === null) return [];
  if (!Array.isArray(v) || v.length > max || v.some((x) => typeof x !== 'string' || !x || x.length > 128)) {
    fail(`${field} geçersiz.`);
  }
  return [...new Set(v)];
}

function validateCampaign(input) {
  const d = input || {};
  const name = typeof d.name === 'string' ? d.name.trim() : '';
  if (!name || name.length > 60) fail('Kampanya adı 1-60 karakter olmalıdır.');
  if (!TYPES.includes(d.type)) fail('Kampanya türü geçersiz.');
  const out = { name, type: d.type, value: 0, nthQty: null, bundle: null, stampMultiplier: 1,
    appliesTo: { categoryIds: [], productIds: [] } };
  if (d.type === 'percent' || d.type === 'nth') {
    if (!isInt(d.value, 1, 100)) fail('İndirim yüzdesi 1-100 olmalıdır.');
    out.value = d.value;
  }
  if (d.type === 'amount') {
    if (!isInt(d.value, 1, 10_000_000)) fail('İndirim tutarı kuruş cinsinden olmalıdır.');
    out.value = d.value;
  }
  if (d.type === 'nth') {
    if (!isInt(d.nthQty, 2, 10)) fail('Kaçıncı ürün 2-10 olmalıdır.');
    out.nthQty = d.nthQty;
  }
  if (d.type === 'bundle') {
    const b = d.bundle || {};
    const productIds = ids(b.productIds, 'Menü ürünleri', 4);
    if (productIds.length < 2) fail('Menüde en az iki farklı ürün olmalıdır.');
    if (!isInt(b.price, 1, 10_000_000)) fail('Menü fiyatı kuruş cinsinden olmalıdır.');
    out.bundle = { productIds, price: b.price };
  }
  if (d.type === 'double_stamps') out.stampMultiplier = isInt(d.stampMultiplier, 2, 5) ? d.stampMultiplier : 2;
  if (['percent', 'amount', 'nth'].includes(d.type)) {
    const a = d.appliesTo || {};
    out.appliesTo = { categoryIds: ids(a.categoryIds, 'Kategoriler', 50), productIds: ids(a.productIds, 'Ürünler', 200) };
  }
  const s = d.schedule || {};
  const days = s.days ?? [1, 2, 3, 4, 5, 6, 7];
  if (!Array.isArray(days) || !days.length || days.some((x) => !isInt(x, 1, 7))) fail('Günler geçersiz.');
  const from = s.from || null;
  const to = s.to || null;
  if ((from && !TIME_RE.test(from)) || (to && !TIME_RE.test(to)) || Boolean(from) !== Boolean(to) || (from && from === to)) {
    fail('Saat aralığı SS:DD – SS:DD olmalıdır.');
  }
  const startDate = s.startDate || null;
  const endDate = s.endDate || null;
  if ((startDate && !DATE_RE.test(startDate)) || (endDate && !DATE_RE.test(endDate))) fail('Tarih geçersiz.');
  if (startDate && endDate && endDate < startDate) fail('Bitiş tarihi başlangıçtan önce olamaz.');
  out.schedule = { days: [...new Set(days)].sort(), from, to, startDate, endDate };
  out.audience = d.audience ?? 'all';
  if (!AUDIENCES.includes(out.audience)) fail('Kampanya kitlesi geçersiz.');
  out.minTotal = d.minTotal ?? 0;
  if (!isInt(out.minTotal, 0, 10_000_000)) fail('En az adisyon tutarı geçersiz.');
  if (d.active !== undefined && typeof d.active !== 'boolean') fail('Aktif değeri geçersiz.');
  out.active = d.active ?? true;
  out.showInApp = d.showInApp === true;
  const description = typeof d.description === 'string' ? d.description.trim() : '';
  if (description.length > 200) fail('Açıklama en fazla 200 karakter olabilir.');
  out.description = description;
  return out;
}

const minutesOf = (hm) => Number(hm.slice(0, 2)) * 60 + Number(hm.slice(3, 5));

// Kampanya bu an (terminalin yerel saati) ve bu müşteri için geçerli mi?
function isLive(c, at, customer) {
  if (!c || c.active === false || c.deleted === true) return false;
  const day = at.slice(0, 10);
  const s = c.schedule || {};
  if (s.startDate && day < s.startDate) return false;
  if (s.endDate && day > s.endDate) return false;
  const weekday = ((new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7) + 1; // 1 = Pazartesi
  const now = minutesOf(at.slice(11, 16));
  const days = s.days || [];
  if (s.from && s.to) {
    const f = minutesOf(s.from);
    const t = minutesOf(s.to);
    let dayOk;
    if (f < t) {
      if (now < f || now >= t) return false;
      dayOk = days.includes(weekday);
    } else if (now >= f) {
      dayOk = days.includes(weekday);
    } else if (now < t) {
      // Gece yarısını geçen aralık (22:00–02:00): gece kısmı önceki günün kampanyasıdır
      dayOk = days.includes(((weekday + 5) % 7) + 1);
    } else {
      return false;
    }
    if (!dayOk) return false;
  } else if (!days.includes(weekday)) {
    return false;
  }
  const aud = c.audience || 'all';
  if (aud === 'all') return true;
  if (!customer) return false;
  if (aud === 'members') return true;
  if (aud === 'silver') return ['silver', 'gold'].includes(customer.tier);
  return customer.tier === 'gold';
}

function lineTotal(l) {
  return (l.unitPrice + (l.options || []).reduce((s, o) => s + o.priceDelta, 0)) * l.qty;
}

const halfUp = (x, pct) => Math.floor((x * pct + 50) / 100);

// Adisyonun indirime açık birimleri: aktif, ödenmemiş satırların ödül almamış adetleri
function unitsOf(order, categoryOf) {
  const units = [];
  for (const l of order.items) {
    if (l.status !== 'active' || l.paidBy) continue;
    const free = (order.rewards || []).filter((r) => r.lineId === l.lineId).length;
    const price = lineTotal(l) / l.qty;
    for (let i = 0; i < l.qty - free; i += 1) {
      units.push({ key: `${l.lineId}#${i}`, lineId: l.lineId, price, productId: l.productId || null,
        categoryId: (l.productId && categoryOf[l.productId]) || null, stampEligible: Boolean(l.stampEligible) });
    }
  }
  // Pahalıdan ucuza; eşitlikte satır sırası
  return units.sort((a, b) => b.price - a.price);
}

function matches(c, u) {
  const a = c.appliesTo || {};
  const cats = a.categoryIds || [];
  const prods = a.productIds || [];
  if (!cats.length && !prods.length) return true;
  return prods.includes(u.productId) || (u.categoryId !== null && cats.includes(u.categoryId));
}

// Kampanyanın kalan birimlere faydası: { amount, take: [[unitKey, indirim]] }
function benefit(c, units) {
  const take = [];
  if (c.type === 'percent' || c.type === 'amount') {
    for (const u of units) {
      if (!matches(c, u)) continue;
      const off = c.type === 'percent' ? halfUp(u.price, c.value) : Math.min(c.value, u.price);
      if (off > 0) take.push([u.key, off]);
    }
  } else if (c.type === 'nth') {
    const eligible = units.filter((u) => matches(c, u));
    for (let i = 0; i + c.nthQty <= eligible.length; i += c.nthQty) {
      const group = eligible.slice(i, i + c.nthQty);
      const cheapest = group[group.length - 1];
      const off = halfUp(cheapest.price, c.value);
      if (off > 0) for (const u of group) take.push([u.key, u === cheapest ? off : 0]);
    }
  } else if (c.type === 'bundle') {
    const pools = c.bundle.productIds.map((pid) => units.filter((u) => u.productId === pid));
    const n = Math.min(...pools.map((p) => p.length));
    for (let i = 0; i < n; i += 1) {
      const set = pools.map((p) => p[i]);
      const sum = set.reduce((s, u) => s + u.price, 0);
      const off = sum - c.bundle.price;
      if (off <= 0) break;
      let left = off;
      set.forEach((u, j) => {
        const share = j === set.length - 1 ? left : Math.floor((off * u.price) / sum);
        left -= share;
        take.push([u.key, share]);
      });
    }
  }
  return { amount: take.reduce((s, [, x]) => s + x, 0), take };
}

function* permutations(list) {
  if (list.length <= 1) {
    yield list;
    return;
  }
  for (let i = 0; i < list.length; i += 1) {
    for (const rest of permutations([...list.slice(0, i), ...list.slice(i + 1)])) yield [list[i], ...rest];
  }
}

function orders(money) {
  return money.length <= 6 ? permutations(money) : [money];
}

// Kampanyaları verilen sırayla kalan birimlere uygular
function applySequence(perm, allUnits) {
  let units = allUnits;
  const out = [];
  let total = 0;
  for (const c of perm) {
    const b = benefit(c, units);
    if (b.amount <= 0) continue;
    const lines = {};
    const used = new Set();
    for (const [key, off] of b.take) {
      used.add(key);
      if (off > 0) {
        const lineId = key.slice(0, key.lastIndexOf('#'));
        lines[lineId] = (lines[lineId] || 0) + off;
      }
    }
    out.push({ campaignId: c.id, name: c.name, type: c.type, lines });
    total += b.amount;
    units = units.filter((u) => !used.has(u.key));
  }
  return { total, out };
}

// Adisyona uygulanacak kampanyalar: applyCampaigns işleminin `campaigns` alanı.
// ctx: { at (yerel ISO), categoryOf: { productId: categoryId } }
function computeCampaigns(order, campaigns, ctx) {
  const excluded = new Set(order.campaignsExcluded || []);
  const live = campaigns.filter((c) => !excluded.has(c.id) && isLive(c, ctx.at, order.customer));
  const subtotal = order.items.reduce((s, l) => s + (l.status === 'active' ? lineTotal(l) : 0), 0);
  const eligible = live.filter((c) => subtotal >= (c.minTotal || 0));
  const out = [];
  const stampy = order.items.some((l) => l.status === 'active' && l.stampEligible);
  if (!order.discount) {
    const units = unitsOf(order, ctx.categoryOf || {});
    const money = eligible.filter((c) => c.type !== 'double_stamps').sort((a, b) => (a.id < b.id ? -1 : 1));
    // Kampanyaları her sırayla dene, müşteriye en çok indirim vereni seç (eşitlikte ilk sıra).
    // Az sayıda kampanya geçerli olur; 6'dan fazlaysa en büyük faydalıdan başlayarak sırayla uygulanır.
    let best = null;
    for (const perm of orders(money)) {
      const r = applySequence(perm, units);
      if (!best || r.total > best.total) best = r;
    }
    if (best) out.push(...best.out);
  }
  const stamps = eligible.filter((c) => c.type === 'double_stamps' && order.customer && stampy)
    .sort((a, b) => (b.stampMultiplier || 2) - (a.stampMultiplier || 2) || (a.id < b.id ? -1 : 1))[0];
  if (stamps) {
    out.push({ campaignId: stamps.id, name: stamps.name, type: 'double_stamps', lines: {},
      stampMultiplier: stamps.stampMultiplier || 2 });
  }
  return out;
}

module.exports = { CampaignError, TYPES, AUDIENCES, validateCampaign, isLive, computeCampaigns };
