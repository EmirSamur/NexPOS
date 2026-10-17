// Veri katmanı. Ekranlar yalnızca Repo arayüzünü bilir; testlerde FakeRepo kullanılır.
import 'dart:async';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:cloud_functions/cloud_functions.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:shared_preferences/shared_preferences.dart';

import '../brand.dart';
import '../models.dart';

class AuthUser {
  final String uid;
  final String? phone;
  const AuthUser(this.uid, this.phone);
}

/// Kullanıcıya gösterilecek hata
class AppError implements Exception {
  final String message;
  const AppError(this.message);
  @override
  String toString() => message;
}

abstract class Repo {
  Stream<AuthUser?> authChanges();
  Future<void> sendCode(String e164);
  Future<void> confirmCode(String code);
  Future<void> signOut();
  Future<String?> customerIdClaim({bool refresh = false});
  Future<LinkResult> link({String? name, String? birthDate, bool? marketingConsent, bool? kvkkAccepted});

  Stream<Customer?> customer(String id);
  Stream<List<Reward>> rewards(String customerId);
  Stream<MenuData> menu();
  Stream<List<Campaign>> campaigns();
  Stream<LoyaltySettings> loyaltySettings();
  Stream<AppInfo> appInfo();

  Future<LoyaltyQr> loyaltyQr();
  Future<List<PastOrder>> myOrders();
  Future<Customer> updateProfile({String? name, String? birthDate, bool clearBirthDate = false, bool? marketingConsent});
  Future<void> deleteAccount();

  Future<Set<String>> favorites();
  Future<void> setFavorite(String productId, bool on);

  // Sipariş (11b)
  Future<OrderingInfo> orderingInfo({String? tableId, String? token});
  Future<String> createAppOrder({
    required String kind,
    required List<CartItem> items,
    TableRef? table,
    PickupChoice? pickup,
    String note = '',
    int? expectedTotal,
  });
  Future<void> cancelAppOrder(String id);
  Future<bool> callTable(TableRef table, String kind); // true: yeni çağrı, false: zaten çağrılmış
  Stream<List<AppOrder>> appOrders(String customerId);
}

// =====================================================================
// Firebase
// =====================================================================

class FirebaseRepo implements Repo {
  final Brand brand;
  final FirebaseAuth auth;
  final FirebaseFirestore db;
  final FirebaseFunctions fns;
  ConfirmationResult? _webConfirmation;
  String? _verificationId;

  FirebaseRepo(this.brand)
      : auth = FirebaseAuth.instance,
        db = FirebaseFirestore.instance,
        fns = FirebaseFunctions.instanceFor(region: brand.functionsRegion);

  /// Emülatöre bağlan (geliştirme ve testler)
  Future<void> useEmulators() async {
    final h = brand.emulatorHost;
    await auth.useAuthEmulator(h, 9099);
    db.useFirestoreEmulator(h, 8080);
    fns.useFunctionsEmulator(h, 5001);
  }

  Future<T> _call<T>(String name, [Map<String, dynamic>? data]) async {
    try {
      final r = await fns.httpsCallable(name).call<Object?>(data ?? {});
      return r.data as T;
    } on FirebaseFunctionsException catch (e) {
      throw AppError(e.message ?? 'İşlem yapılamadı.');
    }
  }

  @override
  Stream<AuthUser?> authChanges() =>
      auth.authStateChanges().map((u) => u == null ? null : AuthUser(u.uid, u.phoneNumber));

