// Mutfak / bar ekranı (5. ekran). Tablette tarayıcıda çalışır; fişleri buluttan canlı dinler.
//
// Kimlik: panelde üretilen 6 haneli kodla eşlenen cihaz hesabı (claims: kds, terminalId, station).
// Bu hesap yalnızca fişleri ve modül/genel ayarları okuyabilir; fiş durumunu
// updateKitchenTicket fonksiyonuyla değiştirir.
import { initializeApp } from './vendor/firebase-app.js';
import {
  getAuth, connectAuthEmulator, onAuthStateChanged, signInWithCustomToken, signOut,
} from './vendor/firebase-auth.js';
import {
  getFirestore, connectFirestoreEmulator, collection, doc, query, where, onSnapshot,
} from './vendor/firebase-firestore.js';
import { getFunctions, connectFunctionsEmulator, httpsCallable } from './vendor/firebase-functions.js';
import {
  STATION_TITLES, ageClass, allDay, formatElapsed, toggleDone, visibleTickets, whereLabel,
} from './kds-logic.js';

const LOCAL = ['localhost', '127.0.0.1'].includes(location.hostname);
const $ = (id) => document.getElementById(id);

async function loadConfig() {
  // Firebase Hosting proje ayarını kendisi sunar; emülatörde de çalışır.
  try {
    const r = await fetch('/__/firebase/init.json');
    if (r.ok) return { apiKey: 'demo-key', ...(await r.json()) };
  } catch (e) { /* aşağıdaki varsayılan */ }
  return { projectId: 'demo-nexpos', apiKey: 'demo-key' };
}

const config = await loadConfig();
const app = initializeApp(config);
const auth = getAuth(app);
const db = getFirestore(app);
const functions = getFunctions(app, 'europe-west1');
if (LOCAL) {
  connectAuthEmulator(auth, 'http://127.0.0.1:9099', { disableWarnings: true });
  connectFirestoreEmulator(db, '127.0.0.1', 8080);
  connectFunctionsEmulator(functions, '127.0.0.1', 5001);
}
const call = (name, data) => httpsCallable(functions, name)(data).then((r) => r.data);

const state = {
  terminalId: null,
  station: 'kitchen',
  tickets: new Map(),
  modules: { kds: { enabled: true, warnMinutes: 10, lateMinutes: 20, sound: true } },
  filter: 'all',
  undo: [],
  sound: localStorage.getItem('kds-sound') !== 'off',
  loaded: false,
  online: true,
  unsubscribe: [],
};

// ------------------------------------------------------------------ ekranlar
function show(id) {
  for (const s of ['pair', 'message', 'board']) $(s).hidden = s !== id;
}

function message(title, text, button, onClick) {
  $('message-title').textContent = title;
  $('message-text').textContent = text || '';
  const b = $('message-btn');
  b.hidden = !button;
  b.textContent = button || '';
  b.onclick = onClick || null;
  show('message');
}

