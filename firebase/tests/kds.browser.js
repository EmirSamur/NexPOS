// Mutfak ekranının tarayıcıda uçtan uca testi (Playwright + emülatörler, Hosting dahil).
//
// Çalıştırma (firebase/ klasöründen):
//   firebase emulators:exec --project demo-nexpos --only auth,firestore,functions,hosting \
//     "node tests/kds.browser.js [ekran-goruntusu-klasoru]"
// Playwright yoksa: npm i -g playwright (tarayıcı: PLAYWRIGHT_BROWSERS_PATH ya da npx playwright install chromium)
const assert = require('node:assert/strict');
const path = require('path');
const { execSync } = require('child_process');
const { adminDb, createOwner, client, signedInAs, closeAll } = require('./helpers');
const { signInWithCustomToken } = require('firebase/auth');

let playwright;
try {
  playwright = require('playwright');
} catch {
  playwright = require(path.join(execSync('npm root -g').toString().trim(), 'playwright'));
}

const URL = 'http://127.0.0.1:5005/mutfak';
const SHOTS = process.argv[2];
const OWNER = { email: 'kds-tarayici@kafe.test', password: 'sahip-sifre-1', name: 'Tarayıcı Sahibi', pin: '482913' };
const AT = () => new Date().toISOString();
let seq = 0;

