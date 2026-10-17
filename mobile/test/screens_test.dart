// Ekran testleri (FakeRepo ile): giriş → profil → kart, mevcut üyelik, menü, ürün, QR, profil, hesabı silme.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kafe_app/brand.dart';
import 'package:kafe_app/main.dart';
import 'package:kafe_app/models.dart';
import 'package:kafe_app/state.dart';
import 'package:kafe_app/ui/profile.dart';

import 'fake_repo.dart';

const brand = Brand(appName: 'Velvet Kafe', slogan: 'Kahven seni bekliyor', primary: Color(0xFF6B4226), accent: Color(0xFFE8A15A));

const menu = MenuData(
  categories: [Category(id: 'kahve', name: 'Kahveler', stampEligible: true), Category(id: 'tatli', name: 'Tatlılar')],
  products: [
    Product(id: 'latte', categoryId: 'kahve', name: 'Latte', price: 9500, description: 'Espresso ve süt',
        optionGroupIds: ['sut'], allergens: ['milk'], calories: 190, caffeineMg: 75,
        flavor: Flavor(dims: {'strength': 2, 'sweetness': 2, 'acidity': 1, 'body': 3}, milk: true)),
    Product(id: 'mocha', categoryId: 'kahve', name: 'Mocha', price: 11000, soldOut: true,
        flavor: Flavor(dims: {'strength': 2, 'sweetness': 4, 'acidity': 1, 'body': 4}, milk: true, notes: ['çikolata'])),
    Product(id: 'espresso', categoryId: 'kahve', name: 'Espresso', price: 6000,
        flavor: Flavor(dims: {'strength': 5, 'sweetness': 1, 'acidity': 3, 'body': 4})),
    Product(id: 'kek', categoryId: 'tatli', name: 'Kek', price: 7000),
  ],
  optionGroups: {
    'sut': OptionGroup(id: 'sut', name: 'Süt', options: [
      OptionItem(id: 'normal', name: 'Normal'),
      OptionItem(id: 'oat', name: 'Yulaf sütü', priceDelta: 1500),
      OptionItem(id: 'lf', name: 'Laktozsuz', priceDelta: 1000, available: false),
    ]),
  },
);

const happyHour = Campaign(id: 'hh', name: 'Happy Hour', type: 'percent', value: 20, categoryIds: ['kahve'],
    from: '14:00', to: '17:00', description: 'Bütün kahvelerde');

Future<(FakeRepo, AppState)> pump(WidgetTester tester, {Customer? existing, List<Reward> rewards = const [],
    List<PastOrder> orders = const [], (String, String)? table, OrderingInfo? ordering}) async {
  tester.view.physicalSize = const Size(1170, 2532);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  final repo = FakeRepo(menuData: menu, campaignList: const [happyHour], existing: existing)
    ..rewardList = rewards
    ..orders = orders;
  if (ordering != null) repo.ordering = ordering;
  final state = AppState(brand, repo, clock: () => DateTime(2026, 10, 16, 15, 0));
  if (table != null) await state.openTable(table.$1, table.$2);
  state.start();
  await tester.pumpWidget(KafeApp(state: state));
  await tester.pumpAndSettle();
  return (repo, state);
}

