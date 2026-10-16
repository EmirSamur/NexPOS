// Vardiya ve mesai hesapları (9. ekran).
//
// NexPOS'taki karşılığı shifts_logic.py'dir; ikisi de test/shift_vectors.json'daki ortak
// senaryolarla test edilir. Saatler terminalin yerel saatidir (ISO'nun ilk 19 karakteri).
// Süreler dakikadır.

const DAY_START_HOUR = 5;
const WEEKLY_LIMIT_MINUTES = 45 * 60; // iş kanunu haftalık sınır (bilgi amaçlı)
const LEAVE_TYPES = ['annual', 'sick', 'unpaid', 'holiday'];

// Yerel saat → dakika cinsinden "mutlak" zaman (karşılaştırma için)
function localMinutes(iso) {
  return Date.parse(`${iso.slice(0, 19)}Z`) / 60000;
}

function businessDayOf(iso) {
  return new Date(Date.parse(`${iso.slice(0, 19)}Z`) - DAY_START_HOUR * 3600_000).toISOString().slice(0, 10);
}

function hm(text) {
  const [h, m] = text.split(':').map(Number);
  return h * 60 + m;
}

// Planın başlangıç ve bitişi (mutlak dakika). 05:00'ten önce başlayan vardiya iş gününün gecesine,
// başlangıçtan önce ya da eşit biten vardiya ertesi güne taşar (16:00–01:00).
function planWindow(plan) {
  if (!plan || plan.leave || !plan.start || !plan.end) return null;
  const day = Date.parse(`${plan.date}T00:00:00Z`) / 60000;
  let start = day + hm(plan.start);
  if (hm(plan.start) < DAY_START_HOUR * 60) start += 24 * 60;
  let end = day + hm(plan.end);
  if (hm(plan.end) < DAY_START_HOUR * 60) end += 24 * 60;
  if (end <= start) end += 24 * 60;
  return { start, end };
}

function plannedMinutes(plan) {
  const w = planWindow(plan);
  return w ? Math.max(w.end - w.start - (plan.breakMinutes || 0), 0) : 0;
}

// Geç kalma: toleransı aşan gecikmenin tamamı (09:00 plan, 09:07 giriş, tolerans 5 → 7 dk)
function lateMinutes(plan, clockIn, tolerance) {
  const w = planWindow(plan);
  if (!w || !clockIn) return 0;
  const diff = Math.floor(localMinutes(clockIn) - w.start);
  return diff > tolerance ? diff : 0;
}

// Kullanılan mola: düğmeyle alınan molaların toplamı; hiç basılmadıysa plandaki mola
// (çalışılan sürenin yarısını geçmeden).
function breakMinutes(entry, plan) {
  const breaks = entry.breaks || [];
  const end = entry.clockOut;
  if (breaks.length) {
    // süren mola (mesai de sürüyorsa) henüz sayılmaz
    return breaks.filter((b) => b.end || end)
      .reduce((s, b) => s + Math.max(Math.floor(localMinutes(b.end || end) - localMinutes(b.start)), 0), 0);
  }
  if (!end) return 0;
  const gross = Math.floor(localMinutes(end) - localMinutes(entry.clockIn));
  return Math.min(plan && !plan.leave ? plan.breakMinutes || 0 : 0, Math.floor(gross / 2));
}

function workedMinutes(entry, plan) {
  if (!entry || !entry.clockIn || !entry.clockOut) return 0;
  const gross = Math.floor(localMinutes(entry.clockOut) - localMinutes(entry.clockIn));
  return Math.max(gross - breakMinutes(entry, plan), 0);
}

// Haftalık fazla mesai: 45 saati aşan kısım
function overtimeMinutes(weekWorked) {
  return Math.max(weekWorked - WEEKLY_LIMIT_MINUTES, 0);
}

module.exports = {
  DAY_START_HOUR, WEEKLY_LIMIT_MINUTES, LEAVE_TYPES, businessDayOf, planWindow, plannedMinutes, lateMinutes,
  breakMinutes, workedMinutes, overtimeMinutes, hm,
};