async function main() {
  createOwner(OWNER);
  const owner = await signedInAs(OWNER.email, OWNER.password);
  const { staffId: waiter } = await owner.call('manageStaff', { action: 'create', name: 'Garson T', role: 'waiter', pin: '730591' });
  const { staffId: manager } = await owner.call('manageStaff', { action: 'create', name: 'Müdür T', role: 'manager',
    email: 'kds-t-mudur@kafe.test', password: 'mudur-sifre-1', pin: '583920' });
  await owner.call('saveModules', { kds: { enabled: true, warnMinutes: 10, lateMinutes: 20, sound: true } });
  const reg = await owner.call('registerTerminal', { name: 'Tarayıcı Kasa' });
  const pos = client();
  await signInWithCustomToken(pos.auth, reg.customToken);
  const op = (name, payload, createdAt = AT()) => ({ opId: `kb-${String(++seq).padStart(6, '0')}`, op: name, payload,
    staffId: waiter, createdAt });
  const sync = async (...ops) => {
    const r = (await pos.call('syncOps', { ops })).results;
    assert.ok(r.every((x) => x.status === 'ok'), JSON.stringify(r));
  };
  const item = (lineId, name, station, qty = 1, extra = {}) =>
    ({ lineId, productId: null, name, unitPrice: 5000, qty, station, ...extra });
  // Masasız (paket) adisyon: aç, ekle, gönder. minutesAgo: fişin ne kadar önce gönderildiği
  async function sendOrder(id, no, items, minutesAgo = 0) {
    const at = new Date(Date.now() - minutesAgo * 60000).toISOString();
    await sync(op('openOrder', { orderId: id, no, businessDay: '2026-10-15', type: 'takeaway' }, at),
      op('addItems', { orderId: id, items }, at),
      op('sendItems', { orderId: id, lineIds: items.map((i) => i.lineId),
        ticketIds: { kitchen: `T-${id}-k`, bar: `T-${id}-b` } }, at));
  }

  const browser = await playwright.chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(URL);
  await page.waitForSelector('#pair:not([hidden])');
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'kds_01_esleme.png') });

  // Hatalı kod
  await page.fill('#pair-code', '000000');
  await page.click('#pair-btn');
  await page.waitForFunction(() => document.querySelector('#pair-error').textContent.length > 0);

  // Eşleme
  const { code } = await owner.call('createKdsPairingCode', { name: 'Mutfak tableti' });
  await page.fill('#pair-code', code);
  await page.check('input[name=station][value=kitchen]');
  await page.click('#pair-btn');
  await page.waitForSelector('#board:not([hidden])', { timeout: 20000 });
  await page.waitForSelector('#empty:not([hidden])');

  // Fişler canlı düşer; gecikenler sarı/kırmızı; bar fişi mutfak ekranında görünmez
  await sendOrder('B1', 'A41', [item('t', 'Tost', 'kitchen', 2, { note: 'bol kaşarlı' }),
    item('m', 'Menemen', 'kitchen'), item('l', 'Latte', 'bar')]);
  await page.waitForSelector('.ticket[data-id="T-B1-k"]', { timeout: 15000 });
  await sendOrder('B2', 'A42', [item('t2', 'Tost', 'kitchen'), item('o', 'Omlet', 'kitchen',
    1, { options: [{ groupId: 'g', optionId: 'o', name: 'Kaşarlı', priceDelta: 0 }] })], 12);
  await sendOrder('B3', 'A43', [item('k', 'Köfte', 'kitchen')], 25);
  await page.waitForSelector('.ticket[data-id="T-B3-k"]');
  assert.equal(await page.locator('.ticket[data-id="T-B1-b"]').count(), 0, 'bar fişi mutfakta görünmemeli');
  assert.ok(await page.locator('.ticket[data-id="T-B2-k"]').evaluate((e) => e.classList.contains('warn')));
  assert.ok(await page.locator('.ticket[data-id="T-B3-k"]').evaluate((e) => e.classList.contains('late')));
  // En eski üstte
  const order = await page.locator('.ticket').evaluateAll((els) => els.map((e) => e.dataset.id));
  assert.deepEqual(order, ['T-B3-k', 'T-B2-k', 'T-B1-k']);
  // Toplu bekleyen
  assert.match(await page.textContent('#allday'), /3× Tost/);

  // Satır işaretleme → bulutta doneLineIds
  await page.locator('.ticket[data-id="T-B1-k"] li').first().click();
  await waitFor(async () => (await ticket('T-B1-k')).doneLineIds?.includes('t'));
  assert.match(await page.textContent('#allday'), /1× Tost/);

  // İptal edilen ürün fişte İPTAL
  await sync(op('voidItem', { orderId: 'B1', lineId: 'm', reason: 'Vazgeçti', approvedBy: manager }));
  await page.waitForSelector('.ticket[data-id="T-B1-k"] li.voided');
  await assertButtonsClickable(page);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'kds_02_pano.png') });

  // Başla → Hazır → Geri al
  await page.locator('.ticket[data-id="T-B2-k"] button', { hasText: 'Başla' }).click();
  await waitFor(async () => (await ticket('T-B2-k')).status === 'preparing');
  await page.waitForFunction(() => document.querySelector('.ticket[data-id="T-B2-k"] .state').textContent === 'HAZIRLANIYOR');
  await page.locator('.ticket[data-id="T-B2-k"] button', { hasText: 'Hazır' }).click();
  await waitFor(async () => (await ticket('T-B2-k')).status === 'ready');
  assert.equal(await page.locator('.ticket[data-id="T-B2-k"]').count(), 0);
  await page.click('#undo-btn');
  await waitFor(async () => (await ticket('T-B2-k')).status === 'preparing');
  await page.waitForSelector('.ticket[data-id="T-B2-k"]');
  // Filtre
  await page.click('.filters button[data-filter="preparing"]');
  assert.deepEqual(await page.locator('.ticket').evaluateAll((els) => els.map((e) => e.dataset.id)), ['T-B2-k']);
  await page.click('.filters button[data-filter="all"]');

  // Telefon genişliği: yatay kaydırma yok
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  assert.equal(overflow, false, 'telefonda yatay kaydırma olmamalı');
  await assertButtonsClickable(page);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'kds_03_telefon.png') });
  await page.setViewportSize({ width: 1280, height: 800 });

  // Modül kapatılınca ekran bilgi verir
  await owner.call('saveModules', { kds: { enabled: false } });
  await page.waitForSelector('#message:not([hidden])');
  assert.match(await page.textContent('#message-title'), /modülü kapalı/);
  await owner.call('saveModules', { kds: { enabled: true } });
  await page.waitForSelector('#board:not([hidden])');

  // Sayfa yenilenince eşleme korunur
  await page.reload();
  await page.waitForSelector('#board:not([hidden])', { timeout: 20000 });

  // Panelden iptal → ekran kilitlenir
  const kds = (await adminDb.collection('terminals').where('kind', '==', 'kds').get()).docs[0];
  await owner.call('revokeTerminal', { terminalId: kds.id });
  await page.waitForSelector('#message:not([hidden])', { timeout: 20000 });
  assert.match(await page.textContent('#message-title'), /iptal edildi/);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'kds_04_iptal.png') });

  assert.deepEqual(errors, [], `sayfa hataları: ${errors.join('; ')}`);
  await browser.close();
  console.log('Mutfak ekranı tarayıcı testi: TAMAM');
}

// Her kartın düğmeleri görünür ve tıklanabilir olmalı (kartlar üst üste binmemeli)
async function assertButtonsClickable(page) {
  const ids = await page.locator('.ticket').evaluateAll((els) => els.map((e) => e.dataset.id));
  for (const id of ids) {
    const button = page.locator(`.ticket[data-id="${id}"] .actions button`).last();
    await button.scrollIntoViewIfNeeded();
    const hit = await button.evaluate((b) => {
      const r = b.getBoundingClientRect();
      return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === b;
    });
    assert.ok(hit, `${id} kartının düğmesi başka bir öğenin altında kalıyor`);
  }
}

async function ticket(id) {
  return (await adminDb.doc(`kitchenTickets/${id}`).get()).data() || {};
}

async function waitFor(cond, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await cond()) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('zaman aşımı');
}

main().then(closeAll, async (e) => {
  console.error(e);
  await closeAll();
  process.exit(1);
});