Future<void> login(WidgetTester tester) async {
  await tester.enterText(find.byKey(const Key('phone')), '0532 111 22 33');
  await tester.tap(find.byKey(const Key('sendCode')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('code')), '123456');
  await tester.tap(find.byKey(const Key('confirmCode')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('yeni müşteri: SMS kodu → profil (KVKK zorunlu) → kart', (tester) async {
    final (repo, _) = await pump(tester);
    expect(find.text('Velvet Kafe'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('phone')), '123');
    await tester.tap(find.byKey(const Key('sendCode')));
    await tester.pump();
    expect(find.text('Telefon numarası geçersiz.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('phone')), '0532 111 22 33');
    await tester.tap(find.byKey(const Key('sendCode')));
    await tester.pumpAndSettle();
    expect(repo.sentTo, '+905321112233');
    await tester.enterText(find.byKey(const Key('code')), '000000');
    await tester.tap(find.byKey(const Key('confirmCode')));
    await tester.pumpAndSettle();
    expect(find.text('Kod hatalı.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('code')), '123456');
    await tester.tap(find.byKey(const Key('confirmCode')));
    await tester.pumpAndSettle();
    expect(find.text('Hoş geldin!'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('name')), 'Can Bulut');
    await tester.tap(find.byKey(const Key('saveProfile')));
    await tester.pump();
    expect(find.text('Devam etmek için aydınlatma metnini onayla.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('kvkk')));
    await tester.tap(find.byKey(const Key('saveProfile')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Can'), findsWidgets);
    expect(find.text('0 / 10 damga'), findsOneWidget);
    expect(find.text('10 kahve sonra bir içecek bizden'), findsOneWidget);
  });

  testWidgets('kasada açılmış üyelik: kart, ödül, seviye, kampanya, her zamankinden', (tester) async {
    await pump(tester,
        existing: const Customer(id: 'c1', name: 'Ayşe Kaya', stamps: 7, lifetimeStamps: 57, tier: 'silver', birthDate: '10-18'),
        rewards: const [
          Reward(id: 'r1', type: 'free_drink', status: 'active', expiresAt: '2026-12-01'),
          Reward(id: 'r2', type: 'free_drink', status: 'used', expiresAt: '2026-12-01'),
        ],
        orders: const [PastOrder(id: 'o1', no: 'A4', businessDay: '2026-10-11', total: 19000, items: [PastItem(name: 'Latte', qty: 2)])]);
    await login(tester);
    expect(find.text('İyi günler Ayşe 👋'), findsOneWidget);
    expect(find.text('7 / 10 damga'), findsOneWidget);
    expect(find.text('⭐ Gümüş'), findsOneWidget);
    expect(find.textContaining('1 ödülün var'), findsOneWidget);
    expect(find.text('Doğum günün kutlu olsun!'), findsOneWidget);
    expect(find.text('Altın seviyesine 93 damga kaldı'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Happy Hour'), 200);
    expect(find.text('2× Latte'), findsOneWidget);
    expect(find.text('Şimdi'), findsOneWidget);
  });

  testWidgets('QR ekranı: dinamik QR ve yenileme', (tester) async {
    final (repo, _) = await pump(tester, existing: const Customer(id: 'c1', name: 'Ayşe', stamps: 2));
    await login(tester);
    await tester.tap(find.text('QR\'ımı göster'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byKey(const Key('qr')), findsOneWidget);
    expect(repo.qrCount, 1);
    for (var i = 0; i < 56; i++) {
      await tester.pump(const Duration(seconds: 1));
    }
    expect(repo.qrCount, 2); // süresi dolmadan yenilendi
    Navigator.of(tester.element(find.byKey(const Key('qr')))).pop();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('qr')), findsNothing);
  });

  testWidgets('misafir menü: kampanya fiyatı, tükendi, favori, ürün detayı', (tester) async {
    final (repo, _) = await pump(tester);
    await tester.tap(find.byKey(const Key('guest')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Menü'));
    await tester.pumpAndSettle();
    expect(find.text('76,00 ₺'), findsOneWidget); // Happy Hour: 95 → 76
    expect(find.text('Tükendi'), findsOneWidget);
    await tester.tap(find.byTooltip('Favorilere ekle').first);
    await tester.pumpAndSettle();
    expect(repo.favs, {'latte'});
    expect(find.text('♥ Favoriler'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('search')), 'kek');
    await tester.pumpAndSettle();
    expect(find.text('Kek'), findsOneWidget);
    expect(find.text('Latte'), findsNothing);
    await tester.enterText(find.byKey(const Key('search')), '');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Latte'));
    await tester.pumpAndSettle();
    expect(find.text('Yulaf sütü (+15,00 ₺)'), findsOneWidget);
    expect(find.text('Süt'), findsWidgets);
    await tester.dragUntilVisible(find.text('190 kcal'), find.byType(ListView).last, const Offset(0, -200));
    expect(find.text('190 kcal'), findsOneWidget);
    expect(find.text('75 mg kafein'), findsOneWidget);
    expect(find.text('☕ Bu ürün sadakat kartına damga kazandırır.'), findsOneWidget);
  });

  testWidgets('profil: bildirim izni, geçmiş siparişler, hesabı silme', (tester) async {
    final (repo, state) = await pump(tester,
        existing: const Customer(id: 'c1', name: 'Ayşe Kaya', stamps: 3, phoneMasked: '0532 *** ** 33'),
        orders: const [PastOrder(id: 'o1', no: 'A4', businessDay: '2026-10-11', total: 19000, stamps: 2, items: [PastItem(name: 'Latte', qty: 2)])]);
    await login(tester);
    await tester.tap(find.text('Profil'));
    await tester.pumpAndSettle();
    expect(find.textContaining('0532 *** ** 33'), findsOneWidget);
    expect(find.text('7 damga sonra ilk ödülün gelir.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('profileConsent')));
    await tester.pumpAndSettle();
    expect(state.customer!.marketingConsent, isTrue);
    await tester.scrollUntilVisible(find.byKey(const Key('deleteAccount')), 300,
        scrollable: find.descendant(of: find.byType(ProfileTab), matching: find.byType(Scrollable)).first);
    await tester.pumpAndSettle();
    expect(find.text('11 Ekim · 190,00 ₺ · +2 damga'), findsOneWidget);
    await tester.tap(find.byKey(const Key('deleteAccount')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirmDelete')));
    await tester.pumpAndSettle();
    expect(repo.deleted, isTrue);
    expect(state.phase, Phase.signedOut);
    expect(state.customerId, isNull);
    expect(find.byKey(const Key('phone')), findsOneWidget); // giriş ekranına döndü
  });

  testWidgets('masadaki QR: menüden başlar, seçenekli ürün sepete, giriş, siparişi gönder, durum ve hazır bildirimi',
      (tester) async {
    final (repo, state) = await pump(tester, table: ('t4', 'tok4'));
    // Giriş ekranı atlanır: misafir doğrudan menüyü görür
    expect(find.text('Masa 4 · Velvet Kafe'), findsOneWidget);
    expect(find.text('Latte'), findsOneWidget); // menü sekmesi açık
    // Garson çağır: girişsiz de olur, tekrar basınca çoğalmaz
    await tester.tap(find.text('Garson çağır'));
    await tester.pumpAndSettle();
    expect(find.text('Çağrın iletildi, garson geliyor.'), findsOneWidget);
    await tester.tap(find.text('Garson çağır'));
    await tester.pumpAndSettle();
    expect(find.text('Çağrın zaten iletildi, garson geliyor.'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5)); // bildirim kapansın
    await tester.pumpAndSettle();

    await tester.tap(find.text('Latte'));
    await tester.pumpAndSettle();
    expect(find.text('Sepete ekle · 95,00 ₺'), findsOneWidget);
    await tester.tap(find.text('Yulaf sütü (+15,00 ₺)'));
    await tester.tap(find.byTooltip('Artır'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('addToCart')));
    await tester.pumpAndSettle();
    expect(find.text('Sepet · 2 ürün'), findsOneWidget);
    expect(find.text('220,00 ₺'), findsOneWidget);

    await tester.tap(find.byKey(const Key('cartBar')));
    await tester.pumpAndSettle();
    expect(find.text('Yulaf sütü'), findsOneWidget);
    expect(find.text('Siparişi gönder · Masa 4'), findsOneWidget);
    await tester.tap(find.byKey(const Key('sendOrder')));
    await tester.pumpAndSettle();
    // Misafir: giriş ekranı açılır, sepet korunur
    expect(find.byKey(const Key('phone')), findsOneWidget);
    expect(state.cartCount, 2);
    repo.existing = const Customer(id: 'c1', name: 'Ayşe Kaya');
    await login(tester);
    await tester.pump(const Duration(seconds: 5)); // "giriş yap" bildirimi kapansın
    await tester.pumpAndSettle();
    expect(find.text('Sepet · 2 ürün'), findsOneWidget);
    await tester.tap(find.byKey(const Key('cartBar')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'pencere kenarı');
    await tester.tap(find.byKey(const Key('sendOrder')));
    await tester.pumpAndSettle();
    expect(repo.sent.single, {
      'kind': 'table',
      'items': [
        {'productId': 'latte', 'qty': 2, 'options': [{'groupId': 'sut', 'optionId': 'oat'}]},
      ],
      'tableId': 't4',
      'pickup': null,
      'note': 'pencere kenarı',
      'expectedTotal': 22000,
    });
    expect(state.cart, isEmpty);
    expect(find.text('Siparişin alındı ☕'), findsOneWidget);

    // Kasa onaylar → hazırlanıyor → hazır: bildirim her ekranda
    AppOrder at(String status) => AppOrder(id: 'ao1', kind: 'table', status: status, tableName: '4', orderNo: 'A71',
        total: 22000, createdAt: DateTime(2026, 10, 16, 15), items: const [AppOrderItem('Latte', 2, ['Yulaf sütü'], 22000)]);
    repo.pushOrders([at('preparing')]);
    await tester.pumpAndSettle();
    expect(find.text('Hazırlanıyor ☕'), findsOneWidget);
    expect(find.text('Sipariş no: A71'), findsOneWidget);
    repo.pushOrders([at('ready')]);
    await tester.pumpAndSettle();
    expect(find.text('Hazır 🔔 Birazdan masanda'), findsOneWidget);
    expect(find.text('🔔 Siparişin hazır (A71), birazdan masanda.'), findsOneWidget);
  });

  testWidgets('gel-al: ana sayfadan, saat seçimi; kasa çevrimdışıyken gönderilemez; geçersiz masa QR\'ı', (tester) async {
    final (repo, state) = await pump(tester, existing: const Customer(id: 'c1', name: 'Mert Tan'), table: ('t4', 'yanlis'));
    await login(tester);
    expect(find.text("Masa QR'ı geçersiz."), findsOneWidget);
    await tester.tap(find.text('Tamam'));
    await tester.pumpAndSettle();
    expect(state.table, isNull);
    await tester.tap(find.byKey(const Key('orderPickup')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Tatlılar'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tatlılar'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Kek'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('addToCart')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cartBar')));
    await tester.pumpAndSettle();
    expect(find.text('Gel-al siparişini gönder'), findsOneWidget);
    await tester.tap(find.text('15 dk sonra'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('sendOrder')));
    await tester.pumpAndSettle();
    expect(repo.sent.single['kind'], 'pickup');
    expect(repo.sent.single['pickup'], {'inMinutes': 15});
    expect(repo.sent.single['expectedTotal'], 7000);
    Navigator.of(tester.element(find.byKey(const Key('orderHeadline')))).pop();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ana sayfa'));
    await tester.pumpAndSettle();
    expect(find.text('Siparişlerim'), findsOneWidget);
    expect(find.text('Gel-al · Onay bekliyor'), findsOneWidget);

    // Kasa çevrimdışı: sepet açılır ama gönderilemez
    repo.ordering = const OrderingInfo(online: false, pickup: true);
    await state.refreshOrdering();
    state.addItem(CartItem(menu.product('kek')!));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cartBar')));
    await tester.pumpAndSettle();
    expect(find.text('Şu an çevrimiçi sipariş alınmıyor.'), findsOneWidget);
    expect(find.byKey(const Key('sendOrder')), findsNothing);
  });

  testWidgets('bana öner: 4 soru → en uyumlu (tükenen önerilmez), kaydedilir, sepete → siparişte öneri kimliği', (tester) async {
    final (repo, state) = await pump(tester, existing: const Customer(id: 'c1', name: 'Ayşe Kaya'));
    await login(tester);
    await tester.tap(find.byKey(const Key('quiz')));
    await tester.pumpAndSettle();
    expect(find.text('Bugün nasıl hissediyorsun?'), findsOneWidget);
    await tester.tap(find.text('Keyifliyim 🙂'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Evet'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sıcak ☕'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Çikolata 🍫'));
    await tester.pumpAndSettle();
    // Mocha en uygunu ama tükendi; Latte önerilir
    expect(find.byKey(const Key('quizTop')), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('quizTop'))).data, 'Latte');
    expect(repo.recLog.single.$1, ['latte']);
    expect(repo.recLog.single.$2, {'mood': 'happy', 'milk': 'yes', 'temp': 'hot', 'taste': 'choc'});
    await tester.tap(find.byKey(const Key('quizPick')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('addToCart')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cartBar')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('sendOrder')));
    await tester.pumpAndSettle();
    expect(repo.sent.single['recommendationId'], 'rec1');

    // Telefon bildirimi: sipariş ekranından izin; uygulama açıkken gelen bildirim görünür
    expect(state.pushEnabled, isFalse);
    await tester.tap(find.byKey(const Key('enablePush')));
    await tester.pumpAndSettle();
    expect(repo.pushAsked, 1);
    expect(state.pushEnabled, isTrue);
    expect(find.byKey(const Key('enablePush')), findsNothing);
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    repo.push('Kartın doldu 🎁', 'Bir içecek bizden.');
    await tester.pumpAndSettle();
    expect(find.text('Kartın doldu 🎁 — Bir içecek bizden.'), findsOneWidget);
  });

  testWidgets('herkese açık gizlilik ve hesap silme sayfaları (mağaza)', (tester) async {
    final repo = FakeRepo(info: const AppInfo(cafeName: 'Velvet Kafe', phone: '0216 000 00 00', kvkkText: 'Aydınlatma metni…'));
    final state = AppState(brand, repo)..start();
    await tester.pumpWidget(KafeApp(state: state, page: 'hesap-sil'));
    await tester.pumpAndSettle();
    expect(find.text('Hesabını ve verilerini silme'), findsOneWidget);
    expect(find.textContaining('0216 000 00 00'), findsOneWidget);
    expect(find.text('Aydınlatma metni…'), findsOneWidget);
  });
}
