// Uygulama durumu: giriş/üyelik aşaması, menü, kampanyalar, müşterinin kartı ve ödülleri.
import 'dart:async';

import 'package:flutter/widgets.dart';

import 'brand.dart';
import 'data/repo.dart';
import 'logic.dart';
import 'models.dart';
import 'quiz.dart';

enum Phase { loading, signedOut, needsProfile, ready }

class AppState extends ChangeNotifier {
  final Brand brand;
  final Repo repo;
  final DateTime Function() clock;

  Phase phase = Phase.loading;
  AuthUser? user;
  String? customerId;
  Customer? customer;
  List<Reward> rewards = const [];
  MenuData menu = const MenuData();
  bool menuLoaded = false;
  List<Campaign> campaigns = const [];
  LoyaltySettings loyalty = const LoyaltySettings();
  AppInfo info = const AppInfo();
  Set<String> favorites = {};
  String? error;

  // Sipariş (11b)
  List<CartItem> cart = const [];
  TableRef? table; // masadaki QR ile açıldıysa
  String? tableError;
  OrderingInfo? ordering;
  List<AppOrder> appOrders = const [];
  VoidCallback? requestLogin; // misafir sipariş vermek isterse giriş ekranı (Root bağlar)
  String? notice; // tek seferlik bildirim: "Siparişin hazır" gibi (ekran gösterip temizler)
  final _lastStatus = <String, String>{};

  // Kahve önerisi ve bildirimler (11c)
  Quiz quiz = defaultQuiz;
  Set<String>? triedIds; // üyenin daha önce sipariş ettiği ürünler (öneride "henüz denemedin")
  String? lastRecommendationId;
  bool pushEnabled = false;

  final _subs = <StreamSubscription>[];
  final _customerSubs = <StreamSubscription>[];

  AppState(this.brand, this.repo, {DateTime Function()? clock}) : clock = clock ?? DateTime.now;

  String get today => businessDay(clock());
  bool get signedIn => phase == Phase.ready;

  List<Reward> get usableRewards => rewards.where((r) => r.usableOn(today)).toList()
    ..sort((a, b) => a.expiresAt.compareTo(b.expiresAt));

  void start() {
    _subs.add(repo.menu().listen((m) {
      menu = m;
      menuLoaded = true;
      notifyListeners();
    }, onError: _onError));
    _subs.add(repo.campaigns().listen((c) => _set(() => campaigns = c), onError: _onError));
    _subs.add(repo.loyaltySettings().listen((l) => _set(() => loyalty = l), onError: _onError));
    _subs.add(repo.appInfo().listen((i) => _set(() => info = i), onError: _onError));
    _subs.add(repo.authChanges().listen(_onAuth, onError: _onError));
    repo.favorites().then((f) => _set(() => favorites = f));
    if (table == null) refreshOrdering();
    _subs.add(repo.quiz().listen((q) => _set(() => quiz = q), onError: (_) {}));
    _subs.add(repo.pushMessages().listen((m) => _set(() => notice = m.$2.isEmpty ? m.$1 : '${m.$1} — ${m.$2}'),
        onError: (_) {}));
  }

  void _set(VoidCallback fn) {
    fn();
    notifyListeners();
  }

  void _onError(Object e) => _set(() => error = '$e');

  Future<void> _onAuth(AuthUser? u) async {
    user = u;
    await _dropCustomer();
    if (u == null) {
      _set(() => phase = Phase.signedOut);
      return;
    }
    try {
      final claim = await repo.customerIdClaim();
      if (claim != null) {
        _attach(claim);
        return;
      }
      final r = await repo.link();
      if (r.status == LinkStatus.needsProfile) {
        _set(() => phase = Phase.needsProfile);
      } else {
        customer = r.customer;
        _attach(r.customer!.id);
      }
    } catch (e) {
      _set(() {
        error = '$e';
        phase = Phase.signedOut;
      });
    }
  }

  void _attach(String id) {
    customerId = id;
    phase = Phase.ready;
    _customerSubs.add(repo.customer(id).listen((c) {
      if (c == null) return; // silinmiş hesap: çıkışta temizlenir
      _set(() => customer = c);
    }, onError: _onError));
    _customerSubs.add(repo.rewards(id).listen((r) => _set(() => rewards = r), onError: _onError));
    _customerSubs.add(repo.appOrders(id).listen(_onAppOrders, onError: _onError));
    notifyListeners();
    refreshOrdering(); // gel-al bu müşteriye kapalı olabilir
    repo.myOrders().then((list) => _set(() => triedIds = {
          for (final o in list)
            for (final i in o.items) ?i.productId,
        }), onError: (_) {});
    repo.enablePush(ask: false).then((on) => _set(() => pushEnabled = on), onError: (_) {});
  }

  /// "Bana öner": en uyumlu 3 ürün; üye ise öneri kaydedilir (sipariş edilirse "tuttu" sayılır)
  Future<List<Recommendation>> runQuiz(Map<String, String> answers) async {
    final now = clock();
    final recs = recommend(menu.products, quiz, answers, hour: now.hour, triedIds: triedIds);
    lastRecommendationId = null;
    if (signedIn && recs.isNotEmpty) {
      try {
        lastRecommendationId = await repo.logRecommendation([for (final r in recs) r.productId], answers);
      } catch (_) {
        // Kayıt olmasa da öneri gösterilir
      }
    }
    return recs;
  }

