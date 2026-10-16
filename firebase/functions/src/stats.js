// Günlük özet (7. ekran): dailyStats/{iş günü}.
//
// NexPOS'taki reports.py ile aynı "katkı" hesabıdır; bir kural değişirse iki dosya birlikte
// güncellenmelidir (uçtan uca test ikisini karşılaştırır). Adisyon ödenip kapandığında ya da iptal
// edildiğinde katkısı açıldığı iş gününe, iade yapıldığı iş gününe eklenir. Para kuruştur.
const { computeTotals, lineTotal, lineDeduction } = require('./orders');

const DAY_START_HOUR = 5;

// '2026-10-16T02:30:00+03:00' → '2026-10-15' (terminalin yerel saati, 05:00 dönümü)
function businessDayOf(iso) {
  const local = Date.parse(`${iso.slice(0, 19)}Z`);
  return new Date(local - DAY_START_HOUR * 3600_000).toISOString().slice(0, 10);
}

const listValue = (line) => lineTotal({ ...line, status: 'active' });
const productKey = (line) => line.productId || `n:${line.name}`;

// Aktif satırlar ve kampanya/ödül/iskonto düşülmüş payları (kuruş farkı son satırda)
function lineNets(order) {
  const lines = order.items.filter((l) => l.status === 'active' && lineTotal(l) > 0);
  const t = computeTotals(order);
  const nets = lines.map((l) => lineTotal(l) - lineDeduction(order, l.lineId));
  const base = nets.reduce((s, n) => s + n, 0);
  let left = t.discountAmount;
  return lines.map((l, i) => {
    const share = i === lines.length - 1 ? left : (base ? Math.floor((t.discountAmount * nets[i]) / base) : 0);
    left -= share;
    return [l, nets[i] - share];
  });
}

function merge(a, b) {
  for (const [k, v] of Object.entries(b)) {
    if (v && typeof v === 'object') merge((a[k] ??= {}), v);
    else if (typeof v === 'string') a[k] ??= v;
    else a[k] = (a[k] || 0) + v;
  }
  return a;
}

function contribution(order) {
  if (order.status === 'cancelled') {
    const lost = order.items.filter((l) => l.status === 'void' || (l.status === 'active' && l.state === 'sent'));
    return { cancelled: 1, voids: { count: lost.reduce((s, l) => s + l.qty, 0), amount: lost.reduce((s, l) => s + listValue(l), 0) } };
  }
  if (order.status !== 'paid') return {};
  const t = computeTotals(order);
  const hour = (order.closedAt || order.openedAt).slice(11, 13);
  const c = {
    orders: 1,
    dineIn: order.type === 'dine_in' ? 1 : 0,
    takeaway: order.type === 'dine_in' ? 0 : 1,
    gross: t.subtotal,
    discount: t.discountAmount,
    discountCount: t.discountAmount ? 1 : 0,
    revenue: t.total,
    tips: order.payments.reduce((s, p) => s + (p.tip || 0), 0),
    byPayment: {},
    byHour: { [hour]: { revenue: t.total, orders: 1 } },
    byStaff: { [order.waiterId]: { revenue: t.total, orders: 1 } },
    byProduct: {},
    comps: { count: 0, amount: 0 },
    voids: { count: 0, amount: 0 },
    vat: {},
  };
  for (const p of order.payments) c.byPayment[p.method] = (c.byPayment[p.method] || 0) + p.amount;
  for (const [l, net] of lineNets(order)) {
    merge(c.byProduct, { [productKey(l)]: { name: l.name, qty: l.qty, revenue: net } });
    const rate = String(l.taxRate ?? 10);
    c.vat[rate] = (c.vat[rate] || 0) + net;
  }
  for (const l of order.items) {
    if (l.status !== 'comp' && l.status !== 'void') continue;
    const kind = l.status === 'comp' ? 'comps' : 'voids';
    c[kind].count += l.qty;
    c[kind].amount += listValue(l);
    merge(c.byProduct, { [productKey(l)]: { name: l.name, [kind]: l.qty } });
  }
  // 10. ekran: kampanya, ödül ve üye adisyonları (yalnızca varsa)
  if (t.campaignAmount) {
    c.campaign = t.campaignAmount;
    c.byCampaign = {};
    for (const x of order.campaigns) {
      if (x.amount) merge(c.byCampaign, { [x.campaignId]: { name: x.name, count: 1, amount: x.amount } });
    }
  }
  if (t.rewardAmount) c.rewards = { count: order.rewards.length, amount: t.rewardAmount };
  if (order.customer) c.members = { orders: 1, revenue: t.total };
  return c;
}

function refundContribution(refund) {
  return { refunds: { count: 1, amount: refund.amount, [refund.method]: refund.amount } };
}

module.exports = { businessDayOf, contribution, refundContribution, merge, lineNets };