  @override
  Future<void> sendCode(String e164) async {
    try {
      if (kIsWeb) {
        _webConfirmation = await auth.signInWithPhoneNumber(e164);
        return;
      }
      final sent = Completer<void>();
      await auth.verifyPhoneNumber(
        phoneNumber: e164,
        verificationCompleted: (cred) async {
          await auth.signInWithCredential(cred); // Android otomatik doğrulama
          if (!sent.isCompleted) sent.complete();
        },
        verificationFailed: (e) {
          if (!sent.isCompleted) sent.completeError(AppError(e.message ?? 'Kod gönderilemedi.'));
        },
        codeSent: (id, _) {
          _verificationId = id;
          if (!sent.isCompleted) sent.complete();
        },
        codeAutoRetrievalTimeout: (id) => _verificationId = id,
      );
      return await sent.future;
    } on FirebaseAuthException catch (e) {
      throw AppError(e.message ?? 'Kod gönderilemedi.');
    }
  }

  @override
  Future<void> confirmCode(String code) async {
    try {
      if (_webConfirmation != null) {
        await _webConfirmation!.confirm(code);
      } else if (_verificationId != null) {
        await auth.signInWithCredential(PhoneAuthProvider.credential(verificationId: _verificationId!, smsCode: code));
      } else {
        throw const AppError('Önce kod isteyin.');
      }
    } on FirebaseAuthException catch (e) {
      throw AppError(e.code == 'invalid-verification-code' ? 'Kod hatalı.' : (e.message ?? 'Giriş yapılamadı.'));
    }
  }

  @override
  Future<void> signOut() => auth.signOut();

  @override
  Future<String?> customerIdClaim({bool refresh = false}) async {
    final u = auth.currentUser;
    if (u == null) return null;
    final t = await u.getIdTokenResult(refresh);
    final id = t.claims?['customerId'];
    return id is String ? id : null;
  }

  @override
  Future<LinkResult> link({String? name, String? birthDate, bool? marketingConsent, bool? kvkkAccepted}) async {
    final r = Map<String, dynamic>.from(await _call<Map>('linkCustomer', {
      'name': ?name,
      'birthDate': ?birthDate,
      'marketingConsent': ?marketingConsent,
      'kvkkAccepted': ?kvkkAccepted,
    }));
    if (r['status'] == 'needsProfile') return const LinkResult(LinkStatus.needsProfile);
    await auth.currentUser?.getIdToken(true); // yeni customerId yetkisi
    return LinkResult(r['status'] == 'created' ? LinkStatus.created : LinkStatus.linked,
        Customer.fromView(Map<String, dynamic>.from(r['customer'] as Map)));
  }

  @override
  Stream<Customer?> customer(String id) =>
      db.doc('customers/$id').snapshots().map((s) => Customer.fromDoc(s.id, s.data()));

  @override
  Stream<List<Reward>> rewards(String customerId) => db
      .collection('rewards')
      .where('customerId', isEqualTo: customerId)
      .snapshots()
      .map((q) => q.docs.map((d) => Reward.fromDoc(d.id, d.data())).toList());

  @override
  Stream<MenuData> menu() {
    // Üç koleksiyon birleşir; biri değişince menü yeniden kurulur (tükendi anında yansır)
    late StreamController<MenuData> out;
    final subs = <StreamSubscription>[];
    var cats = <Category>[];
    var prods = <Product>[];
    var groups = <String, OptionGroup>{};
    final seen = <int>{};
    void emit(int part) {
      seen.add(part);
      if (seen.length == 3) out.add(MenuData(categories: cats, products: prods, optionGroups: groups));
    }

    out = StreamController<MenuData>(
      onListen: () {
        subs.add(db.collection('categories').snapshots().listen((q) {
          cats = q.docs.map((d) => Category.fromDoc(d.id, d.data())).whereType<Category>().toList()
            ..sort((a, b) => a.order.compareTo(b.order));
          emit(0);
        }, onError: out.addError));
        subs.add(db.collection('products').snapshots().listen((q) {
          prods = q.docs.map((d) => Product.fromDoc(d.id, d.data())).whereType<Product>().toList()
            ..sort((a, b) => a.order != b.order ? a.order.compareTo(b.order) : a.name.compareTo(b.name));
          emit(1);
        }, onError: out.addError));
        subs.add(db.collection('optionGroups').snapshots().listen((q) {
          groups = {
            for (final d in q.docs)
              d.id: ?OptionGroup.fromDoc(d.id, d.data())
          };
          emit(2);
        }, onError: out.addError));
      },
      onCancel: () async {
        for (final s in subs) {
          await s.cancel();
        }
      },
    );
    return out.stream;
  }

