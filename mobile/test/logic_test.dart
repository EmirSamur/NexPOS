// Saf hesaplar. Kampanya geçerliliği ve doğum günü kuralları sunucuyla ortak senaryolardan
// (firebase/functions/test/*_vectors.json) test edilir: JS, Python ve Dart aynı sonucu verir.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:kafe_app/logic.dart';
import 'package:kafe_app/models.dart';
import 'package:kafe_app/quiz.dart';

Map<String, dynamic> _vectors(String name) =>
    jsonDecode(File('../firebase/functions/test/$name').readAsStringSync()) as Map<String, dynamic>;

/// '2026-10-16T15:30:00+03:00' → yerel saat (terminal gibi ilk 19 karakter)
DateTime _local(String iso) => DateTime.parse(iso.substring(0, 19));

void main() {
  test('para biçimi', () {
    expect(formatTl(9500), '95,00 ₺');
    expect(formatTl(125000), '1.250,00 ₺');
    expect(formatTl(-4750), '-47,50 ₺');
    expect(formatTl(100000000), '1.000.000,00 ₺');
  });

  test('telefon', () {
    expect(toE164('0532 123 45 67'), '+905321234567');
    expect(toE164('+90 (532) 123-45-67'), '+905321234567');
    expect(toE164('532 123 45'), isNull);
    expect(toE164('1321234567'), isNull);
  });

  test('iş günü 05:00\'te döner', () {
    expect(businessDay(DateTime(2026, 10, 17, 2, 30)), '2026-10-16');
    expect(businessDay(DateTime(2026, 10, 17, 5, 0)), '2026-10-17');
  });

  group('kampanya geçerliliği (ortak senaryolar)', () {
    final cases = _vectors('campaign_vectors.json')['live'] as List;
    for (final c in cases.cast<Map<String, dynamic>>()) {
      test(c['name'] as String, () {
        final doc = Map<String, dynamic>.from(c['campaign'] as Map)..['showInApp'] = true;
        final campaign = Campaign.fromDoc('x', doc);
        final customer = c['customer'] as Map?;
        final live = campaign != null && isLive(campaign, _local(c['at'] as String), tier: customer?['tier'] as String?);
        expect(live, c['expect']);
      });
    }
  });

  group('doğum günü haftası (ortak senaryolar)', () {
    final cases = (jsonDecode(File('../firebase/functions/test/loyalty_vectors.json').readAsStringSync()) as List)
        .cast<Map<String, dynamic>>()
        .where((c) => c['fn'] == 'isBirthdayWeek');
    for (final c in cases) {
      test(c['name'] as String, () {
        final args = c['args'] as List;
        expect(isBirthdayWeek(args[0] as String?, DateTime.parse(args[1] as String)), c['expect']);
      });
    }
  });

  test('ürün kartı kampanyası: en çok indirim, X. ürün ve menü etiketi', () {
    const latte = Product(id: 'latte', categoryId: 'kahve', name: 'Latte', price: 9500);
    const kek = Product(id: 'kek', categoryId: 'tatli', name: 'Kek', price: 7000);
    final now = DateTime(2026, 10, 16, 15, 0); // Cuma
    const hh = Campaign(id: 'hh', name: 'Happy Hour', type: 'percent', value: 20, categoryIds: ['kahve'], from: '14:00', to: '17:00');
    const gold = Campaign(id: 'g', name: 'Altın %25', type: 'percent', value: 25, audience: 'gold');
    const nth = Campaign(id: 'n', name: '2. kahve', type: 'nth', value: 50, nthQty: 2, categoryIds: ['kahve']);
    const menu = Campaign(id: 'm', name: 'Öğrenci Menüsü', type: 'bundle', bundleProductIds: ['latte', 'kek'], bundlePrice: 12000);
    expect(productPromo(latte, [hh, gold], now), (label: 'Happy Hour', price: 7600));
    expect(productPromo(latte, [hh, gold], now, tier: 'gold'), (label: 'Altın %25', price: 7125));
    expect(productPromo(latte, [hh], DateTime(2026, 10, 16, 18, 0)), isNull);
    expect(productPromo(latte, [nth], now)?.label, '2. ürün %50');
    expect(productPromo(kek, [menu], now)?.label, 'Öğrenci Menüsü: 120,00 ₺');
    expect(campaignSummary(const Campaign(id: 'x', name: 'x', type: 'nth', value: 100, nthQty: 3)), '3 al 2 öde');
    expect(scheduleText(hh), 'Her gün 14:00–17:00');
  });

  test('model okuma: gizli/silinmiş ürün ve kategori elenir, ödül süresi', () {
    expect(Product.fromDoc('p', {'name': 'X', 'price': 100, 'visibleInApp': false}), isNull);
    expect(Product.fromDoc('p', {'name': 'X', 'price': 100, 'deleted': true}), isNull);
    expect(Category.fromDoc('c', {'name': 'X', 'deleted': true}), isNull);
    expect(Campaign.fromDoc('c', {'name': 'X', 'type': 'percent', 'showInApp': false}), isNull);
    final c = Customer.fromDoc('c1', {'name': 'Ayşe', 'phone': '5321112233', 'stamps': 3});
    expect(c!.phoneMasked, '0532 *** ** 33');
    const r = Reward(id: 'r', type: 'free_drink', status: 'active', expiresAt: '2026-10-16');
    expect(r.usableOn('2026-10-16'), isTrue);
    expect(r.usableOn('2026-10-17'), isFalse);
    expect(birthdayLabel('10-18'), '18 Ekim');
  });

  test('masa QR adresi', () {
    expect(parseTableLink(Uri.parse('https://kafe.web.app/masa/t4?t=abc')), ('t4', 'abc'));
    expect(parseTableLink(Uri.parse('https://kafe.web.app/masa/t4')), isNull);
    expect(parseTableLink(Uri.parse('https://kafe.web.app/')), isNull);
  });

  test('seçenek kuralı ve sepet birleştirme', () {
    const g = OptionGroup(id: 'e', name: 'Ekstra', multi: true, max: 2);
    const size = OptionGroup(id: 's', name: 'Boy', required: true, min: 1);
    expect(optionProblem(size, 0), 'Boy seçin');
    expect(optionProblem(g, 3), 'Ekstra: en fazla 2 seçim');
    expect(optionProblem(g, 0), isNull);
    const p = Product(id: 'latte', categoryId: 'k', name: 'Latte', price: 9500);
    const oat = PickedOption('sut', OptionItem(id: 'oat', name: 'Yulaf', priceDelta: 1500));
    var cart = addToCart(const [], const CartItem(p, options: [oat]));
    cart = addToCart(cart, const CartItem(p, options: [oat], qty: 2));
    cart = addToCart(cart, const CartItem(p));
    expect(cart.map((c) => c.qty), [3, 1]);
    expect(cartTotal(cart), 3 * 11000 + 9500);
    expect(cart.first.toRequest(), {'productId': 'latte', 'qty': 3, 'options': [{'groupId': 'sut', 'optionId': 'oat'}]});
  });

  test('onay süresi dolan istek "yoğun" görünür', () {
    final o = AppOrder(id: 'a', kind: 'table', status: 'pending', tableName: '4',
        createdAt: DateTime(2026, 10, 16, 15), expiresAt: DateTime(2026, 10, 16, 15, 2));
    expect(o.statusAt(DateTime(2026, 10, 16, 15, 1)), 'pending');
    expect(o.statusAt(DateTime(2026, 10, 16, 15, 3)), 'expired');
    expect(o.activeAt(DateTime(2026, 10, 16, 15, 3)), isFalse);
    expect(o.place, 'Masa 4');
  });

  group('kahve önerisi (quiz_vectors.json)', () {
    final v = _vectors('quiz_vectors.json');
    final quiz = Quiz.fromDoc(v['quiz'] as Map<String, dynamic>);
    final products = [
      for (final p in (v['products'] as List).cast<Map>())
        Product(
          id: p['id'] as String,
          categoryId: 'k',
          name: p['name'] as String,
          price: 0,
          soldOut: p['soldOut'] == true,
          caffeineMg: p['caffeineMg'] as int?,
          flavor: Flavor.fromMap(p['flavor']),
        ),
    ];
    test('hazır sorular sunucuyla aynı', () {
      expect(quiz.questions.map((q) => '${q.id}:${q.answers.map((a) => '${a.id}${a.weights}${a.notes}${a.milk}${a.temperature}').join(',')}'),
          defaultQuiz.questions.map((q) => '${q.id}:${q.answers.map((a) => '${a.id}${a.weights}${a.notes}${a.milk}${a.temperature}').join(',')}'));
    });
    for (final c in (v['cases'] as List).cast<Map>()) {
      test(c['name'] as String, () {
        final without = (c['without'] as List).cast<String>();
        final ctx = c['ctx'] as Map;
        final answers = (c['answers'] as Map).map((k, v) => MapEntry('$k', '$v'));
        final prof = profileFrom(quiz, answers);
        expect(prof.target, (c['profile'] as Map)['target']);
        final out = recommend(products.where((p) => !without.contains(p.id)).toList(), quiz, answers,
            hour: ctx['hour'] as int? ?? 12,
            hotDay: ctx['hotDay'] == true,
            triedIds: ctx['triedIds'] == null ? null : (ctx['triedIds'] as List).cast<String>().toSet());
        expect([for (final r in out) {'productId': r.productId, 'score': r.score, 'reasons': r.reasons}], c['expect']);
      });
    }
  });
}
