// Kafe müşteri uygulaması (NexPOS, 11. ekran).
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform, kIsWeb, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'brand.dart';
import 'data/repo.dart';
import 'logic.dart';
import 'state.dart';
import 'ui/policy.dart';
import 'ui/shell.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final brand = await Brand.load();
  final f = brand.firebase;
  final android = !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  await Firebase.initializeApp(
    options: FirebaseOptions(
      apiKey: f['apiKey'] ?? '',
      appId: (android ? f['androidAppId'] : null) ?? f['appId'] ?? '',
      messagingSenderId: f['messagingSenderId'] ?? '',
      projectId: f['projectId'] ?? '',
      authDomain: f['authDomain'],
      storageBucket: f['storageBucket'],
    ),
  );
  final repo = FirebaseRepo(brand);
  if (brand.useEmulator) await repo.useEmulators();
  final state = AppState(brand, repo);
  // Masadaki QR web adresi: https://<kafe>/masa/<masaId>?t=<anahtar>
  final link = parseTableLink(Uri.base);
  if (link != null) await state.openTable(link.$1, link.$2);
  // Mağaza için herkese açık sayfalar: /gizlilik ve /hesap-sil
  final page = Uri.base.pathSegments.where((x) => x.isNotEmpty).firstOrNull;
  runApp(KafeApp(state: state..start(), page: page == 'gizlilik' || page == 'hesap-sil' ? page : null));
}

class KafeApp extends StatelessWidget {
  final AppState state;
  final String? page; // gizlilik | hesap-sil
  const KafeApp({super.key, required this.state, this.page});

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: state,
      child: MaterialApp(
        title: state.brand.appName,
        debugShowCheckedModeBanner: false,
        theme: state.brand.theme(),
        locale: const Locale('tr'),
        supportedLocales: const [Locale('tr')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: page == null ? const Root() : PolicyPage(deletion: page == 'hesap-sil'),
      ),
    );
  }
}
