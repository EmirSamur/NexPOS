// Bildirimler (11c): kime, hangi metin, hangi sınırla.
//
// Türler: "order" (sipariş durumu; izin gerekmez — işlem bildirimi), "loyalty" (ödül, doğum günü, süre doluyor;
// bildirim izni gerekir), "marketing" (panelden kampanya bildirimi; izin + kişi başı günde en fazla 1).

const ORDER_MESSAGES = {
  accepted: (a) => ({ title: 'Siparişin onaylandı ☕', body: a.kind === 'pickup' ? 'Hazırlanmaya başladı.' : 'Birazdan hazır.' }),
  ready: (a) => ({ title: 'Siparişin hazır 🔔', body: a.kind === 'pickup'
    ? `${a.orderNo ? `${a.orderNo} · ` : ''}Gelip alabilirsin.` : 'Birazdan masanda.' }),
  rejected: (a) => ({ title: 'Sipariş alınamadı', body: a.reason || 'Kasaya ya da garsona sipariş verebilirsin.' }),
  expired: () => ({ title: 'Kafe şu an yoğun', body: 'Siparişin onaylanamadı; kasaya ya da garsona sipariş verebilirsin.' }),
};

// appOrders durum değişimi → bildirim (yoksa null)
function orderMessage(before, after) {
  if (!after || before?.status === after.status || !ORDER_MESSAGES[after.status]) return null;
  return { ...ORDER_MESSAGES[after.status](after), data: { type: 'appOrder', id: String(after.id || ''), status: after.status } };
}

const REWARD_TITLES = { free_drink: 'Kartın doldu 🎁', birthday: 'Doğum günün kutlu olsun 🎂', manual: 'Sana bir hediye var 🎁' };

function rewardMessage(reward) {
  const title = REWARD_TITLES[reward?.type];
  if (!title || reward.status !== 'active') return null;
  return { title, body: `Bir içecek bizden. Son kullanma: ${reward.expiresAt.split('-').reverse().join('.')}`,
    data: { type: 'reward' } };
}

// kind: order | loyalty | marketing; today: YYYY-AA-GG (Türkiye)
function allowed(customer, kind, today) {
  if (!customer || customer.deleted === true) return false;
  if (kind === 'order') return true;
  if (customer.marketingConsent !== true) return false;
  return kind !== 'marketing' || customer.lastMarketingPushDay !== today;
}

// Günlük bildirimler: bugün doğum günü olanlar ve süresi 7 gün sonra dolan ödüller.
// customers: [{ id, birthDate }], rewards: [{ id, customerId, status, expiresAt }] → [{ customerId, title, body }]
function dailyMessages(customers, rewards, today, addDays) {
  const out = [];
  const mmdd = today.slice(5);
  for (const c of customers) {
    if (c.birthDate === mmdd) out.push({ customerId: c.id, title: 'Doğum günün kutlu olsun 🎂', body: 'Bu hafta gel, bir içecek bizden.' });
  }
  const in7 = addDays(today, 7);
  for (const r of rewards) {
    if (r.status === 'active' && r.expiresAt === in7) {
      out.push({ customerId: r.customerId, title: 'Ödülünü unutma 🎁', body: 'Bedava içeceğinin süresi 7 gün sonra doluyor.' });
    }
  }
  return out;
}

module.exports = { orderMessage, rewardMessage, allowed, dailyMessages };
