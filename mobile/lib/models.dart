// Uygulamanın kullandığı veriler. Firestore dokümanlarından (docs/VERI_MODELI.md) okunur.

int _int(Object? v, [int fallback = 0]) => v is int ? v : (v is num ? v.toInt() : fallback);
String _str(Object? v, [String fallback = '']) => v is String ? v : fallback;
bool _bool(Object? v, [bool fallback = false]) => v is bool ? v : fallback;
List<String> _strings(Object? v) => v is List ? v.whereType<String>().toList() : const [];

class Category {
  final String id;
  final String name;
  final int order;
  final bool stampEligible;
  const Category({required this.id, required this.name, this.order = 0, this.stampEligible = false});

  static Category? fromDoc(String id, Map<String, dynamic> d) {
    if (d['deleted'] == true || d['visibleInApp'] == false) return null;
    return Category(id: id, name: _str(d['name']), order: _int(d['order']), stampEligible: _bool(d['stampEligible']));
  }
}

class OptionItem {
  final String id;
  final String name;
  final int priceDelta;
  final bool available;
  const OptionItem({required this.id, required this.name, this.priceDelta = 0, this.available = true});
}

class OptionGroup {
  final String id;
  final String name;
  final bool multi;
  final bool required;
  final int min;
  final int max;
  final List<OptionItem> options;
  const OptionGroup({
    required this.id,
    required this.name,
    this.multi = false,
    this.required = false,
    this.min = 0,
    this.max = 1,
    this.options = const [],
  });

  static OptionGroup? fromDoc(String id, Map<String, dynamic> d) {
    if (d['deleted'] == true) return null;
    final opts = (d['options'] is List ? d['options'] as List : const [])
        .whereType<Map>()
        .where((o) => o['active'] != false)
        .map((o) => OptionItem(
              id: _str(o['id']),
              name: _str(o['name']),
              priceDelta: _int(o['priceDelta']),
              available: o['soldOut'] != true,
            ))
        .toList();
    final multi = d['selection'] == 'multi';
    final required = _bool(d['required']);
    return OptionGroup(
      id: id,
      name: _str(d['name']),
      multi: multi,
      required: required,
      min: d['min'] is num ? _int(d['min']) : (required ? 1 : 0),
      max: multi ? (d['max'] is num ? _int(d['max']) : opts.length) : 1,
      options: opts,
    );
  }
}

/// Tat profili (kahve önerisi): sertlik, tatlılık, asidite, gövde 1–5
class Flavor {
  final Map<String, int> dims;
  final bool milk;
  final String temperature; // hot | iced
  final List<String> notes;
  const Flavor({required this.dims, this.milk = false, this.temperature = 'hot', this.notes = const []});

  static Flavor? fromMap(Object? v) {
    if (v is! Map) return null;
    return Flavor(
      dims: {for (final k in const ['strength', 'sweetness', 'acidity', 'body']) k: _int(v[k], 3)},
      milk: _bool(v['milk']),
      temperature: _str(v['temperature'], 'hot'),
      notes: _strings(v['notes']),
    );
  }
}

const allergenLabels = {'milk': 'Süt', 'gluten': 'Gluten', 'nuts': 'Kuruyemiş', 'soy': 'Soya', 'egg': 'Yumurta'};

class Product {
  final String id;
  final String categoryId;
  final String name;
  final String description;
  final int price;
  final String? imageUrl;
  final int order;
  final bool soldOut;
  final List<String> optionGroupIds;
  final List<String> allergens;
  final int? calories;
  final int? caffeineMg;
  final List<String> tags;
  final bool? stampEligible;
  final Flavor? flavor;

  const Product({
    required this.id,
    required this.categoryId,
    required this.name,
    this.description = '',
    required this.price,
    this.imageUrl,
    this.order = 0,
    this.soldOut = false,
    this.optionGroupIds = const [],
    this.allergens = const [],
    this.calories,
    this.caffeineMg,
    this.tags = const [],
    this.stampEligible,
    this.flavor,
  });