let toastTimer = null;
function toast(text) {
  let el = document.querySelector('.toast');
  if (!el) {
    el = document.createElement('div');
    el.className = 'toast';
    el.style.cssText = 'position:fixed;left:50%;bottom:80px;transform:translateX(-50%);background:#dc2626;color:white;'
      + 'padding:12px 20px;border-radius:10px;font-weight:700;z-index:10;max-width:90%;text-align:center';
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

// ------------------------------------------------------------------ eşleme
$('pair-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const code = $('pair-code').value.trim();
  const station = document.querySelector('input[name=station]:checked').value;
  $('pair-error').textContent = '';
  $('pair-btn').disabled = true;
  try {
    const res = await call('pairKds', { code, station, name: $('pair-name').value.trim() });
    unlockAudio();
    await signInWithCustomToken(auth, res.customToken);
  } catch (err) {
    $('pair-error').textContent = err.message || 'Eşleme yapılamadı.';
  } finally {
    $('pair-btn').disabled = false;
  }
});

$('unpair-btn').addEventListener('click', async () => {
  if (confirm('Bu tabletin eşlemesi kaldırılsın mı? Tekrar kullanmak için panelden yeni kod gerekir.')) {
    await signOut(auth);
  }
});

// ------------------------------------------------------------------ oturum
onAuthStateChanged(auth, async (user) => {
  stop();
  if (!user) {
    show('pair');
    $('pair-code').focus();
    return;
  }
  const token = await user.getIdTokenResult();
  if (token.claims.kds !== true) {
    await signOut(auth);
    return;
  }
  state.terminalId = token.claims.terminalId;
  state.station = token.claims.station || 'kitchen';
  $('station-title').textContent = STATION_TITLES[state.station] || 'MUTFAK';
  message('Yükleniyor…', 'Fişler alınıyor.');
  start();
});

function stop() {
  for (const u of state.unsubscribe) u();
  state.unsubscribe = [];
  state.tickets.clear();
  state.loaded = false;
}

function revoked() {
  stop();
  message('Bu ekran iptal edildi', 'Yönetim panelinden iptal edilmiş. Tekrar kullanmak için yeni kodla eşleyin.',
    'Yeniden eşle', () => signOut(auth));
}

function start() {
  state.unsubscribe.push(onSnapshot(doc(db, 'terminals', state.terminalId), (snap) => {
    if (!snap.exists() || snap.data().revoked === true) revoked();
  }, () => revoked()));

  state.unsubscribe.push(onSnapshot(doc(db, 'settings', 'modules'), (snap) => {
    const m = snap.exists() ? snap.data() : {};
    state.modules = { kds: { enabled: false, warnMinutes: 10, lateMinutes: 20, sound: true, ...(m.kds || {}) } };
    applyModule();
  }, (err) => console.warn('modules', err)));

  const filters = [where('status', 'in', ['new', 'preparing'])];
  if (state.station !== 'all') filters.push(where('station', '==', state.station));
  state.unsubscribe.push(onSnapshot(query(collection(db, 'kitchenTickets'), ...filters),
    { includeMetadataChanges: true }, (snap) => {
      for (const change of snap.docChanges()) {
        const t = { id: change.doc.id, ...change.doc.data() };
        if (change.type === 'removed') state.tickets.delete(t.id);
        else {
          if (change.type === 'added' && state.loaded && !t.cancelled) beep();
          state.tickets.set(t.id, t);
        }
      }
      state.loaded = true;
      setOnline(!snap.metadata.fromCache && navigator.onLine);
      if (state.modules.kds.enabled) render();
    }, (err) => {
      if (err.code === 'permission-denied') revoked();
      else setOnline(false);
    }));

  const beat = () => call('terminalHeartbeat', { pending: 0, appVersion: 'kds-1' }).catch(() => {});
  beat();
  const timer = setInterval(beat, 60_000);
  state.unsubscribe.push(() => clearInterval(timer));
}

function applyModule() {
  if (!state.modules.kds.enabled) {
    message('Mutfak ekranı modülü kapalı', 'Yönetici, NexPOS → Ayarlar → Modüller sayfasından açabilir. '
      + 'Bu sırada fişler kasadaki Fiş Panosu\'nda görünür.');
    return;
  }
  show('board');
  render();
}

function setOnline(online) {
  state.online = online;
  const el = $('conn');
  el.textContent = online ? '🟢 Bağlı' : '🔴 Bağlantı yok';
  el.classList.toggle('off', !online);
  el.classList.toggle('ok', online);
}
window.addEventListener('online', () => setOnline(true));
window.addEventListener('offline', () => setOnline(false));

// ------------------------------------------------------------------ ses
let audio = null;
function unlockAudio() {
  if (!audio && window.AudioContext) audio = new AudioContext();
  if (audio && audio.state === 'suspended') audio.resume();
}
function beep() {
  if (!state.sound || !state.modules.kds.sound || !audio) return;
  const o = audio.createOscillator();
  const g = audio.createGain();
  o.frequency.value = 880;
  g.gain.setValueAtTime(0.25, audio.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.5);
  o.connect(g).connect(audio.destination);
  o.start();
  o.stop(audio.currentTime + 0.5);
}
function paintSound() {
  $('sound-btn').classList.toggle('off', !state.sound);
}
$('sound-btn').addEventListener('click', () => {
  unlockAudio();
  state.sound = !state.sound;
  localStorage.setItem('kds-sound', state.sound ? 'on' : 'off');
  paintSound();
  beep();
});
document.addEventListener('pointerdown', unlockAudio, { once: true });
paintSound();

// ------------------------------------------------------------------ işlemler
async function update(ticketId, data) {
  try {
    return await call('updateKitchenTicket', { ticketId, ...data });
  } catch (err) {
    toast(state.online ? (err.message || 'İşlem yapılamadı.') : 'Bağlantı yok; işlem yapılamadı.');
    return null;
  }
}

async function setStatus(ticket, status) {
  if (status === 'ready') {
    state.undo.push(ticket.id);
    state.tickets.delete(ticket.id); // ekrandan hemen kalksın
    render();
  }
  const ok = await update(ticket.id, { status });
  if (!ok && status === 'ready') {
    state.undo.pop();
    state.tickets.set(ticket.id, ticket);
    render();
  }
  $('undo-btn').disabled = !state.undo.length;
}

$('undo-btn').addEventListener('click', async () => {
  const id = state.undo.pop();
  $('undo-btn').disabled = !state.undo.length;
  if (id) await update(id, { status: 'preparing' });
});

async function toggleLine(ticket, lineId) {
  const done = toggleDone(ticket, lineId);
  if (!done) return;
  ticket.doneLineIds = done;
  render();
  await update(ticket.id, { doneLineIds: done });
}

for (const b of document.querySelectorAll('.filters button')) {
  b.addEventListener('click', () => {
    state.filter = b.dataset.filter;
    for (const x of document.querySelectorAll('.filters button')) x.classList.toggle('active', x === b);
    render();
  });
}

// ------------------------------------------------------------------ çizim
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function card(t) {
  const { warnMinutes, lateMinutes } = state.modules.kds;
  const age = t.cancelled ? 'ok' : ageClass(t.createdAt, Date.now(), warnMinutes, lateMinutes);
  const c = el('article', `ticket ${age}${t.cancelled ? ' cancelled' : ''}`);
  c.dataset.id = t.id;
  const head = el('header');
  head.append(el('span', 'where', whereLabel(t)), el('span', 'no', t.orderNo));
  const meta = el('div', 'meta');
  const elapsed = el('span', 'elapsed', formatElapsed(Date.now() - Date.parse(t.createdAt)));
  const label = t.cancelled ? 'İPTAL EDİLDİ' : age === 'late' ? '⚠ GECİKTİ'
    : t.status === 'preparing' ? 'HAZIRLANIYOR' : 'YENİ';
  meta.append(elapsed, el('span', 'state', label));
  const list = el('ul');
  const done = new Set(t.doneLineIds || []);
  for (const l of t.lines || []) {
    const li = el('li', l.voided ? 'voided' : done.has(l.lineId) ? 'done' : '');
    li.append(el('span', 'check', l.voided ? '' : done.has(l.lineId) ? '☑' : '☐'),
      document.createTextNode(`${l.qty}× ${l.name}`));
    for (const o of l.options || []) li.append(el('span', 'opt', `+ ${o}`));
    if (l.note) li.append(el('span', 'note', l.note));
    if (!l.voided && !t.cancelled) li.addEventListener('click', () => toggleLine(t, l.lineId));
    list.append(li);
  }
  const actions = el('div', 'actions');
  if (t.cancelled) {
    const b = el('button', 'secondary', 'Kaldır');
    b.addEventListener('click', () => setStatus(t, 'ready'));
    actions.append(b);
  } else {
    if (t.status === 'new') {
      const start = el('button', '', 'Başla');
      start.addEventListener('click', () => setStatus(t, 'preparing'));
      actions.append(start);
    }
    const ready = el('button', 'ready', 'Hazır ✓');
    ready.addEventListener('click', () => setStatus(t, 'ready'));
    actions.append(ready);
  }
  c.append(head, meta, list, actions);
  return c;
}

function render() {
  if ($('board').hidden) return;
  const all = [...state.tickets.values()];
  const shown = visibleTickets(all, state.filter);
  $('tickets').replaceChildren(...shown.map(card));
  $('empty').hidden = shown.length > 0;
  const pending = allDay(all);
  $('allday').replaceChildren(...(pending.length ? [document.createTextNode('Bekleyen: ')] : []),
    ...pending.flatMap((p, i) => [el('b', '', `${p.qty}× ${p.name}`), document.createTextNode(i < pending.length - 1 ? ', ' : '')]));
}

// Saat ve geçen süreler her saniye güncellenir (kartlar yeniden çizilmez).
setInterval(() => {
  $('clock').textContent = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  const { warnMinutes, lateMinutes } = state.modules.kds;
  let colorChanged = false;
  for (const c of document.querySelectorAll('.ticket')) {
    const t = state.tickets.get(c.dataset.id);
    if (!t) continue;
    c.querySelector('.elapsed').textContent = formatElapsed(Date.now() - Date.parse(t.createdAt));
    if (!t.cancelled && !c.classList.contains(ageClass(t.createdAt, Date.now(), warnMinutes, lateMinutes))) {
      colorChanged = true;
    }
  }
  if (colorChanged) render(); // sarıya / kırmızıya dönen kart
}, 1000);
