// Müşteri uygulamasının (Flutter web) tarayıcıda uçtan uca testi: emülatörler + Playwright.
//
// Önce:  cd mobile && flutter build web --release --no-web-resources-cdn   (assets/brand.json: emulator.enabled true)
// Sonra (firebase/ klasöründen):
//   firebase emulators:exec --project demo-nexpos --only auth,firestore,functions \
//     "node tests/app.browser.js [ekran-goruntusu-klasoru]"
//
// www.gstatic.com'a erişilemeyen ortamda (ör. kapalı ağ) Firebase JS SDK'yı yerelden vermek için:
//   FIREBASE_JS_DIR=<firebase@13 npm paketinin klasörü> (firebase-app.js, firebase-auth.js… içerir)
//
// Kasada telefonla üye olmuş, damgası ve ödülü olan müşteri aynı numarayla uygulamaya girer; kartı, kampanyayı,
// menüyü, ürün ayrıntısını ve QR'ı görür; QR kasada (terminal) bir kez okunur.
const assert = require('node:assert/strict');
const fs = require('fs');
const http = require('http');
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

const WEB = path.join(__dirname, '../../mobile/build/web');
const PORT = 8091;
const SHOTS = process.argv[2];
const OWNER = { email: 'app-tarayici@kafe.test', password: 'sahip-sifre-1', name: 'Uygulama Sahibi', pin: '482919' };
const PHONE = '0532 777 00 11';
let seq = 0;

function serve() {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm',
    '.png': 'image/png', '.ttf': 'font/ttf', '.otf': 'font/otf', '.css': 'text/css', '.symbols': 'text/plain' };
  return http.createServer((req, res) => {
    let file = path.join(WEB, decodeURIComponent(req.url.split('?')[0]));
    if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(WEB, 'index.html');
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  }).listen(PORT);
}

// Hazır tat profili şablonları (Menü → ürün → Tat Profili)
const TEMPLATES = require('../functions/src/flavor_templates.json').templates;
const flavor = (name) => TEMPLATES.find((t) => t.name === name).flavor;