  static Product? fromDoc(String id, Map<String, dynamic> d) {
    if (d['deleted'] == true || d['active'] == false || d['visibleInApp'] == false) return null;
    return Product(
      id: id,
      categoryId: _str(d['categoryId']),
      name: _str(d['name']),
      description: _str(d['description']),
      price: _int(d['price']),
      imageUrl: d['imageUrl'] is String ? d['imageUrl'] as String : null,
      order: _int(d['order']),
      soldOut: _bool(d['soldOut']),
      optionGroupIds: _strings(d['optionGroupIds']),
      allergens: _strings(d['allergens']),
      calories: d['calories'] is num ? _int(d['calories']) : null,
      caffeineMg: d['caffeineMg'] is num ? _int(d['caffeineMg']) : null,
      tags: _strings(d['tags']),
      stampEligible: d['stampEligible'] is bool ? d['stampEligible'] as bool : null,
      flavor: Flavor.fromMap(d['flavor']),
    );
  }
}

class MenuData {
  final List<Category> categories;
  final List<Product> products;
  final Map<String, OptionGroup> optionGroups;
  const MenuData({this.categories = const [], this.products = const [], this.optionGroups = const {}});

  List<Product> productsOf(String categoryId) => products.where((p) => p.categoryId == categoryId).toList();
  Product? product(String id) => products.where((p) => p.id == id).firstOrNull;
  Category? category(String id) => categories.where((c) => c.id == id).firstOrNull;

  /// Ürün damga kazandırır mı (ürün ayarı yoksa kategoriden)
  bool earnsStamp(Product p) => p.stampEligible ?? (category(p.categoryId)?.stampEligible ?? false);
}

class Customer {
  final String id;
  final String name;
  final String? birthDate; // 'MM-DD'
  final bool marketingConsent;
  final int stamps;
  final int lifetimeStamps;
  final String tier;
  final int visitCount;
  final String phoneMasked;

  const Customer({
    required this.id,
    required this.name,
    this.birthDate,
    this.marketingConsent = false,
    this.stamps = 0,
    this.lifetimeStamps = 0,
    this.tier = 'bronze',
    this.visitCount = 0,
    this.phoneMasked = '',
  });

  static Customer? fromDoc(String id, Map<String, dynamic>? d) {
    if (d == null || d['deleted'] == true) return null;
    final phone = _str(d['phone']);
    return Customer(
      id: id,
      name: _str(d['name']),
      birthDate: d['birthDate'] is String ? d['birthDate'] as String : null,
      marketingConsent: _bool(d['marketingConsent']),
      stamps: _int(d['stamps']),
      lifetimeStamps: _int(d['lifetimeStamps']),
      tier: _str(d['tier'], 'bronze'),
      visitCount: _int(d['visitCount']),
      phoneMasked: phone.length == 10 ? '0${phone.substring(0, 3)} *** ** ${phone.substring(8)}' : _str(d['phone']),
    );
  }

  static Customer fromView(Map<String, dynamic> d) => Customer(
        id: _str(d['id']),
        name: _str(d['name']),
        birthDate: d['birthDate'] is String ? d['birthDate'] as String : null,
        marketingConsent: _bool(d['marketingConsent']),
        stamps: _int(d['stamps']),
        lifetimeStamps: _int(d['lifetimeStamps']),
        tier: _str(d['tier'], 'bronze'),
        visitCount: _int(d['visitCount']),
        phoneMasked: _str(d['phone']),
      );
}

const rewardTypeLabels = {
  'free_drink': 'Bedava içecek',
  'birthday': 'Doğum günü hediyesi',
  'manual': 'Hediye içecek',
  'campaign': 'Kampanya hediyesi',
};

class Reward {
  final String id;
  final String type;
  final String status;
  final String expiresAt; // YYYY-MM-DD
  const Reward({required this.id, required this.type, required this.status, required this.expiresAt});

  static Reward fromDoc(String id, Map<String, dynamic> d) =>
      Reward(id: id, type: _str(d['type']), status: _str(d['status']), expiresAt: _str(d['expiresAt']));

  bool usableOn(String day) => status == 'active' && expiresAt.compareTo(day) >= 0;
  String get label => rewardTypeLabels[type] ?? 'Ödül';
}

class Tier {
  final String id;
  final String name;
  final int minStamps;
  final String perks;
  const Tier(this.id, this.name, this.minStamps, [this.perks = '']);
}

