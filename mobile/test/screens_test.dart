// Ekran testleri (FakeRepo ile): giriş → profil → kart, mevcut üyelik, menü, ürün, QR, profil, hesabı silme.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kafe_app/brand.dart';
import 'package:kafe_app/main.dart';
import 'package:kafe_app/models.dart';
import 'package:kafe_app/state.dart';

import 'fake_repo.dart';

const brand = Brand(appName: 'Velvet Kafe', slogan: 'Kahven seni bekliyor', primary: Color(0xFF6B4226), accent: Color(0xFFE8A15A));

const menu = MenuData(
  categories: [Category(id: 'kahve', name: 'Kahveler', stampEligible: true), Category(id: 'tatli', name: 'Tatlılar')],
  products: [
    Product(id: 'latte', categoryId: 'kahve', name: 'Latte', price: 9500, description: 'Espresso ve süt',
        optionGroupIds: ['sut'], allergens: ['milk'], calories: 190, caffeineMg: 75),
    Product(id: 'mocha', categoryId: 'kahve', name: 'Mocha', price: 11000, soldOut: true),
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
    List<PastOrder> orders = const []}) async {
  tester.view.physicalSize = const Size(1170, 2532);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
  final repo = FakeRepo(menuData: menu, campaignList: const [happyHour], existing: existing)
    ..rewardList = rewards
    ..orders = orders;
  final state = AppState(brand, repo, clock: () => DateTime(2026, 10, 16, 15, 0))..start();
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
    await tester.ensureVisible(find.byKey(const Key('deleteAccount')));
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
}
