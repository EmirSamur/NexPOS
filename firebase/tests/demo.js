// Emülatörde deneme için örnek kafe (docs/DENEME.md). Emülatörler açıkken çalıştırın:
//   cd firebase/tests && node demo.js
// Tekrar çalıştırmak güvenlidir: eksikleri tamamlar, sonda giriş bilgilerini ve masa QR adreslerini yazar.
// Gerçek (canlı) projeye bağlanmaz; yalnızca 127.0.0.1'deki emülatörlere yazar.
const { adminDb, createOwner, signedInAs, closeAll } = require('./helpers');

const WEB = process.env.DEMO_WEB || 'http://127.0.0.1:5005';
const OWNER = { email: 'sahip@demo.kafe', password: 'demo-sifre-1', name: 'Deniz Yılmaz', pin: '482913' };
const STAFF = [
  { name: 'Mert Kaya', role: 'manager', pin: '583920', email: 'mudur@demo.kafe', password: 'demo-sifre-1' },
  { name: 'Selin Ak', role: 'cashier', pin: '640218' },
  { name: 'Cem Akar', role: 'waiter', pin: '730591' },
];
const TEMPLATES = require('../functions/src/flavor_templates.json').templates;
const flavor = (name) => TEMPLATES.find((t) => t.name === name).flavor;

const KVKK = `Velvet Kafe olarak kişisel verilerinizi (ad, telefon, isteğe bağlı doğum günü, sipariş geçmişi) yalnızca
sadakat kartı, sipariş ve - izin verirseniz - kampanya bildirimleri için işliyoruz. Verileriniz üçüncü kişilerle
paylaşılmaz. Hesabınızı uygulamada Profil → Hesabımı sil ile istediğiniz an silebilirsiniz.
(Bu bir deneme metnidir; gerçek kafede Pazarlama → Mobil Uygulama'dan kafenin metni girilir.)`;