class LoyaltySettings {
  final int stampsForReward;
  final int rewardMaxValue;
  final int rewardValidDays;
  final bool birthdayReward;
  final List<Tier> tiers;
  const LoyaltySettings({
    this.stampsForReward = 10,
    this.rewardMaxValue = 9000,
    this.rewardValidDays = 60,
    this.birthdayReward = true,
    this.tiers = const [Tier('bronze', 'Bronz', 0), Tier('silver', 'Gümüş', 50), Tier('gold', 'Altın', 150)],
  });

  static LoyaltySettings fromDoc(Map<String, dynamic>? d) {
    if (d == null) return const LoyaltySettings();
    final tiers = d['tiers'] is List
        ? (d['tiers'] as List)
            .whereType<Map>()
            .map((t) => Tier(_str(t['id']), _str(t['name']), _int(t['minStamps']), _str(t['perks'])))
            .toList()
        : const LoyaltySettings().tiers;
    return LoyaltySettings(
      stampsForReward: _int(d['stampsForReward'], 10),
      rewardMaxValue: _int(d['rewardMaxValue'], 9000),
      rewardValidDays: _int(d['rewardValidDays'], 60),
      birthdayReward: _bool(d['birthdayReward'], true),
      tiers: tiers.length == 3 ? tiers : const LoyaltySettings().tiers,
    );
  }

  Tier tier(String id) => tiers.firstWhere((t) => t.id == id, orElse: () => tiers.first);
  Tier? nextTier(int lifetime) => tiers.where((t) => t.minStamps > lifetime).firstOrNull;
}

class Campaign {
  final String id;
  final String name;
  final String type;
  final int value;
  final int? nthQty;
  final List<String> bundleProductIds;
  final int? bundlePrice;
  final int stampMultiplier;
  final List<String> categoryIds;
  final List<String> productIds;
  final List<int> days;
  final String? from;
  final String? to;
  final String? startDate;
  final String? endDate;
  final String audience;
  final int minTotal;
  final String description;

  const Campaign({
    required this.id,
    required this.name,
    required this.type,
    this.value = 0,
    this.nthQty,
    this.bundleProductIds = const [],
    this.bundlePrice,
    this.stampMultiplier = 1,
    this.categoryIds = const [],
    this.productIds = const [],
    this.days = const [1, 2, 3, 4, 5, 6, 7],
    this.from,
    this.to,
    this.startDate,
    this.endDate,
    this.audience = 'all',
    this.minTotal = 0,
    this.description = '',
  });

  /// Uygulamada gösterilecek aktif kampanya; değilse null
  static Campaign? fromDoc(String id, Map<String, dynamic> d) {
    if (d['deleted'] == true || d['active'] == false || d['showInApp'] != true) return null;
    final s = d['schedule'] is Map ? d['schedule'] as Map : const {};
    final a = d['appliesTo'] is Map ? d['appliesTo'] as Map : const {};
    final b = d['bundle'] is Map ? d['bundle'] as Map : const {};
    return Campaign(
      id: id,
      name: _str(d['name']),
      type: _str(d['type']),
      value: _int(d['value']),
      nthQty: d['nthQty'] is num ? _int(d['nthQty']) : null,
      bundleProductIds: _strings(b['productIds']),
      bundlePrice: b['price'] is num ? _int(b['price']) : null,
      stampMultiplier: _int(d['stampMultiplier'], 1),
      categoryIds: _strings(a['categoryIds']),
      productIds: _strings(a['productIds']),
      days: s['days'] is List ? (s['days'] as List).whereType<num>().map((x) => x.toInt()).toList() : const [1, 2, 3, 4, 5, 6, 7],
      from: s['from'] is String ? s['from'] as String : null,
      to: s['to'] is String ? s['to'] as String : null,
      startDate: s['startDate'] is String ? s['startDate'] as String : null,
      endDate: s['endDate'] is String ? s['endDate'] as String : null,
      audience: _str(d['audience'], 'all'),
      minTotal: _int(d['minTotal']),
      description: _str(d['description']),
    );
  }
}

class AppInfo {
  final String cafeName;
  final String address;
  final String phone;
  final String instagram;
  final String hours;
  final String kvkkText;
  const AppInfo({this.cafeName = '', this.address = '', this.phone = '', this.instagram = '', this.hours = '', this.kvkkText = ''});

