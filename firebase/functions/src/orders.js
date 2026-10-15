// Sipariş mantığı (4. ekran): bir adisyonun durumuna işlem uygulayan saf fonksiyonlar.
//
// Aynı mantığın Python karşılığı NexPOS'ta cloud/orders.py içindedir. İkisi de
// test/order_vectors.json'daki ortak senaryolarla test edilir; bir kural değişirse iki
// dosya ve senaryolar birlikte güncellenmelidir.
//
// Para her zaman kuruş cinsinden tam sayıdır.

class OrderError extends Error {}

const STATIONS = ['bar', 'kitchen'];
const TAX_RATES = [0, 1, 10, 20];
const PAYMENT_METHODS = ['cash', 'card', 'meal'];
const ORDER_TYPES = ['dine_in', 'takeaway'];

function fail(message) {
  throw new OrderError(message);
}

function isInt(v, min, max) {
  return Number.isInteger(v) && v >= min && v <= max;
}

function str(v, field, max, { optional = false } = {}) {
  if ((v === undefined || v === null || v === '') && optional) return '';
  if (typeof v !== 'string' || !v.trim() || v.length > max) fail(`${field} geçersiz.`);
  return v.trim();
}

function clone(o) {
  return JSON.parse(JSON.stringify(o));
}

function lineTotal(line) {
  if (line.status !== 'active') return 0;
  const unit = line.unitPrice + (line.options || []).reduce((s, o) => s + o.priceDelta, 0);
  return unit * line.qty;
}

// Toplamları hesaplar. İskonto ara toplama BİR KEZ uygulanır (eski NexPOS'ta yeni ürün
// eklendikçe tekrar uygulanıyordu).
function computeTotals(order) {
  const subtotal = order.items.reduce((s, l) => s + lineTotal(l), 0);
  let discountAmount = 0;
  const d = order.discount;
  if (d && d.type === 'percent') discountAmount = Math.floor((subtotal * d.value + 50) / 100); // yarım yukarı
  if (d && d.type === 'amount') discountAmount = Math.min(d.value, subtotal);
  const total = subtotal - discountAmount;
  const paid = order.payments.reduce((s, p) => s + p.amount, 0);
  const refunded = (order.refunds || []).reduce((s, r) => s + r.amount, 0);
  return { subtotal, discountAmount, total, paid, refunded, remaining: Math.max(total - paid, 0) };
}

// Seçilen satırların ödenecek payı: satır toplamı − iskontonun orantılı payı (aşağı yuvarlanır;
// kuruş farkı son ödemede kapanır).
function linesShare(order, lineIds) {
  const t = computeTotals(order);
  const gross = order.items.filter((l) => lineIds.includes(l.lineId)).reduce((s, l) => s + lineTotal(l), 0);
  if (!t.discountAmount || !t.subtotal) return gross;
  return gross - Math.floor((t.discountAmount * gross) / t.subtotal);
}

function withTotals(order) {
  return { ...order, ...computeTotals(order) };
}

// Masanın buluttaki durumu: açık masa siparişi dolu ya da hesap istendi, değilse boş.
function tableStatusFor(order) {
  if (!order || order.status !== 'open' || order.type !== 'dine_in') return 'empty';
  return order.billRequested ? 'bill_requested' : 'occupied';
}

function findLine(order, lineId) {
  const line = order.items.find((l) => l.lineId === lineId);
  if (!line) fail('Adisyon satırı bulunamadı.');
  return line;
}

function validateItem(item, existingIds) {
  const lineId = str(item?.lineId, 'Satır kimliği', 64);
  if (existingIds.has(lineId)) fail('Bu satır zaten eklenmiş.');
  existingIds.add(lineId);
  if (!isInt(item.unitPrice, 0, 10_000_000)) fail('Birim fiyat kuruş cinsinden tam sayı olmalıdır.');
  if (!isInt(item.qty, 1, 99)) fail('Adet 1-99 arası olmalıdır.');
  if (!STATIONS.includes(item.station)) fail('İstasyon bar ya da mutfak olmalıdır.');
  const taxRate = item.taxRate ?? 10;
  if (!TAX_RATES.includes(taxRate)) fail('KDV oranı geçersiz.');
  const options = item.options ?? [];
  if (!Array.isArray(options) || options.length > 20) fail('Seçenekler geçersiz.');
  return {
    lineId,
    productId: item.productId == null ? null : str(item.productId, 'Ürün', 128),
    name: str(item.name, 'Ürün adı', 80),
    unitPrice: item.unitPrice,
    options: options.map((o) => {
      if (!isInt(o?.priceDelta, -10_000_000, 10_000_000)) fail('Seçenek fiyat farkı geçersiz.');
      return { groupId: str(o.groupId, 'Seçenek grubu', 128), optionId: str(o.optionId, 'Seçenek', 64),
        name: str(o.name, 'Seçenek adı', 60), priceDelta: o.priceDelta };
    }),
    qty: item.qty,
    note: str(item.note, 'Not', 120, { optional: true }),
    station: item.station,
    taxRate,
    stampEligible: item.stampEligible === true,
    state: 'pending',
    status: 'active',
  };
}