  @override
  Stream<List<Campaign>> campaigns() => db
      .collection('campaigns')
      .snapshots()
      .map((q) => q.docs.map((d) => Campaign.fromDoc(d.id, d.data())).whereType<Campaign>().toList());

  @override
  Stream<LoyaltySettings> loyaltySettings() =>
      db.doc('settings/loyalty').snapshots().map((s) => LoyaltySettings.fromDoc(s.data()));

  @override
  Stream<AppInfo> appInfo() => db.doc('settings/app').snapshots().map((s) => AppInfo.fromDoc(s.data()));

  @override
  Future<LoyaltyQr> loyaltyQr() async {
    final r = await _call<Map>('getLoyaltyQr');
    return LoyaltyQr(r['qr'] as String, DateTime.parse(r['expiresAt'] as String));
  }

  @override
  Future<List<PastOrder>> myOrders() async {
    final r = await _call<List>('myOrders');
    return r.whereType<Map>().map((m) => PastOrder.fromMap(Map<String, dynamic>.from(m))).toList();
  }

  @override
  Future<Customer> updateProfile({String? name, String? birthDate, bool clearBirthDate = false, bool? marketingConsent}) async {
    final r = await _call<Map>('updateMyProfile', {
      'name': ?name,
      'birthDate': ?birthDate,
      if (clearBirthDate) 'birthDate': null,
      'marketingConsent': ?marketingConsent,
    });
    return Customer.fromView(Map<String, dynamic>.from(r['customer'] as Map));
  }

  @override
  Future<void> deleteAccount() async {
    await _call<Map>('deleteMyAccount');
    await auth.signOut();
  }

  @override
  Future<OrderingInfo> orderingInfo({String? tableId, String? token}) async {
    final r = await _call<Map>('appOrderingInfo', {'tableId': ?tableId, 't': ?token});
    return OrderingInfo.fromMap(Map<String, dynamic>.from(r), token: token);
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
    final r = await _call<Map>('createAppOrder', {
      'kind': kind,
      'items': [for (final i in items) i.toRequest()],
      if (table != null) 'tableId': table.id,
      if (table != null) 't': table.token,
      if (pickup != null) 'pickup': pickup.toRequest(),
      if (note.isNotEmpty) 'note': note,
      'expectedTotal': ?expectedTotal,
    });
    return r['id'] as String;
  }

  @override
  Future<void> cancelAppOrder(String id) => _call<Map>('cancelMyAppOrder', {'id': id});

  @override
  Future<bool> callTable(TableRef table, String kind) async {
    final r = await _call<Map>('callTable', {'tableId': table.id, 't': table.token, 'kind': kind});
    return r['already'] != true;
  }

  @override
  Stream<List<AppOrder>> appOrders(String customerId) => db
      .collection('appOrders')
      .where('customerId', isEqualTo: customerId)
      .snapshots()
      .map((q) => q.docs.map((d) => AppOrder.fromDoc(d.id, d.data())).toList()
        ..sort((a, b) => b.createdAt.compareTo(a.createdAt)));

  @override
  Future<Set<String>> favorites() async =>
      (await SharedPreferences.getInstance()).getStringList('favorites')?.toSet() ?? {};

  @override
  Future<void> setFavorite(String productId, bool on) async {
    final p = await SharedPreferences.getInstance();
    final set = p.getStringList('favorites')?.toSet() ?? {};
    on ? set.add(productId) : set.remove(productId);
    await p.setStringList('favorites', set.toList());
  }
}