  static AppInfo fromDoc(Map<String, dynamic>? d) => d == null
      ? const AppInfo()
      : AppInfo(
          cafeName: _str(d['cafeName']),
          address: _str(d['address']),
          phone: _str(d['phone']),
          instagram: _str(d['instagram']),
          hours: _str(d['hours']),
          kvkkText: _str(d['kvkkText']),
        );
}

class PastItem {
  final String? productId;
  final String name;
  final int qty;
  final List<String> options;
  const PastItem({this.productId, required this.name, required this.qty, this.options = const []});
}

class PastOrder {
  final String id;
  final String no;
  final String businessDay;
  final int total;
  final int stamps;
  final List<PastItem> items;
  const PastOrder({required this.id, required this.no, required this.businessDay, required this.total, this.stamps = 0, this.items = const []});

  static PastOrder fromMap(Map<String, dynamic> d) => PastOrder(
        id: _str(d['id']),
        no: _str(d['no']),
        businessDay: _str(d['businessDay']),
        total: _int(d['total']),
        stamps: _int(d['stamps']),
        items: (d['items'] is List ? d['items'] as List : const [])
            .whereType<Map>()
            .map((i) => PastItem(
                  productId: i['productId'] is String ? i['productId'] as String : null,
                  name: _str(i['name']),
                  qty: _int(i['qty'], 1),
                  options: (i['options'] is List ? i['options'] as List : const [])
                      .whereType<Map>()
                      .map((o) => _str(o['name']))
                      .toList(),
                ))
            .toList(),
      );
}

class LoyaltyQr {
  final String qr;
  final DateTime expiresAt;
  const LoyaltyQr(this.qr, this.expiresAt);
}

/// Girişten sonra üyelik durumu
enum LinkStatus { linked, created, needsProfile }

class LinkResult {
  final LinkStatus status;
  final Customer? customer;
  const LinkResult(this.status, [this.customer]);
}

// ---------------------------------------------------------------------------
// Sipariş (11b): sepet, masa, gel-al, uygulama siparişi
// ---------------------------------------------------------------------------

class PickedOption {
  final String groupId;
  final OptionItem option;
  const PickedOption(this.groupId, this.option);
}

class CartItem {
  final Product product;
  final List<PickedOption> options;
  final int qty;
  final String note;
  const CartItem(this.product, {this.options = const [], this.qty = 1, this.note = ''});

  int get unitPrice => product.price + options.fold(0, (s, o) => s + o.option.priceDelta);
  int get total => unitPrice * qty;
  String get optionsText => options.map((o) => o.option.name).join(', ');

  /// Aynı ürün + aynı seçenekler + aynı not tek satırda toplanır
  String get key => [product.id, ...options.map((o) => '${o.groupId}/${o.option.id}'), note].join('|');

  CartItem copyWith({int? qty}) => CartItem(product, options: options, qty: qty ?? this.qty, note: note);

  Map<String, dynamic> toRequest() => {
        'productId': product.id,
        'qty': qty,
        'options': [for (final o in options) {'groupId': o.groupId, 'optionId': o.option.id}],
        if (note.isNotEmpty) 'note': note,
      };
}

class TableRef {
  final String id;
  final String token;
  final String name;
  final String label;
  const TableRef({required this.id, required this.token, this.name = '', this.label = ''});
}

class OrderingInfo {
  final bool online;
  final bool tableOrders;
  final bool pickup;
  final bool pickupBlocked;
  final int prepMinutes;
  final String cafeName;
  final TableRef? table;
  const OrderingInfo({
    this.online = false,
    this.tableOrders = false,
    this.pickup = false,
    this.pickupBlocked = false,
    this.prepMinutes = 10,
    this.cafeName = '',
    this.table,
  });

  static OrderingInfo fromMap(Map<String, dynamic> d, {String? token}) {
    final t = d['table'] is Map ? d['table'] as Map : null;
    return OrderingInfo(
      online: _bool(d['online']),
      tableOrders: _bool(d['tableOrders']),
      pickup: _bool(d['pickup']),
      pickupBlocked: _bool(d['pickupBlocked']),
      prepMinutes: _int(d['prepMinutes'], 10),
      cafeName: _str(d['cafeName']),
      table: t == null
          ? null
          : TableRef(id: _str(t['id']), token: token ?? '', name: _str(t['name']), label: _str(t['label'])),
    );
  }
}