async function seed() {
  createOwner(OWNER);
  const owner = await signedInAs(OWNER.email, OWNER.password);
  const { staffId: cashier } = await owner.call('manageStaff', { action: 'create', name: 'Kasa A', role: 'cashier', pin: '640231' });
  await owner.call('saveModules', { loyalty: { enabled: true }, campaigns: { enabled: true },
    app: { enabled: true, tableOrders: true, pickup: true } });
  const { id: areaId } = await owner.call('saveArea', { name: 'Tarayıcı Salonu' });
  const plan = await owner.call('saveFloorPlan', { areaId, expectedVersion: 0, fixtures: [], tables: [{ tempId: 'w4', name: '4',
    shape: 'square', capacity: 4, x: 60, y: 60, w: 120, h: 120, rotation: 0 }] });
  const table = { id: plan.created.w4, t: (await adminDb.doc(`tables/${plan.created.w4}`).get()).data().qrToken };
  await owner.call('saveAppSettings', { cafeName: 'Velvet Kafe', address: 'Moda Cad. 12, Kadıköy', phone: '0216 000 00 00',
    instagram: '@velvetkafe', hours: 'Her gün 08:00 – 24:00', kvkkText: 'Velvet Kafe olarak kişisel verilerinizi…' });
  await owner.call('saveLoyaltySettings', { stampsForReward: 10, rewardMaxValue: 9000,
    tiers: [{ name: 'Bronz' }, { name: 'Gümüş', minStamps: 50, perks: 'Ayda 1 ücretsiz boy büyütme' }, { name: 'Altın', minStamps: 150 }] });
  const { id: kahve } = await owner.call('saveCategory', { name: 'Kahveler', station: 'bar', stampEligible: true });
  const { id: tatli } = await owner.call('saveCategory', { name: 'Tatlılar', station: 'kitchen' });
  const { id: sut } = await owner.call('saveOptionGroup', { name: 'Süt', selection: 'single', options: [
    { id: 'normal', name: 'Normal süt', priceDelta: 0 }, { id: 'oat', name: 'Yulaf sütü', priceDelta: 1500 },
    { id: 'lf', name: 'Laktozsuz', priceDelta: 1000 }] });
  const products = {};
  for (const [name, categoryId, price, extra] of [
    ['Latte', kahve, 9500, { description: 'Çift shot espresso, ipeksi süt köpüğü', optionGroupIds: [sut], allergens: ['milk'],
      calories: 190, caffeineMg: 128, flavor: flavor('Latte') }],
    ['Flat White', kahve, 10000, { description: 'Daha yoğun, az köpüklü', optionGroupIds: [sut], allergens: ['milk'],
      flavor: flavor('Flat White') }],
    ['Americano', kahve, 8500, { description: 'Espresso ve sıcak su', caffeineMg: 128, flavor: flavor('Americano') }],
    ['Cold Brew', kahve, 11000, { description: '18 saat soğuk demleme', flavor: flavor('Cold Brew') }],
    ['Mocha', kahve, 11500, { description: 'Espresso, bitter çikolata ve süt', allergens: ['milk'], flavor: flavor('Mocha') }],
    ['Cheesecake', tatli, 14000, { description: 'Limonlu, bisküvi tabanlı', allergens: ['milk', 'gluten', 'egg'] }],
    ['Brownie', tatli, 12000, { description: 'Bitter çikolatalı, cevizli', allergens: ['gluten', 'nuts', 'egg'] }],
  ]) {
    products[name] = (await owner.call('saveProduct', { categoryId, name, price, ...extra })).id;
  }
  await owner.call('saveCampaign', { name: 'Happy Hour', type: 'percent', value: 20, appliesTo: { categoryIds: [kahve] },
    schedule: { days: [1, 2, 3, 4, 5, 6, 7] }, showInApp: true, description: 'Bütün kahvelerde' });
  await owner.call('saveCampaign', { name: 'Öğrenci Menüsü', type: 'bundle',
    bundle: { productIds: [products.Latte, products.Brownie], price: 17000 }, schedule: { days: [1, 2, 3, 4, 5] },
    showInApp: true, description: 'Latte + Brownie' });
  // Kasada telefonla üyelik, 2 latte ödenmiş (8 + 2 → ödül), her zamankinden siparişi
  const reg = await owner.call('registerTerminal', { name: 'Uygulama Testi Kasa' });
  const term = client();
  await signInWithCustomToken(term.auth, reg.customToken);
  const at = new Date().toISOString();
  const op = (name, payload) => ({ opId: `ab-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId: cashier, createdAt: at });
  const day = at.slice(0, 10);
  const r = (await term.call('syncOps', { ops: [
    op('customerCreate', { customerId: 'WEB1', name: 'Ayşe Kaya', phone: PHONE, marketingConsent: false, birthDate: null }),
    op('openOrder', { orderId: 'WO1', no: 'A12', businessDay: day, type: 'takeaway' }),
    op('addItems', { orderId: 'WO1', items: [{ lineId: 'l1', productId: products.Latte, name: 'Latte', unitPrice: 9500, qty: 2,
      station: 'bar', stampEligible: true, options: [{ groupId: sut, optionId: 'oat', name: 'Yulaf sütü', priceDelta: 1500 }] }] }),
    op('sendItems', { orderId: 'WO1', lineIds: ['l1'], ticketIds: { bar: 'WO1-b' } }),
    op('setCustomer', { orderId: 'WO1', customer: { id: 'WEB1', name: 'Ayşe Kaya' } }),
    op('takePayment', { orderId: 'WO1', paymentId: 'WP1', method: 'card', amount: 22000 }),
  ] })).results;
  assert.ok(r.every((x) => x.status === 'ok'), JSON.stringify(r));
  await adminDb.doc('customers/WEB1').update({ stamps: 7, lifetimeStamps: 57, tier: 'silver' });
  return { term, table, cashier, products };
}

async function smsCode() {
  const res = await fetch('http://127.0.0.1:9099/emulator/v1/projects/demo-nexpos/verificationCodes');
  const codes = (await res.json()).verificationCodes || [];
  return codes[codes.length - 1].code;
}

async function main() {
  const { term, table, cashier, products } = await seed();
  const server = serve();
  const browser = await playwright.chromium.launch();
  const logs = [];
  // Her müşteri ayrı bir telefon/tarayıcı: yeni bağlam (oturum ve depolama boş)
  const openPage = async () => {
    const p = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, ignoreHTTPSErrors: true, locale: 'tr-TR' });
    if (process.env.FIREBASE_JS_DIR) {
      await p.route('https://www.gstatic.com/firebasejs/**', (route) => {
        const file = path.join(process.env.FIREBASE_JS_DIR, path.basename(new URL(route.request().url()).pathname));
        if (!fs.existsSync(file)) return route.abort();
        return route.fulfill({ status: 200, contentType: 'text/javascript', body: fs.readFileSync(file) });
      });
    }
    p.on('console', (m) => logs.push(`${m.type()}: ${m.text()}`));
    p.on('pageerror', (e) => logs.push(`pageerror: ${e.message}`));
    return p;
  };
  let page = await openPage();
  const shot = async (name) => SHOTS && page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  const settle = (ms = 800) => page.waitForTimeout(ms);
  try {
    await page.goto(`http://127.0.0.1:${PORT}/`);
    await page.waitForSelector('flt-semantics-placeholder, flt-glass-pane, flutter-view', { timeout: 60000, state: 'attached' });
    await settle(4000);
    await page.evaluate(() => document.querySelector('flt-semantics-placeholder')?.click());
    await settle(1500);
    const button = (name, exact = false) => page.getByRole('button', { name, exact }).first();
    const input = (i) => page.locator('input, textarea').nth(i);
    const type = async (i, text) => {
      await input(i).click();
      await settle(500); // Flutter odaklanınca kendi düzenleme alanını kurar; ilk tuş kaybolmasın
      await page.keyboard.type(text, { delay: 30 });
    };
    // Flutter yazıları erişilebilirlik ağacında metin ya da aria-label olarak bulunur
    // Kartlar gibi "button" rolü olmayan dokunulabilir alanlar: yazının bulunduğu yere dokun
    const tapText = async (text) => {
      const box = await page.evaluate((t) => {
        const all = [...document.querySelectorAll('flt-semantics')];
        const el = all.reverse().find((e) => (e.getAttribute('aria-label') || '').includes(t)
          || [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.includes(t)) || e.textContent.includes(t));
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      }, text);
      assert.ok(box, `ekranda yok: ${text}`);
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    };
    const seen = (text, timeout = 20000) => page.waitForFunction((t) => document.body.textContent.includes(t)
      || [...document.querySelectorAll('[aria-label]')].some((e) => e.getAttribute('aria-label').includes(t)), text, { timeout });
    await shot('01_giris');
    // ---- Giriş: telefon → SMS kodu (emülatör) → kasadaki üyelik aynı numarayla bağlanır
    await type(0, PHONE);
    await button('Kod gönder').click();
    await seen('numarasına gelen kod');
    const code = await smsCode();
    await type(0, code);
    await shot('02_kod');
    await button('Giriş yap', true).click();
    await seen('7 / 10 damga', 40000);
    await settle(1500);
    await shot('03_ana_sayfa');
    const linked = (await adminDb.doc('customers/WEB1').get()).data();
    assert.ok(linked.authUid, 'üyelik uygulama hesabına bağlanmadı');
    for (const t of ['Ayşe', 'Gümüş', 'Happy Hour', 'Öğrenci Menüsü', 'Her zamankinden', '2× Latte', 'Moda Cad. 12']) await seen(t);
    // ---- QR: 60 sn geçerli, kasada bir kez okunur
    await button('QR').click();
    await seen('sn sonra yenilenir');
    await settle(1000);
    await shot('04_qr');
    const tokens = await adminDb.collection('loyaltyTokens').where('uid', '==', 'WEB1').get();
    assert.equal(tokens.size, 1);
    const res = await term.call('resolveLoyaltyToken', { token: `KAFE:LOYALTY:${tokens.docs[0].id}` });
    assert.equal(res.customerId, 'WEB1');
    await button('Geri').click();
    await settle(1000);
    // ---- Menü: kampanya fiyatı, tükendi (kasadan), ürün ayrıntısı
    const { id: coldBrew } = (await adminDb.collection('products').where('name', '==', 'Cold Brew').get()).docs[0];
    await term.call('syncOps', { ops: [{ opId: `ab-${String(++seq).padStart(6, '0')}`, op: 'setSoldOut',
      payload: { productId: coldBrew, soldOut: true }, staffId: (await adminDb.collection('staff').where('role', '==', 'cashier').get()).docs[0].id,
      createdAt: new Date().toISOString() }] });
    await page.getByRole('tab', { name: 'Menü' }).or(button('Menü')).first().click();
    await seen('76,00 ₺');
    await seen('Tükendi');
    await settle(1000);
    await shot('05_menu');
    await tapText('Çift shot espresso');
    await seen('128 mg kafein');
    await seen('Yulaf sütü');
    await settle(1000);
    await shot('06_urun');
    await button('Geri').click();
    await settle(800);
    // ---- Profil
    await page.getByRole('tab', { name: 'Profil' }).or(button('Profil')).first().click();
    await seen('Geçmiş siparişler');
    await settle(1500);
    await shot('07_profil');

    // ---- Bana öner (11c): 4 soru → öneri; üyenin önerisi kaydedilir
    await page.getByRole('tab', { name: 'Ana sayfa' }).or(button('Ana sayfa')).first().click();
    await settle(800);
    await button('Bana öner').click();
    await seen('Bugün nasıl hissediyorsun?');
    await settle(600);
    await shot('07a_oneri_soru');
    for (const answer of ['Keyifliyim', 'Evet', 'Sıcak', 'Çikolata']) {
      await button(answer).click();
      await settle(700);
    }
    await seen('Sana önerimiz');
    await seen('Mocha');
    await settle(1000);
    await shot('07b_oneri');
    const recs = await adminDb.collection('customers/WEB1/recommendations').get();
    assert.equal(recs.size, 1);
    await button('Geri').click();
    await settle(800);

    // ---- Masadaki QR (11b): telefonun kamerası masa adresini tarayıcıda açar → menü (girişsiz), garson çağır,
    // sepet; sipariş gönderirken telefonla giriş istenir
    await page.close();
    page = await openPage();
    await page.goto(`http://127.0.0.1:${PORT}/masa/${table.id}?t=${table.t}`);
    await page.waitForSelector('flt-semantics-placeholder, flt-glass-pane, flutter-view', { timeout: 60000, state: 'attached' });
    await settle(4000);
    await page.evaluate(() => document.querySelector('flt-semantics-placeholder')?.click());
    await settle(1500);
    await seen('Masa 4 · Velvet Kafe', 40000);
    // Emülatörün alttaki uyarı şeridi düğmelerin üstüne biniyor (canlıda yok)
    await page.addStyleTag({ content: '.firebase-emulator-warning { display: none !important; }' });
    await seen('Çift shot espresso');
    await button('Garson çağır').click();
    await seen('Çağrın iletildi');
    const call = (await adminDb.doc(`tableCalls/${table.id}_waiter`).get()).data();
    assert.deepEqual([call.status, call.tableName], ['open', '4']);
    await settle(1000);
    await shot('08_masa_menu');
    await page.waitForTimeout(4500); // bildirim kapansın
    await tapText('Çift shot espresso');
    await seen('Sepete ekle');
    await tapText('Yulaf sütü');
    await seen('Sepete ekle · 110,00 ₺');
    await button('Sepete ekle').click();
    await seen('Sepet · 1 ürün');
    await settle(800);
    await tapText('Sepet · 1 ürün');
    await seen('Siparişi gönder · Masa 4');
    await settle(800);
    await shot('09_sepet');
    await button('Siparişi gönder').click();
    // Misafir: sipariş gönderirken giriş istenir; sepet korunur
    await seen('Telefon numaran');
    {
      await page.waitForTimeout(4500);
      await type(0, PHONE);
      await button('Kod gönder').click();
      await seen('numarasına gelen kod');
      await type(0, await smsCode());
      await button('Giriş yap', true).click();
      await seen('Sepet · 1 ürün', 40000);
      await settle(800);
      await tapText('Sepet · 1 ürün');
      await seen('Siparişi gönder · Masa 4');
      await button('Siparişi gönder').click();
    }
    await seen('Siparişin alındı', 30000);
    await settle(1000);
    await shot('10_gonderildi');
    const reqs = await adminDb.collection('appOrders').where('customerId', '==', 'WEB1').get();
    assert.equal(reqs.size, 1);
    const req = reqs.docs[0];
    assert.deepEqual([req.data().status, req.data().total, req.data().tableId, req.data().items[0].options[0].name],
      ['pending', 11000, table.id, 'Yulaf sütü']);
    // Kasa (NexPOS) onaylar: adisyonu kuyruktan açar, fişi gönderir; bar "Hazır" der
    const at = new Date().toISOString();
    const op = (name, payload) => ({ opId: `ab-${String(++seq).padStart(6, '0')}`, op: name, payload, staffId: cashier, createdAt: at });
    const it = req.data().items[0];
    await term.call('syncOps', { ops: [
      op('openOrder', { orderId: 'WO2', no: 'A13', businessDay: at.slice(0, 10), type: 'dine_in', tableId: table.id, tableName: '4' }),
      op('addItems', { orderId: 'WO2', items: [{ lineId: 'm1', productId: it.productId, name: it.name, unitPrice: it.unitPrice,
        qty: it.qty, options: it.options, station: 'bar', stampEligible: true }] }),
      op('sendItems', { orderId: 'WO2', lineIds: ['m1'], ticketIds: { bar: 'WO2-b' } }),
    ] });
    await term.call('acceptAppOrder', { id: req.id, orderId: 'WO2', orderNo: 'A13', ticketIds: ['WO2-b'] });
    await seen('Hazırlanıyor', 30000);
    await term.call('syncOps', { ops: [op('updateTicket', { ticketId: 'WO2-b', status: 'ready' })] });
    await seen('Birazdan masanda', 30000);
    await settle(800);
    await shot('11_hazir');
    assert.ok(products.Latte);
  } catch (e) {
    await shot('hata').catch(() => {});
    throw e;
  } finally {
    if (SHOTS) fs.writeFileSync(path.join(SHOTS, 'browser.log'), logs.join('\n'));
    await browser.close();
    server.close();
    await closeAll();
  }
  console.log('app.browser: tamam');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
