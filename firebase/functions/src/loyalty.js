// Sadakat (10. ekran): damga, ödül, seviye ve doğum günü kuralları.
//
// NexPOS'taki karşılığı loyalty_logic.py'dir; ikisi de test/loyalty_vectors.json'daki ortak
// senaryolarla test edilir. Telefon numarası 10 hane olarak tutulur (5321234567).

const DEFAULT_LOYALTY = {
  stampsForReward: 10,
  rewardMaxValue: 9000, // kuruş: bedava ürün en fazla 90 ₺
  rewardValidDays: 60,
  birthdayReward: true,
  tiers: [
    { id: 'bronze', name: 'Bronz', minStamps: 0, perks: '' },
    { id: 'silver', name: 'Gümüş', minStamps: 50, perks: '' },
    { id: 'gold', name: 'Altın', minStamps: 150, perks: '' },
  ],
};

class LoyaltyError extends Error {}

function intIn(v, fallback, min, max, message) {
  const x = v ?? fallback;
  if (!Number.isInteger(x) || x < min || x > max) throw new LoyaltyError(message);
  return x;
}

// Ayarları doğrular; eksikler varsayılandan gelir. Seviye eşikleri artan sırada olmalıdır.
function validateLoyaltySettings(input) {
  const d = input || {};
  const D = DEFAULT_LOYALTY;
  const tiersIn = d.tiers ?? D.tiers;
  if (!Array.isArray(tiersIn) || tiersIn.length !== 3) throw new LoyaltyError('Üç seviye olmalıdır.');
  const tiers = tiersIn.map((t, i) => {
    const name = typeof t?.name === 'string' ? t.name.trim() : '';
    if (!name || name.length > 20) throw new LoyaltyError('Seviye adı 1-20 karakter olmalıdır.');
    const perks = typeof t.perks === 'string' ? t.perks.trim() : '';
    if (perks.length > 200) throw new LoyaltyError('Ayrıcalık metni en fazla 200 karakter olabilir.');
    return { id: D.tiers[i].id, name, minStamps: i === 0 ? 0 : intIn(t.minStamps, D.tiers[i].minStamps, 1, 100000,
      'Seviye eşiği geçersiz.'), perks };
  });
  if (!(tiers[1].minStamps < tiers[2].minStamps)) throw new LoyaltyError('Seviye eşikleri artan sırada olmalıdır.');
  if (d.birthdayReward !== undefined && typeof d.birthdayReward !== 'boolean') throw new LoyaltyError('Doğum günü ayarı geçersiz.');
  return {
    stampsForReward: intIn(d.stampsForReward, D.stampsForReward, 2, 50, 'Ödül için damga sayısı 2-50 olmalıdır.'),
    rewardMaxValue: intIn(d.rewardMaxValue, D.rewardMaxValue, 100, 1_000_000, 'Ödül üst sınırı geçersiz.'),
    rewardValidDays: intIn(d.rewardValidDays, D.rewardValidDays, 1, 365, 'Ödül süresi 1-365 gün olmalıdır.'),
    birthdayReward: d.birthdayReward ?? D.birthdayReward,
    tiers,
  };
}

function normalizeLoyalty(stored) {
  try {
    return validateLoyaltySettings(stored);
  } catch (e) {
    return JSON.parse(JSON.stringify(DEFAULT_LOYALTY));
  }
}

// '0532 123 45 67', '+90 532…', '5321234567' → '5321234567'; geçersizse null
function normalizePhone(text) {
  if (typeof text !== 'string') return null;
  let digits = text.replace(/\D/g, '');
  if (digits.length === 12 && digits.startsWith('90')) digits = digits.slice(2);
  if (digits.length === 11 && digits.startsWith('0')) digits = digits.slice(1);
  return /^[2-5]\d{9}$/.test(digits) ? digits : null;
}

// '5321234567' → '0532 *** ** 67'
function maskPhone(phone) {
  return phone ? `0${phone.slice(0, 3)} *** ** ${phone.slice(8)}` : '';
}

function tierFor(lifetime, settings) {
  let id = settings.tiers[0].id;
  for (const t of settings.tiers) if (lifetime >= t.minStamps) id = t.id;
  return id;
}

// Damga ekler: kart dolunca ödül çıkar, artan damga yeni karta geçer.
function applyStamps(state, earned, settings) {
  const total = (state.stamps || 0) + earned;
  const lifetimeStamps = (state.lifetimeStamps || 0) + earned;
  return {
    stamps: total % settings.stampsForReward,
    lifetimeStamps,
    newRewards: Math.floor(total / settings.stampsForReward),
    tier: tierFor(lifetimeStamps, settings),
  };
}

// Damga geri alır (iade, elle düzeltme). Verilmiş ödül geri alınmaz; damga 0'ın altına inmez.
function revokeStamps(state, n, settings) {
  const lifetimeStamps = Math.max((state.lifetimeStamps || 0) - n, 0);
  return { stamps: Math.max((state.stamps || 0) - n, 0), lifetimeStamps, newRewards: 0,
    tier: tierFor(lifetimeStamps, settings) };
}

// İadede geri alınacak damga: ödenenin iade edilen oranı kadar (aşağı), daha önce alınanlar düşülür.
function refundRevoke(earned, paid, refundedTotal, alreadyRevoked) {
  if (!earned || !paid) return 0;
  return Math.max(Math.floor((earned * Math.min(refundedTotal, paid)) / paid) - (alreadyRevoked || 0), 0);
}

function addDays(day, n) {
  return new Date(Date.parse(`${day}T00:00:00Z`) + n * 86400_000).toISOString().slice(0, 10);
}

// Doğum günü haftası: doğum gününün 3 gün öncesi ile 3 gün sonrası (yıl dönümü dahil)
function isBirthdayWeek(birthDate, day) {
  if (typeof birthDate !== 'string' || !/^\d{2}-\d{2}$/.test(birthDate)) return false;
  const year = Number(day.slice(0, 4));
  const at = Date.parse(`${day}T00:00:00Z`);
  for (const y of [year - 1, year, year + 1]) {
    let md = birthDate;
    const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
    if (md === '02-29' && !leap) md = '02-28';
    const b = Date.parse(`${y}-${md}T00:00:00Z`);
    if (Number.isNaN(b)) return false;
    if (Math.abs(at - b) <= 3 * 86400_000) return true;
  }
  return false;
}

// Ödül bu müşteri için bu gün kullanılabilir mi?
function rewardUsable(reward, customerId, day) {
  return Boolean(reward) && reward.status === 'active' && reward.customerId === customerId
    && typeof reward.expiresAt === 'string' && reward.expiresAt >= day;
}

module.exports = {
  DEFAULT_LOYALTY, LoyaltyError, validateLoyaltySettings, normalizeLoyalty, normalizePhone, maskPhone, tierFor,
  applyStamps, revokeStamps, refundRevoke, addDays, isBirthdayWeek, rewardUsable,
};