/// Gel-al saati: hemen / dakika sonra / saat
class PickupChoice {
  final bool asap;
  final int? inMinutes;
  final DateTime? at;
  const PickupChoice.asap() : asap = true, inMinutes = null, at = null;
  const PickupChoice.inMinutes(int this.inMinutes) : asap = false, at = null;
  const PickupChoice.at(DateTime this.at) : asap = false, inMinutes = null;

  Map<String, dynamic> toRequest() => asap
      ? {'asap': true}
      : inMinutes != null
          ? {'inMinutes': inMinutes}
          : {'at': at!.toUtc().toIso8601String()};
}

const appOrderStatusLabels = {
  'pending': 'Onay bekliyor',
  'accepted': 'Onaylandı',
  'preparing': 'Hazırlanıyor',
  'ready': 'Hazır',
  'completed': 'Teslim edildi',
  'rejected': 'Reddedildi',
  'expired': 'Kafe şu an yoğun',
  'cancelled': 'İptal edildi',
  'no_show': 'Gelinmedi',
};

class AppOrderItem {
  final String name;
  final int qty;
  final List<String> options;
  final int lineTotal;
  const AppOrderItem(this.name, this.qty, this.options, this.lineTotal);
}

class AppOrder {
  final String id;
  final String kind; // table | pickup
  final String status;
  final String? reason;
  final String tableName;
  final List<AppOrderItem> items;
  final int total;
  final String? orderNo;
  final DateTime? pickupAt;
  final DateTime createdAt;
  final DateTime? expiresAt;

  const AppOrder({
    required this.id,
    required this.kind,
    required this.status,
    this.reason,
    this.tableName = '',
    this.items = const [],
    this.total = 0,
    this.orderNo,
    this.pickupAt,
    required this.createdAt,
    this.expiresAt,
  });

  static DateTime? _time(Object? v) {
    if (v is String) return DateTime.tryParse(v)?.toLocal();
    if (v is DateTime) return v.toLocal();
    try {
      return (v as dynamic)?.toDate() as DateTime?; // Firestore Timestamp
    } catch (_) {
      return null;
    }
  }

  static AppOrder fromDoc(String id, Map<String, dynamic> d) => AppOrder(
        id: id,
        kind: _str(d['kind'], 'table'),
        status: _str(d['status'], 'pending'),
        reason: d['reason'] is String ? d['reason'] as String : null,
        tableName: _str(d['tableName']),
        items: (d['items'] is List ? d['items'] as List : const [])
            .whereType<Map>()
            .map((i) => AppOrderItem(
                  _str(i['name']),
                  _int(i['qty'], 1),
                  (i['options'] is List ? i['options'] as List : const []).whereType<Map>().map((o) => _str(o['name'])).toList(),
                  _int(i['lineTotal']),
                ))
            .toList(),
        total: _int(d['total']),
        orderNo: d['orderNo'] is String ? d['orderNo'] as String : null,
        pickupAt: _time(d['pickupAt']),
        createdAt: _time(d['createdAt']) ?? DateTime.fromMillisecondsSinceEpoch(0),
        expiresAt: _time(d['expiresAt']),
      );

  /// Sunucu süresi dolanı dakikada bir kapatır; uygulama beklemeden "yoğun" gösterir
  String statusAt(DateTime now) =>
      status == 'pending' && expiresAt != null && now.isAfter(expiresAt!) ? 'expired' : status;

  bool activeAt(DateTime now) => const ['pending', 'accepted', 'preparing', 'ready'].contains(statusAt(now));

  String get place => kind == 'pickup'
      ? 'Gel-al'
      : (RegExp(r'^\d+$').hasMatch(tableName) || tableName.isEmpty ? 'Masa $tableName' : tableName);

  String get itemsText => items.map((i) => '${i.qty}× ${i.name}${i.options.isEmpty ? '' : ' (${i.options.join(', ')})'}').join(', ');
}
