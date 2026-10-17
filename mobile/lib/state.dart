// Uygulama durumu: giriş/üyelik aşaması, menü, kampanyalar, müşterinin kartı ve ödülleri.
import 'dart:async';

import 'package:flutter/widgets.dart';

import 'brand.dart';
import 'data/repo.dart';
import 'logic.dart';
import 'models.dart';

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
    notifyListeners();
  }

  Future<void> _dropCustomer() async {
    // Liste önce boşaltılır: çıkış olayı ve hesap silme aynı anda çağırabilir
    final subs = [..._customerSubs];
    _customerSubs.clear();
    customerId = null;
    customer = null;
    rewards = const [];
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