// order: mevcut durum (openOrder için null). Geriye yeni durumu döndürür; girdiyi değiştirmez.
// ctx: { staffId, at } — işlemi yapan personel ve terminal saati (ISO).
function applyOrderOp(order, op, payload, ctx) {
  const p = payload || {};
  if (op === 'openOrder') {
    if (order) fail('Bu adisyon zaten açılmış.');
    if (!ORDER_TYPES.includes(p.type)) fail('Sipariş türü geçersiz.');
    if (p.type === 'dine_in' && (typeof p.tableId !== 'string' || !p.tableId)) fail('Masa belirtilmedi.');
    return withTotals({
      id: str(p.orderId, 'Adisyon', 64),
      no: str(p.no, 'Adisyon numarası', 12),
      businessDay: str(p.businessDay, 'İş günü', 10),
      type: p.type,
      tableId: p.type === 'dine_in' ? p.tableId : null,
      tableName: str(p.tableName, 'Masa adı', 40, { optional: true }),
      status: 'open',
      billRequested: false,
      waiterId: ctx.staffId,
      openedAt: p.openedAt || ctx.at,
      closedAt: null,
      items: [],
      discount: null,
      payments: [],
      mergedInto: null,
      cancelReason: null,
    });
  }

  if (!order) fail('Adisyon bulunamadı.');
  if (op === 'refundPayment') return refund(order, p, ctx);
  if (order.status !== 'open') fail('Adisyon kapanmış.');
  const o = clone(order);

  switch (op) {
    case 'addItems': {
      if (!Array.isArray(p.items) || p.items.length < 1 || p.items.length > 50) fail('Eklenecek ürün yok.');
      const ids = new Set(o.items.map((l) => l.lineId));
      for (const item of p.items) {
        o.items.push({ ...validateItem(item, ids), addedBy: ctx.staffId, addedAt: ctx.at });
      }
      break;
    }
    case 'updateItem': {
      const line = findLine(o, p.lineId);
      if (line.state !== 'pending' || line.status !== 'active') fail('Gönderilmiş satır değiştirilemez.');
      if (p.qty !== undefined) {
        if (!isInt(p.qty, 1, 99)) fail('Adet 1-99 arası olmalıdır.');
        line.qty = p.qty;
      }
      if (p.note !== undefined) line.note = str(p.note, 'Not', 120, { optional: true });
      break;
    }
    case 'removeItem': {
      const line = findLine(o, p.lineId);
      if (line.state !== 'pending') fail('Gönderilmiş satır silinemez; iptal edilmelidir.');
      o.items = o.items.filter((l) => l.lineId !== p.lineId);
      break;
    }
    case 'sendItems': {
      if (!Array.isArray(p.lineIds) || p.lineIds.length < 1) fail('Gönderilecek satır yok.');
      const tickets = p.ticketIds || {};
      for (const id of p.lineIds) {
        const line = findLine(o, id);
        if (line.state !== 'pending' || line.status !== 'active') fail('Satır zaten gönderilmiş.');
        if (typeof tickets[line.station] !== 'string') fail('Fiş kimliği eksik.');
        line.state = 'sent';
        line.sentAt = ctx.at;
        line.ticketId = tickets[line.station];
      }
      break;
    }
    case 'voidItem':
    case 'compItem': {
      const line = findLine(o, p.lineId);
      if (line.status !== 'active') fail('Satır zaten iptal ya da ikram edilmiş.');
      if (line.paidBy) fail('Ödenmiş satır iptal edilemez; iade yapılmalıdır.');
      if (op === 'voidItem' && line.state !== 'sent') fail('Gönderilmemiş satır iptal edilmez, silinir.');
      line.status = op === 'voidItem' ? 'void' : 'comp';
      line.reason = str(p.reason, 'Gerekçe', 120);
      line.by = ctx.staffId;
      line.approvedBy = p.approvedBy || ctx.staffId;
      line.actionAt = ctx.at;
      break;
    }
    case 'setDiscount': {
      if (o.payments.some((x) => x.lineIds)) fail('Ürün seçerek ödeme alınmış adisyonda iskonto değiştirilemez.');
      if (p.discount === null) {
        o.discount = null;
        break;
      }
      const d = p.discount || {};
      if (d.type === 'percent' && !isInt(d.value, 1, 100)) fail('İskonto yüzdesi 1-100 arası tam sayı olmalıdır.');
      if (d.type === 'amount' && !isInt(d.value, 1, 10_000_000)) fail('İskonto tutarı kuruş cinsinden olmalıdır.');
      if (!['percent', 'amount'].includes(d.type)) fail('İskonto türü geçersiz.');
      o.discount = { type: d.type, value: d.value, reason: str(p.reason, 'Gerekçe', 120, { optional: true }),
        by: ctx.staffId, approvedBy: p.approvedBy || ctx.staffId, at: ctx.at };
      break;
    }
    case 'requestBill': {
      if (typeof p.value !== 'boolean') fail('Hesap isteği true/false olmalıdır.');
      o.billRequested = p.value;
      break;
    }
    case 'moveOrder': {
      if (o.type !== 'dine_in') fail('Masasız sipariş taşınamaz.');
      if (typeof p.toTableId !== 'string' || !p.toTableId || p.toTableId === o.tableId) fail('Hedef masa geçersiz.');
      o.tableId = p.toTableId;
      o.tableName = str(p.toTableName, 'Masa adı', 40, { optional: true });
      break;
    }
    case 'splitLine': {
      const line = findLine(o, p.lineId);
      if (line.status !== 'active' || line.paidBy) fail('Bu satır bölünemez.');
      if (!isInt(p.qty, 1, line.qty - 1)) fail('Ayrılacak adet satırdaki adetten az olmalıdır.');
      const newId = str(p.newLineId, 'Satır kimliği', 64);
      if (o.items.some((l) => l.lineId === newId)) fail('Bu satır zaten eklenmiş.');
      line.qty -= p.qty;
      o.items.splice(o.items.indexOf(line) + 1, 0, { ...clone(line), lineId: newId, qty: p.qty, splitFrom: line.lineId });
      break;
    }
    case 'takePayment': {
      const t = computeTotals(o);
      if (o.items.some((l) => l.status === 'active' && l.state === 'pending')) {
        fail('Gönderilmemiş ürün varken ödeme alınamaz.');
      }
      const paymentId = str(p.paymentId, 'Ödeme', 64);
      if (o.payments.some((x) => x.paymentId === paymentId)) fail('Bu ödeme zaten alınmış.');
      if (!PAYMENT_METHODS.includes(p.method)) fail('Ödeme yöntemi geçersiz.');
      if (!isInt(p.amount, t.total === 0 ? 0 : 1, t.remaining)) fail('Ödeme tutarı kalan tutardan fazla olamaz.');
      if (t.total > 0 && p.amount === 0) fail('Ödeme tutarı geçersiz.');
      let lineIds = null;
      if (p.lineIds !== undefined && p.lineIds !== null) {
        // Ürün seçerek bölme
        if (!Array.isArray(p.lineIds) || p.lineIds.length < 1) fail('Ödenecek satır seçilmedi.');
        if (o.payments.some((x) => !x.lineIds)) fail('Tutar olarak ödeme alınmış adisyonda ürün seçerek bölünemez.');
        const unpaid = o.items.filter((l) => l.status === 'active' && !l.paidBy).map((l) => l.lineId);
        for (const id of p.lineIds) {
          if (!unpaid.includes(id)) fail('Seçilen satır ödenmiş ya da geçersiz.');
        }
        const all = unpaid.every((id) => p.lineIds.includes(id));
        const expected = all ? t.remaining : linesShare(o, p.lineIds);
        if (p.amount !== expected) fail('Tutar seçilen ürünlerin payıyla uyuşmuyor.');
        lineIds = [...p.lineIds];
      }
      const tip = p.tip ?? 0;
      if (!isInt(tip, 0, 10_000_000)) fail('Bahşiş geçersiz.');
      let received = null;
      if (p.method === 'cash') {
        received = p.received ?? p.amount;
        if (!isInt(received, p.amount, 10_000_000)) fail('Alınan nakit tutardan az olamaz.');
      }
      o.payments.push({ paymentId, method: p.method, amount: p.amount, tip, received,
        change: received === null ? 0 : received - p.amount, by: ctx.staffId, at: ctx.at,
        lineIds, cashSessionId: typeof p.cashSessionId === 'string' ? p.cashSessionId : null });
      if (lineIds) {
        for (const l of o.items) if (lineIds.includes(l.lineId)) l.paidBy = paymentId;
      }
      if (computeTotals(o).remaining === 0) {
        o.status = 'paid';
        o.closedAt = ctx.at;
      }
      break;
    }
    case 'cancelOrder': {
      if (o.payments.length) fail('Ödeme alınmış adisyon iptal edilemez.');
      o.status = 'cancelled';
      o.cancelReason = str(p.reason, 'Gerekçe', 120);
      o.closedAt = ctx.at;
      o.cancelledBy = ctx.staffId;
      o.approvedBy = p.approvedBy || ctx.staffId;
      break;
    }
    default:
      fail(`Bilinmeyen adisyon işlemi: ${op}`);
  }
  return withTotals(o);
}