  /// Telefon bildirimlerini aç (izin sorar)
  Future<bool> turnOnPush() async {
    final on = await repo.enablePush();
    _set(() => pushEnabled = on);
    return on;
  }

  void _onAppOrders(List<AppOrder> list) {
    for (final o in list) {
      final before = _lastStatus[o.id];
      if (before != null && before != o.status) {
        final no = o.orderNo != null ? ' (${o.orderNo})' : '';
        notice = switch (o.status) {
          'accepted' => '✓ ${o.place}: siparişin onaylandı, hazırlanıyor.',
          'ready' => o.kind == 'pickup' ? '🔔 Siparişin hazır$no — gelip alabilirsin.' : '🔔 Siparişin hazır$no, birazdan masanda.',
          'rejected' => 'Sipariş alınamadı: ${o.reason ?? ''}',
          'expired' => 'Kafe şu an yoğun; siparişin onaylanamadı.',
          _ => notice,
        };
      }
      _lastStatus[o.id] = o.status;
    }
    _set(() => appOrders = list);
  }

  List<AppOrder> get activeOrders => appOrders.where((o) => o.activeAt(clock())).toList();

  // ------------------------------------------------------------ sipariş
  Future<void> refreshOrdering() async {
    try {
      final info = await repo.orderingInfo(tableId: table?.id, token: table?.token);
      _set(() => ordering = info);
    } catch (e) {
      _set(() => ordering = null);
    }
  }

  /// Masadaki QR okutuldu (web adresi ya da uygulama bağlantısı)
  Future<void> openTable(String tableId, String token) async {
    try {
      final info = await repo.orderingInfo(tableId: tableId, token: token);
      _set(() {
        ordering = info;
        table = info.table;
        tableError = null;
      });
    } on AppError catch (e) {
      _set(() => tableError = e.message);
    }
  }

  void leaveTable() {
    table = null;
    refreshOrdering();
  }

  bool get canOrderAtTable => table != null && (ordering?.tableOrders ?? false);
  bool get canPickup => ordering?.pickup ?? false;
  bool get canOrder => canOrderAtTable || canPickup;
  int get cartCount => cart.fold(0, (s, i) => s + i.qty);

  void addItem(CartItem item) => _set(() => cart = addToCart(cart, item));

  void setQty(String key, int qty) => _set(() => cart = [
        for (final c in cart)
          if (c.key != key) c else if (qty > 0) c.copyWith(qty: qty.clamp(1, 20)),
      ]);

  void clearCart() => _set(() => cart = const []);

  /// Sepeti gönderir; isteğin kimliğini döndürür
  Future<String> submitOrder({required String kind, PickupChoice? pickup, String note = ''}) async {
    final id = await repo.createAppOrder(
      kind: kind,
      items: cart,
      table: kind == 'table' ? table : null,
      pickup: pickup,
      note: note,
      expectedTotal: cartTotal(cart),
      recommendationId: lastRecommendationId,
    );
    _set(() => cart = const []);
    return id;
  }

  Future<bool> callTable(String kind) => repo.callTable(table!, kind);

  String? takeNotice() {
    final n = notice;
    notice = null;
    return n;
  }

  Future<void> _dropCustomer() async {
    // Liste önce boşaltılır: çıkış olayı ve hesap silme aynı anda çağırabilir
    final subs = [..._customerSubs];
    _customerSubs.clear();
    customerId = null;
    customer = null;
    rewards = const [];
    appOrders = const [];
    _lastStatus.clear();
    for (final s in subs) {
      await s.cancel();
    }
  }

  /// Profil formu: üyelik açılır (KVKK onayıyla)
  Future<void> completeProfile({required String name, String? birthDate, required bool marketingConsent}) async {
    final r = await repo.link(name: name, birthDate: birthDate, marketingConsent: marketingConsent, kvkkAccepted: true);
    customer = r.customer;
    _attach(r.customer!.id);
  }

  Future<void> updateProfile({String? name, String? birthDate, bool clearBirthDate = false, bool? marketingConsent}) async {
    final c = await repo.updateProfile(
        name: name, birthDate: birthDate, clearBirthDate: clearBirthDate, marketingConsent: marketingConsent);
    _set(() => customer = c);
  }

  Future<void> signOut() => repo.signOut();

  Future<void> deleteAccount() async {
    await repo.deleteAccount();
    await _dropCustomer();
    _set(() => phase = Phase.signedOut);
  }

  Future<void> toggleFavorite(String productId) async {
    final on = !favorites.contains(productId);
    _set(() => on ? favorites.add(productId) : favorites.remove(productId));
    await repo.setFavorite(productId, on);
  }

  @override
  void dispose() {
    for (final s in [..._subs, ..._customerSubs]) {
      s.cancel();
    }
    super.dispose();
  }
}

class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);

  static AppState of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;
  static AppState read(BuildContext context) => context.getInheritedWidgetOfExactType<AppScope>()!.notifier!;
}
