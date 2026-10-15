// Mutfak ekranının saf hesapları (DOM'a ve Firebase'e bağımlı değildir; Node'da test edilir).

export const STATION_TITLES = { kitchen: 'MUTFAK', bar: 'BAR', all: 'MUTFAK + BAR' };

// Fişin bekleme süresine göre rengi: ok (yeşil) → warn (sarı) → late (kırmızı)
export function ageClass(createdAt, nowMs, warnMinutes, lateMinutes) {
  const minutes = (nowMs - Date.parse(createdAt)) / 60000;
  if (minutes >= lateMinutes) return 'late';
  if (minutes >= warnMinutes) return 'warn';
  return 'ok';
}

// 125000 ms → "02:05", 1 saati geçerse "1:02:05"
export function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

// Hazırlanmayı bekleyen ürünlerin toplamı ("3× Tost"): işaretlenen ve iptal edilen satırlar hariç.
export function allDay(tickets) {
  const counts = new Map();
  for (const t of tickets) {
    if (t.cancelled) continue;
    const done = new Set(t.doneLineIds || []);
    for (const l of t.lines || []) {
      if (l.voided || done.has(l.lineId)) continue;
      counts.set(l.name, (counts.get(l.name) || 0) + l.qty);
    }
  }
  return [...counts].map(([name, qty]) => ({ name, qty }))
    .sort((a, b) => b.qty - a.qty || a.name.localeCompare(b.name, 'tr'));
}

// Ekranda gösterilecek fişler: filtre (all | new | preparing), en eski üstte.
export function visibleTickets(tickets, filter) {
  return tickets
    .filter((t) => filter === 'all' || t.status === filter)
    .sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt) || a.id.localeCompare(b.id));
}

// "Masa 5" / "BAHÇE 3" / "PAKET" — masa adı yalnız rakamsa "MASA" eklenir (NexPOS'taki place_label ile aynı).
export function whereLabel(ticket) {
  if (ticket.type !== 'dine_in') return 'PAKET';
  const name = (ticket.tableName || '').trim();
  return (/^\d+$/.test(name) || !name ? `MASA ${name}`.trim() : name).toLocaleUpperCase('tr');
}

// Satıra dokununca işaretlenir / işaret kalkar. İptal edilen satır işaretlenmez.
export function toggleDone(ticket, lineId) {
  const line = (ticket.lines || []).find((l) => l.lineId === lineId);
  if (!line || line.voided) return null;
  const done = new Set(ticket.doneLineIds || []);
  if (done.has(lineId)) done.delete(lineId);
  else done.add(lineId);
  return [...done];
}