// Kapanmış (ödenmiş) adisyonda iade. Adisyon "paid" kalır; iadeler ayrı listede tutulur.
function refund(order, p, ctx) {
  if (order.status !== 'paid') fail('Yalnızca ödenmiş adisyon iade edilebilir.');
  const o = clone(order);
  o.refunds = o.refunds || [];
  const t = computeTotals(o);
  const refundId = str(p.refundId, 'İade', 64);
  if (o.refunds.some((r) => r.refundId === refundId)) fail('Bu iade zaten yapılmış.');
  if (!PAYMENT_METHODS.includes(p.method)) fail('İade yöntemi geçersiz.');
  if (!isInt(p.amount, 1, t.paid - t.refunded)) fail('İade tutarı ödenen tutarı aşamaz.');
  o.refunds.push({ refundId, method: p.method, amount: p.amount, reason: str(p.reason, 'Gerekçe', 120),
    by: ctx.staffId, approvedBy: p.approvedBy || ctx.staffId, at: ctx.at,
    cashSessionId: typeof p.cashSessionId === 'string' ? p.cashSessionId : null });
  return withTotals(o);
}

// İki masanın adisyonunu birleştirir: kaynaktaki satırlar hedefe taşınır, kaynak kapanır.
function mergeOrders(target, source, ctx) {
  if (!target || !source) fail('Adisyon bulunamadı.');
  if (target.status !== 'open' || source.status !== 'open') fail('Kapanmış adisyon birleştirilemez.');
  if (target.id === source.id) fail('Adisyon kendisiyle birleştirilemez.');
  if (source.payments.length) fail('Ödeme alınmış adisyon birleştirilemez.');
  if (target.payments.some((x) => x.lineIds)) fail('Ürün seçerek ödeme alınmış adisyona birleştirme yapılamaz.');
  const t = clone(target);
  const s = clone(source);
  const ids = new Set(t.items.map((l) => l.lineId));
  for (const l of s.items) {
    if (ids.has(l.lineId)) fail('Satır kimlikleri çakışıyor.');
    t.items.push({ ...l, mergedFrom: s.id });
  }
  s.items = [];
  s.status = 'merged';
  s.mergedInto = t.id;
  s.closedAt = ctx.at;
  return [withTotals(t), withTotals(s)];
}

// Hangi ürünlerin sadakat damgası kazandırdığı (10. ekran için şimdiden kaydedilir).
function stampCount(order) {
  return order.items.filter((l) => l.status === 'active' && l.stampEligible).reduce((s, l) => s + l.qty, 0);
}

module.exports = {
  OrderError,
  TAX_RATES,
  linesShare,
  PAYMENT_METHODS,
  applyOrderOp,
  mergeOrders,
  computeTotals,
  tableStatusFor,
  stampCount,
  lineTotal,
};