async function main() {
  const existing = await adminDb.collection('staff').where('email', '==', OWNER.email).get();
  if (existing.empty) {
    console.log('Örnek kafe kuruluyor…');
    createOwner(OWNER);
    const owner = await signedInAs(OWNER.email, OWNER.password);
    for (const s of STAFF) await owner.call('manageStaff', { action: 'create', ...s });

    await owner.call('saveModules', {
      kds: { enabled: true }, staff: { enabled: true }, loyalty: { enabled: true }, campaigns: { enabled: true },
      app: { enabled: true, tableOrders: true, pickup: true },
    });
    await owner.call('saveGeneralSettings', { cafeName: 'Velvet Kafe', qrBaseUrl: `${WEB}/masa`, idleLockMinutes: 10 });
    await owner.call('saveAppSettings', { cafeName: 'Velvet Kafe', address: 'Moda Cad. 12, Kadıköy / İstanbul',
      phone: '0216 000 00 00', instagram: '@velvetkafe', hours: 'Her gün 08:00 – 24:00', kvkkText: KVKK,
      pickupPrepMinutes: 10, acceptMinutes: 2 });
    await owner.call('saveLoyaltySettings', { stampsForReward: 10, rewardMaxValue: 9000,
      tiers: [{ name: 'Bronz' }, { name: 'Gümüş', minStamps: 50, perks: 'Ayda 1 ücretsiz boy büyütme' },
        { name: 'Altın', minStamps: 150, perks: 'Her siparişte ekstra shot' }] });

    const { id: kahve } = await owner.call('saveCategory', { name: 'Sıcak Kahveler', station: 'bar', stampEligible: true });
    const { id: soguk } = await owner.call('saveCategory', { name: 'Soğuk İçecekler', station: 'bar', stampEligible: true });
    const { id: tatli } = await owner.call('saveCategory', { name: 'Tatlılar', station: 'kitchen' });
    const { id: sut } = await owner.call('saveOptionGroup', { name: 'Süt', selection: 'single', options: [
      { id: 'normal', name: 'Normal süt', priceDelta: 0 }, { id: 'oat', name: 'Yulaf sütü', priceDelta: 1500 },
      { id: 'lf', name: 'Laktozsuz', priceDelta: 1000 }] });
    const { id: boy } = await owner.call('saveOptionGroup', { name: 'Boy', selection: 'single', required: true, options: [
      { id: 's', name: 'Küçük', priceDelta: 0 }, { id: 'm', name: 'Orta', priceDelta: 1000 }, { id: 'l', name: 'Büyük', priceDelta: 2000 }] });
    const milky = { optionGroupIds: [boy, sut], allergens: ['milk'] };
    const products = {};
    for (const [name, categoryId, price, extra] of [
      ['Espresso', kahve, 6000, { description: 'Yoğun, çift shot', caffeineMg: 128, flavor: flavor('Espresso') }],
      ['Americano', kahve, 8500, { description: 'Espresso ve sıcak su', optionGroupIds: [boy], caffeineMg: 128, flavor: flavor('Americano') }],
      ['Latte', kahve, 9500, { description: 'Çift shot espresso, ipeksi süt köpüğü', ...milky, calories: 190, caffeineMg: 128, flavor: flavor('Latte') }],
      ['Cappuccino', kahve, 9500, { description: 'Eşit espresso, süt ve köpük', ...milky, caffeineMg: 128, flavor: flavor('Cappuccino') }],
      ['Flat White', kahve, 10000, { description: 'Daha yoğun, az köpüklü', ...milky, caffeineMg: 128, flavor: flavor('Flat White') }],
      ['Mocha', kahve, 11000, { description: 'Espresso, bitter çikolata ve süt', ...milky, caffeineMg: 95, flavor: flavor('Mocha') }],
      ['Türk Kahvesi', kahve, 7000, { description: 'Lokum ile', caffeineMg: 60, flavor: flavor('Türk kahvesi') }],
      ['Sıcak Çikolata', kahve, 9000, { description: 'Belçika çikolatası', allergens: ['milk'], caffeineMg: 0, flavor: flavor('Sıcak çikolata') }],
      ['Cold Brew', soguk, 11000, { description: '18 saat soğuk demleme', caffeineMg: 150, flavor: flavor('Cold Brew') }],
      ['Iced Latte', soguk, 10500, { description: 'Buzlu latte', ...milky, caffeineMg: 128, flavor: flavor('Iced Latte') }],
      ['Limonata', soguk, 8000, { description: 'Taze sıkım, naneli', caffeineMg: 0, flavor: flavor('Limonata') }],
      ['Cheesecake', tatli, 14000, { description: 'Limonlu, bisküvi tabanlı', allergens: ['milk', 'gluten', 'egg'], calories: 420 }],
      ['Brownie', tatli, 12000, { description: 'Bitter çikolatalı, cevizli', allergens: ['gluten', 'nuts', 'egg'], calories: 380 }],
      ['Kurabiye', tatli, 4500, { description: 'Damla çikolatalı', allergens: ['gluten', 'egg'] }],
    ]) {
      products[name] = (await owner.call('saveProduct', { categoryId, name, price, ...extra })).id;
    }
    await owner.call('saveCampaign', { name: 'Happy Hour', type: 'percent', value: 20, appliesTo: { categoryIds: [kahve, soguk] },
      schedule: { days: [1, 2, 3, 4, 5], from: '14:00', to: '17:00' }, showInApp: true, description: 'Hafta içi 14–17 tüm kahvelerde' });
    await owner.call('saveCampaign', { name: 'Kahve + Brownie', type: 'bundle',
      bundle: { productIds: [products.Latte, products.Brownie], price: 17000 }, schedule: { days: [1, 2, 3, 4, 5, 6, 7] },
      showInApp: true, description: 'Latte ve brownie birlikte 170 ₺' });

    // Kasada üye olmuş bir müşteri: bu numarayla uygulamaya girince kartı dolu gelir
    await adminDb.doc('customers/DEMO1').set({ name: 'Ayşe Kaya', phone: '5327770011', birthDate: null, marketingConsent: true,
      consentAt: new Date().toISOString(), stamps: 7, lifetimeStamps: 57, tier: 'silver', totalSpent: 560000, visitCount: 24,
      lastVisitAt: new Date().toISOString(), source: 'pos', deleted: false, createdAt: new Date(), updatedAt: new Date() });
    await adminDb.doc('customerPhones/5327770011').set({ customerId: 'DEMO1' });
    await adminDb.doc('rewards/DEMO1-r1').set({ customerId: 'DEMO1', type: 'free_drink', status: 'active',
      expiresAt: new Date(Date.now() + 40 * 86400_000).toISOString().slice(0, 10), createdAt: new Date().toISOString(), updatedAt: new Date() });
    console.log('Örnek kafe hazır.\n');
  } else {
    console.log('Örnek kafe zaten kurulu.\n');
  }

  const tables = await adminDb.collection('tables').get();
  const live = tables.docs.filter((d) => d.data().deleted !== true)
    .sort((a, b) => String(a.data().name).localeCompare(String(b.data().name), 'tr', { numeric: true }));
  console.log(`NexPOS bağlama (ilk açılış):  ${OWNER.email}  /  ${OWNER.password}`);
  console.log(`PIN'ler: Yönetici ${OWNER.pin} · Müdür 583920 (mudur@demo.kafe / demo-sifre-1) · Kasa 640218 · Garson 730591`);
  console.log(`Uygulama:  ${WEB}   (üye: 0532 777 00 11 — SMS kodu emülatör penceresinde yazar)`);
  console.log(`Mutfak ekranı:  ${WEB}/mutfak`);
  if (!live.length) {
    console.log('\nMasa yok: NexPOS → Yönetim → Tanımlamalar → Masa / Bölgeler → "Buluta Aktar" yapın,');
    console.log('sonra bu betiği tekrar çalıştırın; masaların QR adresleri burada listelenir.');
  } else {
    console.log('\nMasa QR adresleri (tarayıcıda açın — masadaki QR\'ı okutmak gibi):');
    for (const d of live.slice(0, 12)) console.log(`  ${String(d.data().name).padEnd(10)} ${WEB}/masa/${d.id}?t=${d.data().qrToken}`);
    if (live.length > 12) console.log(`  … ve ${live.length - 12} masa daha (NexPOS'tan QR etiketleri de basılabilir)`);
  }
}

main().then(closeAll, async (e) => {
  console.error(e.message || e);
  await closeAll();
  process.exit(1);
});
