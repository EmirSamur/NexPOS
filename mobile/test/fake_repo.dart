import 'dart:async';

import 'package:kafe_app/data/repo.dart';
import 'package:kafe_app/models.dart';

/// Bellekte çalışan Repo: ekran testleri için (sunucu davranışı firebase/tests'te ayrıca test edilir).
class FakeRepo implements Repo {
  final _auth = StreamController<AuthUser?>.broadcast();
  final _customer = StreamController<Customer?>.broadcast();
  final _rewards = StreamController<List<Reward>>.broadcast();
  final _orders = StreamController<List<AppOrder>>.broadcast();
  AuthUser? user;
  String? claim;
  String? sentTo;
  Customer? existing; // kasada açılmış üyelik (aynı telefonla bağlanır)
  Customer? current;
  List<Reward> rewardList = [];
  List<PastOrder> orders = [];
  MenuData menuData;
  List<Campaign> campaignList;
  LoyaltySettings loyalty;
  AppInfo info;
  final Set<String> favs = {};
  bool deleted = false;
  int qrCount = 0;
  OrderingInfo ordering = const OrderingInfo(online: true, tableOrders: true, pickup: true, cafeName: 'Velvet Kafe');
  final tables = {'t4': 'tok4'};
  final sent = <Map<String, dynamic>>[];
  final calls = <String>[];
  List<AppOrder> orderList = [];

  FakeRepo({
    this.menuData = const MenuData(),
    this.campaignList = const [],
    this.loyalty = const LoyaltySettings(),
    this.info = const AppInfo(cafeName: 'Velvet Kafe'),
    this.existing,
  });

  /// İlk değeri hemen, sonrakileri denetleyiciden veren akış (iptal edilebilir)
  Stream<T> _seeded<T>(T Function() first, StreamController<T> source) {
    late StreamController<T> out;
    StreamSubscription<T>? sub;
    out = StreamController<T>(
      onListen: () {
        out.add(first());
        sub = source.stream.listen(out.add);
      },
      onCancel: () => sub?.cancel(),
    );
    return out.stream;
  }

  @override
  Stream<AuthUser?> authChanges() => _seeded(() => user, _auth);

  @override
  Future<void> sendCode(String e164) async => sentTo = e164;

  @override
  Future<void> confirmCode(String code) async {
    if (code != '123456') throw const AppError('Kod hatalı.');
    user = AuthUser('u1', sentTo);
    _auth.add(user);
  }

  @override
  Future<void> signOut() async {
    user = null;
    claim = null;
    _auth.add(null);
  }

  @override
  Future<String?> customerIdClaim({bool refresh = false}) async => claim;

  @override
  Future<LinkResult> link({String? name, String? birthDate, bool? marketingConsent, bool? kvkkAccepted}) async {
    if (existing != null) {
      current = existing;
      claim = existing!.id;
      return LinkResult(LinkStatus.linked, existing);
    }
    if (name == null) return const LinkResult(LinkStatus.needsProfile);
    if (kvkkAccepted != true) throw const AppError('Aydınlatma metni onaylanmalıdır.');
    current = Customer(id: 'new1', name: name, birthDate: birthDate, marketingConsent: marketingConsent ?? false);
    claim = 'new1';
    return LinkResult(LinkStatus.created, current);
  }

  @override
  Stream<Customer?> customer(String id) => _seeded(() => current, _customer);

  void pushCustomer(Customer c) {
    current = c;
    _customer.add(c);
  }

  @override
  Stream<List<Reward>> rewards(String customerId) => _seeded(() => rewardList, _rewards);

  @override
  Stream<MenuData> menu() => Stream.value(menuData);
  @override
  Stream<List<Campaign>> campaigns() => Stream.value(campaignList);
  @override
  Stream<LoyaltySettings> loyaltySettings() => Stream.value(loyalty);
  @override
  Stream<AppInfo> appInfo() => Stream.value(info);

  @override
  Future<LoyaltyQr> loyaltyQr() async {
    qrCount++;
    return LoyaltyQr('KAFE:LOYALTY:token$qrCount', DateTime.now().add(const Duration(seconds: 60)));
  }

  @override
  Future<List<PastOrder>> myOrders() async => orders;

  @override
  Future<Customer> updateProfile({String? name, String? birthDate, bool clearBirthDate = false, bool? marketingConsent}) async {
    final c = current!;
    current = Customer(
      id: c.id,
      name: name ?? c.name,
      birthDate: clearBirthDate ? null : (birthDate ?? c.birthDate),
      marketingConsent: marketingConsent ?? c.marketingConsent,
      stamps: c.stamps,
      lifetimeStamps: c.lifetimeStamps,
      tier: c.tier,
      phoneMasked: c.phoneMasked,
    );
    return current!;
  }

  @override
  Future<void> deleteAccount() async {
    deleted = true;
    await signOut();
  }

  @override
  Future<OrderingInfo> orderingInfo({String? tableId, String? token}) async {
    if (tableId != null && tables[tableId] != token) throw const AppError("Masa QR'ı geçersiz.");
    return OrderingInfo(
      online: ordering.online,
      tableOrders: ordering.tableOrders,
      pickup: ordering.pickup,
      prepMinutes: ordering.prepMinutes,
      cafeName: ordering.cafeName,
      table: tableId == null ? null : TableRef(id: tableId, token: token!, name: '4', label: 'Masa 4'),
    );
  }

  @override
  Future<String> createAppOrder({
    required String kind,
    required List<CartItem> items,
    TableRef? table,
    PickupChoice? pickup,
    String note = '',
    int? expectedTotal,
  }) async {
    final id = 'ao${sent.length + 1}';
    sent.add({
      'kind': kind,
      'items': [for (final i in items) i.toRequest()],
      'tableId': table?.id,
      'pickup': pickup?.toRequest(),
      'note': note,
      'expectedTotal': expectedTotal,
    });
    pushOrders([
      AppOrder(
        id: id,
        kind: kind,
        status: 'pending',
        tableName: table?.name ?? '',
        total: expectedTotal ?? 0,
        items: [for (final i in items) AppOrderItem(i.product.name, i.qty, [i.optionsText], i.total)],
        createdAt: DateTime.now(),
        expiresAt: DateTime.now().add(const Duration(minutes: 2)),
      ),
      ...orderList,
    ]);
    return id;
  }

  void pushOrders(List<AppOrder> list) {
    orderList = list;
    _orders.add(list);
  }

  @override
  Future<void> cancelAppOrder(String id) async {}

  @override
  Future<bool> callTable(TableRef table, String kind) async {
    final fresh = !calls.contains(kind);
    calls.add(kind);
    return fresh;
  }

  @override
  Stream<List<AppOrder>> appOrders(String customerId) => _seeded(() => orderList, _orders);

  @override
  Future<Set<String>> favorites() async => {...favs};
  @override
  Future<void> setFavorite(String productId, bool on) async => on ? favs.add(productId) : favs.remove(productId);
}
