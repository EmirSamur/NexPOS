// Uygulama siparişleri (11. ekran): masadan QR sipariş ve gel-al.
//
// Müşterinin gönderdiği sepet bir İSTEKTİR (appOrders/{id}). Fiyatı sunucu menüden hesaplar;
// uygulamanın gönderdiği fiyata güvenilmez. Kasa (NexPOS) isteği onaylayınca normal adisyona
// çevirir; mutfak/bar fişleri ilerledikçe isteğin durumu da ilerler.
//
// Durumlar: pending → accepted → preparing → ready → completed
//           pending → rejected | expired | cancelled ;  accepted.. → cancelled | no_show

class AppOrderError extends Error {}

const ACTIVE = ['pending', 'accepted', 'preparing', 'ready'];
const MAX_LINES = 20;
const MAX_QTY = 20;
const MAX_UNITS = 50;
const MAX_TOTAL = 300_000; // kuruş: tek istekte en fazla 3.000 ₺
const MAX_PENDING_PER_TABLE = 2;
const MAX_ACTIVE_PER_CUSTOMER = 3;
const PICKUP_MAX_AHEAD_MIN = 180;
const KASA_ONLINE_MS = 120_000; // kasa 2 dakikadır görünmüyorsa çevrimiçi sipariş alınmaz
const NO_SHOW_LIMIT = 2;

function fail(message) {
  throw new AppOrderError(message);
}

const isInt = (v, min, max) => Number.isInteger(v) && v >= min && v <= max;

// items: [{ productId, qty, options: [{ groupId, optionId }], note }]
// menu: { products: Map, groups: Map, categories: Map } (id → doküman verisi)
// → { items: [{ productId, name, qty, unitPrice, options: [{ groupId, optionId, name, priceDelta }], note, lineTotal }], total }
function priceCart(items, menu) {
  if (!Array.isArray(items) || items.length < 1) fail('Sepet boş.');
  if (items.length > MAX_LINES) fail(`Bir siparişte en fazla ${MAX_LINES} satır olabilir.`);
  let units = 0;
  let total = 0;
  const out = items.map((it) => {
    if (!it || typeof it.productId !== 'string' || !it.productId) fail('Ürün geçersiz.');
    if (!isInt(it.qty, 1, MAX_QTY)) fail(`Adet 1-${MAX_QTY} arası olmalıdır.`);
    const p = menu.products.get(it.productId);
    if (!p || p.deleted === true || p.active === false || p.visibleInApp === false) fail('Ürün menüde yok.');
    const cat = menu.categories.get(p.categoryId);
    if (!cat || cat.deleted === true || cat.visibleInApp === false) fail('Ürün menüde yok.');
    if (p.soldOut === true) fail(`${p.name} tükendi.`);
    const note = it.note === undefined || it.note === null ? '' : it.note;
    if (typeof note !== 'string' || note.length > 120) fail('Not en fazla 120 karakter olabilir.');

    const chosen = Array.isArray(it.options) ? it.options : [];
    if (chosen.length > 20) fail('Seçenekler geçersiz.');
    const allowed = new Set(p.optionGroupIds || []);
    const byGroup = new Map();
    const seen = new Set();
    for (const o of chosen) {
      if (!o || typeof o.groupId !== 'string' || typeof o.optionId !== 'string') fail('Seçenek geçersiz.');
      const key = `${o.groupId}/${o.optionId}`;
      if (seen.has(key)) fail('Aynı seçenek iki kez seçilmiş.');
      seen.add(key);
      if (!allowed.has(o.groupId)) fail('Seçenek bu ürüne ait değil.');
      if (!byGroup.has(o.groupId)) byGroup.set(o.groupId, []);
      byGroup.get(o.groupId).push(o.optionId);
    }
    const options = [];
    for (const gid of p.optionGroupIds || []) {
      const g = menu.groups.get(gid);
      if (!g || g.deleted === true) continue;
      const picked = byGroup.get(gid) || [];
      const min = Number.isInteger(g.min) ? g.min : g.required ? 1 : 0;
      const max = Number.isInteger(g.max) ? g.max : g.selection === 'multi' ? (g.options || []).length : 1;
      if (picked.length < min) fail(`${p.name}: ${g.name} seçilmelidir.`);
      if (picked.length > max) fail(`${p.name}: ${g.name} için en fazla ${max} seçim yapılabilir.`);
      for (const oid of picked) {
        const opt = (g.options || []).find((x) => x.id === oid);
        if (!opt || opt.active === false) fail('Seçenek menüde yok.');
        if (opt.soldOut === true) fail(`${opt.name} tükendi.`);
        options.push({ groupId: gid, optionId: oid, name: opt.name, priceDelta: opt.priceDelta || 0 });
      }
    }
    for (const gid of byGroup.keys()) {
      const g = menu.groups.get(gid);
      if (!g || g.deleted === true) fail('Seçenek menüde yok.');
    }
    const unit = p.price + options.reduce((s, o) => s + o.priceDelta, 0);
    const lineTotal = unit * it.qty;
    units += it.qty;
    total += lineTotal;
    return { productId: it.productId, name: p.name, qty: it.qty, unitPrice: p.price, options, note: note.trim(), lineTotal };
  });
  if (units > MAX_UNITS) fail(`Bir siparişte en fazla ${MAX_UNITS} ürün olabilir.`);
  if (total > MAX_TOTAL) fail('Sipariş tutarı sınırı aşıyor; lütfen kasaya başvurun.');
  return { items: out, total };
}

// Gel-al saati. choice: { asap: true } | { inMinutes: 15 } | { at: ISO }. → ms
function pickupAt(choice, nowMs, prepMinutes) {
  const earliest = nowMs + prepMinutes * 60_000;
  const c = choice || {};
  let at;
  if (c.asap === true) at = earliest;
  else if (isInt(c.inMinutes, 1, PICKUP_MAX_AHEAD_MIN)) at = Math.max(nowMs + c.inMinutes * 60_000, earliest);
  else if (typeof c.at === 'string' && Number.isFinite(Date.parse(c.at))) at = Date.parse(c.at);
  else fail('Gel-al saati seçilmelidir.');
  if (at < earliest - 60_000) fail(`En erken ${prepMinutes} dakika sonrası seçilebilir.`);
  if (at > nowMs + PICKUP_MAX_AHEAD_MIN * 60_000) fail('En fazla 3 saat sonrası seçilebilir.');
  return at;
}

// Fişlerin durumundan isteğin durumu (onaylanmış istek için)
function progressFrom(ticketStatuses) {
  const s = ticketStatuses.filter(Boolean);
  if (s.length && s.every((x) => x === 'ready' || x === 'served')) return 'ready';
  if (s.some((x) => x !== 'new')) return 'preparing';
  return 'accepted';
}

// terminals: [{ kind, revoked, lastSeenMs }]
function kasaOnline(terminals, nowMs) {
  return terminals.some((t) => t.kind !== 'kds' && t.revoked !== true && nowMs - (t.lastSeenMs || 0) <= KASA_ONLINE_MS);
}

module.exports = {
  AppOrderError, ACTIVE, MAX_TOTAL, MAX_PENDING_PER_TABLE, MAX_ACTIVE_PER_CUSTOMER, KASA_ONLINE_MS, NO_SHOW_LIMIT,
  priceCart, pickupAt, progressFrom, kasaOnline,
};
